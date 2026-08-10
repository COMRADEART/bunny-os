# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistence, lifecycle and the four maintenance operations.

§6's claim is that opening an application reconnects to what is already there.
That is a claim about identity and about the filesystem, and both are checkable
here. §8's claim is that a person can inspect, revoke, clear, reset, delete and
uninstall — six operations whose difference from each other is the whole reason
the layout has seven directories rather than one.
"""

from __future__ import annotations

import unittest

import trust
from capsules.errors import CapsuleSchemaError, CapsuleStateError
from capsules.identity import capsule_identity
from capsules.layout import CLEARABLE, DELETABLE, RESETTABLE
from capsules.lifecycle import STATES, TRANSITIONS, transition_allowed

from tests.capsule_support import World, manifest_for


class IdentityTests(unittest.TestCase):
    def test_an_application_id_can_never_become_a_path(self) -> None:
        for hostile in ("../../etc/passwd", "/etc/passwd", "a/b", "..", "", "-leading", "no-dots"):
            with self.assertRaises(CapsuleSchemaError, msg=hostile):
                capsule_identity(hostile)

    def test_the_directory_name_contains_no_separator_or_dotdot(self) -> None:
        identity = capsule_identity("org.example.Photo-Editor")
        self.assertNotIn("/", identity.directory_name)
        self.assertNotIn("\\", identity.directory_name)
        self.assertNotIn("..", identity.directory_name)
        self.assertFalse(identity.directory_name.startswith("-"))

    def test_two_ids_that_sanitise_alike_get_different_directories(self) -> None:
        """The digest is over the id as given. Hashing the slug instead would
        reintroduce the collision it exists to prevent."""
        first = capsule_identity("org.example.Photo_Editor")
        second = capsule_identity("org.example.Photo-Editor")
        self.assertEqual(first.slug, second.slug)
        self.assertNotEqual(first.directory_name, second.directory_name)

    def test_the_portal_identity_is_the_application_id_unchanged(self) -> None:
        self.assertEqual(capsule_identity("org.gimp.GIMP").portal_id, "org.gimp.GIMP")


class LifecycleTableTests(unittest.TestCase):
    def test_a_capsule_cannot_go_straight_from_running_to_removed(self) -> None:
        self.assertFalse(transition_allowed("running", "removed"))

    def test_nothing_leaves_removed(self) -> None:
        self.assertEqual([target for source, target in TRANSITIONS if source == "removed"], [])

    def test_broken_is_not_terminal(self) -> None:
        """§23 requires a recovery path for a broken capsule."""
        self.assertTrue(transition_allowed("broken", "resetting"))
        self.assertTrue(transition_allowed("broken", "removed"))

    def test_recovery_from_a_crash_does_not_resume_running(self) -> None:
        self.assertFalse(transition_allowed("unknown", "starting"))
        self.assertTrue(transition_allowed("unknown", "stopped"))

    def test_every_state_is_reachable_or_initial(self) -> None:
        reachable = {"absent"} | {target for _source, target in TRANSITIONS}
        self.assertEqual(reachable, set(STATES))


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def test_opening_twice_reconnects_to_one_capsule(self) -> None:
        first = self.world.install()
        first.layout.directory("data").joinpath("notes.txt").write_bytes(b"kept")
        second = self.world.runtime.open("org.example.PhotoEditor")
        self.assertEqual(first.layout.root, second.layout.root)
        self.assertEqual(second.layout.directory("data").joinpath("notes.txt").read_bytes(), b"kept")

    def test_installing_over_an_existing_capsule_keeps_its_data(self) -> None:
        capsule = self.world.install()
        capsule.layout.directory("data").joinpath("notes.txt").write_bytes(b"kept")
        self.world.runtime.install(manifest_for(optional=("gpu",)))
        again = self.world.runtime.open("org.example.PhotoEditor")
        self.assertTrue(again.layout.directory("data").joinpath("notes.txt").exists())

    def test_installing_over_an_existing_capsule_keeps_its_grants(self) -> None:
        capsule = self.world.install()
        self.world.answer(("gpu", "allow", "always"))
        self.world.request(capsule, category="gpu")
        self.assertEqual(len(self.world.runtime.grants(capsule)), 1)
        self.world.runtime.install(manifest_for())
        self.assertEqual(len(self.world.runtime.grants(self.world.runtime.open("org.example.PhotoEditor"))), 1)

    def test_opening_an_application_that_was_never_installed_refuses(self) -> None:
        with self.assertRaises(CapsuleStateError):
            self.world.runtime.open("org.example.NeverInstalled")

    def test_a_running_state_from_a_previous_session_becomes_unknown(self) -> None:
        capsule = self.world.install()
        capsule.state.state = "running"
        capsule.state.session_id = "an-older-session"
        capsule.state.write(capsule.layout.state_path)
        reopened = self.world.runtime.open("org.example.PhotoEditor")
        self.assertEqual(reopened.state.state, "unknown")


class LaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()

    def test_the_default_executor_starts_nothing_and_says_so(self) -> None:
        record = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertFalse(record.started)
        self.assertIsNone(record.pid)
        self.assertEqual(self.world.runtime.open("org.example.PhotoEditor").state.state, "stopped")

    def test_the_argument_vector_is_a_list_with_no_shell_anywhere(self) -> None:
        record = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertIsInstance(record.argv, tuple)
        self.assertNotIn("sh", record.argv)
        self.assertNotIn("-c", record.argv)
        self.assertNotIn("bash", record.argv)

    def test_the_sandbox_root_is_remounted_read_only_after_the_binds(self) -> None:
        """Order is the property: before the binds it would make the capsule's
        own directories read-only too. Measured on Linux, asserted here."""
        record = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        argv = list(record.argv)
        remount = argv.index("--remount-ro")
        self.assertEqual(argv[remount + 1], "/")
        last_bind = max(index for index, value in enumerate(argv) if value in ("--bind", "--ro-bind", "--tmpfs"))
        self.assertGreater(remount, last_bind, "the root is remounted before a bind is in place")
        self.assertLess(remount, argv.index("--clearenv"))

    def test_the_launcher_environment_is_two_keys_and_never_reaches_the_application(self) -> None:
        """systemd-run --user needs the session bus to create a scope. bwrap's
        --clearenv between the two is what stops the launcher's environment
        reaching the application.

        The assertion is on *values*, not on key names. XDG_RUNTIME_DIR is a key
        in both — the launcher gets the session's /run/user/N and the application
        gets the capsule's own runtime directory — and an earlier version of this
        test asserted the key was absent, which passed on a developer host only
        because nothing had set it there. A key in common with a different value
        is the design; a value in common is the leak."""
        from capsules.isolation import LAUNCHER_ENVIRONMENT_KEYS

        plan = self.world.runtime.build_plan(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertTrue(set(plan.launcher_environment) <= set(LAUNCHER_ENVIRONMENT_KEYS))
        self.assertEqual(set(LAUNCHER_ENVIRONMENT_KEYS), {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"})
        for key, value in plan.launcher_environment.items():
            self.assertNotEqual(
                plan.environment.get(key), value,
                f"the launcher's {key} reached the application unchanged",
            )

    def test_a_capsule_whose_process_exited_can_be_launched_again(self) -> None:
        """Nothing moves a capsule out of `running` when an ordinary application
        exits, so before reconciliation the second launch refused forever."""

        class Exiting:
            starts_processes = True

            def __init__(self) -> None:
                self.started = 0

            def start(self, argv, plan):  # noqa: ANN001
                self.started += 1
                return 4242

            def poll(self, pid):  # noqa: ANN001
                return 0

            def stop(self, scope_name):  # noqa: ANN001
                return True

        self.world.runtime.executor = Exiting()
        first = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertTrue(first.started)
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        self.assertEqual(capsule.state.state, "stopped")
        self.assertEqual(capsule.state.last_exit_code, 0)
        second = self.world.runtime.launch(capsule)
        self.assertTrue(second.started)
        self.assertEqual(self.world.runtime.executor.started, 2)

    def test_bubblewrap_clears_the_environment_before_setting_it(self) -> None:
        record = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertIn("--clearenv", record.argv)
        self.assertIn("bwrap", record.argv)

    def test_flatpak_revokes_the_packaged_defaults_before_adding_anything(self) -> None:
        world = World.build()
        self.addCleanup(world.close)
        world.install(manifest_for(backend="flatpak", package_source="flatpak", package_reference="org.example.PhotoEditor"))
        record = world.runtime.launch(world.runtime.open("org.example.PhotoEditor"))
        self.assertIn("--nofilesystem=host", record.argv)
        self.assertIn("--nofilesystem=home", record.argv)
        self.assertIn("--nodevice=all", record.argv)
        self.assertIn("--no-talk-name=*", record.argv)

    def test_the_launch_is_inside_a_systemd_scope_with_the_declared_limits(self) -> None:
        record = self.world.runtime.launch(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertEqual(record.argv[0], "systemd-run")
        self.assertIn("MemoryMax=4294967296", record.argv)
        self.assertIn("TasksMax=512", record.argv)

    def test_launching_a_running_capsule_refuses(self) -> None:
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        capsule.state.state = "running"
        with self.assertRaises(CapsuleStateError):
            self.world.runtime.launch(capsule)


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()
        for name in ("data", "config", "cache", "tmp", "exports", "inbox"):
            self.capsule.layout.directory(name).joinpath("f").write_bytes(b"x")

    def surviving(self):  # type: ignore[no-untyped-def]
        return {
            name
            for name in ("data", "config", "cache", "tmp", "exports", "inbox")
            if self.capsule.layout.directory(name).joinpath("f").exists()
        }

    def test_clearing_temporary_data_keeps_documents_and_settings(self) -> None:
        self.world.runtime.clear_temporary(self.capsule)
        self.assertEqual(self.surviving(), {"data", "config", "exports", "inbox"})

    def test_resetting_keeps_documents_and_drops_settings(self) -> None:
        self.world.runtime.reset(self.capsule)
        self.assertEqual(self.surviving(), {"data", "exports"})

    def test_deleting_data_removes_everything_the_capsule_holds(self) -> None:
        self.world.runtime.delete_data(self.capsule)
        self.assertEqual(self.surviving(), set())

    def test_the_three_removal_sets_are_nested(self) -> None:
        self.assertTrue(set(CLEARABLE) < set(RESETTABLE) < set(DELETABLE))

    def test_a_destructive_operation_refuses_while_the_capsule_is_running(self) -> None:
        self.capsule.state.state = "running"
        for operation in (
            self.world.runtime.clear_temporary,
            self.world.runtime.reset,
            self.world.runtime.delete_data,
            self.world.runtime.uninstall,
        ):
            with self.assertRaises(CapsuleStateError):
                operation(self.capsule)

    def test_uninstalling_revokes_every_grant_and_removes_the_directory(self) -> None:
        self.world.answer(("gpu", "allow", "always"), ("files", "allow", "always"))
        picture = self.world.file("Pictures/cat.png")
        self.world.request(self.capsule, category="gpu")
        self.world.request(self.capsule, category="files", resource=trust.path_resource(picture), purpose="read")
        self.assertEqual(len(self.world.runtime.grants(self.capsule)), 2)

        outcome = self.world.runtime.uninstall(self.capsule)
        self.assertEqual(outcome["grantsRevoked"], 2)
        self.assertTrue(outcome["directoryRemoved"])
        self.assertFalse(self.capsule.layout.root.exists())
        self.assertEqual(self.world.store.for_application("org.example.PhotoEditor"), ())

    def test_stopping_drops_session_grants_but_not_standing_ones(self) -> None:
        self.world.answer(("gpu", "allow", "session"), ("network", "allow", "always"))
        capsule = self.world.install(manifest_for(optional=("gpu", "network"), network_ceiling="internet"))
        self.world.request(capsule, category="gpu")
        self.world.request(capsule, category="network", resource=trust.network_resource("internet"))
        capsule.state.state = "running"
        self.world.runtime.stop(capsule)
        remaining = self.world.runtime.grants(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertEqual([grant.category for grant in remaining], ["network"])

    def test_a_broken_capsule_is_listed_rather_than_dropped(self) -> None:
        self.capsule.layout.manifest_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.world.runtime.list(), ())
        self.assertEqual(self.world.runtime.broken(), (self.capsule.layout.root.name,))


if __name__ == "__main__":
    unittest.main()

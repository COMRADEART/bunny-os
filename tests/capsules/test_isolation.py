# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a capsule can reach, asserted on the plan rather than on a running kernel.

The isolation plan is a value, so these run anywhere. That is the point: "a
capsule with no file grants has no bind mount into the user's home" is a property
of the planner, and testing it against a real sandbox would make it a property of
whichever machine the suite happened to run on.

What these tests cannot show is that bwrap honours the plan. That is a VM
question and is recorded as such in the reports; nothing here is labelled as
evidence of runtime isolation.
"""

from __future__ import annotations

import os
import unittest

import trust
from capsules.backends import BACKENDS, backend as backend_descriptor
from capsules.errors import CapsuleContainmentError, CapsuleIsolationError, CapsuleUnavailable
from capsules.isolation import BASE_DEVICES, CREDENTIAL_DIRECTORIES, GRANT_TARGET_ROOT, plan_isolation

from tests.capsule_support import World, manifest_for, unconfined_probe


class PlanShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install(manifest_for(required=("files",), optional=("gpu", "network", "folders")))

    def plan(self, *, allow_unconfined: bool = False):
        return self.world.runtime.build_plan(self.world.runtime.open("org.example.PhotoEditor"),
                                             allow_unconfined=allow_unconfined)

    # -- the empty start --------------------------------------------------

    def test_a_capsule_with_no_grants_reaches_no_user_path(self) -> None:
        plan = self.plan()
        self.assertEqual(plan.reachable_paths(), ())
        for bind in plan.binds:
            self.assertNotEqual(bind.origin, "grant")

    def test_the_home_directory_is_never_bound(self) -> None:
        plan = self.plan()
        home = str(self.world.home)
        for bind in plan.binds:
            self.assertNotEqual(bind.source, home)
            self.assertFalse(bind.source.startswith(home + os.sep), bind.source)

    def test_the_capsule_gets_its_own_seven_directories_and_a_tmpfs(self) -> None:
        plan = self.plan()
        capsule_binds = [bind for bind in plan.binds if bind.origin == "capsule"]
        self.assertEqual(len(capsule_binds), 7)
        self.assertTrue(all(bind.writable for bind in capsule_binds))
        self.assertTrue(any(bind.kind == "tmpfs" and bind.target == "/tmp" for bind in plan.binds))

    def test_no_network_means_the_network_namespace_is_unshared(self) -> None:
        plan = self.plan()
        self.assertEqual(plan.network, "none")
        self.assertIn("net", plan.unshare)

    def test_only_the_base_devices_are_present_without_a_grant(self) -> None:
        self.assertEqual(self.plan().devices, BASE_DEVICES)

    # -- the environment --------------------------------------------------

    def test_the_environment_is_built_rather_than_inherited(self) -> None:
        """A pattern-matched allowlist is how LD_PRELOAD gets in; this is a fixed
        key set, so a variable that is not named is simply not there."""
        os.environ["LD_PRELOAD"] = "/tmp/evil.so"
        os.environ["PYTHONPATH"] = "/tmp/evil"
        os.environ["http_proxy"] = "http://attacker.example"
        self.addCleanup(lambda: [os.environ.pop(key, None) for key in ("LD_PRELOAD", "PYTHONPATH", "http_proxy")])
        keys = set(self.plan().environment)
        self.assertEqual(
            keys,
            {"PATH", "HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "TMPDIR", "LANG"},
        )

    def test_home_inside_the_capsule_is_the_capsule_not_the_user(self) -> None:
        plan = self.plan()
        self.assertTrue(plan.environment["HOME"].startswith("/run/bunny/app"))

    # -- grants become mounts ---------------------------------------------

    def test_a_read_grant_becomes_a_read_only_bind_under_a_neutral_root(self) -> None:
        picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(picture), purpose="read")
        plan = self.plan()
        grants = [bind for bind in plan.binds if bind.origin == "grant"]
        self.assertEqual(len(grants), 1)
        self.assertFalse(grants[0].writable)
        self.assertTrue(grants[0].target.startswith(GRANT_TARGET_ROOT))
        self.assertTrue(grants[0].target.endswith("/cat.png"))

    def test_a_grant_target_does_not_disclose_the_users_directory_layout(self) -> None:
        picture = self.world.file("Pictures/holiday/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(picture), purpose="read")
        target = [bind for bind in self.plan().binds if bind.origin == "grant"][0].target
        self.assertNotIn("holiday", target)
        self.assertNotIn("Pictures", target)

    def test_a_write_grant_becomes_a_writable_bind(self) -> None:
        picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(picture), purpose="write")
        self.assertTrue([bind for bind in self.plan().binds if bind.origin == "grant"][0].writable)

    def test_a_gpu_grant_adds_the_render_node_and_nothing_else(self) -> None:
        self.world.answer(("gpu", "allow", "always"))
        self.world.request(self.capsule, category="gpu")
        plan = self.plan()
        self.assertIn("/dev/dri", plan.devices)
        self.assertEqual(len(plan.devices), len(BASE_DEVICES) + 1)

    def test_a_network_grant_sets_the_class_and_stops_unsharing_the_namespace(self) -> None:
        manifest = manifest_for(optional=("network",), network_ceiling="internet")
        self.world.install(manifest)
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        self.world.answer(("network", "allow", "always"))
        self.world.request(capsule, category="network", resource=trust.network_resource("internet"))
        plan = self.world.runtime.build_plan(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertEqual(plan.network, "internet")
        self.assertNotIn("net", plan.unshare)

    # -- the four refusals -------------------------------------------------

    def test_a_credential_directory_is_refused_even_when_granted(self) -> None:
        """A person can pick ~/.ssh in a file chooser. The capsule still does not
        get it: §7 lists SSH keys among the things an application must never
        automatically receive, and a click past a chooser is not the informed
        decision that overrides it."""
        secret = self.world.home / ".ssh" / "id_ed25519"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_bytes(b"KEY")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(secret), purpose="read")
        plan = self.plan()
        self.assertEqual(plan.reachable_paths(), ())
        self.assertTrue(any(".ssh" in reason for _gid, reason in plan.refusals))

    def test_every_named_credential_directory_is_refused(self) -> None:
        self.world.answer(*[("files", "allow", "always") for _ in CREDENTIAL_DIRECTORIES])
        for name in sorted(CREDENTIAL_DIRECTORIES):
            target = self.world.home / name / "secret"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            self.world.request(
                self.capsule, category="files", resource=trust.path_resource(target), purpose="read"
            )
        self.assertEqual(self.plan().reachable_paths(), ())

    def test_a_path_inside_another_capsule_raises_rather_than_being_skipped(self) -> None:
        """§20: one application's private data is never mounted into another. A
        refusal recorded in the plan would let the launch proceed; this raises."""
        other = self.world.install(manifest_for("org.example.Other", display_name="Other"))
        victim = other.layout.directory("data") / "notes.txt"
        victim.write_bytes(b"private")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(victim), purpose="read")
        with self.assertRaises(CapsuleContainmentError):
            self.plan()

    def test_a_grant_whose_file_has_gone_is_refused_not_bound(self) -> None:
        picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=trust.path_resource(picture), purpose="read")
        picture.unlink()
        plan = self.plan()
        self.assertEqual(plan.reachable_paths(), ())
        self.assertTrue(plan.refusals)

    def test_a_grant_for_a_category_the_manifest_no_longer_declares_is_refused(self) -> None:
        """An application update that drops a permission drops the grant's effect,
        and the discrepancy is recorded rather than ignored."""
        self.world.answer(("gpu", "allow", "always"))
        self.world.request(self.capsule, category="gpu")
        narrowed = manifest_for(required=("files",), optional=())
        self.world.runtime.install(narrowed)
        plan = self.world.runtime.build_plan(self.world.runtime.open("org.example.PhotoEditor"))
        self.assertNotIn("/dev/dri", plan.devices)
        self.assertTrue(any("no longer declared" in reason for _gid, reason in plan.refusals))

    def test_a_grant_belonging_to_another_application_raises(self) -> None:
        manifest = self.capsule.manifest
        stray = trust.Grant(
            grant_id="g-stray",
            application_id="org.example.Somebody",
            category="gpu",
            resource=trust.no_resource(),
            purpose="use",
            scope="always",
            verdict="allow",
            source="user",
            decided_at="2026-01-01T00:00:00Z",
        )
        with self.assertRaises(CapsuleIsolationError):
            plan_isolation(
                manifest,
                [stray],
                backend=backend_descriptor("bubblewrap"),
                layout=self.capsule.layout,
                capsule_root=self.world.runtime.root,
            )


class BackendHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build(probe=unconfined_probe())
        self.addCleanup(self.world.close)
        self.world.install(manifest_for())

    def test_no_confining_backend_means_no_launch(self) -> None:
        """§22 applied to the sandbox: an application whose isolation cannot be
        built does not start, and the message names what is missing."""
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        with self.assertRaises(CapsuleUnavailable) as caught:
            self.world.runtime.build_plan(capsule)
        self.assertIn("user namespaces", str(caught.exception))

    def test_the_non_confining_backend_is_never_selected_automatically(self) -> None:
        from capsules.backends import select_backend

        with self.assertRaises(CapsuleUnavailable):
            select_backend("bubblewrap", self.world.runtime.probe)
        chosen = select_backend("bubblewrap", self.world.runtime.probe, allow_unconfined=True)
        self.assertEqual(chosen.backend, "systemd-scope")
        self.assertFalse(chosen.confines)

    def test_an_unconfined_plan_says_it_is_unconfined(self) -> None:
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        plan = self.world.runtime.build_plan(capsule, allow_unconfined=True)
        self.assertFalse(plan.confining)

    def test_a_backend_reports_the_categories_it_cannot_enforce(self) -> None:
        world = World.build(probe=unconfined_probe())
        self.addCleanup(world.close)
        capsule = world.install(manifest_for(optional=("gpu", "clipboard", "network")))
        world.answer(("gpu", "allow", "always"), ("clipboard", "allow", "session"))
        world.request(capsule, category="gpu")
        world.request(capsule, category="clipboard")
        plan = world.runtime.build_plan(world.runtime.open("org.example.PhotoEditor"), allow_unconfined=True)
        self.assertIn("gpu", plan.unenforced)
        self.assertIn("clipboard", plan.unenforced)

    def test_every_declared_backend_names_what_it_enforces(self) -> None:
        for name, entry in BACKENDS.items():
            self.assertIsInstance(entry.enforces, frozenset)
            if entry.confines:
                self.assertIn("files", entry.enforces, name)
            else:
                self.assertNotIn("files", entry.enforces, name)


if __name__ == "__main__":
    unittest.main()

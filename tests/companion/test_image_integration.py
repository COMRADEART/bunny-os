# SPDX-License-Identifier: GPL-3.0-or-later
"""The companion's place in the installed image.

The install set is declared once, in ``build/scripts/install_routes.py``, and
``install-root.py`` is driven by that table — so these tests read the same
route objects the installer copies from. Re-parsing the installer here would
let a test pass while the two sides disagreed, which is precisely the failure
the shared table exists to prevent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "build/scripts/install-root.py"
ROUTE_TABLE = ROOT / "build/scripts/install_routes.py"


def load_route_table():
    """Import the declaration both consumers read.

    The module is standard-library-only on purpose — it runs inside a bootc
    container with no repository Python on its path — so importing it here is
    safe as well as honest.
    """
    spec = importlib.util.spec_from_file_location("install_routes_under_test", ROUTE_TABLE)
    module = importlib.util.module_from_spec(spec)
    # Dataclass processing resolves string annotations through sys.modules; an
    # unregistered module makes that lookup return None under Python 3.14.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_installer():
    """Import install-root.py the same way, for the functions that are pure."""
    spec = importlib.util.spec_from_file_location("install_root_under_test", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CompanionInstalledImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = load_route_table()

    def route(self, identifier: str):
        return next(
            item for item in self.table.INSTALL_ROUTES if item.id == identifier
        )

    def test_companion_code_has_a_read_only_install_route(self) -> None:
        route = self.route("companion-package")
        self.assertEqual(route.destination, "/usr/lib/bunny-os/python/companion")
        self.assertEqual(route.mode, 0o444)
        # A package route installs source and only source: bytecode carries the
        # producing machine's paths and mtimes, and fixtures are
        # untrusted-input-shaped content.
        self.assertIn("__pycache__", route.effective_exclude)
        self.assertEqual(route.effective_suffixes, (".py",))
        copied = list(self.table.route_files(route, ROOT))
        self.assertTrue(copied, "the companion package route selects no file")
        destinations = {destination for _, destination in copied}
        # The whole package travels, voice and character included: this is the
        # coverage whose absence once reported a voice-runtime change as zero
        # build impact.
        self.assertIn("/usr/lib/bunny-os/python/companion/store.py", destinations)
        self.assertTrue(
            any(item.startswith("/usr/lib/bunny-os/python/companion/voice/") for item in destinations),
            "companion/voice/ did not travel with the package route",
        )
        self.assertTrue(
            any(item.startswith("/usr/lib/bunny-os/python/companion/character/") for item in destinations),
            "companion/character/ did not travel with the package route",
        )
        self.assertFalse(any(destination.endswith((".pyc", ".pyo")) for destination in destinations))

    def test_build_context_and_installer_include_the_runtime(self) -> None:
        containerfile = (ROOT / "build/Containerfile").read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("COPY companion /tmp/bunny-os/companion", containerfile)
        # Destinations live in the route table, not hardcoded in the installer —
        # that duplication is exactly what the shared table replaced. Assert
        # through the declaration both consumers read.
        destinations = {
            route.id: route.destination for route in self.table.INSTALL_ROUTES
        }
        self.assertEqual(
            destinations["companion-service-executable"],
            "/usr/libexec/bunny-companion-service",
        )
        self.assertEqual(
            destinations["companion-shell-assets"],
            "/usr/share/bunny-shell/companion",
        )
        # The activation list names the unit the preset enables: a companion
        # shipped but never enabled is the defect "a preset is not an enablement".
        self.assertIn('"bunny-companion.service"', installer)

    def test_user_service_is_private_bounded_and_local_only(self) -> None:
        unit = (ROOT / "systemd/user/bunny-companion.service").read_text(encoding="utf-8")
        for directive in (
            "ExecStart=/usr/libexec/bunny-companion-service",
            "RuntimeDirectoryMode=0700",
            "StateDirectoryMode=0700",
            "UMask=0077",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "RestrictAddressFamilies=AF_UNIX",
            # Enforcement budgets sized for the resident recogniser plus the
            # isolated TTS worker, not benchmark claims; see the unit comment.
            "MemoryHigh=1536M",
            "MemoryMax=2G",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, unit)
        self.assertNotIn("AF_INET", unit)

    def test_shell_entry_points_asset_desktop_and_activation_exist(self) -> None:
        required = (
            "services/bunny-companion/bunny_companion_service.py",
            "shell/services/bin/bunny-companion",
            "shell/services/bin/bunny-approvals",
            "shell/assets/companion/default-bunny.svg",
            "shell/components/applications/art.comrade.BunnyCompanion.desktop",
        )
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
        preset = (ROOT / "config/systemd/60-bunny-os-user.preset").read_text(encoding="utf-8")
        target = (ROOT / "systemd/user/bunny-shell.target").read_text(encoding="utf-8")
        self.assertIn("enable bunny-companion.service", preset)
        self.assertIn("Wants=bunny-companion.service", target)

    def test_companion_sources_contain_no_embedded_credential_values(self) -> None:
        credential = re.compile(
            r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}"
        )
        for path in sorted((ROOT / "companion").glob("*.py")):
            with self.subTest(path=path.name):
                self.assertIsNone(credential.search(path.read_text(encoding="utf-8")))

    def test_no_companion_runtime_state_is_committed(self) -> None:
        forbidden = {"companion.sqlite3", "approvals.json", "runtime.sock"}
        found = {path.name for path in ROOT.rglob("*") if path.is_file() and path.name in forbidden}
        self.assertEqual(found, set())


class ActivationAndRouteGuardTests(unittest.TestCase):
    """Regressions from the runtime-path audit, at the files that carry them.

    Each test names the boot it would have prevented. They read the artifacts
    rather than re-running an image build, because the artifact is what ships.
    """

    def test_the_shell_target_is_not_reaped_when_its_start_job_completes(self) -> None:
        """Regression: ``StopWhenUnneeded=yes`` stopped bunny-shell.target the
        moment its start job completed — a same-second Reached/Stopped pair on
        every recorded boot — taking its Wanted= dependents (the companion,
        with it the whole assistant surface: "status unavailable · security
        unknown") down with it. Logout teardown is PartOf='s job, and it was
        already there."""
        target = (ROOT / "systemd/user/bunny-shell.target").read_text(encoding="utf-8")
        # The comment explaining the absence names the directive too, so match
        # the directive itself, not the word anywhere in the file.
        self.assertFalse(
            [line for line in target.splitlines() if line.strip().startswith("StopWhenUnneeded")],
            "StopWhenUnneeded is set on bunny-shell.target")
        self.assertIn("PartOf=graphical-session.target", target)

    def test_the_capability_supervisor_is_enabled_and_asserted_by_the_installer(self) -> None:
        """Regression: presets are never applied in this build — enablement is
        what install_activation() writes — so a unit only named in the preset
        never ran at boot. The enable line AND the symlink assertion must both
        name it."""
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('"bunny-capability-supervisor.service",', installer)
        self.assertIn('"bunny-capability-supervisor.service": Path(', installer)

    def test_first_run_only_runs_where_its_program_was_installed(self) -> None:
        """Regression: on profiles whose route set does not ship
        /usr/bin/bunny-first-run, the enabled unit answered every boot with
        status 203/EXEC. The condition makes absence a skip, not a failure."""
        unit = (ROOT / "systemd/user/bunny-first-run.service").read_text(encoding="utf-8")
        self.assertIn("ConditionFileIsExecutable=/usr/bin/bunny-first-run", unit)

    def test_no_preset_line_is_declared_twice(self) -> None:
        """Regression: 60-bunny-os.preset carried one enable block twice (and
        two contradictory disable lines for one unit). An exact duplicate line
        can never be intentional — last-wins means it is either dead weight or
        a silent override of the line someone thought was in charge."""
        preset = (ROOT / "config/systemd/60-bunny-os.preset").read_text(encoding="utf-8")
        actions = [
            line.strip() for line in preset.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        duplicates = {item for item in actions if actions.count(item) > 1}
        self.assertEqual(duplicates, set())

    def test_the_desktop_entry_is_declared_exactly_once(self) -> None:
        """Regression: art.comrade.BunnyCompanion.desktop existed twice in the
        tree with two different Exec= policies, and both routes installed into
        the same destination — which one shipped depended on tuple position.
        The Applications entry under shell/components is the repo-tested policy
        (Exec=/usr/bin/bunny-companion); nothing else may install that name."""
        entries = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("art.comrade.BunnyCompanion.desktop")
            if not any(part in (".git", "node_modules", "__pycache__") for part in path.parts)
            and path.parts[:2] != ("build", "out")
        ]
        self.assertEqual(entries, ["shell/components/applications/art.comrade.BunnyCompanion.desktop"])
        text = (ROOT / entries[0]).read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/bin/bunny-companion", text)

    def test_installing_every_profile_hits_no_destination_twice(self) -> None:
        """The duplicate-destination guard, exercised against the real table.

        install_all_routes refuses two routes writing one file; this runs the
        real installer's route pass into a throwaway root for every profile,
        so a new route that collides fails here instead of shipping whichever
        file tuple position favoured. Also proves no route names a source that
        does not exist — the way a deleted tree breaks a build.
        """
        import tempfile

        table = load_route_table()
        installer = load_installer()
        for profile in table.PROFILES:
            with self.subTest(profile=profile):
                with tempfile.TemporaryDirectory() as tmp:
                    installed = installer.install_all_routes(
                        ROOT, profile, root=Path(tmp),
                    )
                    destinations = [
                        destination
                        for copied in installed.values()
                        for destination in copied
                    ]
                    self.assertEqual(len(destinations), len(set(destinations)))


if __name__ == "__main__":
    unittest.main()

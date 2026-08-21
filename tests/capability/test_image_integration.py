# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The build-input closure analyser, and what the image must and must not carry.

Two things are being defended here. The first is the analyser itself: it exists
because a build-impact claim was made by inspection and was wrong, so an
analyser that is merely *usually* right would reproduce the original failure
with more ceremony. The second is the install set: a validation fixture that
reached an installed system would be startable on somebody's machine.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
ANALYSER = ROOT / "build/scripts/build-input-closure.py"
INSTALLER = ROOT / "build/scripts/install-root.py"
CONTAINERFILE = ROOT / "build/Containerfile"


def load_analyser():
    """Import the analyser by path; its filename is not an identifier."""
    spec = importlib.util.spec_from_file_location("build_input_closure", ANALYSER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_install_routes() -> tuple:
    """Read INSTALL_ROUTES out of the installer without importing it.

    Importing install-root.py would execute a module written to run inside a
    container; parsing it is both safer and closer to what the analyser does.
    """
    tree = ast.parse(INSTALLER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [item.id for item in node.targets if isinstance(item, ast.Name)]
            if "INSTALL_ROUTES" in names:
                return ast.literal_eval(node.value)
    raise AssertionError("install-root.py no longer declares INSTALL_ROUTES")


class AnalyserResolutionTests(unittest.TestCase):
    """Every install route must be resolvable, or the closure is a guess."""

    def setUp(self) -> None:
        self.module = load_analyser()

    def classify(self, path: str) -> dict:
        roots, _ = self.module.build_context_roots(CONTAINERFILE)
        routes, _ = self.module.install_routes(INSTALLER)
        return self.module.classify(path, roots, routes)

    def test_capability_code_is_recognised_as_installed(self) -> None:
        # The whole point of the integration. If this reports context-only, the
        # analyser would license another "build impact: none" claim.
        result = self.classify("capability/apply/applicator.py")
        self.assertEqual(result["classification"], "installed")
        self.assertEqual(
            result["routes"][0]["installedAs"],
            "/usr/lib/bunny-os/python/capability/apply/applicator.py",
        )

    def test_the_supervisor_module_is_installed(self) -> None:
        self.assertEqual(
            self.classify("capability/supervisor.py")["classification"], "installed",
        )

    def test_a_service_manifest_is_installed_read_only(self) -> None:
        result = self.classify("capability/services/bunny-inference-local.json")
        self.assertEqual(result["classification"], "installed")
        self.assertTrue(
            result["routes"][0]["installedAs"].startswith("/usr/share/bunny-os/capability/services/"),
        )

    def test_the_supervisor_entry_point_and_unit_are_installed(self) -> None:
        for path in (
            "services/bunny-capability-supervisor/bunny_capability_supervisor.py",
            "systemd/bunny-capability-supervisor.service",
            "config/bunny-os/capability-supervisor.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.classify(path)["classification"], "installed")

    def test_the_probe_fixture_is_never_installed(self) -> None:
        for path in (
            "capability/testing/bunny-capability-probe",
            "capability/testing/bunny-capability-probe.service",
            "capability/services/bunny-capability-probe.json",
        ):
            with self.subTest(path=path):
                self.assertNotEqual(
                    self.classify(path)["classification"], "installed",
                    "a validation fixture must not reach an installed system",
                )

    def test_bytecode_is_never_installed(self) -> None:
        self.assertNotEqual(
            self.classify("capability/apply/__pycache__/applicator.cpython-313.pyc")["classification"],
            "installed",
        )

    def test_tests_are_unreachable_from_the_build(self) -> None:
        result = self.classify("tests/capability/test_apply_reconcile.py")
        self.assertEqual(result["classification"], "unreachable")
        self.assertFalse(result["inBuildContext"])

    def test_a_path_outside_every_copy_is_unreachable(self) -> None:
        for path in ("KNOWN_LIMITATIONS.md", "qualification/whatever.json", "reviews/x.md"):
            with self.subTest(path=path):
                self.assertEqual(self.classify(path)["classification"], "unreachable")


class AnalyserRegressionTests(unittest.TestCase):
    """The exact mistakes the analyser was written to catch."""

    def setUp(self) -> None:
        self.module = load_analyser()

    def test_the_applicator_commit_is_reported_build_affecting(self) -> None:
        # The claim that started this: capability/apply/ is genuinely not
        # installed, but the same commit changed schemas/ and docs/, which are.
        result = subprocess.run(
            [sys.executable, str(ANALYSER), "--range", "96ca61f..ff751ab", "--json"],
            capture_output=True, text=True, cwd=ROOT, check=False,
        )
        self.assertEqual(result.returncode, 1, "a build-affecting range must exit 1")
        document = json.loads(result.stdout)
        self.assertTrue(document["summary"]["buildAffecting"])
        installed = {item["path"] for item in document["installed"]}
        self.assertIn("schemas/execution-plan.schema.json", installed)
        self.assertIn("docs/CAPABILITY_APPLICATOR.md", installed)

    def test_a_documentation_only_change_is_still_build_affecting(self) -> None:
        # docs/ is copied wholesale. A "docs only, surely harmless" change is
        # exactly the shape of the original error.
        roots, _ = self.module.build_context_roots(CONTAINERFILE)
        routes, _ = self.module.install_routes(INSTALLER)
        result = self.module.classify("docs/CAPABILITY_RUNTIME.md", roots, routes)
        self.assertEqual(result["classification"], "installed")

    def test_the_exit_status_distinguishes_build_affecting_changes(self) -> None:
        for paths, expected in (
            (["tests/capability/test_apply_ledger.py"], 0),
            (["capability/apply/applicator.py"], 1),
        ):
            with self.subTest(paths=paths):
                result = subprocess.run(
                    [sys.executable, str(ANALYSER), "--paths", *paths],
                    capture_output=True, text=True, cwd=ROOT, check=False,
                )
                self.assertEqual(result.returncode, expected)

    def test_the_analyser_reports_its_own_unresolved_calls(self) -> None:
        # Honesty about incompleteness is the property that stops this tool
        # becoming the next thing somebody trusts too far.
        _, unresolved = self.module.install_routes(INSTALLER)
        self.assertIsInstance(unresolved, list)

    def test_the_closure_is_complete_for_copy_directives(self) -> None:
        _, unresolved = self.module.build_context_roots(CONTAINERFILE)
        self.assertEqual(unresolved, [], f"unresolved COPY directives: {unresolved}")

    def test_the_indirect_routes_are_declared(self) -> None:
        # Every commit changes the OCI config digest. An analyser that did not
        # say so would let an unchanged layer digest read as an unchanged image.
        destinations = {item["destination"] for item in self.module._INDIRECT_ROUTES}
        self.assertTrue(any("revision" in item for item in destinations))
        self.assertIn("/usr/lib/bunny-os/release.json", destinations)


class InstallRouteTableTests(unittest.TestCase):
    """The declaration the installer is driven by must stay honest."""

    def setUp(self) -> None:
        self.routes = load_install_routes()

    def test_capability_code_and_manifests_are_both_declared(self) -> None:
        identifiers = {item["id"] for item in self.routes}
        self.assertIn("capability-code", identifiers)
        self.assertIn("capability-manifests", identifiers)

    def test_the_code_route_excludes_fixtures_and_bytecode(self) -> None:
        route = next(item for item in self.routes if item["id"] == "capability-code")
        self.assertIn("testing", route["exclude"])
        self.assertIn("__pycache__", route["exclude"])
        self.assertIn("services", route["exclude"])

    def test_the_manifest_route_excludes_the_probe(self) -> None:
        route = next(item for item in self.routes if item["id"] == "capability-manifests")
        self.assertIn("bunny-capability-probe", route["excludeStems"])

    def test_installed_code_is_read_only(self) -> None:
        # Immutable code must not be writable by anything, which is half of
        # "code cannot write into its own installation directory"; the unit's
        # ProtectSystem=strict is the other half.
        for route in self.routes:
            with self.subTest(route=route["id"]):
                self.assertEqual(route["mode"], 0o444)

    def test_every_declared_source_glob_matches_something(self) -> None:
        # A route matching nothing is a route that silently installs nothing.
        for route in self.routes:
            with self.subTest(route=route["id"]):
                self.assertTrue(
                    list(ROOT.glob(route["sourceGlob"])),
                    f"{route['sourceGlob']} matches no file",
                )


class InstalledLayoutTests(unittest.TestCase):
    """The layout's invariants, checked against the files that create it."""

    def test_the_supervisor_unit_names_the_installed_executable(self) -> None:
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/libexec/bunny-capability-supervisor", unit)
        self.assertIn("--config /etc/bunny-os/capability/supervisor.json", unit)

    def test_the_unit_separates_state_runtime_configuration_and_logs(self) -> None:
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        for directive in ("StateDirectory=", "RuntimeDirectory=", "ConfigurationDirectory=", "LogsDirectory="):
            with self.subTest(directive=directive):
                self.assertIn(directive, unit)

    def test_state_is_not_world_readable(self) -> None:
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        self.assertIn("StateDirectoryMode=0700", unit)

    def test_immutable_code_cannot_be_written_by_the_supervisor(self) -> None:
        # ProtectSystem=strict makes /usr read-only to the unit, and the
        # ReadWritePaths list is the complete set of exceptions.
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        self.assertIn("ProtectSystem=strict", unit)
        writable = [
            line.split("=", 1)[1]
            for line in unit.splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertTrue(writable)
        for path in " ".join(writable).split():
            with self.subTest(path=path):
                self.assertFalse(
                    path.startswith("/usr"),
                    "the supervisor must not be able to write into its own installation",
                )

    def test_the_unit_bounds_startup_shutdown_and_restart(self) -> None:
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        for directive in ("TimeoutStartSec=", "TimeoutStopSec=", "StartLimitBurst=", "RestartSec="):
            with self.subTest(directive=directive):
                self.assertIn(directive, unit)

    def test_the_unit_does_not_set_directives_that_would_break_it(self) -> None:
        # ProtectControlGroups=yes would make the cgroup read-back impossible,
        # and every transition would be reported unenforceable and rolled back.
        # PrivateNetwork=yes would blind the network probe.
        unit = (ROOT / "systemd/bunny-capability-supervisor.service").read_text(encoding="utf-8")
        for forbidden in ("ProtectControlGroups=yes", "PrivateNetwork=yes", "DynamicUser=yes"):
            with self.subTest(directive=forbidden):
                self.assertNotIn(f"\n{forbidden}", unit)

    def test_the_shipped_configuration_is_observe_only(self) -> None:
        config = json.loads(
            (ROOT / "config/bunny-os/capability-supervisor.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(config["mode"], "observe")
        self.assertFalse(config["allowEssentialStop"])
        self.assertFalse(config["directCgroupWrites"])

    def test_the_shipped_configuration_parses(self) -> None:
        sys.path.insert(0, str(ROOT))
        from capability.supervisor import SupervisorConfig

        document = json.loads(
            (ROOT / "config/bunny-os/capability-supervisor.json").read_text(encoding="utf-8"),
        )
        config = SupervisorConfig.from_json(document, source="shipped")
        self.assertEqual(config.mode, "observe")
        self.assertFalse(config.applies)

    def test_state_paths_do_not_depend_on_a_home_directory(self) -> None:
        document = json.loads(
            (ROOT / "config/bunny-os/capability-supervisor.json").read_text(encoding="utf-8"),
        )
        for key in ("stateDirectory", "runtimeDirectory", "auditPath"):
            with self.subTest(key=key):
                value = document[key]
                self.assertTrue(value.startswith(("/var", "/run", "/etc")))
                self.assertNotIn("~", value)
                self.assertNotIn("home", value)

    def test_the_preset_enables_the_supervisor(self) -> None:
        preset = (ROOT / "config/systemd/60-bunny-os.preset").read_text(encoding="utf-8")
        self.assertIn("enable bunny-capability-supervisor.service", preset)

    def test_the_tmpfiles_declaration_protects_state(self) -> None:
        conf = (ROOT / "config/tmpfiles/bunny-os.conf").read_text(encoding="utf-8")
        self.assertIn("/var/lib/bunny-os/capability 0700", conf)
        # Bounded retention on the audit directory.
        self.assertRegex(conf, r"/var/log/bunny-os 0750 root systemd-journal \d+d")


class NoSecretsOrHostStateTests(unittest.TestCase):
    """Nothing host-specific or secret may be packaged."""

    def test_no_capability_source_file_contains_a_credential_shape(self) -> None:
        import re

        pattern = re.compile(r"(?i)(api[_-]?key|secret|password)\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}")
        for path in sorted((ROOT / "capability").rglob("*.py")):
            with self.subTest(path=path.name):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_no_runtime_state_is_committed_under_capability(self) -> None:
        for name in ("reservations.json", "approvals.json", "retries.json",
                     "capability-audit.jsonl", "supervisor.lock"):
            with self.subTest(name=name):
                self.assertEqual(
                    list((ROOT / "capability").rglob(name)), [],
                    "runtime state must never be committed, let alone packaged",
                )

    def test_the_shipped_configuration_names_no_host(self) -> None:
        text = (ROOT / "config/bunny-os/capability-supervisor.json").read_text(encoding="utf-8")
        for token in ("wsl", "allam", "Users", "C:", "/root/", "/home/"):
            with self.subTest(token=token):
                self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()

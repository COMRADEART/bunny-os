# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The closure analyser, and the failure it was blind to.

``build-input-closure.py`` answers "is this change build-affecting?", and the
answer is used to decide whether a commit needs a two-build comparison. It got
that answer wrong for the whole voice runtime: it collected install routes by
walking ``install-root.py`` for calls named ``copy_tree`` or ``copy_file``, and
``companion/`` is installed by neither — it is installed by
``copy_python_package``, which the collector filtered out *before* it recorded
anything, so the call never even reached the "unresolved" list that exists to
say the closure is incomplete. Twenty installed paths were reported as
``context-only``, which reads as "probably not in the artifact".

These tests are therefore mostly *mutation* tests. Asserting that the analyser
gets today's answer right proves very little — the old one also got most answers
right, and was silent precisely where it was wrong. What has to be proved is
that it cannot go quiet again:

* a helper the route table does not model is **refused**, not skipped;
* a copy issued from outside a route stage is refused;
* a generated file nobody declared is refused;
* the installer as it stood at ``b825dd4`` is refused, so the defect that
  produced this closure could not recur unnoticed;
* renaming a helper moves no route, because routes are data.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "build/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from install_routes import (  # noqa: E402 - the path above is what makes this importable
    COPY_HELPERS,
    GENERATED_ROUTES,
    GENERATOR_FUNCTIONS,
    INSTALL_ROUTES,
    INSTALL_STAGES,
    MODELLED_HELPERS,
    PROFILES,
    audit_installer,
    installed_destination,
    route_files,
    routes_for_profile,
)


def _closure_module():
    path = SCRIPTS / "build-input-closure.py"
    spec = importlib.util.spec_from_file_location("bunny_build_input_closure", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLOSURE = _closure_module()


def _installer_module():
    path = SCRIPTS / "install-root.py"
    spec = importlib.util.spec_from_file_location("bunny_install_root", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INSTALLER = _installer_module()

#: The install set the voice runtime actually changed, derived mechanically
#: rather than counted by hand. Pinned so that a future edit to the route table
#: that quietly drops the package route fails here with the paths it lost.
VOICE_INSTALLED_PATHS = (
    "companion/character/lipsync.py",
    "companion/cli.py",
    "companion/protocol.py",
    "companion/service.py",
    "companion/voice/__init__.py",
    "companion/voice/audio.py",
    "companion/voice/captions.py",
    "companion/voice/execution.py",
    "companion/voice/pcm.py",
    "companion/voice/policy.py",
    "companion/voice/provider.py",
    "companion/voice/providers.py",
    "companion/voice/queue.py",
    "companion/voice/recovery.py",
    "companion/voice/request.py",
    "companion/voice/service.py",
    "companion/voice/system.py",
    "companion/voice/vertical_slice.py",
    "companion/voice/visemes.py",
    "companion/voice/worker.py",
    "docs/companion-voice.md",
    "schemas/companion-protocol.schema.json",
)


def _run_closure(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "build-input-closure.py"), *arguments],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _classify(path: str) -> dict:
    roots, _ = CLOSURE.build_context_roots(ROOT / "build/Containerfile")
    return CLOSURE.classify(path, roots)


class TheSharedDeclaration(unittest.TestCase):
    """One table, two consumers, and no second list anywhere."""

    def test_the_installer_and_the_analyser_read_the_same_module(self) -> None:
        installer = (SCRIPTS / "install-root.py").read_text(encoding="utf-8")
        analyser = (SCRIPTS / "build-input-closure.py").read_text(encoding="utf-8")
        self.assertIn("from install_routes import", installer)
        self.assertIn("from install_routes import", analyser)

    def test_every_declared_route_points_at_something_that_exists(self) -> None:
        """A route whose source is gone installs nothing and reports nothing."""
        for route in INSTALL_ROUTES:
            with self.subTest(route=route.id):
                self.assertTrue(
                    (ROOT / route.source).exists(),
                    f"route {route.id} names {route.source}, which is not in the repository",
                )

    def test_every_route_declares_an_absolute_destination_and_a_known_kind(self) -> None:
        for route in INSTALL_ROUTES:
            with self.subTest(route=route.id):
                self.assertIn(route.kind, {"file", "tree", "package", "glob"})
                self.assertTrue(route.destination.startswith("/"))
                self.assertIn(route.mode, {0o444, 0o555, 0o644, 0o600})

    def test_route_identifiers_are_unique(self) -> None:
        identifiers = [route.id for route in INSTALL_ROUTES]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_the_installer_selects_exactly_what_the_analyser_classifies(self) -> None:
        """The two answers come from one function, and this is the assertion of it.

        Every file the installer would copy for the ``developer`` profile is
        classified ``installed`` at the same destination by the analyser. A
        disagreement here would mean the shared predicate had been bypassed on
        one side.
        """
        roots, _ = CLOSURE.build_context_roots(ROOT / "build/Containerfile")
        checked = 0
        for route in routes_for_profile("developer"):
            if route.id == "release-payload":
                continue
            for item, destination in route_files(route, ROOT):
                relative = item.relative_to(ROOT).as_posix()
                verdict = CLOSURE.classify(relative, roots)
                self.assertEqual(
                    verdict["classification"], "installed",
                    f"the installer copies {relative} and the analyser does not say so",
                )
                self.assertIn(
                    destination, [entry["installedAs"] for entry in verdict["routes"]],
                )
                checked += 1
        self.assertGreater(checked, 500)


class TheInstalledVoicePayload(unittest.TestCase):
    """The image build checks results, not just package and route declarations."""

    @staticmethod
    def _required_files(root: Path) -> None:
        relative_paths = (
            "usr/bin/pw-record",
            "usr/bin/parec",
            "usr/bin/arecord",
            "usr/bin/espeak-ng",
            "usr/bin/spd-say",
            "usr/lib64/libvosk.so",
            "usr/lib/bunny-os/python/companion/speech/vosk_runtime.py",
            "usr/lib/systemd/user/bunny-companion.service",
            "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/.bunny-model.json",
            "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/am/final.mdl",
            "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/graph/Gr.fst",
            "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/graph/HCLr.fst",
            "usr/share/licenses/bunny-os-voice/Apache-2.0.txt",
            "usr/share/doc/bunny-os/voice-provenance.json",
        )
        for relative in relative_paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"present")

    def test_a_desktop_build_refuses_an_empty_voice_route(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bunny-voice-image-") as temporary:
            with self.assertRaisesRegex(SystemExit, "voice payload is incomplete"):
                INSTALLER.assert_voice_image_payload("beta", {}, root=Path(temporary))

    def test_a_complete_desktop_payload_passes_the_postcondition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bunny-voice-image-") as temporary:
            root = Path(temporary)
            self._required_files(root)
            installed = {
                route_id: [f"/{route_id}"]
                for route_id in (
                    "companion-package",
                    "speech-recognition-models",
                    "speech-recognition-licenses",
                    "speech-recognition-provenance",
                    "user-units",
                )
            }
            INSTALLER.assert_voice_image_payload("beta", installed, root=root)

    def test_a_non_desktop_profile_does_not_require_voice(self) -> None:
        INSTALLER.assert_voice_image_payload("minimal", {}, root=Path("unused"))


class ThePackageRoute(unittest.TestCase):
    """``copy_python_package`` — the route the old analyser did not model."""

    def test_a_package_copied_through_copy_python_package_is_reported(self) -> None:
        for path in ("companion/__init__.py", "capability/__init__.py"):
            with self.subTest(path=path):
                verdict = _classify(path)
                self.assertEqual(verdict["classification"], "installed")

    def test_a_changed_file_beneath_that_package_is_reported(self) -> None:
        verdict = _classify("companion/voice/worker.py")
        self.assertEqual(verdict["classification"], "installed")
        self.assertEqual(
            [route["installedAs"] for route in verdict["routes"]],
            ["/usr/lib/bunny-os/python/companion/voice/worker.py"],
        )
        self.assertEqual(verdict["routes"][0]["routeId"], "companion-package")
        self.assertEqual(verdict["routes"][0]["mode"], "0o444")

    def test_a_deeply_nested_new_module_is_reported(self) -> None:
        """The route is a prefix rule, not a file list; depth is irrelevant."""
        verdict = _classify("companion/voice/backends/experimental/thing.py")
        self.assertEqual(verdict["classification"], "installed")
        self.assertEqual(
            verdict["routes"][0]["installedAs"],
            "/usr/lib/bunny-os/python/companion/voice/backends/experimental/thing.py",
        )

    def test_an_excluded_test_or_bytecode_file_is_not_reported(self) -> None:
        excluded = (
            "companion/__pycache__/service.cpython-314.pyc",
            "companion/voice/__pycache__/worker.cpython-314.pyc",
            "companion/tests/test_thing.py",
            "capability/testing/probe.py",
            "capability/tests/test_engine.py",
            # Not Python: a package route installs source and only source.
            "companion/voice/notes.md",
        )
        for path in excluded:
            with self.subTest(path=path):
                verdict = _classify(path)
                self.assertNotEqual(
                    verdict["classification"], "installed",
                    f"{path} must not reach the image",
                )
                self.assertEqual(verdict["routes"], [])

    def test_the_package_route_is_the_only_reason_the_voice_runtime_is_installed(self) -> None:
        """Named, so that deleting the route fails with the reason attached."""
        package_routes = [route for route in INSTALL_ROUTES if route.kind == "package"]
        self.assertEqual(
            sorted(route.source for route in package_routes), ["capability", "companion"],
        )


class TheAuditFailsClosed(unittest.TestCase):
    """An installer the table does not describe produces no answer at all."""

    def test_the_real_installer_passes(self) -> None:
        self.assertEqual(audit_installer(SCRIPTS / "install-root.py"), [])

    def test_an_unknown_copy_helper_fails_closed(self) -> None:
        source = (
            "import shutil\n"
            "def copy_secret_thing(a, b):\n"
            "    shutil.copyfile(a, b)\n"
            "def main():\n"
            "    copy_secret_thing('x', '/usr/lib/x')\n"
        )
        complaints = audit_installer("synthetic.py", source=source)
        self.assertTrue(complaints)
        self.assertTrue(any("copy_secret_thing" in item for item in complaints))

    def test_a_newly_added_install_helper_fails_until_modelled(self) -> None:
        source = (
            "def install_extra_assets(source, root):\n"
            "    copy_file(source, root, 0o444)\n"
            "def main():\n"
            "    install_extra_assets('a', 'b')\n"
        )
        complaints = audit_installer("synthetic.py", source=source)
        self.assertTrue(any("install_extra_assets" in item for item in complaints))

    def test_a_copy_issued_outside_a_route_stage_fails_closed(self) -> None:
        """The rule that stops ``main`` installing something off-table."""
        source = (
            "def copy_file(a, b, mode):\n"
            "    pass\n"
            "def main():\n"
            "    copy_file('extra.json', '/usr/share/extra.json', 0o444)\n"
        )
        complaints = audit_installer("synthetic.py", source=source)
        self.assertTrue(any("not declared in INSTALL_ROUTES" in item for item in complaints))

    def test_a_stdlib_copy_outside_a_copy_helper_fails_closed(self) -> None:
        source = (
            "import shutil\n"
            "def stage_something(a, b):\n"
            "    shutil.copy2(a, b)\n"
        )
        complaints = audit_installer("synthetic.py", source=source)
        self.assertTrue(any("copy2" in item for item in complaints))

    def test_an_undeclared_generated_file_fails_closed(self) -> None:
        source = (
            "def emit_marker(root):\n"
            "    (root / 'usr/share/marker').write_text('x')\n"
        )
        complaints = audit_installer("synthetic.py", source=source)
        self.assertTrue(any("GENERATOR_FUNCTIONS" in item for item in complaints))

    def test_the_installer_as_it_stood_at_the_base_commit_is_refused(self) -> None:
        """The defect this closure exists to fix would now stop the gate.

        ``b825dd4``'s installer defined ``copy_python_package`` and called every
        copy helper straight from ``main``. Under the audit that installer
        cannot produce a closure at all, which is the correct answer: the
        analyser of the day could not describe it, and said nothing.
        """
        source = (
            "import shutil\n"
            "def copy_file(source, destination, mode):\n"
            "    shutil.copyfile(source, destination)\n"
            "def copy_python_package(source, destination):\n"
            "    for item in sorted(source.rglob('*.py')):\n"
            "        copy_file(item, destination, 0o444)\n"
            "def main():\n"
            "    copy_python_package(source / 'companion', Path('/usr/lib/x'))\n"
        )
        complaints = audit_installer("install-root.py", source=source)
        self.assertTrue(any("copy_python_package" in item for item in complaints))

    def test_a_refused_installer_produces_exit_two_and_no_claim(self) -> None:
        """End to end: the analyser refuses to answer rather than understating."""
        original = (SCRIPTS / "install-root.py").read_bytes()
        mutated = original.decode("utf-8") + (
            "\n\ndef copy_one_more_thing(source, destination):\n"
            "    copy_file(source, destination, 0o444)\n"
        )
        try:
            (SCRIPTS / "install-root.py").write_text(mutated, encoding="utf-8", newline="\n")
            result = _run_closure("--paths", "companion/voice/worker.py")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("BLOCKED", result.stderr)
            self.assertIn("copy_one_more_thing", result.stderr)
            self.assertNotIn("BUILD-AFFECTING", result.stdout)
        finally:
            (SCRIPTS / "install-root.py").write_bytes(original)
        self.assertEqual((SCRIPTS / "install-root.py").read_bytes(), original)


class ARenameMovesNoRoute(unittest.TestCase):
    """Coverage lives in the table, so it cannot be lost by renaming a function."""

    def test_renaming_the_helper_changes_no_classification(self) -> None:
        before = _classify("companion/voice/worker.py")
        original = (SCRIPTS / "install-root.py").read_bytes()
        mutated = original.decode("utf-8").replace("def copy_route(", "def copy_route_v2(") \
                                          .replace("copy_route(route,", "copy_route_v2(route,")
        try:
            (SCRIPTS / "install-root.py").write_text(mutated, encoding="utf-8", newline="\n")
            after = _classify("companion/voice/worker.py")
            self.assertEqual(before["classification"], after["classification"])
            self.assertEqual(
                [item["installedAs"] for item in before["routes"]],
                [item["installedAs"] for item in after["routes"]],
            )
            # And the rename is still reported, because the new name is not modelled.
            complaints = audit_installer(SCRIPTS / "install-root.py")
            self.assertTrue(any("copy_route_v2" in item for item in complaints))
        finally:
            (SCRIPTS / "install-root.py").write_bytes(original)
        self.assertEqual((SCRIPTS / "install-root.py").read_bytes(), original)

    def test_the_modelled_helper_set_is_pinned(self) -> None:
        """Adding a helper or a stage fails here until it is declared deliberately."""
        self.assertEqual(dict(COPY_HELPERS), {"copy_file": "file", "copy_route": "route-engine"})
        self.assertEqual(
            INSTALL_STAGES,
            frozenset({"install_all_routes", "install_release_payload", "install_activation"}),
        )
        self.assertEqual(
            GENERATOR_FUNCTIONS,
            frozenset({
                "write_release_metadata",
                "write_package_inventory",
                # Writes /usr/lib/os-release so the machine stops calling itself
                # "Fedora Linux 44" in every system surface. Declared with a full
                # GENERATED_ROUTES entry naming its destination, what it derives
                # from and what produces it, which is the bar this pin exists to
                # hold a generator to.
                "write_os_release",
            }),
        )
        self.assertEqual(len(MODELLED_HELPERS), 8)

    def test_every_generated_route_names_what_produces_it(self) -> None:
        for entry in GENERATED_ROUTES:
            with self.subTest(destination=entry["destination"]):
                self.assertTrue(entry["derivedFrom"])
                self.assertTrue(entry["producer"])


class TheRangesThisClosureIsAbout(unittest.TestCase):
    """The three ranges the report makes claims about, computed mechanically."""

    @staticmethod
    def _range(revisions: str) -> dict:
        result = _run_closure("--range", revisions, "--json")
        if result.returncode == 2:  # pragma: no cover - the repository is a git checkout
            raise unittest.SkipTest(f"closure refused: {result.stderr.strip()}")
        return json.loads(result.stdout)

    def test_the_pre_branch_range_remains_non_build_affecting(self) -> None:
        document = self._range("66652d0..dfb0cd7")
        self.assertFalse(document["summary"]["buildAffecting"])
        self.assertEqual(document["summary"]["installed"], 0)

    def test_the_post_gate_range_remains_non_build_affecting(self) -> None:
        """0cf81a1..b825dd4 — the commits after the gate commit."""
        document = self._range("0cf81a1..b825dd4")
        self.assertFalse(document["summary"]["buildAffecting"])
        self.assertEqual(document["summary"]["installed"], 0)
        self.assertEqual(document["summary"]["contextOnly"], 0)

    def test_the_voice_branch_reports_the_complete_installed_path_set(self) -> None:
        """22 paths, and the 20 the old analyser missed are all package-route paths."""
        document = self._range("dfb0cd7..b825dd4")
        self.assertTrue(document["summary"]["buildAffecting"])
        self.assertEqual(
            tuple(item["path"] for item in document["installed"]), VOICE_INSTALLED_PATHS,
        )
        by_route: dict[str, int] = {}
        for item in document["installed"]:
            for route in item["routes"]:
                by_route[route["routeId"]] = by_route.get(route["routeId"], 0) + 1
        self.assertEqual(by_route, {"companion-package": 20, "documentation": 1, "schemas": 1})

    def test_a_deliberate_mutation_to_one_voice_module_is_reported(self) -> None:
        """An actual edit to an actual installed file, then restored."""
        target = ROOT / "companion/voice/worker.py"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n# closure mutation probe\n")
            result = _run_closure("--range", "HEAD", "--json")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            document = json.loads(result.stdout)
            self.assertTrue(document["summary"]["buildAffecting"])
            installed = {item["path"] for item in document["installed"]}
            self.assertIn("companion/voice/worker.py", installed)
        finally:
            target.write_bytes(original)
        self.assertEqual(target.read_bytes(), original)


class TheProfileDimension(unittest.TestCase):
    """Conditional installation, which the old analyser did not model at all."""

    def test_a_character_asset_is_installed_only_on_desktop_profiles(self) -> None:
        verdict = _classify("assets/companion/characters/default-bunny/manifest.json")
        self.assertEqual(verdict["classification"], "installed")
        self.assertEqual(
            verdict["profiles"],
            ["beta", "desktop", "developer", "live", "shell", "shell-test"],
        )
        self.assertNotIn("minimal", verdict["profiles"])
        self.assertNotIn("recovery", verdict["profiles"])

    def test_a_live_only_file_names_only_the_live_profile(self) -> None:
        verdict = _classify("installer/config/iso.yaml")
        self.assertEqual(verdict["classification"], "installed")
        self.assertIn("/usr/lib/image-builder/bootc/iso.yaml",
                      [item["installedAs"] for item in verdict["routes"]])
        live = [item for item in verdict["routes"] if item["routeId"] == "live-iso-config"]
        self.assertEqual(live[0]["profiles"], ["live"])

    def test_a_destination_override_is_honoured(self) -> None:
        verdict = _classify("installer/bin/bunny-installer-backend")
        installed = [item["installedAs"] for item in verdict["routes"]]
        self.assertIn("/usr/libexec/bunny-installer-backend", installed)
        self.assertNotIn("/usr/bin/bunny-installer-backend", installed)

    def test_a_user_unit_lands_only_under_the_user_directory(self) -> None:
        """The installer used to write these into the system directory and delete them."""
        candidates = sorted((ROOT / "systemd/user").glob("*.service"))
        self.assertTrue(candidates)
        relative = candidates[0].relative_to(ROOT).as_posix()
        verdict = _classify(relative)
        installed = [item["installedAs"] for item in verdict["routes"]]
        self.assertEqual(installed, [f"/usr/lib/systemd/user/{candidates[0].name}"])

    def test_every_profile_resolves(self) -> None:
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertTrue(routes_for_profile(profile))


class ThePredicateItself(unittest.TestCase):
    """``installed_destination`` is the whole of the agreement; test it directly."""

    def test_a_file_route_matches_only_that_file(self) -> None:
        route = next(item for item in INSTALL_ROUTES if item.id == "readme")
        self.assertEqual(installed_destination(route, "README.md"), "/usr/share/doc/bunny-os/README.md")
        self.assertIsNone(installed_destination(route, "README.md.bak"))
        self.assertIsNone(installed_destination(route, "docs/README.md"))

    def test_a_glob_route_is_flat(self) -> None:
        route = next(item for item in INSTALL_ROUTES if item.id == "shell-commands")
        self.assertEqual(installed_destination(route, "shell/services/bin/bunny-shell"), "/usr/bin/bunny-shell")
        self.assertIsNone(installed_destination(route, "shell/services/bin/nested/thing"))

    def test_a_tree_route_skips_build_residue(self) -> None:
        route = next(item for item in INSTALL_ROUTES if item.id == "documentation")
        self.assertEqual(installed_destination(route, "docs/a.md"), "/usr/share/doc/bunny-os/a.md")
        self.assertIsNone(installed_destination(route, "docs/__pycache__/a.pyc"))
        self.assertIsNone(installed_destination(route, "docs/node_modules/a.md"))

    def test_the_predicate_answers_for_a_path_that_no_longer_exists(self) -> None:
        """A deleted installed file is build-affecting, and must classify as one."""
        verdict = _classify("companion/voice/deleted_module.py")
        self.assertEqual(verdict["classification"], "installed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

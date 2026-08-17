# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from companion import cli as companion_cli
from companion.character.defaults import default_character_path
from companion.character.demo import run_character_demo
from companion.character.diagnostics import selected_package
from companion.character.importer import CharacterPackageImporter, PackageRegistry
from companion.character.mapper import map_character_state
from companion.character.vertical_slice import run_character_slice
from companion.character.performance import measure_renderer_performance
from companion.character.package import validate_package_directory


def diagnose(document: dict) -> str:
    """Everything the report knows about why the slice failed, in the message.

    ``self.assertTrue(report.passed, report.failures)`` prints the step names
    and nothing else, and the step names for this failure have read

        ['step 17 (trigger controlled presentation pressure)',
         'step 21 (recover only after hysteresis)']

    on and off for four phases without anybody being able to say why. The
    answer was in the report the whole time: step 17 carries
    ``incidentalRendererFault``, ``retryCleanOfFaults`` and the renderer events
    with the *exception text* on them. Nothing printed it, so every
    investigation started from a step number.

    The Phase 4 rule this applies: make the thing that failed report what it
    saw. That diagnosis would have been one field long.
    """
    steps = {item["step"]: item for item in document.get("steps", [])}
    lines = [f"slice failures: {document.get('failures')}"]
    seventeen = steps.get(17, {})
    lines.append(
        "step 17: presentation={presentation!r} incidentalRendererFault={fault!r} "
        "retryCleanOfFaults={retry!r}".format(
            presentation=seventeen.get("presentation"),
            fault=seventeen.get("incidentalRendererFault"),
            retry=seventeen.get("retryCleanOfFaults"),
        )
    )
    for event in seventeen.get("rendererEvents", []):
        lines.append(f"  event: {event}")
    twenty_one = steps.get(21, {})
    lines.append(
        "step 21: presentation={presentation!r} samplesBeforeRecovery={samples!r}".format(
            presentation=twenty_one.get("presentation"),
            samples=twenty_one.get("samplesBeforeRecovery"),
        )
    )
    for number in (18, 19, 20):
        step = steps.get(number, {})
        lines.append(f"step {number}: presentation={step.get('presentation')!r} ok={step.get('ok')!r}")
    return "\n".join(lines)


def parse(*argv: str, root: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bunny-os")
    sub = parser.add_subparsers(dest="command", required=True)
    companion_cli.add_arguments(sub)
    return parser.parse_args(["companion", "--root", str(root), "--simulate", "laptop", *argv])


class CharacterCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-character-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def command(self, *argv: str) -> dict:
        result = companion_cli.dispatch(parse(*argv, root=self.root))
        json.dumps(result)
        return result

    def test_exact_diagnostic_command_tree_exists(self) -> None:
        for argv in (
            ("character", "list"),
            ("character", "inspect", "org.bunny-os.default-bunny"),
            ("character", "validate", str(default_character_path())),
            ("character", "import", str(default_character_path())),
            ("character", "select", "org.bunny-os.default-bunny"),
            ("character", "trust", "0" * 64, "disabled"),
            ("renderer", "status"),
            ("renderer", "explain"),
            ("renderer", "demo"),
        ):
            with self.subTest(argv=argv):
                parsed = parse(*argv, root=self.root)
                self.assertEqual(parsed.command, "companion")

    def test_character_list_inspect_and_validate_are_read_only(self) -> None:
        listing = self.command("character", "list")
        self.assertEqual(listing["effect"], "read-only")
        self.assertEqual(listing["packages"][0]["trustState"], "built-in")
        inspected = self.command("character", "inspect", "org.bunny-os.default-bunny")
        self.assertEqual(inspected["effect"], "read-only")
        validated = self.command("character", "validate", str(default_character_path()))
        self.assertEqual(validated["effect"], "read-only")
        self.assertFalse(validated["validation"]["creatorTrusted"])

    def test_import_and_select_name_their_mutation(self) -> None:
        imported = self.command("character", "import", str(default_character_path()))
        self.assertIn("IMPORTED", imported["effect"])
        self.assertFalse(imported["package"]["creatorTrusted"])
        selected = self.command("character", "select", imported["package"]["packageId"],
                                "--digest", imported["package"]["packageDigest"])
        self.assertIn("SELECTED", selected["effect"])

    def test_renderer_status_uses_capability_plan(self) -> None:
        status = self.command("renderer", "status")
        self.assertEqual(status["effect"], "read-only")
        self.assertIn(status["presentation"]["effectivePresentation"],
                      {"text-only", "static-image", "animated-2d"})
        self.assertTrue(status["capabilityPlan"]["planId"])
        self.assertIn("resourceDeclaration", status)
        self.assertIn("observedResourceUse", status)
        self.assertIn("missingStates", status)
        self.assertIn("rendererErrors", status)
        self.assertIn("SIMULATED HARDWARE", status["simulationBanner"])

    def test_invalid_package_cli_returns_structured_json_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "tools/bunny-os/bin/bunny-os",
                "--json",
                "companion",
                "character",
                "validate",
                str(self.root / "missing"),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        document = json.loads(result.stdout)
        self.assertFalse(document["ok"])
        self.assertEqual(document["error"]["code"], "companion_refused")

    def test_corrupt_selected_package_falls_back_to_builtin(self) -> None:
        registry = PackageRegistry(
            self.root / "fallback-registry", built_in_paths=(default_character_path(),)
        )
        imported = CharacterPackageImporter(registry).import_package(default_character_path())
        registry.select(imported.package_id, package_digest=imported.package_digest)
        frame = next(imported.path.glob("assets/*.png"))
        frame.write_bytes(b"corrupt after installation")
        selected, package, event = selected_package(registry)
        self.assertEqual(selected.trust_state.value, "built-in")
        self.assertEqual(package.trust_state.value, "built-in")
        self.assertEqual(event["eventType"], "renderer.package-fallback")
        self.assertTrue(event["taskContinues"])

    def test_renderer_explain_shows_state_fallback_and_trust(self) -> None:
        """§5: the fallback path used must be visible to a person."""
        explained = self.command("renderer", "explain")["explanation"]
        self.assertTrue(explained["fallbackChain"])
        self.assertTrue(explained["characterState"])
        self.assertTrue(explained["priorityReason"])
        self.assertEqual(explained["trustState"], "built-in")
        self.assertTrue(explained["integrityVerified"])
        # §4: integrity is not creator trust, and the diagnostic says so.
        self.assertIn("does not establish creator trust", explained["note"])
        # This asserted that the note named ``animated-2d`` as the top of what
        # the build implemented. Since the 3D renderer landed there is no rung
        # above what is implemented, so the note says *that* instead — and the
        # property worth keeping is that the note is about which rung is drawn
        # and why, not that it names one particular rung for ever.
        self.assertIn("capability projection", explained["note"])
        self.assertIn("selected package", explained["note"])

    def test_renderer_demo_command_runs_all_steps(self) -> None:
        result = self.command("renderer", "demo", "--demo-root", str(self.root / "demo"))
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(len(result["steps"]), 23)
        self.assertEqual(result["commercialProvider"], "none")
        three_d = result["threeDimensionalRenderer"]
        self.assertIsInstance(three_d, dict)
        self.assertTrue(three_d["shipped"])
        self.assertFalse(three_d["exercisedInThisSlice"])
        self.assertNotIn("not implemented", json.dumps(result))


class VerticalSliceAndPerformanceTests(unittest.TestCase):
    """One slice run, many assertions — see the note in test_integration_slice."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="bunny-character-slice-")
        cls.report = run_character_slice(Path(cls._directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._directory.cleanup()

    def test_a_completed_task_maps_to_success_not_a_stale_review_warning(self) -> None:
        """The canonical projection decides; a spent disagreement is history.

        Driven through the *real* service and the canonical projection rather
        than through a helper that re-read the store — the helper this replaces
        was the second interpretation of the record that §2 forbids.
        """
        self.assertTrue(self.report.passed, diagnose(self.report.to_json()))
        steps = {item["step"]: item for item in self.report.to_json()["steps"]}
        self.assertEqual(steps[16]["characterState"], "success")
        self.assertEqual(steps[24]["after"]["state"], "completed")

    def test_the_installed_slice_exercises_the_required_renderer_story(self) -> None:
        document = self.report.to_json()
        self.assertTrue(document["passed"], diagnose(document))
        names = [step["name"] for step in document["steps"]]
        for required in (
            "load the validated default character package",
            "anchor the approval bubble to the character",
            "play generic lip-sync events",
            "degrade animated 2D to static",
            "degrade static to text-only",
            "recover only after hysteresis",
            "restart the renderer",
            "verify the task never restarted or was cancelled",
        ):
            self.assertIn(required, names)
        # What the host could not run is reported as NOT_RUN, never as a pass.
        self.assertTrue(document["notRun"])
        self.assertFalse(document["gtkWidgetsExercised"])
        for step in document["steps"]:
            self.assertIn(step.get("ok"), (True, None))

    def test_the_slice_reports_the_shipped_3d_renderer_truthfully(self) -> None:
        """The 3D renderer ships; a slice that does not exercise it says so.

        This field read "not implemented" for two phases after the renderer
        landed — evidence emitters must claim the rung they exercised, never
        deny a capability that ships.
        """
        document = self.report.to_json()
        three_d = document["threeDimensionalRenderer"]
        self.assertIsInstance(three_d, dict)
        self.assertTrue(three_d["shipped"])
        self.assertFalse(three_d["exercisedInThisSlice"])
        self.assertNotIn("not implemented", json.dumps(document))

    def test_performance_measurement_has_every_required_dimension_and_scope(self) -> None:
        package = validate_package_directory(default_character_path())
        result = measure_renderer_performance(package)
        for key in (
            "packageLoadMs", "staticImageMemoryBytes", "animatedRendererMemoryBytes",
            "idleCpuPercent", "activeAnimationCpuPercent",
            "averageFrameTickMs", "droppedFramesInIntentionalGap",
            "bubbleUpdateMicroseconds", "stateTransitionMs", "rendererRestartMs", "packageImportMs",
        ):
            with self.subTest(key=key):
                self.assertIn(key, result)
                self.assertGreaterEqual(result[key], 0)
        self.assertIn("No Raspberry Pi", result["scope"])
        self.assertGreaterEqual(result["idleCpuSampleMs"], 150)
        self.assertGreaterEqual(result["activeAnimationCpuSampleMs"], 450)
        decisions = {
            item["budget"]: item["effectivePresentation"]
            for item in result["representativeBudgetDecisions"]
        }
        self.assertEqual(decisions["text-only-ceiling"], "text-only")
        self.assertEqual(decisions["static-ceiling"], "static-image")
        self.assertEqual(decisions["animation-fits"], "animated-2d")
        self.assertEqual(decisions["runtime-memory-pressure"], "static-image")


class IncidentalRendererFaultTests(unittest.TestCase):
    """The load flake, pinned: one transient renderer fault must not read as
    a selector defect.

    Steps 17 and 21 flipped ~2-in-12 on a loaded host across three phases,
    and the pair reproduces deterministically from a single injected fault:
    the fault parks the presenter unhealthy for 15 renderer-seconds, the
    slice advances ~11 synthetic seconds for its whole remainder, and the
    report blamed the pressure/hysteresis steps without naming the fault.
    """

    def _run_with_faults(self, fail_calls: set[int] | None, persistent_from: int | None = None):
        import companion.character.controller as controller_module

        calls = {"n": 0}
        original = controller_module.CharacterRendererController.apply

        def flaky(inner_self, *args, **kwargs):
            calls["n"] += 1
            if fail_calls and calls["n"] in fail_calls:
                raise RuntimeError("injected transient renderer fault")
            # Every third call from the threshold, not every call: one update
            # may retry apply() up to three times on its internal fallback
            # ladder, and a fault on all of them would break the ladder's own
            # "text-only cannot fail" contract — a different defect than the
            # recurring-fault this control simulates.
            if persistent_from is not None and calls["n"] >= persistent_from \
                    and (calls["n"] - persistent_from) % 3 == 0:
                raise RuntimeError("injected recurring renderer fault")
            return original(inner_self, *args, **kwargs)

        controller_module.CharacterRendererController.apply = flaky
        self.addCleanup(
            setattr, controller_module.CharacterRendererController, "apply", original
        )
        with tempfile.TemporaryDirectory(prefix="bunny-fault-slice-") as root:
            return run_character_slice(Path(root))

    def test_one_transient_fault_recovers_and_is_named_in_evidence(self) -> None:
        report = self._run_with_faults({10})
        document = report.to_json()
        self.assertTrue(document["passed"], diagnose(document))
        step_17 = next(s for s in document["steps"] if s["step"] == 17)
        self.assertTrue(step_17.get("incidentalRendererFault"),
                        "the fault recovered silently; evidence must name it")
        self.assertTrue(step_17.get("retryCleanOfFaults"))

    def test_a_persistent_fault_still_fails_and_names_itself(self) -> None:
        """The negative control: the retry must not absorb a real defect."""
        report = self._run_with_faults(None, persistent_from=40)
        document = report.to_json()
        self.assertFalse(document["passed"])
        step_17 = next(s for s in document["steps"] if s["step"] == 17)
        self.assertTrue(step_17.get("incidentalRendererFault"))
        self.assertFalse(step_17.get("retryCleanOfFaults", True))


class BuildAndBoundaryTests(unittest.TestCase):
    def test_installed_image_copies_runtime_renderer_and_data_assets(self) -> None:
        """Asserted against the declaration the installer is driven by.

        This used to search ``install-root.py`` for the string
        ``source / "companion"``, which is how a test can pass while the thing
        it is about is broken: the string was there, the package was installed,
        and the closure analyser that read the same file for the same substrings
        still reported the whole package as not reaching the image. The install
        set is now data in ``build/scripts/install_routes.py``, so this asserts
        the route rather than the spelling of the call that executes it.
        """
        import sys as _sys

        scripts = Path("build/scripts").resolve()
        if str(scripts) not in _sys.path:
            _sys.path.insert(0, str(scripts))
        from install_routes import INSTALL_ROUTES

        routes = {route.source: route for route in INSTALL_ROUTES}
        self.assertEqual(routes["companion"].kind, "package")
        self.assertEqual(routes["companion"].destination, "/usr/lib/bunny-os/python/companion")
        self.assertEqual(routes["capability"].kind, "package")
        self.assertEqual(routes["capability"].destination, "/usr/lib/bunny-os/python/capability")
        self.assertEqual(
            routes["capability/services"].destination,
            "/usr/share/bunny-os/capability/services",
        )
        characters = routes["assets/companion/characters"]
        self.assertEqual(characters.destination, "/usr/share/bunny-os/companion/characters")
        self.assertEqual(characters.mode, 0o444)
        containerfile = Path("build/Containerfile").read_text(encoding="utf-8")
        for source in ("assets", "capability", "companion"):
            self.assertIn(f"COPY {source} /tmp/bunny-os/{source}", containerfile)

    def test_there_is_one_client_and_no_second_character_application(self) -> None:
        """One restartable client, decided in the integration phase.

        The renderer's first implementation shipped its own window, its own
        desktop entry and its own store poller. Two clients would be two things
        polling the same runtime and two places a user could be shown a
        different answer, so the character renders inside the companion window
        instead.
        """
        self.assertFalse(Path("shell/services/bin/bunny-companion-character").exists())
        self.assertFalse(Path(
            "shell/components/applications/art.comrade.BunnyCompanionCharacter.desktop"
        ).exists())
        self.assertTrue(Path("shell/services/bin/bunny-companion").is_file())

    def test_the_surface_is_headless_import_safe(self) -> None:
        import companion.character.surface as surface

        self.assertTrue(hasattr(surface, "CharacterPresenter"))
        source = Path("companion/character/surface.py").read_text(encoding="utf-8")
        self.assertNotIn("import gi", source.split('"""')[-1])


    def test_the_surface_never_reads_the_record_directly(self) -> None:
        """§2: no second reader of tasks or events."""
        import ast

        for name in ("surface.py", "integration.py", "mapper.py"):
            tree = ast.parse(Path(f"companion/character/{name}").read_text(encoding="utf-8"))
            reached = {
                node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            for forbidden in ("companion.store", "companion.events", "companion.task"):
                with self.subTest(module=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, reached)

    def test_default_package_contains_no_executable_or_active_content(self) -> None:
        suffixes = {path.suffix.casefold() for path in default_character_path().rglob("*") if path.is_file()}
        self.assertEqual(suffixes, {".json", ".txt", ".png"})
        self.assertFalse(suffixes & {".py", ".js", ".sh", ".svg", ".html", ".so", ".dll"})

    def test_renderer_controller_has_no_runtime_execution_dependency(self) -> None:
        source = Path("companion/character/controller.py").read_text(encoding="utf-8")
        for forbidden in ("CompanionRuntime", "ToolBroker", "grant_approval", "cancel_task", "choose_provider"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_3d_renderer_lives_in_its_package_not_a_top_level_module(self) -> None:
        files = "\n".join(path.name for path in Path("companion/character").glob("*.py"))
        self.assertNotIn("3d_renderer", files.casefold())
        self.assertFalse(Path("companion/character/three_d_renderer.py").exists())
        self.assertTrue(Path("companion/character/three_d/renderer.py").exists())


if __name__ == "__main__":
    unittest.main()
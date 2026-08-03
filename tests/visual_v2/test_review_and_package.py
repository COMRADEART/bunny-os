from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

from tests.support import ROOT


SCENARIO_IDS = (
    "regular-empty-desktop",
    "regular-command-palette",
    "regular-quick-settings",
    "regular-assistant-ready",
    "regular-approval",
    "regular-privacy-local-only",
    "regular-focus-mode",
    "regular-compact-layout",
    "regular-light-theme",
    "regular-high-contrast",
    "regular-offline",
    "regular-error",
    "character-welcome",
    "character-assistant-ready",
    "character-thinking",
    "character-explaining",
    "character-requesting-approval",
    "character-task-running",
    "character-task-completed",
    "character-warning",
    "character-error",
    "character-offline",
    "character-privacy-mode",
    "character-compact-layout",
    "character-focus-mode",
    "character-200-percent-scaling",
)
NOTICE = ("VISUAL PROTOTYPE ONLY", "NOT RELEASE QUALIFIED", "DO NOT MERGE INTO MAIN")


class VisualV2ReviewAndPackageTests(unittest.TestCase):
    def test_all_v2_reports_carry_the_exact_non_release_notice(self) -> None:
        documents = list((ROOT / "visual-v2").rglob("*.md")) + [
            ROOT / "VISUAL_PHASE_V2_REPORT.md",
            ROOT / "docs/BUNNY_DESKTOP_V2_ARCHITECTURE.md",
            ROOT / "docs/BUNNY_DUAL_MODE_STATE_MODEL.md",
            ROOT / "docs/BUNNY_VISUAL_SECURITY_BOUNDARY.md",
            ROOT / "docs/VISUAL_PHASE_V3_OPTIONS.md",
        ]
        for document in documents:
            value = document.read_text(encoding="utf-8")
            for notice in NOTICE:
                self.assertIn(notice, value, document.relative_to(ROOT).as_posix())

    def test_exact_screenshot_inventory_is_deterministic_and_mock_labelled(self) -> None:
        data = json.loads((ROOT / "visual-v2/screenshots/scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(item["id"] for item in data["scenarios"]), SCENARIO_IDS)
        for scenario in data["scenarios"]:
            svg = (ROOT / f"visual-v2/screenshots/rendered/{scenario['id']}.svg").read_text(encoding="utf-8")
            self.assertIn("VISUAL MOCK DATA", svg)
            self.assertIn(scenario["id"], svg)

    def test_regular_renders_have_no_character_residue(self) -> None:
        for scenario_id in SCENARIO_IDS[:12]:
            svg = (ROOT / f"visual-v2/screenshots/rendered/{scenario_id}.svg").read_text(encoding="utf-8")
            self.assertNotIn("<image", svg, scenario_id)

    def test_character_renders_have_at_most_one_guide_and_responsive_suppression(self) -> None:
        scenarios = json.loads((ROOT / "visual-v2/screenshots/scenarios.json").read_text(encoding="utf-8"))["scenarios"]
        for scenario in scenarios[12:]:
            svg = (ROOT / f"visual-v2/screenshots/rendered/{scenario['id']}.svg").read_text(encoding="utf-8")
            count = svg.count("<image")
            self.assertLessEqual(count, 1, scenario["id"])
            if scenario.get("characterSuppressed"):
                self.assertEqual(count, 0, scenario["id"])
            else:
                self.assertEqual(count, 1, scenario["id"])
        approval = (ROOT / "visual-v2/screenshots/rendered/character-requesting-approval.svg").read_text(encoding="utf-8")
        for control in ("Inspect details", "Deny", "Approve"):
            self.assertIn(control, approval)

    def test_system_concepts_are_character_free_and_never_replace_system_themes(self) -> None:
        manifest = json.loads((ROOT / "visual-v2/assets/system-concepts.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["installedAsBootTheme"])
        self.assertFalse(manifest["installedAsGdmTheme"])
        self.assertFalse(manifest["characterAllowed"])
        self.assertEqual(len(manifest["files"]), 5)
        combined = ""
        for relative in manifest["files"]:
            svg = (ROOT / "visual-v2/assets" / relative).read_text(encoding="utf-8")
            self.assertNotIn("<image", svg)
            for notice in NOTICE:
                self.assertIn(notice, svg)
            combined += svg
        for required in ("Keyboard", "Accessibility", "Network", "Power", "GNOME", "Bunny Desktop Preview"):
            self.assertIn(required, combined)

    def test_staged_prototype_excludes_mock_fixtures_and_release_mutations(self) -> None:
        entry = ROOT / "visual-v2/tools/visual_v2.py"
        spec = importlib.util.spec_from_file_location("bunny_visual_v2_entry", entry)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = module.stage_package()
        self.assertEqual(tuple(manifest["status"]), NOTICE)
        self.assertFalse(manifest["defaultSessionChanged"])
        self.assertFalse(manifest["qualificationTargetsChanged"])
        self.assertFalse(manifest["releaseGatesChanged"])
        self.assertFalse(manifest["mockFixturePackaged"])
        paths = {item["path"] for item in manifest["files"]}
        self.assertFalse(any("mock-state" in path or "screenshots" in path for path in paths))
        self.assertIn("usr/share/doc/bunny-visual-v2/PROTOTYPE-NOTICE.txt", paths)
        self.assertIn("usr/share/doc/bunny-visual-v2/VISUAL_PHASE_V2_REPORT.md", paths)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import py_compile
import sys
import unittest

from tests.support import ROOT


EXTENSION = ROOT / "shell/bunny-shell-extension"
sys.path.insert(0, str(ROOT / "apps/common"))
from bunny_visual.runtime import normalize  # noqa: E402


class InteractionSurfaceTests(unittest.TestCase):
    def test_command_palette_is_keyboard_first_and_non_privileged(self) -> None:
        source = (EXTENSION / "components/commandPalette.js").read_text(encoding="utf-8")
        for capability in ("WINDOWS", "APPLICATIONS", "WORKSPACES", "SETTINGS & SYSTEM", "RECENT", "POWER"):
            self.assertIn(capability, source)
        for key in ("KEY_Down", "KEY_Up", "KEY_Return", "KEY_Escape"):
            self.assertIn(key, source)
        self.assertIn("requires approval", source)
        self.assertNotIn("Subprocess", source)
        self.assertNotIn("/bin/sh", source)

    def test_assistant_has_truthful_state_regions(self) -> None:
        source = (EXTENSION / "components/assistantPanel.js").read_text(encoding="utf-8")
        for region in ("SYSTEM CONTEXT", "ACTIVE APPLICATION", "CURRENT TASK", "CONVERSATION", "PLAN", "TOOL ACTIVITY", "RECENT FILES", "RESULT HISTORY", "APPROVAL REQUESTS"):
            self.assertIn(region, source)
        for state in ("Local model active", "Cloud provider active", "Offline", "Provider unavailable", "Bunny disabled", "Privacy restricted"):
            self.assertIn(state, source)
        stylesheet = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
        for visual_state in ("role-user", "role-assistant", "state-proposed-action", "state-approval-required"):
            self.assertIn(visual_state, stylesheet)

    def test_approval_fixture_and_adapter_cover_required_fields(self) -> None:
        fixture = json.loads((EXTENSION / "mock-state.json").read_text(encoding="utf-8"))
        approval = fixture["approvals"][0]
        fields = {"component", "operation", "resources", "privilege", "networkImpact", "dataImpact", "reversibility", "reason", "expiration", "severity"}
        self.assertTrue(fields.issubset(approval))
        normalized = normalize(fixture, is_mock=True)
        self.assertTrue(normalized["mockMode"])
        self.assertEqual(normalized["approvals"][0]["operation"], approval["operation"])

    def test_mock_mode_is_permanently_labelled_and_decisions_disabled(self) -> None:
        shell = (EXTENSION / "components/approvalPanel.js").read_text(encoding="utf-8")
        app = (ROOT / "apps/common/bunny_visual/application.py").read_text(encoding="utf-8")
        runtime = (ROOT / "apps/common/bunny_visual/runtime.py").read_text(encoding="utf-8")
        self.assertIn("VISUAL MOCK DATA", shell)
        self.assertIn("VISUAL MOCK DATA", app)
        self.assertIn("not mock_mode()", runtime)

    def test_critical_approval_has_no_default_affirmative(self) -> None:
        source = (ROOT / "apps/common/bunny_visual/application.py").read_text(encoding="utf-8")
        self.assertIn('severity == "critical"', source)
        self.assertIn("inspect.grab_focus()", source)
        self.assertNotIn("set_default_widget(approve", source)

    def test_python_surfaces_compile(self) -> None:
        for path in (ROOT / "apps").rglob("*.py"):
            py_compile.compile(str(path), doraise=True)

    def test_required_app_entry_points_exist(self) -> None:
        for app in ("bunny-command-center", "bunny-approval-center", "bunny-assistant", "bunny-diagnostics"):
            self.assertTrue((ROOT / "apps" / app / app).is_file())


if __name__ == "__main__":
    unittest.main()

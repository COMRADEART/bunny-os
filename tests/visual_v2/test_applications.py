from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from tests.support import ROOT
from apps.common.bunny_visual_v2.runtime import normalize, save_welcome_preferences


class VisualV2ApplicationTests(unittest.TestCase):
    def test_five_companion_applications_exist(self) -> None:
        for name in ("control-center", "assistant", "approval-center", "welcome", "diagnostics"):
            path = ROOT / f"apps/bunny-{name}-v2/bunny-{name}-v2"
            self.assertTrue(path.is_file(), path)
            self.assertIn("run_surface", path.read_text(encoding="utf-8"))

    def test_control_center_has_required_sections_and_live_mode_setting(self) -> None:
        source = (ROOT / "apps/common/bunny_visual_v2/application.py").read_text(encoding="utf-8")
        for section in ("Appearance", "Visual Mode", "Desktop", "Layout", "Dock", "Command Palette", "Assistant", "Character", "Privacy", "Approvals", "Notifications", "Accessibility", "Diagnostics", "About"):
            self.assertIn(f'"{section}"', source)
        self.assertIn("Live preview:", source)
        self.assertIn('set_string("visual-mode", mode)', source)

    def test_welcome_has_nine_offline_capable_steps(self) -> None:
        source = (ROOT / "apps/common/bunny_visual_v2/application.py").read_text(encoding="utf-8")
        for step in ("Language", "Keyboard", "Appearance", "Regular Mode or Character Mode", "Accessibility", "Privacy", "Local Only or optional provider", "Approval model", "Finish"):
            self.assertIn(f'page("{step}"', source)
        self.assertIn('"visualMode": "regular"', source)
        self.assertIn('"bunnyEnabled": False', source)
        self.assertIn('"localOnly": True', source)
        self.assertIn('"provider": "none"', source)

    def test_welcome_persists_only_allowlisted_non_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=False):
                destination = save_welcome_preferences({
                    "visualMode": "character", "bunnyEnabled": False,
                    "localOnly": True, "provider": "none", "password": "not-allowed",
                })
            value = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(value["visualMode"], "character")
        self.assertFalse(value["telemetry"])
        self.assertNotIn("password", value)
        self.assertNotIn("secret", value)
        self.assertNotIn("token", value)

    def test_mock_state_never_exposes_decision_adapter(self) -> None:
        state = normalize({"decisionAvailable": True}, is_mock=True)
        self.assertTrue(state["mockMode"])
        self.assertFalse(state["decisionAvailable"])


if __name__ == "__main__":
    unittest.main()

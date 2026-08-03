from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.support import ROOT

from apps.common.bunny_visual.runtime import save_welcome_preferences


class IdentityAndToolingTests(unittest.TestCase):
    def test_six_wallpapers_have_light_dark_and_all_required_sizes(self) -> None:
        data = json.loads((ROOT / "visual/assets/wallpapers/wallpapers.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data["families"]), {"bunny-night", "bunny-dawn", "bunny-cloud", "bunny-horizon", "bunny-focus", "bunny-minimal"})
        self.assertEqual(set(data["sizes"]), {"16x9", "16x10", "ultrawide", "4k"})
        for family in data["families"].values():
            self.assertIn("light", family)
            self.assertIn("dark", family)

    def test_review_scenarios_cover_required_states(self) -> None:
        data = json.loads((ROOT / "visual/screenshots/scenarios.json").read_text(encoding="utf-8"))
        ids = {item["id"] for item in data["scenarios"]}
        required = {
            "empty-desktop", "multiple-windows", "workspace-overview", "command-palette",
            "quick-settings", "assistant-panel", "approval-request", "critical-approval",
            "notification-center", "focus-mode", "compact-layout", "light-mode", "dark-mode",
            "high-contrast", "scaling-200", "offline", "bunny-disabled", "provider-unavailable",
        }
        self.assertEqual(ids, required)
        self.assertEqual(data["mockEnvironment"], "BUNNY_VISUAL_MOCK_MODE=1")

    def test_welcome_defaults_to_offline_optional_choices(self) -> None:
        source = (ROOT / "apps/common/bunny_visual/application.py").read_text(encoding="utf-8")
        for text in ("Language and keyboard", "Appearance", "Accessibility", "Privacy and Bunny", "Optional provider", "Approvals", "Data controls", "Ready"):
            self.assertIn(text, source)
        self.assertIn('"bunnyEnabled": False', source)
        self.assertIn('"localOnly": True', source)
        self.assertIn('"provider": "none"', source)
        self.assertIn("No credentials are collected", source)

    def test_welcome_persists_only_non_secret_offline_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=False):
                destination = save_welcome_preferences({"bunnyEnabled": False, "localOnly": True, "provider": "none"})
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertFalse(payload["bunnyEnabled"])
            self.assertTrue(payload["localOnly"])
            self.assertEqual(payload["provider"], "none")
            self.assertFalse(payload["telemetry"])
            self.assertNotIn("password", payload)
            self.assertNotIn("secret", payload)

    def test_boot_and_login_keep_upstream_safety_paths(self) -> None:
        boot = (ROOT / "visual/assets/boot/README.md").read_text(encoding="utf-8")
        login = (ROOT / "visual/assets/login/README.md").read_text(encoding="utf-8")
        self.assertIn("Verbose boot remains available", boot)
        self.assertIn("Authentication remains upstream GDM", login)
        self.assertIn("GNOME", login)

    def test_icon_and_sound_contracts_are_bounded(self) -> None:
        icons = json.loads((ROOT / "visual/assets/icons/icons.json").read_text(encoding="utf-8"))
        sounds = json.loads((ROOT / "visual/assets/sounds/sounds.json").read_text(encoding="utf-8"))
        self.assertFalse(icons["standardApplicationIconsRedrawn"])
        self.assertGreaterEqual(len(icons["symbolic"]), 6)
        self.assertFalse(sounds["enabledByDefault"])
        self.assertTrue(sounds["respectsSystemEventSounds"])

    def test_visual_make_targets_are_present(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in ("visual-setup", "visual-preview", "visual-preview-nested", "visual-build", "visual-test", "visual-a11y", "visual-screenshot", "visual-package", "visual-clean"):
            self.assertIn(f"{target}:", makefile)

    def test_package_excludes_mock_fixture_and_refuses_mock_environment(self) -> None:
        tool = (ROOT / "visual/tools/visual.py").read_text(encoding="utf-8")
        self.assertIn('exclude={"mock-state.json"}', tool)
        self.assertIn('BUNNY_VISUAL_MOCK_MODE") == "1"', tool)
        self.assertIn('"defaultSessionChanged": False', tool)
        self.assertIn('"mockFixturePackaged": False', tool)


if __name__ == "__main__":
    unittest.main()

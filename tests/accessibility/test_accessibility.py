from __future__ import annotations

import unittest

from tests.support import ROOT


class AccessibilityTests(unittest.TestCase):
    def test_ui_has_programmatic_labels_and_keyboard_activation(self) -> None:
        source = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("AccessibleProperty.LABEL", source)
        self.assertIn("row-activated", source)

    def test_focus_is_visible_in_all_owned_themes(self) -> None:
        for name in ("bunny-light.css", "bunny-dark.css", "bunny-high-contrast.css"):
            source = (ROOT / "shell/themes" / name).read_text(encoding="utf-8")
            self.assertIn(":focus-visible", source)
            self.assertIn("outline", source)

    def test_reduced_motion_and_text_scale_are_real_settings(self) -> None:
        source = (ROOT / "shell/services/bunny_shell/settings.py").read_text(encoding="utf-8")
        self.assertIn('"reducedMotion"', source)
        self.assertIn('"textScalePercent"', source)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from tests.support import ROOT


EXTENSION = ROOT / "shell/bunny-shell-extension"


class LayoutModeTests(unittest.TestCase):
    def test_controller_applies_theme_motion_contrast_and_mode(self) -> None:
        source = (EXTENSION / "components/layoutController.js").read_text(encoding="utf-8")
        for state in ("layout-mode", "theme", "reduced-motion", "high-contrast", "enable-animations", "color-scheme"):
            self.assertIn(state, source)

    def test_focus_dock_remains_summonable(self) -> None:
        source = (EXTENSION / "components/dock.js").read_text(encoding="utf-8")
        self.assertIn("this._focusMode", source)
        self.assertIn("this._hotEdge.connect('enter-event'", source)

    def test_components_define_intentional_compact_variants(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (EXTENSION / "components").glob("*.js"))
        self.assertGreaterEqual(sources.count("bunny-v1-compact"), 5)
        self.assertNotIn("scale_x", sources)
        self.assertNotIn("scale_y", sources)

    def test_light_dark_high_contrast_and_reduced_motion_css_exist(self) -> None:
        source = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
        for style in ("bunny-v1-light", "bunny-v1-high-contrast", "bunny-v1-reduced-motion"):
            self.assertIn(style, source)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "visual/tools"))
from layout_model import SUPPORTED_VIEWPORTS, surface_bounds  # noqa: E402


class VisualV1AccessibilityTests(unittest.TestCase):
    def test_all_major_surfaces_fit_supported_logical_viewports(self) -> None:
        for viewport in SUPPORTED_VIEWPORTS:
            for mode in ("normal", "compact", "focus"):
                for surface, (width, height) in surface_bounds(viewport, mode).items():
                    with self.subTest(viewport=viewport, mode=mode, surface=surface):
                        self.assertGreater(width, 0)
                        self.assertGreater(height, 0)
                        self.assertLessEqual(width, viewport.width)
                        self.assertLessEqual(height, viewport.height)

    def test_compact_layout_is_not_global_scaling(self) -> None:
        viewport = SUPPORTED_VIEWPORTS[0]
        normal = surface_bounds(viewport, "normal")
        compact = surface_bounds(viewport, "compact")
        ratios = {surface: compact[surface][0] / normal[surface][0] for surface in normal}
        self.assertGreater(len({round(value, 2) for value in ratios.values()}), 1)

    def test_focus_mode_preserves_critical_exceptions_and_exit(self) -> None:
        notification = (ROOT / "shell/bunny-shell-extension/components/notificationCenter.js").read_text(encoding="utf-8")
        topbar = (ROOT / "shell/bunny-shell-extension/components/topBar.js").read_text(encoding="utf-8")
        for state in ("critical", "security", "battery-critical", "approval", "accessibility", "system-error"):
            self.assertIn(state, notification)
        self.assertIn("Exit FocusMode", topbar)

    def test_accessibility_audit_executes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "visual/tools/a11y_audit.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertIn("runtime AT-SPI/Orca validation remains required", payload["scope"])

    def test_accessibility_standard_covers_required_matrix(self) -> None:
        standard = (ROOT / "visual/ACCESSIBILITY_STANDARD.md").read_text(encoding="utf-8").casefold()
        for term in ("keyboard", "orca", "high-contrast", "large text", "200%", "reduced-motion", "color", "magnifier", "small screen", "touch"):
            self.assertIn(term, standard)


if __name__ == "__main__":
    unittest.main()

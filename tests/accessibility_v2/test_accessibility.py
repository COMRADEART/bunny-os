from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT


class VisualV2AccessibilityTests(unittest.TestCase):
    def test_spec_covers_required_matrix(self) -> None:
        spec = (ROOT / "visual-v2/ACCESSIBILITY_SPEC.md").read_text(encoding="utf-8")
        for term in ("Keyboard-only", "Orca", "high-contrast", "Large text", "200%", "Reduced motion", "color-vision", "Magnifier", "1366×768", "3840×2160"):
            self.assertIn(term, spec)

    def test_audit_executes_and_all_deterministic_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "visual-v2/tools/a11y_audit.py"), "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(audit["passed"])
        self.assertTrue(all(item["fits"] for item in audit["viewports"]))
        self.assertFalse(audit["liveOrcaTested"])

    def test_character_semantics_do_not_expose_pose_filenames(self) -> None:
        illustration = (ROOT / "shell/bunny-desktop-v2/components/characterIllustration.js").read_text(encoding="utf-8")
        self.assertIn("descriptionForPose(pose)", illustration)
        self.assertIn("Atk.Role.REDUNDANT_OBJECT", illustration)
        self.assertNotIn("accessible_name: pose", illustration)

    def test_focus_and_reduced_motion_contracts_exist(self) -> None:
        shell = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "shell/bunny-desktop-v2/components").glob("*.js"))
        css = (ROOT / "shell/bunny-desktop-v2/stylesheet.css").read_text(encoding="utf-8")
        self.assertIn("can_focus: true", shell)
        self.assertIn("bunny-v2-focus", shell)
        self.assertIn("bunny-v2-reduced-motion", css)
        self.assertIn("transition-duration: 0ms", css)


if __name__ == "__main__":
    unittest.main()

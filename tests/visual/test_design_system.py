from __future__ import annotations

import json
import math
import subprocess
import sys
import unittest

from tests.support import ROOT


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class DesignSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        data = json.loads((ROOT / "visual/tokens/colors.json").read_text(encoding="utf-8"))
        cls.colors = {name: token["value"] for name, token in data["tokens"].items()}

    def test_primary_text_and_semantic_colors_meet_normal_text_contrast(self) -> None:
        for theme in ("dark", "light", "high"):
            background = self.colors[f"{theme}-background"]
            for role in ("text", "muted", "accent", "focus", "success", "warning", "danger"):
                with self.subTest(theme=theme, role=role):
                    self.assertGreaterEqual(contrast(background, self.colors[f"{theme}-{role}"]), 4.5)

    def test_motion_has_zero_reduced_values(self) -> None:
        data = json.loads((ROOT / "visual/tokens/motion.json").read_text(encoding="utf-8"))
        self.assertTrue(all(token["reducedValue"] == "0ms" for token in data["tokens"].values()))

    def test_generated_css_matches_tokens(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "visual/tools/generate_css.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mark_is_abstract_and_accessibly_named(self) -> None:
        mark = (ROOT / "visual/assets/logo/bunny-mark-symbolic.svg").read_text(encoding="utf-8")
        self.assertIn("<title>", mark)
        self.assertIn("currentColor", mark)
        self.assertNotIn("<image", mark)


if __name__ == "__main__":
    unittest.main()

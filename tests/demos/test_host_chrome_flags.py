# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Product trees must not copy the demo-only Chrome --no-sandbox flag."""

from __future__ import annotations

from pathlib import Path
import unittest

from tests.support import ROOT

PRODUCT_TREES = (
    "companion",
    "shell",
    "services",
    "capability",
    "capsules",
    "trust",
)


class DemoOnlyChromeSandboxTests(unittest.TestCase):
    def test_product_trees_do_not_pass_no_sandbox(self) -> None:
        offenders: list[str] = []
        for tree in PRODUCT_TREES:
            root = ROOT / tree
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix not in {".py", ".js", ".desktop", ".sh"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if "--no-sandbox" in text:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"--no-sandbox leaked into product code: {offenders}")

    def test_demos_import_the_guarded_flag_name(self) -> None:
        helper = (ROOT / "demos/host_chrome.py").read_text(encoding="utf-8")
        self.assertIn("DEMO_ONLY_CHROME_NO_SANDBOX", helper)
        self.assertIn("Never import this name", helper)
        self.assertIn("DEMO-ONLY", helper)
        for relative in (
            "demos/08-visible-trust/run.py",
            "demos/10-product-vision/run.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("DEMO_ONLY_CHROME_FLAGS", text)
            self.assertNotIn('chrome, "--no-sandbox"', text)


if __name__ == "__main__":
    unittest.main()

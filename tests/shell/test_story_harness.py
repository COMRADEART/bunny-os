# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§36 and §37: the story harness, and the regression it exists to catch.

The harness renders every component in every theme in about a second. This file
is the part that runs unattended: it regenerates the manifest, fails on a
structural change, and fails on any of the six findings the harness looks for.

**Not pixel equality.** §36 is explicit that pixel-perfect screenshot equality
must not be the sole pass condition, and here it is not a condition at all — the
manifest records shape, never bytes. A manifest containing the stylesheet would
fail on every token change, and a check that fails on every change is one that
gets regenerated without being read.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

STORY = ROOT / "build/scripts/story.mjs"
COMMITTED = ROOT / "qualification/design/story-manifest.json"


def generated() -> dict:
    """The manifest as the harness produces it now."""
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(
            f"import {{manifest}} from '{STORY.as_uri()}';\n"
            "console.log(JSON.stringify(manifest()));\n", encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, encoding="utf-8",
            check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"the story harness failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class StoryHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")
        cls.now = generated()
        cls.committed = json.loads(COMMITTED.read_text(encoding="utf-8"))

    # -- the six checks ----------------------------------------------------

    def test_the_harness_reports_no_structural_findings(self) -> None:
        """Missing fields, overflow, scaling, contrast, disagreement, markup."""
        self.assertEqual(
            self.now["findings"], [],
            "\n".join(f"{f['theme']} · {f['panel']} · {f['kind']} · {f['detail']}"
                      for f in self.now["findings"]))

    def test_it_covers_the_states_the_brief_lists(self) -> None:
        """§37 names them: Trust, long, hostile, 200 %, contrast, dark, light, task states."""
        themes = {theme["theme"] for theme in self.now["themes"]}
        self.assertIn("dark", themes)
        self.assertIn("light", themes)
        self.assertIn("dark @200%", themes)
        self.assertIn("high contrast dark", themes)
        self.assertIn("high contrast light", themes)
        panels = " ".join(self.now["themes"][0]["panels"]).lower()
        for wanted in ("trust", "bound", "hostile", "completed", "blocked", "failed",
                       "result", "errors", "protected space", "companion"):
            with self.subTest(panel=wanted):
                self.assertIn(wanted, panels)

    # -- the regression ----------------------------------------------------

    def test_the_committed_manifest_is_what_the_harness_produces(self) -> None:
        self.assertEqual(
            self.now, self.committed,
            "the story manifest is stale; run node build/scripts/story.mjs and commit "
            "qualification/design/story-manifest.json")

    # -- what the manifest is guarding, stated so a regeneration is a decision --

    def test_every_theme_keeps_the_trust_prompts_fields(self) -> None:
        """A field that disappears is the defect the first booted run photographed."""
        for theme in self.now["themes"]:
            with self.subTest(theme=theme["theme"]):
                trust = theme["trust"]
                self.assertTrue(trust["identity"])
                self.assertGreaterEqual(trust["bodyLines"], 2)
                self.assertEqual(trust["confinementRows"], ["Files", "Network", "App data"])
                self.assertGreaterEqual(len(trust["detailRows"]), 4)

    def test_every_theme_keeps_the_names_the_harness_presses(self) -> None:
        for theme in self.now["themes"]:
            with self.subTest(theme=theme["theme"]):
                self.assertEqual(
                    set(theme["trust"]["buttons"]),
                    {"Allow this Bunny action", "Deny this Bunny action"})

    def test_the_safe_answer_holds_focus_in_every_theme(self) -> None:
        for theme in self.now["themes"]:
            with self.subTest(theme=theme["theme"]):
                self.assertEqual(theme["trust"]["initialFocus"], "deny")

    def test_type_scales_between_the_hundred_and_two_hundred_percent_themes(self) -> None:
        by_name = {theme["theme"]: theme for theme in self.now["themes"]}
        base = by_name["dark"]["typeSizes"]
        large = by_name["dark @200%"]["typeSizes"]
        self.assertEqual(set(base), set(large))
        for role, size in base.items():
            with self.subTest(role=role):
                self.assertEqual(large[role], size * 2)

    def test_the_four_companion_modes_agree_in_every_theme(self) -> None:
        for theme in self.now["themes"]:
            with self.subTest(theme=theme["theme"]):
                self.assertEqual(
                    len(theme["companionTruths"]), 1,
                    f"modes disagree: {theme['companionTruths']}")

    def test_only_the_text_only_mode_draws_no_character(self) -> None:
        """§17: the OS stays usable without the character, and the others keep it."""
        for theme in self.now["themes"]:
            with self.subTest(theme=theme["theme"]):
                modes = theme["companionModes"]
                self.assertFalse(modes["text-only"]["character"])
                for mode in ("full", "compact", "minimal"):
                    self.assertTrue(modes[mode]["character"])
                self.assertGreater(modes["full"]["sizePx"], modes["compact"]["sizePx"])
                self.assertGreater(modes["compact"]["sizePx"], modes["minimal"]["sizePx"])

    def test_the_manifest_records_that_it_is_an_approximation(self) -> None:
        """Nothing downstream may promote a browser render to a runtime result."""
        self.assertTrue(self.now["approximate"])


if __name__ == "__main__":
    unittest.main()

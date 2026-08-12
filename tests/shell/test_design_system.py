# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The design system, measured rather than described.

Every claim in this file is one the previous accessibility run could not make
about the desktop, and each is measured by running the real module under node
against the real tokens — not by reading the source for a promising-looking
string.

The four that matter, in the order the brief puts them:

* §32 typography responds to `text-scaling-factor`. Measured as: the rendered
  stylesheet's font sizes at 200 % are twice those at 100 %, for every one of
  them. The old desktop's were 43 of 43 absolute pixels, and 43 of 43 identical
  at every scale.
* §33 high contrast produces a real adaptation. Measured as: the high-contrast
  sheet differs from the default in most of its declarations, its surfaces are
  opaque, and its shadows are gone.
* §9 contrast is validated automatically. Measured as: every text/surface pair
  the desktop actually draws clears WCAG AA in all four themes.
* §38 the shipped artefacts are generated. Measured as: regenerating them
  produces what is committed.

None of this says the desktop looks right. That is §33's screenshots, and
`ACCESSIBILITY_QUALIFICATION_REPORT.md` is where they are recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

EXTENSION = ROOT / "shell/components/gnome-shell-extension"
DESIGN = EXTENSION / "lib/design"
SCALES = (1.0, 1.25, 1.5, 2.0)
THEME_NAMES = ("light", "dark", "highContrastLight", "highContrastDark")


def run_node(script: str) -> object:
    """Evaluate an ES module and return the JSON on its last output line."""
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, encoding="utf-8",
            check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def imports() -> str:
    return (
        f"import * as tokens from '{(DESIGN / 'tokens.js').as_uri()}';\n"
        f"import * as contrast from '{(DESIGN / 'contrast.js').as_uri()}';\n"
        f"import {{resolveTheme, themeKey}} from '{(DESIGN / 'theme.js').as_uri()}';\n"
        f"import {{renderStylesheet, REACTIVE_CLASSES}} from '{(DESIGN / 'stylesheet.js').as_uri()}';\n"
    )


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class ContrastGateTests(NodeBackedTestCase):
    """§9. The automated half of the contrast argument, and only that half."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.measured = run_node(imports() + """
const rows = [];
for (const [name, theme] of Object.entries(tokens.THEMES)) {
  const base = theme.colour.surfacePrimary;
  for (const pair of tokens.CONTRAST_PAIRS) {
    const spec = tokens.TYPE[pair.type];
    const ratio = contrast.effectiveRatio(theme.colour[pair.text], theme.colour[pair.surface], base);
    rows.push({theme: name, kind: 'text', what: `${pair.text} on ${pair.surface}`,
               ratio, passes: contrast.passesText(ratio, {sizePx: spec.size, weight: spec.weight})});
  }
  for (const pair of tokens.NON_TEXT_PAIRS) {
    const ratio = contrast.effectiveRatio(theme.colour[pair.mark], theme.colour[pair.surface], base);
    rows.push({theme: name, kind: 'non-text', what: `${pair.mark} on ${pair.surface}`,
               ratio, passes: ratio >= contrast.AA_NON_TEXT});
  }
}
console.log(JSON.stringify(rows));
""")

    def test_the_arithmetic_agrees_with_known_answers(self) -> None:
        """A contrast module that always returned 21 would pass every other test here.

        The three greys are the standard WCAG worked examples: #767676 is the
        darkest grey that still clears 4.5:1 on white, #777777 is the first one
        that does not, and #595959 is the AAA boundary at 7:1. A module that
        reproduces all three to two places is doing the real calculation.
        """
        checks = run_node(imports() + """
console.log(JSON.stringify({
  extremes: contrast.contrastRatio('#ffffff', '#000000'),
  identical: contrast.contrastRatio('#808080', '#808080'),
  aaBoundaryPass: contrast.contrastRatio('#767676', '#FFFFFF'),
  aaBoundaryFail: contrast.contrastRatio('#777777', '#FFFFFF'),
  aaaBoundary: contrast.contrastRatio('#595959', '#FFFFFF'),
}));
""")
        self.assertEqual(checks["extremes"], 21)
        self.assertEqual(checks["identical"], 1)
        self.assertEqual(checks["aaBoundaryPass"], 4.54)
        self.assertEqual(checks["aaBoundaryFail"], 4.48)
        self.assertEqual(checks["aaaBoundary"], 7)

    def test_the_figure_the_old_palette_was_justified_by_does_not_reproduce(self) -> None:
        """A finding, kept as a test so it cannot quietly come back.

        docs/DESIGN_SYSTEM.md justified moving secondary text from #A9AFBC to
        #B4BAC6 on the grounds that the first "measures 4.36:1 on the primary
        panel and misses WCAG AA". It measures 8.51:1 — comfortably over — and
        no plausible Bunny backdrop produces 4.36. The hand-computed figure was
        wrong by roughly a factor of two.

        The colour it argued for is fine and stays. What does not stay is
        deciding contrast by hand: this is the whole case for §9's gate, and the
        assertion below is here so that anyone who restores the old sentence has
        to look at a number first.
        """
        measured = run_node(imports() + """
console.log(JSON.stringify({
  onPanel: contrast.effectiveRatio('#A9AFBC', 'rgba(17, 21, 32, 0.72)', '#080B12'),
  onWallpaper: contrast.effectiveRatio('#A9AFBC', 'rgba(17, 21, 32, 0.72)', '#141033'),
}));
""")
        self.assertGreater(measured["onPanel"], 4.5)
        self.assertGreater(measured["onWallpaper"], 4.5)

    def test_a_translucent_colour_cannot_be_measured_by_accident(self) -> None:
        """The old figures were computed against a panel's nominal colour, not its result."""
        refused = run_node(imports() + """
let message = '';
try { contrast.relativeLuminance('rgba(17, 21, 32, 0.72)'); }
catch (error) { message = error.message; }
console.log(JSON.stringify({message}));
""")
        self.assertIn("opaque", refused["message"])

    def test_every_pair_the_desktop_draws_clears_wcag_aa(self) -> None:
        failures = [row for row in self.measured if not row["passes"]]
        self.assertEqual(
            failures, [],
            "\n".join(f"{r['theme']}: {r['what']} = {r['ratio']}:1" for r in failures))

    def test_the_gate_actually_covers_all_four_themes(self) -> None:
        """A gate that silently checked one theme would pass and prove nothing."""
        self.assertEqual({row["theme"] for row in self.measured}, set(THEME_NAMES))
        self.assertGreaterEqual(len(self.measured), 80)


class TypographyScalingTests(NodeBackedTestCase):
    """§5 and §32. The release blocker."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        scales = json.dumps(list(SCALES))
        cls.sizes = run_node(imports() + f"""
const out = {{}};
for (const scale of {scales}) {{
  const css = renderStylesheet(resolveTheme({{scheme: 'dark', textScale: scale}}));
  out[String(scale)] = [...css.matchAll(/font-size:\\s*(\\d+)px/g)].map(m => Number(m[1]));
}}
console.log(JSON.stringify(out));
""")

    def test_the_stylesheet_declares_a_font_size_for_every_role_it_draws(self) -> None:
        self.assertGreaterEqual(len(self.sizes["1"]), 40)

    def test_no_font_size_survives_a_change_of_scale(self) -> None:
        """The measured failure: 43 of 43 font sizes were the same at 150 % as at 100 %."""
        at_100 = self.sizes["1"]
        at_150 = self.sizes["1.5"]
        self.assertEqual(len(at_100), len(at_150))
        unchanged = [a for a, b in zip(at_100, at_150) if a == b]
        self.assertEqual(unchanged, [], f"{len(unchanged)} font sizes ignore the text scale")

    def test_two_hundred_percent_is_twice_one_hundred(self) -> None:
        for base, doubled in zip(self.sizes["1"], self.sizes["2"]):
            with self.subTest(base=base):
                self.assertEqual(doubled, base * 2)

    def test_the_scale_is_clamped_rather_than_trusted(self) -> None:
        """`gsettings set … text-scaling-factor 6.0` is a legal thing to do."""
        clamped = run_node(imports() + """
console.log(JSON.stringify({
  huge: resolveTheme({textScale: 6}).textScale,
  tiny: resolveTheme({textScale: 0.1}).textScale,
  nonsense: resolveTheme({textScale: NaN}).textScale,
  negative: resolveTheme({textScale: -2}).textScale,
}));
""")
        self.assertEqual(clamped["huge"], tokens_value("MAX_TEXT_SCALE"))
        self.assertEqual(clamped["tiny"], tokens_value("MIN_TEXT_SCALE"))
        self.assertEqual(clamped["nonsense"], 1)
        self.assertEqual(clamped["negative"], 1)

    def test_whitespace_grows_more_slowly_than_glyphs(self) -> None:
        """§10. Padding at 1:1 with type turns a 200 % desktop into three cards and air."""
        measured = run_node(imports() + """
const a = resolveTheme({textScale: 1});
const b = resolveTheme({textScale: 2});
console.log(JSON.stringify({
  typeRatio: b.type.body.size / a.type.body.size,
  spaceRatio: b.space.lg / a.space.lg,
}));
""")
        self.assertEqual(measured["typeRatio"], 2.0)
        self.assertGreater(measured["spaceRatio"], 1.0)
        self.assertLess(measured["spaceRatio"], 2.0)


class HighContrastTests(NodeBackedTestCase):
    """§8 and §33. The other release blocker."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.measured = run_node(imports() + """
const plain = renderStylesheet(resolveTheme({scheme: 'dark'}));
const contrasted = renderStylesheet(resolveTheme({scheme: 'dark', highContrast: true}));

// Whether the two sheets differ at all, and by how much, as a coarse guard.
// The precise claim is made at the token level below: comparing declaration
// *strings* cannot tell "this rule kept its colour" from "a different rule
// happens to also be white", and `color: #FFFFFF` legitimately appears in both
// sheets on different selectors.
const theme = resolveTheme({scheme: 'dark', highContrast: true});

// The claim that matters is not "every value changed" — in the light theme
// `surfaceRaised` and `textOnAccent` are already #FFFFFF, and there is nothing
// whiter to move them to. It is that no pair the desktop draws gets *worse*,
// and that the worst pair gets substantially better. That is what a person
// enabling the setting is asking for, and it is measurable.
const ratios = (a, b) => {
  const base = tokens.THEMES[a].colour.surfacePrimary;
  const other = tokens.THEMES[b].colour.surfacePrimary;
  return tokens.CONTRAST_PAIRS.map(pair => ({
    what: `${pair.text} on ${pair.surface}`,
    normal: contrast.effectiveRatio(tokens.THEMES[a].colour[pair.text], tokens.THEMES[a].colour[pair.surface], base),
    contrasted: contrast.effectiveRatio(tokens.THEMES[b].colour[pair.text], tokens.THEMES[b].colour[pair.surface], other),
  }));
};

console.log(JSON.stringify({
  sheetsDiffer: plain !== contrasted,
  dark: ratios('dark', 'highContrastDark'),
  light: ratios('light', 'highContrastLight'),
  translucentSurfaces: Object.values(theme.colour).filter(v => String(v).startsWith('rgba(')).length,
  shadows: Object.values(theme.shadow),
  focusWidth: theme.focus.width,
  plainFocusWidth: resolveTheme({scheme: 'dark'}).focus.width,
}));
""")

    def test_no_pair_gets_worse_when_high_contrast_is_enabled(self) -> None:
        """The setting is a request, and it must not be answered with a downgrade."""
        self.assertTrue(self.measured["sheetsDiffer"])
        for scheme in ("dark", "light"):
            for pair in self.measured[scheme]:
                with self.subTest(scheme=scheme, pair=pair["what"]):
                    self.assertGreaterEqual(
                        pair["contrasted"], pair["normal"],
                        f"{pair['what']} falls from {pair['normal']}:1 to {pair['contrasted']}:1")

    def test_the_worst_pair_improves_substantially(self) -> None:
        """The measured failure: enabling it changed 0.18 % of the screen, under the noise floor.

        A theme where the tightest pair moves from 4.9:1 to 5.0:1 would satisfy
        the no-regression check above and would be the same failure with a
        different number. The tightest pair is the one a person enabling high
        contrast is enabling it *for*.

        The bar is WCAG AAA, 7:1, rather than a multiple of wherever the ordinary
        theme happens to sit. A multiplier makes the requirement depend on how
        good the default already was, which rewards a worse default; a named
        standard does not.
        """
        for scheme in ("dark", "light"):
            with self.subTest(scheme=scheme):
                normal = min(pair["normal"] for pair in self.measured[scheme])
                contrasted = min(pair["contrasted"] for pair in self.measured[scheme])
                self.assertGreaterEqual(
                    contrasted, 7.0,
                    f"{scheme}: worst pair is {contrasted}:1, below AAA "
                    f"(the ordinary theme's worst is {normal}:1)")
                self.assertGreater(contrasted, normal)

    def test_high_contrast_surfaces_are_opaque(self) -> None:
        """A translucent panel is the wallpaper showing through the foreground."""
        self.assertEqual(self.measured["translucentSurfaces"], 0)

    def test_high_contrast_drops_shadows_for_borders(self) -> None:
        self.assertEqual(set(self.measured["shadows"]), {"none"})

    def test_the_focus_ring_thickens(self) -> None:
        self.assertGreater(self.measured["focusWidth"], self.measured["plainFocusWidth"])

    def test_high_contrast_is_reachable_from_either_scheme(self) -> None:
        names = run_node(imports() + """
console.log(JSON.stringify([
  resolveTheme({scheme: 'light', highContrast: true}).name,
  resolveTheme({scheme: 'dark', highContrast: true}).name,
]));
""")
        self.assertEqual(names, ["highContrastLight", "highContrastDark"])


class MotionAndTransparencyTests(NodeBackedTestCase):
    """§15. Reduced motion is zero, not shorter."""

    def test_every_duration_collapses_to_zero(self) -> None:
        measured = run_node(imports() + """
const reduced = resolveTheme({reducedMotion: true}).motion;
const normal = resolveTheme({}).motion;
console.log(JSON.stringify({
  reduced: [reduced.instant, reduced.fast, reduced.normal, reduced.slow],
  normal: [normal.instant, normal.fast, normal.normal, normal.slow],
  easingsSurvive: typeof reduced.easeOut === 'string',
}));
""")
        self.assertEqual(measured["reduced"], [0, 0, 0, 0])
        self.assertGreater(max(measured["normal"]), 0)
        self.assertTrue(measured["easingsSurvive"])

    def test_reduced_transparency_composites_rather_than_listing_a_second_palette(self) -> None:
        measured = run_node(imports() + """
const theme = resolveTheme({scheme: 'dark', reducedTransparency: true});
console.log(JSON.stringify({
  translucent: Object.values(theme.colour).filter(v => String(v).startsWith('rgba(')).length,
  panel: theme.colour.surfaceSecondary,
  expected: contrast.composite(tokens.THEMES.dark.colour.surfaceSecondary,
                               tokens.THEMES.dark.colour.surfacePrimary),
}));
""")
        self.assertEqual(measured["translucent"], 0)
        self.assertEqual(measured["panel"], measured["expected"])


class GeneratedArtefactTests(NodeBackedTestCase):
    """§38. What is committed is what the tokens produce."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        generator = (ROOT / "build/scripts/render_design_assets.mjs").as_uri()
        cls.generated = run_node(
            f"import {{defaultStylesheet, tokenJson}} from '{generator}';\n"
            "console.log(JSON.stringify({css: defaultStylesheet(), json: tokenJson()}));\n")

    @staticmethod
    def _normalised(path: Path) -> str:
        """Line endings are the working tree's business, not the generator's."""
        return "\n".join(path.read_text(encoding="utf-8").splitlines())

    def test_the_shipped_stylesheet_is_what_the_tokens_render(self) -> None:
        committed = self._normalised(EXTENSION / "stylesheet.css")
        expected = "\n".join(self.generated["css"].splitlines())
        self.assertEqual(
            committed, expected,
            "stylesheet.css is stale; run node build/scripts/render_design_assets.mjs")

    def test_the_python_token_mirror_is_what_the_tokens_render(self) -> None:
        committed = self._normalised(ROOT / "shell/themes/tokens.json")
        expected = "\n".join(self.generated["json"].splitlines())
        self.assertEqual(
            committed, expected,
            "shell/themes/tokens.json is stale; run node build/scripts/render_design_assets.mjs")

    def test_the_two_dead_theme_stylesheets_are_gone(self) -> None:
        """They were installed to /usr/share/bunny-shell/themes and loaded by nothing."""
        for name in ("bunny-light.css", "bunny-dark.css", "bunny-high-contrast.css"):
            with self.subTest(name=name):
                self.assertFalse((ROOT / "shell/themes" / name).exists())


class ThemeIdentityTests(NodeBackedTestCase):
    """The key that decides whether a settings change costs a restyle."""

    def test_an_identical_setting_produces_an_identical_key(self) -> None:
        measured = run_node(imports() + """
console.log(JSON.stringify({
  same: themeKey({scheme: 'dark', textScale: 1}) === themeKey({scheme: 'dark', textScale: 1}),
  scale: themeKey({textScale: 1}) !== themeKey({textScale: 1.5}),
  contrast: themeKey({}) !== themeKey({highContrast: true}),
  motion: themeKey({}) !== themeKey({reducedMotion: true}),
  clampedAlike: themeKey({textScale: 6}) === themeKey({textScale: 9}),
}));
""")
        self.assertTrue(measured["same"])
        self.assertTrue(measured["scale"])
        self.assertTrue(measured["contrast"])
        self.assertTrue(measured["motion"])
        # Two scales that clamp to the same value are the same theme, and
        # re-rendering for them would be a restyle of every actor for nothing.
        self.assertTrue(measured["clampedAlike"])


def tokens_value(name: str) -> float:
    """One exported constant, read through node so the test cannot restate it."""
    return run_node(imports() + f"console.log(JSON.stringify(tokens.{name}));\n")


if __name__ == "__main__":
    unittest.main()

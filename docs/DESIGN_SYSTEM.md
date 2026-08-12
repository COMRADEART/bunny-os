# Bunny OS design system

One token source, four themes, generated output. The design language is calm and
operational: a warm neutral foundation, a single violet accent, clear keyboard
focus, and status that is never encoded by colour alone.

Tokens live in **`shell/components/gnome-shell-extension/lib/design/tokens.js`**.
`shell/themes/tokens.json` and the desktop's `stylesheet.css` are both generated
from it by `build/scripts/render_design_assets.mjs`; editing either by hand is a
change the next regeneration discards, and `tests/shell/test_design_system.py`
fails a committed file that does not match the tokens.

## One palette, and what happened to the other

There were two. `shell/themes/tokens.json` described an evergreen and mint
palette; the desktop shell had a violet one in JavaScript. The earlier version of
this document recorded the split and said resolving it "is worth doing and is not
done yet".

It is done, in favour of violet — the palette in every screenshot the project
has. The evergreen palette was installed to `/usr/share/bunny-shell/themes` and
loaded by nothing: its only consumers were two test files. Retiring it changed
what nobody had seen rather than what everybody had.

The accent is `#7C3AED` for fills that carry text and `#A78BFA` for text and
focus rings on dark surfaces. `#8B5CF6`, the previous fill, measures 4.23:1
against white and misses AA for the button role.

## Four themes

`light`, `dark`, `highContrastLight`, `highContrastDark`. The scheme follows
`org.gnome.desktop.interface color-scheme` and the contrast pair follows
`org.gnome.desktop.a11y.interface high-contrast`. There is no Bunny-specific
theme toggle: §8 of the design brief is explicit that a preference which ignores
the platform setting is not a fix, and the desktop had one of those already — a
`theme` key that was stored, validated, displayed back to the user, and applied
by nothing.

High contrast is not a tint. Surfaces become opaque, shadows become `none` and a
visible border carries the separation instead — a shadow is precisely the cue a
high-contrast theme exists to stop relying on — and the focus ring goes from 2px
to 3px. The gate asserts that no text pair gets *worse* when the setting is
enabled and that the tightest pair clears WCAG AAA.

## Typography scales, and where it did not

Eight semantic roles: Display, Title, Heading, Body, Body Small, Caption, Button,
Monospace. Sizes are derived from
`org.gnome.desktop.interface text-scaling-factor` at render time, so a size at
150 % is 150 % of the size at 100 % by construction.

The previous desktop believed it honoured text scaling. `desktopShell._textScale()`
parsed the point size out of `St.Settings.font_name` and divided by 11 — but GNOME
implements text scaling through Xft DPI for GTK clients and never rewrites
`font-name`, so that function returned 1.0 at every scale. The 43 absolute pixel
font sizes in the old stylesheet were the second half of the same failure: even
with the scale read correctly, none of them would have grown.

Whitespace grows at half the rate of glyphs (`SPACE_SCALE_RATE`). Padding at 1:1
turned a 200 % desktop into three cards and a lot of air; padding that did not
scale left 24px text against a 1px border.

Bunny ships no font file. The system UI font and system monospace are used.

## Spacing, shape, elevation, motion, focus

Spacing is 2/4/8/12/20/32/48. Radii carry hierarchy — control 12, card 18, panel
22, floating 20, modal 24 — and only the Trust prompt sits at modal elevation,
because it is the only thing in Bunny OS permitted to interrupt.

Motion is instant/fast/normal/slow (0/120/220/360 ms) with two easings. Reduced
motion sets every duration to **zero**, not shorter: a 40 ms fade is still a fade
and the setting is not "please hurry". The easings survive so that a component
reading `theme.motion.easeOut` does not have to check first.

Focus is one treatment everywhere: a 2px ring at 2px offset, 3px at high
contrast, in a colour that is never the accent — a focus ring sharing a colour
with a selected row is one you have to hunt for. Every reactive class has a
`:focus` rule and a test measures that across all four themes.

## Contrast is computed, not asserted

`lib/design/contrast.js` does the WCAG arithmetic and reproduces the standard
worked examples (#767676 on white = 4.54:1, #777777 = 4.48:1, #595959 = 7:1).
The gate checks every text and non-text pair the desktop actually draws, in all
four themes — 88 pairs — and composites translucent surfaces over their real
backdrop first, because a translucent panel has no contrast ratio until you say
what is behind it.

**A correction.** The previous version of this document justified moving
secondary text from `#A9AFBC` to `#B4BAC6` on the grounds that the first
"measures 4.36:1 on the primary panel and misses WCAG AA". It measures 8.51:1,
and no plausible Bunny backdrop produces 4.36. The hand-computed figure was wrong
by roughly a factor of two. `#B4BAC6` is a fine colour and stays; what does not
stay is deciding contrast by hand, and
`test_the_figure_the_old_palette_was_justified_by_does_not_reproduce` exists so
that anyone restoring the old sentence has to look at a number first.

Automated contrast is necessary and not sufficient. A palette that clears 4.5:1
can still be unreadable; that is what the booted-guest screenshots are for.

## Security semantics

`risk` marks high and critical with a *shape* beside the heading as well as a
colour, and `standing` pairs every permission state with a glyph and a word.
Colour alone fails for a reader who cannot distinguish those hues, and a
permission prompt is the worst place for that failure.

`unenforced` is a badge that coexists with `granted` rather than replacing it,
because "allowed, and this build cannot actually restrict it" is two facts and
one row. The Trust component draws each confinement row as
"Files: holiday.png only, enforced" in its accessible name for the same reason:
§19 requires a person to tell "Network off — enforced" from "Network
restrictions declared but not enforced" without reading documentation.

## What consumes this

The desktop shell renders its whole stylesheet from the tokens at runtime and
re-renders it whenever a display setting changes; see `lib/themeManager.js`. The
shipped `stylesheet.css` is the generated default theme, kept as the fallback for
a session where the theme manager could not start.

The GTK4 surfaces — `bunny-launcher`, `bunny-settings`, `bunny-approvals` and the
rest, plus the Companion window — do not consume these tokens and should not.
They are plain GTK against the system palette (`@window_bg_color`,
`alpha(@accent_bg_color, .12)`) with relative font sizes, so they already follow
scaling, light/dark and high contrast because Adwaita does. They are the proof
that the platform pipeline works, and the desktop shell was the outlier.

## Related

- `docs/DESIGN_SYSTEM_AUDIT.md` — every Bunny-owned surface and what this phase
  did with it.
- `docs/VISUAL_IDENTITY.md` — the identity these tokens express.
- `docs/ACCESSIBILITY.md` — the runtime evidence model these tokens are checked
  against.

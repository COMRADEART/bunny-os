# Bunny OS design system

Phase 1 of the companion-centric OS UI. One token source, four themes, generated
output. The language is calm, premium, and original Bunny — not a macOS copy,
not a chatbot overlay.

Tokens live in **`shell/components/gnome-shell-extension/lib/design/tokens.js`**.
`shell/themes/tokens.json` and the desktop's `stylesheet.css` are both generated
from it by `build/scripts/render_design_assets.mjs`; editing either by hand is a
change the next regeneration discards, and `tests/shell/test_design_system.py`
fails a committed file that does not match the tokens.

Primitives (pure models, consumed by GNOME Shell widgets) live in
`lib/design/primitives.js`. Companion vocabulary lives in
`lib/companionVocabulary.js` and `companion/os_companion.py`.

## Three questions every screen must answer

1. **What am I doing?**
2. **What is Bunny doing?**
3. **What can I do next?**

A surface that cannot answer all three is not ready. Progressive disclosure
beats decoration. The companion is first-class OS UI and is **not required** to
use the OS: turning it off, hiding it, or failing to draw it still leaves the
thin system bar, the dock, keyboard paths, and Trust prompts.

## Colour

Layered charcoal on dark (`#080B12` sunken through raised panels) and warm paper
on light. Interactive accent stays violet (`#7C3AED` / `#A78BFA`) because that
is the fill that clears WCAG AA behind white button text.

**Bunny Blue** `#4EA8FF` (dark) / `#2F80ED` (light) is the companion *signal* —
glow, presence, the current timeline mark. It is used sparingly. It is never a
fill behind text.

## Type, space, radius, motion

| Role | Size at 100 % |
|---|---|
| Display | 32–40 |
| Title | 22 |
| Heading | 16 |
| Body | 14 |
| Body small | 12 |
| Caption | 11 |
| Button / mono | 12 |

Spacing is 4 / 8 / 12 / 16 / 24 / 32 / 48. Radius is 8 (control) / 14 (card) /
22 (panel, bubble) / 28 (sheet, modal). Elevation is base / raised / overlay /
dialog; blur is 0 / 18 / 28, gone at high contrast.

Motion is 80–420 ms. Chrome uses 150–350; companion pose uses 300–420. Reduced
motion sets **every** duration to zero, including companion and the 80 ms micro
band. Easings survive so callers do not have to branch.

## Companion states

One active companion. Seventeen states:

`idle` `listening` `understanding` `thinking` `planning` `working` `coding`
`reading` `searching` `waiting` `asking` `warning` `error` `success`
`celebrating` `sleep` `offline`

Presentation modes: **FULL** / **COMPACT** / **AMBIENT**. Default anchor is
bottom-right, with drag / scale / hide hooks. Absolute Wayland placement is
not claimed.

Rendering tiers: **FULL** (implemented) / **BALANCED** / **LIGHT** / **MINIMAL**
(named stubs mapping onto the existing fidelity ladder).

The drawable poses remain the ten in `lib/character/state.js`. The seventeen
states project onto those poses so a bubble, a figure and a task card cannot
disagree.

Character: young stylized 3D human, black hoodie / pants / sneakers, warm
face. Desktop figure is the vector in `lib/character/definition.js`. The GLB
hook is `assets/companion/characters/default-bunny-3d`. Missing assets fall
back to the vector; nothing invents a second character.

## Bubbles and tasks

Bubbles are 1–3 sentence captions at 22px radius, with actions underneath when
needed — not a chat transcript. Longer copy is a sheet or the task card.

Task timelines use ✓ / ● / ○ stages, expandable plan / tools / files /
permissions, and Pause / Cancel. There is no “AI is typing…”.

## Desktop chrome (Phase 1 skeleton)

Thin system bar, centred dock, companion anchor, generous whitespace. Widget
columns are the `full` layout profile and are not the Phase 1 default. The
live session drops the assistant card; Trust/consent is a chrome dialog plus
a bubble caption, not a hidden dashboard card. The live GNOME session is
**not verified** in this change.

The story harness live copy is `shell/themes/story-manifest.json`.
`qualification/design/story-manifest.json` remains Phase 7 frozen evidence
and is not retargeted by this phase.

## Primitives

Button, IconButton, Card, Panel, Sheet, Dialog, Popover, Tooltip, TextField,
SearchField, Toggle, Slider, Menu, List, Sidebar, TaskCard, TaskTimeline,
PermissionCard, Bubble, CompanionAnchor, Notification, DockItem.

Each focusable primitive has a `:focus` rule. Icon-only controls are invalid
without an accessible name.

## Four themes

`light`, `dark`, `highContrastLight`, `highContrastDark`. The scheme follows
`org.gnome.desktop.interface color-scheme` and the contrast pair follows
`org.gnome.desktop.a11y.interface high-contrast`.

High contrast is not a tint. Surfaces become opaque, shadows become `none` and a
visible border carries the separation instead. The gate asserts that no text
pair gets *worse* when the setting is enabled and that the tightest pair
clears WCAG AAA.

## Typography scaling

Sizes are derived from `org.gnome.desktop.interface text-scaling-factor` at
render time, so a size at 150 % is 150 % of the size at 100 % by construction.
Whitespace grows at half the rate of glyphs (`SPACE_SCALE_RATE`).

Bunny ships no font file. The system UI font and system monospace are used.

## Contrast is computed, not asserted

`lib/design/contrast.js` does the WCAG arithmetic. The gate checks every text
and non-text pair the desktop actually draws, in all four themes, and
composites translucent surfaces over their real backdrop first.

Automated contrast is necessary and not sufficient. A palette that clears 4.5:1
can still be unreadable; that is what the booted-guest screenshots are for.

## Security semantics

`risk` marks high and critical with a *shape* beside the heading as well as a
colour, and `standing` pairs every permission state with a glyph and a word.
Colour alone fails for a reader who cannot distinguish those hues.

## What consumes this

The desktop shell renders its whole stylesheet from the tokens at runtime and
re-renders it whenever a display setting changes; see `lib/themeManager.js`.
The shipped `stylesheet.css` is the generated default theme, kept as the
fallback for a session where the theme manager could not start.

GTK4 surfaces continue to follow Adwaita. Host HTML reads
`companion.design_tokens.css_custom_properties`.

## Related

- `docs/DESIGN_SYSTEM_AUDIT.md` — every Bunny-owned surface and what an earlier
  phase did with it.
- `docs/VISUAL_IDENTITY.md` — the identity these tokens express.
- `docs/ACCESSIBILITY.md` — the runtime evidence model these tokens are checked
  against.

The older accessibility history (text-scale reading the wrong GNOME key, two
palettes, the 4.36:1 figure that does not reproduce) is in
`DESIGN_SYSTEM_REPORT.md`. The gate
`test_the_figure_the_old_palette_was_justified_by_does_not_reproduce` remains so
that sentence cannot quietly return.

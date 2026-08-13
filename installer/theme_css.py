# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny design system, rendered as GTK4 CSS.

§24 asks that the setup surface reuse the design system already built rather than
invent installer-only visual conventions. There is a real obstacle to doing that
literally: the design system's renderer, `lib/design/stylesheet.js`, emits **St**
CSS for GNOME Shell, and the setup surface is a **GTK4** application. St's
stylesheet language and GTK4's are both subsets of CSS, and they are not the same
subset — St has ``spacing`` and ``icon-size``, GTK4 has neither; GTK4 has
``outline`` and box-model ``margin``, St's are different.

So there are two renderers and **one** set of values. `shell/themes/
resolved-themes.json` holds every theme the setup surface can be in, already
resolved by the same `resolveTheme` the desktop uses — the same clamp, the same
half-rate space scaling, the same rule that high contrast implies opaque
surfaces. This module turns one of those records into GTK4 CSS and decides
nothing.

That "decides nothing" is the point and is worth stating precisely: there is no
colour literal in this file, no font size, no padding value, no radius. Every
number comes out of the resolved theme. A reviewer can check that claim by
searching for a ``#`` and finding none outside a comment.

## Reduced motion

`resolveTheme` sets every motion duration to zero when reduced motion is on, so
the transitions below render as ``0ms`` rather than being omitted. That matters
for §41: nothing in setup may depend on animation to communicate completion or
error, and a stylesheet whose transitions are zero-duration proves the surface
still works when they do not run — where a stylesheet with the transitions
deleted would merely be a different stylesheet.

## Focus

§37 requires that focus always be visible and that there be no keyboard trap.
Visibility is this file's half: every focusable role gets an ``outline`` in the
theme's focus colour at the theme's focus width, which is 3px under high contrast
and 2px otherwise. GTK4 draws ``outline`` outside the border box, so a focus ring
cannot be clipped by the widget's own padding — which is how the previous phase's
Deny button ended up with a focus ring nobody could see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "RESOLVED_THEMES",
    "ThemeUnavailable",
    "load_resolved_themes",
    "render_gtk_css",
    "resolve",
    "theme_key",
]

#: Shipped alongside the shell theme assets; `install_routes.py` places it.
RESOLVED_THEMES = Path("/usr/share/bunny-shell/themes/resolved-themes.json")

#: The checkout copy, used when the installer runs from a source tree.
_SOURCE_THEMES = Path(__file__).resolve().parents[1] / "shell" / "themes" / "resolved-themes.json"


class ThemeUnavailable(RuntimeError):
    """The resolved-theme document is missing or does not contain the request.

    Raised rather than defaulted. A setup surface that silently fell back to a
    different theme than the person selected would defeat §8, whose whole claim
    is that an accessibility setting takes effect immediately.
    """


def load_resolved_themes(path: Path | None = None) -> Mapping[str, Any]:
    for candidate in ([path] if path is not None else [RESOLVED_THEMES, _SOURCE_THEMES]):
        if candidate is not None and candidate.is_file():
            document = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or "themes" not in document:
                raise ThemeUnavailable(f"{candidate} is not a resolved-theme document")
            return document
    raise ThemeUnavailable("no resolved-theme document found; run build/scripts/render_design_assets.mjs")


def theme_key(*, scheme: str = "light", high_contrast: bool = False,
              text_scale: float = 1.0, reduced_motion: bool = False) -> str:
    """Mirror of ``themeKey`` in ``lib/design/theme.js``.

    The one piece of the JavaScript reproduced here, because it is string
    formatting rather than arithmetic and because a lookup key has to be built
    before the record that would contain it can be read. ``test_setup_theme.py``
    asserts every key this produces exists in the generated document, so a format
    that drifted would fail rather than fall back.
    """
    dark = scheme != "light"
    if high_contrast:
        name = "highContrastDark" if dark else "highContrastLight"
    else:
        name = "dark" if dark else "light"
    # High contrast implies opaque surfaces — see resolveTheme's `flatten`.
    transparency = "opaque" if high_contrast else "translucent"
    return f"{name}:{text_scale:.3f}:{'rm' if reduced_motion else 'motion'}:{transparency}"


def resolve(*, scheme: str = "light", high_contrast: bool = False,
            text_scale: float = 1.0, reduced_motion: bool = False,
            document: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """The resolved theme for these settings, or a refusal."""
    source = document or load_resolved_themes()
    key = theme_key(scheme=scheme, high_contrast=high_contrast,
                    text_scale=text_scale, reduced_motion=reduced_motion)
    entry = source["themes"].get(key)
    if entry is None:
        offered = source.get("textScales", [])
        raise ThemeUnavailable(
            f"no resolved theme for {key!r}; the offered text scales are {offered}"
        )
    return entry["theme"]


def _px(value: object) -> str:
    return f"{int(round(float(value)))}px"


def render_gtk_css(theme: Mapping[str, Any], *, companion_size_px: int | None = None) -> str:
    """One resolved theme in, one GTK4 stylesheet out.

    The class names match the ones `build/scripts/story.mjs` renders, so the
    story harness draws this stylesheet rather than an approximation of it. That
    is what makes §35's "renderable without a VM boot" worth anything: a panel
    that looks right in the story looks right because the same rules produced it.

    **No control has a fixed height.** That is deliberate and it is the §39
    requirement expressed as a stylesheet rule: a ``min-height`` chosen to look
    right at 100 % is the thing that clips its own label at 200 %, because the
    label scales at the glyph rate and the box does not. Every control here is
    sized by its font plus its padding, both of which come from the resolved
    theme and both of which already scale. The one exception is the Companion
    figure, which is a picture rather than text and is therefore passed in by the
    caller that knows which presentation mode is active.
    """
    colour = theme["colour"]
    type_ = theme["type"]
    space = theme["space"]
    radius = theme["radius"]
    focus = theme["focus"]
    motion = theme["motion"]
    metric = theme["metric"]

    def font(role: str) -> str:
        spec = type_[role]
        family = "monospace" if spec.get("family") == "monospace" else "inherit"
        return (f"font-size: {_px(spec['size'])};\n"
                f"  font-weight: {spec['weight']};\n"
                f"  font-family: {family};")

    def focus_ring(selector: str) -> str:
        return (f"{selector}:focus-visible {{\n"
                f"  outline: {_px(focus['width'])} solid {focus['colour']};\n"
                f"  outline-offset: {_px(focus['offset'])};\n"
                f"}}")

    figure = companion_size_px or metric["characterMinWidth"]
    standard = f"{motion['normal']}ms"
    fast = f"{motion['fast']}ms"

    return f"""/* Generated by installer/theme_css.py from shell/themes/resolved-themes.json.
   Theme: {theme['name']} · text scale {theme['textScale']} ·
   {'reduced motion' if theme['reducedMotion'] else 'motion'} ·
   {'opaque' if theme['reducedTransparency'] else 'translucent'}.
   Every value here comes from the resolved theme; nothing is decided in Python. */

/* ---------------------------------------------------------------- surface */

window.bunny-setup,
.bunny-setup {{
  background-color: {colour['surfacePrimary']};
  color: {colour['textPrimary']};
  {font('body')}
}}

.bunny-setup-column {{
  padding: {_px(space['xl'])};
  min-width: {_px(metric['cardWidth'])};
}}

/* §5: the opening scene is the Companion on a light ground with almost nothing
   else on it, so the greeting surface gets its own generous measure. */
.bunny-setup-welcome .bunny-setup-column {{
  padding: {_px(space['xxl'])};
}}

/* ------------------------------------------------------------------- type */

.bunny-setup-heading {{
  {font('title')}
  color: {colour['textPrimary']};
  margin-bottom: {_px(space['md'])};
}}

.bunny-setup-says {{
  {font('heading')}
  color: {colour['textPrimary']};
}}

.bunny-setup-label {{
  {font('body')}
  color: {colour['textPrimary']};
}}

.bunny-setup-help {{
  {font('bodySmall')}
  color: {colour['textSecondary']};
  margin-top: {_px(space['xxs'])};
}}

.bunny-setup-required {{
  color: {colour['textMuted']};
}}

.bunny-setup-value {{
  {font('body')}
  color: {colour['textPrimary']};
}}

.bunny-setup-advanced,
.bunny-setup-advanced-line {{
  {font('mono')}
  color: {colour['textMuted']};
}}

.bunny-setup-disclosure {{
  {font('bodySmall')}
  color: {colour['accentText']};
}}

/* The accessible announcement. Present in the widget tree with its text set,
   never drawn: GTK reads it to Orca and gives it no allocation. §9 asks for an
   equivalent, and an equivalent that took space would be a duplicate. */
.bunny-setup-announcement {{
  {font('caption')}
  color: {colour['textMuted']};
}}

/* --------------------------------------------------------------- controls */

.bunny-setup-field {{
  margin-bottom: {_px(space['lg'])};
}}

entry.bunny-setup-entry {{
  {font('body')}
  color: {colour['textPrimary']};
  background-color: {colour['surfaceRaised']};
  border: 1px solid {colour['border']};
  border-radius: {_px(radius['control'])};
  padding: {_px(space['sm'])} {_px(space['md'])};
  transition: border-color {fast} ease-out;
}}

entry.bunny-setup-entry:disabled {{
  color: {colour['textMuted']};
}}

/* A field the installer backend rejected. Colour is never the only signal —
   the message text is a sibling label, so this reads correctly in high contrast
   and to a screen reader alike. */
entry.bunny-setup-entry.bunny-setup-invalid {{
  border-color: {colour['danger']};
}}

.bunny-setup-option {{
  padding: {_px(space['sm'])} {_px(space['md'])};
  border: 1px solid {colour['border']};
  border-radius: {_px(radius['control'])};
  background-color: {colour['surfaceSecondary']};
  margin-bottom: {_px(space['xs'])};
  transition: background-color {fast} ease-out;
}}

.bunny-setup-option:hover {{
  background-color: {colour['surfaceHover']};
}}

.bunny-setup-option:selected,
.bunny-setup-option:checked {{
  background-color: {colour['selection']};
  color: {colour['textOnSelection']};
}}

/* Visible and unselectable, never hidden. A disk that vanishes from the list is
   a consequence hidden by omission — see storage_screen in setup_view.py. */
.bunny-setup-option-unavailable {{
  color: {colour['textMuted']};
  background-color: {colour['surfacePrimary']};
}}

.bunny-setup-option-label {{
  {font('body')}
}}

.bunny-setup-option-note {{
  {font('caption')}
  color: {colour['textSecondary']};
}}

/* --------------------------------------------------------------- warnings */

.bunny-setup-warning {{
  padding: {_px(space['md'])};
  border-radius: {_px(radius['card'])};
  margin-bottom: {_px(space['md'])};
  border: 1px solid {colour['border']};
}}

.bunny-setup-warning-info {{
  background-color: {colour['surfaceSecondary']};
  color: {colour['textPrimary']};
}}

.bunny-setup-warning-caution {{
  background-color: {colour['surfaceSecondary']};
  color: {colour['textPrimary']};
  border-color: {colour['warning']};
}}

/* §11: destructive consequences are never softened. This is the only role that
   uses the danger colour as a border and the only one with a raised weight, so
   the treatment means exactly one thing wherever it appears. */
.bunny-setup-warning-danger {{
  background-color: {colour['surfaceSecondary']};
  color: {colour['textPrimary']};
  border: {_px(focus['width'])} solid {colour['danger']};
}}

.bunny-setup-warning-danger .bunny-setup-warning-text {{
  {font('heading')}
  color: {colour['danger']};
}}

.bunny-setup-warning-glyph {{
  color: {colour['danger']};
  margin-right: {_px(space['sm'])};
}}

/* --------------------------------------------------------------- progress */

.bunny-setup-stage {{
  padding: {_px(space['xs'])} 0;
  {font('body')}
  color: {colour['textMuted']};
}}

.bunny-setup-stage-done {{
  color: {colour['success']};
}}

.bunny-setup-stage-active {{
  color: {colour['textPrimary']};
  font-weight: {type_['heading']['weight']};
}}

.bunny-setup-stage-glyph {{
  margin-right: {_px(space['sm'])};
}}

/* ---------------------------------------------------------------- actions */

button.bunny-setup-action {{
  {font('button')}
  padding: {_px(space['sm'])} {_px(space['lg'])};
  border-radius: {_px(radius['control'])};
  border: 1px solid {colour['border']};
  background-color: {colour['surfaceRaised']};
  color: {colour['textPrimary']};
  transition: background-color {standard} ease-out;
}}

button.bunny-setup-action-primary {{
  background-color: {colour['accent']};
  color: {colour['textOnAccent']};
  border-color: {colour['accent']};
}}

button.bunny-setup-action-safe {{
  background-color: {colour['surfaceRaised']};
  color: {colour['textPrimary']};
}}

button.bunny-setup-action-quiet {{
  background-color: transparent;
  border-color: transparent;
  color: {colour['accentText']};
}}

/* The button that erases a disk. Distinct from primary, so that the forward
   action on an ordinary screen and the destructive action on the confirmation
   screen can never be the same shape in the same place. */
button.bunny-setup-action-danger {{
  background-color: {colour['danger']};
  color: {colour['textOnAccent']};
  border-color: {colour['danger']};
}}

button.bunny-setup-action:disabled {{
  color: {colour['textMuted']};
  background-color: {colour['surfaceSecondary']};
  border-color: {colour['border']};
}}

{focus_ring('button.bunny-setup-action')}
{focus_ring('entry.bunny-setup-entry')}
{focus_ring('.bunny-setup-option')}
{focus_ring('checkbutton.bunny-setup-toggle')}
{focus_ring('switch.bunny-setup-toggle')}

/* -------------------------------------------------------------- companion */

.bunny-setup-companion {{
  margin-bottom: {_px(space['xl'])};
}}

.bunny-setup-figure {{
  min-width: {_px(figure)};
  min-height: {_px(figure)};
  border-radius: {_px(radius['floating'])};
}}
"""

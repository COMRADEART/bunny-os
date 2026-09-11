# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python mirror of the desktop design tokens.

The source of truth is ``shell/components/gnome-shell-extension/lib/design/
tokens.js``. ``shell/themes/tokens.json`` is generated from it. This module
reads that JSON so host HTML (product vision, Trust demo) cannot invent a
second palette. If the file is missing, a small fallback matching the dark
theme is used — a missing generated file must not crash a demo.

Nothing here grants a permission or starts a task.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "BUBBLE_PREVIEW_LIMIT",
    "MOTION_UI_MS",
    "MOTION_COMPANION_MS",
    "bunny_silhouette_svg",
    "css_custom_properties",
    "load_tokens",
    "visual_key_spec",
]

_ROOT = Path(__file__).resolve().parents[1]
_TOKENS_PATH = _ROOT / "shell" / "themes" / "tokens.json"

#: Visual Key 1: a speech bubble is a caption, not a transcript.
BUBBLE_PREVIEW_LIMIT = 220

MOTION_UI_MS = (80, 420)
MOTION_COMPANION_MS = (300, 420)

_FALLBACK_DARK = {
    "schemaVersion": 5,
    "space": {"xxs": 4, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32, "xxxl": 48},
    "radius": {"control": 8, "card": 14, "panel": 22, "floating": 22, "bubble": 22, "sheet": 28, "modal": 28},
    "motion": {
        "fastMs": 150, "standardMs": 220, "slowMs": 350, "microMs": 80,
        "companionFastMs": 300, "companionNormalMs": 360, "companionSlowMs": 420,
        "reducedMs": 0, "uiRangeMs": [80, 420], "companionRangeMs": [300, 420],
    },
    "dark": {
        "surfacePrimary": "#080B12",
        "surfaceSecondary": "rgba(17, 21, 32, 0.72)",
        "surfaceRaised": "rgba(27, 31, 45, 0.65)",
        "textPrimary": "#F7F8FA",
        "textSecondary": "#B4BAC6",
        "textMuted": "#8F96A4",
        "textOnAccent": "#FFFFFF",
        "border": "rgba(255, 255, 255, 0.06)",
        "borderStrong": "rgba(255, 255, 255, 0.36)",
        "focus": "#A78BFA",
        "accent": "#7C3AED",
        "accentText": "#A78BFA",
        "success": "#22C55E",
        "warning": "#F59E0B",
        "danger": "#EF4444",
        "permission": "#F59E0B",
        "offline": "#8F96A4",
        "loading": "#A78BFA",
        "trust": "#A78BFA",
        "companionSignal": "#4EA8FF",
        "scrim": "rgba(8, 11, 18, 0.72)",
    },
    "companion": {"visualKey": {}},
    "opacity": {"disabled": 0.45, "surface": 0.86},
}


@lru_cache(maxsize=1)
def load_tokens() -> Mapping[str, Any]:
    """The generated token document, or a dark-theme fallback."""
    try:
        document = json.loads(_TOKENS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _FALLBACK_DARK
    if not isinstance(document, dict) or "dark" not in document:
        return _FALLBACK_DARK
    return document


#: Fallback matching ``VISUAL_KEY`` in tokens.js so host HTML still poses
#: correctly if the generated JSON has not been regenerated yet.
_FALLBACK_VISUAL_KEY: Mapping[str, Mapping[str, Any]] = {
    "idle": {"token": "companionSignal", "intensity": "quiet", "ears": "rest", "mic": False, "dim": False},
    "listening": {"token": "focus", "intensity": "active", "ears": "up", "mic": True, "dim": False},
    "thinking": {"token": "trust", "intensity": "active", "ears": "tilt", "mic": False, "dim": False},
    "understanding": {"token": "trust", "intensity": "active", "ears": "tilt", "mic": False, "dim": False},
    "planning": {"token": "trust", "intensity": "active", "ears": "tilt", "mic": False, "dim": False},
    "working": {"token": "success", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "searching": {"token": "focus", "intensity": "active", "ears": "up", "mic": False, "dim": False},
    "downloading": {"token": "warning", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "installing": {"token": "warning", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "reading": {"token": "trust", "intensity": "quiet", "ears": "tilt", "mic": False, "dim": False},
    "coding": {"token": "focus", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "waiting": {"token": "textMuted", "intensity": "quiet", "ears": "rest", "mic": False, "dim": False},
    "asking": {"token": "permission", "intensity": "attention", "ears": "up", "mic": False, "dim": False},
    "waiting_for_permission": {"token": "permission", "intensity": "attention", "ears": "up", "mic": False, "dim": False},
    "celebrating": {"token": "success", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "success": {"token": "success", "intensity": "active", "ears": "rest", "mic": False, "dim": False},
    "warning": {"token": "warning", "intensity": "attention", "ears": "tilt", "mic": False, "dim": False},
    "error": {"token": "danger", "intensity": "attention", "ears": "down", "mic": False, "dim": False},
    "sleep": {"token": "textMuted", "intensity": "quiet", "ears": "rest", "mic": False, "dim": True},
    "offline": {"token": "offline", "intensity": "quiet", "ears": "rest", "mic": False, "dim": True},
    "disconnected": {"token": "textMuted", "intensity": "quiet", "ears": "down", "mic": False, "dim": True},
}


def visual_key_spec(key: str) -> Mapping[str, Any]:
    companion = load_tokens().get("companion") or {}
    table = companion.get("visualKey") if isinstance(companion, Mapping) else {}
    if isinstance(table, Mapping) and key in table:
        spec = table[key]
        if isinstance(spec, Mapping) and spec:
            return spec
    return _FALLBACK_VISUAL_KEY.get(key, _FALLBACK_VISUAL_KEY["idle"])


def bunny_silhouette_svg(*, ears: str = "rest", mic: bool = False, dim: bool = False) -> str:
    """One Bunny silhouette. Pose is ears, glow, and a mic badge — never a second character."""
    ear_left = {
        "rest": "M38 52 C34 18 58 10 62 46",
        "up": "M40 48 C36 8 62 4 66 42",
        "tilt": "M32 56 C22 22 52 16 58 50",
        "down": "M42 58 C48 28 70 28 68 56",
    }.get(ears, "M38 52 C34 18 58 10 62 46")
    ear_right = {
        "rest": "M102 46 C108 10 132 18 126 52",
        "up": "M98 42 C104 4 130 8 124 48",
        "tilt": "M106 50 C118 16 148 22 138 56",
        "down": "M96 56 C98 28 120 28 126 58",
    }.get(ears, "M102 46 C108 10 132 18 126 52")
    opacity = "0.55" if dim else "1"
    mic_mark = (
        '<g class="mic-badge" aria-hidden="true">'
        '<circle cx="128" cy="118" r="14" fill="var(--focus)"/>'
        '<rect x="123" y="110" width="10" height="14" rx="5" fill="var(--text-on-accent)"/>'
        "</g>"
        if mic else ""
    )
    return f"""
<svg class="bunny-face" viewBox="0 0 164 164" role="img" aria-hidden="true" style="opacity:{opacity}">
  <path d="{ear_left}" fill="#E8D7F8" stroke="#3B3348" stroke-width="3"/>
  <path d="{ear_right}" fill="#E8D7F8" stroke="#3B3348" stroke-width="3"/>
  <ellipse cx="82" cy="96" rx="46" ry="42" fill="#F4E9F8" stroke="#3B3348" stroke-width="3"/>
  <ellipse cx="68" cy="92" rx="6" ry="7" fill="#1A1424"/>
  <ellipse cx="96" cy="92" rx="6" ry="7" fill="#1A1424"/>
  <ellipse cx="82" cy="108" rx="7" ry="5" fill="#C4A4C8"/>
  <path d="M70 118 Q82 126 94 118" fill="none" stroke="#3B3348" stroke-width="2.5" stroke-linecap="round"/>
  {mic_mark}
</svg>
"""


def css_custom_properties(*, scheme: str = "dark") -> str:
    """CSS custom properties for host HTML that wraps production copy.

    Named after the semantic roles, never after a swatch. Reduced-motion
    consumers still get the durations; they set them to zero themselves.
    """
    tokens = load_tokens()
    colour = tokens.get(scheme if scheme in ("light", "dark") else "dark")
    if not isinstance(colour, Mapping):
        colour = _FALLBACK_DARK["dark"]
    space = tokens.get("space") if isinstance(tokens.get("space"), Mapping) else _FALLBACK_DARK["space"]
    radius = tokens.get("radius") if isinstance(tokens.get("radius"), Mapping) else _FALLBACK_DARK["radius"]
    motion = tokens.get("motion") if isinstance(tokens.get("motion"), Mapping) else _FALLBACK_DARK["motion"]
    opacity = tokens.get("opacity") if isinstance(tokens.get("opacity"), Mapping) else _FALLBACK_DARK["opacity"]
    lines = [":root {"]
    for name, value in colour.items():
        css_name = "".join(("-" + ch.lower() if ch.isupper() else ch) for ch in name)
        lines.append(f"  --{css_name}: {value};")
    for name, value in space.items():
        lines.append(f"  --space-{name}: {int(value)}px;")
    for name, value in radius.items():
        lines.append(f"  --radius-{name}: {int(value)}px;")
    lines.append(f"  --motion-micro: {int(motion.get('microMs', 80))}ms;")
    lines.append(f"  --motion-fast: {int(motion.get('fastMs', 150))}ms;")
    lines.append(f"  --motion-normal: {int(motion.get('standardMs', 220))}ms;")
    lines.append(f"  --motion-slow: {int(motion.get('slowMs', 350))}ms;")
    lines.append(f"  --motion-companion: {int(motion.get('companionNormalMs', 360))}ms;")
    lines.append(f"  --opacity-disabled: {opacity.get('disabled', 0.45)};")
    lines.append("}")
    lines.append("@media (prefers-reduced-motion: reduce) {")
    lines.append("  :root { --motion-micro: 0ms; --motion-fast: 0ms; --motion-normal: 0ms; --motion-slow: 0ms; --motion-companion: 0ms; }")
    lines.append("}")
    return "\n".join(lines)

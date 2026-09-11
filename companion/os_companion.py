# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 1 OS companion vocabulary — Python mirror of the desktop module.

The source of truth for *drawing* is
``shell/components/gnome-shell-extension/lib/companionVocabulary.js``.
This module exists so host HTML, the GTK companion, and tests can name the
same seventeen states without importing GJS.

It does not start a task, grant a permission, or invent a renderer.
"""

from __future__ import annotations

from typing import Mapping

from companion.design_tokens import load_tokens

__all__ = [
    "OS_STATES",
    "PRESENTATION_MODES",
    "RENDERING_TIERS",
    "SCREEN_QUESTIONS",
    "fidelity_for_tier",
    "tier_is_implemented",
    "tier_is_fully_featured",
    "limit_bubble_text",
    "os_state_from_phase",
    "pose_for_os_state",
    "screen_answers",
]

SCREEN_QUESTIONS = (
    "What am I doing?",
    "What is Bunny doing?",
    "What can I do next?",
)

OS_STATES = (
    "idle", "listening", "understanding", "thinking", "planning",
    "working", "coding", "reading", "searching", "waiting", "asking",
    "warning", "error", "success", "celebrating", "sleep", "offline",
)

PRESENTATION_MODES = ("full", "compact", "ambient")

RENDERING_TIERS = ("FULL", "BALANCED", "LIGHT", "MINIMAL")

_PHASE_TO_OS: Mapping[str, str] = {
    "idle": "idle",
    "starting": "thinking",
    "recovering": "thinking",
    "understanding": "understanding",
    "planning": "planning",
    "waiting_for_approval": "asking",
    "waiting_for_permission": "asking",
    "listening": "listening",
    "transcribing": "listening",
    "speaking": "working",
    "working": "working",
    "reviewing": "reading",
    "presenting_result": "success",
    "success": "success",
    "cancelling": "waiting",
    "cancelled": "idle",
    "paused": "waiting",
    "blocked": "warning",
    "error": "error",
    "disconnected": "offline",
}

_ACTIVITY = {
    "code": "coding",
    "coding": "coding",
    "type": "coding",
    "typing": "coding",
    "read": "reading",
    "reading": "reading",
    "review": "reading",
    "search": "searching",
    "searching": "searching",
    "research": "searching",
}

_POSE = {
    "idle": "idle",
    "listening": "listening",
    "understanding": "thinking",
    "thinking": "thinking",
    "planning": "thinking",
    "working": "working",
    "coding": "working",
    "reading": "thinking",
    "searching": "working",
    "waiting": "idle",
    "asking": "warning",
    "warning": "warning",
    "error": "error",
    "success": "success",
    "celebrating": "celebrating",
    "sleep": "sleeping",
    "offline": "idle",
}

_TIER_FIDELITY = {
    "FULL": "full-3d",
    "BALANCED": "lightweight-3d",
    "LIGHT": "static-image",
    "MINIMAL": "text-only",
}


def os_state_from_phase(
    phase: str,
    *,
    tool_activity: str = "",
    celebrating: bool = False,
    sleeping: bool = False,
) -> str:
    """One OS companion state for a presentation phase."""
    if sleeping:
        return "sleep"
    if celebrating:
        return "celebrating"
    state = _PHASE_TO_OS.get(str(phase or "idle"), "idle")
    if state == "working":
        activity = str(tool_activity or "").strip().casefold()
        for needle, mapped in _ACTIVITY.items():
            if needle in activity:
                return mapped
    return state


def pose_for_os_state(state: str) -> str:
    return _POSE.get(state, "idle")


def tier_is_implemented(tier: str) -> bool:
    """Phase 4: every named tier is a live ceiling on the fidelity ladder."""
    document = load_tokens()
    companion = document.get("companion") if isinstance(document, dict) else {}
    tiers = companion.get("renderingTiers") if isinstance(companion, dict) else {}
    key = str(tier or "FULL").upper()
    if isinstance(tiers, dict) and key in tiers and isinstance(tiers[key], dict):
        return tiers[key].get("implemented") is True
    return key in RENDERING_TIERS


def tier_is_fully_featured(tier: str) -> bool:
    """FULL is the only fully featured tier. Lower tiers must not claim full-3d."""
    document = load_tokens()
    companion = document.get("companion") if isinstance(document, dict) else {}
    tiers = companion.get("renderingTiers") if isinstance(companion, dict) else {}
    key = str(tier or "FULL").upper()
    if isinstance(tiers, dict) and key in tiers and isinstance(tiers[key], dict):
        return tiers[key].get("fullyFeatured") is True
    return key == "FULL"


def fidelity_for_tier(tier: str) -> str:
    document = load_tokens()
    companion = document.get("companion") if isinstance(document, dict) else {}
    tiers = companion.get("renderingTiers") if isinstance(companion, dict) else {}
    key = str(tier or "FULL").upper()
    if isinstance(tiers, dict) and key in tiers and isinstance(tiers[key], dict):
        fidelity = tiers[key].get("fidelity")
        if isinstance(fidelity, str) and fidelity:
            return fidelity
    return _TIER_FIDELITY.get(key, "full-3d")


def limit_bubble_text(value: str, *, max_sentences: int = 3) -> str:
    """Short contextual copy. A fourth sentence belongs in a panel."""
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""
    parts: list[str] = []
    buf: list[str] = []
    for char in raw:
        buf.append(char)
        if char in ".!?":
            parts.append("".join(buf).strip())
            buf = []
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    if len(parts) <= max_sentences:
        return raw
    return " ".join(parts[:max_sentences])


def screen_answers(*, doing: str, bunny: str, nxt: str) -> Mapping[str, str]:
    """The three questions every screen must answer, as a labelled mapping."""
    return {
        SCREEN_QUESTIONS[0]: str(doing or "").strip(),
        SCREEN_QUESTIONS[1]: str(bunny or "").strip(),
        SCREEN_QUESTIONS[2]: str(nxt or "").strip(),
    }

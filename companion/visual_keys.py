# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The eleven user-facing Visual Keys, projected from the canonical record.

The Companion is the visual face of Bunny OS, not the OS. Ordinary people
should see a small character and a short speech bubble — not a chat log —
and the room around Bunny should change with what Bunny is doing.

This module does not add states to the task lifecycle or to
:class:`companion.character.mapper.CharacterState`. Those vocabularies are
already load-bearing. Visual Keys are a *projection*: they name what a
person should see, using the eleven words the product vision lists, derived
from a presentation phase plus an optional tool activity.

Speech bubbles here are captions. A long answer belongs in a task panel, not
beside the character. That is Visual Key 1. State transitions are Visual
Key 2. The reactive scene is Visual Key 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = [
    "VISUAL_KEYS",
    "Scene",
    "SpeechBubble",
    "VisualFrame",
    "activity_for",
    "bubble_for",
    "frame_for",
    "project_visual_key",
    "scene_for",
]

#: The product-vision character states, in the order a demo photographs them.
VISUAL_KEYS = (
    "idle",
    "listening",
    "thinking",
    "working",
    "searching",
    "downloading",
    "installing",
    "reading",
    "coding",
    "error",
    "success",
)

#: Presentation phases that are "thinking" for a person: Bunny has the
#: request and has not started a visible tool yet.
_THINKING_PHASES = frozenset({"understanding", "planning", "starting", "recovering"})

#: How a tool activity narrows ``working`` into a more specific Visual Key.
#: Unknown activities stay ``working``. These strings are matched casefolded.
_ACTIVITY_KEYS: Mapping[str, str] = {
    "search": "searching",
    "searching": "searching",
    "research": "searching",
    "researching": "searching",
    "web": "searching",
    "browse": "searching",
    "download": "downloading",
    "downloading": "downloading",
    "fetch": "downloading",
    "install": "installing",
    "installing": "installing",
    "setup": "installing",
    "read": "reading",
    "reading": "reading",
    "open-document": "reading",
    "code": "coding",
    "coding": "coding",
    "typing": "coding",
    "write": "coding",
    "editing": "coding",
}


@dataclass(frozen=True)
class SpeechBubble:
    """A short caption next to the character. Not a chat transcript."""

    text: str
    kind: str = "caption"

    def __post_init__(self) -> None:
        if self.kind not in ("caption", "approval", "warning", "error"):
            raise ValueError(f"unknown bubble kind: {self.kind!r}")
        if len(self.text) > 220:
            object.__setattr__(self, "text", self.text[:219] + "…")

    def to_json(self) -> dict[str, str]:
        return {"text": self.text, "kind": self.kind}


@dataclass(frozen=True)
class Scene:
    """What the room is doing. Derived from the Visual Key, never authored."""

    name: str
    sky: str
    floor: str
    accent: str
    motion: str

    def to_json(self) -> dict[str, str]:
        return {
            "name": self.name,
            "sky": self.sky,
            "floor": self.floor,
            "accent": self.accent,
            "motion": self.motion,
        }


@dataclass(frozen=True)
class VisualFrame:
    """One photographed Visual Key: character, bubble, room."""

    key: str
    character: str
    label: str
    bubble: SpeechBubble
    scene: Scene
    presentation_phase: str
    tool_activity: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "character": self.character,
            "label": self.label,
            "bubble": self.bubble.to_json(),
            "scene": self.scene.to_json(),
            "presentationPhase": self.presentation_phase,
            "toolActivity": self.tool_activity,
        }


_LABELS: Mapping[str, str] = {
    "idle": "Ready",
    "listening": "Listening",
    "thinking": "Thinking",
    "working": "Working",
    "searching": "Searching",
    "downloading": "Downloading",
    "installing": "Installing",
    "reading": "Reading",
    "coding": "Writing",
    "error": "Something failed",
    "success": "Done",
}

_BUBBLES: Mapping[str, tuple[str, str]] = {
    "idle": ("Ready when you are.", "caption"),
    "listening": ("I'm listening.", "caption"),
    "thinking": ("Let me think about that.", "caption"),
    "working": ("Working on it.", "caption"),
    "searching": ("Looking that up.", "caption"),
    "downloading": ("Downloading — still on this computer.", "caption"),
    "installing": ("Installing. I'll ask before anything touches your files.", "caption"),
    "reading": ("Reading what you pointed at.", "caption"),
    "coding": ("Writing that for you.", "caption"),
    "error": ("That didn't work. Nothing else was changed.", "error"),
    "success": ("Done.", "caption"),
}

_SCENES: Mapping[str, Scene] = {
    "idle": Scene("quiet-room", "#1a2233", "#121820", "#7C3AED", "still"),
    "listening": Scene("open-window", "#1b2a3a", "#121820", "#38BDF8", "soft"),
    "thinking": Scene("lamp-glow", "#241833", "#161320", "#A78BFA", "pulse"),
    "working": Scene("desk-light", "#1a2430", "#141a22", "#34D399", "active"),
    "searching": Scene("map-wall", "#13202c", "#101820", "#38BDF8", "active"),
    "downloading": Scene("shelf-glow", "#1a2030", "#121820", "#FBBF24", "active"),
    "installing": Scene("toolbox", "#1c1a28", "#14141c", "#F59E0B", "active"),
    "reading": Scene("book-nook", "#1c1824", "#141018", "#C4B5FD", "soft"),
    "coding": Scene("editor", "#10141c", "#0c1016", "#22D3EE", "active"),
    "error": Scene("warning-desk", "#2a1518", "#1a1012", "#F43F5E", "attention"),
    "success": Scene("clear-desk", "#14241c", "#101816", "#34D399", "soft"),
}


def activity_for(tool_activity: str) -> str:
    """The Visual Key a tool activity narrows ``working`` into, or empty."""
    return _ACTIVITY_KEYS.get(str(tool_activity or "").strip().casefold(), "")


def project_visual_key(
    presentation_phase: str,
    *,
    tool_activity: str = "",
    listening: bool = False,
    error_summary: str = "",
) -> str:
    """Project canonical facts into one of :data:`VISUAL_KEYS`.

    Priority matches the presentation ladder for the things a person must
    not miss: an error beats work, listening beats idle. A decorative
    activity never hides those.
    """
    phase = str(presentation_phase or "idle").strip().casefold()
    if error_summary or phase in {"error", "failed", "blocked"}:
        return "error"
    if phase in {"cancelled", "cancelling"}:
        return "idle"
    if phase == "success" or phase == "presenting_result":
        return "success"
    if phase == "waiting_for_approval":
        # The Trust surface owns this; Visual Keys still show working-adjacent
        # attention rather than inventing a twelfth key.
        return "working"
    if listening or phase == "listening":
        return "listening"
    if phase in _THINKING_PHASES:
        return "thinking"
    if phase in {"working", "reviewing", "speaking"}:
        narrowed = activity_for(tool_activity)
        return narrowed or "working"
    return "idle"


def bubble_for(key: str, *, text: str = "") -> SpeechBubble:
    """The ordinary-action bubble for a Visual Key.

    ``text`` may replace the default caption. It is still truncated to a
    bubble, never grown into a chat panel.
    """
    if key not in VISUAL_KEYS:
        raise ValueError(f"unknown visual key: {key!r}")
    default, kind = _BUBBLES[key]
    return SpeechBubble(text or default, kind=kind)


def scene_for(key: str) -> Scene:
    if key not in VISUAL_KEYS:
        raise ValueError(f"unknown visual key: {key!r}")
    return _SCENES[key]


def frame_for(
    presentation_phase: str,
    *,
    tool_activity: str = "",
    listening: bool = False,
    error_summary: str = "",
    bubble_text: str = "",
) -> VisualFrame:
    """One complete Visual Key frame from canonical facts."""
    key = project_visual_key(
        presentation_phase,
        tool_activity=tool_activity,
        listening=listening,
        error_summary=error_summary,
    )
    return VisualFrame(
        key=key,
        character=key,
        label=_LABELS[key],
        bubble=bubble_for(key, text=bubble_text),
        scene=scene_for(key),
        presentation_phase=presentation_phase,
        tool_activity=tool_activity,
    )

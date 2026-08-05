# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sanitised speech-bubble state and screen-edge-aware anchoring."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
import textwrap
from typing import Any, Sequence

from .positioning import Display, PixelRect
from .schema import BubbleAnchor


class BubbleKind(str, Enum):
    CAPTION = "caption"
    APPROVAL = "approval"
    WARNING = "warning"
    ERROR = "error"


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_bubble_text(value: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError("bubble text must be sanitised text")
    cleaned = _CONTROL.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    if len(cleaned) > maximum:
        cleaned = cleaned[: maximum - 1] + "…"
    return cleaned


@dataclass(frozen=True)
class BubbleState:
    revision: int
    text: str
    kind: BubbleKind
    partial: bool
    final: bool
    persistent: bool
    visible: bool
    updated_at: float
    expires_at: float | None
    high_contrast: bool = False
    keyboard_accessible: bool = True
    announce_to_screen_reader: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "text": self.text,
            "kind": self.kind.value,
            "partial": self.partial,
            "final": self.final,
            "persistent": self.persistent,
            "visible": self.visible,
            "updatedAt": self.updated_at,
            "expiresAt": self.expires_at,
            "highContrast": self.high_contrast,
            "keyboardAccessible": self.keyboard_accessible,
            "announceToScreenReader": self.announce_to_screen_reader,
        }


class SpeechBubbleController:
    def __init__(self) -> None:
        self.state = BubbleState(0, "", BubbleKind.CAPTION, False, False, False, False, 0.0, None)

    def update(
        self,
        text: str,
        *,
        kind: BubbleKind = BubbleKind.CAPTION,
        partial: bool = False,
        final: bool = False,
        now: float,
        timeout_seconds: float = 6.0,
        high_contrast: bool = False,
        persistent: bool | None = None,
    ) -> BubbleState:
        if timeout_seconds < 0:
            raise ValueError("bubble timeout cannot be negative")
        cleaned = sanitize_bubble_text(text)
        # An approval is always persistent; a caller may additionally declare
        # one. §11 gives ordinary speech a timeout, and an error is not
        # ordinary speech: a message about something that went wrong which
        # faded after six seconds would be a message the user is likely to have
        # missed. Derived from the kind alone at first, which meant exactly
        # that.
        persistent = (kind is BubbleKind.APPROVAL) if persistent is None else bool(persistent)
        expires = None if persistent or timeout_seconds == 0 else now + timeout_seconds
        self.state = BubbleState(
            self.state.revision + 1, cleaned, kind, partial, final, persistent,
            bool(cleaned), now, expires, high_contrast,
        )
        return self.state

    def detach(self, *, now: float) -> BubbleState:
        self.state = replace(
            self.state, revision=self.state.revision + 1, visible=False,
            persistent=False, expires_at=now, updated_at=now,
        )
        return self.state

    def tick(self, *, now: float) -> BubbleState:
        if self.state.visible and self.state.expires_at is not None and now >= self.state.expires_at:
            return self.detach(now=now)
        return self.state


@dataclass(frozen=True)
class BubbleLayout:
    display_id: str
    bounds: PixelRect
    side: str
    anchor_x: int
    anchor_y: int
    maximum_width: int
    wrapped_lines: tuple[str, ...]
    edge_avoided: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "displayId": self.display_id,
            "bounds": self.bounds.to_json(),
            "side": self.side,
            "anchor": {"x": self.anchor_x, "y": self.anchor_y},
            "maximumWidth": self.maximum_width,
            "wrappedLines": list(self.wrapped_lines),
            "edgeAvoided": self.edge_avoided,
        }


def layout_bubble(
    state: BubbleState,
    anchor: BubbleAnchor,
    character: PixelRect,
    displays: Sequence[Display],
    *,
    scale: float = 1.0,
    maximum_width: int = 420,
    edge_margin: int = 12,
) -> BubbleLayout:
    if not displays:
        raise ValueError("bubble layout requires a display")
    if not 0.75 <= scale <= 3.0:
        raise ValueError("bubble scale is outside the accessibility range")
    center_x, center_y = character.x + character.width // 2, character.y + character.height // 2
    display = next((item for item in displays if (
        item.work_area.x <= center_x < item.work_area.right
        and item.work_area.y <= center_y < item.work_area.bottom
    )), next((item for item in displays if item.primary), displays[0]))
    area = display.work_area
    max_width = min(round(maximum_width * scale), max(120, area.width - 2 * edge_margin))
    char_width = max(16, int(max_width / max(8, round(8 * scale))))
    lines = tuple(textwrap.wrap(state.text, width=char_width, replace_whitespace=False) or [""])
    width = min(max_width, max(120, min(max_width, max((len(line) for line in lines), default=1) * round(8 * scale) + 28)))
    height = min(area.height - 2 * edge_margin, max(48, len(lines) * round(20 * scale) + 24))
    anchor_x = character.x + round(anchor.x * character.width)
    anchor_y = character.y + round(anchor.y * character.height)
    preferred = anchor.preferred_side
    order = [preferred] if preferred != "auto" else []
    order.extend(side for side in ("right", "left", "above", "below") if side not in order)

    def candidate(side: str) -> PixelRect:
        gap = round(12 * scale)
        if side == "right":
            return PixelRect(anchor_x + gap, anchor_y - height // 2, width, height)
        if side == "left":
            return PixelRect(anchor_x - gap - width, anchor_y - height // 2, width, height)
        if side == "above":
            return PixelRect(anchor_x - width // 2, anchor_y - gap - height, width, height)
        return PixelRect(anchor_x - width // 2, anchor_y + gap, width, height)

    selected_side = order[0]
    bounds = candidate(selected_side)
    avoided = False
    for side in order:
        possible = candidate(side)
        if (possible.x >= area.x + edge_margin and possible.right <= area.right - edge_margin
                and possible.y >= area.y + edge_margin and possible.bottom <= area.bottom - edge_margin):
            avoided = side != selected_side
            selected_side, bounds = side, possible
            break
    clamped = PixelRect(
        max(area.x + edge_margin, min(bounds.x, area.right - edge_margin - bounds.width)),
        max(area.y + edge_margin, min(bounds.y, area.bottom - edge_margin - bounds.height)),
        bounds.width, bounds.height,
    )
    avoided = avoided or clamped != bounds
    return BubbleLayout(display.display_id, clamped, selected_side, anchor_x, anchor_y, max_width, lines, avoided)

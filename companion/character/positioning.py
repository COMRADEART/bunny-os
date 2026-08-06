# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Focus-neutral character placement across displays and avoidance regions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence


class Placement(str, Enum):
    CENTER_SCREEN = "center-screen"
    DOCK_LEFT = "dock-left"
    DOCK_RIGHT = "dock-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"
    COMPACT_FLOATING = "compact-floating"
    USER_DRAGGED = "user-dragged"


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: "PixelRect") -> bool:
        return not (self.right <= other.x or other.right <= self.x or self.bottom <= other.y or other.bottom <= self.y)

    def to_json(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Display:
    display_id: str
    work_area: PixelRect
    primary: bool = False


@dataclass(frozen=True)
class SavedPosition:
    display_id: str
    x_fraction: float
    y_fraction: float
    placement: Placement = Placement.USER_DRAGGED

    def __post_init__(self) -> None:
        if not 0 <= self.x_fraction <= 1 or not 0 <= self.y_fraction <= 1:
            raise ValueError("saved position fractions must be normalized")

    def to_json(self) -> dict[str, Any]:
        return {
            "displayId": self.display_id,
            "xFraction": self.x_fraction,
            "yFraction": self.y_fraction,
            "placement": self.placement.value,
        }


@dataclass(frozen=True)
class PositionDecision:
    display_id: str
    character: PixelRect
    placement: Placement
    snap_target: str | None
    recovered_from_removed_display: bool
    avoids_fullscreen: bool
    avoids_task_panel: bool
    accepts_keyboard_focus: bool = False
    reasons: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "displayId": self.display_id,
            "character": self.character.to_json(),
            "placement": self.placement.value,
            "snapTarget": self.snap_target,
            "recoveredFromRemovedDisplay": self.recovered_from_removed_display,
            "avoidsFullscreen": self.avoids_fullscreen,
            "avoidsTaskPanel": self.avoids_task_panel,
            "acceptsKeyboardFocus": self.accepts_keyboard_focus,
            "reasons": list(self.reasons),
        }


class PositionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> SavedPosition | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return SavedPosition(
                str(value["displayId"]), float(value["xFraction"]), float(value["yFraction"]),
                Placement(str(value.get("placement", "user-dragged"))),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, value: SavedPosition) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".position-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value.to_json(), stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, max(low, high)))


def place_character(
    displays: Sequence[Display],
    *,
    size: tuple[int, int],
    placement: Placement,
    saved: SavedPosition | None = None,
    dragged_origin: tuple[int, int] | None = None,
    task_panel: PixelRect | None = None,
    fullscreen_application: bool = False,
    edge_margin: int = 16,
    bubble_safe_area: int = 96,
    snap_distance: int = 32,
) -> PositionDecision:
    if not displays:
        raise ValueError("a visual position requires at least one display")
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("character size must be positive")
    by_id = {display.display_id: display for display in displays}
    recovered = bool(saved and saved.display_id not in by_id)
    display = by_id.get(saved.display_id) if saved else None
    display = display or next((item for item in displays if item.primary), displays[0])
    area = display.work_area
    reasons: list[str] = []
    maximum_width = max(1, area.width - 2 * edge_margin)
    maximum_height = max(1, area.height - 2 * edge_margin)
    if width > maximum_width or height > maximum_height:
        ratio = min(maximum_width / width, maximum_height / height)
        width = max(1, round(width * ratio))
        height = max(1, round(height * ratio))
        reasons.append("character scale was constrained to the display work area")
    left = area.x + edge_margin
    right = area.right - edge_margin - width
    top = area.y + edge_margin
    bottom = area.bottom - edge_margin - height
    snap: str | None = None
    if recovered:
        reasons.append("saved display was removed; position recovered to the primary display")

    if placement is Placement.CENTER_SCREEN:
        x, y = area.x + (area.width - width) // 2, area.y + (area.height - height) // 2
    elif placement is Placement.DOCK_LEFT:
        x, y = left, area.y + (area.height - height) // 2
    elif placement is Placement.DOCK_RIGHT:
        x, y = right, area.y + (area.height - height) // 2
    elif placement is Placement.BOTTOM_LEFT:
        x, y = left, bottom
    elif placement in {Placement.BOTTOM_RIGHT, Placement.COMPACT_FLOATING}:
        x, y = right, bottom
    elif dragged_origin is not None:
        x, y = dragged_origin
    elif saved is not None:
        x = area.x + round(saved.x_fraction * max(0, area.width - width))
        y = area.y + round(saved.y_fraction * max(0, area.height - height))
    else:
        x, y = right, bottom
    x, y = _clamp(x, left, right), _clamp(y, top, bottom)

    if placement is Placement.USER_DRAGGED or dragged_origin is not None:
        targets = {
            "left": left, "right": right,
            "center-x": area.x + (area.width - width) // 2,
        }
        closest = min(targets.items(), key=lambda item: abs(x - item[1]))
        if abs(x - closest[1]) <= snap_distance:
            snap, x = closest
        vertical = {"top": top, "bottom": bottom, "center-y": area.y + (area.height - height) // 2}
        closest_y = min(vertical.items(), key=lambda item: abs(y - item[1]))
        if abs(y - closest_y[1]) <= snap_distance:
            snap = f"{snap}+{closest_y[0]}" if snap else closest_y[0]
            y = closest_y[1]

    avoids_fullscreen = False
    if fullscreen_application and placement not in {Placement.DOCK_LEFT, Placement.DOCK_RIGHT}:
        x, y = right, bottom
        avoids_fullscreen = True
        reasons.append("fullscreen application moved the passive character to a compact edge position")

    candidate = PixelRect(x, y, width, height)
    avoids_panel = False
    if task_panel is not None and candidate.intersects(task_panel):
        alternatives = [
            PixelRect(left, candidate.y, width, height),
            PixelRect(right, candidate.y, width, height),
            PixelRect(candidate.x, top, width, height),
            PixelRect(candidate.x, max(top, task_panel.y - height - edge_margin), width, height),
        ]
        replacement = next((item for item in alternatives if not item.intersects(task_panel)), None)
        if replacement is not None:
            candidate = replacement
            avoids_panel = True
            reasons.append("position moved away from the task panel")

    # Reserve vertical room for a bubble where possible.  The bubble engine
    # still clamps independently, so a tiny display degrades safely.
    if candidate.y < area.y + bubble_safe_area and area.height >= height + 2 * bubble_safe_area:
        candidate = PixelRect(candidate.x, area.y + bubble_safe_area, width, height)
        reasons.append("position preserves speech-bubble safe area")
    return PositionDecision(
        display.display_id, candidate, placement, snap, recovered,
        avoids_fullscreen, avoids_panel, False, tuple(reasons),
    )


def saved_from_decision(decision: PositionDecision, display: Display) -> SavedPosition:
    width_space = max(1, display.work_area.width - decision.character.width)
    height_space = max(1, display.work_area.height - decision.character.height)
    return SavedPosition(
        display.display_id,
        max(0.0, min(1.0, (decision.character.x - display.work_area.x) / width_space)),
        max(0.0, min(1.0, (decision.character.y - display.work_area.y) / height_space)),
        Placement.USER_DRAGGED,
    )

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptive Hybrid workspace layouts for the Hyprland Bunny session.

Desktop / Focus / Studio are **visual layouts**, not capability editions.
Switching layout must preserve the same task identity, event cursor, approvals
and artifacts — this module never invents task truth.

Geometry here is advisory for Hyprland chrome (gaps, reserved rail, companion
footprint). Absolute Wayland placement is not claimed; callers apply what
Hyprland/`hyprctl` actually support and report the rest honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

LAYOUTS = ("desktop", "focus", "studio")

# Aliases so older GNOME profile names map without a second authority.
LEGACY_PROFILE_ALIASES = {
    "skeleton": "desktop",
    "full": "studio",
}


@dataclass(frozen=True)
class ScreenRect:
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", max(640, int(self.width)))
        object.__setattr__(self, "height", max(480, int(self.height)))


@dataclass(frozen=True)
class BandRect:
    x: int
    y: int
    width: int
    height: int

    def to_json(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class LayoutSolution:
    """Pure geometry for one Adaptive Hybrid layout on one screen."""

    layout: str
    breakpoint: str
    scale: float
    gaps_out: int
    gaps_in: int
    top_bar: BandRect
    dock: BandRect
    work: BandRect
    task_rail: BandRect | None
    task_rail_mode: str  # "hidden" | "drawer" | "side"
    companion: BandRect
    companion_mode: str  # "ambient" | "compact" | "full"
    dropped: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "layout": self.layout,
            "breakpoint": self.breakpoint,
            "scale": self.scale,
            "gapsOut": self.gaps_out,
            "gapsIn": self.gaps_in,
            "topBar": self.top_bar.to_json(),
            "dock": self.dock.to_json(),
            "work": self.work.to_json(),
            "taskRail": None if self.task_rail is None else self.task_rail.to_json(),
            "taskRailMode": self.task_rail_mode,
            "companion": self.companion.to_json(),
            "companionMode": self.companion_mode,
            "dropped": list(self.dropped),
            "notes": list(self.notes),
            "absolutePlacementAvailable": False,
        }


@dataclass
class AdaptiveLayoutState:
    """Persisted presentation preference + retained task cursor (not truth)."""

    layout: str = "desktop"
    task_id: str = ""
    event_sequence: int | None = None
    approval_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "layout": self.layout,
            "taskId": self.task_id,
            "eventSequence": self.event_sequence,
            "approvalId": self.approval_id,
            "artifactRefs": list(self.artifact_refs),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any] | None) -> "AdaptiveLayoutState":
        data = dict(payload or {})
        layout = normalise_layout(str(data.get("layout") or "desktop"))
        sequence = data.get("eventSequence")
        if sequence is not None and not isinstance(sequence, bool):
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                sequence = None
        refs = data.get("artifactRefs") or []
        if not isinstance(refs, list):
            refs = []
        return cls(
            layout=layout,
            task_id=str(data.get("taskId") or ""),
            event_sequence=sequence,
            approval_id=str(data.get("approvalId") or ""),
            artifact_refs=[str(item) for item in refs if str(item).strip()],
        )


def normalise_layout(name: str) -> str:
    raw = str(name or "").strip().lower()
    if raw in LEGACY_PROFILE_ALIASES:
        return LEGACY_PROFILE_ALIASES[raw]
    if raw in LAYOUTS:
        return raw
    return "desktop"


def next_layout(current: str) -> str:
    ordered = list(LAYOUTS)
    layout = normalise_layout(current)
    return ordered[(ordered.index(layout) + 1) % len(ordered)]


def breakpoint_for(width: int) -> str:
    if width >= 1800:
        return "wide"
    if width >= 1500:
        return "standard"
    if width >= 1200:
        return "compact"
    return "narrow"


def solve(
    screen: ScreenRect | Mapping[str, Any],
    *,
    layout: str = "desktop",
    scale: float = 1.0,
    rail_collapsed: bool = False,
) -> LayoutSolution:
    """Compute chrome bands for Desktop / Focus / Studio.

    At 1280×800 and 1366×768 the task rail becomes a drawer; at 1920×1080+ Focus
    and Studio may use a side rail (Adaptive Hybrid Spec §4.4).
    """
    if isinstance(screen, Mapping):
        screen = ScreenRect(width=int(screen["width"]), height=int(screen["height"]))
    layout = normalise_layout(layout)
    scale = max(1.0, float(scale))
    width, height = screen.width, screen.height
    point = breakpoint_for(width)

    top_bar_h = max(32, int(round(36 * min(scale, 1.5))))
    dock_h = max(48, int(round(56 * min(scale, 1.5))))
    edge = max(12, int(round(16 * min(scale, 1.25))))
    gap = max(8, int(round(12 * min(scale, 1.25))))

    top_bar = BandRect(0, 0, width, top_bar_h)
    dock_w = min(width - 2 * edge, 560)
    dock = BandRect(int((width - dock_w) / 2), height - dock_h - edge, dock_w, dock_h)

    band_top = top_bar_h + edge
    band_bottom = dock.y - gap
    band_height = max(200, band_bottom - band_top)

    notes: list[str] = []
    dropped: list[str] = []

    if layout == "desktop":
        # Conventional apps fill the work area; companion is a compact corner.
        companion_size = int(round(min(200, max(120, width * 0.11)) * min(scale, 1.5)))
        companion = BandRect(
            width - edge - companion_size,
            band_bottom - companion_size,
            companion_size,
            companion_size,
        )
        work = BandRect(edge, band_top, width - 2 * edge, band_height)
        return LayoutSolution(
            layout=layout,
            breakpoint=point,
            scale=scale,
            gaps_out=edge,
            gaps_in=gap,
            top_bar=top_bar,
            dock=dock,
            work=work,
            task_rail=None,
            task_rail_mode="hidden",
            companion=companion,
            companion_mode="ambient",
            dropped=("taskRail",),
            notes=("desktop: compact companion; task rail hidden until Focus/Studio",),
        )

    # Focus / Studio share a rail; Studio gives the companion more free space.
    side_rail_ok = width >= 1500 and not rail_collapsed
    if side_rail_ok:
        rail_w = int(round((340 if layout == "studio" else 300) * min(scale, 1.5)))
        rail_w = min(rail_w, int(width * 0.28))
        task_rail = BandRect(width - edge - rail_w, band_top, rail_w, band_height)
        task_rail_mode = "side"
        work_w = max(320, task_rail.x - gap - edge)
        work = BandRect(edge, band_top, work_w, band_height)
    else:
        # Drawer: bottom strip above the dock, does not cover file actions forever.
        drawer_h = int(round(min(220, max(140, band_height * 0.28)) * min(scale, 1.35)))
        task_rail = BandRect(edge, band_bottom - drawer_h, width - 2 * edge, drawer_h)
        task_rail_mode = "drawer"
        work = BandRect(edge, band_top, width - 2 * edge, max(160, task_rail.y - gap - band_top))
        notes.append("narrow/compact: task rail is a drawer")

    if layout == "focus":
        companion_size = int(round(min(180, max(100, width * 0.09)) * min(scale, 1.5)))
        companion_mode = "compact"
        notes.append("focus: one primary work surface; collapsible task rail")
    else:
        companion_size = int(round(min(360, max(180, width * 0.18)) * min(scale, 1.5)))
        companion_mode = "full"
        notes.append("studio: expanded canvas; companion only in free space")

    # Companion must stay inside the work band (never over the rail/drawer).
    companion_size = min(companion_size, work.width, work.height)
    companion_size = max(64, companion_size)
    companion = BandRect(
        work.x + work.width - companion_size,
        work.y + work.height - companion_size,
        companion_size,
        companion_size,
    )

    return LayoutSolution(
        layout=layout,
        breakpoint=point,
        scale=scale,
        gaps_out=edge,
        gaps_in=gap,
        top_bar=top_bar,
        dock=dock,
        work=work,
        task_rail=task_rail,
        task_rail_mode=task_rail_mode,
        companion=companion,
        companion_mode=companion_mode,
        dropped=tuple(dropped),
        notes=tuple(notes),
    )


def retain_task_cursor(
    state: AdaptiveLayoutState,
    *,
    layout: str | None = None,
    task_id: str | None = None,
    event_sequence: int | None = None,
    approval_id: str | None = None,
    artifact_refs: list[str] | None = None,
) -> AdaptiveLayoutState:
    """Switch layout while retaining task IDs / cursors / approvals / artifacts."""
    next_state = AdaptiveLayoutState.from_json(state.to_json())
    if layout is not None:
        next_state.layout = normalise_layout(layout)
    if task_id is not None:
        next_state.task_id = str(task_id)
    if event_sequence is not None:
        next_state.event_sequence = int(event_sequence)
    if approval_id is not None:
        next_state.approval_id = str(approval_id)
    if artifact_refs is not None:
        next_state.artifact_refs = [str(item) for item in artifact_refs if str(item).strip()]
    return next_state


def hyprland_dispatch_plan(solution: LayoutSolution) -> dict[str, Any]:
    """Describe what a Hyprland session *may* apply — no compositor side effects.

    Callers with `hyprctl` can execute the supported subset. Unsupported items
    stay listed under ``unsupported`` rather than being silently claimed.
    """
    supported = [
        {"kind": "keyword", "args": ["general:gaps_out", str(solution.gaps_out)]},
        {"kind": "keyword", "args": ["general:gaps_in", str(solution.gaps_in)]},
    ]
    unsupported = [
        "absolute companion coordinates (no unrestricted Wayland placement claim)",
        "synthetic input / focus steal outside approval Trust path",
    ]
    if solution.task_rail_mode == "hidden":
        supported.append({"kind": "signal", "args": ["task-rail", "hide"]})
    else:
        supported.append(
            {
                "kind": "signal",
                "args": ["task-rail", solution.task_rail_mode, solution.task_rail.to_json() if solution.task_rail else {}],
            }
        )
    supported.append(
        {
            "kind": "signal",
            "args": ["companion-mode", solution.companion_mode],
        }
    )
    return {
        "layout": solution.layout,
        "compositor": "hyprland",
        "supported": supported,
        "unsupported": unsupported,
        "absolutePlacementAvailable": False,
    }


def overlapping_pairs(solution: LayoutSolution) -> list[tuple[str, str]]:
    """Return overlapping chrome pairs that must not collide."""

    def boxes() -> dict[str, BandRect]:
        items = {
            "topBar": solution.top_bar,
            "dock": solution.dock,
            "work": solution.work,
            "companion": solution.companion,
        }
        if solution.task_rail is not None:
            items["taskRail"] = solution.task_rail
        return items

    names = list(boxes().keys())
    rects = boxes()
    hits: list[tuple[str, str]] = []
    for index, left in enumerate(names):
        a = rects[left]
        for right in names[index + 1 :]:
            b = rects[right]
            # work may share edge with rail/companion by design; only interior overlap counts.
            if left == "work" and right in {"taskRail", "companion"}:
                continue
            if right == "work" and left in {"taskRail", "companion"}:
                continue
            if _overlap_interior(a, b):
                hits.append((left, right))
    return hits


def _overlap_interior(a: BandRect, b: BandRect) -> bool:
    return not (
        a.x + a.width <= b.x
        or b.x + b.width <= a.x
        or a.y + a.height <= b.y
        or b.y + b.height <= a.y
    )

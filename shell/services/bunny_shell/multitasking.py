# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Snap / workspaces chrome. Geometry lives in layout.js and is tested under node."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

SNAP_TARGETS = ("left", "right", "maximize", "restore")
COMPANION_CORNER = "bottom-right"
NAMED_VIEWPORTS = {
    "hd1366": {"width": 1366, "height": 768, "name": "1366"},
    "fhd": {"width": 1920, "height": 1080, "name": "1080"},
    "uhd": {"width": 3840, "height": 2160, "name": "4K"},
}


def viewport_for_name(name: str | None) -> dict[str, Any]:
    key = str(name or "").casefold()
    if key in {"1366", "hd1366", "laptop"}:
        return dict(NAMED_VIEWPORTS["hd1366"])
    if key in {"4k", "uhd", "2160"}:
        return dict(NAMED_VIEWPORTS["uhd"])
    return dict(NAMED_VIEWPORTS["fhd"])


def build_multitasking(
    *,
    workspaces: Sequence[Mapping[str, Any]] | None = None,
    active_id: str = "",
    reduced_motion: bool = False,
    screen: Mapping[str, Any] | None = None,
    scale: float = 1,
    profile: str = "skeleton",
) -> dict[str, Any]:
    area = dict(screen or NAMED_VIEWPORTS["fhd"])
    items = []
    for item in workspaces or ():
        rec = dict(item)
        ident = str(rec.get("id") or "")
        items.append({
            "id": ident,
            "name": str(rec.get("name") or "Workspace"),
            "archived": bool(rec.get("archivedAt")),
            "active": ident == str(active_id or ""),
        })
    return {
        "kind": "Multitasking",
        "title": "Workspaces",
        "summary": "Snap windows around Bunny. The figure stays bottom-right and does not cover work.",
        "companionCorner": COMPANION_CORNER,
        "companionCoversWork": False,
        "snapTargets": list(SNAP_TARGETS),
        "workspaces": items,
        "companionRequired": False,
        "chatbot": False,
        "reducedMotion": bool(reduced_motion),
        "motionMs": 0 if reduced_motion else 220,
        "liveMutterTiling": False,
        "accessibleName": "Workspaces and snap",
        "canFocus": True,
        "viewport": f"{area.get('width')}×{area.get('height')}",
        "scale": scale,
        "profile": profile,
        "doing": "Arranging windows",
        "bunny": "In the corner",
        "next": "Snap left or right. Maximize leaves the companion visible.",
    }

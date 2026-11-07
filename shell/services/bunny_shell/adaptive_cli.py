# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI for Adaptive Hybrid layout switching on the Hyprland Bunny session."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .adaptive_layout import (
    LAYOUTS,
    AdaptiveLayoutState,
    hyprland_dispatch_plan,
    next_layout,
    normalise_layout,
    retain_task_cursor,
    solve,
    ScreenRect,
)
from .paths import JsonStore, ensure_private_dir, state_dir
from .task_rail import build_task_rail


STATE_NAME = "adaptive-layout.json"


def state_path() -> Path:
    return state_dir() / STATE_NAME


def _store() -> JsonStore:
    ensure_private_dir(state_dir())
    return JsonStore(state_path(), default={})


def load_state() -> AdaptiveLayoutState:
    return AdaptiveLayoutState.from_json(_store().read())


def save_state(state: AdaptiveLayoutState) -> None:
    _store().write(state.to_json())


def _screen_from_args(args: argparse.Namespace) -> ScreenRect:
    return ScreenRect(width=int(args.width), height=int(args.height))


def _maybe_apply_hyprland(plan: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """Apply the supported keyword subset when hyprctl exists; else NOT_RUN."""
    hyprctl = shutil.which("hyprctl")
    result: dict[str, Any] = {
        "hyprctl": hyprctl or "",
        "applied": [],
        "skipped": [],
        "status": "DRY_RUN" if dry_run else "NOT_RUN",
    }
    if dry_run:
        result["skipped"] = [item for item in plan.get("supported", [])]
        return result
    if not hyprctl:
        result["skipped"] = list(plan.get("supported", []))
        result["status"] = "NOT_RUN"
        result["reason"] = "hyprctl not on PATH (host without Hyprland session)"
        return result

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in plan.get("supported", []):
        kind = item.get("kind")
        args = item.get("args") or []
        if kind == "keyword" and len(args) >= 2:
            completed = subprocess.run(
                [hyprctl, "keyword", str(args[0]), str(args[1])],
                check=False,
                capture_output=True,
                text=True,
            )
            entry = {**item, "returncode": completed.returncode}
            if completed.returncode == 0:
                applied.append(entry)
            else:
                entry["stderr"] = (completed.stderr or "").strip()
                skipped.append(entry)
        else:
            # Signals for companion/task-rail surfaces — no compositor keyword.
            skipped.append({**item, "reason": "signal-only; chrome consumers poll state"})
    result["applied"] = applied
    result["skipped"] = skipped
    result["status"] = "APPLIED" if applied else "NOT_RUN"
    return result


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunny-adaptive-layout",
        description="Adaptive Hybrid Desktop/Focus/Studio layouts for Bunny Hyprland",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show persisted layout state and geometry")
    show.add_argument("--width", type=int, default=1920)
    show.add_argument("--height", type=int, default=1080)
    show.add_argument("--scale", type=float, default=1.0)
    show.add_argument("--rail-collapsed", action="store_true")

    set_cmd = sub.add_parser("set", help="Set layout; retain task cursor fields")
    set_cmd.add_argument("layout", choices=LAYOUTS)
    set_cmd.add_argument("--width", type=int, default=1920)
    set_cmd.add_argument("--height", type=int, default=1080)
    set_cmd.add_argument("--scale", type=float, default=1.0)
    set_cmd.add_argument("--rail-collapsed", action="store_true")
    set_cmd.add_argument("--task-id", default=None)
    set_cmd.add_argument("--event-sequence", type=int, default=None)
    set_cmd.add_argument("--approval-id", default=None)
    set_cmd.add_argument("--artifact", action="append", default=None)
    set_cmd.add_argument("--apply", action="store_true", help="Apply hyprctl keywords when available")
    set_cmd.add_argument("--dry-run", action="store_true")

    cycle = sub.add_parser("cycle", help="Cycle desktop → focus → studio")
    cycle.add_argument("--width", type=int, default=1920)
    cycle.add_argument("--height", type=int, default=1080)
    cycle.add_argument("--scale", type=float, default=1.0)
    cycle.add_argument("--apply", action="store_true")
    cycle.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="List layout names")

    rail = sub.add_parser("rail", help="Project a task rail from presentation JSON")
    rail.add_argument(
        "--presentation",
        type=Path,
        help="Path to presentation JSON (PresentationState.to_json shape)",
    )
    rail.add_argument("--collapsed", action="store_true")
    rail.add_argument("--layout", default=None)

    waybar = sub.add_parser("waybar", help="Minimal JSON for a Waybar custom module")

    args = parser.parse_args(argv)

    if args.command == "list":
        print(json.dumps({"layouts": list(LAYOUTS), "compositor": "hyprland"}, indent=2))
        return 0

    if args.command == "waybar":
        state = load_state()
        text = {
            "text": state.layout.title(),
            "class": f"bunny-layout-{state.layout}",
            "tooltip": (
                f"Adaptive layout: {state.layout}"
                + (f" · task {state.task_id}" if state.task_id else "")
            ),
        }
        print(json.dumps(text, ensure_ascii=False))
        return 0

    if args.command == "rail":
        state = load_state()
        payload: dict[str, Any] = {}
        if args.presentation:
            payload = json.loads(args.presentation.read_text(encoding="utf-8"))
        layout = normalise_layout(args.layout or state.layout)
        model = build_task_rail(payload, collapsed=bool(args.collapsed), layout=layout)
        print(json.dumps(model, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    state = load_state()
    screen = _screen_from_args(args)
    scale = float(getattr(args, "scale", 1.0))
    rail_collapsed = bool(getattr(args, "rail_collapsed", False))

    if args.command == "show":
        solution = solve(
            screen,
            layout=state.layout,
            scale=scale,
            rail_collapsed=rail_collapsed,
        )
        print(
            json.dumps(
                {
                    "state": state.to_json(),
                    "solution": solution.to_json(),
                    "dispatch": hyprland_dispatch_plan(solution),
                    "compositor": os.environ.get("BUNNY_DESKTOP_COMPOSITOR", ""),
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "cycle":
        target = next_layout(state.layout)
        state = retain_task_cursor(state, layout=target)
        save_state(state)
        solution = solve(screen, layout=state.layout, scale=scale)
        plan = hyprland_dispatch_plan(solution)
        apply_result = _maybe_apply_hyprland(
            plan, dry_run=bool(args.dry_run) or not bool(args.apply)
        )
        print(
            json.dumps(
                {
                    "state": state.to_json(),
                    "solution": solution.to_json(),
                    "dispatch": plan,
                    "apply": apply_result,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "set":
        state = retain_task_cursor(
            state,
            layout=args.layout,
            task_id=args.task_id,
            event_sequence=args.event_sequence,
            approval_id=args.approval_id,
            artifact_refs=args.artifact,
        )
        save_state(state)
        solution = solve(
            screen,
            layout=state.layout,
            scale=scale,
            rail_collapsed=rail_collapsed,
        )
        plan = hyprland_dispatch_plan(solution)
        apply_result = _maybe_apply_hyprland(
            plan, dry_run=bool(args.dry_run) or not bool(args.apply)
        )
        print(
            json.dumps(
                {
                    "state": state.to_json(),
                    "solution": solution.to_json(),
                    "dispatch": plan,
                    "apply": apply_result,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return 0

    parser.error(f"unknown command {args.command}")
    return 2

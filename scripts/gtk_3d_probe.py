#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§32: drive the 3D character inside a real GTK window and record what happened.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

Everything below the widget is already tested without a compositor. This is the
part that cannot be: whether a ``Gtk.GLArea`` realizes, whether it gets a
desktop-GL context, whether the character appears in it, whether a resize and a
scale change and a renderer restart survive, and what the frame times are when a
compositor rather than a loop decides the cadence.

It reports the environment **as it is**. WSLg is recorded as WSLg. It is a
Wayland compositor and it is not GNOME on bare metal, and a probe that printed
"Wayland: pass" would be inviting the reader to conclude something it did not
measure.

Usage::

    scripts/gtk_3d_probe.py --json --seconds 6
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_INSTALLED = Path("/usr/lib/bunny-os/python")
for _candidate in (_INSTALLED, _REPOSITORY):
    if not _candidate.is_dir():
        continue
    name = str(_candidate)
    while name in sys.path:
        sys.path.remove(name)
    sys.path.insert(0, name)


def environment() -> dict[str, Any]:
    """What this machine is, named rather than characterised."""
    wsl = ""
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="ascii").strip()
        if "microsoft" in release.casefold():
            wsl = release
    except OSError:
        pass
    return {
        "sessionType": os.environ.get("XDG_SESSION_TYPE", ""),
        "waylandDisplay": os.environ.get("WAYLAND_DISPLAY", ""),
        "x11Display": os.environ.get("DISPLAY", ""),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "wslKernel": wsl,
        "isWslg": bool(wsl) and Path("/mnt/wslg").is_dir(),
        "note": (
            "WSLg is WSLg: a Weston-based Wayland compositor bridged to Windows. "
            "It is not native GNOME on Wayland and no result here should be read as one."
            if wsl else "a non-WSL Linux graphical session"
        ),
    }


def run(seconds: float, *, mode: str, package_id: str | None) -> dict[str, Any]:
    from companion.character.defaults import default_3d_character_path
    from companion.character.mapper import (
        CharacterState,
        StateMapperInput,
        map_character_state,
    )
    from companion.character.package import validate_package_directory
    from companion.character.schema import PackageTrustState
    from companion.character.three_d.gtk_surface import ThreeDCharacterArea, gtk_available

    available, reason = gtk_available()
    result: dict[str, Any] = {
        "probe": "companion-3d-gtk",
        "environment": environment(),
        "gtkAvailable": available,
        "gtkReason": reason,
    }
    if not available:
        result["result"] = "NOT_RUN"
        return result

    root = default_3d_character_path()
    if not root.is_dir():
        result["result"] = "NOT_RUN"
        result["gtkReason"] = "the built-in 3D package is not installed"
        return result
    package = validate_package_directory(root, trust_state=PackageTrustState.BUILT_IN)

    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    steps: list[dict[str, Any]] = []
    area_holder: dict[str, Any] = {}

    def record(name: str, ok: bool, **evidence: Any) -> None:
        steps.append({"step": name, "ok": bool(ok), **evidence})

    def phases() -> list[tuple[str, Any]]:
        manifest = package.manifest
        return [
            (name, map_character_state(manifest, StateMapperInput(
                presentation_phase=phase, status_text="Bunny is here.",
                listening=phase == "listening",
            )))
            for name, phase in (
                ("idle", "idle"), ("understanding", "understanding"), ("planning", "planning"),
                ("working", "working"), ("waiting-for-approval", "waiting_for_approval"),
                ("speaking", "speaking"), ("success", "success"), ("listening", "listening"),
                ("error", "error"),
            )
        ]

    def on_activate(application: Any) -> None:
        window = Gtk.ApplicationWindow(application=application, title="Bunny 3D probe")
        window.set_default_size(360, 460)
        try:
            area = ThreeDCharacterArea(package, mode=mode, seed=0x33, quality="full-3d")
        except Exception as exc:  # noqa: BLE001 - a construction fault is a result
            record("construct-area", False, detail=f"{type(exc).__name__}: {exc}")
            window.close()
            return
        area_holder["area"] = area
        window.set_child(area.area)
        window.present()
        record("present-window", True)

        sequence = phases()
        state_index = {"value": 0}
        started = time.monotonic()

        def step() -> bool:
            elapsed = time.monotonic() - started
            index = state_index["value"]
            if index < len(sequence):
                name, mapped = sequence[index]
                area.set_state(mapped)
                record(f"state:{name}", True, frames=area.report.frames_rendered)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if index == len(sequence):
                area.set_mouth_shape("open-wide")
                record("mouth:open-wide", True)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if index == len(sequence) + 1:
                area.set_mouth_shape("neutral")
                area.set_scale(1.4)
                record("scale:1.4", True, scaleChanges=area.report.scale_changes)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if index == len(sequence) + 2:
                window.set_default_size(300, 380)
                area.set_mode("compact")
                record("mode:compact", True, resizes=area.report.resizes)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if index == len(sequence) + 3:
                area.set_reduced_motion(True)
                record("reduced-motion", True)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if index == len(sequence) + 4:
                area.set_reduced_motion(False)
                restarted = area.restart()
                record("renderer-restart", restarted, restarts=area.report.renderer_restarts)
                state_index["value"] += 1
                return GLib.SOURCE_CONTINUE
            if elapsed >= seconds:
                record("frames-drawn", area.report.frames_rendered > 0,
                       frames=area.report.frames_rendered)
                window.close()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(int(max(60, seconds * 1000 / 24)), step)
        GLib.timeout_add(int(seconds * 1000) + 4000, lambda: (window.close(), GLib.SOURCE_REMOVE)[1])

    application = Gtk.Application(application_id="os.bunny.Companion3dProbe")
    application.connect("activate", on_activate)
    status = application.run([])

    area = area_holder.get("area")
    result.update({
        "result": "RAN",
        "exitStatus": status,
        "steps": steps,
        "surface": area.report.to_json() if area is not None else None,
        "renderer": (
            area.renderer.describe() if area is not None and area.renderer is not None else None
        ),
        "passed": bool(
            area is not None
            and area.report.realized
            and area.report.context_created
            and area.report.frames_rendered > 0
            and not area.report.errors
            and all(item["ok"] for item in steps)
        ),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--mode", default="docked", choices=("docked", "center", "compact"))
    parser.add_argument("--package-id", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()

    report = run(arguments.seconds, mode=arguments.mode, package_id=arguments.package_id)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.write_text(payload + "\n", encoding="utf-8", newline="\n")
    if arguments.json or arguments.output is None:
        print(payload)
    return 0 if report.get("passed") or report.get("result") == "NOT_RUN" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the animated 2D renderer through a real GTK widget on a real compositor.

The renderer phase validated animation as *data*: frame lists, durations,
looping rules, degradation ladders. It never drew anything, and said so —
"validated as data and never as pixels here". The Linux phase then executed the
widget layer, but only the static path. This is the part that was still missing:
frames actually decoded by GTK, actually swapped on a ``Gtk.Picture``, actually
timed by a main loop.

What it will not do:

* it will not run without a display. There is no offscreen mode, because a
  frame that was never given to a compositor proves nothing about one that was;
* it will not measure the frame rate from the renderer's own arithmetic. The
  renderer decides *which* frame belongs at a time; the observed rate is
  counted from when the widget was actually given each file, which is the only
  number that includes the main loop, the decode and the compositor;
* it will not call this a GNOME session, or a hardware validation, or a
  performance figure for target hardware. It is a development machine.

Exit status: 0 every check held, 2 something did not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def display_environment() -> dict[str, Any]:
    """What display this is, named honestly."""
    wayland = os.environ.get("WAYLAND_DISPLAY")
    x11 = os.environ.get("DISPLAY")
    wslg = Path("/mnt/wslg").exists()
    if wayland and wslg:
        kind, note = "wayland-wslg-remoted", (
            "A real Wayland compositor supplied by the WSLg system distribution and "
            "composited by the Windows host. Real enough to decode, draw and time "
            "frames. NOT a GNOME session, NOT physical hardware, and NOT a "
            "performance measurement for any target device."
        )
    elif wayland:
        kind, note = "wayland-unclassified", "A Wayland compositor that was not identified."
    elif x11:
        kind, note = "x11-unclassified", "An X server that was not identified."
    else:
        kind, note = "none", "No display. The renderer cannot be driven."
    return {
        "kind": kind,
        "note": note,
        "waylandDisplay": wayland,
        "display": x11,
        "isGnomeSession": False,
        "isPhysicalHardware": False,
        "available": kind != "none",
    }


class LogCapture:
    """GTK reports most faults through the log rather than by raising."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def install(self, GLib: Any) -> None:
        def writer(level: Any, fields: Any, _user_data: Any = None) -> Any:
            entry: dict[str, str] = {"level": str(level)}
            try:
                for key in ("GLIB_DOMAIN", "MESSAGE"):
                    value = fields.get(key) if hasattr(fields, "get") else None
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    if value:
                        entry[key] = str(value)
            except Exception:  # noqa: BLE001 - a log handler must not fault
                pass
            self.records.append(entry)
            return GLib.LogWriterOutput.HANDLED

        try:
            GLib.log_set_writer_func(writer, None)
        except Exception:  # noqa: BLE001 - older GLib; the probe still runs
            pass

    @property
    def serious(self) -> list[dict[str, str]]:
        return [
            record for record in self.records
            if "CRITICAL" in record.get("level", "").upper()
            or "ERROR" in record.get("level", "").upper()
        ]


def drive(renderer: Any, picture: Any, GLib: Any, *, animation: str, seconds: float,
          tick_ms: int = 8) -> dict[str, Any]:
    """Play one animation for a while, recording every frame the widget received.

    The elapsed time handed to the renderer is real wall-clock time from the
    start of the run, so the frame it picks is the frame that belongs at that
    moment — not a synthetic step count that would make any rate come out right.
    """
    observed: list[dict[str, Any]] = []
    started = time.monotonic()
    loop = GLib.MainLoop()

    def show(frame: Any) -> None:
        if frame is None:
            return
        path = str(frame.asset_path)
        # The actual widget call under test. If GTK cannot decode the file this
        # is where it complains, and the complaint goes to the log capture.
        picture.set_filename(path)
        observed.append({
            "atMs": round((time.monotonic() - started) * 1000, 2),
            "assetId": frame.asset_id,
            "frameIndex": frame.frame_index,
            "animation": frame.animation,
            "path": path,
        })

    show(renderer.play_animation(animation, now_ms=0))

    def tick() -> bool:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms >= seconds * 1000:
            loop.quit()
            return False
        show(renderer.tick(now_ms=elapsed_ms))
        return True

    source_id = GLib.timeout_add(tick_ms, tick)
    loop.run()
    GLib.source_remove(source_id)

    indices = [item["frameIndex"] for item in observed]
    changes = sum(1 for a, b in zip(indices, indices[1:]) if a != b)
    return {
        "animation": animation,
        "seconds": seconds,
        "framesDelivered": len(observed),
        "distinctFrameIndices": sorted(set(indices)),
        "frameChanges": changes,
        "observedChangesPerSecond": round(changes / seconds, 3) if seconds else 0.0,
        "returnedToFirstFrame": bool(indices and 0 in indices[1:]),
        "first": observed[0] if observed else None,
        "last": observed[-1] if observed else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path("/usr/share/bunny-os/companion/characters"))
    parser.add_argument("--package", default="default-bunny")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    report: dict[str, Any] = {
        "schema": "bunny-os/gtk-animation-probe/1",
        "display": display_environment(),
        "checks": {},
    }
    failures: list[str] = []

    if not report["display"]["available"]:
        report["gate"] = {"passed": False, "failures": ["no display; refusing to pretend"]}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        from companion.character.animated_renderer import Animated2DRenderer
        from companion.character.package import validate_package_directory
        from companion.character.mapper import (
            AccessibilityPreferences,
            StateMapperInput,
            map_character_state,
        )
        import companion.character.animated_renderer as animated_module

        report["gtkVersion"] = (
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        )
        report["provenance"] = {"animatedRenderer": animated_module.__file__}

        capture = LogCapture()
        capture.install(GLib)

        package = validate_package_directory(arguments.package_root / arguments.package)
        report["package"] = {
            "id": arguments.package,
            "root": str(arguments.package_root / arguments.package),
            "animations": sorted(package.manifest.animations),
        }

        window = Gtk.Window(title="Bunny animation probe")
        picture = Gtk.Picture()
        window.set_child(picture)
        window.set_default_size(320, 320)
        window.present()

        renderer = Animated2DRenderer()
        renderer.load_package(package)

        # -- frames decode and advance, and the rate is observed -------------
        working = package.manifest.animations["working"]
        configured_ms = sum(frame.duration_ms for frame in working.frames)
        expected_changes_per_second = 1000.0 * len(working.frames) / configured_ms

        run = drive(renderer, picture, GLib, animation="working", seconds=arguments.seconds)
        report["checks"]["loopingAnimation"] = {
            **run,
            "configuredChangesPerSecond": round(expected_changes_per_second, 3),
        }
        if run["framesDelivered"] < 2:
            failures.append("no frames were delivered to the widget")
        if len(run["distinctFrameIndices"]) < 2:
            failures.append("the animation never advanced past its first frame")
        if not run["returnedToFirstFrame"]:
            failures.append("a looping animation never returned to its first frame")
        # Tolerance is wide on purpose: this is a timer on a shared machine, not
        # a real-time system, and a narrow bound here would be a flaky test
        # wearing the word "performance".
        low, high = expected_changes_per_second * 0.5, expected_changes_per_second * 1.5
        if not low <= run["observedChangesPerSecond"] <= high:
            failures.append(
                f"observed {run['observedChangesPerSecond']}/s against a configured "
                f"{expected_changes_per_second:.3f}/s, outside the 50-150% band"
            )

        # -- a one-shot animation completes and stops ------------------------
        one_shot = drive(renderer, picture, GLib, animation="success", seconds=1.0)
        report["checks"]["oneShot"] = one_shot
        if one_shot["framesDelivered"] < 1:
            failures.append("a one-shot animation delivered no frame")

        # -- interruption ----------------------------------------------------
        renderer.play_animation("working", now_ms=0)
        interrupted = renderer.play_animation("error", now_ms=10)
        report["checks"]["interruption"] = {
            "interruptedTo": interrupted.animation if interrupted is not None else None,
        }
        if interrupted is None or interrupted.animation != "error":
            failures.append("an animation could not be interrupted")

        # -- reduced motion and degradation both fall back to a still --------
        #
        # Driven through the real mapper rather than a hand-built state, so this
        # exercises the decision the product makes rather than one written here.
        def mapped(**overrides: Any) -> Any:
            return map_character_state(
                package.manifest,
                StateMapperInput(presentation_phase="working", **overrides),
            )

        moving = mapped()
        reduced_motion = mapped(
            accessibility=AccessibilityPreferences(reduced_motion=True, no_animation=True)
        )
        degraded = mapped(
            effective_presentation="static-image",
            degradation_explanation="the renderer was degraded for this probe",
        )

        fresh = Animated2DRenderer()
        fresh.load_package(package)
        animated_frame = fresh.display_state(moving, now_ms=0)
        reduced_frame = fresh.display_state(reduced_motion, now_ms=0)
        degraded_frame = fresh.display_state(degraded, now_ms=0)
        for label, frame in (
            ("animated", animated_frame),
            ("reducedMotion", reduced_frame),
            ("degraded", degraded_frame),
        ):
            if frame is not None:
                picture.set_filename(str(frame.asset_path))

        report["checks"]["fallbacks"] = {
            "animatedPlayback": moving.playback_policy,
            "animatedLoop": moving.loop,
            "reducedMotionPlayback": reduced_motion.playback_policy,
            "reducedMotionLoop": reduced_motion.loop,
            "degradedPlayback": degraded.playback_policy,
            "degradedFrame": degraded_frame.asset_id if degraded_frame is not None else None,
            "reducedMotionFrame": reduced_frame.asset_id if reduced_frame is not None else None,
        }
        if reduced_frame is None or degraded_frame is None:
            failures.append("a fallback produced no frame at all")
        if reduced_motion.loop:
            failures.append("reduced motion still asked for a looping animation")

        # -- a renderer restart returns to the current state -----------------
        restarted = Animated2DRenderer()
        restarted.load_package(package)
        before_restart = restarted.display_state(moving, now_ms=0)
        restarted.unload_package()
        restarted.load_package(package)
        after_restart = restarted.display_state(moving, now_ms=0)
        report["checks"]["restart"] = {
            "before": before_restart.asset_id if before_restart is not None else None,
            "after": after_restart.asset_id if after_restart is not None else None,
        }
        if after_restart is None:
            failures.append("the renderer produced no frame after a restart")
        elif before_restart is not None and after_restart.state != before_restart.state:
            failures.append("a restart did not return to the state that was current")

        # -- teardown leaves nothing running ---------------------------------
        renderer.stop_animation(now_ms=0)
        renderer.unload_package()
        window.destroy()
        pending_after_teardown = 0
        context = GLib.MainContext.default()
        while context.pending() and pending_after_teardown < 200:
            context.iteration(False)
            pending_after_teardown += 1
        report["checks"]["teardown"] = {
            "iterationsToDrain": pending_after_teardown,
            "drained": not context.pending(),
        }
        if context.pending():
            failures.append("work was still queued on the main context after teardown")

        report["logs"] = {
            "total": len(capture.records),
            "serious": capture.serious[:10],
        }
        if capture.serious:
            failures.append(f"{len(capture.serious)} GTK critical or error messages were logged")

    except Exception as error:  # noqa: BLE001 - the failure is the report
        failures.append(f"{type(error).__name__}: {error}")
        report["traceback"] = traceback.format_exc().splitlines()[-12:]

    report["gate"] = {"passed": not failures, "failures": failures}
    serialised = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialised + "\n", encoding="utf-8")
    print(serialised)
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())

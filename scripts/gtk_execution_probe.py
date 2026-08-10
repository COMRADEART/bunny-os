#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute the companion's GTK widget layer against a real compositor.

The renderer phase shipped with an honest admission: "no compositor was
available; the widget code has never been executed." Everything about the
window — that the box hierarchy builds, that ``Gtk.Picture.set_filename``
accepts the shipped PNGs, that the character updates when the phase does — was
validated as data and never as pixels. This runs it.

What it will not do:

* it will not run without a display. There is no headless mode and no
  offscreen substitute, because a widget tree built without a compositor
  proves nothing about a widget tree shown on one, and a probe that quietly
  degraded would produce a pass with the same wording as a real one;
* it will not call the result a GNOME session, or a desktop-session claim of
  any kind. It reports the compositor it actually found. Under WSLg that is a
  Wayland compositor belonging to another distribution and composited by the
  Windows host — a genuine Wayland target for a GTK client, and not a Bunny OS
  desktop;
* it will not report success from the absence of an error. GTK reports most
  widget faults through the log rather than by raising, so criticals and
  warnings are captured and returned as evidence.

Exit status: 0 the widget layer ran, 2 it did not or there was no display.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import importlib.util
import sys
import traceback
from typing import Any

# Only when the package is not importable yet.
#
# For a standalone invocation nothing is importable, so this behaves exactly as
# it always has: the installed tree first, the checkout as a fallback.
#
# The guard is for the other case. In a process that already works — a test
# run, another tool that imported this one — the checkout is already on
# ``sys.path``, so the loop skipped it as already-present and inserted the
# *installed* tree in front of it. Every import after that came from whatever
# build happened to be installed, which on a qualification host is a build from
# an earlier phase. It fails loudly when that build is missing a module and
# silently when it is not, and the silent case is a whole test suite passing
# against code nobody changed.
if importlib.util.find_spec("companion") is None:
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))


def display_environment() -> dict[str, Any]:
    """What display is available, and what it is honestly called."""
    wayland = os.environ.get("WAYLAND_DISPLAY")
    x11 = os.environ.get("DISPLAY")
    wslg = Path("/mnt/wslg").exists()
    if wayland and wslg:
        kind = "wayland-wslg-remoted"
        note = (
            "A real Wayland compositor, supplied by the WSLg system distribution and "
            "composited by the Windows host. Sufficient to execute and observe the GTK "
            "widget layer. NOT a GNOME session, NOT a session compositor, and NOT "
            "evidence about a Bunny OS desktop."
        )
    elif wayland:
        kind = "wayland-unclassified"
        note = "A Wayland compositor whose identity was not established."
    elif x11:
        kind = "x11-unclassified"
        note = "An X server whose identity was not established."
    else:
        kind = "none"
        note = "No display. The widget layer cannot be executed."
    return {
        "kind": kind,
        "note": note,
        "waylandDisplay": wayland,
        "display": x11,
        "xdgSessionType": os.environ.get("XDG_SESSION_TYPE"),
        "xdgCurrentDesktop": os.environ.get("XDG_CURRENT_DESKTOP"),
        "isGnomeSession": False,
        "available": kind != "none",
    }


class LogCapture:
    """Collect GLib log messages, because GTK rarely raises."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def install(self, GLib: Any) -> None:
        def writer(level: Any, fields: Any, _user_data: Any = None) -> Any:
            entry: dict[str, str] = {}
            try:
                for key in ("GLIB_DOMAIN", "MESSAGE"):
                    value = fields.get(key) if hasattr(fields, "get") else None
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    if value:
                        entry[key] = str(value)
            except Exception:  # noqa: BLE001 - a log handler must not fault
                pass
            entry["level"] = str(level)
            self.records.append(entry)
            return GLib.LogWriterOutput.HANDLED

        try:
            GLib.log_set_writer_func(writer, None)
        except Exception:  # noqa: BLE001 - older GLib; the probe still runs
            pass

    @property
    def serious(self) -> list[dict[str, str]]:
        """Criticals and errors only. Warnings are reported but not fatal."""
        return [
            record for record in self.records
            if "CRITICAL" in record.get("level", "").upper()
            or "ERROR" in record.get("level", "").upper()
        ]


def describe_widget(widget: Any, depth: int = 0, limit: int = 3) -> dict[str, Any]:
    """A shallow shape of the built tree, to prove it is a tree."""
    node: dict[str, Any] = {"type": type(widget).__name__}
    try:
        node["visible"] = bool(widget.get_visible())
        node["mapped"] = bool(widget.get_mapped())
        node["realized"] = bool(widget.get_realized())
    except Exception:  # noqa: BLE001
        pass
    if depth >= limit:
        return node
    children = []
    try:
        child = widget.get_first_child()
        while child is not None and len(children) < 12:
            children.append(describe_widget(child, depth + 1, limit))
            child = child.get_next_sibling()
    except Exception:  # noqa: BLE001 - not every widget is a container
        pass
    if children:
        node["children"] = children
    return node


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", type=Path, help="the runtime socket to connect to")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--iterations",
        type=int,
        default=60,
        help="main-loop iterations to run after activation",
    )
    arguments = parser.parse_args(argv)

    report: dict[str, Any] = {
        "schema": "bunny-os/gtk-execution-probe/1",
        "display": display_environment(),
    }

    if not report["display"]["available"]:
        report["gate"] = {"passed": False, "reason": "no display; refusing to pretend"}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    try:
        from companion.gtk_shell import BunnyCompanionApplication
        import companion.gtk_shell as shell_module

        report["provenance"] = {"gtkShell": shell_module.__file__}

        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        report["gtkVersion"] = (
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        )

        capture = LogCapture()
        capture.install(GLib)

        application = BunnyCompanionApplication(arguments.endpoint)
        # register() then activate() rather than run(): run() blocks until the
        # window is closed, and nothing here can close it.
        application.app.register(None)
        application.app.activate()

        context = GLib.MainContext.default()
        iterations = 0
        while iterations < arguments.iterations and context.pending():
            context.iteration(False)
            iterations += 1
        # Give the frame clock work to do even if nothing was pending.
        for _ in range(arguments.iterations - iterations):
            context.iteration(False)
            iterations += 1

        window = application.window
        report["window"] = {
            "constructed": window is not None,
            "title": window.get_title() if window is not None else None,
            "realized": bool(window.get_realized()) if window is not None else False,
            "mapped": bool(window.get_mapped()) if window is not None else False,
            "size": [window.get_width(), window.get_height()] if window is not None else None,
        }
        report["mainLoopIterations"] = iterations
        report["widgetTree"] = describe_widget(window) if window is not None else None

        picture = application.picture
        report["character"] = {
            "pictureWidget": type(picture).__name__ if picture is not None else None,
            "pictureFile": (
                picture.get_file().get_path()
                if picture is not None and picture.get_file() is not None
                else None
            ),
            "staticCharacterLoaded": application.character is not None,
            "modelError": application.model.last_error or "",
        }
        report["logs"] = {
            "total": len(capture.records),
            "serious": capture.serious[:10],
            "sample": capture.records[:10],
        }

        realized = bool(window is not None and window.get_realized())
        failures: list[str] = []
        if window is None:
            failures.append("the window was never constructed")
        elif not realized:
            failures.append("the window was constructed but never realized on the compositor")
        if capture.serious:
            failures.append(f"{len(capture.serious)} GTK critical or error messages were logged")
        report["gate"] = {"passed": not failures, "failures": failures}

        try:
            application.app.quit()
        except Exception:  # noqa: BLE001 - shutting down must not fail the probe
            pass

    except Exception as error:  # noqa: BLE001 - the failure is the report
        report["gate"] = {
            "passed": False,
            "failures": [f"{type(error).__name__}: {error}"],
            "traceback": traceback.format_exc().splitlines()[-12:],
        }

    serialised = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialised + "\n", encoding="utf-8")
    print(serialised)
    return 0 if report["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

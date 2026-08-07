#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Diagnostics: what is wrong, and the buttons that usually fix it.

§18 asks for user-accessible diagnostics when Bunny fails, which means this
cannot live inside Bunny. It is a separate program, a separate desktop entry and
a separate process, and it reads systemd and the filesystem rather than the
companion protocol — because the failure it exists for is "there is no companion
to ask".

Two surfaces, one report. The GTK window is what a person opens from the
applications list. ``--text`` prints the same thing, which is what the recovery
console runs and what a screen reader gets without a window. §26 forbids
essential information existing only in a graphical surface, and the honest way
to hold that is to build the graphical surface *from* the text one.

Every action states its effect before it runs and none of them touches a task,
a message or a character package. The most destructive thing here resets a
presentation preference.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if importlib.util.find_spec("companion") is None:  # pragma: no cover - path setup
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))

from companion.support import companion_state_root  # noqa: E402
from companion.support.diagnose import RECOVERY_ACTIONS, diagnose  # noqa: E402
from companion.support.export import default_destination, export_diagnostics  # noqa: E402
from companion.support.safemode import (  # noqa: E402
    clear_safe_mode, read_safe_mode, request_safe_mode,
)

_ENV_KEYS = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "HOME", "USER", "PATH")


def _systemctl(*arguments: str) -> tuple[int, str]:
    binary = shutil.which("systemctl")
    if not binary:
        return 127, "systemctl is not available"
    try:
        result = subprocess.run(
            [binary, "--user", *arguments],
            env={key: os.environ[key] for key in _ENV_KEYS if key in os.environ},
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 126, str(error)
    return result.returncode, (result.stdout or result.stderr or "").strip()


def perform(action_id: str, *, root: Path | None = None) -> tuple[bool, str]:
    """Run one recovery action. ``(succeeded, what happened)``.

    Returns rather than raises, because every caller is a surface that has to
    show the outcome — a window that closed on an exception would take the
    diagnostics with it at the moment they were being read.
    """
    root = root or companion_state_root()
    if action_id == "restart":
        code, output = _systemctl("restart", "bunny-companion.service")
        if code != 0:
            return False, f"the runtime could not be restarted: {output or code}"
        _systemctl("restart", "bunny-companion-window.service")
        return True, "Bunny was restarted. Any task that was running has been recovered."
    if action_id == "disable-3d":
        request_safe_mode(
            reason="3D was disabled from the diagnostics window", origin="recovery",
            sticky=False, root=root,
        )
        return True, (
            "The next start will not use 3D. Your selected character is unchanged; "
            "it will be drawn with a simpler renderer."
        )
    if action_id == "reset-presentation":
        removed = _reset_presentation(root)
        return True, (
            f"Cleared {removed} presentation preference file(s). "
            "The machine's own capability decides again at the next start."
        )
    if action_id == "safe-mode":
        request_safe_mode(
            reason="Safe Mode was requested from the diagnostics window", origin="recovery",
            sticky=True, root=root,
        )
        return True, (
            "Safe Mode is on until you turn it off. The next start has no 3D, no microphone, "
            "no remote providers and no desktop actions."
        )
    if action_id == "normal-mode":
        clear_safe_mode(root)
        return True, "Safe Mode is off. The next start is a normal one."
    if action_id == "text-only":
        launcher = Path("/usr/libexec/bunny-companion-window")
        program = str(launcher) if launcher.exists() else sys.executable
        arguments = (
            [program, "--text-only"] if launcher.exists()
            else [program, "-m", "companion.cli", "companion", "shell", "--text-only"]
        )
        try:
            subprocess.Popen(  # noqa: S603 - a fixed program with fixed arguments
                arguments, env=dict(os.environ),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, f"the text-only window could not be started: {error}"
        return True, "A text-only Bunny window is starting."
    if action_id == "export":
        destination = default_destination(root)
        try:
            written = export_diagnostics(destination, root=root)
        except OSError as error:
            return False, f"the diagnostics file could not be written: {error}"
        return True, (
            f"Diagnostics written to {written}. Nothing has been sent anywhere. "
            "Open it and read it before you share it."
        )
    return False, f"unknown action {action_id!r}"


def _reset_presentation(root: Path) -> int:
    """Remove presentation preference files, and nothing else.

    Named files rather than a directory sweep: a reset that removed whatever it
    found would eventually remove a task store somebody moved there.
    """
    removed = 0
    for name in ("presentation.json", "presentation-preferences.json", "renderer-state.json"):
        candidate = root / name
        try:
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def text_report(root: Path, *, as_json: bool = False) -> str:
    report = diagnose(root=root)
    if as_json:
        return json.dumps(report.to_json(), indent=2, sort_keys=True)
    safe = read_safe_mode(root)
    rows = ["Bunny Diagnostics", "=" * 17, ""]
    identity = report.identity or {}
    if identity.get("displayName"):
        rows.extend([str(identity["displayName"]), f"Build {identity.get('buildId', 'unknown')}", ""])
    rows.extend(report.lines())
    rows.extend(["", "What you can do:"])
    for action in RECOVERY_ACTIONS:
        rows.append(f"  {action.action_id:18} {action.label} — {action.effect}")
    if safe.enabled:
        rows.append(f"  {'normal-mode':18} Leave Safe Mode — the next start is a normal one.")
    rows.extend([
        "", "Run one with:  bunny-os companion recover-ui --do <action>",
        "Nothing here is uploaded. Diagnostics are written to a file you read first.",
    ])
    return "\n".join(rows)


def run_window(root: Path) -> int:  # pragma: no cover - requires a display
    """The GTK surface. Falls back to text when there is no toolkit or display."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk
    except (ImportError, ValueError) as error:
        print(text_report(root))
        print(f"\n(The graphical diagnostics window is unavailable: {error})", file=sys.stderr)
        return 0

    report = diagnose(root=root)
    safe = read_safe_mode(root)

    class Window(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title="Bunny Diagnostics")
            self.set_default_size(760, 620)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for side in ("top", "bottom", "start", "end"):
                getattr(outer, f"set_margin_{side}")(20)

            heading = Gtk.Label(label=report.summary, wrap=True, xalign=0.0)
            heading.add_css_class("title-2")
            heading.set_selectable(True)
            outer.append(heading)

            identity = report.identity or {}
            if identity.get("displayName"):
                subtitle = Gtk.Label(
                    label=f"{identity['displayName']} — build {identity.get('buildId', 'unknown')}",
                    xalign=0.0, wrap=True, selectable=True,
                )
                subtitle.add_css_class("dim-label")
                outer.append(subtitle)

            scroller = Gtk.ScrolledWindow(vexpand=True)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            for section in report.sections:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                title = Gtk.Label(
                    label=f"{'✓' if section.ok else '✗'}  {section.title}",
                    xalign=0.0, selectable=True,
                )
                # The tick is decoration; the word is the information. §26: no
                # essential information in a glyph alone, so the state is spelled
                # out for anything that reads the label rather than the glyph.
                verdict = "working" if section.ok else "not working"
                title.set_tooltip_text(verdict)
                try:
                    title.update_property(
                        [Gtk.AccessibleProperty.LABEL], [f"{section.title}: {verdict}"],
                    )
                except (AttributeError, TypeError):
                    pass
                detail = Gtk.Label(label=section.detail, xalign=0.0, wrap=True, selectable=True)
                detail.add_css_class("dim-label")
                row.append(title)
                row.append(detail)
                body.append(row)
            if report.failures:
                body.append(Gtk.Label(label="Recent problems (paths and tokens removed):",
                                      xalign=0.0, selectable=True))
                for line in report.failures:
                    entry = Gtk.Label(label=line, xalign=0.0, wrap=True, selectable=True)
                    entry.add_css_class("dim-label")
                    body.append(entry)
            scroller.set_child(body)
            outer.append(scroller)

            self.status = Gtk.Label(label="", xalign=0.0, wrap=True, selectable=True)
            outer.append(self.status)

            actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8,
                                  row_spacing=8, max_children_per_line=3)
            available = list(RECOVERY_ACTIONS)
            if safe.enabled:
                from companion.support.diagnose import RecoveryAction

                available.append(RecoveryAction(
                    "normal-mode", "Leave Safe Mode",
                    "The next start is a normal one, with 3D, audio and desktop actions.",
                ))
            for action in available:
                button = Gtk.Button(label=action.label)
                button.set_tooltip_text(action.effect)
                button.connect("clicked", self.on_action, action.action_id)
                actions.append(button)
            outer.append(actions)
            self.set_child(outer)

        def on_action(self, _button, action_id):
            succeeded, message = perform(action_id, root=root)
            self.status.set_label(("" if succeeded else "Could not do that: ") + message)

    application = Gtk.Application(application_id="art.comrade.BunnyDiagnostics")
    application.connect("activate", lambda app: Window(app).present())
    return int(application.run(None))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunny-companion-recovery",
        description="Show what is wrong with Bunny, and fix the common causes.",
    )
    parser.add_argument("--text", action="store_true", help="print the report instead of opening a window")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--do", metavar="ACTION", default="", help="run one recovery action and exit")
    parser.add_argument("--root", type=Path, default=None, help="companion state directory")
    arguments = parser.parse_args(argv)
    root = arguments.root or companion_state_root()

    if arguments.do:
        succeeded, message = perform(arguments.do, root=root)
        print(message, file=sys.stdout if succeeded else sys.stderr)
        return 0 if succeeded else 2
    if arguments.json:
        print(text_report(root, as_json=True))
        return 0
    if arguments.text or not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        print(text_report(root))
        return 0
    return run_window(root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

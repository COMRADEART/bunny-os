# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The guest half of the pointer test: find the controls, then say what happened.

Imported by ``desktop-probe.py``, which is injected into a copy of the disk. It
is not shipped: a measuring instrument inside the artifact would be part of what
it measures.

## Finding a control

The host has to click a dock tile, and it needs the tile's position on screen.
Three ways were available and two are unsound.

Computing it from ``lib/layout.js`` gives the dock's rectangle but not the
tiles inside it, which St's box layout places from stylesheet padding and the
icons' natural sizes; reproducing that arithmetic here would be a second
implementation of a layout, wrong in a different way from the first.

Asking the shell over D-Bus is not possible: ``org.gnome.Shell.Eval`` is refused
outside unsafe mode, and ``org.gnome.Shell.Introspect`` has an allowlist this
probe is not on.

So: AT-SPI. Every dock tile is already an accessible object with a role and a
name, because ``makeActivatable`` gives it both — and ``AtspiComponent`` reports
extents in screen coordinates, which is exactly the question. It is also
independent of the desktop's own arithmetic in a way the first option is not:
the extents come from Clutter's actual allocation of the actor, not from what
the layout solver intended. If the tile is drawn somewhere other than where the
solver put it, this finds where it *is*.

The side effect is that this only works if the control is exposed to assistive
technology at all — which for a desktop that ships a screen reader is a property
worth failing on.

## Saying what happened

Four independent signals, recorded separately and never merged:

  * the systemd user scope, which is how GNOME Shell starts an application. A
    scope named ``app-gnome-org.gnome.Nautilus-*.scope`` exists only if
    ``Shell.App.activate`` ran — not if a shell command started the process.
  * the process table.
  * the window, through AT-SPI: a frame with a name, belonging to that
    application.
  * the session bus name the application owns.

They are recorded as four fields because they answer four different questions,
and a harness that reduced them to one boolean would hide the interesting case
where a process exists and no window ever appeared.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

#: The control channel, as the guest sees it. The host end is a Unix socket
#: QEMU listens on; see vm-desktop-story.sh.
CONTROL_PORT = Path("/dev/virtio-ports/org.bunny-os.control")


def _run(argv: list[str], *, user: str | None = None, timeout: int = 30,
         limit: int = 8000) -> dict:
    """Run a command and record what happened, including when it did not run.

    `limit` truncates the captured output, because most of these are
    `systemctl list-units` and a record full of them is unreadable. It is a
    parameter and not a constant because the accessibility tree is one of these
    calls and is far larger than any cap that suits the others: the first run of
    this harness reported "the guest exposes 0 named controls" on a session
    whose tree was returned correctly and then cut off at 8000 characters, so
    `json.loads` failed and every target came back missing. Nothing was wrong
    with the desktop and nothing was wrong with AT-SPI.
    """
    if user:
        argv = ["/usr/bin/sudo", "-u", user, "-H", *argv]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "ran": False, "error": str(exc)}
    return {
        "argv": argv,
        "ran": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[:limit],
        "stderr": completed.stderr.strip()[:2000],
    }


# --------------------------------------------------------------------------
# The AT-SPI half, which has to run inside the user's session.
#
# The probe is a root oneshot; AT-SPI clients talk to a per-session accessibility
# bus that only the session user can reach. So the code below is *text*, handed
# to a python3 running as that user with the session bus in its environment.
# Written as a here-document rather than a file so there is one place to read it
# and nothing to keep in step.
# --------------------------------------------------------------------------

_ATSPI_PROGRAM = r'''
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()

def describe(node, depth=0, limit=4):
    """A node, its role, name and screen extents."""
    try:
        component = node.get_component_iface()
        extents = component.get_extents(Atspi.CoordType.SCREEN) if component else None
    except Exception:
        extents = None
    entry = {
        "name": node.get_name() or "",
        "role": node.get_role_name(),
        "extents": None if extents is None else {
            "x": extents.x, "y": extents.y,
            "width": extents.width, "height": extents.height,
        },
    }
    return entry

def walk(node, depth, out, maximum_depth):
    if depth > maximum_depth:
        return
    try:
        count = node.get_child_count()
    except Exception:
        return
    for index in range(count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is None:
            continue
        out.append(describe(child))
        walk(child, depth + 1, out, maximum_depth)

mode = sys.argv[1]
desktop = Atspi.get_desktop(0)

if mode == "applications":
    applications = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if application is None:
            continue
        frames = []
        for child_index in range(application.get_child_count()):
            frame = application.get_child_at_index(child_index)
            if frame is None:
                continue
            entry = describe(frame)
            try:
                state = frame.get_state_set()
                entry["showing"] = state.contains(Atspi.StateType.SHOWING)
                entry["visible"] = state.contains(Atspi.StateType.VISIBLE)
                entry["active"] = state.contains(Atspi.StateType.ACTIVE)
            except Exception:
                pass
            frames.append(entry)
        applications.append({"name": application.get_name() or "", "frames": frames})
    print(json.dumps({"applications": applications}))

elif mode == "controls":
    # Everything named, under the application called gnome-shell. The desktop's
    # controls are all inside the compositor process, so that is where the dock
    # tiles are; nothing else in the tree is searched.
    found = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if application is None:
            continue
        if (application.get_name() or "") not in ("gnome-shell", "GNOME Shell", "mutter"):
            continue
        walk(application, 0, found, 12)
    print(json.dumps({"controls": [entry for entry in found if entry["name"]]}))
'''


def _atspi(user: str, environment: list[str], mode: str) -> dict:
    """Run the AT-SPI program as the session user and parse what it prints."""
    if not environment:
        return {"ran": False, "error": "no user session environment"}
    result = _run(
        ["/usr/bin/env", *environment, "/usr/bin/python3", "-c", _ATSPI_PROGRAM, mode],
        user=user, timeout=120, limit=4_000_000)
    if result.get("returncode") != 0:
        return {"ran": True, "ok": False, "call": result}
    try:
        parsed = json.loads(result.get("stdout", "{}"))
    except json.JSONDecodeError as exc:
        return {"ran": True, "ok": False, "error": str(exc), "call": result}
    # The whole tree is megabytes and is not worth carrying into the record; the
    # parsed result is what every caller uses, and the call is kept only for the
    # failure paths above.
    result.pop("stdout", None)
    return {"ran": True, "ok": True, "call": result, **parsed}


def enable_accessibility(user: str, environment: list[str]) -> dict:
    """Ask the session to expose its widget tree, and give it a moment.

    Two mechanisms, because they are not the same one and either can be the
    reason the tree is empty. `toolkit-accessibility` is the GSettings key
    toolkits read; `org.a11y.Status.IsEnabled` is the live property they watch,
    and connecting to the accessibility bus at all is what activates it. Setting
    the key and then connecting covers a session that reads it once at startup
    and one that watches it, without depending on which this Shell does.

    Recorded rather than assumed: if the tree comes back empty, the first thing
    anyone will want to know is whether this step worked.
    """
    setting = _run(["/usr/bin/env", *environment, "/usr/bin/gsettings", "set",
                    "org.gnome.desktop.interface", "toolkit-accessibility", "true"],
                   user=user) if environment else {"ran": False}
    # The bridge is not instant: the toolkit has to notice, register every actor
    # it already built, and answer. Five seconds is generous on llvmpipe and is
    # paid once per run.
    time.sleep(5)
    return {"gsettings": setting}


def locate_controls(user: str, environment: list[str]) -> dict:
    """Every named control the shell exposes, with its screen rectangle."""
    return _atspi(user, environment, "controls")


def windows(user: str, environment: list[str]) -> dict:
    """Every application on the accessibility bus, and its frames."""
    return _atspi(user, environment, "applications")


def find_control(controls: dict, name: str) -> dict | None:
    """The smallest control whose accessible name matches, with real extents.

    Smallest, because accessible names repeat up a container chain: the dock
    tile is called "Files" and so, in some themes, is the box around it. The
    tile is the one to press, and it is the smaller of the two. A control with
    no extents, or with zero area, is not a thing on screen and is skipped —
    that is what an actor that was built and never allocated looks like.
    """
    candidates = []
    for entry in controls.get("controls", []):
        if entry.get("name", "").strip().lower() != name.strip().lower():
            continue
        extents = entry.get("extents")
        if not extents or extents["width"] <= 0 or extents["height"] <= 0:
            continue
        candidates.append(entry)
    if not candidates:
        return None
    return min(candidates, key=lambda entry:
               entry["extents"]["width"] * entry["extents"]["height"])


# --------------------------------------------------------------------------
# What happened after a click
# --------------------------------------------------------------------------

#: Logical name → (systemd scope fragment, process pattern, AT-SPI application
#: names, session bus name). Every field is matched independently.
APPLICATIONS = {
    "files": {
        "scope": "org.gnome.Nautilus",
        "process": "nautilus",
        "atspi": ("Files", "org.gnome.Nautilus", "nautilus"),
        "bus": "org.gnome.Nautilus",
    },
    "terminal": {
        "scope": "org.gnome.Terminal",
        "process": "gnome-terminal-server",
        "atspi": ("Terminal", "gnome-terminal-server", "org.gnome.Terminal"),
        "bus": "org.gnome.Terminal",
    },
}


def application_state(name: str, user: str, environment: list[str]) -> dict:
    """The four independent signals for one application."""
    definition = APPLICATIONS[name]

    scopes = _run(["/usr/bin/systemctl", "--user", "list-units", "--all",
                   "--no-legend", "--plain", "--type=scope"], user=user)
    scope_lines = [line for line in scopes.get("stdout", "").splitlines()
                   if definition["scope"] in line]

    processes = _run(["/usr/bin/pgrep", "-a", "-u", user, "-f", definition["process"]])
    process_lines = [line for line in processes.get("stdout", "").splitlines() if line.strip()]

    names = _run(["/usr/bin/env", *environment, "/usr/bin/busctl", "--user",
                  "list", "--no-legend", "--no-pager"], user=user) if environment else {}
    owns_bus_name = any(line.split()[0] == definition["bus"]
                        for line in names.get("stdout", "").splitlines() if line.split())

    tree = windows(user, environment)
    frames = []
    for application in tree.get("applications", []):
        if application.get("name", "") in definition["atspi"]:
            frames.extend(application.get("frames", []))

    return {
        "scope": {"present": bool(scope_lines), "units": scope_lines},
        "process": {"present": bool(process_lines), "processes": process_lines[:6]},
        "busName": {"owned": owns_bus_name, "name": definition["bus"]},
        "windows": {"count": len(frames), "frames": frames},
        # Every field above is a separate measurement; this is the only derived
        # value in the record and it says exactly what it is derived from.
        "launched": bool(scope_lines) and bool(process_lines),
        "windowVisible": any(frame.get("showing") for frame in frames),
    }


def shell_alive(user: str, environment: list[str]) -> dict:
    """Is GNOME Shell still answering, and is the Bunny extension still enabled?

    Asked after every step of the interaction. "The shell survived opening
    Files" is not something a screenshot can establish — a compositor that has
    thrown inside an event handler keeps compositing.
    """
    if not environment:
        return {"responded": False, "error": "no user session environment"}
    call = _run(["/usr/bin/env", *environment, "/usr/bin/gdbus", "call", "--session",
                 "--dest", "org.gnome.Shell", "--object-path", "/org/gnome/Shell",
                 "--method", "org.gnome.Shell.Extensions.GetExtensionInfo",
                 '"bunny-shell@bunny-os.org"'], user=user, timeout=25)
    text = call.get("stdout", "")
    state = None
    if "'state':" in text:
        fragment = text.split("'state':", 1)[1]
        digits = "".join(character for character in fragment[:20]
                         if character.isdigit() or character == ".")
        if digits:
            state = int(float(digits))
    return {
        "responded": call.get("returncode") == 0,
        "extensionState": state,
        "extensionEnabled": state == 1,
        "call": call,
    }


# --------------------------------------------------------------------------
# The control channel
# --------------------------------------------------------------------------

class ControlChannel:
    """Line-delimited JSON over a virtio-serial port.

    The host drives the interaction and the guest observes it, and neither can
    do the other's job: the host cannot see a systemd scope and the guest cannot
    inject a pointer event. So they take turns, and this is the turn-taking.

    A fixed schedule was the alternative — the host clicks at t=200s, the guest
    samples at t=210s — and it fails in the way that matters most: on a slow
    boot the click lands before the desktop is up and the run reports that
    pressing Files did nothing.
    """

    def __init__(self, path: Path = CONTROL_PORT) -> None:
        self.path = path
        self._handle = None
        self.available = False
        self.error = None
        try:
            # Unbuffered binary, opened read-write: a virtio port is one file
            # for both directions, and opening it twice gets EBUSY.
            self._handle = os.fdopen(os.open(str(path), os.O_RDWR), "r+b", buffering=0)
            self.available = True
        except OSError as exc:
            self.error = str(exc)

    def send(self, document: dict) -> None:
        if not self.available:
            return
        self._handle.write((json.dumps(document) + "\n").encode("utf-8"))
        self._handle.flush()

    def receive(self, timeout: float = 600.0) -> dict | None:
        """One request from the host, or None when the deadline passes."""
        if not self.available:
            return None
        deadline = time.monotonic() + timeout
        buffer = b""
        while time.monotonic() < deadline:
            try:
                chunk = self._handle.read(4096)
            except OSError:
                return None
            if not chunk:
                # No writer attached yet, or none right now. A virtio port reads
                # empty rather than blocking, so this is a poll and not a spin.
                time.sleep(0.25)
                continue
            buffer += chunk
            if b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                try:
                    return json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
        return None

    def close(self) -> None:
        try:
            if self._handle is not None:
                self._handle.close()
        except OSError:
            pass

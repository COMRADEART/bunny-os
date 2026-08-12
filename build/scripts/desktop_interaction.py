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
import re
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

def describe(node, ancestors=()):
    """A node, its role, name, screen extents and where it sits in the tree."""
    try:
        component = node.get_component_iface()
        extents = component.get_extents(Atspi.CoordType.SCREEN) if component else None
    except Exception:
        extents = None
    try:
        description = node.get_description() or ""
    except Exception:
        description = ""
    entry = {
        "name": node.get_name() or "",
        "role": node.get_role_name(),
        # The desktop puts the character's state and the assistant's answer in
        # accessible descriptions and names, for a screen reader. Carrying them
        # here is what lets the harness watch the state machine from outside
        # the process without the product growing a test hook.
        "description": description,
        # The named ancestors, outermost first. Two different controls are
        # called "Files" — the sidebar row and the dock tile — and nothing about
        # either one distinguishes them except where they are.
        "path": list(ancestors),
        "extents": None if extents is None else {
            "x": extents.x, "y": extents.y,
            "width": extents.width, "height": extents.height,
        },
    }
    return entry

def walk(node, depth, out, maximum_depth, ancestors=()):
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
        entry = describe(child, ancestors)
        out.append(entry)
        name = entry["name"]
        walk(child, depth + 1, out, maximum_depth,
             ancestors + (name,) if name else ancestors)

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
        # Twelve. Raised to twenty once, on the theory that the Trust approval
        # box sat deeper than the walk reached — and the run that followed
        # returned *no controls at all*, because a deeper walk over this tree
        # does not finish inside the call's timeout. The theory was wrong and
        # the change made the instrument worse, so it is back.
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


def keep_the_session_awake(user: str, environment: list[str]) -> dict:
    """Stop the guest locking its own screen in the middle of the test.

    Measured, not anticipated. A run that waited seven minutes before looking at
    the desktop found the Bunny extension DISABLED and the accessibility tree
    empty, on a session that had been correct four minutes earlier. Nothing had
    failed: GNOME had idled, locked, and switched to the `unlock-dialog` session
    mode, which disables every extension that does not declare that mode — and
    the Bunny desktop deliberately does not, because a dashboard drawing behind
    a lock screen would show a locked machine's calendar and notifications to
    whoever is standing in front of it.

    So this is a property of the *machine under test*, not of the product, and
    it is turned off here rather than worked around by making the harness
    faster. A test that only passes when it finishes inside five minutes is a
    test that will fail the first time a build is slow.
    """
    if not environment:
        return {"ran": False, "error": "no user session environment"}
    settings = [
        ("org.gnome.desktop.session", "idle-delay", "0"),
        ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
        ("org.gnome.desktop.screensaver", "idle-activation-enabled", "false"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'"),
    ]
    applied = []
    for schema, key, value in settings:
        applied.append({
            "key": f"{schema} {key}",
            "call": _run(["/usr/bin/env", *environment, "/usr/bin/gsettings",
                          "set", schema, key, value], user=user, limit=400),
        })
    return {"ran": True, "settings": applied}


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


#: Roles that can be pressed. A label named "Files" is the text *inside* the
#: sidebar row, not the row; clicking it happens to work, because Clutter picks
#: the reactive ancestor, but recording it as the control that was pressed
#: misreports what the test did.
ACTIVATABLE_ROLES = ("push button", "button", "toggle button", "menu item", "list item")


def find_control(controls: dict, name: str, *, within: str | None = None) -> dict | None:
    """The control to press, by accessible name and optionally by container.

    Two things in this desktop are called "Files" — the sidebar row and the dock
    tile — and the acceptance criterion names the dock. `within` is matched
    against the control's ancestor names, which is why the tree walk records
    them: nothing about the two controls differs except where they are.

    A pressable role is preferred over any other, and among equals the smallest,
    because an accessible name propagates up a container chain and the innermost
    match is the control rather than the box around it. A control with no
    extents, or with zero area, is skipped: that is what an actor that was built
    and never allocated looks like, and pressing its centre would press the
    top-left corner of the screen.
    """
    candidates = []
    for entry in controls.get("controls", []):
        if entry.get("name", "").strip().lower() != name.strip().lower():
            continue
        extents = entry.get("extents")
        if not extents or extents["width"] <= 0 or extents["height"] <= 0:
            continue
        if within is not None and not any(
                within.lower() in ancestor.lower() for ancestor in entry.get("path", [])):
            continue
        candidates.append(entry)
    if not candidates:
        return None
    pressable = [entry for entry in candidates
                 if entry.get("role") in ACTIVATABLE_ROLES]
    return min(pressable or candidates,
               key=lambda entry: entry["extents"]["width"] * entry["extents"]["height"])


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
        # An alternation, because a terminal is two processes and which one is
        # running depends on how it was started. GNOME Shell launches
        # `gnome-terminal`, the client — systemd names the scope
        # `app-gnome-org.gnome.Terminal-<pid>.scope`, "Application launched by
        # gnome-shell" — and that client D-Bus-activates
        # `gnome-terminal-server`, which owns the window. Matching only the
        # server reported `process: absent` on a run where the unit, the window
        # and a file typed into that window were all present.
        "process": "gnome-terminal|gnome-console|kgx",
        "atspi": ("Terminal", "gnome-terminal-server", "org.gnome.Terminal",
                  "Console", "kgx"),
        "bus": "org.gnome.Terminal",
    },
}


def application_state(name: str, user: str, environment: list[str]) -> dict:
    """The four independent signals for one application."""
    definition = APPLICATIONS[name]

    # Every unit, not just scopes.
    #
    # The first version filtered `--type=scope`, on the belief that GNOME Shell
    # starts an application in a transient scope. It does not, or not only:
    # GNOME 50 starts it as `app-<desktop-id>@<token>.service`, and a terminal
    # additionally gets a `vte-spawn-*.scope` for the shell it runs. Filtering
    # to scopes therefore reported "not launched" for a Nautilus window that was
    # open on screen at the time — which is the harness lying about the product
    # in the safest-looking direction.
    units = _run(["/usr/bin/systemctl", "--user", "list-units", "--all",
                  "--no-legend", "--plain"], user=user, limit=60_000)
    unit_lines = [line.strip() for line in units.get("stdout", "").splitlines()
                  if definition["scope"] in line or definition["process"] in line]

    processes = _run(["/usr/bin/pgrep", "-a", "-u", user, "-f", definition["process"]])
    process_lines = [line for line in processes.get("stdout", "").splitlines() if line.strip()]

    names = _run(["/usr/bin/env", *environment, "/usr/bin/busctl", "--user",
                  "list", "--no-legend", "--no-pager"], user=user,
                 limit=60_000) if environment else {}
    owns_bus_name = any(line.split()[0] == definition["bus"]
                        for line in names.get("stdout", "").splitlines() if line.split())

    tree = windows(user, environment)
    frames = []
    for application in tree.get("applications", []):
        if application.get("name", "") in definition["atspi"]:
            frames.extend(application.get("frames", []))

    return {
        # Each of these is a separate measurement of a different thing, kept
        # apart on purpose: a process with no window, a window with no unit and
        # a unit with no process are three different failures and a single
        # boolean would hide all of them.
        "unit": {"present": bool(unit_lines), "units": unit_lines[:8]},
        "process": {"present": bool(process_lines), "processes": process_lines[:6]},
        "busName": {"owned": owns_bus_name, "name": definition["bus"]},
        "windows": {"count": len(frames), "frames": frames},
        # The two derived values, each naming exactly what it is derived from.
        "launched": bool(process_lines),
        "startedByTheShell": bool(unit_lines),
        "windowVisible": any(frame.get("showing") for frame in frames),
    }


def character_state(user: str, environment: list[str]) -> dict:
    """What the character is doing, and what the bubble is saying.

    Read out of the accessibility tree rather than out of the desktop's own
    logs, and that is the whole point: the shell sets the character's accessible
    description to ``Bunny is <state>. <reason>`` on every transition and the
    bubble's accessible name to ``Bunny says: <text>``, both for a screen
    reader. A harness reading the same two strings is seeing exactly what an
    assistive technology sees, which is a much stronger claim than reading a
    journal line the desktop wrote about itself.

    So the state machine and the response are observable from outside the
    process, with no test hook in the product.
    """
    controls = locate_controls(user, environment)
    state = ""
    reason = ""
    says = ""
    for entry in controls.get("controls", []):
        name = str(entry.get("name", ""))
        # The state is in the *name*, after an em dash. It was in the
        # accessible description for two releases and no assistive technology
        # ever saw it: St has no accessible-description, so the assignment
        # created a JavaScript property and nothing more. Every control in the
        # tree reported an empty description, which is how that was found.
        if name.startswith("Bunny, your assistant"):
            _, _, body = name.partition("—")
            body = body.strip()
            if body:
                state, _, reason = body.partition(". ")
                state = state.strip().rstrip(".")
        elif name.startswith("Bunny says: "):
            says = name[len("Bunny says: "):]
    return {"state": state, "reason": reason, "says": says,
            "controlCount": len(controls.get("controls", []))}


def ask_through_the_bridge(request: str, user: str, environment: list[str]) -> dict:
    """Submit a request through the exact program the desktop spawns.

    `/usr/bin/bunny-shell-assistant` is what `AssistantService` runs; this runs
    it the same way, as the same user, against the same socket, and parses the
    same newline-delimited events. What it proves is everything from the shell's
    process boundary inwards: the protocol, the runtime, executor selection,
    planning, the approval derivation, the tool allowlist, the desktop broker
    and the adapter that opens the application.

    What it does not prove is the GJS half — a keystroke reaching the entry
    widget and `_ask` being called. That is a separate claim and is reported
    separately, because collapsing the two would let a working backend stand in
    for a working interface.
    """
    if not environment:
        return {"ran": False, "error": "no user session environment"}
    result = _run(
        ["/usr/bin/env", *environment, "/usr/bin/bunny-shell-assistant", "ask", request],
        user=user, timeout=240, limit=60_000)
    events = []
    for line in result.get("stdout", "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    phases = [str(item.get("phase", "")) for item in events if item.get("event") == "phase"]
    replies = [str(item.get("text", "")) for item in events if item.get("event") == "reply"]
    errors = [str(item.get("reason", "")) for item in events if item.get("event") == "error"]
    finished = [str(item.get("phase", "")) for item in events if item.get("event") == "finished"]
    return {
        "ran": True,
        "request": request,
        "returncode": result.get("returncode"),
        "accepted": any(item.get("event") == "accepted" for item in events),
        "phases": phases,
        "reply": replies[-1] if replies else "",
        "errors": errors,
        "finishedPhase": finished[-1] if finished else "",
        "eventCount": len(events),
    }



#: The journey's fixture, written as the user by the user's own Python. A file
#: created by root in /var/home would be owned by root and unreadable to the
#: capsule's grant, which is a permission failure dressed as a security result.
_FIXTURE_PROGRAM = """
import sys
from pathlib import Path
kind = sys.argv[1]
pictures = Path.home() / "Pictures"
pictures.mkdir(parents=True, exist_ok=True)
source = pictures / "holiday.png"
neighbour = pictures / "private-neighbour.png"
for stale in list(pictures.glob("*-resized*.png")) + [source, neighbour]:
    if stale.exists():
        stale.unlink()
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
def png(path, width, height, colour):
    buf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    buf.fill(colour)
    buf.savev(str(path), "png", [], [])
# The neighbour first and stamped older, so "this" means holiday.png. Written
# after it once, and Bunny offered to resize the file the slice exists to prove
# is never touched.
png(neighbour, 32, 32, 0xFF0000FF)
import os
os.utime(neighbour, (1000000, 1000000))
if kind == "corrupt":
    source.write_bytes(b"not a png, and deliberately so" * 8)
else:
    png(source, 400, 200, 0x3366CCFF)
import hashlib, json
print(json.dumps({
    "source": str(source),
    "kind": kind,
    "sourceDigest": hashlib.sha256(source.read_bytes()).hexdigest()[:32],
    "neighbourDigest": hashlib.sha256(neighbour.read_bytes()).hexdigest()[:32],
}))
"""

#: What the journey produced, read back as the user.
_RESULT_PROGRAM = """
import hashlib, json
from pathlib import Path
pictures = Path.home() / "Pictures"
source = pictures / "holiday.png"
neighbour = pictures / "private-neighbour.png"
produced = sorted(item.name for item in pictures.glob("*-resized*.png"))
pixels = None
if produced:
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        buf = GdkPixbuf.Pixbuf.new_from_file(str(pictures / produced[0]))
        pixels = [buf.get_width(), buf.get_height()]
    except Exception:
        pixels = None
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32] if path.is_file() else ""
print(json.dumps({
    "files": produced,
    "pixels": pixels,
    "sourceDigest": digest(source),
    "neighbourDigest": digest(neighbour),
}))
"""


def _as_user_python(program: str, arguments: list[str], user: str,
                    environment: list[str]) -> dict:
    # `_run` returns a record, not a tuple. Unpacking it as three values raised
    # inside the probe's command loop, which killed the probe and turned every
    # answer after it into `null` — a broken harness reading exactly like a
    # broken desktop.
    outcome = _run(
        ["/usr/bin/env", *environment, "/usr/bin/python3", "-c", program, *arguments],
        user=user, timeout=60,
    )
    if not outcome.get("ran"):
        return {"ok": False, "error": str(outcome.get("error"))[:300]}
    out = str(outcome.get("stdout", ""))
    if outcome.get("returncode") != 0:
        return {"ok": False,
                "error": (str(outcome.get("stderr", "")) or out)[-300:]}
    try:
        return {"ok": True, **json.loads(out.strip().splitlines()[-1])}
    except (ValueError, IndexError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}", "raw": out[-200:]}


def make_image_fixture(kind: str, user: str, environment: list[str]) -> dict:
    """Put the journey's images in the user's Pictures folder."""
    return _as_user_python(_FIXTURE_PROGRAM, [kind], user, environment)


def journey_result(user: str, environment: list[str]) -> dict:
    """What is in Pictures now, and whether the originals moved."""
    return _as_user_python(_RESULT_PROGRAM, [], user, environment)


# --------------------------------------------------------------------------
# Accessibility, asked of the running session
#
# Not "is the setting set". A settings echo proves the key exists, which nobody
# doubted. Each measurement below is a property of what a person using assistive
# technology would actually meet:
#
#   names       an unnamed button is unreadable to a screen reader, whatever it
#               looks like. Counted by role, and the unnamed ones are listed so
#               they can be fixed rather than totalled.
#   keyboard    FOCUSABLE on the Trust prompt's buttons. A permission dialog
#               that can only be answered with a pointer is a security surface
#               that excludes people, and no amount of contrast fixes it.
#   actions     the AT-SPI Action interface. A focusable button with no action
#               can be reached and not pressed.
#   motion      enable-animations and a11y reduced-motion, set and read back,
#               *and* the consequence checked — see below.
#   text        text-scaling-factor, with the prompt's own height measured
#               before and after, because the setting changing is not the text
#               changing.
#
# The motion and text checks each carry their own negative control: the value is
# read at the default first, so "it is 0 because reduced motion is on" cannot be
# confused with "it is 0 because nothing reports it".
# --------------------------------------------------------------------------

_A11Y_PROGRAM = r'''
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()

INTERACTIVE = {
    "push button", "button", "toggle button", "check box", "radio button",
    "menu item", "list item", "entry", "text", "combo box", "slider", "link",
}

def states(node):
    try:
        state = node.get_state_set()
    except Exception:
        return {}
    out = {}
    for name in ("FOCUSABLE", "FOCUSED", "SENSITIVE", "SHOWING", "VISIBLE", "ENABLED"):
        try:
            out[name.lower()] = state.contains(getattr(Atspi.StateType, name))
        except Exception:
            out[name.lower()] = None
    return out

def actions(node):
    try:
        iface = node.get_action_iface()
        if iface is None:
            return []
        return [Atspi.Action.get_action_name(iface, i)
                for i in range(Atspi.Action.get_n_actions(iface))]
    except Exception:
        return []

def extents(node):
    try:
        component = node.get_component_iface()
        if component is None:
            return None
        box = component.get_extents(Atspi.CoordType.SCREEN)
        return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
    except Exception:
        return None

rows = []

def walk(node, depth, maximum, ancestors=()):
    if depth > maximum:
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
        try:
            role = child.get_role_name()
            name = child.get_name() or ""
            description = child.get_description() or ""
        except Exception:
            continue
        entry = {"role": role, "name": name, "description": description,
                 "path": list(ancestors)}
        if role in INTERACTIVE:
            entry["states"] = states(child)
            entry["actions"] = actions(child)
            entry["extents"] = extents(child)
        rows.append(entry)
        walk(child, depth + 1, maximum, ancestors + (name,) if name else ancestors)

desktop = Atspi.get_desktop(0)
for index in range(desktop.get_child_count()):
    application = desktop.get_child_at_index(index)
    if application is None:
        continue
    if (application.get_name() or "") not in ("gnome-shell", "GNOME Shell", "mutter"):
        continue
    # Twelve, for the reason recorded above _ATSPI_PROGRAM: a deeper walk over
    # this tree does not finish inside the call's timeout.
    walk(application, 0, 12)

interactive = [r for r in rows if r["role"] in INTERACTIVE]

# "Unnamed interactive controls" was one number and had to be two.
#
# The first run of this measurement reported forty, which read as forty
# accessibility defects. Thirty-nine of them were role `text`: the ClutterText
# inside every St.Label, which AT-SPI exposes as a child of the label that
# already carries the name. A screen reader reads the label. Naming the inner
# node as well would make Orca say everything twice, which is one of the three
# failures §31 names — so "fixing" all forty would have made the desktop worse.
#
# The fortieth was a real unnamed button, and it was invisible in the count it
# was hiding in.
unnamed_all = [{"role": r["role"], "path": r["path"]} for r in interactive if not r["name"]]
unnamed_controls = [r for r in unnamed_all if r["role"] != "text"]
unnamed_text = [r for r in unnamed_all if r["role"] == "text"]
unnamed = unnamed_controls

# The Trust prompt, by the names the shell gives its two buttons. Looked up by
# name rather than by position: the point of the check is that the name exists.
trust = {}
for r in interactive:
    if r["name"] in ("Allow this Bunny action", "Deny this Bunny action"):
        trust[r["name"]] = {
            "role": r["role"],
            "states": r.get("states", {}),
            "actions": r.get("actions", []),
            "extents": r.get("extents"),
            "description": r["description"],
        }

by_role = {}
for r in interactive:
    slot = by_role.setdefault(r["role"], {"total": 0, "named": 0})
    slot["total"] += 1
    if r["name"]:
        slot["named"] += 1

# A named sample with its screen rectangle, so the same control can be measured
# before and after a text-scaling change. A preference that is stored and not
# drawn leaves these heights identical, and that is the difference between the
# desktop honouring a setting and merely remembering it.
sample = {}
for r in interactive:
    box = r.get("extents")
    if r["name"] and box and box.get("height"):
        sample.setdefault(r["name"], {"role": r["role"],
                                      "height": box["height"], "width": box["width"]})

print(json.dumps({
    "nodes": len(rows),
    "interactive": len(interactive),
    "named": len(interactive) - len(unnamed_all),
    "unnamed": unnamed[:40],
    # Split, because the two mean different things: a control with no name is a
    # defect, and a label's inner text node with no name is how AT-SPI models a
    # label.
    "unnamedControls": len(unnamed_controls),
    "unnamedTextNodes": len(unnamed_text),
    "byRole": by_role,
    "trustPrompt": trust,
    "sample": dict(sorted(sample.items())[:60]),
    "focusable": sum(1 for r in interactive if (r.get("states") or {}).get("focusable")),
    "withActions": sum(1 for r in interactive if r.get("actions")),
}))
'''


#: The settings an accessibility run reads and writes, as (schema, key).
_A11Y_SETTINGS = (
    ("org.gnome.desktop.interface", "enable-animations"),
    ("org.gnome.desktop.interface", "text-scaling-factor"),
    ("org.gnome.desktop.interface", "toolkit-accessibility"),
    ("org.gnome.desktop.a11y.interface", "high-contrast"),
    ("org.gnome.desktop.a11y.interface", "reduced-motion"),
    ("org.gnome.desktop.a11y.interface", "show-status-shapes"),
    ("org.gnome.desktop.a11y.applications", "screen-reader-enabled"),
)


def read_a11y_settings(user: str, environment: list[str]) -> dict:
    """Every accessibility key this desktop claims to honour, as it stands."""
    values: dict = {}
    for schema, key in _A11Y_SETTINGS:
        outcome = _run(["/usr/bin/env", *environment, "/usr/bin/gsettings",
                        "get", schema, key], user=user, timeout=20)
        values[f"{schema}.{key}"] = (
            str(outcome.get("stdout", "")).strip()
            if outcome.get("returncode") == 0 else None
        )
    return values


def set_a11y_setting(schema: str, key: str, value: str,
                     user: str, environment: list[str]) -> dict:
    """Set one key and read it straight back, because `set` can succeed and not take."""
    written = _run(["/usr/bin/env", *environment, "/usr/bin/gsettings",
                    "set", schema, key, value], user=user, timeout=20)
    read = _run(["/usr/bin/env", *environment, "/usr/bin/gsettings",
                 "get", schema, key], user=user, timeout=20)
    return {
        "wrote": written.get("returncode") == 0,
        "error": str(written.get("stderr", ""))[:200] or None,
        "readBack": str(read.get("stdout", "")).strip(),
    }


def accessibility_tree(user: str, environment: list[str]) -> dict:
    """Names, roles, focusability and actions for every interactive control."""
    if not environment:
        return {"ok": False, "error": "no user session environment"}
    outcome = _run(
        ["/usr/bin/env", *environment, "/usr/bin/python3", "-c", _A11Y_PROGRAM],
        user=user, timeout=180, limit=4_000_000)
    if not outcome.get("ran"):
        return {"ok": False, "error": str(outcome.get("error"))[:300]}
    if outcome.get("returncode") != 0:
        return {"ok": False, "error": str(outcome.get("stderr", ""))[-300:]}
    try:
        return {"ok": True, **json.loads(str(outcome.get("stdout", "")).strip().splitlines()[-1])}
    except (ValueError, IndexError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


_TASK_TRACE_PROGRAM = r'''
"""The runtime's own account of the last task, asked of the runtime.

A phase is a projection of an event stream. "Thinking…" for ever means the
stream stopped, and the only useful question is which event was last written —
which is a question the runtime can answer and a screenshot cannot.
"""
import json, os, sys
sys.path.insert(0, "/usr/lib/bunny-os/python")
from companion.protocol import CompanionClient

socket_path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "bunny-companion", "runtime.sock")
client = CompanionClient(socket_path)
sessions = client.list_sessions().get("sessions", [])
out = {"sessions": len(sessions), "tasks": []}
for session in sessions:
    listed = client.list_tasks(session["sessionId"]).get("tasks", [])
    for task in listed:
        task_id = task.get("taskId")
        events = client.get_events(task_id=task_id).get("events", [])
        state = client.get_presentation_state(task_id).get("state", {})
        out["tasks"].append({
            "taskId": task_id,
            "request": str(task.get("request", ""))[:80],
            "status": task.get("status"),
            "phase": state.get("phase"),
            "statusText": state.get("statusText"),
            "errorSummary": state.get("errorSummary"),
            "approvals": len(state.get("approvals") or []),
            "eventCount": len(events),
            "events": [{"seq": e.get("sequence"), "type": e.get("type"),
                        "summary": str(e.get("summary", ""))[:120]}
                       for e in events[-14:]],
        })
print(json.dumps(out))
'''


_APPROVAL_BUTTONS_PROGRAM = r'''
"""The Trust prompt's two buttons, found as fast as the tree allows.

`locate_controls` returns every named control in the shell, and over this
desktop that walk can take minutes. That is fine for an inventory and wrong for
a race: the prompt is on screen for as long as whatever clock is shortest allows,
and a walk that outlives the prompt reports an empty desktop and proves nothing.

So this looks for two names and stops the moment it has them. It is additive —
the full walk is still there and is still what the driver falls back to — because
the last time this instrument was "improved" in place, the change broke it and
the only reason anyone noticed was that the previous behaviour had been recorded.
"""
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()

WANTED = {"Allow this Bunny action", "Deny this Bunny action"}
found = {}
seen = 0

def extents(node):
    try:
        component = node.get_component_iface()
        if component is None:
            return None
        box = component.get_extents(Atspi.CoordType.SCREEN)
        return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
    except Exception:
        return None

def walk(node, depth, maximum, ancestors=()):
    global seen
    if depth > maximum or len(found) == len(WANTED):
        return
    try:
        count = node.get_child_count()
    except Exception:
        return
    for index in range(count):
        if len(found) == len(WANTED):
            return
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is None:
            continue
        try:
            name = child.get_name() or ""
            role = child.get_role_name()
        except Exception:
            continue
        seen += 1
        if name in WANTED and name not in found:
            found[name] = {"name": name, "role": role, "extents": extents(child),
                           "path": list(ancestors)}
        walk(child, depth + 1, maximum, ancestors + (name,) if name else ancestors)

desktop = Atspi.get_desktop(0)
for index in range(desktop.get_child_count()):
    application = desktop.get_child_at_index(index)
    if application is None:
        continue
    if (application.get_name() or "") not in ("gnome-shell", "GNOME Shell", "mutter"):
        continue
    walk(application, 0, 12)

print(json.dumps({"buttons": found, "nodesVisited": seen,
                  "complete": len(found) == len(WANTED)}))
'''


def approval_buttons(user: str, environment: list[str]) -> dict:
    """The Trust prompt's two buttons, or an honest report that they are absent."""
    if not environment:
        return {"ok": False, "error": "no user session environment"}
    outcome = _run(
        ["/usr/bin/env", *environment, "/usr/bin/python3", "-c", _APPROVAL_BUTTONS_PROGRAM],
        user=user, timeout=180, limit=1_000_000)
    if not outcome.get("ran"):
        return {"ok": False, "error": str(outcome.get("error"))[:300]}
    if outcome.get("returncode") != 0:
        return {"ok": False, "error": str(outcome.get("stderr", ""))[-300:]}
    try:
        return {"ok": True, **json.loads(str(outcome.get("stdout", "")).strip().splitlines()[-1])}
    except (ValueError, IndexError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def task_trace(user: str, environment: list[str]) -> dict:
    """Every task the runtime knows about, and the last events of each."""
    return _as_user_python(_TASK_TRACE_PROGRAM, [], user, environment)


_COMPANION_STATE_PROGRAM = r'''
"""What the Companion unit is doing, and what it last said."""
import json, subprocess

def run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return {"rc": done.returncode, "out": done.stdout[-4000:], "err": done.stderr[-800:]}
    except Exception as error:
        return {"rc": None, "error": f"{type(error).__name__}: {error}"}

print(json.dumps({
    "unit": run(["systemctl", "--user", "show", "bunny-companion.service",
                 "--property=ActiveState,SubState,NRestarts,ExecMainStatus,MainPID"]),
    "journal": run(["journalctl", "--user", "-u", "bunny-companion.service",
                    "-n", "60", "--no-pager", "-o", "cat"]),
    "capsuleUnits": run(["systemctl", "--user", "list-units", "bunny-capsule-*",
                         "--all", "--no-legend", "--no-pager"]),
    # The shell's own complaints. `AssistantService` logs "could not be started"
    # and "assistant unavailable" here, and those two sentences separate "the
    # runtime never heard the request" from "the runtime heard it and stopped".
    "shellLog": run(["journalctl", "--user", "--since", "-30m", "--no-pager", "-o", "cat",
                     "-g", "bunny|assistant|companion"]),
    # And whether the shipped bridge runs at all, as the shell would run it.
    "bridgeHealth": run(["/usr/bin/bunny-shell-assistant", "health"]),
}))
'''


def companion_state(user: str, environment: list[str]) -> dict:
    """The unit's state and its recent log, from inside the session."""
    return _as_user_python(_COMPANION_STATE_PROGRAM, [], user, environment)


def screen_reader(user: str, environment: list[str]) -> dict:
    """Whether the shipped screen reader is present and will start.

    Deliberately modest. Starting Orca and capturing what it speaks needs an
    audio path and a speech engine, and neither is qualified here. What this
    answers is the pair of questions that must be true before that is even worth
    attempting: is Orca in the image, and does it run far enough to report its
    own version rather than dying on an import.
    """
    present = _run(["/usr/bin/test", "-x", "/usr/bin/orca"], user=user, timeout=10)
    version = _run(["/usr/bin/env", *environment, "/usr/bin/orca", "--version"],
                   user=user, timeout=30) if environment else {"ran": False}
    return {
        "installed": present.get("returncode") == 0,
        "ranVersion": version.get("returncode") == 0,
        "version": str(version.get("stdout", "")).strip()[:120] or None,
        "error": str(version.get("stderr", ""))[:200] or None,
    }



#: Where Orca is asked to write its debug log inside the guest.
#:
#: Orca's `--debug-file` turns on a log that contains, among a great deal else,
#: one line per utterance in the form `SPEECH OUTPUT: 'the words'`. That is the
#: only place in the system where *what a screen reader actually said* exists as
#: text: the audio path is a speech engine and a sound card, and neither is
#: qualified on this guest. Reading the log is not a substitute for listening to
#: it — a wrong pronunciation or a stuck utterance would not show here — but it
#: answers §31's question, which is whether the right words are produced at all.
ORCA_DEBUG = "/tmp/bunny-orca-debug.txt"

#: Orca's own stdout and stderr. Empty on a healthy start; the reason on a
#: failed one — see start_screen_reader for why this exists.
ORCA_OUTPUT = "/tmp/bunny-orca-output.txt"

_ORCA_SPEECH = re.compile(r"SPEECH OUTPUT:\s*'(.*)'\s*$")

#: Where speech-dispatcher is told to write its log, and the line that carries
#: an utterance.
#:
#: `Incoming text: |…|` is the text a client submitted, logged at LogLevel 4.
#: The pattern is not a guess: the first version looked for "Text to say" and
#: three other plausible phrasings, matched none of a 1.3 MB log, and reported
#: zero utterances from a run where the daemon had clearly been busy. These are
#: the daemon's own format strings, read out of the binary with `strings` rather
#: than out of a twenty-five-minute guest run.
SPEECHD_LOG_DIR = "/tmp/bunny-speechd-log"
_SPEECHD_SPEECH = re.compile(r"Incoming text:\s*\|(.*)\|", re.M)
#: The same utterance again, after speechd has queued it. Kept as a fallback for
#: a build that logs one and not the other.
_SPEECHD_QUEUED = re.compile(r"Queueing message \|(.*)\| with priority", re.M)


def start_screen_reader(user: str, environment: list[str], wait: float = 25.0) -> dict:
    """Turn Orca on and wait for it to be speaking.

    Two steps, and the order matters. The gsetting is what a person would use
    and what the session watches, so it goes first; `orca --replace` then starts
    the process with debugging on. Starting Orca without the setting leaves a
    screen reader running that the session does not believe in, which is a state
    no user can reach and therefore not one worth measuring.
    """
    if not environment:
        return {"ran": False, "error": "no user session environment"}

    _run(["/usr/bin/env", *environment, "/usr/bin/gsettings", "set",
          "org.gnome.desktop.a11y.applications", "screen-reader-enabled", "true"],
         user=user, timeout=20)
    _run(["/usr/bin/rm", "-f", ORCA_DEBUG, ORCA_OUTPUT], user=user, timeout=10)

    # Point speech-dispatcher at the module that needs no sound card.
    #
    # The image configures `espeak-ng`, which wants an audio sink, and this
    # guest has none — a headless QEMU with no `-device` for sound. A speech
    # module that cannot open an output is a plausible reason for a screen
    # reader to start and then produce nothing, and it is not a reason worth
    # spending a twenty-five-minute run to distinguish from the others.
    #
    # `sd_dummy` ships in the image and discards the audio. What it does not
    # discard is the *utterance*: Orca still decides what to say and still logs
    # it, which is the only thing this measurement reads. So the record below
    # says what a screen reader would announce, on a machine that could not have
    # played it. §31's question is what is announced; a run that also proved it
    # was audible would need a sound device and a listener.
    config = "/var/home/bunny/.config/speech-dispatcher"
    _run(["/usr/bin/mkdir", "-p", config], user=user, timeout=10)
    _run(["/usr/bin/mkdir", "-p", SPEECHD_LOG_DIR], user=user, timeout=10)
    # LogLevel 4 and an explicit LogDir, because speech-dispatcher's own log is
    # the channel this measurement actually reads. See screen_reader_speech.
    _run(["/bin/sh", "-c",
          f'printf "AddModule \\"dummy\\" \\"sd_dummy\\" \\"\\"\\n'
          f'DefaultModule dummy\\nLogLevel 4\\nLogDir \\"{SPEECHD_LOG_DIR}\\"\\n" '
          f'> {config}/speechd.conf'],
         user=user, timeout=10)

    # Stop whatever screen reader is already running before starting ours.
    #
    # Setting `screen-reader-enabled` is itself enough to make the session start
    # Orca, so by the time this launches its own there may already be one — and
    # `orca --replace` then hands over to an instance nobody gave a debug file
    # to. Every previous run of this probe reported `running: true` from a
    # `pgrep` that could not tell the two apart, which is exactly how four runs
    # produced an empty log from a process that was genuinely alive.
    _run(["/usr/bin/pkill", "-TERM", "-x", "orca"], user=user, timeout=15)
    time.sleep(3)
    _run(["/usr/bin/pkill", "-KILL", "-x", "orca"], user=user, timeout=15)
    time.sleep(1)

    # Detached, and with its own output captured to a file.
    #
    # The first version of this ran `setsid --fork orca …` and reported
    # `started: true` because setsid's *parent* exited zero. Orca then wrote no
    # debug log and the record said `speaking: false` with `error: null` — an
    # instrument that had failed and could not say so, which is worse than one
    # that fails loudly. Whatever Orca prints now lands in ORCA_OUTPUT and is
    # carried back in the record.
    launcher = (
        f"exec /usr/bin/orca --replace --debug --debug-file={ORCA_DEBUG} "
        f">{ORCA_OUTPUT} 2>&1"
    )
    started = _run(
        ["/usr/bin/env", *environment, "/usr/bin/setsid", "--fork",
         "/bin/sh", "-c", launcher],
        user=user, timeout=30)

    deadline = time.monotonic() + wait
    lines = 0
    while time.monotonic() < deadline:
        probe = _run(["/usr/bin/wc", "-l", ORCA_DEBUG], user=user, timeout=10)
        try:
            lines = int(str(probe.get("stdout", "0")).split()[0])
        except (ValueError, IndexError):
            lines = 0
        # Any log at all is a screen reader that has got past its imports and
        # reached the accessibility bus. The first version wanted forty lines
        # before it believed it, which is a threshold nobody had measured.
        if lines > 0:
            break
        time.sleep(1.5)

    # `pgrep -x`, not `-f`. `-f orca` matches any command line containing the
    # word — including the sudo wrapper this probe runs things under, so the
    # old check reported `running: true` for a screen reader that had exited.
    # `pgrep -a` prints the command line, not just the pid.
    #
    # "Is a process called orca running" was never the question — the question
    # is whether the running one is *ours*, the one with a debug file. A
    # session-started Orca answers the first question and cannot answer the
    # second, and four runs were spent on the difference.
    running = _run(["/usr/bin/pgrep", "-a", "-u", user, "-x", "orca"], user=user, timeout=10)
    command_line = str(running.get("stdout", "")).strip()
    output = _run(["/usr/bin/cat", ORCA_OUTPUT], user=user, timeout=10)

    # Everything needed to tell an instrument fault from a product one, in the
    # record, so the next diagnosis does not need another twenty-five minutes.
    return {
        "ran": True,
        "launched": started.get("returncode") == 0,
        "running": running.get("returncode") == 0,
        # The decisive field: our launch put ORCA_DEBUG on the command line.
        "isOurInstance": ORCA_DEBUG in command_line,
        "commandLine": command_line[:400] or None,
        "debugLines": lines,
        "speaking": lines > 0,
        "orcaOutput": str(output.get("stdout", ""))[:2000] or None,
        "error": str(started.get("stderr", ""))[:400] or None,
        "diagnostics": {
            "screenReaderEnabled": str(_run(
                ["/usr/bin/env", *environment, "/usr/bin/gsettings", "get",
                 "org.gnome.desktop.a11y.applications", "screen-reader-enabled"],
                user=user, timeout=15).get("stdout", "")).strip(),
            "orcaSettings": str(_run(
                ["/usr/bin/env", *environment, "/usr/bin/dconf", "dump", "/org/gnome/orca/"],
                user=user, timeout=15).get("stdout", "")).strip()[:600],
            # Orca's own output as the session captured it, which is where a
            # session-started instance's messages go.
            "journal": str(_run(
                ["/usr/bin/journalctl", "--user", "--since", "-30m", "--no-pager",
                 "-o", "cat", "-g", "orca"],
                user=user, timeout=30).get("stdout", "")).strip()[-2500:],
            "speechdRunning": _run(
                ["/usr/bin/pgrep", "-a", "-u", user, "-f", "speech-dispatcher"],
                user=user, timeout=10).get("stdout", "")[:300],
            "files": str(_run(
                ["/bin/sh", "-c", f"ls -la {ORCA_DEBUG} {ORCA_OUTPUT} {SPEECHD_LOG_DIR}/ 2>&1"],
                user=user, timeout=10).get("stdout", ""))[:800],
        },
    }


def screen_reader_speech(user: str, environment: list[str], since: int = 0) -> dict:
    """Every utterance the screen reader produced, in order, from `since` onward.

    Read from **speech-dispatcher's** log rather than Orca's.

    Two runs were spent on Orca's `--debug-file`, which produced an empty file
    both times while `pgrep -x orca` said the process was alive. Whether that is
    buffering, a flag interaction between `--debug` and `--debug-file`, or
    something else in Orca 50 was never established — and it does not need to
    be, because it is the wrong channel. speechd is where the utterance actually
    goes: Orca decides what to say and hands the text to the speech system, and
    that hand-off is logged at LogLevel 4 by the daemon whatever Orca's own
    debugging is doing.

    It is also closer to the question. §31 asks what is announced; a line in
    speechd's log is a string that was submitted to be spoken, which is one hop
    nearer to a person's ear than a line in a screen reader's debug output.

    Orca is stopped first. Its own log is read afterwards as a second channel,
    and stopping it is also what would flush a buffered one.

    Returned as a list rather than a set: "announced twice" is one of the three
    failures §31 names, and collapsing repeats would hide it.
    """
    if not environment:
        return {"ran": False, "error": "no user session environment"}

    # Stop the screen reader before reading. A log still being written by a live
    # process is a log that may be missing its last line, and the last line is
    # the result announcement.
    _run(["/usr/bin/pkill", "-TERM", "-x", "orca"], user=user, timeout=15)
    time.sleep(4)
    _run(["/usr/bin/pkill", "-KILL", "-x", "orca"], user=user, timeout=15)

    utterances: list[str] = []
    source = None

    # speechd's log: one `set_...`/`speak` exchange per utterance, with the text.
    listing = _run(["/bin/sh", "-c", f"cat {SPEECHD_LOG_DIR}/*.log 2>/dev/null"],
                   user=user, timeout=30, limit=8_000_000)
    speechd_text = str(listing.get("stdout", ""))
    for match in _SPEECHD_SPEECH.finditer(speechd_text):
        said = match.group(1).strip()
        if said:
            utterances.append(said)
    if utterances:
        source = "speech-dispatcher"
    else:
        for match in _SPEECHD_QUEUED.finditer(speechd_text):
            said = match.group(1).strip()
            if said:
                utterances.append(said)
        if utterances:
            source = "speech-dispatcher-queue"

    # Orca's own debug log, second. Kept because when it works it is the
    # canonical record of what Orca decided to say, and because a run where the
    # two disagree would be worth knowing about.
    orca_read = _run(["/bin/sh", "-c",
                      f"cat {ORCA_DEBUG} /var/home/{user}/debug-*.out 2>/dev/null"],
                     user=user, timeout=30, limit=8_000_000)
    orca_lines = [m.group(1).strip()
                  for m in (_ORCA_SPEECH.search(line)
                            for line in str(orca_read.get("stdout", "")).splitlines())
                  if m and m.group(1).strip()]
    if not utterances and orca_lines:
        utterances = orca_lines
        source = "orca-debug"

    return {
        "ran": True,
        "ok": bool(utterances),
        "source": source,
        "total": len(utterances),
        "orcaDebugUtterances": len(orca_lines),
        "speechdLogBytes": len(speechd_text),
        # `since` lets a caller ask "what was said after I pressed that", which
        # is the only way to attribute an utterance to an action.
        "utterances": utterances[since:][:400],
    }


#: The processes §41 asks about, by the pattern that finds each one.
PERFORMANCE_TARGETS = {
    "gnome-shell": "gnome-shell",
    "companion": "bunny-companion",
    "orca": "orca",
}


def performance_sample(user: str, seconds: float = 20.0) -> dict:
    """CPU and memory for the desktop and the Companion, over an idle interval.

    CPU is measured as a *delta* over the interval, not read from `ps`'s `%cpu`.
    `ps` reports the average since the process started, which on a session that
    has just done a whole permission journey is a number about the journey, not
    about the desktop sitting still — and "Companion idle CPU" is the question.

    Read from /proc rather than from a tool: `utime + stime` in clock ticks is
    the same quantity before and after, and the arithmetic is visible here
    instead of inside `top`'s idea of an interval.
    """
    def snapshot() -> dict:
        found: dict[str, dict] = {}
        for label, pattern in PERFORMANCE_TARGETS.items():
            listing = _run(["/usr/bin/pgrep", "-u", user, "-f", pattern], timeout=15)
            pids = [line.strip() for line in str(listing.get("stdout", "")).splitlines() if line.strip()]
            total_ticks, total_rss = 0, 0
            for pid in pids[:8]:
                stat = _run(["/usr/bin/cat", f"/proc/{pid}/stat"], timeout=10)
                status = _run(["/usr/bin/grep", "VmRSS", f"/proc/{pid}/status"], timeout=10)
                fields = str(stat.get("stdout", "")).split()
                if len(fields) > 14:
                    try:
                        total_ticks += int(fields[13]) + int(fields[14])
                    except ValueError:
                        pass
                parts = str(status.get("stdout", "")).split()
                if len(parts) > 1 and parts[1].isdigit():
                    total_rss += int(parts[1])
            found[label] = {"processes": len(pids), "ticks": total_ticks, "rssKib": total_rss}
        return found

    first = snapshot()
    time.sleep(seconds)
    second = snapshot()

    hertz = 100.0  # USER_HZ; constant on every kernel this image runs on.
    measured = {}
    for label in PERFORMANCE_TARGETS:
        before, after = first[label], second[label]
        used = (after["ticks"] - before["ticks"]) / hertz
        measured[label] = {
            "processes": after["processes"],
            "rssKib": after["rssKib"],
            "rssMib": round(after["rssKib"] / 1024, 1) if after["rssKib"] else 0,
            "cpuSeconds": round(used, 3),
            "cpuPercent": round(100 * used / seconds, 2) if seconds else None,
        }
    return {"ran": True, "intervalSeconds": seconds, "processes": measured}


def session_ready(user: str, environment: list[str], wait: float = 120.0) -> dict:
    """The product's own readiness probe, run as it ships.

    Not a reimplementation. `/usr/libexec/bunny-session-ready` answers eight
    conditions — logind, the compositor, the shell extension, the Companion
    units, its socket, the trust store, a confining capsule backend and the
    operation's program — and prints BUNNY_SESSION_READY on its own line only
    when all of them hold.

    The journey needs this because asking first is not the same as asking early:
    a request submitted before the runtime is up came back `warning`, and the
    same request later in the same session reached a permission prompt.
    """
    outcome = _run(
        ["/usr/bin/env", *environment, "/usr/libexec/bunny-session-ready",
         "--wait", str(wait)],
        user=user, timeout=int(wait) + 60,
    )
    if not outcome.get("ran"):
        return {"ok": False, "error": str(outcome.get("error"))[:300]}
    out = str(outcome.get("stdout", ""))
    marker = any(line.strip() == "BUNNY_SESSION_READY" for line in out.splitlines())
    document = {}
    try:
        document = json.loads(out.split("BUNNY_SESSION_READY")[0].strip())
    except (ValueError, IndexError):
        pass
    return {
        "ok": outcome.get("returncode") == 0 and marker,
        "markerSeen": marker,
        "notReady": document.get("notReady", []),
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

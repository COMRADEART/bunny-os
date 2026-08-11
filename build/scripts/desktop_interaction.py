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

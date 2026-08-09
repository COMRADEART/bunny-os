#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Press the Bunny desktop's controls, and record what the guest saw.

This is the host half of the acceptance test the desktop shipped without:

    boot -> shell loads -> click Files -> a file manager window appears ->
    close it -> click Terminal -> a terminal appears and takes typing ->
    close it -> the Bunny shell is still alive and still takes input.

Every click is a QEMU input event on an emulated tablet (see qmp-input.py) and
every observation is made inside the guest by desktop_interaction.py. Neither
side can fake the other's evidence, which is the point of splitting it: the host
cannot see a systemd scope and the guest cannot inject a pointer event.

Two things the script does that are worth stating outright.

**It proves the keyboard, not just the pointer.** After the terminal opens it
types a command that writes a file, and afterwards the run reads that file out
of the guest's disk. A terminal window that appeared but never received a
keystroke is a real failure mode — Mutter focus is a separate mechanism from
Mutter mapping — and a screenshot of a terminal cannot tell the two apart.

**It closes windows through the window manager.** Alt+F4 is a key event, which
means the close path is exercised as input too, and the "does the shell survive
an application closing" question is asked about a real unmap rather than a
`kill`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qmp_client import Qmp  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "qmp_input", Path(__file__).resolve().parent / "qmp-input.py")
_qmp_input = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_qmp_input)
Pointer = _qmp_input.Pointer


class Control:
    """The host end of the guest's control channel."""

    def __init__(self, path: str, timeout: float = 900.0) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect(path)
        self._buffer = b""

    def read(self, timeout: float = 300.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buffer:
            if time.monotonic() > deadline:
                return None
            self._socket.settimeout(max(1.0, deadline - time.monotonic()))
            try:
                chunk = self._socket.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                return None
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def ask_nothing(self, document: dict) -> None:
        """Send without waiting. Only the hello does this."""
        self._socket.sendall((json.dumps(document) + "\n").encode("utf-8"))

    def ask(self, document: dict, timeout: float = 300.0) -> dict | None:
        self._socket.sendall((json.dumps(document) + "\n").encode("utf-8"))
        answer = self.read(timeout=timeout)
        return None if answer is None else answer.get("reply")

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


def centre(extents: dict) -> tuple[int, int]:
    return (extents["x"] + extents["width"] // 2,
            extents["y"] + extents["height"] // 2)


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-drive")
    parser.add_argument("--qmp", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--screens", help="directory for per-step screenshots")
    parser.add_argument("--marker", default="/var/home/bunny/bunny-terminal-typed.txt",
                        help="the file the typed command creates in the guest")
    #: How long to wait for a window after a click. Generous, because this runs
    #: on llvmpipe and Nautilus's first start on a cold page cache is slow; the
    #: wait ends as soon as the guest reports a window, so the cost is only paid
    #: when something is actually wrong.
    parser.add_argument("--settle", type=float, default=45.0)
    #: The two requests the milestone names. The first must produce a real
    #: answer from the runtime; the second must produce a desktop action.
    parser.add_argument("--ask", default="What files are in my Downloads folder?")
    parser.add_argument("--ask-action", default="Open Files")
    arguments = parser.parse_args()

    steps: list[dict] = []
    report = {
        "schemaVersion": 1,
        "display": {"width": arguments.width, "height": arguments.height},
        "steps": steps,
    }

    def save(status: str) -> int:
        report["status"] = status
        Path(arguments.output).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.output).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"interaction report: {arguments.output}")
        return 0 if status == "complete" else 7

    try:
        control = Control(arguments.control)
    except OSError as exc:
        report["error"] = f"cannot reach the control socket: {exc}"
        return save("no-control-channel")

    # Say hello first. The guest is waiting to be asked rather than announcing,
    # because QEMU discards what the guest writes while no client is attached
    # and this driver attaches minutes after the guest is ready.
    control.ask_nothing({"command": "hello"})
    print("waiting for the guest to report its controls...")
    ready = control.read(timeout=780)
    if ready is None or ready.get("event") != "ready":
        report["error"] = "the guest never reported ready"
        report["lastMessage"] = ready
        control.close()
        return save("guest-never-ready")

    targets = ready.get("targets", {})
    report["targets"] = targets
    report["controlCount"] = ready.get("controlCount")
    print(f"the guest exposes {ready.get('controlCount')} named controls; "
          f"targets: {', '.join(sorted(targets)) or 'none'}")

    try:
        qmp = Qmp(arguments.qmp)
    except (OSError, RuntimeError) as exc:
        report["error"] = f"cannot reach QMP: {exc}"
        control.close()
        return save("no-qmp")
    pointer = Pointer(qmp, arguments.width, arguments.height)

    def screenshot(name: str) -> str | None:
        if not arguments.screens:
            return None
        target = Path(arguments.screens) / f"{name}.ppm"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            qmp.execute("screendump", filename=str(target.resolve()))
        except (RuntimeError, TimeoutError, OSError) as exc:
            print(f"  screendump failed: {exc}")
            return None
        for _ in range(50):
            if target.is_file() and target.stat().st_size > 0:
                return str(target)
            time.sleep(0.2)
        return None

    def step(name: str, **fields) -> dict:
        entry = {"step": name, **fields}
        steps.append(entry)
        print(f"  {name}: {json.dumps({k: v for k, v in fields.items() if k != 'state'})[:160]}")
        return entry

    def wait_for(application: str, want_window: bool, label: str) -> dict:
        """Poll the guest until the application's window appears, or time out."""
        deadline = time.monotonic() + arguments.settle
        state = None
        while time.monotonic() < deadline:
            answer = control.ask({"command": "state", "application": application,
                                  "label": label}, timeout=120)
            state = (answer or {}).get("state")
            if state is None:
                break
            if state.get("windowVisible") == want_window:
                break
            time.sleep(3)
        return state or {}

    def press(target_name: str, label: str) -> dict | None:
        target = targets.get(target_name)
        if target is None:
            step(f"click-{target_name}", pressed=False,
                 reason="the guest never found this control on screen")
            return None
        x, y = centre(target["extents"])
        pointer.click(x, y)
        step(f"click-{target_name}", pressed=True, at={"x": x, "y": y},
             extents=target["extents"], role=target.get("role"),
             within=target.get("path", [])[-3:])
        return target

    def close_focused(what: str, *, shell_exit: bool = False) -> None:
        """Close the front window the way a person would.

        A terminal is closed by leaving the shell — that is what the window is
        *for*, and `exit` cannot be confused with a window manager keybinding
        that did not arrive. Everything else gets Alt+F4, the window manager's
        own close, which exercises the same unmap path the title bar button
        takes.

        Ctrl+W follows as a second attempt for applications that answer it.
        It is deliberately last: an earlier version sent it first and Nautilus
        closed, which made Alt+F4 look like it was working when it was not.
        """
        used = []
        if shell_exit:
            pointer.type_text("exit")
            pointer.key("ret")
            used.append("exit")
            time.sleep(4)
        pointer.key("alt", "f4")
        used.append("alt+f4")
        time.sleep(4)
        pointer.key("ctrl", "w")
        used.append("ctrl+w")
        time.sleep(3)
        step(f"close-{what}", keys=used)

    try:
        return interact(control, qmp, pointer, targets, arguments,
                        report, steps, step, screenshot, wait_for, press,
                        close_focused, save)
    except Exception as exc:  # noqa: BLE001 - the report matters more
        # Whatever went wrong, the transcript up to that point is the evidence
        # this run exists to produce. The first version let a ValueError out of
        # the middle of the interaction and lost every step before it, including
        # the two that had already succeeded.
        report["error"] = f"{type(exc).__name__}: {exc}"
        import traceback
        report["traceback"] = traceback.format_exc().splitlines()[-8:]
        try:
            control.close()
            qmp.close()
        except Exception:  # noqa: BLE001
            pass
        return save("driver-failed")


def interact(control, qmp, pointer, targets, arguments,
             report, steps, step, screenshot, wait_for, press, close_focused, save):
    """The scenario. Everything it needs is passed in; it owns no state."""
    # ---- baseline ---------------------------------------------------------
    before_files = control.ask({"command": "state", "application": "files",
                                "label": "before"}, timeout=120)
    before_terminal = control.ask({"command": "state", "application": "terminal",
                                   "label": "before"}, timeout=120)
    step("baseline",
         files=(before_files or {}).get("state", {}),
         terminal=(before_terminal or {}).get("state", {}))
    screenshot("00-desktop")

    # A baseline that already has the application running would make everything
    # after it meaningless — "it was there after the click" is only evidence if
    # it was not there before.
    report["baselineClean"] = not (
        (before_files or {}).get("state", {}).get("launched") or
        (before_terminal or {}).get("state", {}).get("launched"))

    # ---- Files ------------------------------------------------------------
    if press("files", "Files") is not None:
        state = wait_for("files", True, "after-click")
        step("files-opened", launched=state.get("launched"),
             startedByTheShell=state.get("startedByTheShell"),
             windowVisible=state.get("windowVisible"),
             windows=state.get("windows", {}).get("count"),
             units=state.get("unit", {}).get("units"), state=state)
        report["files"] = state
        screenshot("01-files-open")

        close_focused("files")
        closed = wait_for("files", False, "after-close")
        step("files-closed", windowVisible=closed.get("windowVisible"),
             windows=closed.get("windows", {}).get("count"), state=closed)
        report["filesClosed"] = closed
        screenshot("02-files-closed")

    shell = (control.ask({"command": "shell", "label": "after-files"}, timeout=120) or {}).get("shell", {})
    step("shell-after-files", responded=shell.get("responded"),
         extensionEnabled=shell.get("extensionEnabled"))
    report["shellAfterFiles"] = shell

    # ---- Terminal ---------------------------------------------------------
    if press("terminal", "Terminal") is not None:
        state = wait_for("terminal", True, "after-click")
        step("terminal-opened", launched=state.get("launched"),
             startedByTheShell=state.get("startedByTheShell"),
             windowVisible=state.get("windowVisible"),
             windows=state.get("windows", {}).get("count"),
             units=state.get("unit", {}).get("units"), state=state)
        report["terminal"] = state
        screenshot("03-terminal-open")

        # Type into it. The window has to be focused for this to land, which is
        # the point: a mapped window that never took focus is a real failure and
        # it looks identical in a photograph.
        if state.get("windowVisible"):
            time.sleep(3)
            pointer.type_text(f"date > {arguments.marker}")
            pointer.key("ret")
            time.sleep(4)
            screenshot("04-terminal-typed")
            step("terminal-typed", command=f"date > {arguments.marker}",
                 note="the file is read from the guest disk after shutdown")

        close_focused("terminal", shell_exit=True)
        closed = wait_for("terminal", False, "after-close")
        step("terminal-closed", windowVisible=closed.get("windowVisible"),
             windows=closed.get("windows", {}).get("count"), state=closed)
        report["terminalClosed"] = closed
        screenshot("05-terminal-closed")

    # ---- the assistant, end to end ----------------------------------------
    #
    # The milestone's central claim: a person types a request, the character
    # moves through the states the request is actually in, and a real answer
    # comes back from the runtime. Every observation is read out of the
    # accessibility tree, which is the same thing a screen reader would see.
    def watch_character(seconds: float, label: str) -> list[dict]:
        """Poll the character and record every state it passes through."""
        seen: list[dict] = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            answer = control.ask({"command": "character", "label": label}, timeout=120)
            observation = (answer or {}).get("character") or {}
            state = observation.get("state", "")
            if state and (not seen or seen[-1]["state"] != state):
                seen.append({"state": state, "says": observation.get("says", ""),
                             "reason": observation.get("reason", "")})
                # Idle after something happened means the request is over.
                if state == "idle" and len(seen) > 1:
                    break
            time.sleep(2)
        return seen

    for label, request in (("factual", arguments.ask), ("action", arguments.ask_action)):
        if not request:
            continue
        target = targets.get("ask")
        if target is None:
            step(f"assistant-{label}", asked=False,
                 reason="the assistant input was not found in the accessibility tree")
            continue

        x, y = centre(target["extents"])
        pointer.click(x, y)
        time.sleep(1.5)
        before = control.ask({"command": "character", "label": f"{label}-before"}, timeout=120)
        pointer.type_text(request)
        time.sleep(0.5)
        screenshot(f"07-{label}-typed")
        pointer.key("ret")

        transitions = watch_character(arguments.settle * 2, label)
        after = control.ask({"command": "character", "label": f"{label}-after"}, timeout=120)
        final = (after or {}).get("character") or {}
        step(f"assistant-{label}", asked=True, request=request,
             at={"x": x, "y": y},
             stateBefore=((before or {}).get("character") or {}).get("state"),
             states=[item["state"] for item in transitions],
             answer=final.get("says", ""),
             finalState=final.get("state", ""))
        report[f"assistant_{label}"] = {
            "request": request,
            "transitions": transitions,
            "final": final,
        }
        screenshot(f"08-{label}-answered")

    # ---- the desktop is still there and still takes input -----------------
    shell = (control.ask({"command": "shell", "label": "after-terminal"}, timeout=120) or {}).get("shell", {})
    step("shell-after-terminal", responded=shell.get("responded"),
         extensionEnabled=shell.get("extensionEnabled"))
    report["shellAfterTerminal"] = shell

    # Press a Bunny control that is not an application launch, and confirm the
    # desktop still reacts: the shell answering D-Bus says the process is alive,
    # not that its input handling is. A control that is still findable at the
    # same place afterwards is what says the desktop is still assembled.
    press("home", "Home")
    time.sleep(2)
    after = control.ask({"command": "controls", "label": "after-everything"}, timeout=180)
    remaining = (after or {}).get("controls", {}).get("controls", [])
    named = {entry["name"] for entry in remaining}
    report["controlsAfter"] = sorted(named)
    step("desktop-still-assembled",
         controlCount=len(remaining),
         hasFiles="Files" in named, hasTerminal="Terminal" in named)
    screenshot("06-desktop-after")

    control.ask({"command": "done"}, timeout=60)
    control.close()
    qmp.close()

    return save("complete")


if __name__ == "__main__":
    raise SystemExit(main())

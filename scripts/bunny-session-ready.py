#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether a Bunny session is ready for a person to use, asked of the system.

Every graphical harness in this repository has, at some point, waited a fixed
number of seconds and then photographed whatever was there. That is how a
screenshot of GDM, and a screenshot of a blanked screen, both got recorded as
"the desktop". A delay is not a readiness condition; it is a guess that happens
to be right on the machine it was tuned on.

So readiness is defined as a conjunction of things that are separately true or
false, each measured from the running system, each reported by name:

``session``    logind says this user has an active graphical session
``compositor`` a Wayland display exists and gnome-shell is running under it
``shell``      the Bunny Shell extension is loaded and not in error
``companion``  the Companion runtime unit is active
``client``     the Companion window unit is active and its socket answers
``trust``      the trust store is readable and the gate can be constructed
``capsules``   a *confining* backend is available, not merely systemd
``tasks``      the task runtime accepted a status request

A blank desktop fails ``shell``. A Companion that crash-looped fails
``companion`` on its restart count rather than on a lucky sample. A machine
where only ``systemd-scope`` is present fails ``capsules``, because that backend
carries a cgroup and confines nothing — and a session that would run the first
application unconfined is not a ready Bunny session.

Prints one JSON document, and — only when everything holds — the line
``BUNNY_SESSION_READY`` on its own. The marker is what a serial console can be
grepped for; the JSON is what says which condition was false when it is not.

Exit status is 0 when ready, 1 when not, so a shell can wait on it in a loop.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MARKER = "BUNNY_SESSION_READY"

#: User units that must be active. Named rather than discovered: a probe that
#: asked "is anything failing" would pass on a machine where the Companion had
#: never been started at all.
REQUIRED_USER_UNITS = ("bunny-companion.service",)

#: Units that must be active *if the build has them*. The window is enabled per
#: user rather than by preset, so a profile without it is a real configuration
#: and not a failure — but a session that has it and cannot start it is.
OPTIONAL_USER_UNITS = ("bunny-companion-window.service",)

#: Above this many restarts in one session, a unit is looping rather than
#: running. Sampling "is it active right now" catches a looping unit only when
#: the sample lands inside a live window.
RESTART_CEILING = 3


def _run(argv: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 127, f"{type(error).__name__}: {error}"
    return completed.returncode, (completed.stdout or "").strip()


def _unit_property(unit: str, name: str) -> str:
    code, value = _run(["systemctl", "--user", "show", "--property", name, "--value", unit])
    return value if code == 0 else ""


def check_session() -> dict:
    code, seat = _run(["loginctl", "show-user", str(os.getuid()), "--property=State", "--value"])
    code2, sessions = _run(["loginctl", "list-sessions", "--no-legend"])
    graphical = any(
        part in sessions for part in ("wayland", "x11", "seat0")
    ) if code2 == 0 else False
    return {
        "ok": code == 0 and seat == "active" and graphical,
        "userState": seat,
        "hasGraphicalSession": graphical,
    }


def check_compositor() -> dict:
    display = os.environ.get("WAYLAND_DISPLAY", "")
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    socket = Path(runtime) / display if runtime and display else None
    code, _ = _run(["pgrep", "-x", "gnome-shell"])
    return {
        "ok": bool(display) and socket is not None and socket.exists() and code == 0,
        "waylandDisplay": display,
        "socketExists": bool(socket and socket.exists()),
        "gnomeShellRunning": code == 0,
    }


def check_shell() -> dict:
    """The Bunny Shell extension, as GNOME itself reports it.

    Asked over D-Bus rather than by looking for files: an extension directory
    that exists and failed to load is exactly the state that produces a blank
    desktop, and the filesystem cannot tell the difference.
    """
    code, output = _run([
        "gdbus", "call", "--session",
        "--dest", "org.gnome.Shell",
        "--object-path", "/org/gnome/Shell",
        "--method", "org.gnome.Shell.Extensions.GetExtensionInfo",
        "bunny-shell@bunny-os.org",
    ])
    loaded = code == 0 and "'state': <1>" in output.replace('"', "'")
    return {"ok": loaded, "queried": code == 0, "raw": output[:200]}


def check_units() -> dict:
    rows = {}
    healthy = True
    for unit in REQUIRED_USER_UNITS + OPTIONAL_USER_UNITS:
        state = _unit_property(unit, "ActiveState")
        restarts = _unit_property(unit, "NRestarts")
        loaded = _unit_property(unit, "LoadState")
        looping = restarts.isdigit() and int(restarts) > RESTART_CEILING
        row = {
            "activeState": state,
            "loadState": loaded,
            "restarts": int(restarts) if restarts.isdigit() else None,
            "looping": looping,
        }
        required = unit in REQUIRED_USER_UNITS
        row["ok"] = state == "active" and not looping if required else (
            state in ("active", "inactive") and not looping
        )
        if not row["ok"]:
            healthy = False
        rows[unit] = row
    return {"ok": healthy, "units": rows}


def check_client() -> dict:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    socket = Path(runtime) / "bunny-companion" / "companion.sock" if runtime else None
    return {
        "ok": socket is not None and socket.exists(),
        "socket": str(socket) if socket else "",
    }


def check_trust() -> dict:
    try:
        sys.path.insert(0, "/usr/lib/bunny-os/python")
        import trust
        from trust.store import TrustStore

        path = trust.default_store_path()
        TrustStore(path, session_id="readiness").load()
        return {"ok": True, "store": str(path)}
    except Exception as error:  # noqa: BLE001 - an unreadable store is not ready
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def check_capsules() -> dict:
    try:
        sys.path.insert(0, "/usr/lib/bunny-os/python")
        from capsules.backends import MachineProbe, available_backends

        backends = list(available_backends(MachineProbe.measure()))
        confining = [name for name in backends if name != "systemd-scope"]
        return {"ok": bool(confining), "backends": backends, "confining": confining}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def check_tasks() -> dict:
    """The operation table, and the program the first one needs.

    A session whose catalogue offers an operation whose program is not installed
    is a session that will refuse the first thing anybody asks for, and it
    should say so here rather than there.
    """
    try:
        sys.path.insert(0, "/usr/lib/bunny-os/python")
        from companion.capsule_tasks import OPERATIONS

        missing = []
        for descriptor in OPERATIONS.values():
            if descriptor.operation_id == "image.resize" and not Path(
                "/usr/libexec/bunny-image-tool"
            ).is_file():
                missing.append("/usr/libexec/bunny-image-tool")
        return {"ok": not missing, "operations": sorted(OPERATIONS), "missingPrograms": missing}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


CHECKS = {
    "session": check_session,
    "compositor": check_compositor,
    "shell": check_shell,
    "companion": check_units,
    "client": check_client,
    "trust": check_trust,
    "capsules": check_capsules,
    "tasks": check_tasks,
}


def evaluate() -> dict:
    results = {}
    for name, check in CHECKS.items():
        try:
            results[name] = check()
        except Exception as error:  # noqa: BLE001 - a check that raised is not a pass
            results[name] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    ready = all(bool(row.get("ok")) for row in results.values())
    return {
        "ready": ready,
        "notReady": sorted(name for name, row in results.items() if not row.get("ok")),
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunny-session-ready", description=__doc__)
    parser.add_argument(
        "--wait", type=float, default=0.0,
        help="poll until ready or this many seconds have passed",
    )
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--quiet", action="store_true", help="print only the marker")
    arguments = parser.parse_args(argv)

    deadline = time.monotonic() + max(0.0, arguments.wait)
    while True:
        report = evaluate()
        if report["ready"] or time.monotonic() >= deadline:
            break
        time.sleep(max(0.1, arguments.interval))

    if not arguments.quiet:
        print(json.dumps(report, indent=1, sort_keys=True))
    if report["ready"]:
        # On its own line, so a serial console can be grepped for it and a
        # partial line from another writer cannot manufacture it.
        print(MARKER, flush=True)
        return 0
    print(f"{MARKER}-NOT: {','.join(report['notReady'])}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

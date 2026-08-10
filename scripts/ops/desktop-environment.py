#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What desk the gates ran on, recorded so the figures can be read later.

A development tool, not shipped.

Everything here is a fact about the machine rather than about this build, and
each one changes what a gate result means. A hundred lifecycle runs on a host
with no notification daemon measure the refusal path; the same hundred with one
measure the dispatch path. A report that gave the number without the desk would
be giving half of it.

The service versions are read by asking the running services, not by reading
package metadata: an installed ``xdg-desktop-portal`` that is not running is a
different desk from one that is, and §16 is a whole section about that
distinction.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "bunny-os/desktop-action-environment/1"

_PROGRAMS = (
    "pactl", "gsettings", "wl-copy", "xclip", "notify-send",
    "gnome-control-center", "systemsettings", "nautilus", "dunst",
)

_BUS_NAMES = (
    "org.freedesktop.Notifications",
    "org.freedesktop.portal.Desktop",
    "org.freedesktop.FileManager1",
)


def _run(argv: list[str], *, timeout: float = 10.0) -> str:
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _owner(name: str) -> bool:
    output = _run([
        "busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "NameHasOwner", "s", name,
    ], timeout=5.0)
    return output.strip().endswith("true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.root))
    from companion.desktop.broker import BrokerOptions, DesktopActionBroker

    broker = DesktopActionBroker(BrokerOptions()).start()
    report = broker.environment(refresh=True)
    posture = report.to_json()
    broker.stop()

    document = {
        "schemaVersion": SCHEMA,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "distribution": _run(["sh", "-c", ". /etc/os-release && echo \"$PRETTY_NAME\""]),
            "container": bool(os.environ.get("container")),
            "wsl": "microsoft" in platform.release().lower(),
        },
        "session": {
            "type": posture["session"],
            "desktop": posture["desktop"],
            "waylandDisplay": bool(os.environ.get("WAYLAND_DISPLAY")),
            "x11Display": bool(os.environ.get("DISPLAY")),
            "runtimeDirectory": bool(os.environ.get("XDG_RUNTIME_DIR")),
            "sessionBus": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
        },
        # Installed *and* answering, kept apart. §16's rule is that the first
        # does not imply the second, and a record that conflated them would let
        # a later reader draw exactly the inference the rule forbids.
        "programsInstalled": {
            name: bool(_run(["sh", "-c", f"command -v {name}"])) for name in _PROGRAMS
        },
        "servicesAnswering": {name: _owner(name) for name in _BUS_NAMES},
        "audio": _run(["sh", "-c", "pactl info 2>/dev/null | head -3"]),
        "posture": posture,
        "commit": _run(["git", "-C", str(args.root), "rev-parse", "HEAD"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "posture": posture["posture"],
        "available": len(posture["availableActions"]),
        "servicesAnswering": document["servicesAnswering"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

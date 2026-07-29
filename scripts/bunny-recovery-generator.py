#!/usr/bin/python3
"""Select the recovery target once when an authenticated request schedules it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


MARKER = Path("/var/lib/bunny-os/recovery/scheduled.json")
TARGET = "/usr/lib/systemd/system/bunny-recovery.target"


def main() -> int:
    if len(sys.argv) < 2 or not MARKER.is_file():
        return 0
    try:
        value = json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if set(value) != {"schemaVersion", "mode", "scheduledAt", "scheduledByUid"} or value.get("schemaVersion") != 1 or value.get("mode") not in {"recovery", "safe-graphics"}:
        return 0
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    link = output / "default.target"
    try:
        link.symlink_to(TARGET)
    except FileExistsError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

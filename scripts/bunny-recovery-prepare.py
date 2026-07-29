#!/usr/bin/python3
"""Fail closed if the one-shot recovery marker is malformed or unsafe."""

import json
import os
from pathlib import Path


MARKER = Path("/var/lib/bunny-os/recovery/scheduled.json")


def main() -> int:
    try:
        value = json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    valid = set(value) == {"schemaVersion", "mode", "scheduledAt", "scheduledByUid"} and value.get("schemaVersion") == 1 and value.get("mode") in {"recovery", "safe-graphics"} and isinstance(value.get("scheduledByUid"), int)
    if not valid or MARKER.is_symlink() or (MARKER.stat().st_mode & 0o077):
        return 1
    print(f'Recovery mode {value["mode"]} is scheduled for the next boot.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

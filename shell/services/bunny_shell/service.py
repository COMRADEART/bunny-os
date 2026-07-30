# SPDX-License-Identifier: GPL-3.0-or-later
"""Small resilient user-session status service."""

from __future__ import annotations

from datetime import datetime, timezone
import signal
import time

from .core_state import shell_status
from .paths import atomic_write_json, runtime_dir


def run() -> int:
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    target = runtime_dir() / "status.json"
    while not stopping:
        value = shell_status()
        value["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        atomic_write_json(target, value)
        for _ in range(20):
            if stopping:
                break
            time.sleep(0.5)
    return 0

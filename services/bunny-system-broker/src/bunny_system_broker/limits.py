# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-UID replay and rate controls."""

from __future__ import annotations

from collections import defaultdict, deque
import threading
import time


class RateLimiter:
    def __init__(self, read_per_minute: int = 60, mutate_per_minute: int = 10) -> None:
        self._limits = {"read": read_per_minute, "mutate": mutate_per_minute}
        self._events: dict[tuple[int, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, uid: int, mutating: bool, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        bucket = "mutate" if mutating else "read"
        key = (uid, bucket)
        with self._lock:
            queue = self._events[key]
            while queue and moment - queue[0] >= 60:
                queue.popleft()
            if len(queue) >= self._limits[bucket]:
                return False
            queue.append(moment)
            return True


class NonceCache:
    def __init__(self, lifetime_seconds: int = 90, max_per_uid: int = 512) -> None:
        self._lifetime = lifetime_seconds
        self._maximum = max_per_uid
        self._values: dict[int, dict[str, float]] = defaultdict(dict)
        self._lock = threading.Lock()

    def accept(self, uid: int, nonce: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        with self._lock:
            values = self._values[uid]
            expired = [key for key, seen in values.items() if moment - seen >= self._lifetime]
            for key in expired:
                del values[key]
            if nonce in values:
                return False
            if len(values) >= self._maximum:
                oldest = min(values, key=values.get)
                del values[oldest]
            values[nonce] = moment
            return True


#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""An application that deliberately exceeds its limits, and says how far it got.

The companion to :mod:`probe`. Where the probe asks what it can *reach*, this one
asks what it is *allowed to consume* — and the only honest way to answer that is
to go past the limit and record what happened.

Three modes, and each records the point at which the system intervened rather
than whether a property exists in a unit file:

``memory``  allocate in fixed blocks until the allocation fails or the process is
            killed. A cgroup ``MemoryMax`` shows up as the second: the process
            does not get an exception, it gets a SIGKILL, and the evidence is the
            harness observing the exit signal.
``tasks``   spawn threads until one cannot be created. ``TasksMax`` is a hard
            ceiling on the cgroup's pid count, so this one *does* surface as an
            exception and the count reached is the measurement.
``idle``    do nothing for a bounded time, so the harness can measure steady-state
            memory and kill it from outside.

It writes progress continuously rather than at the end, because the memory mode
is expected to be killed and a result written only on a clean exit would be a
result this test never produces.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

#: Allocation granularity. Large enough that a 4 GiB ceiling is reached in a few
#: hundred steps, small enough that the last successful step is a precise figure.
BLOCK_BYTES = 8 * 1024 * 1024

#: Ceilings on the run itself, so a mode whose limit is not enforced stops rather
#: than consuming the machine. Exceeding one of these is itself the result: it
#: means nothing intervened.
#:
#: The absolute bound is deliberately modest. An earlier version allowed 32 GiB
#: and, on a host that does not enforce ``MemoryMax``, drove the whole virtual
#: machine into its own out-of-memory killer — which then looked like the cgroup
#: working. A qualification run that destabilises the machine it is measuring
#: produces evidence about the wrong thing.
MAX_BLOCKS = 512           # 4 GiB, absolute

#: When the harness states the ceiling under test, stop at a small multiple of
#: it. Going eight times past a limit is more than enough to show that nothing
#: intervened; going a hundred times past it only exhausts the host.
CEILING_MULTIPLE = 8
MAX_THREADS = 20_000
IDLE_SECONDS = 30.0


def _output() -> Path:
    return Path(os.environ.get("BUNNY_STRESS_OUTPUT", "/run/bunny/app/data/stress-result.json"))


def _write(document: dict) -> None:
    target = _output()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def _cgroup() -> str:
    try:
        return Path("/proc/self/cgroup").read_text(encoding="utf-8").strip()[:200]
    except OSError as error:
        return f"unreadable: {error}"


def _rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def memory_mode(document: dict) -> None:
    blocks: list[bytearray] = []
    ceiling = 0
    try:
        ceiling = int(os.environ.get("BUNNY_STRESS_CEILING", "0"))
    except ValueError:
        ceiling = 0
    limit = MAX_BLOCKS
    if ceiling > 0:
        limit = min(MAX_BLOCKS, max(4, (ceiling * CEILING_MULTIPLE) // BLOCK_BYTES))
    document["stopAfterBytes"] = limit * BLOCK_BYTES
    for index in range(limit):
        try:
            block = bytearray(BLOCK_BYTES)
            # Touch every page: an untouched allocation is address space, not
            # memory, and a cgroup accounts for pages that exist.
            for offset in range(0, BLOCK_BYTES, 4096):
                block[offset] = 1
            blocks.append(block)
        except MemoryError:
            document["outcome"] = "MemoryError"
            document["allocatedBytes"] = index * BLOCK_BYTES
            _write(document)
            return
        document["allocatedBytes"] = (index + 1) * BLOCK_BYTES
        document["rssBytes"] = _rss_bytes()
        if index % 4 == 0:
            _write(document)
    document["outcome"] = "ceiling-reached-without-intervention"
    _write(document)


def tasks_mode(document: dict) -> None:
    stop = threading.Event()
    threads: list[threading.Thread] = []

    def idle() -> None:
        stop.wait()

    for index in range(MAX_THREADS):
        try:
            thread = threading.Thread(target=idle, daemon=True)
            thread.start()
            threads.append(thread)
        except RuntimeError as error:
            document["outcome"] = f"RuntimeError: {error}"
            document["threadsStarted"] = index
            document["cgroup"] = _cgroup()
            _write(document)
            stop.set()
            return
        except OSError as error:
            document["outcome"] = f"OSError: {error}"
            document["threadsStarted"] = index
            document["cgroup"] = _cgroup()
            _write(document)
            stop.set()
            return
        if index % 32 == 0:
            document["threadsStarted"] = index
            _write(document)
    document["outcome"] = "ceiling-reached-without-intervention"
    document["threadsStarted"] = MAX_THREADS
    _write(document)
    stop.set()


def idle_mode(document: dict) -> None:
    document["outcome"] = "idling"
    started = time.monotonic()
    while time.monotonic() - started < IDLE_SECONDS:
        document["rssBytes"] = _rss_bytes()
        document["elapsed"] = round(time.monotonic() - started, 2)
        _write(document)
        time.sleep(0.5)
    document["outcome"] = "idled-to-completion"
    _write(document)


def main() -> int:
    mode = os.environ.get("BUNNY_STRESS_MODE", "idle")
    document = {
        "schemaVersion": 1,
        "mode": mode,
        "pid": os.getpid(),
        "cgroup": _cgroup(),
        "startedAt": time.time(),
        "outcome": "started",
        "rssBytes": _rss_bytes(),
    }
    _write(document)
    if mode == "memory":
        memory_mode(document)
    elif mode == "tasks":
        tasks_mode(document)
    else:
        idle_mode(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

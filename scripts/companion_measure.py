#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure the integrated companion on the machine this is run on.

§24's list, and nothing beyond it. Every figure here is a measurement of *this*
host with *this* Python, and the report says so in the record it produces —
because the number that matters for Bunny OS is the one taken on a Raspberry Pi
running the installed image, and this program cannot take that one.

What it will not do:

* it will not report a Raspberry Pi, ARM, 64 MiB or GPU figure. There is no code
  path that produces one, so a report cannot accidentally contain one.
* it will not report resident memory where the platform cannot measure it. On
  Linux it reads ``/proc/self/status``'s ``VmRSS``; elsewhere it says
  ``unavailable`` rather than substituting Python's own heap accounting, which
  measures a different thing and would be quietly wrong by a factor.
* it will not average away a cold start. The first sample of every latency is
  reported beside the median, because the first task after a runtime starts is
  the one a user actually waits for.

Run it with ``bunny-os companion measure`` or directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import statistics
import importlib.util
import sys
import tempfile
import time
from typing import Any, Callable

# Only when the package is not importable yet.
#
# For a standalone invocation nothing is importable, so this behaves exactly as
# it always has: the installed tree first, the checkout as a fallback.
#
# The guard is for the other case. In a process that already works — a test
# run, another tool that imported this one — the checkout is already on
# ``sys.path``, so the loop skipped it as already-present and inserted the
# *installed* tree in front of it. Every import after that came from whatever
# build happened to be installed, which on a qualification host is a build from
# an earlier phase. It fails loudly when that build is missing a module and
# silently when it is not, and the silent case is a whole test suite passing
# against code nobody changed.
if importlib.util.find_spec("companion") is None:
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))

from companion.gtk_shell import CompanionViewModel  # noqa: E402
from companion.protocol import CompanionClient  # noqa: E402
from companion.service import CompanionService, ServiceOptions  # noqa: E402

REQUEST = "Count the words in this note and validate the count."


def resident_bytes() -> int | None:
    """This process's resident set, or ``None`` where it cannot be measured.

    ``None`` rather than a guess. ``sys.getsizeof`` sums Python objects and
    ``tracemalloc`` measures the allocator; neither is the number an operator
    cares about, and reporting one under the heading "idle memory" would be a
    measurement of something else wearing the right label.
    """
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, the BSDs and macOS report bytes.
        return peak * 1024 if sys.platform.startswith("linux") else peak
    except (ImportError, OSError):
        return None


def _timed(action: Callable[[], Any], repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "samples": len(samples),
        "firstMs": round(samples[0], 3),
        "medianMs": round(statistics.median(samples), 3),
        "meanMs": round(statistics.fmean(samples), 3),
        "maximumMs": round(max(samples), 3),
    }


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def measure(root: Path, *, tasks: int = 10, repeats: int = 20) -> dict[str, Any]:
    endpoint = root / "runtime" / "runtime.sock"
    report: dict[str, Any] = {
        "measurement": "companion-runtime-integration",
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "processors": os.cpu_count(),
            "residentMemoryMeasurable": resident_bytes() is not None,
        },
        "scope": (
            "this host only. No Raspberry Pi, ARM, 64 MiB full-system or GPU figure is "
            "produced here, and none may be inferred from these numbers."
        ),
        "gtkWidgets": (
            "not measured: the window needs a compositor. The client figures below are for "
            "CompanionViewModel, which is the whole of its behaviour and none of its widgets."
        ),
    }

    baseline = resident_bytes()
    service = CompanionService(ServiceOptions(
        root=root, endpoint=endpoint, machine="laptop", consent_wait_seconds=10.0,
    )).start()
    try:
        time.sleep(0.2)
        idle = resident_bytes()
        report["runtimeIdle"] = {
            "residentBytes": idle,
            "aboveInterpreterBaselineBytes": (idle - baseline) if idle and baseline else None,
            "detail": (
                "the runtime service in this process, idle, with no session"
                if idle else "resident memory is not measurable on this platform"
            ),
        }

        client = CompanionClient(endpoint, timeout=30.0)
        report["health"] = _timed(client.health, repeats)

        session_id = str(client.create_session("Measurement")["session"]["sessionId"])
        report["sessionCreation"] = _timed(
            lambda: client.create_session("Measurement"), min(repeats, 10)
        )

        submitted: list[str] = []
        store = root / "store"
        before_bytes = _directory_bytes(store)

        def _submit() -> None:
            submitted.append(str(client.submit_task(session_id, REQUEST)["task"]["taskId"]))

        report["taskSubmission"] = _timed(_submit, tasks)
        service.gateway.drain(timeout=120.0)
        task_id = submitted[-1]

        report["eventToUi"] = _timed(
            lambda: client.get_presentation_state(task_id), repeats
        )
        report["eventReplay"] = _timed(
            lambda: client.get_events(task_id, limit=500), repeats
        )

        model = CompanionViewModel(client=CompanionClient(endpoint, timeout=30.0))
        report["clientFirstConnect"] = _timed(
            lambda: CompanionViewModel(client=CompanionClient(endpoint, timeout=30.0)).connect(),
            min(repeats, 10),
        )
        model.connect()
        report["clientRefresh"] = _timed(model.refresh, repeats)

        events = len(client.get_events(task_id, limit=500)["events"])
        after_bytes = _directory_bytes(store)
        report["store"] = {
            "totalBytes": after_bytes,
            "tasks": len(client.list_tasks()["tasks"]),
            # The *delta* across a known number of tasks, not the whole store
            # divided by them. Dividing the total attributes the session and
            # store metadata to the tasks and overstates the growth — which for
            # a store that has to live on a 64 MB machine is the one figure it
            # is worth being careful about.
            "growthBytesForRun": after_bytes - before_bytes,
            "tasksInRun": tasks,
            "growthBytesPerTask": round((after_bytes - before_bytes) / max(1, tasks)),
            "eventsPerTask": events,
        }

        combined = resident_bytes()
        report["combinedIdle"] = {
            "residentBytes": combined,
            "detail": (
                "runtime and client in one process — the installed system runs them as two, "
                "so this is an upper bound on neither and a lower bound on the pair"
            ),
        }
    finally:
        stop_start = time.perf_counter()
        service.close()
        report["serviceStopMs"] = round((time.perf_counter() - stop_start) * 1000.0, 3)

    restart_start = time.perf_counter()
    restarted = CompanionService(ServiceOptions(
        root=root, endpoint=endpoint, machine="laptop", consent_wait_seconds=10.0,
    )).start()
    report["runtimeRestartMs"] = round((time.perf_counter() - restart_start) * 1000.0, 3)
    report["runtimeRestartIncludes"] = (
        "binding the endpoint, a full recovery pass over every session in the store, "
        "and starting the worker"
    )
    try:
        report["recoveredSessions"] = len(restarted.recovery.get("sessions", []))
    finally:
        restarted.close()

    from companion.voice import SystemVoice

    voice = SystemVoice()
    report["voice"] = {
        "available": voice.available,
        "voiceId": voice.voice_id,
        "processOverhead": (
            "one short-lived local process per utterance, not measured here because this "
            "host has no local synthesiser" if not voice.available
            else "one short-lived local process per utterance"
        ),
    }
    return report


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        tempfile.mkdtemp(prefix="bunny-companion-measure-")
    )
    report = measure(root)
    report["root"] = str(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

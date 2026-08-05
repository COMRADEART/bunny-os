#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeat a companion target and record what the process owns each time.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

The intermittent companion-suite failure had resisted diagnosis because it never
appeared in isolation — only inside the full in-process suite, and only
sometimes. That shape says the fault is *accumulated state in the interpreter*
rather than anything a single test does, so this harness measures exactly that:
what threads, file descriptors, sockets, temporary directories and runtime locks
exist before and after each iteration, and how those inventories trend.

It deliberately reports raw inventories rather than a verdict. A leak is a line
that goes up; a race is a failure with a flat inventory. Those need different
fixes, and a harness that printed "leak detected" would be guessing which.

Usage::

    companion_stress.py --target service --runs 100
    companion_stress.py --target suite --runs 50 --order random
    companion_stress.py --target slice --runs 20 --isolate
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

#: The service-driven subset — every module that starts a real runtime, binds a
#: socket or drives a slice. These are the tests the flake lives in; the other
#: ~350 are pure and have never failed.
SERVICE_MODULES = (
    "tests.companion.test_protocol_ipc",
    "tests.companion.test_integration_slice",
    "tests.companion.test_character_cli_vertical",
)

SUITE_MODULES = SERVICE_MODULES + (
    "tests.companion.test_approvals",
    "tests.companion.test_cli",
    "tests.companion.test_events_store",
    "tests.companion.test_executors_reviewers",
    "tests.companion.test_privacy_slice",
    "tests.companion.test_recovery_cancellation",
    "tests.companion.test_schemas",
    "tests.companion.test_sessions_tasks",
    "tests.companion.test_presentation_projection",
    "tests.companion.test_integration_authority",
    "tests.companion.test_voice_character",
    "tests.companion.test_migration_and_recovery",
    "tests.companion.test_character_adaptation",
    "tests.companion.test_character_image_boundary",
    "tests.companion.test_character_importer",
    "tests.companion.test_character_mapper",
    "tests.companion.test_character_package_validation",
    "tests.companion.test_character_renderers",
    "tests.companion.test_character_speech_position",
)


# --------------------------------------------------------------------------- #
# Inventories
# --------------------------------------------------------------------------- #


def thread_inventory() -> dict[str, Any]:
    """Every live thread, by name and daemon status.

    Named rather than counted. "Three threads leaked" is a number; "three
    threads called bunny-companion-worker leaked" is a diagnosis.
    """
    threads = sorted(
        (item.name, bool(item.daemon), item.is_alive())
        for item in threading.enumerate()
    )
    return {
        "count": len(threads),
        "nonDaemon": sum(1 for _name, daemon, _alive in threads if not daemon),
        "names": [name for name, _daemon, _alive in threads],
    }


def descriptor_inventory() -> dict[str, Any]:
    """Open file descriptors, split into sockets, files and anonymous.

    Reads ``/proc/self/fd``. Returns ``NOT_RUN`` where there is no ``/proc``,
    because an fd count guessed from Python objects would be a different
    measurement wearing the same label.
    """
    root = Path("/proc/self/fd")
    if not root.is_dir():
        return {"result": "NOT_RUN", "reason": "this platform has no /proc/self/fd"}
    sockets: list[str] = []
    files: list[str] = []
    other: list[str] = []
    total = 0
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        total += 1
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:"):
            sockets.append(target)
        elif target.startswith("/"):
            files.append(target)
        else:
            other.append(target)
    return {
        "total": total,
        "sockets": len(sockets),
        "files": len(files),
        "other": len(other),
        # Only the paths under a companion store or runtime directory: the rest
        # is the interpreter's own and is noise for this purpose.
        "companionFiles": sorted(
            item for item in files
            if "companion" in item or "bunny" in item
        )[:24],
    }


def socket_inventory() -> dict[str, Any]:
    """Listening and connected sockets belonging to this process.

    ``/proc/net/unix`` names the paths, which is what matters here: a leaked
    listener shows up as a path that should have been unlinked.
    """
    result: dict[str, Any] = {}
    unix = Path("/proc/net/unix")
    if unix.is_file():
        try:
            lines = unix.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        paths = [
            parts[-1] for parts in (line.split() for line in lines)
            if parts and parts[-1].startswith("/") and "bunny-companion" in parts[-1]
        ]
        result["unixCompanionPaths"] = sorted(set(paths))
        result["unixCompanionCount"] = len(paths)
    else:
        result["unix"] = "NOT_RUN: no /proc/net/unix"
    tcp = Path("/proc/net/tcp")
    if tcp.is_file():
        try:
            lines = tcp.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        # State 0A is LISTEN, 06 is TIME_WAIT — the two that matter for the
        # loopback fallback's port pressure.
        states = [line.split()[3] for line in lines if len(line.split()) > 3]
        result["tcpListen"] = states.count("0A")
        result["tcpTimeWait"] = states.count("06")
    else:
        result["tcp"] = "NOT_RUN: no /proc/net/tcp"
    return result


def runtime_inventory() -> dict[str, Any]:
    """Companion-owned state that should be empty between iterations."""
    import gc as _gc

    leases: list[str] = []
    waiters: list[str] = []
    services = 0
    runtimes = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "CompanionService":
            services += 1
        elif name == "CompanionRuntime":
            runtimes += 1
            try:
                leases.extend(getattr(item, "leases").leases)
            except Exception:
                pass
        elif name == "InteractiveConsent":
            try:
                waiters.extend(getattr(item, "_waiting", {}))
            except Exception:
                pass
    return {
        "liveServices": services,
        "liveRuntimes": runtimes,
        "executorLeases": sorted(leases),
        "consentWaiters": sorted(waiters),
    }


def memory_inventory() -> dict[str, Any]:
    """RSS from /proc, or NOT_RUN. Never a substitute measurement."""
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return {"rssBytes": int(line.split()[1]) * 1024}
    except OSError:
        pass
    return {"result": "NOT_RUN", "reason": "this platform has no /proc/self/status"}


def snapshot(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "threads": thread_inventory(),
        "descriptors": descriptor_inventory(),
        "sockets": socket_inventory(),
        "runtime": runtime_inventory(),
        "memory": memory_inventory(),
        "tempDirectories": len(list(Path(tempfile.gettempdir()).glob("bunny-*"))),
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def _get(value: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    result: dict[str, Any] = {}
    for name, path in (
        ("threads", ("threads", "count")),
        ("nonDaemonThreads", ("threads", "nonDaemon")),
        ("descriptors", ("descriptors", "total")),
        ("socketDescriptors", ("descriptors", "sockets")),
        ("unixCompanionSockets", ("sockets", "unixCompanionCount")),
        ("tcpListen", ("sockets", "tcpListen")),
        ("tcpTimeWait", ("sockets", "tcpTimeWait")),
        ("liveServices", ("runtime", "liveServices")),
        ("liveRuntimes", ("runtime", "liveRuntimes")),
        ("rssBytes", ("memory", "rssBytes")),
        ("tempDirectories", ("tempDirectories",)),
    ):
        start, end = _get(before, *path), _get(after, *path)
        if isinstance(start, int) and isinstance(end, int):
            result[name] = end - start
    result["executorLeases"] = _get(after, "runtime", "executorLeases") or []
    result["consentWaiters"] = _get(after, "runtime", "consentWaiters") or []
    return result


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #


def _run_modules(modules: tuple[str, ...], *, order: str, seed: int) -> dict[str, Any]:
    names = list(modules)
    if order == "random":
        random.Random(seed).shuffle(names)
    elif order == "reverse":
        names.reverse()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(loader.loadTestsFromName(name))
    stream = open(os.devnull, "w", encoding="utf-8")
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    finally:
        stream.close()
    return {
        "order": names,
        "ran": result.testsRun,
        "failures": [str(case) for case, _text in result.failures],
        "errors": [str(case) for case, _text in result.errors],
        "detail": [text for _case, text in (result.failures + result.errors)][:2],
        "ok": result.wasSuccessful(),
    }


def _run_slice() -> dict[str, Any]:
    from companion.character.vertical_slice import run_character_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-slice-") as directory:
        report = run_character_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": report["failures"],
        "notRun": report["notRun"],
        "ran": len(report["steps"]),
    }


def _run_integration_slice() -> dict[str, Any]:
    from companion.vertical_slice import run_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-int-") as directory:
        report = run_slice(Path(directory), speak=False).to_json()
    return {"ok": report["passed"], "failures": report["failures"], "ran": len(report["steps"])}


TARGETS = {
    "service": lambda order, seed: _run_modules(SERVICE_MODULES, order=order, seed=seed),
    "suite": lambda order, seed: _run_modules(SUITE_MODULES, order=order, seed=seed),
    "protocol": lambda order, seed: _run_modules(
        ("tests.companion.test_protocol_ipc",), order=order, seed=seed
    ),
    "slice": lambda order, seed: _run_slice(),
    "integration-slice": lambda order, seed: _run_integration_slice(),
}


def run_in_process(target: str, runs: int, *, order: str, verbose: bool) -> dict[str, Any]:
    iterations: list[dict[str, Any]] = []
    consecutive = 0
    best = 0
    first_failure: dict[str, Any] | None = None
    baseline = snapshot("baseline")
    for index in range(1, runs + 1):
        before = snapshot("before")
        started = time.monotonic()
        try:
            outcome = TARGETS[target](order, index)
        except Exception as exc:  # a harness fault is data, not a crash
            outcome = {"ok": False, "failures": [f"{type(exc).__name__}: {exc}"], "ran": 0}
        elapsed = time.monotonic() - started
        teardown_started = time.monotonic()
        gc.collect()
        teardown = time.monotonic() - teardown_started
        after = snapshot("after")
        record = {
            "iteration": index,
            "ok": bool(outcome.get("ok")),
            "seconds": round(elapsed, 3),
            "gcSeconds": round(teardown, 4),
            "ran": outcome.get("ran"),
            "failures": outcome.get("failures", []),
            "errors": outcome.get("errors", []),
            "pid": os.getpid(),
            "delta": _delta(before, after),
            "sinceBaseline": _delta(baseline, after),
        }
        if not record["ok"]:
            record["detail"] = outcome.get("detail", [])
            record["order"] = outcome.get("order")
            if first_failure is None:
                first_failure = record
            best = max(best, consecutive)
            consecutive = 0
        else:
            consecutive += 1
        iterations.append(record)
        if verbose:
            mark = "ok " if record["ok"] else "FAIL"
            print(
                f"  {index:4d} {mark} {record['seconds']:6.2f}s "
                f"threads{record['delta'].get('threads', 0):+d} "
                f"fd{record['delta'].get('descriptors', 0):+d} "
                f"rss{record['sinceBaseline'].get('rssBytes', 0) // 1024:+d}K",
                file=sys.stderr, flush=True,
            )
    best = max(best, consecutive)
    return {
        "target": target,
        "order": order,
        "mode": "in-process",
        "runs": runs,
        "passed": sum(1 for item in iterations if item["ok"]),
        "failed": sum(1 for item in iterations if not item["ok"]),
        "longestConsecutivePass": best,
        "finalConsecutivePass": consecutive,
        "firstFailure": first_failure,
        "iterations": iterations,
        "baseline": baseline,
        "final": snapshot("final"),
    }


def run_isolated(target: str, runs: int, *, order: str) -> dict[str, Any]:
    """One interpreter per iteration. The control for accumulated state."""
    iterations = []
    consecutive = best = 0
    for index in range(1, runs + 1):
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, __file__, "--target", target, "--runs", "1",
             "--order", order, "--json"],
            capture_output=True, text=True,
        )
        ok = completed.returncode == 0
        iterations.append({
            "iteration": index,
            "ok": ok,
            "seconds": round(time.monotonic() - started, 3),
            "stderr": completed.stderr[-400:] if not ok else "",
        })
        if ok:
            consecutive += 1
        else:
            best = max(best, consecutive)
            consecutive = 0
    best = max(best, consecutive)
    return {
        "target": target, "order": order, "mode": "process-isolated", "runs": runs,
        "passed": sum(1 for item in iterations if item["ok"]),
        "failed": sum(1 for item in iterations if not item["ok"]),
        "longestConsecutivePass": best,
        "iterations": iterations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), default="service")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--order", choices=("declared", "random", "reverse"), default="declared")
    parser.add_argument("--isolate", action="store_true", help="one interpreter per iteration")
    parser.add_argument("--json", action="store_true", help="print the report and nothing else")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    verbose = not args.json
    if verbose:
        print(
            f"stress: target={args.target} runs={args.runs} order={args.order} "
            f"mode={'isolated' if args.isolate else 'in-process'} pid={os.getpid()}",
            file=sys.stderr, flush=True,
        )
    report = (
        run_isolated(args.target, args.runs, order=args.order) if args.isolate
        else run_in_process(args.target, args.runs, order=args.order, verbose=verbose)
    )
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.json:
        print(encoded)
    elif verbose:
        print(
            f"stress: {report['passed']}/{report['runs']} passed, "
            f"longest consecutive {report['longestConsecutivePass']}",
            file=sys.stderr, flush=True,
        )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

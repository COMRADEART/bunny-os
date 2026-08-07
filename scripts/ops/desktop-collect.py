#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§23's verdicts and §24's measurements, computed on the Linux side.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

The rule the previous phases arrived at, sharpened once: a **growth** between
iterations is a failure and a **cleanup** is not. A negative delta means this
iteration tidied residue an earlier one left, and reporting that as a leak would
fail a clean run because a dirty one preceded it.

The sharpening is that the verdict is taken on the **net**, not on the sum of
the positive deltas. A thread that is *exiting* when a snapshot happens to be
taken counts as +1 in one iteration and −1 in the next; a positives-only sum
records growth of one for something that grew by nothing, and a fifty-run gate
fails for a scheduling coincidence. A genuine leak of one per iteration still
nets ninety-nine, so nothing real hides in the difference — and the gained and
released totals are reported separately, so a reader can see which it was rather
than take the verdict's word for it.

Two columns are this phase's own and neither is a delta.

``ledgerConsistent`` is a *property*: no entry is left in ``started`` while the
process that began it is still alive. A false here between iterations means an
attempt was begun and forgotten — the state §20 turns into ``unknown`` on the
next start-up, and one that should never exist in a living process.

``approvalsSpent`` is deliberately **not** absolute. A spent approval is the
record of a consent that was used, and clearing it between iterations would be
the replay guard forgetting what it is for. It is reported and never failed on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_GATES = "bunny-os/desktop-action-gates/1"
SCHEMA_MANIFEST = "bunny-os/desktop-action-evidence-manifest/1"
SCHEMA_ENVIRONMENT = "bunny-os/desktop-action-environment/1"
SCHEMA_MEASUREMENTS = "bunny-os/desktop-action-measurements/1"

#: Counters that must not grow between iterations. Each names something the
#: process *holds*: a thread it must join, a descriptor it must close, a
#: selection a child of ours owns, a bus connection, a portal handle.
_TRACKED = (
    "threads", "nonDaemonThreads", "descriptors", "socketDescriptors",
    "unixCompanionSockets", "tcpListen", "liveServices", "liveRuntimes",
    "tempDirectories", "childProcesses", "zombies",
    # This phase's own.
    "desktopChildren", "liveDesktopBrokers", "portalHandles",
    "clipboardOwners", "notificationsTracked", "dbusConnections",
)

#: Counters that must be zero between iterations whatever the baseline held.
_ABSOLUTE = (
    "queueDepth", "activeRequests", "pendingActions", "preparedActions",
    "startedActions",
)

#: List-valued absolutes: a lease, a waiter or an outstanding question between
#: iterations is wrong however it got there.
_ABSOLUTE_LISTS = (
    "executorLeases", "consentWaiters", "heldAnswers",
    "pendingApprovals", "activeExecutors", "lockedStores",
)


def _verdict(path: Path) -> dict[str, Any]:
    """One gate's answer: did anything grow, and did anything fail.

    **The first iteration is measured and does not fail the gate**, and the
    reason is a measured one rather than a convenience. A broker's first run
    opens a session-bus connection and maps the GObject typelib; the second run
    reuses both. So iteration 1 shows a few descriptors and a few megabytes, and
    every iteration after it shows zero. That is a warm-up, not a leak.

    A leak looks different and is what the remaining ninety-nine iterations are
    for: it grows *per iteration*, so it accumulates. Summing from iteration 2
    means a real leak of one descriptor per run still totals ninety-nine and
    still fails, while a one-off cost is reported under its own name instead of
    being counted ninety-nine times or, worse, quietly subtracted.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    iterations = list(document.get("iterations", ()))
    seconds = sorted(item.get("seconds", 0.0) for item in iterations)
    growth: dict[str, int] = {}
    cleanup: dict[str, int] = {}
    net: dict[str, int] = {}
    violations: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    ledger_inconsistent: list[int] = []
    postures: dict[str, int] = {}

    warm_up = {
        name: value
        for name, value in (iterations[0].get("delta", {}) if iterations else {}).items()
        if name in _TRACKED and isinstance(value, int) and value
    }

    for position, item in enumerate(iterations):
        delta = item.get("delta", {})
        # The iteration record is flat: `companion_stress.py` lifts the target's
        # outcome fields onto it rather than nesting them. Read them where they
        # are; an earlier version of this collector looked for a nested
        # ``outcome`` key, found none, and reported every iteration as passing.
        if not item.get("ok", True):
            failures.append({
                "iteration": item.get("iteration"),
                "failures": item.get("failures", []),
                "detail": item.get("detail", []),
            })
        posture = item.get("posture") or ""
        if posture:
            postures[posture] = postures.get(posture, 0) + 1
        if position:  # see the docstring: iteration 1 is the warm-up
            for name in _TRACKED:
                value = delta.get(name)
                if not isinstance(value, int):
                    continue
                net[name] = net.get(name, 0) + value
                if value > 0:
                    growth[name] = growth.get(name, 0) + value
                elif value < 0:
                    cleanup[name] = cleanup.get(name, 0) + value
        for name in _ABSOLUTE:
            value = delta.get(name)
            if isinstance(value, int) and value:
                violations.setdefault(name, []).append(
                    {"iteration": item.get("iteration"), "value": value}
                )
        for name in _ABSOLUTE_LISTS:
            value = delta.get(name)
            if value:
                violations.setdefault(name, []).append(
                    {"iteration": item.get("iteration"), "value": value}
                )
        if delta.get("ledgerConsistent") is False:
            ledger_inconsistent.append(item.get("iteration"))

    leaked = {name: value for name, value in net.items() if value > 0}
    transient = {
        name: {"gained": growth.get(name, 0), "released": cleanup.get(name, 0)}
        for name in sorted(set(growth) | set(cleanup))
        if net.get(name, 0) <= 0 and growth.get(name, 0) > 0
    }
    return {
        "file": path.name,
        "target": document.get("target"),
        "runs": document.get("runs"),
        "commit": document.get("commit"),
        "consecutive": document.get("consecutive", document.get("bestConsecutive")),
        "passed": (
            not leaked and not violations and not failures and not ledger_inconsistent
        ),
        # Iteration 1's own deltas, reported and not failed on. A bus connection
        # and a typelib, once.
        "firstIterationWarmUp": dict(sorted(warm_up.items())),
        # The **net** across iterations 2..N, which is what fails a gate.
        #
        # Summing only the positive deltas was the first rule and it fails a
        # clean run. A thread that is *exiting* when a snapshot is taken counts
        # as +1 in one iteration and −1 in the next; the positives-only sum
        # records growth of one for something that grew by nothing. A leak of
        # one thread per iteration still nets ninety-nine, so nothing real hides
        # here — and both halves are reported below, so a reader can see the
        # difference rather than take the verdict's word for it.
        "resourceGrowth": dict(sorted(leaked.items())),
        "gainedAcrossIterations": dict(sorted(growth.items())),
        "releasedAcrossIterations": dict(sorted(cleanup.items())),
        "transientOnly": transient,
        "absoluteViolations": violations,
        "ledgerInconsistentIterations": ledger_inconsistent,
        "failedIterations": failures,
        "postures": dict(sorted(postures.items())),
        "duration": _figures(seconds),
    }


def _figures(values: list[float]) -> dict[str, Any]:
    """Minimum, median, p95, maximum and count. §24's shape, everywhere."""
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "samples": len(ordered),
        "minimum": round(ordered[0], 6),
        "median": round(statistics.median(ordered), 6),
        "p95": round(ordered[index], 6),
        "maximum": round(ordered[-1], 6),
    }


def _measurements(path: Path) -> dict[str, Any]:
    """§24's latencies, gathered from every slice iteration in a gate file.

    Read from the *gate* rather than from a separate run: a latency measured
    once tells you what one run did, and a latency measured across twenty tells
    you what the thing does. The slice records each figure per iteration and
    this collects them.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    gathered: dict[str, list[float]] = {}
    for item in document.get("iterations", ()):
        for entry in item.get("measurements") or ():
            gathered.setdefault(str(entry.get("name")), []).append(float(entry.get("seconds", 0.0)))
    return {name: _figures(values) for name, values in sorted(gathered.items())}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    root: Path = args.evidence
    verdicts = [
        _verdict(root / name)
        for name in (
            "gate-desktop-100.json", "gate-suite-50.json", "gate-desktop-slice-20.json",
        )
        if (root / name).is_file()
    ]
    document = {
        "schemaVersion": SCHEMA_GATES,
        "commit": args.commit,
        "gates": verdicts,
        "allPassed": bool(verdicts) and all(item["passed"] for item in verdicts),
    }
    (root / "gate-verdicts.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    slice_path = root / "gate-desktop-slice-20.json"
    if slice_path.is_file():
        (root / "desktop-measurements.json").write_text(
            json.dumps({
                "schemaVersion": SCHEMA_MEASUREMENTS,
                "commit": args.commit,
                "source": slice_path.name,
                "latencies": _measurements(slice_path),
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "schemaVersion": SCHEMA_MANIFEST,
        "commit": args.commit,
        "files": [
            {"name": item.name, "bytes": item.stat().st_size, "sha256": _digest(item)}
            for item in sorted(root.iterdir())
            if item.is_file() and item.name != "manifest.json"
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    print(json.dumps({
        "allPassed": document["allPassed"],
        "gates": [
            {
                "file": item["file"], "passed": item["passed"],
                "consecutive": item["consecutive"], "runs": item["runs"],
                "growth": item["resourceGrowth"],
                "transientOnly": sorted(item["transientOnly"]),
                "violations": sorted(item["absoluteViolations"]),
                "failed": len(item["failedIterations"]),
            }
            for item in verdicts
        ],
    }, indent=2))
    return 0 if document["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

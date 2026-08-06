#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compute the §24 verdicts and the evidence manifest, on the Linux side.

The rule the previous phases arrived at, kept: a *growth* between iterations
is a failure and a *cleanup* is not. A negative delta means this run tidied up
residue an earlier one left in the shared temporary directory; reporting that
as a leak would make a clean run fail because a dirty one preceded it. So
positive deltas are collected as ``resourceGrowth`` and negative ones as
``cleanupOfPriorResidue``, and only the first can fail a gate.

``settledFixtures`` is the other half of that rule. The final snapshot is
taken while the harness's own fixtures are still alive — the suite target
leaves one service constructed by the module that ran last — so a final
delta of one live service is expected and is recorded as such rather than
silently subtracted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_GATES = "bunny-os/agent-provider-gates/1"
SCHEMA_MANIFEST = "bunny-os/agent-provider-evidence-manifest/1"
SCHEMA_ENVIRONMENT = "bunny-os/agent-provider-environment/1"

#: Counters that must not grow between iterations. Each names something this
#: process *holds*: a thread it must join, a descriptor it must close, an
#: object it must release, a child it must reap.
_TRACKED = (
    "threads", "nonDaemonThreads", "descriptors", "socketDescriptors",
    "unixCompanionSockets", "tcpListen", "liveServices",
    "liveRuntimes", "tempDirectories", "childProcesses", "zombies",
    "audioHandles", "temporaryWorkspaces", "liveVoiceWorkers",
    "liveVoiceServices", "captureChildren", "audioInputHandles",
    "temporarySpeechWorkspaces", "liveCaptureWorkers", "liveSpeechServices",
    "agentChildren", "liveAgentWorkers", "liveAgentServices", "httpConnections",
)

#: Kernel-side socket states, counted and reported separately because they are
#: not ours to release. A loopback TCP connection that we closed correctly
#: still occupies a ``TIME_WAIT`` entry in the kernel's table for 2×MSL — sixty
#: seconds on Linux — with no file descriptor attached to this process. The
#: agent gates open one connection per generation, so a hundred iterations
#: leave a few hundred TIME_WAIT entries behind and every one of them is the
#: protocol working. Counting them as growth would fail a gate for closing its
#: sockets; omitting them would hide a genuine socket leak. So they are
#: measured, reported, and named for what they are — and ``descriptors``,
#: ``socketDescriptors`` and ``httpConnections`` above are the columns that
#: would move if this process were really holding anything.
_KERNEL_SOCKET_STATES = ("tcpTimeWait",)

#: Counters that must be zero between iterations whatever the baseline held.
_ABSOLUTE = (
    "queueDepth", "activeRequests", "activeCaptures", "openRecognizerSessions",
    "bufferedBytes", "providerQueueDepth", "activeStreams",
)

#: List-valued absolutes: a lease, a waiter or a held answer between
#: iterations is wrong however it got there.
_ABSOLUTE_LISTS = (
    "executorLeases", "consentWaiters", "heldAnswers",
    "pendingApprovals", "activeExecutors", "lockedStores",
)


def _verdict(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    iterations = document.get("iterations", ())
    seconds = sorted(item.get("seconds", 0.0) for item in iterations)
    growth: dict[str, int] = {}
    cleanup: dict[str, int] = {}
    violations: dict[str, Any] = {}
    kernel_states: dict[str, int] = {}
    modes: set[str] = set()
    commits: set[str] = set()
    for item in iterations:
        commits.add(str(item.get("commit", "")))
        if item.get("mode"):
            modes.add(str(item["mode"]))
        delta = item.get("delta") or {}
        for name in _KERNEL_SOCKET_STATES:
            value = (item.get("sinceBaseline") or {}).get(name)
            if isinstance(value, int) and value > 0:
                kernel_states[name] = max(kernel_states.get(name, 0), value)
        for name in _TRACKED:
            value = delta.get(name)
            if not isinstance(value, int) or value == 0:
                continue
            if value > 0:
                growth[name] = max(growth.get(name, 0), value)
            else:
                cleanup[name] = min(cleanup.get(name, 0), value)
        for name in _ABSOLUTE:
            value = delta.get(name)
            if isinstance(value, int) and value:
                violations[name] = max(violations.get(name, 0), value)
        for name in _ABSOLUTE_LISTS:
            value = delta.get(name)
            if isinstance(value, list) and value:
                violations[name] = value
    final = document.get("final") or {}
    baseline = document.get("baseline") or {}
    settled: dict[str, int] = {}
    for section, keys in (
        ("threads", ("count",)),
        ("runtime", ("liveServices", "liveRuntimes")),
        ("agents", ("liveAgentWorkers", "liveAgentServices")),
        ("voice", ("liveVoiceWorkers", "liveVoiceServices")),
        ("speech", ("liveCaptureWorkers", "liveSpeechServices")),
    ):
        for key in keys:
            before = (baseline.get(section) or {}).get(key)
            after = (final.get(section) or {}).get(key)
            if isinstance(before, int) and isinstance(after, int) and after > before:
                settled[f"{section}.{key}" if key == "count" else key] = after - before
    rss_final = ((final.get("memory") or {}).get("rssBytes"))
    rss_base = ((baseline.get("memory") or {}).get("rssBytes"))
    return {
        "file": path.name,
        "target": document.get("target"),
        "commit": sorted(commits)[0] if len(commits) == 1 else sorted(commits),
        "singleCommit": len(commits) == 1,
        "runs": document.get("runs"),
        "passed": document.get("passed"),
        "failed": document.get("failed"),
        "gateMet": document.get("failed") == 0
        and document.get("longestConsecutivePass") == document.get("runs"),
        "longestConsecutivePass": document.get("longestConsecutivePass"),
        "secondsMedian": round(seconds[len(seconds) // 2], 3) if seconds else None,
        "secondsMax": round(seconds[-1], 3) if seconds else None,
        "secondsTotal": round(sum(seconds), 1) if seconds else None,
        "rssSinceBaselineFinalBytes": (rss_final - rss_base)
        if isinstance(rss_final, int) and isinstance(rss_base, int) else None,
        "resourceGrowth": growth,
        "cleanupOfPriorResidue": cleanup,
        "kernelSocketStatesSinceBaseline": kernel_states,
        "absoluteViolations": violations,
        "settledFixtures": settled,
        "modesObserved": sorted(modes),
        "firstFailure": document.get("firstFailure"),
    }


def _environment(worktree: Path) -> dict[str, Any]:
    def _run(*command: str) -> str:
        try:
            return subprocess.run(
                command, capture_output=True, text=True, timeout=20
            ).stdout.strip()
        except Exception:  # noqa: BLE001 - an absent tool is a recorded absence
            return ""

    return {
        "schema": SCHEMA_ENVIRONMENT,
        "distribution": _run("cat", "/etc/os-release").splitlines()[:3],
        "kernel": _run("uname", "-r"),
        "python": _run("python3", "--version"),
        "systemd": _run("systemctl", "--version").splitlines()[:1],
        "llamaServer": _run("sh", "-c", "ls -l /usr/bin/llama-server 2>/dev/null"),
        "llamaCli": _run("sh", "-c", "ls -l /usr/bin/llama-cli 2>/dev/null"),
        "ollama": _run("sh", "-c", "command -v ollama || echo absent"),
        "modelDirectory": _run(
            "sh", "-c",
            "ls -l ~/.local/share/bunny-os/agent-models 2>/dev/null"
        ),
        "serverProcess": _run("sh", "-c", "pgrep -a llama-server | head -1"),
        "serverHealth": _run(
            "sh", "-c", "curl -sf -m 3 http://127.0.0.1:8080/health || echo unreachable"
        ),
        "remoteProviderConfigured": False,
        "remoteCredentialPresent": False,
        "paidProviderUsed": False,
        "worktree": str(worktree),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("/home/bunny/agents-evidence"))
    parser.add_argument("--worktree", type=Path, default=Path("/home/bunny/agents-work"))
    parser.add_argument("--commit", required=True)
    arguments = parser.parse_args()
    evidence = arguments.evidence

    verdicts: dict[str, Any] = {}
    for name in ("gate-agents-100.json", "gate-suite-50.json", "gate-agent-slice-20.json"):
        path = evidence / name
        if path.exists():
            verdicts[name] = _verdict(path)
        else:
            verdicts[name] = {"file": name, "present": False,
                              "reason": "the gate produced no report"}

    gates = {
        "schema": SCHEMA_GATES,
        "allGatesMet": all(
            item.get("gateMet") and item.get("singleCommit") for item in verdicts.values()
        ),
        "gateCommit": arguments.commit,
        "verdicts": verdicts,
    }
    (evidence / "gate-verdicts.json").write_text(
        json.dumps(gates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (evidence / "env.json").write_text(
        json.dumps(_environment(arguments.worktree), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    files: dict[str, Any] = {}
    for path in sorted(evidence.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        files[path.name] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    (evidence / "manifest.json").write_text(
        json.dumps({
            "schema": SCHEMA_MANIFEST,
            "candidateCommit": arguments.commit,
            "files": files,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "allGatesMet": gates["allGatesMet"],
        "verdicts": {
            name: {
                "gateMet": item.get("gateMet"),
                "passed": item.get("passed"),
                "runs": item.get("runs"),
                "growth": item.get("resourceGrowth"),
                "absolutes": item.get("absoluteViolations"),
                "kernelSockets": item.get("kernelSocketStatesSinceBaseline"),
                "modes": item.get("modesObserved"),
            } for name, item in verdicts.items()
        },
        "manifestFiles": len(files),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

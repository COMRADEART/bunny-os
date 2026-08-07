#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§34's verdicts and §35's measurements, computed on the Linux side.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

The rule the earlier phases arrived at, applied unchanged: a **growth** between
iterations is a failure and a **cleanup** is not, and the verdict is taken on the
**net** rather than on the sum of the positive deltas. The first iteration is
measured and does not fail the gate — a renderer's first run compiles three
shader programs, maps the driver and decodes a texture, and the second run does
none of it. That is a warm-up, and a leak looks different: it grows per
iteration, so it accumulates, and summing from iteration 2 still catches one
GL object per run as ninety-nine.

Two columns are this phase's own and neither is a delta.

``glTableUnloaded`` is a *property*, and it is §30 in counter form: a run that
never selected a 3D presentation must leave
``companion.character.three_d.gl._LOADED`` at ``None``. A suite gate where it is
loaded has opened ``libGL`` for something that did not need it.

``leakSuspicions`` is the ledger's own report of a driver call that raised
during release. It is reported and failed on, because unlike a counter it names
the object that could not be given back.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_GATES = "bunny-os/renderer-3d-gates/1"
SCHEMA_MANIFEST = "bunny-os/renderer-3d-evidence-manifest/1"
SCHEMA_ENVIRONMENT = "bunny-os/renderer-3d-environment/1"
SCHEMA_MEASUREMENTS = "bunny-os/renderer-3d-measurements/1"

#: Counters that must not grow between iterations. Each names something the
#: process *holds*: a thread it must join, a descriptor it must close, a GPU
#: context it must destroy, a driver object it must delete.
_TRACKED = (
    "threads", "nonDaemonThreads", "descriptors", "socketDescriptors",
    "unixCompanionSockets", "liveServices", "liveRuntimes",
    "tempDirectories", "childProcesses", "zombies",
    # This phase's own.
    "gpuContexts", "liveGpuContexts", "renderers", "activeModels",
    "glObjects", "textures", "buffers", "vertexArrays", "shaderPrograms",
    "framebuffers", "animationTimers", "gtkGlAreas", "rendererWorkers",
)

#: Counters that must be zero between iterations whatever the baseline held.
_ABSOLUTE = ("queueDepth", "activeRequests", "pendingActions", "startedActions")

#: List-valued absolutes: something a runtime is still *holding*.
_ABSOLUTE_LISTS = (
    "executorLeases", "consentWaiters", "heldAnswers", "pendingApprovals", "lockedStores",
)

#: Reported and never failed on. See ``activeExecutors`` in desktop-collect.py:
#: it is a configured set on a live object, not held authority.
_REPORTED_LISTS = ("activeExecutors",)


def _verdict(path: Path) -> dict[str, Any]:
    """One gate's answer, read from the harness's own iteration schema.

    That schema is ``{iteration, ok, seconds, delta, sinceBaseline, ...}`` with
    the target's own result fields flattened alongside — there is no ``before``
    or ``after`` snapshot per iteration, only the two deltas and the run's
    ``baseline`` and ``final``. The first version of this collector read
    ``iteration["after"]["renderer3d"]`` and would have reported an empty
    ``leakSuspicions`` list and no ``glTable`` state for every gate, silently,
    in the direction that looks clean. It reads ``final`` for both now, which is
    where the end-of-run inventory actually lives.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    iterations = list(document.get("iterations", ()))
    seconds = sorted(item.get("seconds", 0.0) for item in iterations)
    growth: dict[str, int] = {}
    cleanup: dict[str, int] = {}
    net: dict[str, int] = {}
    violations: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    coverages: list[float] = []

    final = document.get("final", {})
    renderer_final = final.get("renderer3d", {}) if isinstance(final, dict) else {}
    leak_suspicions = list(renderer_final.get("leakSuspicions", ()))
    gl_table_loaded = bool(renderer_final.get("glTable", False))
    residual = {
        name: value for name, value in renderer_final.items()
        if isinstance(value, int) and not isinstance(value, bool) and value
    }

    warm_up = {
        name: value
        for name, value in (iterations[0].get("delta", {}) if iterations else {}).items()
        if isinstance(value, int) and not isinstance(value, bool) and value
    }

    for index, iteration in enumerate(iterations):
        if not iteration.get("ok", False):
            failures.append({
                "iteration": iteration.get("iteration", index + 1),
                "failures": iteration.get("failures", []),
                "notRun": iteration.get("notRun", []),
                "errors": iteration.get("errors", []),
            })
        if isinstance(iteration.get("coverage"), (int, float)):
            coverages.append(float(iteration["coverage"]))
        if index == 0:
            # Measured, and not counted. See the module docstring.
            continue
        delta = iteration.get("delta", {})
        for name in _TRACKED:
            value = delta.get(name)
            if not isinstance(value, int):
                continue
            net[name] = net.get(name, 0) + value
            if value > 0:
                growth[name] = growth.get(name, 0) + value
            elif value < 0:
                cleanup[name] = cleanup.get(name, 0) - value
        for name in _ABSOLUTE:
            value = delta.get(name)
            if isinstance(value, int) and value:
                violations.setdefault(name, 0)
                violations[name] += value
        for name in _ABSOLUTE_LISTS:
            value = delta.get(name)
            if isinstance(value, list) and value:
                violations.setdefault(name, [])
                violations[name] = sorted(set(violations[name]) | set(value))

    grew = {name: value for name, value in net.items() if value > 0}
    runs = int(document.get("runs", 0) or 0)
    passed = int(document.get("passed", 0) or 0)
    baseline_rss = (document.get("baseline", {}) or {}).get("memory", {}).get("rssBytes")
    final_rss = (final or {}).get("memory", {}).get("rssBytes")
    return {
        "target": document.get("target"),
        "runs": runs,
        "passed": passed,
        "commit": (iterations[0].get("commit") if iterations else document.get("commit")),
        "longestConsecutive": document.get("longestConsecutivePass"),
        "finalConsecutive": document.get("finalConsecutivePass"),
        "allPassed": (
            runs > 0 and passed == runs
            and int(document.get("longestConsecutivePass", 0) or 0) == runs
            and not grew and not violations and not failures and not leak_suspicions
            and not residual
        ),
        "iterationsMeasured": len(iterations),
        "warmUp": warm_up,
        "netGrowth": grew,
        "gainedTotals": growth,
        "releasedTotals": cleanup,
        "absoluteViolations": violations,
        "leakSuspicions": sorted(set(leak_suspicions)),
        # §30 in counter form. ``true`` is correct for a gate that drew in 3D
        # and wrong for one that never selected a 3D presentation; the reader
        # needs the value rather than a verdict, because which is right depends
        # on the gate.
        "glTableLoadedAtEnd": gl_table_loaded,
        "residualThreeDObjects": residual,
        "failedIterations": failures,
        "rss": {
            "baselineBytes": baseline_rss,
            "finalBytes": final_rss,
            "growthBytes": (
                final_rss - baseline_rss
                if isinstance(final_rss, int) and isinstance(baseline_rss, int) else None
            ),
        },
        "coverage": {
            "minimum": min(coverages) if coverages else None,
            "maximum": max(coverages) if coverages else None,
            "mean": round(statistics.fmean(coverages), 6) if coverages else None,
        },
        "seconds": {
            "minimum": round(seconds[0], 4) if seconds else None,
            "median": round(statistics.median(seconds), 4) if seconds else None,
            "maximum": round(seconds[-1], 4) if seconds else None,
            "total": round(sum(seconds), 4) if seconds else None,
        },
    }


def _measurements(path: Path) -> dict[str, Any]:
    """§35's figures, gathered from the slice gate's per-iteration reports."""
    document = json.loads(path.read_text(encoding="utf-8"))
    columns: dict[str, list[float]] = {}
    for iteration in document.get("iterations", ()):
        for name, value in (iteration.get("measurements", {}) or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                columns.setdefault(name, []).append(float(value))
    summary: dict[str, Any] = {}
    for name, values in sorted(columns.items()):
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
        summary[name] = {
            "samples": len(ordered),
            "minimum": round(ordered[0], 4),
            "median": round(statistics.median(ordered), 4),
            "p95": round(ordered[index], 4),
            "maximum": round(ordered[-1], 4),
        }
    return {"schema": SCHEMA_MEASUREMENTS, "columns": summary}


def _environment() -> dict[str, Any]:
    def _run(*command: str) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    graphics: dict[str, Any] = {"result": "NOT_RUN", "reason": "no context was created"}
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from companion.character.three_d.context import SurfacelessContext, offscreen_available
        from companion.character.three_d.diagnostics import three_d_environment

        available, reason = offscreen_available()
        graphics = {"offscreenAvailable": available, "reason": reason, **three_d_environment()}
        if available:
            context = SurfacelessContext()
            try:
                graphics["context"] = context.info().to_json()
            finally:
                context.release()
    except Exception as exc:  # noqa: BLE001 - an environment probe reports rather than fails
        graphics = {"result": "NOT_RUN", "reason": f"{type(exc).__name__}: {exc}"}

    return {
        "schema": SCHEMA_ENVIRONMENT,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "kernel": _run("uname", "-r"),
        "distribution": _run("sh", "-c", "grep PRETTY_NAME /etc/os-release | cut -d= -f2-"),
        "mesa": _run("sh", "-c", "rpm -q mesa-libGL mesa-libEGL mesa-dri-drivers 2>/dev/null"),
        "gtk": _run("sh", "-c", "rpm -q gtk4 python3-gobject 2>/dev/null"),
        "user": _run("id", "-un"),
        "sessionType": _run("sh", "-c", "printf %s \"$XDG_SESSION_TYPE\""),
        "waylandDisplay": _run("sh", "-c", "printf %s \"$WAYLAND_DISPLAY\""),
        "graphics": graphics,
        "note": (
            "A renderer string containing llvmpipe is Mesa's software rasteriser. "
            "Every frame-time figure taken on such a host is a software-rasteriser "
            "figure and means something different from a GPU one."
        ),
    }


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--gate", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--slice-gate", type=Path, default=None)
    parser.add_argument("--commit", default="")
    arguments = parser.parse_args()

    evidence: Path = arguments.evidence
    evidence.mkdir(parents=True, exist_ok=True)

    verdicts: dict[str, Any] = {"schema": SCHEMA_GATES, "commit": arguments.commit, "gates": {}}
    for entry in arguments.gate:
        name, _, raw = entry.partition("=")
        path = Path(raw)
        if not path.is_file():
            verdicts["gates"][name] = {"result": "NOT_RUN", "reason": f"{path} does not exist"}
            continue
        verdicts["gates"][name] = _verdict(path)
    verdicts["allPassed"] = all(
        item.get("allPassed") is True for item in verdicts["gates"].values()
    )
    (evidence / "gate-verdicts.json").write_text(
        json.dumps(verdicts, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    if arguments.slice_gate is not None and arguments.slice_gate.is_file():
        (evidence / "renderer3d-measurements.json").write_text(
            json.dumps(_measurements(arguments.slice_gate), indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )

    (evidence / "env.json").write_text(
        json.dumps(_environment(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "commit": arguments.commit,
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": _digest(path)}
            for path in sorted(evidence.iterdir())
            if path.is_file() and path.name != "manifest.json"
        },
    }
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"allPassed": verdicts["allPassed"], "gates": list(verdicts["gates"])}))
    return 0 if verdicts["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure what the capability control plane actually costs, under real limits.

The 64 MB target has been arithmetic until now: the declared essential floor is
28 MiB, the simulated device budgets 40 MiB allocatable, and the plan says five
services start. None of that is a measurement of anything, and
``KNOWN_LIMITATIONS.md`` has said so.

This measures. Each configuration runs the supervisor inside a
``systemd-run --scope`` with a kernel-enforced ``MemoryMax``, and every figure
comes from the cgroup the process was actually in:

* ``memory.peak``    — the high-water mark, which is what decides whether a
                       limit is survivable
* ``memory.current`` — steady state at exit
* ``memory.events``  — ``max`` and ``oom`` counters, the only trustworthy
                       statement that a limit was reached
* RSS and PSS        — from ``/proc/self/smaps_rollup``, for attribution

A configuration that OOMs is a result, not a failure of the exercise. The
classification at the end is derived from the numbers, not chosen.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

#: The limits §16 requires. 64 MiB is the target; the rest bracket it so that a
#: failure at 64 can be attributed rather than merely reported.
DEFAULT_LIMITS_MIB = (64, 128, 256, 512)

MIB = 1024 ** 2


def read_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return None if raw == "max" else int(raw)


def read_events(path: Path) -> dict[str, int]:
    try:
        raw = path.read_text(encoding="ascii")
    except OSError:
        return {}
    result: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            result[parts[0]] = int(parts[1])
    return result


def baseline() -> dict[str, object]:
    """What the machine costs before any Bunny process exists."""
    result: dict[str, object] = {}
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="ascii")
        for line in meminfo.splitlines():
            key, _, value = line.partition(":")
            if key in ("MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree"):
                result[key] = int(value.split()[0]) * 1024
    except OSError:
        pass
    try:
        result["processCount"] = len([
            item for item in Path("/proc").iterdir() if item.name.isdigit()
        ])
    except OSError:
        pass
    return result


#: Run inside the scope. Reports its own cost at each named phase, then the
#: cgroup figures for the whole run. Written as a string so the measured process
#: is a fresh interpreter with nothing of this script's imports resident.
_PROBE = r'''
import json, os, sys, time
# Installed layout first, so a run inside the artifact measures the installed
# package. Without this the probe injected the script's own parent directory,
# which inside the image is /opt — and the measurement reported "cannot run at
# this limit" for a missing import rather than for memory.
for _candidate in ("/usr/lib/bunny-os/python", {root!r}):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

def smaps():
    out = {{}}
    try:
        for line in open("/proc/self/smaps_rollup", encoding="ascii"):
            key, _, value = line.partition(":")
            if key in ("Rss", "Pss"):
                out[key] = int(value.split()[0]) * 1024
    except OSError:
        pass
    return out

def cgroup_dir():
    try:
        for line in open("/proc/self/cgroup", encoding="ascii"):
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                return "/sys/fs/cgroup" + parts[2].strip()
    except OSError:
        pass
    return None

def cg(name):
    d = cgroup_dir()
    if not d:
        return None
    try:
        raw = open(os.path.join(d, name), encoding="ascii").read().strip()
    except OSError:
        return None
    return None if raw == "max" else raw

phases = []
def phase(label):
    phases.append({{
        "phase": label,
        "atMonotonic": round(time.monotonic(), 4),
        "smaps": smaps(),
        "memoryCurrent": cg("memory.current"),
        "memoryPeak": cg("memory.peak"),
    }})

phase("interpreter-started")

from capability.supervisor import Supervisor, SupervisorConfig
phase("modules-imported")

import tempfile, pathlib
work = pathlib.Path(tempfile.mkdtemp(prefix="cap-measure-"))
config = SupervisorConfig(
    mode={mode!r},
    interval_seconds=1.0,
    state_directory=work / "state",
    runtime_directory=work / "run",
    audit_path=work / "audit.jsonl",
    service_directory=(
        pathlib.Path("/usr/share/bunny-os/capability/services")
        if os.path.isdir("/usr/share/bunny-os/capability/services")
        else pathlib.Path({root!r}) / "capability/services"
    ),
    maximum_cycles={cycles},
    constrained_monitoring=True,
    discovery_budget_ms=1500,
)
sup = Supervisor(config=config)
try:
    sup.prepare()
    phase("supervisor-prepared")
    for index in range({cycles}):
        sup.cycle()
        phase("cycle-%d" % (index + 1))
finally:
    try:
        sup.shutdown()
    except Exception:
        pass
phase("idle-after-cycles")

last = sup.history[-1] if sup.history else None
print("BUNNY-MEASUREMENT " + json.dumps({{
    "phases": phases,
    "cycles": sup.cycles,
    "cgroup": cgroup_dir(),
    "memoryCurrent": cg("memory.current"),
    "memoryPeak": cg("memory.peak"),
    "memoryEvents": cg("memory.events"),
    "planId": last.plan_id if last else None,
    "transitions": len(last.report.applied) if last and last.report else 0,
    "blocked": len(last.report.blocked) if last and last.report else 0,
    "problems": list(last.problems) if last else [],
    "warnings": sup.warnings,
}}))
'''


def measure(limit_mib: int, *, mode: str, cycles: int, swap: bool) -> dict[str, object]:
    """One configuration, inside a kernel-enforced memory limit."""
    scope = f"bunny-cap-measure-{limit_mib}-{os.getpid()}"
    program = _PROBE.format(root=str(ROOT), mode=mode, cycles=cycles)

    argv = [
        "systemd-run", "--scope", "--quiet", "--collect",
        f"--unit={scope}",
        f"--property=MemoryMax={limit_mib * MIB}",
        f"--property=MemorySwapMax={'infinity' if swap else 0}",
        "--property=MemoryAccounting=yes",
        "--property=TasksAccounting=yes",
        "/usr/bin/python3", "-c", program,
    ]

    started = time.monotonic()
    completed = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=300)
    duration = time.monotonic() - started

    payload: dict[str, object] = {}
    for line in (completed.stdout or "").splitlines():
        if line.startswith("BUNNY-MEASUREMENT "):
            try:
                payload = json.loads(line[len("BUNNY-MEASUREMENT "):])
            except json.JSONDecodeError:
                pass

    stderr = (completed.stderr or "")[-2000:]
    killed = completed.returncode in (-9, 137) or "Killed" in stderr or "oom" in stderr.lower()
    events = payload.get("memoryEvents") or ""
    oom_count = 0
    max_count = 0
    if isinstance(events, str):
        for line in events.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                if parts[0] == "oom":
                    oom_count = int(parts[1])
                elif parts[0] == "max":
                    max_count = int(parts[1])

    peak = payload.get("memoryPeak")
    peak_bytes = int(peak) if isinstance(peak, str) and peak.isdigit() else None

    return {
        "limitMib": limit_mib,
        "mode": mode,
        "swapPermitted": swap,
        "exitCode": completed.returncode,
        "durationSeconds": round(duration, 3),
        "booted": completed.returncode == 0 and bool(payload),
        "oomKilled": killed or oom_count > 0,
        "oomEvents": oom_count,
        "limitReachedEvents": max_count,
        "peakBytes": peak_bytes,
        "peakMib": round(peak_bytes / MIB, 2) if peak_bytes else None,
        "headroomMib": round((limit_mib * MIB - peak_bytes) / MIB, 2) if peak_bytes else None,
        "measurement": payload,
        "importFailed": "ModuleNotFoundError" in stderr or "ImportError" in stderr,
        "stderrTail": stderr if completed.returncode != 0 else "",
    }


def classify(results: list[dict[str, object]], target_mib: int = 64) -> dict[str, object]:
    """Classify **the control plane's** cost. Not the whole §17 gate.

    This is worth being pedantic about, because the pedantry is the difference
    between a measurement and a claim. What runs inside the scope is a Python
    interpreter running the supervisor. What §17 asks about is a *booted system*:
    a kernel, an init, a service manager, whatever base userspace the image
    carries, and then this. The second is strictly larger than the first and is
    not measured here.

    So the verdict returned has two parts. ``componentResult`` is a real A/B/C
    over the thing that was measured. ``systemResult`` is ``NOT_MEASURED``,
    unconditionally, until something boots a Bunny OS image under the limit and
    reports back. Reporting the first as though it were the second is exactly
    the substitution the brief forbids.
    """
    at_target = next((item for item in results if item["limitMib"] == target_mib), None)
    if at_target is None:
        return {
            "componentResult": "NOT_MEASURED",
            "systemResult": "NOT_MEASURED",
            "detail": f"no run at {target_mib} MiB",
        }

    unmeasured = {
        "systemResult": "NOT_MEASURED",
        "systemDetail": (
            "no Bunny OS image has been booted under this limit. This run measured a Python "
            "interpreter running the supervisor inside a cgroup; a booted system additionally "
            "carries a kernel, an init, a service manager and the base userspace, none of which "
            "is included above. The §17 gate is unresolved until an image is booted and measured."
        ),
    }
    if not at_target["booted"] and not at_target["oomKilled"] and at_target.get("importFailed"):
        return {
            **unmeasured,
            "componentResult": "NOT_MEASURED",
            "headline": "The run did not start",
            "detail": (
                "the measured process failed before allocating anything, so nothing about "
                "memory was established. Reporting this as a limit failure would be a "
                "harness bug wearing a measurement's clothes."
            ),
        }
    if not at_target["booted"] or at_target["oomKilled"]:
        return {
            **unmeasured,
            "componentResult": "C",
            "headline": "Cannot run the control plane at this limit",
            "detail": (
                f"the supervisor did not complete a cycle inside {target_mib} MiB: "
                f"exit {at_target['exitCode']}, oomEvents={at_target['oomEvents']}"
            ),
        }

    peak = at_target["peakMib"]
    headroom = at_target["headroomMib"]
    reached = at_target["limitReachedEvents"]
    if reached and reached > 0:
        return {
            **unmeasured,
            "componentResult": "B",
            "headline": "Runs, but not safely, at this limit",
            "detail": (
                f"the run completed but hit its ceiling {reached} time(s); peak {peak} MiB "
                f"of {target_mib} MiB. Continuous reclaim is not a safe operating point."
            ),
        }
    if headroom is not None and headroom < 8:
        return {
            **unmeasured,
            "componentResult": "B",
            "headline": "Runs, but not safely, at this limit",
            "detail": (
                f"peak {peak} MiB leaves only {headroom} MiB of headroom inside {target_mib} MiB, "
                "which the protected reserve alone would consume"
            ),
        }
    return {
        **unmeasured,
        "componentResult": "A",
        "headline": "The control plane alone fits at this limit",
        "detail": (
            f"peak {peak} MiB inside {target_mib} MiB, {headroom} MiB headroom, no reclaim "
            "events. This is the supervisor process only."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limits", type=int, nargs="+", default=list(DEFAULT_LIMITS_MIB))
    parser.add_argument("--mode", default="observe", choices=("observe", "dry-run", "apply"))
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--swap", action="store_true", help="permit swap (the target assumes none)")
    parser.add_argument("--output", type=Path, default=Path("/root/capability-evidence/memory.json"))
    args = parser.parse_args()

    if shutil.which("systemd-run") is None:
        print("BLOCKED: systemd-run is absent; no kernel-enforced limit can be applied", file=sys.stderr)
        return 2
    if Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        controllers = Path("/sys/fs/cgroup/cgroup.controllers").read_text(encoding="ascii").split()
        if "memory" not in controllers:
            print("BLOCKED: the memory controller is not available", file=sys.stderr)
            return 2
    else:
        print("BLOCKED: this is not a cgroup v2 hierarchy", file=sys.stderr)
        return 2

    environment = {
        "kernel": os.uname().release,
        "architecture": os.uname().machine,
        "python": sys.version.split()[0],
        "baseline": baseline(),
        "swapPermitted": args.swap,
        "mode": args.mode,
        "cyclesPerRun": args.cycles,
        "emulated": False,
        "virtualisation": subprocess.run(
            ["systemd-detect-virt"], capture_output=True, text=True, check=False,
        ).stdout.strip() or "none",
    }

    print(f"kernel {environment['kernel']} on {environment['architecture']}, "
          f"virtualisation={environment['virtualisation']}")
    print(f"mode={args.mode} cycles={args.cycles} swap={'permitted' if args.swap else 'disabled'}\n")

    results: list[dict[str, object]] = []
    for limit in sorted(args.limits):
        print(f"--- {limit} MiB ---", flush=True)
        try:
            result = measure(limit, mode=args.mode, cycles=args.cycles, swap=args.swap)
        except subprocess.TimeoutExpired:
            result = {
                "limitMib": limit, "mode": args.mode, "swapPermitted": args.swap,
                "exitCode": -1, "booted": False, "oomKilled": False, "oomEvents": 0,
                "limitReachedEvents": 0, "peakBytes": None, "peakMib": None,
                "headroomMib": None, "measurement": {},
                "stderrTail": "the run exceeded its 300s deadline",
            }
        results.append(result)
        status = "ok" if result["booted"] and not result["oomKilled"] else "FAILED"
        print(f"  {status}: exit={result['exitCode']} peak={result['peakMib']} MiB "
              f"headroom={result['headroomMib']} MiB oom={result['oomEvents']} "
              f"reclaim={result['limitReachedEvents']}")
        if result["stderrTail"]:
            print(f"  stderr: {result['stderrTail'][-300:]}")

    verdict = classify(results)
    document = {
        "schemaVersion": 1,
        "environment": environment,
        "results": results,
        "classification": verdict,
        "note": (
            "Every figure comes from the cgroup the measured process was actually in. "
            "This measures the capability control plane under a kernel-enforced limit; "
            "it is not a measurement of a booted Bunny OS image, whose kernel and base "
            "userspace are additional and are not included here."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\n=== 64 MB gate ===")
    print(f"  control plane : Result {verdict['componentResult']} - {verdict.get('headline', '')}")
    print(f"                  {verdict.get('detail', '')}")
    print(f"  booted system : {verdict['systemResult']}")
    print(f"                  {verdict['systemDetail']}")
    print(f"\nevidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

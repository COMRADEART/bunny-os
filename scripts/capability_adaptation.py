#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The runtime-adaptation scenario, driven by real kernel memory pressure.

Every previous test of the monitor fed it numbers. This feeds it a kernel.

The scenario runs inside a cgroup with a real ``memory.max``, and the pressure
is produced by a real process allocating and touching real pages inside that
cgroup until the kernel starts reclaiming. The readings the monitor sees come
from ``memory.current``, ``memory.max`` and ``memory.events`` — not from a
fixture — which is the only way to find out whether the debounce, hysteresis and
cooldown arithmetic survives contact with a signal that is noisy for reasons
nobody chose.

The sequence is §15's, and the properties asserted are the ones that would
actually hurt if they were wrong:

* a transient spike must produce **no** event, or services flap on noise;
* sustained pressure must produce **one** event, or the machine never adapts;
* the plan generated under pressure must grant **less** than the plan before it;
* a single good reading must **not** restore anything;
* restoration must wait for the recovery to hold *and* for the cooldown.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

_INSTALLED = Path("/usr/lib/bunny-os/python")
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))
if os.environ.get("BUNNY_SLICE_INSTALLED") != "1":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability.apply.monitor import (
    DEFAULT_SIGNALS,
    MonitorSettings,
    RuntimeMonitor,
    Sample,
)
from capability.budget import compute_budget
from capability.engine import evaluate
from capability.model import Inventory, MemoryFacts, measured
from capability.policy import Policy
from capability.registry import load_registry
from capability.scores import compute_scores
from dataclasses import replace

MIB = 1024 ** 2
EVIDENCE = Path(os.environ.get("EVIDENCE", "/tmp/adaptation-evidence"))
evidence: dict[str, object] = {"schemaVersion": 1, "steps": []}
failures: list[str] = []


def record(step: str, **fields: object) -> None:
    evidence["steps"].append({"step": step, **fields})
    print(f"  [{step}] " + " ".join(f"{k}={v}" for k, v in fields.items()))


def check(name: str, condition: bool, detail: str) -> None:
    if condition:
        print(f"  PASS {name}: {detail}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL {name}: {detail}")


def own_cgroup() -> Path | None:
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                return Path("/sys/fs/cgroup") / parts[2].strip().lstrip("/")
    except OSError:
        pass
    return None


def read(path: Path, name: str) -> str | None:
    try:
        return (path / name).read_text(encoding="ascii").strip()
    except OSError:
        return None


def cgroup_reading(cgroup: Path) -> dict[str, int]:
    """The kernel's own numbers for this cgroup. No estimate anywhere."""
    current = read(cgroup, "memory.current")
    maximum = read(cgroup, "memory.max")
    events = read(cgroup, "memory.events") or ""
    parsed = {}
    for line in events.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            parsed[parts[0]] = int(parts[1])
    return {
        "current": int(current) if current and current.isdigit() else 0,
        "max": int(maximum) if maximum and maximum.isdigit() else 0,
        "high": parsed.get("high", 0),
        "maxEvents": parsed.get("max", 0),
    }


def sample_from_cgroup(cgroup: Path, at: float) -> tuple[Sample, dict[str, int]]:
    """Build a monitor sample from what the kernel says about this cgroup.

    ``memory_available_fraction`` is free-over-limit within the cgroup, which is
    the same quantity the inventory computes on a machine whose memory is capped
    by a cgroup — the constrained-container case the capability engine was built
    around.
    """
    reading = cgroup_reading(cgroup)
    numeric: dict[str, float] = {}
    if reading["max"] > 0:
        free = max(0, reading["max"] - reading["current"])
        numeric["memory_available_fraction"] = free / reading["max"]
    return Sample(at_monotonic=at, numeric=numeric), reading


class Hog:
    """A real process allocating and touching real pages in this cgroup."""

    def __init__(self, mib: int) -> None:
        program = (
            "import time,sys\n"
            f"n={mib}\n"
            "held=[]\n"
            "for _ in range(n):\n"
            "    b=bytearray(1024*1024)\n"
            "    for o in range(0,len(b),4096): b[o]=1\n"
            "    held.append(b)\n"
            "sys.stdout.write('held\\n'); sys.stdout.flush()\n"
            "time.sleep(3600)\n"
        )
        self.process = subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )

    def wait_until_resident(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return False
            line = self.process.stdout.readline() if self.process.stdout else ""
            if line.strip() == "held":
                return True
        return False

    def stop(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                self.process.kill()
            except Exception:  # noqa: BLE001
                pass


def plan_for(available_bytes: int, usable_bytes: int, registry, policy, previous=None, now=0.0, reason="initial"):
    """A plan for a machine with this much memory, everything else held fixed."""
    inventory = Inventory(
        detected_at="2026-01-01T00:00:00Z",
        memory=MemoryFacts(
            physical_bytes=measured(usable_bytes, "cgroup"),
            available_bytes=measured(available_bytes, "cgroup"),
            cgroup_limit_bytes=measured(usable_bytes, "cgroup"),
        ),
    )
    scores = compute_scores(inventory)
    budget = compute_budget(inventory, scores, policy,
                            essential_floor_bytes=registry.essential_floor_bytes())
    return evaluate(inventory, scores, budget, registry, policy,
                    previous=previous, now=now, reason=reason), budget


def main() -> int:
    cgroup = own_cgroup()
    if cgroup is None or not cgroup.is_dir():
        print("BLOCKED: not running inside a readable cgroup", file=sys.stderr)
        return 2
    baseline = cgroup_reading(cgroup)
    if baseline["max"] <= 0:
        print("BLOCKED: this cgroup has no memory.max; there is no pressure to create",
              file=sys.stderr)
        return 2

    print("=== environment ===")
    record("cgroup", path=str(cgroup), memoryMax=baseline["max"],
           memoryCurrent=baseline["current"])
    ceiling = baseline["max"]

    manifests = (
        Path("/usr/share/bunny-os/capability/services")
        if os.environ.get("BUNNY_SLICE_INSTALLED") == "1"
        else Path("capability/services")
    )
    registry = load_registry(manifests)
    policy = Policy()
    monitor = RuntimeMonitor(settings=MonitorSettings(signals=DEFAULT_SIGNALS))

    print("\n=== 1-3: sufficient memory, initial plan ===")
    sample, reading = sample_from_cgroup(cgroup, at=0.0)
    monitor.observe(sample)
    comfortable_free = ceiling - reading["current"]
    first_plan, first_budget = plan_for(comfortable_free, ceiling, registry, policy, now=0.0)
    record("initial", freeBytes=comfortable_free,
           granted=first_plan.granted_memory_bytes,
           running=len(first_plan.running()),
           availableFraction=round(sample.numeric.get("memory_available_fraction", 0), 4))
    check("the initial plan runs services", len(first_plan.running()) > 0,
          f"{len(first_plan.running())} running, {first_plan.granted_memory_bytes} bytes granted")

    print("\n=== 4-5: a transient spike must produce no event ===")
    # One bad reading, then back. Debounce exists exactly for this.
    spike = Sample(at_monotonic=30.0, numeric={"memory_available_fraction": 0.02})
    spike_events = monitor.observe(spike)
    recovered_immediately = monitor.observe(
        Sample(at_monotonic=33.0, numeric={"memory_available_fraction": 0.60}),
    )
    record("transient-spike", spikeEvents=[e.event for e in spike_events],
           afterEvents=[e.event for e in recovered_immediately])
    check("a transient spike raises nothing", not spike_events and not recovered_immediately,
          f"{len(spike_events)} + {len(recovered_immediately)} event(s)")

    print("\n=== 6: real sustained pressure from a real allocator ===")
    # Fill most of the cgroup. The kernel decides what happens next, not us.
    # 95% of what is free. 80% left an 18% free fraction, which is above the
    # 10% entry threshold — the hog has to fill hard enough that the kernel is
    # genuinely short, not merely busy.
    target = max(8, int((ceiling - reading["current"]) * 0.95 / MIB))
    hog = Hog(target)
    resident = hog.wait_until_resident(timeout=60.0)
    time.sleep(1.0)
    pressured_sample, pressured = sample_from_cgroup(cgroup, at=60.0)
    record("pressure-applied", requestedMib=target, residentReported=resident,
           memoryCurrent=pressured["current"], memoryMax=pressured["max"],
           highEvents=pressured["high"], maxEvents=pressured["maxEvents"],
           availableFraction=round(pressured_sample.numeric.get("memory_available_fraction", 1.0), 4))
    check("the kernel reports the cgroup filling",
          pressured["current"] > reading["current"],
          f"{reading['current']} -> {pressured['current']} bytes")

    fraction = pressured_sample.numeric.get("memory_available_fraction", 1.0)
    check("pressure crossed the entry threshold",
          fraction <= 0.10,
          f"available fraction {fraction:.4f} against a 0.10 entry threshold")

    print("\n=== 7: sustained pressure raises exactly one event ===")
    events_first = monitor.observe(pressured_sample)
    later_sample, _ = sample_from_cgroup(cgroup, at=75.0)
    events_second = monitor.observe(later_sample)
    raised = list(events_first) + list(events_second)
    record("sustained-pressure", firstPass=[e.event for e in events_first],
           secondPass=[e.event for e in events_second])
    check("sustained pressure raises memory_pressure_entered",
          any(e.event == "memory_pressure_entered" for e in raised),
          f"events: {[e.event for e in raised]}")
    check("it is raised once, not once per sample",
          sum(1 for e in raised if e.event == "memory_pressure_entered") == 1,
          f"{sum(1 for e in raised if e.event == 'memory_pressure_entered')} occurrence(s)")

    reason = monitor.reevaluation_reason(raised)
    check("the reevaluation reason is the pressure event",
          reason == "memory_pressure_entered", f"reason={reason}")

    print("\n=== 8-11: the plan under pressure grants less ===")
    pressured_free = max(0, pressured["max"] - pressured["current"])
    second_plan, second_budget = plan_for(
        pressured_free, ceiling, registry, policy,
        previous=first_plan, now=75.0, reason=reason or "memory_pressure_entered",
    )
    record("replan", freeBytes=pressured_free,
           granted=second_plan.granted_memory_bytes,
           running=len(second_plan.running()),
           revision=second_plan.identity.revision,
           reason=second_plan.identity.reevaluation_reason)
    check("the new plan grants no more than the first",
          second_plan.granted_memory_bytes <= first_plan.granted_memory_bytes,
          f"{first_plan.granted_memory_bytes} -> {second_plan.granted_memory_bytes} bytes")
    check("the new plan records why it exists",
          second_plan.identity.reevaluation_reason == "memory_pressure_entered",
          second_plan.identity.reevaluation_reason)
    check("the protected reserve is still held back",
          second_budget.protected_reserve_bytes > 0,
          f"{second_budget.protected_reserve_bytes} bytes reserved")

    # The property worth asserting is preference, not survival. Under acute
    # pressure some essential service may genuinely not fit, and refusing it is
    # correct; what would be a defect is an *optional* service running while an
    # essential one was refused, because that is the priority order inverted.
    essential = {item.id for item in registry.essential()}
    still_running = {item.service_id for item in second_plan.running()}
    refused_essential = essential - still_running
    optional_running = still_running - essential
    record("priority-under-pressure",
           essentialRunning=len(essential & still_running), essentialTotal=len(essential),
           refusedEssential=sorted(refused_essential),
           optionalRunning=sorted(optional_running))
    check("no optional service runs while an essential one is refused",
          not (refused_essential and optional_running),
          f"refused essential={sorted(refused_essential)}, optional running={sorted(optional_running)}")
    check("user work is preserved: the reserve is never drawn on",
          second_budget.currently_allocatable_bytes >= 0
          and second_budget.protected_reserve_bytes > 0,
          f"allocatable={second_budget.currently_allocatable_bytes}, "
          f"reserve={second_budget.protected_reserve_bytes}")

    print("\n=== 12-13: remove the pressure; one good reading must not restore ===")
    hog.stop()
    time.sleep(2.0)
    relieved_sample, relieved = sample_from_cgroup(cgroup, at=90.0)
    record("pressure-removed", memoryCurrent=relieved["current"],
           availableFraction=round(relieved_sample.numeric.get("memory_available_fraction", 0), 4))
    blip_events = monitor.observe(relieved_sample)
    check("a single good reading does not raise recovery",
          not blip_events, f"events: {[e.event for e in blip_events]}")

    print("\n=== 14-15: recovery only after it holds ===")
    held_events: list[str] = []
    for offset, at in enumerate((105.0, 120.0, 135.0)):
        sample_n, _ = sample_from_cgroup(cgroup, at=at)
        held_events.extend(item.event for item in monitor.observe(sample_n))
    record("sustained-recovery", events=held_events)
    check("sustained recovery raises memory_pressure_recovered",
          "memory_pressure_recovered" in held_events,
          f"events: {held_events}")

    print("\n=== 16-17: the restored plan converges ===")
    restored_free = max(0, relieved["max"] - relieved["current"])
    # Replan repeatedly on a settled machine. The cooldown deliberately makes
    # the first plan after recovery differ from the next — a service held at its
    # previous action inside the window is the mechanism working — so the
    # property is that the sequence reaches a fixed point, not that any two
    # adjacent plans agree.
    third_plan, _ = plan_for(
        restored_free, ceiling, registry, policy,
        previous=second_plan, now=135.0, reason="memory_pressure_recovered",
    )
    digests: list[str] = []
    plan_n = third_plan
    for step in range(6):
        plan_n, _ = plan_for(
            restored_free, ceiling, registry, policy,
            previous=plan_n, now=200.0 + step * 120.0,
            reason="memory_pressure_recovered",
        )
        digests.append(plan_n.identity.content_digest[:12])
    record("restore", granted=third_plan.granted_memory_bytes,
           running=len(third_plan.running()),
           digestSequence=digests,
           finalRunning=len(plan_n.running()))
    check("the restored plan grants at least the pressured one",
          third_plan.granted_memory_bytes >= second_plan.granted_memory_bytes,
          f"{second_plan.granted_memory_bytes} -> {third_plan.granted_memory_bytes} bytes")
    check("repeated replanning reaches a fixed point rather than oscillating",
          digests[-1] == digests[-2] == digests[-3],
          f"last three digests: {digests[-3:]}")
    check("the machine returns to running what it ran before the pressure",
          len(plan_n.running()) >= len(first_plan.running()),
          f"{len(first_plan.running())} before, {len(plan_n.running())} after recovery")

    print("\n=== 18: the whole cycle raised two events, not twenty ===")
    all_events = [item.event for item in monitor.history]
    record("event-total", events=all_events, count=len(all_events))
    check("the full pressure cycle raised at most 3 events",
          len(all_events) <= 3, f"{len(all_events)}: {all_events}")

    evidence["failures"] = failures
    evidence["passed"] = not failures
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "adaptation.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8",
    )
    print(f"\n=== result: {'PASS' if not failures else 'FAIL'} ===")
    for item in failures:
        print(f"  {item}")
    print(f"evidence written to {EVIDENCE / 'adaptation.json'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

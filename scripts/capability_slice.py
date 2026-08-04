#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive one service through the applicator and read the kernel back at each step.

This is the part of the vertical slice that must not be a shell script, because
every assertion it makes is a comparison between what the applicator believes
and what the kernel reports, and getting that comparison wrong in ``bash`` is
easier than getting it right.

The sequence is §13's, and each step records evidence:

    observe -> plan -> reconcile -> apply (start) -> read back the cgroup
    -> health check -> commit -> stop -> release -> reconcile again (no action)

Nothing here trusts a return code as evidence of a state. ``systemctl start``
returning zero and ``memory.max`` containing the requested figure are different
claims, and only the second one is enforcement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

# Installed layout first. BUNNY_SLICE_INSTALLED=1 makes that mandatory: the
# point of the installed-path run is to exercise what shipped, and silently
# falling back to a source tree would produce a passing result about code the
# artifact does not contain.
_INSTALLED = Path("/usr/lib/bunny-os/python")
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))
if os.environ.get("BUNNY_SLICE_INSTALLED") != "1":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability.apply.applicator import Applicator, ApplicatorSettings
from capability.apply.audit import InMemoryAuditSink
from capability.apply.backends import ServiceLimits
from capability.apply.cgroup import detect_environment
from capability.apply.ledger import JsonFileLedger
from capability.apply.reconcile import reconcile
from capability.apply.state import desired_from_plan
from capability.apply.systemd import SystemdBackend, authorized_units_for
from capability.budget import compute_budget
from capability.discovery import discover
from capability.engine import evaluate
from capability.policy import Policy
from capability.registry import load_registry
from capability.scores import compute_scores

REQUIRE_INSTALLED = os.environ.get("BUNNY_SLICE_INSTALLED") == "1"
SERVICE = "bunny.capability.probe"
UNIT = os.environ.get("UNIT", "bunny-bunny-capability-probe.service")
STATE = Path(os.environ.get("STATE", "/tmp/cap-slice-state"))
EVIDENCE = Path(os.environ.get("EVIDENCE", "/root/capability-evidence"))

MIB = 1024 ** 2
evidence: dict[str, object] = {"schemaVersion": 1, "steps": []}


def record(step: str, **fields: object) -> None:
    entry = {"step": step, **fields}
    evidence["steps"].append(entry)
    detail = " ".join(f"{key}={value}" for key, value in fields.items() if key != "detail")
    print(f"  [{step}] {detail}")


def systemctl(*arguments: str) -> tuple[int, str]:
    result = subprocess.run(
        ["/usr/bin/systemctl", *arguments],
        capture_output=True, text=True, check=False,
    )
    return result.returncode, (result.stdout or result.stderr).strip()


def unit_cgroup_path() -> Path | None:
    """Where systemd actually put the unit. Read from systemd, not guessed."""
    code, value = systemctl("show", UNIT, "--property=ControlGroup", "--value")
    if code != 0 or not value:
        return None
    return Path("/sys/fs/cgroup") / value.lstrip("/")


def read_cgroup(path: Path, attribute: str) -> str | None:
    try:
        return (path / attribute).read_text(encoding="ascii").strip()
    except OSError:
        return None


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str) -> None:
        if condition:
            print(f"  PASS {name}: {detail}")
        else:
            failures.append(f"{name}: {detail}")
            print(f"  FAIL {name}: {detail}")

    print("=== environment ===")
    import capability as _capability_package

    package_path = Path(_capability_package.__file__).resolve()
    record("code-provenance", importedFrom=str(package_path.parent),
           requireInstalled=REQUIRE_INSTALLED)
    if REQUIRE_INSTALLED:
        check(
            "the capability package was imported from the installed path",
            str(package_path).startswith("/usr/lib/bunny-os/python/"),
            f"imported from {package_path}",
        )
        check(
            "the supervisor entry point exists at its installed path",
            Path("/usr/libexec/bunny-capability-supervisor").is_file(),
            "/usr/libexec/bunny-capability-supervisor",
        )

    environment = detect_environment()
    record("cgroup-environment", version=environment.version, usable=environment.usable,
           controllers=",".join(environment.available_controllers), detail=environment.detail)
    check("cgroup v2 usable", environment.usable, environment.detail)

    print("\n=== 1-6: discover, score, budget, plan ===")
    manifest_directory = (
        Path("/usr/share/bunny-os/capability/services") if REQUIRE_INSTALLED
        else Path("capability/services")
    )
    registry = load_registry(manifest_directory)
    policy = Policy()
    inventory = discover(budget_ms=2000, probe_runtimes=False)
    scores = compute_scores(inventory)
    budget = compute_budget(inventory, scores, policy,
                            essential_floor_bytes=registry.essential_floor_bytes())
    record("inventory", usableBytes=inventory.memory.usable_bytes(None),
           availableBytes=inventory.memory.usable_available_bytes(None),
           architecture=inventory.system.architecture.get(None))
    record("budget", allocatable=budget.currently_allocatable_bytes,
           reserve=budget.protected_reserve_bytes, viable=budget.viable)
    check("the probe manifest is in the registry", registry.get(SERVICE) is not None,
          f"{len(registry.services)} manifests loaded")

    plan = evaluate(inventory, scores, budget, registry, policy, now=0.0)
    decision = plan.decision(SERVICE)
    record("plan", planId=plan.plan_id, revision=plan.identity.revision,
           probeAction=decision.action if decision else None,
           grantBytes=decision.memory_grant_bytes if decision else 0)
    check("the plan wants the probe running", bool(decision and decision.running),
          f"action={decision.action if decision else 'absent'}")

    print("\n=== 7-8: observe actual state, reconcile ===")
    backend = SystemdBackend(
        authorized_units=authorized_units_for(registry),
        allow_host_modification=True,
    )
    check("systemd backend available", backend.available(), backend.unavailable_reason() or "ok")
    check("the probe unit is authorised", backend.authorized(SERVICE), UNIT)

    ledger = JsonFileLedger(
        path=STATE / "reservations.json",
        capacity_bytes=budget.currently_allocatable_bytes + budget.essential_services_bytes,
        protected_reserve_bytes=budget.protected_reserve_bytes,
    )
    ledger.load()
    audit = InMemoryAuditSink()
    applicator = Applicator(
        backend=backend, ledger=ledger, audit=audit,
        settings=ApplicatorSettings(dry_run=False),
    )

    actual = applicator.observe(registry, now=0.0)
    observed = actual.get(SERVICE)
    record("actual-before", state=observed.state, observedBy=observed.observed_by)
    check("the probe is observed stopped before we start", observed.state == "stopped",
          f"state={observed.state} ({observed.detail})")

    desired = desired_from_plan(plan, registry)
    settings = applicator._reconciliation_settings(desired, actual, budget, 0.0)
    plan_of_transitions = reconcile(desired, actual, settings=settings, now=0.0)
    probe_transitions = [item for item in plan_of_transitions.transitions if item.service_id == SERVICE]
    record("reconcile", total=len(plan_of_transitions.transitions),
           probeOperations=[item.operation for item in probe_transitions])
    check("reconciliation wants to start the probe",
          any(item.operation == "start" for item in probe_transitions),
          f"{len(probe_transitions)} transition(s) for the probe")

    print("\n=== 9: dry run records the intent and changes nothing ===")
    rehearsal = Applicator(
        backend=__import__("capability.apply.backends", fromlist=["DryRunBackend"]).DryRunBackend(observer=backend),
        ledger=JsonFileLedger(path=STATE / "rehearsal.json",
                              capacity_bytes=ledger.capacity_bytes),
        audit=InMemoryAuditSink(),
        settings=ApplicatorSettings(dry_run=True),
    )
    rehearsal_report = rehearsal.apply(
        plan, registry=registry, inventory=inventory, budget=budget, policy=policy, now=0.0,
    )
    code, active_after_rehearsal = systemctl("is-active", UNIT)
    record("dry-run", transitions=len(rehearsal_report.applied),
           unitStateAfter=active_after_rehearsal)
    check("the dry run left the unit inactive", active_after_rehearsal != "active",
          f"systemctl is-active reports '{active_after_rehearsal}'")

    print("\n=== 10-12: apply for real, then read the kernel back ===")
    report = applicator.apply(
        plan, registry=registry, inventory=inventory, budget=budget, policy=policy,
        now=0.0, actual=actual,
    )
    transition = next((item for item in report.applied if item.service_id == SERVICE), None)
    record("apply", planId=report.plan_id,
           probeResult=transition.result.result if transition and transition.result else None,
           detail=transition.result.detail if transition and transition.result else "")
    check("the applicator reports the probe started",
          bool(transition and transition.result and transition.result.result == "succeeded"),
          transition.result.detail if transition and transition.result else "no transition")

    # Give systemd a moment to settle the unit, then read the truth.
    for _ in range(40):
        code, active = systemctl("is-active", UNIT)
        if active == "active":
            break
        time.sleep(0.25)
    code, active = systemctl("is-active", UNIT)
    code, main_pid = systemctl("show", UNIT, "--property=MainPID", "--value")
    record("systemd-state", isActive=active, mainPid=main_pid)
    check("systemd reports the unit active", active == "active", f"is-active={active}")
    check("the unit has a main pid", main_pid.isdigit() and int(main_pid) > 0, f"MainPID={main_pid}")

    print("\n=== 12-13: cgroup enforcement, read back from the kernel ===")
    cgroup_path = unit_cgroup_path()
    record("cgroup-path", path=str(cgroup_path) if cgroup_path else None)
    check("systemd placed the unit in a cgroup", cgroup_path is not None and cgroup_path.is_dir(),
          str(cgroup_path))

    # The plan's own grant, not an arbitrary figure. Setting something else
    # here would leave the enforced limit disagreeing with the plan, and the
    # applicator would correctly want to correct it on the next pass — which
    # would look like a convergence failure caused by the test.
    requested = decision.memory_grant_bytes
    code, output = systemctl("set-property", UNIT, "--runtime", f"MemoryMax={requested}")
    record("set-property", exit=code, output=output[:200], requestedBytes=requested)
    check("systemctl set-property accepted the limit", code == 0, output[:160] or "ok")

    time.sleep(0.5)
    effective_raw = read_cgroup(cgroup_path, "memory.max") if cgroup_path else None
    current_raw = read_cgroup(cgroup_path, "memory.current") if cgroup_path else None
    peak_raw = read_cgroup(cgroup_path, "memory.peak") if cgroup_path else None
    effective = None if effective_raw in (None, "max") else int(effective_raw)
    record("cgroup-readback", memoryMax=effective_raw, memoryCurrent=current_raw,
           memoryPeak=peak_raw, requestedBytes=requested)
    check("memory.max reads back at or below the requested figure",
          effective is not None and effective <= requested,
          f"requested {requested}, kernel reports {effective_raw}")
    check("memory.current is non-zero, so the working set is real",
          current_raw is not None and current_raw.isdigit() and int(current_raw) > 0,
          f"memory.current={current_raw}")

    # The process must actually be in that cgroup. A limit on a cgroup the
    # service is not in enforces nothing.
    procs = read_cgroup(cgroup_path, "cgroup.procs") if cgroup_path else None
    in_cgroup = bool(procs and main_pid.isdigit() and main_pid in procs.split())
    record("cgroup-membership", procs=(procs or "").replace("\n", ","), mainPid=main_pid)
    check("the service process is inside the limited cgroup", in_cgroup,
          f"cgroup.procs={(procs or '').splitlines()}")

    print("\n=== 14-15: health check and commit ===")
    health = backend.health(SERVICE, timeout_seconds=10)
    record("health", ok=health.ok, detail=health.detail)
    check("the health check passes", health.ok, health.detail)

    held = [item for item in ledger.active() if item.service_id == SERVICE]
    record("reservation", count=len(held),
           state=held[0].state if held else None,
           bytes=held[0].outstanding if held else 0)
    check("a committed reservation is held for the probe",
          bool(held) and held[0].state == "committed",
          f"{len(held)} reservation(s)")

    print("\n=== 19: reconciling at the converged point produces no action ===")
    # Checked here, while the probe is running and committed — not after the
    # stop below. A service that has been stopped and is still wanted is
    # correctly wanted again, so asserting "no action" after a stop would be
    # asserting the opposite of the intended behaviour. Only the probe is
    # asserted on: the other Bunny units are not installed on this machine, so
    # their repeated start attempts are correct behaviour for an absent unit and
    # say nothing about idempotency.
    actual_converged = applicator.observe(registry, now=1.0)
    settled = evaluate(inventory, scores, budget, registry, policy, previous=plan, now=1.0)
    desired_converged = desired_from_plan(settled, registry)
    settings_converged = applicator._reconciliation_settings(
        desired_converged, actual_converged, budget, 1.0,
    )
    again = reconcile(desired_converged, actual_converged, settings=settings_converged, now=1.0)
    probe_again = [item for item in again.transitions if item.service_id == SERVICE]
    record("idempotency", probeTransitions=[item.operation for item in probe_again],
           totalTransitions=len(again.transitions))
    check("the running probe needs no further transition", not probe_again,
          f"operations still wanted: {[item.operation for item in probe_again]}")

    print("\n=== 16-17: stop gracefully, release the reservation ===")
    before_stop = ledger.available_bytes()
    stop_outcome = backend.stop(SERVICE, graceful=True, timeout_seconds=15)
    released = ledger.release_for_service(SERVICE, detail="vertical slice teardown")
    time.sleep(0.5)
    code, active_after = systemctl("is-active", UNIT)
    record("stop", ok=stop_outcome.ok, unitState=active_after,
           released=len(released), availableBefore=before_stop,
           availableAfter=ledger.available_bytes())
    check("the unit stopped", active_after in ("inactive", "failed", "unknown"),
          f"is-active={active_after}")
    check("the reservation was released", ledger.available_bytes() > before_stop,
          f"{before_stop} -> {ledger.available_bytes()} bytes available")

    print("\n=== 18: audit explains every step ===")
    events = list(audit.events())
    for required in ("reconcile.started", "transition.attempted", "reservation.taken",
                     "reservation.committed", "transition.succeeded", "reconcile.finished"):
        check(f"audit records {required}", required in events,
              f"{events.count(required)} occurrence(s)")
    record("audit", events=sorted(set(events)), total=len(events))


    evidence["failures"] = failures
    evidence["passed"] = not failures
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "vertical-slice.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8",
    )

    print(f"\n=== result: {'PASS' if not failures else 'FAIL'} ===")
    for item in failures:
        print(f"  {item}")
    print(f"evidence written to {EVIDENCE / 'vertical-slice.json'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

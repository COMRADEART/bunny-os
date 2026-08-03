# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capability supervisor: the loop that keeps a machine matching its plan.

Everything else in this subsystem is a pure function or a bounded operation.
This is the one component with a lifetime, and its whole design is about not
becoming the thing that goes wrong at three in the morning:

**It never busy-loops.** Each cycle ends by sleeping until the next interval or
until something interesting happens, whichever is sooner. There is no path that
polls without waiting, and the sleep is interruptible so that shutdown does not
have to wait out an interval.

**It refuses to run twice.** Ownership is taken with a kernel lock before
anything else, and released on every exit path. Two supervisors applying plans
to one machine would each be individually correct and jointly disastrous.

**It starts conservatively.** The default mode is ``observe`` — inventory,
plan, reconcile, explain, change nothing. Reaching ``apply`` takes an explicit
configuration change, and the mode is reported in every audit record and every
status output so that no transcript is ambiguous about what it describes.

**It degrades rather than stopping.** State it cannot trust puts it in safe
mode, which observes and explains without applying. A missing service manager
produces ``unknown`` observations rather than an empty machine. Neither is a
reason to exit: a supervisor that quits when something is wrong is a supervisor
that is absent exactly when a person needs to ask it what happened.

The cycle, in order, and each step is bounded:

    recover durable state -> observe -> discover -> budget -> plan
    -> revalidate -> reconcile -> apply (mode permitting) -> audit -> wait
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Callable, Mapping

from .apply.applicator import Applicator, ApplicatorSettings, ApplyReport
from .apply.approval_store import DurableApprovalStore
from .apply.audit import AuditSink, InMemoryAuditSink, JsonLinesAuditSink
from .apply.backends import DryRunBackend, InMemoryBackend
from .apply.cgroup import controller_for, detect_environment
from .apply.failures import CircuitBreaker, RetryJournal, RetryPolicy
from .apply.ledger import JsonFileLedger
from .apply.lock import InstanceLock, LockError
from .apply.monitor import (
    CONSTRAINED_SIGNALS,
    DEFAULT_SIGNALS,
    MonitorSettings,
    RuntimeMonitor,
    sample_from_inventory,
)
from .apply.systemd import SystemdBackend, authorized_units_for, systemd_available
from .budget import compute_budget
from .discovery import DEFAULT_BUDGET_MS, discover
from .engine import evaluate
from .apply.identity import policy_fingerprint, registry_fingerprint
from .policy import Policy, PolicyError, load_policy
from .registry import Registry, ManifestError, load_registry
from .scores import compute_scores

__all__ = ["MODES", "Supervisor", "SupervisorConfig", "main"]

#: What the supervisor is permitted to do, in increasing order of consequence.
#:
#: ``observe``  — read the machine, plan, reconcile, explain. Touch nothing.
#: ``dry-run``  — additionally rehearse transitions through a recording backend.
#: ``apply``    — perform them.
#:
#: The installed default is ``observe``. §6 of the brief asks for a conservative
#: default and this is the most conservative one that still produces a useful
#: answer: a machine running in observe mode can tell an operator exactly what
#: it would do, which is what makes enabling ``apply`` an informed decision
#: rather than a leap.
MODES = ("observe", "dry-run", "apply")

#: Installed layout. Immutable code and data under /usr, administrator
#: configuration under /etc, persistent state under /var/lib, volatile state
#: under /run, audit under /var/log. Each is separate because their backup,
#: permission and lifetime rules differ, and a single directory holding all five
#: gets the weakest of the five.
DEFAULT_CONFIG_PATH = Path("/etc/bunny-os/capability/supervisor.json")
DEFAULT_STATE_DIRECTORY = Path("/var/lib/bunny-os/capability")
DEFAULT_RUNTIME_DIRECTORY = Path("/run/bunny-os/capability")
DEFAULT_AUDIT_PATH = Path("/var/log/bunny-os/capability-audit.jsonl")

#: Hard bound on one cycle. A cycle that exceeds it is a bug, and the supervisor
#: reports it rather than letting a wedged backend stall reconciliation forever.
DEFAULT_CYCLE_DEADLINE_SECONDS = 120.0


@dataclass(frozen=True)
class SupervisorConfig:
    """Everything the supervisor reads before it does anything.

    Parsed from JSON and validated strictly: a supervisor that silently ignored
    a misspelled key would leave an operator believing a limit was in force.
    """

    mode: str = "observe"
    interval_seconds: float = 30.0
    cycle_deadline_seconds: float = DEFAULT_CYCLE_DEADLINE_SECONDS
    state_directory: Path = DEFAULT_STATE_DIRECTORY
    runtime_directory: Path = DEFAULT_RUNTIME_DIRECTORY
    audit_path: Path | None = DEFAULT_AUDIT_PATH
    #: Discovery wall-clock budget, in milliseconds.
    discovery_budget_ms: int = DEFAULT_BUDGET_MS
    #: Only sample memory, at a long cooldown. For constrained nodes.
    constrained_monitoring: bool = False
    #: Permit stopping an essential service. Off, and an operator decision.
    allow_essential_stop: bool = False
    #: Write cgroup limits directly rather than leaving them to systemd.
    #: Off by default: where systemd owns the unit, systemd owns its resources,
    #: and two writers to one cgroup is a race with a kernel on one side.
    direct_cgroup_writes: bool = False
    #: Maximum cycles before exiting. 0 means run until told to stop; a positive
    #: value is what makes the supervisor usable as a one-shot in a test.
    maximum_cycles: int = 0
    service_directory: Path | None = None
    policy_path: Path | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}, not {self.mode!r}")
        if self.interval_seconds < 1.0:
            raise ValueError("intervalSeconds must be at least 1; a shorter loop is a busy loop")
        if self.cycle_deadline_seconds <= 0:
            raise ValueError("cycleDeadlineSeconds must be positive")

    @property
    def applies(self) -> bool:
        return self.mode == "apply"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "mode": self.mode,
            "intervalSeconds": self.interval_seconds,
            "cycleDeadlineSeconds": self.cycle_deadline_seconds,
            "stateDirectory": str(self.state_directory),
            "runtimeDirectory": str(self.runtime_directory),
            "auditPath": str(self.audit_path) if self.audit_path else None,
            "discoveryBudgetMs": self.discovery_budget_ms,
            "constrainedMonitoring": self.constrained_monitoring,
            "allowEssentialStop": self.allow_essential_stop,
            "directCgroupWrites": self.direct_cgroup_writes,
            "maximumCycles": self.maximum_cycles,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any], *, source: str = "<memory>") -> "SupervisorConfig":
        if not isinstance(document, Mapping):
            raise ValueError(f"{source}: configuration must be a JSON object")

        known = {
            "schemaVersion", "mode", "intervalSeconds", "cycleDeadlineSeconds",
            "stateDirectory", "runtimeDirectory", "auditPath", "discoveryBudgetMs",
            "constrainedMonitoring", "allowEssentialStop", "directCgroupWrites",
            "maximumCycles", "serviceDirectory", "policyPath",
        }
        unknown = sorted(set(document) - known)
        if unknown:
            raise ValueError(
                f"{source}: unrecognised configuration key(s) {unknown}. A supervisor that "
                "ignored these would leave you believing a setting was in force when it was not"
            )

        version = document.get("schemaVersion", 1)
        if version != 1:
            raise ValueError(f"{source}: unsupported configuration schemaVersion {version!r}")

        def number(key: str, default: float, minimum: float) -> float:
            value = document.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{source}: {key} must be a number")
            if value < minimum:
                raise ValueError(f"{source}: {key} must be at least {minimum}")
            return float(value)

        def flag(key: str, default: bool) -> bool:
            value = document.get(key, default)
            if not isinstance(value, bool):
                raise ValueError(f"{source}: {key} must be true or false")
            return value

        def path_or_none(key: str) -> Path | None:
            value = document.get(key)
            if value is None:
                return None
            if not isinstance(value, str) or not value:
                raise ValueError(f"{source}: {key} must be a non-empty string path")
            return Path(value)

        audit = document.get("auditPath", str(DEFAULT_AUDIT_PATH))
        return cls(
            mode=str(document.get("mode", "observe")),
            interval_seconds=number("intervalSeconds", 30.0, 1.0),
            cycle_deadline_seconds=number("cycleDeadlineSeconds", DEFAULT_CYCLE_DEADLINE_SECONDS, 1.0),
            state_directory=Path(str(document.get("stateDirectory", DEFAULT_STATE_DIRECTORY))),
            runtime_directory=Path(str(document.get("runtimeDirectory", DEFAULT_RUNTIME_DIRECTORY))),
            audit_path=Path(str(audit)) if audit else None,
            discovery_budget_ms=int(number("discoveryBudgetMs", DEFAULT_BUDGET_MS, 1)),
            constrained_monitoring=flag("constrainedMonitoring", False),
            allow_essential_stop=flag("allowEssentialStop", False),
            direct_cgroup_writes=flag("directCgroupWrites", False),
            maximum_cycles=int(number("maximumCycles", 0, 0)),
            service_directory=path_or_none("serviceDirectory"),
            policy_path=path_or_none("policyPath"),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "SupervisorConfig":
        """Read configuration, or take the conservative defaults.

        An absent file is not an error: a machine with no supervisor
        configuration runs in observe mode, which is the correct behaviour for
        an installation nobody has enabled anything on.
        """
        resolved = DEFAULT_CONFIG_PATH if path is None else path
        if not resolved.is_file():
            return cls()
        try:
            document = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{resolved} could not be read: {exc}") from exc
        return cls.from_json(document, source=str(resolved))


@dataclass
class CycleResult:
    """What one pass of the loop did."""

    cycle: int
    mode: str
    started_at_monotonic: float
    duration_seconds: float
    plan_id: str = ""
    revision: int = 0
    report: ApplyReport | None = None
    events: tuple[str, ...] = ()
    reevaluation_reason: str | None = None
    problems: tuple[str, ...] = ()
    safe_mode: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "mode": self.mode,
            "startedAtMonotonic": self.started_at_monotonic,
            "durationSeconds": round(self.duration_seconds, 4),
            "planId": self.plan_id,
            "revision": self.revision,
            "monitorEvents": list(self.events),
            "reevaluationReason": self.reevaluation_reason,
            "safeMode": self.safe_mode,
            "problems": list(self.problems),
            "report": self.report.to_json() if self.report is not None else None,
        }


@dataclass
class Supervisor:
    """The capability control plane's one long-lived process."""

    config: SupervisorConfig = field(default_factory=SupervisorConfig)
    registry: Registry | None = None
    policy: Policy | None = None
    #: Injected for tests; otherwise built from the configuration.
    backend: Any = None
    audit: AuditSink | None = None
    #: Injected clock, so a test drives the loop without sleeping.
    clock: Callable[[], float] = time.monotonic

    applicator: Applicator | None = field(default=None, init=False)
    monitor: RuntimeMonitor | None = field(default=None, init=False)
    lock: InstanceLock | None = field(default=None, init=False)
    approvals: DurableApprovalStore | None = field(default=None, init=False)
    previous_plan: Any = field(default=None, init=False)
    #: The lock's description, kept after release. ``shutdown()`` drops the lock
    #: itself — holding it open would defeat the point — but a status report
    #: printed after a run still has to be able to say what mechanism protected
    #: it, and reporting ``null`` there reads as "no lock was taken".
    lock_description: dict[str, Any] | None = field(default=None, init=False)
    cycles: int = field(default=0, init=False)
    history: list[CycleResult] = field(default_factory=list, init=False)
    warnings: list[str] = field(default_factory=list, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _reload: threading.Event = field(default_factory=threading.Event, init=False)

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #

    def prepare(self) -> None:
        """Everything that must succeed before the first cycle.

        Ordered so that the most consequential failure is reached first: without
        the lock this process must not proceed at all, and discovering that
        after building a backend and reading a registry wastes work and produces
        a confusing diagnostic.
        """
        self.config.state_directory.mkdir(parents=True, exist_ok=True)
        self.config.runtime_directory.mkdir(parents=True, exist_ok=True)

        # 1. Ownership, before anything else.
        self.lock = InstanceLock(
            self.config.runtime_directory / "supervisor.lock", role="supervisor",
        )
        self.lock.acquire()
        self.lock_description = self.lock.describe()

        # 2. Configuration and registry.
        if self.registry is None:
            self.registry = load_registry(self.config.service_directory)
        if self.policy is None:
            self.policy = load_policy(self.config.policy_path)
        self.warnings.extend(self.policy.warnings)

        # 3. Audit, before any decision is made, so the decisions are recorded.
        if self.audit is None:
            if self.config.audit_path is not None:
                try:
                    self.audit = JsonLinesAuditSink(path=self.config.audit_path)
                except OSError:
                    self.audit = InMemoryAuditSink()
                    self.warnings.append(
                        f"{self.config.audit_path} could not be opened; audit records are "
                        "held in memory and lost on exit"
                    )
            else:
                self.audit = InMemoryAuditSink()

        # 4. Durable approvals.
        self.approvals = DurableApprovalStore(path=self.config.state_directory / "approvals.json")
        self.warnings.extend(self.approvals.load())

        # 5. Durable reservations. Capacity is set per cycle from the budget.
        ledger = JsonFileLedger(path=self.config.state_directory / "reservations.json")
        self.warnings.extend(ledger.load())

        retries = RetryJournal(
            policy=RetryPolicy(), path=self.config.state_directory / "retries.json",
        )
        self.warnings.extend(retries.load())

        # 6. The backend, matched to the mode. This is the only place a backend
        #    that can change the host is constructed, and it happens only in
        #    apply mode with systemd present.
        backend = self.backend if self.backend is not None else self._build_backend()

        self.applicator = Applicator(
            backend=backend,
            ledger=ledger,
            approvals=self.approvals,
            audit=self.audit,
            breaker=CircuitBreaker(),
            retries=retries,
            settings=ApplicatorSettings(
                dry_run=not self.config.applies,
                allow_essential_stop=self.config.allow_essential_stop,
            ),
        )

        self.monitor = RuntimeMonitor(settings=MonitorSettings(
            interval_seconds=self.config.interval_seconds,
            signals=CONSTRAINED_SIGNALS if self.config.constrained_monitoring else DEFAULT_SIGNALS,
        ))

    def _build_backend(self) -> Any:
        """The backend the configured mode entitles this supervisor to.

        ``observe`` gets a dry-run backend with a read-only systemd observer, so
        it can report actual state without any code path that could change it.
        ``apply`` gets a systemd backend with the modification opt-in — and only
        when systemd is actually PID 1, because a backend that cannot reach a
        service manager should say so rather than fail every transition.
        """
        assert self.registry is not None
        if not systemd_available():
            self.warnings.append(
                "systemd is not the init system here, so no service can be observed or "
                "controlled. The supervisor will plan and explain, and apply nothing."
            )
            return DryRunBackend(observer=None)

        units = authorized_units_for(self.registry)
        cgroups = controller_for(
            detect_environment(),
            may_write=self.config.direct_cgroup_writes and self.config.applies,
        )

        if self.config.applies:
            return SystemdBackend(
                authorized_units=units, allow_host_modification=True, cgroups=cgroups,
            )
        observer = SystemdBackend(authorized_units=units, cgroups=cgroups)
        return DryRunBackend(observer=observer)

    # ------------------------------------------------------------------ #
    # The cycle
    # ------------------------------------------------------------------ #

    def cycle(self) -> CycleResult:
        """One bounded pass. Never raises; problems are reported in the result."""
        assert self.applicator is not None and self.registry is not None
        assert self.policy is not None and self.monitor is not None

        self.cycles += 1
        started = self.clock()
        problems: list[str] = []
        events: tuple[str, ...] = ()
        reason: str | None = None
        report: ApplyReport | None = None
        plan_id, revision = "", 0

        try:
            # Discovery is bounded by its own wall-clock budget.
            inventory = discover(
                budget_ms=self.config.discovery_budget_ms,
                probe_runtimes=True,
                probe_reachability=bool(self.policy.reachability_endpoints),
                endpoints=self.policy.reachability_endpoints,
            )
            scores = compute_scores(inventory)
            budget = compute_budget(
                inventory, scores, self.policy,
                essential_floor_bytes=self.registry.essential_floor_bytes(),
            )

            # The monitor's reading of this inventory decides *why* the next
            # plan exists. Its typed reason goes into the plan's identity.
            sample = sample_from_inventory(
                inventory, at_monotonic=started,
                policy_fingerprint=policy_fingerprint(self.policy),
                registry_fingerprint=registry_fingerprint(self.registry),
                failed_services=self._failed_services(),
            )
            raised = self.monitor.observe(sample)
            events = tuple(item.event for item in raised)
            reason = self.monitor.reevaluation_reason(raised) or (
                "initial" if self.previous_plan is None else "operator_requested"
            )

            plan = evaluate(
                inventory, scores, budget, self.registry, self.policy,
                previous=self.previous_plan, now=started, reason=reason,
            )
            plan_id = plan.plan_id
            revision = plan.identity.revision if plan.identity else 0

            # The ledger's capacity is the budget's, every cycle. A machine
            # whose available memory fell must not keep promising the old figure.
            self.applicator.ledger.capacity_bytes = (
                budget.currently_allocatable_bytes + budget.essential_services_bytes
            )
            self.applicator.ledger.protected_reserve_bytes = budget.protected_reserve_bytes

            self.approvals.expire(started)

            report = self.applicator.apply(
                plan, registry=self.registry, inventory=inventory,
                budget=budget, policy=self.policy, now=started,
            )
            self.previous_plan = plan

            if report.reevaluation_reason:
                # A rejected plan is not carried forward: the next cycle plans
                # from scratch rather than chaining onto something invalid.
                if not report.validation or not report.validation.ok:
                    self.previous_plan = None

        except (ManifestError, PolicyError) as exc:
            problems.append(f"configuration is not usable: {exc}")
        except Exception as exc:  # noqa: BLE001 - the loop must survive one bad cycle
            problems.append(f"{type(exc).__name__}: {exc}")

        duration = self.clock() - started
        if duration > self.config.cycle_deadline_seconds:
            problems.append(
                f"this cycle took {duration:.1f}s against a "
                f"{self.config.cycle_deadline_seconds:.0f}s deadline"
            )

        result = CycleResult(
            cycle=self.cycles,
            mode=self.config.mode,
            started_at_monotonic=started,
            duration_seconds=duration,
            plan_id=plan_id,
            revision=revision,
            report=report,
            events=events,
            reevaluation_reason=reason,
            problems=tuple(problems),
            safe_mode=bool(self.approvals and self.approvals.safe_mode),
        )
        self.history.append(result)
        if len(self.history) > 32:
            del self.history[: len(self.history) - 32]
        return result

    def _failed_services(self) -> tuple[str, ...]:
        """Services the last pass observed as failed, for the monitor."""
        if not self.history:
            return ()
        last = self.history[-1]
        if last.report is None:
            return ()
        return tuple(sorted(
            item.service_id for item in last.report.failures
        ))

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        """Cycle until told to stop. Returns a process exit status."""
        try:
            self.prepare()
        except LockError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 3
        except (ManifestError, PolicyError, ValueError) as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2

        for warning in self.warnings:
            print(f"warning: {warning}", file=sys.stderr)

        try:
            while not self._stop.is_set():
                result = self.cycle()
                for problem in result.problems:
                    print(f"cycle {result.cycle}: {problem}", file=sys.stderr)

                if self.config.maximum_cycles and self.cycles >= self.config.maximum_cycles:
                    break
                if self._stop.is_set():
                    break

                # Interruptible wait. `Event.wait` returns as soon as it is set,
                # so shutdown does not have to sit out an interval, and there is
                # no path here that spins.
                self._stop.wait(timeout=self.config.interval_seconds)

                if self._reload.is_set():
                    self._reload.clear()
                    self._apply_reload()
        finally:
            self.shutdown()
        return 0

    def _apply_reload(self) -> None:
        """Re-read what is safe to re-read without dropping state.

        Policy and manifests are re-read; the ledger, approvals and lock are
        not. Reloading those would mean forgetting reservations for services
        that are still running.
        """
        try:
            self.policy = load_policy(self.config.policy_path)
            self.registry = load_registry(self.config.service_directory)
            print("reloaded policy and service manifests", file=sys.stderr)
        except (ManifestError, PolicyError) as exc:
            print(f"reload refused, keeping the previous configuration: {exc}", file=sys.stderr)

    def request_stop(self) -> None:
        self._stop.set()

    def request_reload(self) -> None:
        self._reload.set()

    def shutdown(self) -> None:
        """Flush state and release ownership. Safe to call more than once."""
        if self.applicator is not None:
            try:
                # The ledger and journal persist on every mutation, so there is
                # nothing to flush that is not already durable. Releasing the
                # lock is the part that matters, and it is what a second
                # supervisor is waiting on.
                pass
            except Exception:  # noqa: BLE001
                pass
        if self.lock is not None:
            self.lock.release()
            self.lock = None

    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "mode": self.config.mode,
            "cycles": self.cycles,
            "warnings": list(self.warnings),
            "configuration": self.config.to_json(),
            "lock": self.lock.describe() if self.lock else self.lock_description,
            "applicator": self.applicator.status() if self.applicator else None,
            "approvals": {
                "safeMode": self.approvals.safe_mode,
                "pending": len(self.approvals.pending()),
            } if self.approvals else None,
            "monitor": self.monitor.status() if self.monitor else None,
            "lastCycle": self.history[-1].to_json() if self.history else None,
        }


def _install_signal_handlers(supervisor: Supervisor) -> None:
    """SIGTERM and SIGINT stop; SIGHUP reloads. Best effort on platforms without them."""

    def stop(signum: int, frame: Any) -> None:
        supervisor.request_stop()

    def reload(signum: int, frame: Any) -> None:
        supervisor.request_reload()

    for name, handler in (("SIGTERM", stop), ("SIGINT", stop), ("SIGHUP", reload)):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, handler)
        except (ValueError, OSError):
            # Not the main thread, or a platform that will not take it. The
            # supervisor still stops on its own terms; only the signal path is
            # unavailable.
            continue


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="bunny-capability-supervisor",
        description="Keep this machine matching its capability execution plan.",
    )
    parser.add_argument("--config", type=Path, help=f"configuration file (default {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--mode", choices=MODES, help="override the configured mode")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--status", action="store_true", help="print status as JSON after the run")
    parser.add_argument("--services", type=Path, help="read service manifests from this directory")
    parser.add_argument("--policy", type=Path, help="read policy from this file")
    parser.add_argument("--state-directory", type=Path, help="override the persistent state directory")
    parser.add_argument("--runtime-directory", type=Path, help="override the runtime directory")
    parser.add_argument("--audit-path", type=Path, help="override the audit log path")
    args = parser.parse_args(argv)

    try:
        config = SupervisorConfig.load(args.config)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    overrides: dict[str, Any] = {}
    if args.mode:
        overrides["mode"] = args.mode
    if args.once:
        overrides["maximum_cycles"] = 1
    if args.services:
        overrides["service_directory"] = args.services
    if args.policy:
        overrides["policy_path"] = args.policy
    if args.state_directory:
        overrides["state_directory"] = args.state_directory
    if args.runtime_directory:
        overrides["runtime_directory"] = args.runtime_directory
    if args.audit_path:
        overrides["audit_path"] = args.audit_path
    if overrides:
        config = replace(config, **overrides)

    supervisor = Supervisor(config=config)
    _install_signal_handlers(supervisor)
    status = supervisor.run()

    if args.status:
        print(json.dumps(supervisor.status(), indent=2, sort_keys=True, default=str))
    return status


if __name__ == "__main__":
    raise SystemExit(main())

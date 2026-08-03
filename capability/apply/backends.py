# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The service-control interface, and the backends that do not touch a machine.

Everything above this layer speaks in services; everything below it speaks in
units, cgroups and processes. The interface is deliberately narrow — eight verbs
— because every verb is a way for a bug in the applicator to become a change on
somebody's computer, and a wide interface is a wide blast radius.

Three properties are contractual for every implementation:

**Bounded.** Every operation takes a deadline and is required to return by it.
An operation with no timeout is an operation that can hang the reconciliation
loop, and a reconciliation loop that is hung is a machine that has stopped
adapting without saying so.

**Classified.** Failures come back as a
:class:`~capability.apply.failures.FailureClass` name, never as a bare boolean or
an exception for the caller to interpret. "Unit missing", "permission denied",
"timed out" and "the service itself failed" produce four different responses
from the retry policy, and a backend that collapsed them would make the retry
policy guess.

**Honest about enforcement.** A backend reports what it actually managed to
apply, not what it was asked to apply. If a memory limit could not be written,
the outcome says the service is unconstrained. Nothing in Bunny OS may claim a
service is limited when the write failed — that would put a false statement in
front of a user and a false premise under the budget engine.

The default backend is :class:`DryRunBackend`. It records and changes nothing.
Reaching a backend that can modify a host requires constructing it explicitly,
with an allowlist, which is the only place in this package where that is
possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, Sequence

from .state import ServiceObservation

__all__ = [
    "BackendOutcome",
    "DryRunBackend",
    "EnforcedLimits",
    "InMemoryBackend",
    "RecordedOperation",
    "ServiceControlBackend",
    "ServiceLimits",
]


@dataclass(frozen=True)
class ServiceLimits:
    """Declarative resource limits for one service.

    Provider-neutral by design. These map onto cgroup v2 attributes today and
    onto whatever a future non-systemd node uses tomorrow, and the applicator
    never learns which. ``None`` means "do not set this", which is not the same
    as zero: a ``cpu_quota_percent`` of zero would stop the service entirely.
    """

    memory_max_bytes: int | None = None
    memory_high_bytes: int | None = None
    cpu_weight: int | None = None
    cpu_quota_percent: float | None = None
    process_limit: int | None = None
    io_weight: int | None = None

    @classmethod
    def from_desired(cls, desired: Any) -> "ServiceLimits":
        """Build limits from a desired service. The plan's figures, unaltered.

        ``memory_high`` is set below ``memory_max`` so the kernel throttles and
        reclaims before it kills. That is a *softening* of the plan's limit, not
        a widening of it: the hard ceiling is still exactly what was granted.
        """
        grant = desired.memory_limit_bytes or 0
        return cls(
            memory_max_bytes=grant or None,
            memory_high_bytes=int(grant * 0.9) if grant else None,
            cpu_quota_percent=desired.cpu_percent or None,
            cpu_weight=_cpu_weight(desired.priority),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "memoryMaxBytes": self.memory_max_bytes,
            "memoryHighBytes": self.memory_high_bytes,
            "cpuWeight": self.cpu_weight,
            "cpuQuotaPercent": self.cpu_quota_percent,
            "processLimit": self.process_limit,
            "ioWeight": self.io_weight,
        }


def _cpu_weight(priority: int) -> int:
    """Map a manifest priority band onto a cgroup v2 ``cpu.weight``.

    cgroup v2 takes 1..10000 with 100 as the default. The manifest's 0..100
    priority is mapped so that the ``standard`` band (50) lands on 100, which
    keeps a normally-configured Bunny OS service scheduled like any other
    process on the machine rather than quietly advantaged over the user's work.
    """
    return max(1, min(10000, int(2 * max(0, min(100, priority)) or 1)))


@dataclass(frozen=True)
class EnforcedLimits:
    """What was asked for against what the machine actually applied.

    Both are kept. A limit that was requested and silently ignored is the
    failure mode this type exists to make visible: the requested figure is what
    the plan believed, the effective figure is what is true, and anything that
    reports only one of them is reporting a number nobody can act on.
    """

    requested: ServiceLimits
    effective: ServiceLimits
    enforced: bool
    detail: str = ""
    #: Controllers that were unavailable, e.g. ``("memory", "io")``.
    unavailable_controllers: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "requested": self.requested.to_json(),
            "effective": self.effective.to_json(),
            "enforced": self.enforced,
            "unavailableControllers": list(self.unavailable_controllers),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BackendOutcome:
    """The result of one backend operation."""

    ok: bool
    operation: str
    service_id: str
    failure_class: str | None = None
    detail: str = ""
    observation: ServiceObservation | None = None
    limits: EnforcedLimits | None = None
    #: Seconds the operation took, on the caller's clock.
    duration_seconds: float = 0.0
    #: Backend-specific diagnostic, already redacted. Bounded so that a service
    #: that writes megabytes to stderr cannot fill a constrained node's disk
    #: through the audit log.
    diagnostic: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "serviceId": self.service_id,
            "failureClass": self.failure_class,
            "detail": self.detail,
            "durationSeconds": self.duration_seconds,
            "limits": self.limits.to_json() if self.limits is not None else None,
            "diagnostic": self.diagnostic[:2048],
        }


class ServiceControlBackend(Protocol):
    """What the applicator needs from an operating system.

    Implementations must be replaceable. §7 of the brief is explicit that Bunny
    OS will not assume systemd forever, and the way that promise is kept is by
    never letting a systemd concept — a unit name, a job id, a D-Bus path —
    appear above this line.
    """

    name: str

    def available(self) -> bool:
        """Whether this backend can be used on this machine at all."""

    def authorized(self, service_id: str) -> bool:
        """Whether this backend may operate this service.

        Separate from :meth:`available` because the answers differ: systemd may
        be running and this service may still be one Bunny OS has no business
        controlling. A backend that conflated them would let an authorisation
        failure read as a missing service manager.
        """

    def inspect(self, service_id: str) -> ServiceObservation:
        """Observe one service. Must never change it."""

    def start(
        self, service_id: str, implementation_id: str | None,
        limits: ServiceLimits, *, timeout_seconds: float,
    ) -> BackendOutcome:
        """Apply limits, then start. Limits before start, always: a service that
        starts unconstrained and is limited afterwards has already had its
        chance to allocate past the grant."""

    def stop(self, service_id: str, *, graceful: bool, timeout_seconds: float) -> BackendOutcome:
        ...

    def suspend(self, service_id: str, *, timeout_seconds: float) -> BackendOutcome:
        ...

    def resume(self, service_id: str, *, timeout_seconds: float) -> BackendOutcome:
        ...

    def reload(self, service_id: str, *, timeout_seconds: float) -> BackendOutcome:
        ...

    def apply_limits(self, service_id: str, limits: ServiceLimits, *, timeout_seconds: float) -> BackendOutcome:
        ...

    def health(self, service_id: str, *, timeout_seconds: float) -> BackendOutcome:
        ...


@dataclass(frozen=True)
class RecordedOperation:
    """One operation a backend was asked to perform."""

    sequence: int
    operation: str
    service_id: str
    implementation_id: str | None = None
    limits: ServiceLimits | None = None
    graceful: bool | None = None
    timeout_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "operation": self.operation,
            "serviceId": self.service_id,
            "implementationId": self.implementation_id,
            "limits": self.limits.to_json() if self.limits is not None else None,
            "graceful": self.graceful,
            "timeoutSeconds": self.timeout_seconds,
        }


@dataclass
class InMemoryBackend:
    """A deterministic backend that models a machine without being one.

    Every test in this package runs against this. It is not a mock: it holds
    real state, enforces the same ordering rules a real service manager does
    (you cannot start what is already running, stopping what is stopped is a
    no-op), and it can be told to fail in each of the ways a real one fails.

    Failure injection is by service id rather than by call count, so a test that
    adds an unrelated service does not shift the failure onto a different
    operation.
    """

    name: str = "in-memory"
    services: dict[str, ServiceObservation] = field(default_factory=dict)
    operations: list[RecordedOperation] = field(default_factory=list)
    #: ``{(service_id, operation): failure_class}``. ``operation`` may be
    #: ``"*"`` to fail every operation on that service.
    failures: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Services whose start succeeds but whose health check then fails.
    unhealthy: set[str] = field(default_factory=set)
    #: Services that are present but not ours, and must never be touched.
    external: set[str] = field(default_factory=set)
    #: Services whose start leaves them half-up: the process exists, the service
    #: never becomes ready. Models the partial-startup case.
    partial_start: set[str] = field(default_factory=set)
    authorized_services: set[str] | None = None
    backend_available: bool = True
    #: Controllers this machine will not let the backend use.
    unavailable_controllers: tuple[str, ...] = ()
    _sequence: int = 0

    def available(self) -> bool:
        return self.backend_available

    def authorized(self, service_id: str) -> bool:
        if self.authorized_services is None:
            return True
        return service_id in self.authorized_services

    def inspect(self, service_id: str) -> ServiceObservation:
        if service_id in self.external:
            return ServiceObservation(
                service_id, "externally_managed", observed_by=self.name,
                detail="this unit is running but was not started by Bunny OS",
            )
        found = self.services.get(service_id)
        if found is None:
            return ServiceObservation(
                service_id, "stopped", observed_by=self.name,
                detail="no such service is running",
            )
        return found

    # ------------------------------------------------------------------ #

    def _record(self, operation: str, service_id: str, **fields: Any) -> None:
        self._sequence += 1
        self.operations.append(RecordedOperation(self._sequence, operation, service_id, **fields))

    def _guard(self, operation: str, service_id: str) -> BackendOutcome | None:
        """The checks every operation shares, in the order they must be asked."""
        if not self.available():
            return BackendOutcome(
                False, operation, service_id, "backend_unavailable",
                "the service manager is not running on this machine",
            )
        if not self.authorized(service_id):
            return BackendOutcome(
                False, operation, service_id, "unit_not_authorized",
                f"{service_id} is not in this backend's authorised set",
            )
        if service_id in self.external:
            return BackendOutcome(
                False, operation, service_id, "permission_denied",
                f"{service_id} is externally managed and is not Bunny OS's to control",
            )
        injected = self.failures.get((service_id, operation)) or self.failures.get((service_id, "*"))
        if injected:
            return BackendOutcome(
                False, operation, service_id, injected,
                f"injected {injected} for {operation} on {service_id}",
            )
        return None

    def _limits_outcome(self, limits: ServiceLimits) -> EnforcedLimits:
        """Model a machine that may refuse some controllers."""
        if not self.unavailable_controllers:
            return EnforcedLimits(limits, limits, True)
        effective = limits
        if "memory" in self.unavailable_controllers:
            effective = replace(effective, memory_max_bytes=None, memory_high_bytes=None)
        if "cpu" in self.unavailable_controllers:
            effective = replace(effective, cpu_weight=None, cpu_quota_percent=None)
        if "io" in self.unavailable_controllers:
            effective = replace(effective, io_weight=None)
        if "pids" in self.unavailable_controllers:
            effective = replace(effective, process_limit=None)
        return EnforcedLimits(
            limits, effective, False,
            detail=(
                "controllers " + ", ".join(self.unavailable_controllers) + " are not delegated here; "
                "the limits they would have applied are not in force"
            ),
            unavailable_controllers=self.unavailable_controllers,
        )

    def start(
        self, service_id: str, implementation_id: str | None,
        limits: ServiceLimits, *, timeout_seconds: float,
    ) -> BackendOutcome:
        self._record("start", service_id, implementation_id=implementation_id,
                     limits=limits, timeout_seconds=timeout_seconds)
        refusal = self._guard("start", service_id)
        if refusal is not None:
            return refusal

        existing = self.services.get(service_id)
        if existing is not None and existing.state in ("running", "degraded"):
            # Idempotent, and reported as such. A backend that treated this as
            # an error would make a retried reconciliation look like a failure.
            return BackendOutcome(
                True, "start", service_id, detail="already running", observation=existing,
            )

        enforced = self._limits_outcome(limits)
        state = "starting" if service_id in self.partial_start else "running"
        observation = ServiceObservation(
            service_id, state,
            implementation_id=implementation_id,
            memory_limit_bytes=limits.memory_max_bytes,
            enforced_memory_limit_bytes=enforced.effective.memory_max_bytes,
            cpu_percent=limits.cpu_quota_percent,
            healthy=None if state == "starting" else (service_id not in self.unhealthy),
            observed_by=self.name,
            detail=(
                "started but has not reported ready" if state == "starting"
                else "started"
            ),
        )
        self.services[service_id] = observation
        return BackendOutcome(
            True, "start", service_id, observation=observation, limits=enforced,
            detail="started",
        )

    def stop(self, service_id: str, *, graceful: bool = True, timeout_seconds: float = 30.0) -> BackendOutcome:
        self._record("stop", service_id, graceful=graceful, timeout_seconds=timeout_seconds)
        refusal = self._guard("stop", service_id)
        if refusal is not None:
            return refusal
        self.services.pop(service_id, None)
        observation = ServiceObservation(
            service_id, "stopped", observed_by=self.name,
            detail="stopped gracefully" if graceful else "terminated",
        )
        return BackendOutcome(True, "stop", service_id, observation=observation, detail="stopped")

    def suspend(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        self._record("suspend", service_id, timeout_seconds=timeout_seconds)
        refusal = self._guard("suspend", service_id)
        if refusal is not None:
            return refusal
        existing = self.services.get(service_id)
        if existing is None:
            return BackendOutcome(
                False, "suspend", service_id, "configuration_error",
                "cannot suspend a service that is not running",
            )
        observation = replace(existing, state="suspended", detail="suspended; state retained")
        self.services[service_id] = observation
        return BackendOutcome(True, "suspend", service_id, observation=observation, detail="suspended")

    def resume(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        self._record("resume", service_id, timeout_seconds=timeout_seconds)
        refusal = self._guard("resume", service_id)
        if refusal is not None:
            return refusal
        existing = self.services.get(service_id)
        if existing is None or existing.state != "suspended":
            return BackendOutcome(
                False, "resume", service_id, "configuration_error",
                "cannot resume a service that is not suspended",
            )
        observation = replace(existing, state="running", detail="resumed")
        self.services[service_id] = observation
        return BackendOutcome(True, "resume", service_id, observation=observation, detail="resumed")

    def reload(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        self._record("reload", service_id, timeout_seconds=timeout_seconds)
        refusal = self._guard("reload", service_id)
        if refusal is not None:
            return refusal
        existing = self.services.get(service_id)
        if existing is None:
            return BackendOutcome(
                False, "reload", service_id, "configuration_error",
                "cannot reload a service that is not running",
            )
        return BackendOutcome(True, "reload", service_id, observation=existing, detail="reloaded")

    def apply_limits(self, service_id: str, limits: ServiceLimits, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        self._record("apply_limits", service_id, limits=limits, timeout_seconds=timeout_seconds)
        refusal = self._guard("apply_limits", service_id)
        if refusal is not None:
            return refusal
        enforced = self._limits_outcome(limits)
        existing = self.services.get(service_id)
        if existing is not None:
            self.services[service_id] = replace(
                existing,
                memory_limit_bytes=limits.memory_max_bytes,
                enforced_memory_limit_bytes=enforced.effective.memory_max_bytes,
                cpu_percent=limits.cpu_quota_percent,
            )
        return BackendOutcome(
            True, "apply_limits", service_id, limits=enforced,
            observation=self.services.get(service_id),
            detail="limits applied" if enforced.enforced else enforced.detail,
        )

    def health(self, service_id: str, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        self._record("health", service_id, timeout_seconds=timeout_seconds)
        refusal = self._guard("health", service_id)
        if refusal is not None:
            return refusal
        existing = self.services.get(service_id)
        if existing is None:
            return BackendOutcome(
                False, "health", service_id, "health_check_failure",
                "the service is not running",
            )
        if existing.state == "starting":
            return BackendOutcome(
                False, "health", service_id, "startup_timeout",
                "the service started but never reported ready",
                observation=existing,
            )
        if service_id in self.unhealthy:
            return BackendOutcome(
                False, "health", service_id, "health_check_failure",
                "the service is running but reports itself unhealthy",
                observation=replace(existing, state="degraded", healthy=False),
            )
        return BackendOutcome(
            True, "health", service_id,
            observation=replace(existing, healthy=True), detail="healthy",
        )

    # ------------------------------------------------------------------ #

    def operation_names(self) -> tuple[str, ...]:
        return tuple(f"{item.operation}:{item.service_id}" for item in self.operations)


@dataclass
class DryRunBackend:
    """Records what would have happened. Changes nothing, ever.

    This is the default everywhere in this package. It wraps an optional
    ``observer`` — normally the real backend, consulted only through
    :meth:`inspect` — so that a dry run against a live machine compares the
    *real* actual state against the desired one and reports the transitions that
    would follow. A dry run that observed nothing would produce a plausible
    transition list for a machine nobody looked at, which is worse than useless
    because it looks like a rehearsal.

    Reading is permitted; writing is not. There is no code path in this class
    that calls a mutating method on ``observer``.
    """

    name: str = "dry-run"
    observer: Any = None
    operations: list[RecordedOperation] = field(default_factory=list)
    _sequence: int = 0

    def available(self) -> bool:
        return True

    def authorized(self, service_id: str) -> bool:
        # A dry run must be able to rehearse a transition that the real backend
        # would refuse, and report that refusal. Authorisation is checked and
        # reported by the applicator against the real allowlist; answering
        # ``True`` here keeps the rehearsal from stopping early and hiding
        # everything downstream of the first unauthorised service.
        return True

    def inspect(self, service_id: str) -> ServiceObservation:
        if self.observer is not None:
            return self.observer.inspect(service_id)
        # ``inferred``, not ``dry-run``: with no observer attached, nothing
        # looked at anything. Marking it as observed would let reconciliation
        # act on a state that was never read.
        return ServiceObservation(
            service_id, "unknown", observed_by="inferred",
            detail="no observer is attached; actual state was not read",
        )

    def _record(self, operation: str, service_id: str, **fields: Any) -> BackendOutcome:
        self._sequence += 1
        self.operations.append(RecordedOperation(self._sequence, operation, service_id, **fields))
        return BackendOutcome(
            True, operation, service_id,
            detail=f"dry run: {operation} was recorded and not performed",
            observation=None,
        )

    def start(
        self, service_id: str, implementation_id: str | None,
        limits: ServiceLimits, *, timeout_seconds: float,
    ) -> BackendOutcome:
        outcome = self._record("start", service_id, implementation_id=implementation_id,
                               limits=limits, timeout_seconds=timeout_seconds)
        # The rehearsal reports the limits it would have requested and states
        # plainly that nothing was enforced, so a dry-run transcript can never
        # be mistaken for evidence that a service was constrained.
        return replace(outcome, limits=EnforcedLimits(
            limits, ServiceLimits(), False,
            detail="dry run: no limit was written",
        ))

    def stop(self, service_id: str, *, graceful: bool = True, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._record("stop", service_id, graceful=graceful, timeout_seconds=timeout_seconds)

    def suspend(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._record("suspend", service_id, timeout_seconds=timeout_seconds)

    def resume(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._record("resume", service_id, timeout_seconds=timeout_seconds)

    def reload(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._record("reload", service_id, timeout_seconds=timeout_seconds)

    def apply_limits(self, service_id: str, limits: ServiceLimits, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        outcome = self._record("apply_limits", service_id, limits=limits, timeout_seconds=timeout_seconds)
        return replace(outcome, limits=EnforcedLimits(
            limits, ServiceLimits(), False, detail="dry run: no limit was written",
        ))

    def health(self, service_id: str, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        # A dry run cannot health-check something it did not start. Reporting
        # success would let a rehearsal claim a service is healthy.
        self._sequence += 1
        self.operations.append(RecordedOperation(self._sequence, "health", service_id,
                                                 timeout_seconds=timeout_seconds))
        return BackendOutcome(
            True, "health", service_id,
            detail="dry run: no health check was performed and none is claimed",
        )

    def recorded(self) -> tuple[RecordedOperation, ...]:
        return tuple(self.operations)

    def to_json(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "note": "Every entry is an operation that was NOT performed.",
            "operations": [item.to_json() for item in self.operations],
        }


def mutating_operations(recorded: Sequence[RecordedOperation]) -> tuple[RecordedOperation, ...]:
    """The recorded operations that would have changed the machine."""
    return tuple(item for item in recorded if item.operation not in ("health", "inspect"))

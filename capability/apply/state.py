# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Desired, actual and transition state.

Three questions, three types, and the distinction between them is the whole
design:

**Desired** is what the plan says. It is a projection of an
:class:`~capability.plan.ExecutionPlan` and it is never inferred from the
machine. If the desired state could be derived from what is running, a service
that started by accident would become a service that is supposed to be running.

**Actual** is what the machine can presently be observed to be. Emphatically not
what the applicator last did: an operation that reported success is evidence,
not proof, and a service that exited two seconds later is stopped no matter what
the start command returned. Every actual state carries where it was observed
from, and ``UNKNOWN`` is a real state rather than a default — a backend that
could not answer must say so, because "not observed" and "not running" lead to
opposite and equally irreversible actions.

**Transition** is one attempt to move one service from actual toward desired. It
is a record, not a command: it exists before the operation starts, is updated as
it proceeds, and survives its own failure so that what happened can be explained
afterwards.

The state vocabulary is deliberately wider than "running / stopped". Most of the
interesting states in an adaptive system are the waiting ones — waiting for a
dependency, for resources, for a person to approve something — and collapsing
them into ``stopped`` would throw away precisely the information a user needs in
order to understand why their machine is behaving as it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from . import RUNTIME_STATE_SCHEMA_VERSION

__all__ = [
    "ACTIVE_STATES",
    "ActualState",
    "DesiredService",
    "DesiredState",
    "OPERATIONS",
    "SERVICE_STATES",
    "ServiceObservation",
    "TERMINAL_RESULTS",
    "Transition",
    "TransitionResult",
    "WAITING_STATES",
    "desired_from_plan",
]

#: Every state a service may be observed in.
#:
#: ``externally_managed`` is the state that keeps the applicator honest on a
#: developer's machine: a unit that exists and is running but was not started by
#: Bunny OS is not ours to stop, and recording that as ``running`` would let a
#: reconciliation decide it may be shut down.
SERVICE_STATES = (
    "running",
    "stopped",
    "starting",
    "stopping",
    "suspended",
    "failed",
    "unknown",
    "externally_managed",
    "degraded",
    "waiting_for_approval",
    "waiting_for_dependency",
    "waiting_for_resources",
    "waiting_for_network",
    "remote_execution_pending",
    "remote_execution_active",
)

#: States in which the service is consuming resources on this machine and must
#: therefore hold a reservation. ``degraded`` is included: a service that is
#: unhealthy is still resident.
ACTIVE_STATES = frozenset({"running", "starting", "degraded", "suspended", "remote_execution_active"})

#: States that mean "the plan wants this, and something outside the applicator's
#: control has not happened yet". These never produce a transition — there is
#: nothing to do but wait — and they are reported rather than retried.
WAITING_STATES = frozenset({
    "waiting_for_approval",
    "waiting_for_dependency",
    "waiting_for_resources",
    "waiting_for_network",
    "remote_execution_pending",
})

#: What a transition may attempt. One verb per operation, and no verb that means
#: two things: ``restart`` is deliberately absent, because a restart is a stop
#: and a start with different rollback obligations and modelling it as one
#: operation hides the window in which the service is down.
OPERATIONS = (
    "start",
    "stop",
    "suspend",
    "resume",
    "reload",
    "apply_limits",
    "probe",
    "rollback",
)

#: How a transition ended. ``postponed`` and ``rejected`` are distinct on
#: purpose: postponed means "not now, ask again", rejected means "not this plan,
#: get a new one".
TERMINAL_RESULTS = ("succeeded", "failed", "rolled_back", "postponed", "rejected", "cancelled")


# --------------------------------------------------------------------------- #
# Desired
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DesiredService:
    """What the plan wants for one service.

    ``memory_limit_bytes`` and ``cpu_percent`` are ceilings taken verbatim from
    the decision. The applicator may apply less than this — a cgroup that
    refuses a write leaves the service unconstrained and that is reported — but
    it has no code path that applies more, which is the decision boundary
    expressed as a data flow rather than as a rule someone has to remember.
    """

    service_id: str
    should_run: bool
    implementation_id: str | None
    locality: str                       # "local" | "remote" | "none"
    memory_limit_bytes: int
    cpu_percent: float
    essential: bool
    priority: int
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    suspendable: bool = True
    requires_approval: bool = False
    #: The plan's action verbatim, so an explanation can quote it.
    action: str = "reject"
    #: Reason codes from the decision, carried so the applicator can explain a
    #: refusal without re-deriving it.
    reason_codes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "shouldRun": self.should_run,
            "implementationId": self.implementation_id,
            "locality": self.locality,
            "memoryLimitBytes": self.memory_limit_bytes,
            "cpuPercent": round(self.cpu_percent, 1),
            "essential": self.essential,
            "priority": self.priority,
            "requires": list(self.requires),
            "conflictsWith": list(self.conflicts_with),
            "suspendable": self.suspendable,
            "requiresApproval": self.requires_approval,
            "action": self.action,
            "reasonCodes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class DesiredState:
    """The whole plan, projected into the shape reconciliation consumes."""

    plan_id: str
    revision: int
    services: Mapping[str, DesiredService] = field(default_factory=dict)

    def get(self, service_id: str) -> DesiredService | None:
        return self.services.get(service_id)

    def running_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.service_id for item in self.services.values() if item.should_run))

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": RUNTIME_STATE_SCHEMA_VERSION,
            "planId": self.plan_id,
            "revision": self.revision,
            "services": [self.services[key].to_json() for key in sorted(self.services)],
        }


def desired_from_plan(plan: Any, registry: Any) -> DesiredState:
    """Project a plan into a desired state. The only way one is ever built.

    Dependency and conflict edges come from the registry rather than from the
    plan, because they are declarations about the services and do not change
    when a plan does. Everything else comes from the decision, and nothing is
    recomputed: if the engine granted 256 MiB, this says 256 MiB, whatever the
    manifest happens to declare today.
    """
    services: dict[str, DesiredService] = {}
    for decision in plan.decisions:
        manifest = registry.get(decision.service_id)
        implementation = (
            manifest.implementation(decision.implementation_id)
            if manifest is not None and decision.implementation_id else None
        )
        locality = implementation.locality if implementation is not None else "none"
        services[decision.service_id] = DesiredService(
            service_id=decision.service_id,
            should_run=decision.running,
            implementation_id=decision.implementation_id,
            locality=locality,
            memory_limit_bytes=decision.memory_grant_bytes,
            cpu_percent=decision.cpu_percent,
            essential=bool(manifest is not None and manifest.essential),
            priority=manifest.priority if manifest is not None else 0,
            requires=tuple(manifest.requires) if manifest is not None else (),
            conflicts_with=tuple(manifest.conflicts_with) if manifest is not None else (),
            suspendable=bool(manifest.suspendable) if manifest is not None else True,
            requires_approval=decision.requires_approval,
            action=decision.action,
            reason_codes=decision.reason_codes(),
        )
    identity = getattr(plan, "identity", None)
    return DesiredState(
        plan_id=identity.plan_id if identity is not None else "",
        revision=identity.revision if identity is not None else 0,
        services=services,
    )


# --------------------------------------------------------------------------- #
# Actual
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ServiceObservation:
    """What one service is, as far as anything can presently tell.

    ``observed_by`` is not decoration. A state read from systemd and a state
    inferred from a reservation ledger have very different standing, and a
    rollback decision that treats them the same is a rollback that can act on a
    guess. Anything reported by a backend that did not actually look carries
    ``inferred``, and the reconciliation engine will not stop a service on the
    strength of an inference alone.
    """

    service_id: str
    state: str
    implementation_id: str | None = None
    memory_limit_bytes: int | None = None
    #: What the kernel or service manager reports is actually enforced, which
    #: can be less than what was asked for. ``None`` means nothing enforced or
    #: nothing observable.
    enforced_memory_limit_bytes: int | None = None
    cpu_percent: float | None = None
    healthy: bool | None = None
    #: Whether a person is actively using this service's output right now. Set
    #: by the backend from a declared foreground marker, never guessed.
    user_facing: bool = False
    #: Whether the service has declared it holds unsaved user work.
    holds_unsaved_work: bool = False
    observed_by: str = "inferred"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in SERVICE_STATES:
            raise ValueError(f"unknown service state: {self.state!r}")

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def observed(self) -> bool:
        """Whether this came from looking at the machine rather than from memory."""
        return self.observed_by not in ("inferred", "")

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "state": self.state,
            "implementationId": self.implementation_id,
            "memoryLimitBytes": self.memory_limit_bytes,
            "enforcedMemoryLimitBytes": self.enforced_memory_limit_bytes,
            "cpuPercent": self.cpu_percent,
            "healthy": self.healthy,
            "userFacing": self.user_facing,
            "holdsUnsavedWork": self.holds_unsaved_work,
            "observedBy": self.observed_by,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ActualState:
    """Every service the applicator could observe, and when it looked."""

    services: Mapping[str, ServiceObservation] = field(default_factory=dict)
    observed_at_monotonic: float = 0.0
    #: Backends that could not be consulted at all. Their services are reported
    #: ``unknown`` rather than omitted, so that a missing backend cannot read as
    #: an empty machine.
    unavailable_backends: tuple[str, ...] = ()

    def get(self, service_id: str) -> ServiceObservation:
        """The observation, or an explicit unknown. Never a silent default."""
        found = self.services.get(service_id)
        if found is not None:
            return found
        return ServiceObservation(
            service_id, "unknown", observed_by="inferred",
            detail="no backend reported on this service",
        )

    def active_ids(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, item in self.services.items() if item.active))

    def with_service(self, observation: ServiceObservation) -> "ActualState":
        merged = dict(self.services)
        merged[observation.service_id] = observation
        return replace(self, services=merged)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": RUNTIME_STATE_SCHEMA_VERSION,
            "observedAtMonotonic": self.observed_at_monotonic,
            "unavailableBackends": list(self.unavailable_backends),
            "services": [self.services[key].to_json() for key in sorted(self.services)],
        }


# --------------------------------------------------------------------------- #
# Transition
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TransitionResult:
    """How a transition ended, and everything needed to explain it."""

    result: str
    failure_class: str | None = None
    detail: str = ""
    #: Set when the applicator wants the engine to look again.
    reevaluation_reason: str | None = None

    def __post_init__(self) -> None:
        if self.result not in TERMINAL_RESULTS:
            raise ValueError(f"unknown transition result: {self.result!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "failureClass": self.failure_class,
            "detail": self.detail,
            "reevaluationReason": self.reevaluation_reason,
        }


@dataclass(frozen=True)
class Transition:
    """One operation moving one service from where it is toward where it should be.

    Deterministically identified. ``transition_id`` is derived from the plan,
    the service and the attempt number rather than from a random source or a
    clock, so that a test can assert on the identifier of the transition it
    expects, and so that two processes recovering the same interrupted work
    agree on what to call it.
    """

    transition_id: str
    service_id: str
    plan_id: str
    source_state: str
    target_state: str
    operation: str
    #: Ordering key within one reconciliation. Lower runs first.
    sequence: int = 0
    started_at_monotonic: float | None = None
    completed_at_monotonic: float | None = None
    result: TransitionResult | None = None
    retry_count: int = 0
    #: Ledger reservation id held for the duration, if any.
    reservation_id: str | None = None
    rollback_state: str = "none"       # "none" | "pending" | "completed" | "failed" | "unnecessary"
    #: Structured explanation lines. Facts observed, not prose assembled at the
    #: point of refusal — see :mod:`capability.apply.explain`.
    explanation: tuple[Mapping[str, Any], ...] = ()
    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise ValueError(f"unknown operation: {self.operation!r}")
        for name, value in (("source", self.source_state), ("target", self.target_state)):
            if value not in SERVICE_STATES:
                raise ValueError(f"unknown {name} state: {value!r}")

    @property
    def finished(self) -> bool:
        return self.result is not None

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.result.result == "succeeded"

    def duration_seconds(self) -> float | None:
        if self.started_at_monotonic is None or self.completed_at_monotonic is None:
            return None
        return max(0.0, self.completed_at_monotonic - self.started_at_monotonic)

    def to_json(self) -> dict[str, Any]:
        return {
            "transitionId": self.transition_id,
            "serviceId": self.service_id,
            "planId": self.plan_id,
            "sourceState": self.source_state,
            "targetState": self.target_state,
            "operation": self.operation,
            "sequence": self.sequence,
            "startedAtMonotonic": self.started_at_monotonic,
            "completedAtMonotonic": self.completed_at_monotonic,
            "durationSeconds": self.duration_seconds(),
            "timeoutSeconds": self.timeout_seconds,
            "result": self.result.to_json() if self.result is not None else None,
            "retryCount": self.retry_count,
            "reservationId": self.reservation_id,
            "rollbackState": self.rollback_state,
            "explanation": [dict(item) for item in self.explanation],
        }


def transition_id(plan_id: str, service_id: str, operation: str, attempt: int) -> str:
    """A stable identifier for one attempt at one operation.

    Derived rather than generated: a UUID here would make every audit record
    unreproducible and every test assert on a value it cannot predict. The
    attempt number is part of it so that a retry is a distinguishable event
    rather than an overwrite of the record that explains why it was needed.
    """
    return f"{plan_id}:{service_id}:{operation}:{attempt}"


def order_key(desired: DesiredService) -> tuple[int, int, str]:
    """Total, stable ordering over services.

    Essential first, then descending priority, then service id. Identical to
    :meth:`capability.registry.Registry.ordered`, and deliberately so: the order
    resources are handed out in and the order transitions are applied in must be
    the same, or a service can be funded by the engine and started after the
    service that was supposed to have yielded to it.
    """
    return (0 if desired.essential else 1, -desired.priority, desired.service_id)


def summarize(transitions: Sequence[Transition]) -> dict[str, Any]:
    """Counts by result and by operation, for a status line."""
    by_result: dict[str, int] = {}
    by_operation: dict[str, int] = {}
    for item in transitions:
        key = item.result.result if item.result is not None else "pending"
        by_result[key] = by_result.get(key, 0) + 1
        by_operation[item.operation] = by_operation.get(item.operation, 0) + 1
    return {
        "total": len(transitions),
        "byResult": dict(sorted(by_result.items())),
        "byOperation": dict(sorted(by_operation.items())),
    }

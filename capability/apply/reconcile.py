# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The reconciliation engine: desired state minus actual state, safely ordered.

Given what should be running and what is running, produce the ordered set of
operations that would close the gap — and, just as importantly, the set of gaps
that must **not** be closed right now, each with the reason.

This function is pure. It reads state and returns a plan of transitions; it
starts nothing. That separation is what makes the ten properties §20 requires
testable: idempotency, determinism, dependency ordering and the rest are
assertions about a returned value, not about the state of somebody's computer
after a test ran.

**Stops before starts, always.** The whole reconciliation is two phases:
everything that yields resources happens before anything that consumes them. A
reconciliation that interleaved them would need to reason about whether the
memory being freed in step 4 is the memory being spent in step 2, and it would
sometimes get that wrong on exactly the machine where it matters.

**Dependency order within each phase.** Dependencies start before dependents;
dependents stop before the dependencies they need. These are the same edge read
in two directions, so one topological sort produces both — forward for starts,
reversed for stops.

**Determinism comes from a total order, not from luck.** Every sort in this
module has an explicit tie-break down to the service id. There is no place where
two services could legitimately swap places between runs, because a
reconciliation that reordered itself would make a transition log impossible to
compare against a previous one.

**The decision boundary.** Nothing here decides that a service should run. The
desired state is read, never adjusted. Every output of this module is one of:
an operation the plan implies, or a refusal to perform one. There is no third
kind of output, and that is checked by the type — a :class:`Blocked` carries a
reason and no operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .adaptation import AdaptationAssessment, assess_adaptation
from .state import (
    ActualState,
    DesiredService,
    DesiredState,
    ServiceObservation,
    Transition,
    order_key,
    transition_id,
)

__all__ = [
    "Blocked",
    "DEFAULT_TIMEOUTS",
    "ReconciliationPlan",
    "ReconciliationSettings",
    "reconcile",
    "start_order",
    "stop_order",
]

#: Per-operation deadlines, in seconds. Every transition carries one; there is
#: no unbounded operation anywhere in this package. Start is the longest because
#: a service that loads a model legitimately takes time; probe is the shortest
#: because it only asks a question.
DEFAULT_TIMEOUTS: Mapping[str, float] = {
    "start": 60.0,
    "stop": 30.0,
    "suspend": 15.0,
    "resume": 15.0,
    "reload": 15.0,
    "apply_limits": 10.0,
    "probe": 5.0,
    "rollback": 45.0,
}

#: Why a transition was not produced. Distinct from failure classes: nothing was
#: attempted, so nothing failed.
BLOCK_REASONS = (
    "already_converged",
    "waiting_for_dependency",
    "waiting_for_resources",
    "waiting_for_approval",
    "waiting_for_network",
    "conflict",
    "externally_managed",
    "essential_protected",
    "user_work_protected",
    "circuit_open",
    "retry_backoff",
    "state_unknown",
    "not_authorized",
    "plan_forbids",
)


@dataclass(frozen=True)
class Blocked:
    """A gap between desired and actual that must not be closed right now."""

    service_id: str
    reason: str
    detail: str
    desired_action: str = ""
    actual_state: str = ""
    #: What the user still has. Never empty for a user-visible block.
    fallback: str = ""
    adaptation: AdaptationAssessment | None = None

    def __post_init__(self) -> None:
        if self.reason not in BLOCK_REASONS:
            raise ValueError(f"unknown block reason: {self.reason!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "reason": self.reason,
            "detail": self.detail,
            "desiredAction": self.desired_action,
            "actualState": self.actual_state,
            "fallback": self.fallback,
            "adaptation": self.adaptation.to_json() if self.adaptation is not None else None,
        }


@dataclass(frozen=True)
class ReconciliationSettings:
    """The operational judgements reconciliation is allowed to make.

    Every one of these is a way to be *more* cautious than the plan. There is
    deliberately no setting that permits anything the plan did not ask for.
    """

    #: Stopping an essential service needs this. Off by default: an essential
    #: service is the machine's ability to explain itself, and a reconciliation
    #: that takes it away on a resource judgement removes the thing that would
    #: have reported the shortage.
    allow_essential_stop: bool = False
    #: Terminating a service that declares unsaved work or foreground use needs
    #: an approval. Off means no approval has been given, which means no.
    approved_interruptions: frozenset[str] = frozenset()
    #: Services whose start has been approved where the plan required it.
    approved_starts: frozenset[str] = frozenset()
    #: The documented emergency policy is in force.
    emergency: bool = False
    timeouts: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TIMEOUTS))
    #: Memory the applicator may still promise, from the ledger. Starts that do
    #: not fit are blocked rather than attempted.
    available_bytes: int | None = None
    #: Reported so that a block can name the reserve it is protecting.
    protected_reserve_bytes: int = 0
    #: Services whose circuit breaker is open.
    circuit_open: frozenset[str] = frozenset()
    #: ``{service id: monotonic time the next attempt becomes due}``. A service
    #: inside its backoff window is blocked rather than attempted, which is how
    #: the retry schedule survives a restart of the applicator: the delay lives
    #: in a journal that is consulted here, not in a sleep somebody is holding.
    retry_not_before: Mapping[str, float] = field(default_factory=dict)
    #: Services this backend is not authorised to control.
    unauthorized: frozenset[str] = frozenset()

    def timeout_for(self, operation: str) -> float:
        return float(self.timeouts.get(operation, DEFAULT_TIMEOUTS.get(operation, 30.0)))


@dataclass(frozen=True)
class ReconciliationPlan:
    """The ordered transitions, and everything deliberately not done."""

    plan_id: str
    revision: int
    transitions: tuple[Transition, ...] = ()
    blocked: tuple[Blocked, ...] = ()
    notes: tuple[str, ...] = ()
    #: Set when reconciliation concluded the plan itself needs revisiting.
    reevaluation_reason: str | None = None

    @property
    def converged(self) -> bool:
        """Whether the machine already matches the plan, as far as it can.

        A blocked service does not prevent convergence from being reported: the
        machine is as close to the plan as it is permitted to get, and calling
        that "not converged" would make an approval nobody answers look like a
        reconciliation loop that never finishes.
        """
        return not self.transitions

    def for_service(self, service_id: str) -> tuple[Transition, ...]:
        return tuple(item for item in self.transitions if item.service_id == service_id)

    def block_for(self, service_id: str) -> Blocked | None:
        for item in self.blocked:
            if item.service_id == service_id:
                return item
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "revision": self.revision,
            "converged": self.converged,
            "reevaluationReason": self.reevaluation_reason,
            "transitions": [item.to_json() for item in self.transitions],
            "blocked": [item.to_json() for item in self.blocked],
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


def start_order(services: Mapping[str, DesiredService]) -> tuple[str, ...]:
    """Dependencies before dependents, deterministically.

    A depth-first walk seeded in :func:`~capability.apply.state.order_key` order,
    which is the same order the budget engine hands out memory in. Keeping the
    two identical means a service cannot be funded ahead of another and then
    started behind it.

    Cycles cannot occur — :func:`capability.registry.build_registry` refuses a
    registry containing one — but the walk guards against them anyway, because
    this function also runs against desired states assembled in tests, and a
    guard that costs one set membership is cheaper than a stack overflow.
    """
    emitted: list[str] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def emit(service_id: str) -> None:
        if service_id in placed or service_id in visiting:
            return
        visiting.add(service_id)
        service = services.get(service_id)
        for dependency in sorted(service.requires if service is not None else ()):
            if dependency in services:
                emit(dependency)
        visiting.discard(service_id)
        placed.add(service_id)
        emitted.append(service_id)

    for service in sorted(services.values(), key=order_key):
        emit(service.service_id)
    return tuple(emitted)


def stop_order(services: Mapping[str, DesiredService]) -> tuple[str, ...]:
    """Dependents before the dependencies they need.

    The exact reverse of :func:`start_order`. Written as a reversal rather than
    as a second walk so the two cannot disagree: a service that starts third
    from the end stops third from the beginning, by construction.
    """
    return tuple(reversed(start_order(services)))


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


def reconcile(
    desired: DesiredState,
    actual: ActualState,
    *,
    settings: ReconciliationSettings | None = None,
    now: float = 0.0,
) -> ReconciliationPlan:
    """Produce the ordered, safe transitions from ``actual`` toward ``desired``."""
    config = settings if settings is not None else ReconciliationSettings()
    transitions: list[Transition] = []
    blocked: list[Blocked] = []
    notes: list[str] = []
    sequence = 0

    services = desired.services
    conflicts = _conflicting_desired_pairs(services)
    if conflicts:
        # A plan that wants two mutually exclusive services running is not a
        # plan to reconcile carefully; it is a plan to refuse. Acting on half of
        # it would leave the machine in a state neither the plan nor the user
        # asked for.
        return ReconciliationPlan(
            desired.plan_id, desired.revision,
            blocked=tuple(
                Blocked(
                    service_id, "conflict",
                    f"{service_id} and {other} are declared mutually exclusive and the plan wants both running",
                    desired_action=services[service_id].action,
                    actual_state=actual.get(service_id).state,
                )
                for service_id, other in conflicts
            ),
            notes=("this plan is internally inconsistent and no part of it was applied",),
            reevaluation_reason="apply_time_validation_failed",
        )

    # -- Phase 1: everything that yields resources ------------------------- #
    for service_id in stop_order(services):
        service = services[service_id]
        observation = actual.get(service_id)
        outcome = _plan_release(service, observation, config)
        if outcome is None:
            continue
        if isinstance(outcome, Blocked):
            blocked.append(outcome)
            continue
        operation, target = outcome
        sequence += 1
        transitions.append(_transition(
            desired, service, observation, operation, target, sequence, config,
        ))

    # -- Phase 2: everything that consumes them ---------------------------- #
    #
    # Availability is projected forward through the phase: each admitted start
    # reduces what the next one may take. Without that, five services would each
    # be told there is room for them and the last four would fail at the ledger.
    projected = config.available_bytes
    if projected is not None:
        projected += _released_bytes(transitions, actual)

    starting: set[str] = set()
    for service_id in start_order(services):
        service = services[service_id]
        observation = actual.get(service_id)
        outcome = _plan_acquire(service, observation, config, actual, starting, projected, now)
        if outcome is None:
            continue
        if isinstance(outcome, Blocked):
            blocked.append(outcome)
            continue
        operation, target = outcome
        sequence += 1
        transitions.append(_transition(
            desired, service, observation, operation, target, sequence, config,
        ))
        if operation == "start":
            starting.add(service_id)
            if projected is not None:
                projected = max(0, projected - service.memory_limit_bytes)

    if actual.unavailable_backends:
        notes.append(
            "these backends could not be consulted, so services they own are reported unknown "
            "rather than stopped: " + ", ".join(sorted(actual.unavailable_backends))
        )

    return ReconciliationPlan(
        desired.plan_id, desired.revision,
        transitions=tuple(transitions),
        blocked=tuple(sorted(blocked, key=lambda item: item.service_id)),
        notes=tuple(notes),
    )


def _transition(
    desired: DesiredState,
    service: DesiredService,
    observation: ServiceObservation,
    operation: str,
    target: str,
    sequence: int,
    config: ReconciliationSettings,
) -> Transition:
    return Transition(
        transition_id=transition_id(desired.plan_id, service.service_id, operation, 1),
        service_id=service.service_id,
        plan_id=desired.plan_id,
        source_state=observation.state,
        target_state=target,
        operation=operation,
        sequence=sequence,
        timeout_seconds=config.timeout_for(operation),
        explanation=(
            {
                "fact": "desired",
                "action": service.action,
                "implementationId": service.implementation_id,
                "memoryLimitBytes": service.memory_limit_bytes,
            },
            {
                "fact": "actual",
                "state": observation.state,
                "observedBy": observation.observed_by,
                "implementationId": observation.implementation_id,
            },
            {
                "fact": "operation",
                "operation": operation,
                "timeoutSeconds": config.timeout_for(operation),
            },
        ),
    )


def _plan_release(
    service: DesiredService,
    observation: ServiceObservation,
    config: ReconciliationSettings,
) -> tuple[str, str] | Blocked | None:
    """What, if anything, must be taken away from this service.

    Returns an ``(operation, target_state)`` pair, a :class:`Blocked`, or
    ``None`` when there is nothing to do.
    """
    # Checked before activity, not after. ``externally_managed`` is deliberately
    # not an active state — it must never hold a Bunny OS reservation — but a
    # plan that wants such a service stopped still deserves an answer, and
    # falling through the "not active, nothing to do" return would silently
    # report convergence on a machine where somebody else's service is running.
    if observation.state == "externally_managed":
        if service.should_run:
            return None
        return Blocked(
            service.service_id, "externally_managed",
            "this service is running but was not started by Bunny OS, so it is not Bunny OS's to stop",
            desired_action=service.action, actual_state=observation.state,
            fallback="the service keeps running under whatever started it",
        )

    if not observation.active:
        return None

    # A service the plan still wants running is only released when the plan
    # wants it *differently* — a changed implementation, which is a stop
    # followed by a start in the next phase.
    if service.should_run:
        if service.action == "start_remote":
            return None
        if observation.implementation_id == service.implementation_id:
            return None
        if observation.state == "suspended":
            # Resuming into the wrong implementation is not a resume. Fall
            # through to a stop so the correct one can start.
            pass
        replacement = True
    else:
        replacement = False

    if not observation.observed:
        # Never stop something on the strength of an inference. "I do not know
        # what this is" and "this is running and should not be" call for
        # opposite actions, and the cost of guessing wrong is a stopped service.
        return Blocked(
            service.service_id, "state_unknown",
            f"{service.service_id} is believed active but was not observed by any backend; "
            "nothing is stopped on the strength of an inference",
            desired_action=service.action, actual_state=observation.state,
            fallback="the service is left as it is until a backend can report on it",
        )

    if service.service_id in config.unauthorized:
        return Blocked(
            service.service_id, "not_authorized",
            "the backend is not authorised to control this service",
            desired_action=service.action, actual_state=observation.state,
        )

    # Choose the gentlest operation the plan permits.
    if service.action == "suspend" and service.suspendable and observation.state == "running":
        operation, target = "suspend", "suspended"
    else:
        operation, target = "stop", "stopped"

    assessment = assess_adaptation(operation, service, observation, emergency=config.emergency)

    if service.essential and not config.allow_essential_stop:
        return Blocked(
            service.service_id, "essential_protected",
            f"{service.service_id} is an essential service and stopping it needs an explicit "
            "allowance; the applicator does not take the control plane away on its own judgement",
            desired_action=service.action, actual_state=observation.state,
            fallback="the essential service keeps running and the shortfall is reported instead",
            adaptation=assessment,
        )

    if assessment.requires_approval and service.service_id not in config.approved_interruptions:
        return Blocked(
            service.service_id, "user_work_protected",
            "; ".join(assessment.reasons) or "this transition would interrupt work in progress",
            desired_action=service.action, actual_state=observation.state,
            fallback=assessment.fallback,
            adaptation=assessment,
        )

    if replacement:
        return operation, target
    return operation, target


def _plan_acquire(
    service: DesiredService,
    observation: ServiceObservation,
    config: ReconciliationSettings,
    actual: ActualState,
    starting: set[str],
    projected_bytes: int | None,
    now: float,
) -> tuple[str, str] | Blocked | None:
    """What, if anything, must be given to this service."""
    if not service.should_run:
        return None

    if service.action == "start_remote":
        # Remote work is dispatched through the remote state machine, not by
        # starting a local unit. Reconciliation records that it is pending and
        # leaves the dispatch to the layer that can authenticate a provider.
        return None

    if observation.state == "externally_managed":
        return Blocked(
            service.service_id, "externally_managed",
            "a service by this name is already running under other management; "
            "Bunny OS will not start a second one",
            desired_action=service.action, actual_state=observation.state,
        )

    if service.service_id in config.unauthorized:
        return Blocked(
            service.service_id, "not_authorized",
            "the backend is not authorised to control this service",
            desired_action=service.action, actual_state=observation.state,
        )

    if service.requires_approval and service.service_id not in config.approved_starts:
        return Blocked(
            service.service_id, "waiting_for_approval",
            "the plan recorded that this service needs an approval that has not been given",
            desired_action=service.action, actual_state=observation.state,
            fallback="the feature stays unavailable and nothing is sent anywhere",
        )

    # Dependencies must be up, or be coming up in this same reconciliation.
    missing = [
        dependency for dependency in sorted(service.requires)
        if dependency not in starting and not actual.get(dependency).active
    ]
    if missing:
        return Blocked(
            service.service_id, "waiting_for_dependency",
            f"{service.service_id} requires {', '.join(missing)}, which "
            + ("is" if len(missing) == 1 else "are")
            + " neither running nor starting in this reconciliation",
            desired_action=service.action, actual_state=observation.state,
        )

    # A conflicting service that is still up blocks this one. The stop phase has
    # already run, so anything still active here is something the plan did not
    # ask to stop.
    live_conflicts = [
        other for other in sorted(service.conflicts_with)
        if actual.get(other).active and other not in _stopped_this_pass(actual, starting)
    ]
    if live_conflicts:
        return Blocked(
            service.service_id, "conflict",
            f"{', '.join(live_conflicts)} is running and is declared mutually exclusive with "
            f"{service.service_id}",
            desired_action=service.action, actual_state=observation.state,
        )

    if service.service_id in config.circuit_open:
        return Blocked(
            service.service_id, "circuit_open",
            f"{service.service_id} has failed repeatedly; further attempts are paused until "
            "the recovery window elapses",
            desired_action=service.action, actual_state=observation.state,
            fallback="the feature stays unavailable rather than the machine retrying a failure in a loop",
        )

    not_before = config.retry_not_before.get(service.service_id)
    if not_before is not None and now < not_before:
        return Blocked(
            service.service_id, "retry_backoff",
            f"{service.service_id} failed recently; the next attempt is due in "
            f"{not_before - now:.0f}s",
            desired_action=service.action, actual_state=observation.state,
            fallback="the feature stays unavailable until the backoff elapses",
        )

    if observation.state == "suspended":
        if observation.implementation_id == service.implementation_id:
            return "resume", "running"
        # A suspended service in the wrong implementation was stopped in phase
        # one; it starts here.

    if observation.state in ("running", "degraded"):
        if observation.implementation_id != service.implementation_id:
            # Phase one stopped it, so it starts here.
            pass
        elif _limits_match(service, observation):
            return None
        else:
            return "apply_limits", observation.state

    if observation.state == "starting":
        # Already on its way. Starting it again would enqueue a second job.
        return None

    if observation.state == "unknown" and not observation.observed:
        return Blocked(
            service.service_id, "state_unknown",
            f"{service.service_id} could not be observed, so it is not started; "
            "starting a service that may already be running risks two of them",
            desired_action=service.action, actual_state=observation.state,
            fallback="the service is left alone until a backend can report on it",
        )

    if projected_bytes is not None and service.memory_limit_bytes > projected_bytes:
        return Blocked(
            service.service_id, "waiting_for_resources",
            f"{service.service_id} needs {service.memory_limit_bytes} bytes and "
            f"{projected_bytes} bytes remain after the reserve of "
            f"{config.protected_reserve_bytes} bytes",
            desired_action=service.action, actual_state=observation.state,
            fallback="the service stays stopped rather than the machine drawing on its protected reserve",
        )

    return "start", "running"


def _limits_match(service: DesiredService, observation: ServiceObservation) -> bool:
    """Whether what is enforced already equals what the plan wants.

    Compares the *enforced* figure, not the requested one. A service whose
    memory limit was requested and never applied is not converged, and treating
    it as converged would leave it permanently unconstrained while reporting
    that everything matched.
    """
    if service.memory_limit_bytes <= 0:
        return True
    return observation.enforced_memory_limit_bytes == service.memory_limit_bytes


def _stopped_this_pass(actual: ActualState, starting: set[str]) -> frozenset[str]:
    """Placeholder for services the stop phase has already dealt with.

    Reconciliation returns a plan rather than executing it, so nothing has
    actually stopped yet; a conflict against a service scheduled to stop is
    resolved by the two-phase ordering. This returns an empty set and exists so
    the conflict check reads in the order it is reasoned about.
    """
    return frozenset()


def _released_bytes(transitions: Sequence[Transition], actual: ActualState) -> int:
    """Memory the stop phase will hand back.

    Only from services that were actually observed holding it. A suspend
    releases nothing: a frozen service keeps every page it had, and counting it
    as freed would let the next start be admitted against memory that is still
    occupied.
    """
    total = 0
    for item in transitions:
        if item.operation != "stop":
            continue
        observation = actual.get(item.service_id)
        if observation.observed and observation.enforced_memory_limit_bytes:
            total += observation.enforced_memory_limit_bytes
    return total


def _conflicting_desired_pairs(services: Mapping[str, DesiredService]) -> tuple[tuple[str, str], ...]:
    """Pairs the plan wants running that declare each other exclusive."""
    running = {key for key, item in services.items() if item.should_run}
    found: list[tuple[str, str]] = []
    for service_id in sorted(running):
        for other in sorted(services[service_id].conflicts_with):
            if other in running:
                found.append((service_id, other))
    return tuple(found)

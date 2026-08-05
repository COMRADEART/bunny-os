# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The applicator: every transition as a small transaction.

:mod:`capability.apply.reconcile` decides what to do. This decides how to do it
safely, and the difference is entirely about what happens when something goes
wrong halfway.

A start is seven steps and each one can fail::

    revalidate -> reserve -> apply limits -> start
               -> confirm state -> health check -> commit

Failing at step six with the first five completed leaves a machine with a
running-but-unhealthy process holding a reservation nobody will release. So
every step records what it did, and failure walks the record backwards::

    record failure -> stop the partial service -> restore the previous
    implementation if that is safe -> release the reservation -> record the
    rollback -> schedule or refuse a retry

Three rules govern the rollback path:

**A rollback may not make things worse.** Restoring a previous implementation is
attempted only when it can be reserved and started; if it cannot, the service is
left stopped and that is reported, because a rollback that overcommits the
machine has traded a failed service for a failed machine.

**Cleanup does not fail.** Every release is idempotent and every stop of a
partial service tolerates the service not being there. A cleanup path that can
itself raise is a cleanup path that leaks.

**Retries are scheduled, not slept through.** A failure sets a deadline in the
retry journal and returns. The next reconciliation picks it up. Nothing in this
module sleeps, so nothing here can hold a reconciliation open, and the retry
schedule survives the process being restarted.

The default configuration applies nothing: :class:`ApplicatorSettings` starts in
dry-run against a :class:`~capability.apply.backends.DryRunBackend`, and moving
off that requires saying so twice — once when constructing the backend, once in
the settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from . import SUPPORTED_PLAN_SCHEMA_VERSION
from .adaptation import assess_adaptation
from .approval import ApprovalStore, DenyingApprovalStore, request_for_transition
from .audit import AuditSink, InMemoryAuditSink
from .backends import BackendOutcome, DryRunBackend, ServiceLimits
from .failures import CircuitBreaker, RetryJournal, RetryPolicy, classify_exception, needs_reevaluation
from .identity import PlanIdentity
from .ledger import InMemoryLedger, LedgerError
from .reconcile import (
    Blocked,
    ReconciliationPlan,
    ReconciliationSettings,
    reconcile,
)
from .revalidate import RevalidationVerdict, revalidate_plan, revalidate_transition
from .state import (
    ActualState,
    DesiredService,
    DesiredState,
    ServiceObservation,
    Transition,
    TransitionResult,
    desired_from_plan,
    summarize,
)

__all__ = [
    "ApplyReport",
    "Applicator",
    "ApplicatorSettings",
]


@dataclass(frozen=True)
class ApplicatorSettings:
    """How the applicator is allowed to behave. Cautious by construction."""

    #: Record intentions, change nothing. The default, and the only value at
    #: which a developer checkout is safe by accident rather than by care.
    dry_run: bool = True
    #: Permit stopping an essential service. Requires an operator to say so.
    allow_essential_stop: bool = False
    #: The documented emergency policy is in force.
    emergency: bool = False
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    #: Attempt to restore the previous implementation when a replacement fails.
    rollback_to_previous: bool = True
    #: Bound on transitions performed in one pass, so a pathological plan cannot
    #: occupy the machine indefinitely. Anything beyond it is left for the next
    #: reconciliation, which is exactly what a reconciliation loop is for.
    maximum_transitions_per_pass: int = 32

    def to_json(self) -> dict[str, Any]:
        return {
            "dryRun": self.dry_run,
            "allowEssentialStop": self.allow_essential_stop,
            "emergency": self.emergency,
            "rollbackToPrevious": self.rollback_to_previous,
            "maximumTransitionsPerPass": self.maximum_transitions_per_pass,
            "retry": self.retry.to_json(),
        }


@dataclass(frozen=True)
class ApplyReport:
    """Everything that happened in one pass, and everything that did not."""

    plan_id: str
    revision: int
    dry_run: bool
    applied: tuple[Transition, ...] = ()
    blocked: tuple[Blocked, ...] = ()
    validation: RevalidationVerdict | None = None
    reevaluation_reason: str | None = None
    notes: tuple[str, ...] = ()
    #: Reservations reclaimed from a previous run at the start of this one.
    reclaimed: tuple[str, ...] = ()

    @property
    def converged(self) -> bool:
        return not self.applied and self.validation is not None and self.validation.ok

    @property
    def failures(self) -> tuple[Transition, ...]:
        return tuple(
            item for item in self.applied
            if item.result is not None and item.result.result in ("failed", "rolled_back")
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "revision": self.revision,
            "dryRun": self.dry_run,
            "converged": self.converged,
            "reevaluationReason": self.reevaluation_reason,
            "summary": summarize(self.applied),
            "transitions": [item.to_json() for item in self.applied],
            "blocked": [item.to_json() for item in self.blocked],
            "validation": self.validation.to_json() if self.validation is not None else None,
            "reclaimedReservations": list(self.reclaimed),
            "notes": list(self.notes),
        }


@dataclass
class Applicator:
    """Applies plans through a replaceable backend, transactionally."""

    backend: Any = field(default_factory=DryRunBackend)
    ledger: InMemoryLedger = field(default_factory=InMemoryLedger)
    approvals: ApprovalStore = field(default_factory=DenyingApprovalStore)
    audit: AuditSink = field(default_factory=InMemoryAuditSink)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    retries: RetryJournal = field(default_factory=RetryJournal)
    settings: ApplicatorSettings = field(default_factory=ApplicatorSettings)
    #: The plan currently in force. Used to reject replays and supersessions.
    plan_in_force: PlanIdentity | None = None
    #: ``{service id: (implementation id, memory bytes)}`` for services this
    #: pass stopped in order to replace. Written by the release path and read by
    #: the rollback path, which is the only way a rollback can know what it is
    #: rolling back to.
    _previous_implementations: dict[str, tuple[str, int]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #

    def observe(self, registry: Any, *, now: float = 0.0) -> ActualState:
        """Ask the backend about every declared service.

        A backend that is unavailable produces ``unknown`` observations and is
        named in ``unavailable_backends``, rather than producing an empty state.
        The distinction matters: an empty actual state and a plan wanting five
        services running would reconcile into five starts on a machine where all
        five may already be running.
        """
        services: dict[str, ServiceObservation] = {}
        unavailable: list[str] = []
        available = True
        try:
            available = bool(self.backend.available())
        except Exception:  # noqa: BLE001 - a backend must never break observation
            available = False
        if not available:
            unavailable.append(getattr(self.backend, "name", "backend"))

        for service in registry.ordered():
            if not available:
                services[service.id] = ServiceObservation(
                    service.id, "unknown", observed_by="inferred",
                    detail=f"{getattr(self.backend, 'name', 'the backend')} could not be consulted",
                )
                continue
            try:
                services[service.id] = self.backend.inspect(service.id)
            except Exception as exc:  # noqa: BLE001
                services[service.id] = ServiceObservation(
                    service.id, "unknown", observed_by="inferred",
                    detail=f"inspection failed: {type(exc).__name__}",
                )
        return ActualState(
            services=services,
            observed_at_monotonic=now,
            unavailable_backends=tuple(unavailable),
        )

    # ------------------------------------------------------------------ #
    # The pass
    # ------------------------------------------------------------------ #

    def apply(
        self,
        plan: Any,
        *,
        registry: Any,
        inventory: Any,
        budget: Any,
        policy: Any,
        now: float = 0.0,
        actual: ActualState | None = None,
    ) -> ApplyReport:
        """Reconcile the machine toward ``plan``, one bounded pass.

        ``inventory``, ``budget`` and ``policy`` must be **fresh** — obtained
        after the plan was, not the ones it was generated from. That is what
        makes revalidation a check rather than a tautology, and the caller owns
        it because only the caller knows when it last measured.
        """
        identity: PlanIdentity | None = getattr(plan, "identity", None)
        plan_id = identity.plan_id if identity is not None else ""
        revision = identity.revision if identity is not None else 0

        verdict = revalidate_plan(
            identity,
            inventory=inventory, budget=budget, policy=policy, registry=registry,
            now=now, in_force=self.plan_in_force,
            supported_schema_version=SUPPORTED_PLAN_SCHEMA_VERSION,
        )
        if not verdict.ok:
            self.audit.record(
                "plan.rejected", at_monotonic=now, plan_id=plan_id, severity="warning",
                observed={"checks": [dict(item) for item in verdict.checked]},
                inferred={
                    "failureClass": verdict.failure_class,
                    "problems": list(verdict.problems),
                    "conclusion": "the plan was not applied and no service was touched",
                },
            )
            return ApplyReport(
                plan_id, revision, self.settings.dry_run,
                validation=verdict,
                reevaluation_reason=verdict.reevaluation_reason,
                notes=("nothing was applied; the plan did not survive validation",),
            )

        # A superseding plan invalidates approvals granted against the old one.
        if identity is not None and self.plan_in_force is not None and identity.plan_id != self.plan_in_force.plan_id:
            invalidate = getattr(self.approvals, "invalidate_for_plan", None)
            if callable(invalidate):
                for request_id in invalidate(identity.plan_id):
                    self.audit.record(
                        "approval.resolved", at_monotonic=now, plan_id=plan_id,
                        observed={"requestId": request_id, "decision": "expired"},
                        inferred={"cause": "the plan the approval was granted against was superseded"},
                    )
            self.audit.record(
                "plan.superseded", at_monotonic=now, plan_id=plan_id,
                observed={
                    "previousPlanId": self.plan_in_force.plan_id,
                    "previousRevision": self.plan_in_force.revision,
                    "revision": identity.revision,
                },
                inferred={"conclusion": "the newer plan is now in force"},
            )
        if identity is not None:
            self.plan_in_force = identity

        observed = actual if actual is not None else self.observe(registry, now=now)

        # Recovery before anything else. A reservation left by a previous
        # process, or one whose service is no longer running, is memory the
        # ledger believes is spent; reconciling it back is what stops a machine
        # gradually refusing to start anything after a few unclean shutdowns.
        reclaimed: list[str] = []
        for entry in self.ledger.expire(now):
            reclaimed.append(entry.reservation_id)
            self.audit.record(
                "reservation.reclaimed", at_monotonic=now, plan_id=plan_id,
                service_id=entry.service_id,
                observed={"reservationId": entry.reservation_id, "bytes": entry.reserved_amount},
                inferred={"cause": "the reservation was never committed inside its deadline"},
            )
        for entry in self.ledger.reconcile_with_actual(observed.active_ids()):
            reclaimed.append(entry.reservation_id)
            self.audit.record(
                "reservation.reclaimed", at_monotonic=now, plan_id=plan_id,
                service_id=entry.service_id,
                observed={"reservationId": entry.reservation_id, "bytes": entry.released_amount},
                inferred={"cause": "the service holding this reservation is not running"},
            )

        desired = desired_from_plan(plan, registry)
        settings = self._reconciliation_settings(desired, observed, budget, now)

        self.audit.record(
            "reconcile.started", at_monotonic=now, plan_id=plan_id,
            observed={
                "desiredRunning": list(desired.running_ids()),
                "actuallyActive": list(observed.active_ids()),
                "availableBytes": self.ledger.available_bytes(),
            },
            inferred={"dryRun": self.settings.dry_run},
        )

        reconciliation = reconcile(desired, observed, settings=settings, now=now)

        applied: list[Transition] = []
        failed_services: set[str] = set()
        notes: list[str] = []
        reevaluation = reconciliation.reevaluation_reason

        # The observed state moves as the pass proceeds. Apply-time
        # revalidation asks whether a service's dependencies are up *now*, and
        # "now" includes the dependency this same pass started four transitions
        # ago. Revalidating against the opening snapshot would postpone every
        # dependent service on every pass, and the machine would converge one
        # service per reconciliation or not at all.
        current = observed

        for transition in reconciliation.transitions:
            if len(applied) >= self.settings.maximum_transitions_per_pass:
                notes.append(
                    f"{len(reconciliation.transitions) - len(applied)} transitions were left for the "
                    f"next pass; one pass performs at most {self.settings.maximum_transitions_per_pass}"
                )
                break

            service = desired.get(transition.service_id)
            if service is None:
                continue

            # Partial convergence: a service whose dependency failed in this
            # same pass is skipped, and only that service. An unrelated service
            # further down the list is unaffected, which is the whole point.
            blocked_by = sorted(set(service.requires) & failed_services)
            if blocked_by:
                applied.append(self._finish(
                    transition, "postponed", now,
                    detail=f"a dependency failed in this pass: {', '.join(blocked_by)}",
                ))
                continue

            result = self._perform(
                transition, service, desired, current, budget, policy, now,
            )
            applied.append(result)
            current = self._observed_after(current, result, service)
            if result.result is not None and result.result.result in ("failed", "rolled_back"):
                failed_services.add(transition.service_id)
                if result.result.reevaluation_reason:
                    reevaluation = reevaluation or result.result.reevaluation_reason
                elif needs_reevaluation(result.result.failure_class):
                    reevaluation = reevaluation or "apply_time_validation_failed"

        self.audit.record(
            "reconcile.finished", at_monotonic=now, plan_id=plan_id,
            observed={"summary": summarize(applied), "blocked": len(reconciliation.blocked)},
            inferred={"reevaluationReason": reevaluation},
        )

        return ApplyReport(
            plan_id, revision, self.settings.dry_run,
            applied=tuple(applied),
            blocked=reconciliation.blocked,
            validation=verdict,
            reevaluation_reason=reevaluation,
            notes=tuple([*reconciliation.notes, *notes]),
            reclaimed=tuple(reclaimed),
        )

    # ------------------------------------------------------------------ #

    def _reconciliation_settings(
        self, desired: DesiredState, actual: ActualState, budget: Any, now: float,
    ) -> ReconciliationSettings:
        """Assemble what reconciliation is allowed to do, from live state."""
        # Essential services are never circuit-broken; the breaker is told which
        # they are rather than being asked to work it out.
        self.breaker.protected = frozenset(
            item.service_id for item in desired.services.values() if item.essential
        )
        unauthorized = frozenset(
            service_id for service_id in desired.services
            if not self._authorized(service_id)
        )
        approved = self.approvals.approved_services(desired.plan_id, now)
        return ReconciliationSettings(
            allow_essential_stop=self.settings.allow_essential_stop,
            approved_interruptions=approved,
            approved_starts=approved,
            emergency=self.settings.emergency,
            available_bytes=self.ledger.available_bytes(),
            protected_reserve_bytes=getattr(budget, "protected_reserve_bytes", 0),
            circuit_open=frozenset(
                service_id for service_id in desired.services
                if not self.breaker.allows(service_id, now)
            ),
            unauthorized=unauthorized,
            retry_not_before=self.retries.not_before(),
        )

    def _observed_after(
        self, actual: ActualState, transition: Transition, service: DesiredService,
    ) -> ActualState:
        """Re-read the one service a completed transition touched.

        Only the service that changed, and only from the backend. Re-observing
        everything would multiply backend calls by the number of transitions;
        assuming the outcome instead of reading it would put the applicator's
        expectations into the state that later transitions validate against,
        which is precisely the mistake this whole layer exists to avoid.

        A dry run has nothing to read back, because it changed nothing. It
        instead *projects* the intended outcome, marked ``projected`` and
        detailed as such, so the rest of the rehearsal can proceed past a
        dependency edge. Without that a dry run would stop at the first
        dependent service and report it postponed, which describes neither what
        would happen nor what did.
        """
        if transition.result is None or transition.result.result != "succeeded":
            return actual
        if self.settings.dry_run:
            projected = {
                "start": "running",
                "resume": "running",
                "stop": "stopped",
                "suspend": "suspended",
            }.get(transition.operation)
            if projected is None:
                return actual
            return actual.with_service(ServiceObservation(
                service.service_id, projected,
                implementation_id=service.implementation_id,
                memory_limit_bytes=service.memory_limit_bytes,
                enforced_memory_limit_bytes=service.memory_limit_bytes,
                observed_by="projected",
                detail="dry run: this is what the transition would have produced, not what was observed",
            ))
        try:
            return actual.with_service(self.backend.inspect(service.service_id))
        except Exception:  # noqa: BLE001
            return actual

    def _authorized(self, service_id: str) -> bool:
        try:
            return bool(self.backend.authorized(service_id))
        except Exception:  # noqa: BLE001
            return False

    def _finish(
        self, transition: Transition, result: str, now: float,
        *, detail: str = "", failure_class: str | None = None,
        reevaluation_reason: str | None = None, rollback_state: str | None = None,
        reservation_id: str | None = None, explanation: Sequence[Mapping[str, Any]] = (),
    ) -> Transition:
        return replace(
            transition,
            started_at_monotonic=transition.started_at_monotonic if transition.started_at_monotonic is not None else now,
            completed_at_monotonic=now,
            result=TransitionResult(result, failure_class, detail, reevaluation_reason),
            rollback_state=rollback_state if rollback_state is not None else transition.rollback_state,
            reservation_id=reservation_id if reservation_id is not None else transition.reservation_id,
            explanation=tuple([*transition.explanation, *explanation]),
        )

    # ------------------------------------------------------------------ #
    # One transition
    # ------------------------------------------------------------------ #

    def _perform(
        self,
        transition: Transition,
        service: DesiredService,
        desired: DesiredState,
        actual: ActualState,
        budget: Any,
        policy: Any,
        now: float,
    ) -> Transition:
        started = replace(transition, started_at_monotonic=now)
        self.audit.record(
            "transition.attempted", at_monotonic=now,
            plan_id=transition.plan_id, service_id=transition.service_id,
            transition_id=transition.transition_id,
            observed={
                "operation": transition.operation,
                "sourceState": transition.source_state,
                "targetState": transition.target_state,
            },
            inferred={"dryRun": self.settings.dry_run},
        )

        try:
            if transition.operation == "start":
                finished = self._perform_start(started, service, actual, budget, policy, now)
            elif transition.operation in ("stop", "suspend"):
                finished = self._perform_release(started, service, actual, now)
            elif transition.operation == "resume":
                finished = self._perform_resume(started, service, now)
            elif transition.operation == "apply_limits":
                finished = self._perform_limits(started, service, now)
            else:
                finished = self._finish(
                    started, "rejected", now,
                    detail=f"{transition.operation} is not an operation the applicator performs directly",
                )
        except Exception as exc:  # noqa: BLE001 - a backend bug must not strand the machine
            failure_class = classify_exception(exc)
            self._release_for(transition.service_id, "a transition raised before it could complete")
            finished = self._finish(
                started, "failed", now,
                detail=f"{type(exc).__name__} while performing {transition.operation}",
                failure_class=failure_class,
                rollback_state="completed",
            )

        self._record_outcome(finished, service, now)
        return finished

    def _perform_start(
        self,
        transition: Transition,
        service: DesiredService,
        actual: ActualState,
        budget: Any,
        policy: Any,
        now: float,
    ) -> Transition:
        """The seven-step transaction, with the unwind for every step."""
        # 1. Revalidate against fresh figures. This is the check that stops a
        #    plan decided ninety seconds ago from starting a service into memory
        #    that has since been taken by the user's own work.
        available = self.ledger.available_bytes()
        approvals = self.approvals.approved_services(transition.plan_id, now)
        verdict = revalidate_transition(
            service, budget=budget, policy=policy, actual=actual,
            available_bytes=available, approvals=approvals, now=now,
        )
        if not verdict.ok:
            return self._finish(
                transition, "postponed", now,
                detail="; ".join(verdict.problems),
                failure_class=verdict.failure_class,
                reevaluation_reason=verdict.reevaluation_reason,
                rollback_state="unnecessary",
                explanation=(
                    {"fact": "apply-time validation", "checks": [dict(item) for item in verdict.checked]},
                    {"inference": "no process was started and no reservation was taken"},
                ),
            )

        # 2. Reserve. Nothing starts against memory that has not been taken out
        #    of the pool first.
        try:
            reservation = self.ledger.reserve(
                service_id=service.service_id,
                amount_bytes=service.memory_limit_bytes,
                plan_id=transition.plan_id,
                transition_id=transition.transition_id,
                now=now,
            )
        except LedgerError as exc:
            return self._finish(
                transition, "postponed", now,
                detail=str(exc), failure_class="insufficient_resources",
                reevaluation_reason="apply_time_validation_failed",
                rollback_state="unnecessary",
            )
        self.audit.record(
            "reservation.taken", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed={"reservationId": reservation.reservation_id, "bytes": reservation.reserved_amount},
        )

        held = replace(transition, reservation_id=reservation.reservation_id)
        limits = ServiceLimits.from_desired(service)

        # 3 & 4. Limits, then start. The backend applies limits before the
        #        process exists, so there is no window in which it runs
        #        unconstrained.
        outcome = self.backend.start(
            service.service_id, service.implementation_id, limits,
            timeout_seconds=transition.timeout_seconds,
        )
        self.audit.record(
            "backend.operation", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed=outcome.to_json(),
        )
        if not outcome.ok:
            return self._rollback_start(held, service, outcome, now)

        # A backend that could not enforce the limits started a service that is
        # not constrained. That is not a success: the budget engine's arithmetic
        # assumed a ceiling that does not exist, and every later admission
        # decision would be made against a fiction.
        if outcome.limits is not None and not outcome.limits.enforced and not self.settings.dry_run:
            if service.memory_limit_bytes > 0:
                return self._rollback_start(
                    held, service,
                    replace(
                        outcome, ok=False, failure_class="cgroup_unavailable",
                        detail=(
                            "the service started but its resource limits could not be enforced: "
                            + (outcome.limits.detail or "no controller applied them")
                        ),
                    ),
                    now,
                )

        # 5. Confirm the process is actually where it should be. A backend
        #    reporting success is evidence, not proof.
        observation = outcome.observation
        if observation is not None and observation.state not in ("running", "starting", "degraded"):
            return self._rollback_start(
                held, service,
                replace(
                    outcome, ok=False, failure_class="startup_timeout",
                    detail=f"the backend reported success but the service is {observation.state}",
                ),
                now,
            )

        # 6. Bounded health check.
        health = self.backend.health(service.service_id, timeout_seconds=transition.timeout_seconds)
        if not health.ok:
            return self._rollback_start(held, service, health, now)

        # 7. Commit. Only now is the memory recorded as genuinely in use.
        committed = self.ledger.commit(reservation.reservation_id)
        self.audit.record(
            "reservation.committed", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed={"reservationId": committed.reservation_id, "bytes": committed.committed_amount},
        )
        enforced = outcome.limits
        return self._finish(
            held, "succeeded", now,
            detail=outcome.detail or "started",
            rollback_state="unnecessary",
            explanation=(
                {
                    "fact": "limits",
                    "requested": enforced.requested.to_json() if enforced else None,
                    "effective": enforced.effective.to_json() if enforced else None,
                    "enforced": bool(enforced and enforced.enforced),
                },
                {"fact": "health", "healthy": True, "checkedBy": getattr(self.backend, "name", "")},
            ),
        )

    def _rollback_start(
        self, transition: Transition, service: DesiredService,
        outcome: BackendOutcome, now: float,
    ) -> Transition:
        """Undo a failed start, without making the machine less safe.

        Order matters: stop the partial service first, then release its
        reservation. Releasing first would let another transition in the same
        pass reserve memory that a still-dying process is holding.
        """
        steps: list[str] = []

        stop_result = self.backend.stop(
            service.service_id, graceful=True, timeout_seconds=30.0,
        )
        steps.append(
            "stopped the partially started service" if stop_result.ok
            else f"could not stop the partial service: {stop_result.detail}"
        )

        if transition.reservation_id:
            self.ledger.release(
                transition.reservation_id,
                detail=f"released after a failed start: {outcome.detail}",
            )
            steps.append("released the reservation")
            self.audit.record(
                "reservation.released", at_monotonic=now, plan_id=transition.plan_id,
                service_id=service.service_id, transition_id=transition.transition_id,
                observed={"reservationId": transition.reservation_id},
                inferred={"cause": "the start it was taken for failed"},
            )

        restored = self._restore_previous(service, now)
        if restored:
            steps.append(restored)

        self.audit.record(
            "transition.rolled_back", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            severity="warning",
            observed={"failureClass": outcome.failure_class, "detail": outcome.detail},
            inferred={"steps": steps},
        )
        return self._finish(
            transition, "rolled_back", now,
            detail=outcome.detail,
            failure_class=outcome.failure_class,
            rollback_state="completed",
            explanation=({"fact": "rollback", "steps": steps},),
        )

    def _restore_previous(self, service: DesiredService, now: float) -> str:
        """Bring back what was running before, if that is safe to do.

        "Safe" is not a judgement call: it means the previous implementation's
        memory can be reserved right now. If it cannot, the service stays
        stopped and the report says so, because a rollback that overcommits the
        machine has replaced one failed service with a failing machine.
        """
        if not self.settings.rollback_to_previous:
            return ""
        previous = self._previous_implementations.get(service.service_id)
        if previous is None:
            return ""
        implementation_id, memory = previous
        if implementation_id == service.implementation_id:
            return ""
        try:
            reservation = self.ledger.reserve(
                service_id=service.service_id, amount_bytes=memory,
                plan_id="rollback", transition_id=f"rollback:{service.service_id}", now=now,
            )
        except LedgerError:
            return (
                f"did not restore {implementation_id}: its {memory} bytes cannot be reserved now, "
                "and a rollback may not overcommit the machine"
            )
        outcome = self.backend.start(
            service.service_id, implementation_id,
            ServiceLimits(memory_max_bytes=memory or None),
            timeout_seconds=60.0,
        )
        if outcome.ok:
            self.ledger.commit(reservation.reservation_id)
            return f"restored the previous implementation {implementation_id}"
        self.ledger.release(reservation.reservation_id, detail="the restore also failed")
        return f"could not restore {implementation_id}: {outcome.detail}"

    def _perform_release(
        self, transition: Transition, service: DesiredService,
        actual: ActualState, now: float,
    ) -> Transition:
        """Stop or suspend, and account for what that gives back."""
        observation = actual.get(service.service_id)

        # Remember what was here, so a failed replacement can be rolled back to
        # it. Recorded before the stop, because afterwards there is nothing to
        # read it from.
        if observation.implementation_id and service.should_run:
            self._previous_implementations[service.service_id] = (
                observation.implementation_id,
                observation.enforced_memory_limit_bytes or observation.memory_limit_bytes or 0,
            )

        if transition.operation == "suspend":
            outcome = self.backend.suspend(
                service.service_id, timeout_seconds=transition.timeout_seconds,
            )
        else:
            # An ungraceful stop is reached only under the emergency policy, and
            # only for a service that is neither essential nor holding work the
            # user has not been asked about. Everything else gets SIGTERM and
            # its shutdown deadline.
            assessment = assess_adaptation(
                "stop", service, observation, emergency=self.settings.emergency,
            )
            graceful = not (self.settings.emergency and assessment.user_work_policy == "emergency_only")
            outcome = self.backend.stop(
                service.service_id, graceful=graceful,
                timeout_seconds=transition.timeout_seconds,
            )

        self.audit.record(
            "backend.operation", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed=outcome.to_json(),
        )

        if not outcome.ok:
            return self._finish(
                transition, "failed", now,
                detail=outcome.detail, failure_class=outcome.failure_class,
                rollback_state="unnecessary",
            )

        if transition.operation == "stop":
            # Only a stop gives memory back. A suspended service keeps every
            # page it had, so releasing its reservation would let the next start
            # be admitted against memory that is still occupied.
            for entry in self.ledger.release_for_service(
                service.service_id, detail="the service was stopped",
            ):
                self.audit.record(
                    "reservation.released", at_monotonic=now, plan_id=transition.plan_id,
                    service_id=service.service_id, transition_id=transition.transition_id,
                    observed={"reservationId": entry.reservation_id, "bytes": entry.released_amount},
                )

        return self._finish(
            transition, "succeeded", now, detail=outcome.detail,
            rollback_state="unnecessary",
            explanation=(
                {
                    "fact": "resources",
                    "released": transition.operation == "stop",
                    "note": (
                        "a suspended service keeps its memory; nothing was released"
                        if transition.operation == "suspend" else
                        "the reservation was released back to the pool"
                    ),
                },
            ),
        )

    def _perform_resume(self, transition: Transition, service: DesiredService, now: float) -> Transition:
        outcome = self.backend.resume(service.service_id, timeout_seconds=transition.timeout_seconds)
        self.audit.record(
            "backend.operation", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed=outcome.to_json(),
        )
        if not outcome.ok:
            return self._finish(
                transition, "failed", now,
                detail=outcome.detail, failure_class=outcome.failure_class,
            )
        return self._finish(transition, "succeeded", now, detail=outcome.detail)

    def _perform_limits(self, transition: Transition, service: DesiredService, now: float) -> Transition:
        limits = ServiceLimits.from_desired(service)
        outcome = self.backend.apply_limits(
            service.service_id, limits, timeout_seconds=transition.timeout_seconds,
        )
        self.audit.record(
            "backend.operation", at_monotonic=now, plan_id=transition.plan_id,
            service_id=service.service_id, transition_id=transition.transition_id,
            observed=outcome.to_json(),
        )
        if not outcome.ok:
            return self._finish(
                transition, "failed", now,
                detail=outcome.detail, failure_class=outcome.failure_class,
            )
        enforced = outcome.limits
        return self._finish(
            transition, "succeeded", now, detail=outcome.detail,
            explanation=(
                {
                    "fact": "limits",
                    "requested": enforced.requested.to_json() if enforced else None,
                    "effective": enforced.effective.to_json() if enforced else None,
                    "enforced": bool(enforced and enforced.enforced),
                },
            ),
        )

    # ------------------------------------------------------------------ #

    def _record_outcome(self, transition: Transition, service: DesiredService, now: float) -> None:
        """Update the breaker and the retry journal, and write the audit line."""
        result = transition.result
        if result is None:
            return

        if result.result == "succeeded":
            self.breaker.record_success(transition.service_id)
            self.retries.record_success(transition.service_id)
            self.audit.record(
                "transition.succeeded", at_monotonic=now,
                plan_id=transition.plan_id, service_id=transition.service_id,
                transition_id=transition.transition_id,
                observed={"operation": transition.operation, "detail": result.detail},
            )
            return

        if result.result == "postponed":
            self.audit.record(
                "transition.postponed", at_monotonic=now,
                plan_id=transition.plan_id, service_id=transition.service_id,
                transition_id=transition.transition_id, severity="notice",
                observed={"operation": transition.operation, "failureClass": result.failure_class},
                inferred={
                    "detail": result.detail,
                    "conclusion": "nothing was started and no resources were consumed",
                },
            )
            return

        if result.result in ("failed", "rolled_back"):
            state = self.breaker.record_failure(transition.service_id, result.failure_class, now)
            record = self.retries.record_failure(transition.service_id, result.failure_class, now)
            self.audit.record(
                "transition.failed", at_monotonic=now,
                plan_id=transition.plan_id, service_id=transition.service_id,
                transition_id=transition.transition_id, severity="warning",
                observed={
                    "operation": transition.operation,
                    "failureClass": result.failure_class,
                    "detail": result.detail,
                },
                inferred={
                    "attempt": record.attempt,
                    "willRetry": not record.exhausted,
                    "nextAttemptAtMonotonic": record.next_attempt_at_monotonic,
                    "circuitState": state.state,
                },
            )
            if state.state == "open":
                self.audit.record(
                    "circuit.changed", at_monotonic=now,
                    plan_id=transition.plan_id, service_id=transition.service_id,
                    severity="warning",
                    observed={"consecutiveFailures": state.consecutive_failures},
                    inferred={
                        "conclusion": (
                            "further attempts are paused; retrying a service that fails identically "
                            "every time costs power and changes nothing"
                        ),
                    },
                )

    def _release_for(self, service_id: str, detail: str) -> None:
        """Give back everything held for a service. Never raises."""
        try:
            self.ledger.release_for_service(service_id, detail=detail)
        except Exception:  # noqa: BLE001 - cleanup must not fail
            return

    # ------------------------------------------------------------------ #

    def request_approval_for(
        self, blocked: Blocked, *, plan_id: str, now: float,
        estimated_cost_units: int | None = None,
    ) -> Any:
        """Raise the approval a block is waiting on.

        Separate from the apply path on purpose: applying and asking are
        different acts with different audiences, and an applicator that raised
        approvals as a side effect of reconciling would produce a request every
        thirty seconds for as long as nobody answered.
        """
        action = {
            "user_work_protected": "interrupt_user_work",
            "waiting_for_approval": "remote_dispatch",
            "essential_protected": "stop_essential_service",
        }.get(blocked.reason, "interrupt_user_work")
        alternatives = (
            blocked.fallback or "the service is left exactly as it is",
            "answer later; nothing happens until you do",
        )
        request = request_for_transition(
            plan_id=plan_id,
            transition_id=f"{plan_id}:{blocked.service_id}",
            service_id=blocked.service_id,
            action=action,
            reason=blocked.detail,
            now=now,
            data_affected="none" if action != "remote_dispatch" else "the inputs of this service's work",
            destination="remote" if action == "remote_dispatch" else "local",
            estimated_cost_units=estimated_cost_units,
            resource_impact={"desiredAction": blocked.desired_action, "actualState": blocked.actual_state},
            alternatives=alternatives,
        )
        response = self.approvals.request(request)
        self.audit.record(
            "approval.requested", at_monotonic=now, plan_id=plan_id,
            service_id=blocked.service_id,
            observed={"action": action, "safeDefault": request.safe_default},
            inferred={"decision": response.decision},
        )
        return response

    def status(self) -> dict[str, Any]:
        return {
            "backend": getattr(self.backend, "name", "unknown"),
            "dryRun": self.settings.dry_run,
            "planInForce": self.plan_in_force.to_json() if self.plan_in_force is not None else None,
            "settings": self.settings.to_json(),
            "ledger": self.ledger.to_json(),
            "breaker": self.breaker.to_json(),
            "retries": self.retries.to_json(),
        }

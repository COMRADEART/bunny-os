# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The policy engine: inventory + budget + manifests + policy -> execution plan.

This is where a decision is actually made, and it is the only place. It is a
pure function. Given the same inventory, budget, registry, policy, previous plan
and clock reading, it returns the same plan — on any host, in any order, every
time. That property is not a nicety: it is what lets §16's simulated-hardware
tests assert on real decisions, and it is what "the engine must not randomly
change decisions" means in practice.

**Evaluation order.** Services are walked in :meth:`Registry.start_order`:
essential first, then descending priority, with dependencies pulled ahead of
their dependents. Memory is handed out along that walk, so a high-priority
service is funded before a low-priority one competes for the same bytes. This is
how "essential services always receive priority" is enforced — not by a check
that could be forgotten, but by the order the pool is consumed in.

**The protected reserve is not in the pool.** The engine allocates from
``budget.currently_allocatable_bytes``, which already has the reserve removed.
There is no code path by which an optional service can be granted reserve
memory, because the reserve is not a number the engine ever sees.

**Hysteresis is a Schmitt trigger on the memory gate.** A service that is
already running is re-evaluated against ``minimum * (1 - h)``; a service that is
not is evaluated against ``minimum * (1 + h)``. The gap between those two
thresholds is the band in which nothing changes, which is what stops a service
flapping when free memory oscillates across a boundary.

**Cooldown outranks hysteresis but not safety.** Inside the cooldown window a
service keeps its previous action — except for refusals that are not about
resources at all (the user switched it off, a dependency is gone, a conflicting
service is up, the hardware is not there). Those take effect immediately,
because holding a service running for 60 more seconds because it was running
60 seconds ago is not a stability property when the reason it must stop is that
its dependency died.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .budget import Budget
from .manifest import Implementation, RequirementCheck, ServiceManifest
from .model import Inventory, now_iso8601
from .plan import Decision, ExecutionPlan, Reason
from .policy import Policy
from .registry import Registry
from .scores import ScoreSet

__all__ = ["IMMEDIATE_REASONS", "evaluate"]

#: Refusals that a cooldown may not delay. Every one of these is a statement
#: about correctness or consent rather than about resources, and deferring it
#: would keep a service running that must not be running.
IMMEDIATE_REASONS = frozenset({
    "user-disabled",
    "conflict",
    "dependency-unavailable",
    "essential-shortfall",
    "sensitive-data-local-only",
    "remote-not-permitted",
})


def _memory_gate(minimum: int, *, running: bool, hysteresis: float, essential: bool) -> int:
    """The memory threshold to apply, biased by whether the service is up.

    Running services get an easier gate, stopped ones a harder one. The band
    between them is dead space in which no state change happens at all.

    **Essential services are exempt.** Hysteresis exists to stop an optional
    service flapping as free memory crosses a boundary; an essential service
    does not flap, because if it cannot run the machine is not viable and that
    is reported rather than retried. Applying a start margin to them would also
    make the declared essential floor a lie: the budget engine reserves exactly
    the sum of essential minimums, so a 15% start surcharge on top of that
    reservation refuses the control plane on any machine sized to its own
    stated requirements.
    """
    if essential:
        return minimum
    factor = (1.0 - hysteresis) if running else (1.0 + hysteresis)
    return int(minimum * factor)


def _remote_eligibility(
    service: ServiceManifest,
    implementation: Implementation,
    inventory: Inventory,
    policy: Policy,
) -> list[Reason]:
    """Every reason this remote implementation may not be used. Empty means it may.

    Ordered so that the most fundamental objection is reported first: consent
    before configuration, configuration before connectivity. A user whose
    sensitive workload may not leave the machine should be told that, not told
    the network is down.
    """
    reasons: list[Reason] = []
    provider = implementation.provider or ""

    if service.handles_sensitive_data and not policy.remote_execution.allow_sensitive_data:
        reasons.append(Reason(
            "sensitive-data-local-only",
            f"{service.id} is declared to handle sensitive data and "
            "remoteExecution.allowSensitiveData is false",
            required="allowSensitiveData=true", measured="false",
        ))

    if not policy.remote_execution.enabled:
        reasons.append(Reason(
            "remote-not-permitted",
            "remote execution is disabled; Bunny OS does not send work off the machine by default",
            required="remoteExecution.enabled=true", measured="false",
        ))
    elif not provider:
        reasons.append(Reason(
            "remote-not-permitted",
            f"implementation {implementation.id} names no provider, so there is nothing to authorise",
            required="a named provider", measured=None,
        ))
    elif not policy.remote_execution.permits(provider):
        reasons.append(Reason(
            "remote-not-permitted",
            f"provider {provider!r} is not in remoteExecution.permittedProviders",
            required=provider, measured=list(policy.remote_execution.permitted_providers),
        ))

    if not inventory.network.default_route.is_known:
        reasons.append(Reason(
            "remote-unreachable",
            "connectivity could not be determined, and unmeasured connectivity is not assumed",
            required="a default route", measured=None,
        ))
    elif not inventory.network.online:
        reasons.append(Reason(
            "remote-unreachable", "there is no default route",
            required="a default route", measured=False,
        ))
    elif inventory.network.endpoint_reachable.get(None) is False:
        reasons.append(Reason(
            "remote-unreachable",
            "a route exists but no configured endpoint answered",
            required="a reachable endpoint", measured=False,
        ))

    metered = inventory.network.metered.get(None)
    if not policy.metered_network_allowed and metered is not False:
        reasons.append(Reason(
            "metered-network",
            (
                "the connection is metered and meteredNetworkAllowed is false"
                if metered is True
                else "metering could not be determined, which is treated as possibly metered"
            ),
            required="meteredNetworkAllowed=true or a known-unmetered connection",
            measured=metered,
        ))

    if implementation.costs_money and policy.confirm_before_paid_api:
        reasons.append(Reason(
            "paid-api-confirmation",
            f"{implementation.id} bills the user and confirmBeforePaidApi is true",
            required="explicit confirmation", measured=None,
        ))
    if policy.remote_execution.require_user_approval:
        reasons.append(Reason(
            "remote-approval-required",
            "remoteExecution.requireUserApproval is true; this dispatch needs the user to say yes",
            required="user approval", measured=None,
        ))
    return reasons


def _evaluate_implementation(
    service: ServiceManifest,
    implementation: Implementation,
    inventory: Inventory,
    scores: ScoreSet,
    policy: Policy,
    *,
    remaining_bytes: int,
    was_running: bool,
) -> tuple[bool, list[RequirementCheck], list[Reason], int]:
    """Can this implementation run? Returns eligibility, evidence and its cost."""
    reasons: list[Reason] = []

    if implementation.locality == "remote":
        blockers = _remote_eligibility(service, implementation, inventory, policy)
        if blockers:
            return False, [], blockers, 0
        # A remote implementation consumes a client-side footprint only. It is
        # declared like any other requirement, so a remote path is not free by
        # assumption.
        cost = implementation.requirements.minimum_memory_bytes or 0
        checks = implementation.requirements.evaluate(inventory, scores, available_memory_bytes=remaining_bytes)
        if any(check.blocking for check in checks):
            return False, checks, _requirement_reasons(checks), cost
        return True, checks, [], cost

    minimum = implementation.requirements.minimum_memory_bytes or service.requirements.minimum_memory_bytes or 0
    gate = _memory_gate(
        minimum, running=was_running, hysteresis=policy.hysteresis_fraction, essential=service.essential,
    )
    if minimum and remaining_bytes < gate:
        return False, [], [Reason(
            "budget-exhausted",
            f"{minimum // (1024 ** 2)} MiB is required and {remaining_bytes // (1024 ** 2)} MiB "
            f"of the memory budget remains"
            + (f" (a {gate // (1024 ** 2)} MiB start threshold applies because it is not running)" if not was_running and gate != minimum else ""),
            required=gate, measured=remaining_bytes,
        )], minimum

    checks = list(service.requirements.evaluate(inventory, scores, available_memory_bytes=remaining_bytes))
    checks.extend(implementation.requirements.evaluate(inventory, scores, available_memory_bytes=remaining_bytes))
    if any(check.blocking for check in checks):
        return False, checks, _requirement_reasons(checks), minimum

    # Grant the recommended figure when the budget can afford it: a service that
    # only ever receives its bare minimum will spend its life reclaiming.
    recommended = implementation.requirements.recommended_memory_bytes or minimum
    grant = recommended if recommended <= remaining_bytes else minimum
    return True, checks, [], grant


def _requirement_reasons(checks: Sequence[RequirementCheck]) -> list[Reason]:
    reasons: list[Reason] = []
    for check in checks:
        if check.satisfied is True:
            continue
        code = "requirement-unmet" if check.satisfied is False else "requirement-unknown"
        message = (
            f"{check.requirement} was not satisfied"
            if check.satisfied is False
            else f"{check.requirement} could not be determined"
        )
        if check.detail:
            message = f"{message}: {check.detail}"
        reasons.append(Reason(code, message, required=check.required, measured=check.measured))
    return reasons


def _previous(previous: ExecutionPlan | None, service_id: str) -> Decision | None:
    return previous.decision(service_id) if previous is not None else None


def evaluate(
    inventory: Inventory,
    scores: ScoreSet,
    budget: Budget,
    registry: Registry,
    policy: Policy,
    *,
    previous: ExecutionPlan | None = None,
    now: float = 0.0,
) -> ExecutionPlan:
    """Produce the execution plan. Pure, deterministic, side-effect free."""
    decisions: list[Decision] = []
    notes: list[str] = []
    running: set[str] = set()
    granted = 0

    remaining = budget.currently_allocatable_bytes
    essential_pool = budget.essential_services_bytes

    #: Minimums still owed to essential services that have not been decided yet.
    #: An essential service may be granted its *recommended* size only out of
    #: memory no later essential service needs for its *minimum*. Without this,
    #: the first essential service to be evaluated takes its comfortable size
    #: and the last one — which on this machine is the update agent — is refused
    #: for want of six megabytes. Start order would then silently decide which
    #: parts of the control plane exist.
    owed = {
        service.id: registry.minimum_bytes(service)
        for service in registry.essential()
    }

    if not budget.viable:
        notes.append(
            "Essential services cannot be funded on this machine. Every optional service is "
            "refused so that whatever control plane can run, does."
        )

    for service in registry.start_order():
        previous_decision = _previous(previous, service.id)
        was_running = previous_decision.running if previous_decision else False
        # Essential services draw on their own reserved pool first and fall back
        # to the discretionary one; optional services see only the latter. An
        # optional service therefore cannot consume memory set aside to keep the
        # control plane alive.
        if service.essential:
            owed.pop(service.id, None)
            pool = essential_pool + remaining
            # Only reserve for later essentials when every essential minimum can
            # be met. Under a shortfall there is nothing to protect and holding
            # memory back would refuse the highest-priority services in order to
            # keep a promise to the lowest.
            available = max(0, pool - sum(owed.values())) if budget.viable else pool
        else:
            available = remaining

        decision = _decide(
            service, inventory, scores, budget, registry, policy,
            available_bytes=available,
            running=running,
            was_running=was_running,
            previous_decision=previous_decision,
            now=now,
        )

        if decision.running:
            running.add(service.id)
            granted += decision.memory_grant_bytes
            if service.essential:
                from_essential = min(essential_pool, decision.memory_grant_bytes)
                essential_pool -= from_essential
                remaining -= decision.memory_grant_bytes - from_essential
            else:
                remaining -= decision.memory_grant_bytes
            remaining = max(0, remaining)
        decisions.append(decision)

    # The engine must never promise more than the budget allows. This is the
    # invariant the whole allocation walk exists to maintain, so it is asserted
    # rather than assumed: a violation is a bug in this file, and it should
    # surface here rather than as an OOM kill an hour later.
    ceiling = budget.currently_allocatable_bytes + budget.essential_services_bytes
    if granted > ceiling:
        raise AssertionError(
            f"granted {granted} bytes against a {ceiling} byte ceiling; the allocation walk is wrong"
        )

    return ExecutionPlan(
        decisions=tuple(decisions),
        generated_at=now_iso8601(),
        notes=tuple([*notes, *budget.notes[:4]]),
        granted_memory_bytes=granted,
    )


def _decide(
    service: ServiceManifest,
    inventory: Inventory,
    scores: ScoreSet,
    budget: Budget,
    registry: Registry,
    policy: Policy,
    *,
    available_bytes: int,
    running: set[str],
    was_running: bool,
    previous_decision: Decision | None,
    now: float,
) -> Decision:
    def settle(action: str, reasons: list[Reason], **fields) -> Decision:
        """Apply cooldown, then stamp the state-change time."""
        held = _apply_cooldown(action, reasons, previous_decision, policy, now, available_bytes)
        if held is not None:
            return held
        changed_at = (
            previous_decision.state_changed_at
            if previous_decision is not None and previous_decision.action == action
            else now
        )
        return Decision(
            service_id=service.id, action=action, reasons=tuple(reasons),
            state_changed_at=changed_at, **fields,
        )

    if service.id in policy.disabled_services:
        return settle("reject", [Reason(
            "user-disabled", f"{service.id} is listed in disabledServices",
            required=None, measured="disabled",
        )], fallback="none; the user switched this service off")

    conflicting = sorted(set(service.conflicts_with).intersection(running))
    if conflicting:
        return settle("reject", [Reason(
            "conflict", f"{', '.join(conflicting)} is running and conflicts with {service.id}",
            required="no conflicting service", measured=conflicting,
        )])

    missing = [dependency for dependency in service.requires if dependency not in running]
    if missing:
        code = "dependency-unavailable"
        return settle("defer" if service.suspendable else "reject", [Reason(
            code,
            f"{service.id} requires {', '.join(sorted(missing))}, which "
            + ("is" if len(missing) == 1 else "are") + " not running",
            required=sorted(missing), measured=sorted(running),
        )])

    if not budget.viable and not service.essential:
        return settle("reject", [Reason(
            "essential-shortfall",
            "the machine cannot fund its essential services, so nothing optional is started",
            required=budget.essential_services_bytes + budget.essential_shortfall_bytes,
            measured=budget.allocatable_bytes,
        )], fallback="run the essential control plane only")

    candidates = list(service.ordered_implementations())
    pinned_id = policy.pinned_implementations.get(service.id)
    pin_reasons: list[Reason] = []
    if pinned_id:
        pinned = service.implementation(pinned_id)
        if pinned is None:
            pin_reasons.append(Reason(
                "pin-unsatisfiable",
                f"{service.id} is pinned to {pinned_id!r}, which it does not declare",
                required=pinned_id, measured=[item.id for item in candidates],
            ))
        else:
            # The pin is tried first, and only first. A pin that does not fit is
            # refused with a reason rather than honoured into an OOM kill, and
            # the ladder then proceeds normally — a user's preference is a
            # preference, not an override of the machine's limits.
            candidates = [pinned, *[item for item in candidates if item.id != pinned_id]]

    all_reasons: list[Reason] = list(pin_reasons)
    all_checks: list[RequirementCheck] = []
    best_rank = candidates[0].rank if candidates else 1

    for implementation in candidates:
        eligible, checks, reasons, cost = _evaluate_implementation(
            service, implementation, inventory, scores, policy,
            remaining_bytes=available_bytes, was_running=was_running,
        )
        all_checks.extend(checks)
        if not eligible:
            for reason in reasons:
                all_reasons.append(replace(reason, message=f"{implementation.id}: {reason.message}"))
            if pinned_id == implementation.id:
                all_reasons.append(Reason(
                    "pin-unsatisfiable",
                    f"the pinned implementation {implementation.id!r} cannot run here; "
                    "continuing down the ladder rather than overcommitting the machine",
                    required=pinned_id, measured=None,
                ))
            continue

        selected: list[Reason] = []
        if pinned_id == implementation.id:
            selected.append(Reason("pin-honoured", f"{implementation.id} is pinned by policy and its requirements are met"))
        if implementation.rank > best_rank:
            selected.append(Reason(
                "degraded",
                f"{implementation.id} was selected instead of a richer implementation this machine cannot support",
                required=None, measured=implementation.id,
            ))
        selected.append(Reason(
            "selected",
            f"{implementation.title} ({implementation.locality}) satisfies every declared requirement",
            required=implementation.requirements.minimum_memory_bytes,
            measured=available_bytes,
        ))
        action = "start_local" if implementation.locality == "local" else "start_remote"
        cpu = budget.background_cpu_percent if service.priority <= 30 else budget.interactive_cpu_percent
        return settle(
            action,
            [*all_reasons, *selected],
            implementation_id=implementation.id,
            memory_grant_bytes=cost if implementation.locality == "local" else (implementation.requirements.minimum_memory_bytes or 0),
            cpu_percent=cpu,
            checks=tuple(all_checks),
            fallback="",
        )

    all_reasons.append(Reason(
        "no-implementation",
        f"none of the {len(candidates)} declared implementations of {service.id} can run here",
        required=[item.id for item in candidates], measured=None,
    ))
    action = "suspend" if was_running and service.suspendable else ("stop" if was_running else "reject")
    if was_running:
        all_reasons.append(Reason(
            "resource-pressure",
            f"{service.id} was running and is being {'suspended' if action == 'suspend' else 'stopped'} "
            "because it no longer fits",
            required=None, measured=available_bytes,
        ))
    return settle(action, all_reasons, checks=tuple(all_checks), fallback=_fallback_text(service))


def _fallback_text(service: ServiceManifest) -> str:
    remote = [item for item in service.ordered_implementations() if item.locality == "remote"]
    if remote:
        return (
            "a remote implementation exists but is not permitted; enable remoteExecution and "
            f"add {remote[0].provider or 'its provider'} to permittedProviders to use it"
        )
    if service.essential:
        return "none; this service is essential and has no remote path"
    return "the feature is unavailable locally and has no remote implementation"


def _apply_cooldown(
    action: str,
    reasons: Sequence[Reason],
    previous_decision: Decision | None,
    policy: Policy,
    now: float,
    available_bytes: int,
) -> Decision | None:
    """Hold a service at its previous action inside the cooldown window.

    Returns the held decision, or ``None`` to let the new one stand. Two classes
    of change are never held:

    * refusals listed in :data:`IMMEDIATE_REASONS`, which are statements about
      correctness or consent rather than resources — a stability mechanism that
      keeps a user-disabled service running is a bug wearing a feature's
      clothes;
    * a running service whose previous grant no longer fits the current budget.
      Holding it would carry a memory grant sized for a machine that no longer
      exists, and stability may not be bought by overcommitting the machine.
    """
    if previous_decision is None or previous_decision.action == action:
        return None
    if policy.state_change_cooldown_seconds <= 0:
        return None
    if any(reason.code in IMMEDIATE_REASONS for reason in reasons):
        return None
    if previous_decision.running and previous_decision.memory_grant_bytes > available_bytes:
        return None
    elapsed = now - previous_decision.state_changed_at
    if elapsed >= policy.state_change_cooldown_seconds:
        return None
    return replace(
        previous_decision,
        reasons=(*previous_decision.reasons, Reason(
            "cooldown-hold",
            f"the engine would have moved this service to {action!r}, but it changed state "
            f"{elapsed:.0f}s ago and the cooldown is {policy.state_change_cooldown_seconds:.0f}s",
            required=policy.state_change_cooldown_seconds, measured=round(elapsed, 1),
        )),
    )

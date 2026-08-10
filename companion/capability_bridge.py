# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking the capability runtime where a task may run, and recording the answer.

There is no hardware detection in this module and there must never be. Bunny OS
already has one capability service — :mod:`capability.discovery` measures the
machine, :mod:`capability.scores` grades it, :mod:`capability.budget` decides
what may be spent and :mod:`capability.router` decides where a task runs — and a
second classifier living inside the companion would eventually disagree with the
first. When it did, the user would be shown one answer and the system would act
on the other.

So this module does three things and nothing else:

1. translates a :class:`companion.task.CompanionTask` into the router's
   :class:`capability.router.TaskRequest`, conservatively;
2. asks the router, and reads the §11 signals out of the same inventory the
   router used, so the explanation and the decision come from one measurement;
3. records which plan the answer was given against, by identity, so that a
   decision made ten minutes ago can be recognised as stale.

The one rule that survives translation intact: **local incapability is never an
argument for remote execution.** The router enforces it, and this module does
not add a path around it. A task that cannot run locally and may not run
remotely produces a *blocked* task with the router's own reasons attached — not
a quiet upgrade to a provider that happens to be configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from capability.apply.identity import digest
from capability.router import RemoteProvider, RouteDecision, TaskRequest, route
from capability.runtime import Assessment

from .errors import CapabilityRefused
from .executor import Executor, ExecutorDeclaration
from .privacy import rank, router_privacy
from .session import CompanionSession
from .task import CompanionTask

__all__ = [
    "CapabilityDecision",
    "ExecutorEligibility",
    "capability_signals",
    "evaluate_task",
    "task_request_for",
]


#: The requirement dimension the companion adds when it knows something the
#: hardware probes cannot: that no configured executor can do this work here.
#: It is deliberately a dimension nothing measures, so
#: :func:`capability.router._local_feasible` fails it with ``when_unknown=False``
#: and renders the honest sentence "local-executor is unmeasured against a
#: required 1" into the routing reasons and the disclosure.
LOCAL_EXECUTOR_DIMENSION = "local-executor"


def task_request_for(
    task: CompanionTask,
    session: CompanionSession,
    *,
    local_executor_available: bool = True,
) -> TaskRequest:
    """Translate a companion task into the router's vocabulary.

    Every narrowing is deliberate:

    * ``personal`` becomes ``sensitive`` (:func:`companion.privacy.router_privacy`);
    * the effective locality is the *stricter* of the task's and the session's,
      so a session set to device-only cannot be widened by a task;
    * ``remote_allowed`` is the session's permission, not the task's wish;
    * ``user_approved`` is always ``False`` here. Approval is decided by
      :mod:`companion.approvals` against a specific plan and destination, and
      handing the router a pre-approved flag would let a routing decision be
      made against consent that had not been checked for this act.

    ``local_executor_available=False`` states the one fact the router cannot
    probe for: that nothing configured here can perform this task locally. The
    router asks a *hardware* question, and a machine with ample memory and no
    model installed answers it "local is fine" — which made every remote
    destination unreachable, because permission for remote is only settled
    after local is found impossible. Supplying the fact does not grant
    anything: the router still refuses on locality, policy, network, provider
    declaration and cost, and :mod:`companion.approvals` still has the last
    word.
    """
    localities = ("device-only", "trusted-remote", "any")
    effective_locality = min(
        (task.data_locality, session.locality_preference),
        key=lambda name: localities.index(name),
    )
    privacy = router_privacy(task.classification)
    return TaskRequest(
        id=task.task_id,
        capability="inference",
        privacy=privacy,
        data_locality=effective_locality,
        latency="interactive",
        maximum_cost_units=min(task.cost_limit_units, session.cost_policy.task_limit_units)
        if session.cost_policy.task_limit_units
        else task.cost_limit_units,
        requires_offline=task.requires_offline,
        remote_allowed=session.privacy_policy.permits_remote(task.classification),
        user_approved=False,
        local_memory_bytes=None,
        local_requirements={} if local_executor_available
        else {LOCAL_EXECUTOR_DIMENSION: 1.0},
    )


def capability_signals(assessment: Assessment) -> dict[str, Any]:
    """The §11 signals, read out of the assessment the router used.

    Read rather than re-measured. Two probes of "is there a GPU" taken a second
    apart can disagree, and a decision explained by a different measurement from
    the one it was made on is an explanation that will eventually be wrong in a
    way nobody can reproduce.
    """
    inventory = assessment.inventory
    scores = assessment.scores
    policy = assessment.policy
    budget = assessment.budget

    # `usable_gpus` rather than `gpu`: the inventory is explicit that presence is
    # not usability, and asking the wrong question here would report a GPU to a
    # user whose driver never bound.
    gpu_ready = bool(inventory.usable_gpus)
    local_ai = scores.get("local_ai")
    return {
        "localAiScore": local_ai.value,
        "localAiConfidence": local_ai.confidence,
        # An unmeasured dimension does not satisfy a requirement; the router
        # takes the same position, so the two agree by construction.
        "localAiEligible": bool(local_ai.at_least(1.0, when_unknown=False)),
        "usableMemoryBytes": inventory.memory.usable_bytes(None),
        "availableMemoryBytes": inventory.memory.usable_available_bytes(None),
        "allocatableBytes": budget.currently_allocatable_bytes,
        "budgetViable": budget.viable,
        "cpuScore": scores.get("cpu_compute").value,
        "gpuAvailable": gpu_ready,
        "gpuScore": scores.get("gpu_compute").value,
        "networkOnline": inventory.network.online,
        "networkOffline": inventory.network.offline,
        "networkMetered": inventory.network.metered.get(None),
        "meteredNetworkAllowed": policy.metered_network_allowed,
        "remoteExecutionEnabled": policy.remote_execution.enabled,
        "remoteRequiresApproval": policy.remote_execution.require_user_approval,
        "remoteAllowsSensitiveData": policy.remote_execution.allow_sensitive_data,
        "onBattery": inventory.power.on_battery,
        "batteryPercent": inventory.power.battery_percent.get(None),
        "powerSaving": inventory.power.power_saving.get(None),
        "thermalThrottled": inventory.thermal.throttled.get(None),
        "preferLocal": policy.prefer_local,
        "preferLowEnergy": policy.prefer_low_energy,
    }


@dataclass(frozen=True)
class ExecutorEligibility:
    """Whether one executor may take one task, and every reason."""

    executor_id: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    requires_approval: bool = False
    approval_action: str = ""
    destination: str = "local"

    def to_json(self) -> dict[str, Any]:
        return {
            "executorId": self.executor_id,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "requiresApproval": self.requires_approval,
            "approvalAction": self.approval_action,
            "destination": self.destination,
        }


@dataclass(frozen=True)
class CapabilityDecision:
    """The capability answer for one task, with its plan identity attached."""

    task_id: str
    plan_id: str
    plan_fingerprint: str
    route: RouteDecision
    signals: Mapping[str, Any] = field(default_factory=dict)
    eligibility: tuple[ExecutorEligibility, ...] = ()
    selected_executor: str = ""
    blocked_reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return bool(self.selected_executor)

    def selection(self) -> ExecutorEligibility | None:
        for item in self.eligibility:
            if item.executor_id == self.selected_executor:
                return item
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "planId": self.plan_id,
            "planFingerprint": self.plan_fingerprint,
            "eligible": self.eligible,
            "selectedExecutor": self.selected_executor,
            "route": self.route.to_json(),
            "signals": dict(self.signals),
            "executors": [item.to_json() for item in self.eligibility],
            "blockedReasons": list(self.blocked_reasons),
        }


def _any_local_can_serve(
    local_executors: Sequence[Executor],
    task: CompanionTask,
    session: CompanionSession,
    decision: RouteDecision,
) -> bool:
    """Whether any local executor would take this task under the first routing.

    Asked with the same predicate the eligibility loop uses, so "a local
    executor is available" and "a local executor is eligible" cannot drift
    into two different answers.
    """
    for executor in local_executors:
        if _declaration_reasons(executor.declaration, task, session, decision):
            continue
        try:
            if executor.health().ready:
                return True
        except Exception:  # noqa: BLE001 - a health fault is an unavailable executor
            continue
    return False


def _remote_offered(decision: RouteDecision) -> bool:
    """Whether the router put a remote destination on the table.

    Two shapes mean yes, and conflating them was a real gap. ``target ==
    "remote"`` is the router saying "go ahead"; ``requires_user_approval``
    with a named provider is the router saying "this destination is
    permissible *once somebody consents*" — which is the whole reason
    :class:`~capability.router.RouteDecision` carries a ``disclosure`` of what
    would leave the device. The companion never sets ``user_approved`` on the
    request (:func:`task_request_for` says so, deliberately: consent belongs
    to a specific plan and destination, which do not exist yet), so under the
    shipped policy the router *always* returns the second shape — and reading
    only the first made every configured remote provider permanently
    unreachable, with "the router did not permit remote execution" as the
    reason, which was true of the code and false of the policy.

    Eligible-pending-approval is not permission. It puts the destination in
    front of :mod:`companion.approvals`, whose gate asks, binds the answer to
    the plan and the destination fingerprint, and refuses everything §8 lists.
    """
    if decision.target == "remote":
        return True
    return bool(decision.requires_user_approval and decision.provider_id)


def _declaration_reasons(
    declaration: ExecutorDeclaration,
    task: CompanionTask,
    session: CompanionSession,
    decision: RouteDecision,
) -> list[str]:
    """Everything that disqualifies an executor, gathered rather than short-circuited.

    All the reasons, not the first one. A user told "this cannot run" deserves
    the whole answer; being told about the memory and then, after installing
    more, about the privacy class is how a system wastes somebody's afternoon.
    """
    reasons: list[str] = []
    if not declaration.fully_declared:
        reasons.append(
            f"{declaration.executor_id!r} has not fully declared itself; an undeclared executor fails closed"
        )
    if not declaration.handles(task.task_type):
        reasons.append(
            f"{declaration.executor_id!r} does not serve task type {task.task_type!r}"
        )
    if rank(task.classification) > rank(declaration.maximum_privacy_class):
        reasons.append(
            f"the task is classified {task.classification} and {declaration.executor_id!r} "
            f"may hold data up to {declaration.maximum_privacy_class}"
        )
    if not declaration.local:
        if not _remote_offered(decision):
            reasons.append(
                f"{declaration.executor_id!r} is remote and the router did not permit remote execution "
                f"for this task ({decision.target})"
            )
        if not session.privacy_policy.allow_remote:
            reasons.append("this session does not permit remote execution")
    if declaration.cost_class == "paid":
        permitted = min(task.cost_limit_units, session.cost_policy.task_limit_units) \
            if session.cost_policy.task_limit_units else task.cost_limit_units
        if permitted <= 0:
            reasons.append(
                f"{declaration.executor_id!r} bills for use and this task permits no spend"
            )
    if declaration.cost_class == "metered" and task.requires_offline:
        reasons.append(
            f"{declaration.executor_id!r} needs a connection and the task declares an offline requirement"
        )
    return reasons


def _blocked_reasons(
    decision: RouteDecision,
    eligibility: Sequence[ExecutorEligibility],
    *,
    local_executor_unavailable: bool = False,
) -> tuple[str, ...]:
    """Why nothing may take this task, in an order a person can act on.

    The lead sentence separates the ways this happens, because they call for
    opposite responses: the router refusing to place the task at all is a policy
    or privacy question, whereas the router permitting local execution while no
    local executor is eligible is a *configuration* question, and telling a user
    "local execution satisfies every requirement" while refusing to run locally
    would read as a contradiction.

    ``local_executor_unavailable`` marks the third case, and it leads with the
    executor's own reasons on purpose. When the companion has told the router
    that nothing here can do the work, the router's answer is *downstream* of
    that fact — "the task declares device-only data locality" is true and
    useless, while "the synthesiser is not installed" is what the person can
    act on. Putting the router first cost exactly that: a measured regression
    where the actionable sentence fell past the three the error summary keeps.
    """
    reasons: list[str] = []
    if local_executor_unavailable:
        reasons.append(
            "no configured executor can perform this task on this machine"
        )
        for item in eligibility:
            reasons.extend(item.reasons)
        if not eligibility:
            reasons.append("no executor is configured")
        reasons.append(
            "and no remote destination was available either: "
            + "; ".join(decision.reasons)
            if decision.reasons else "and no remote destination was available either"
        )
        return tuple(reasons)
    if decision.target == "refused":
        reasons.append("the capability router refused to place this task")
        reasons.extend(decision.reasons)
    elif decision.target == "local":
        reasons.append(
            "the capability router permits local execution, but no configured executor "
            "is eligible to perform it"
        )
    else:
        reasons.append(
            f"the capability router placed this task with {decision.provider_id!r}, but no "
            "configured executor is eligible to use it"
        )
        reasons.extend(decision.reasons)
    if not eligibility:
        reasons.append("no executor is configured")
    for item in eligibility:
        reasons.extend(item.reasons)
    return tuple(reasons)


def evaluate_task(
    task: CompanionTask,
    session: CompanionSession,
    executors: Sequence[Executor],
    assessment: Assessment,
    *,
    providers: Sequence[RemoteProvider] = (),
) -> CapabilityDecision:
    """Decide which executor, if any, may take this task.

    Local executors are considered first and are preferred whenever one is
    eligible, whatever the router said about remote being available. Remote is
    reached only when the router itself offered the destination — either
    outright or pending the user's consent, see :func:`_remote_offered` — and
    even then the decision carries ``requires_approval`` so that
    :mod:`companion.approvals` gets the last word.
    """
    request = task_request_for(task, session)
    decision = route(request, assessment.inventory, assessment.scores, assessment.budget, assessment.policy, providers)
    local_executors = tuple(item for item in executors if item.declaration.local)
    local_unavailable = not _any_local_can_serve(local_executors, task, session, decision)
    if local_unavailable:
        # The router said local because it was asked a hardware question and
        # this machine has the hardware. It does not have an executor, which
        # only the companion knows — so the question is asked again with that
        # fact supplied, and the router settles remote permission properly
        # instead of never being asked. A second route call, not a patched
        # decision: every refusal in it is still the router's.
        request = task_request_for(task, session, local_executor_available=False)
        decision = route(
            request, assessment.inventory, assessment.scores,
            assessment.budget, assessment.policy, providers,
        )
    signals = capability_signals(assessment)
    plan_id = assessment.plan.plan_id
    fingerprint = digest({
        "planId": plan_id,
        "signals": {key: signals[key] for key in sorted(signals)},
        "request": request.id,
    })

    eligibility: list[ExecutorEligibility] = []
    for executor in executors:
        declaration = executor.declaration
        reasons = _declaration_reasons(declaration, task, session, decision)
        health = executor.health()
        if not health.ready:
            reasons.append(
                f"{declaration.executor_id!r} is not ready"
                + (f": {health.detail}" if health.detail else "")
                + (" (not available)" if not health.available else "")
                + (" (not authenticated)" if not health.authenticated else "")
                + (" (unhealthy)" if not health.healthy else "")
            )
        requires_approval = False
        action = ""
        if not declaration.local:
            requires_approval = True
            action = "remote_dispatch"
        elif declaration.cost_class == "paid":
            requires_approval = True
            action = "paid_provider"
        eligibility.append(ExecutorEligibility(
            executor_id=declaration.executor_id,
            eligible=not reasons,
            reasons=tuple(reasons),
            requires_approval=requires_approval,
            approval_action=action,
            destination="local" if declaration.local else (decision.provider_id or declaration.provider_id),
        ))

    local_choice = next(
        (item for item in eligibility
         if item.eligible and item.destination == "local"),
        None,
    )
    if local_choice is not None:
        selected = local_choice.executor_id
        blocked: tuple[str, ...] = ()
    else:
        remote_choice = next(
            (item for item in eligibility if item.eligible and _remote_offered(decision)),
            None,
        )
        selected = remote_choice.executor_id if remote_choice is not None else ""
        blocked = () if selected else _blocked_reasons(
            decision, eligibility, local_executor_unavailable=local_unavailable,
        )

    return CapabilityDecision(
        task_id=task.task_id,
        plan_id=plan_id,
        plan_fingerprint=fingerprint,
        route=decision,
        signals=signals,
        eligibility=tuple(eligibility),
        selected_executor=selected,
        blocked_reasons=blocked,
    )


def require_executor(decision: CapabilityDecision) -> str:
    """The selected executor, or a refusal carrying every reason there was none."""
    if decision.selected_executor:
        return decision.selected_executor
    raise CapabilityRefused(
        "no executor is eligible for this task on this machine under this policy",
        reasons=decision.blocked_reasons,
    )

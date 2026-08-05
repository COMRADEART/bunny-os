# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The execution plan: what runs, where, and the reason for every decision.

A plan is a value, not a side effect. Nothing here starts, stops or suspends
anything — :mod:`capability.engine` produces this document and an orchestrator
applies it. Keeping the decision separable from the act is what makes
``bunny-os capability plan`` safe to run on a live machine, and what lets the
simulated-hardware tests assert on real decisions without a machine to make
them on.

Every decision carries its reasons as structured records rather than prose.
§11 requires that a user be able to see why something did not start, and prose
assembled at the point of refusal cannot be tested, cannot be translated, and
drifts from the arithmetic that produced it. A :class:`Reason` carries the code,
the measurement and the requirement, and :mod:`capability.explain` renders it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import PLAN_SCHEMA_VERSION
from .apply.identity import PlanIdentity
from .manifest import RequirementCheck

__all__ = [
    "ACTIONS",
    "APPROVAL_REASONS",
    "Decision",
    "ExecutionPlan",
    "REASON_CODES",
    "Reason",
    "RUNNING_ACTIONS",
]

#: What the engine may decide. These are the actions in §7 of the brief, with
#: "start with reduced resource limits" and "select a lightweight backend"
#: collapsed into the implementation ladder — reducing a service *is* selecting
#: a lower-ranked implementation, and modelling it twice would let the two
#: disagree.
ACTIONS = (
    "start_local",       # run here, at the selected implementation
    "start_remote",      # dispatch to a permitted remote provider
    "suspend",           # was running, must yield resources, can resume
    "stop",              # was running, must yield resources, cannot suspend
    "defer",             # cannot start yet; a dependency is not up
    "reject",            # will not start, with a stated reason
)

#: Actions that mean the service is expected to be up after the plan is applied.
RUNNING_ACTIONS = frozenset({"start_local", "start_remote"})

#: Reason codes. Fixed so that explanations, tests and any future UI agree on
#: what happened without parsing English.
REASON_CODES = (
    "selected",                    # this implementation was chosen
    "degraded",                    # a lower-ranked implementation was chosen
    "user-disabled",               # policy.disabled_services
    "pin-honoured",                # policy pinned this implementation and it fits
    "pin-unsatisfiable",           # policy pinned one that does not fit
    "requirement-unmet",           # a declared requirement was not satisfied
    "requirement-unknown",         # a requirement could not be evaluated
    "budget-exhausted",            # the remaining memory budget cannot hold it
    "no-implementation",           # nothing in the ladder was eligible
    "conflict",                    # a conflicting service is already running
    "dependency-unavailable",      # a required service is not running
    "remote-not-permitted",        # remote execution is off, or the provider is not allowlisted
    "remote-approval-required",    # remote is permitted but needs the user to say yes
    "remote-unreachable",          # no route, or the endpoint did not answer
    "metered-network",             # would spend a metered connection without permission
    "sensitive-data-local-only",   # the task or service handles data that may not leave
    "paid-api-confirmation",       # would spend money without confirmation
    "essential-shortfall",         # the machine cannot fund its own essential services
    "hysteresis-hold",             # held at its current state inside the threshold band
    "cooldown-hold",               # held at its current state inside the cooldown window
    "resource-pressure",           # running work is yielding to a live pressure signal
)

#: Reason codes that mean a decision cannot be acted on until a person says yes.
#: Derived from the reasons rather than stored as a separate flag: a plan with a
#: ``requiresApproval`` field that disagreed with its own reasons would leave the
#: applicator and the explanation telling a user different things.
APPROVAL_REASONS = frozenset({
    "remote-approval-required",
    "paid-api-confirmation",
})


@dataclass(frozen=True)
class Reason:
    """One structured contribution to a decision."""

    code: str
    message: str
    required: Any = None
    measured: Any = None

    def __post_init__(self) -> None:
        if self.code not in REASON_CODES:
            raise ValueError(f"unknown reason code: {self.code!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "required": self.required,
            "measured": self.measured,
        }


@dataclass(frozen=True)
class Decision:
    """What happens to one service, and every reason it happens."""

    service_id: str
    action: str
    implementation_id: str | None = None
    memory_grant_bytes: int = 0
    cpu_percent: float = 0.0
    reasons: Sequence[Reason] = ()
    checks: Sequence[RequirementCheck] = ()
    fallback: str = ""
    #: Monotonic seconds at which this service last changed action. Carried
    #: forward across plans so cooldown can be evaluated without a clock inside
    #: the engine, which is what keeps the engine testable and deterministic.
    state_changed_at: float = 0.0

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action: {self.action!r}")

    @property
    def running(self) -> bool:
        return self.action in RUNNING_ACTIONS

    def reason_codes(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in self.reasons)

    @property
    def requires_approval(self) -> bool:
        """Whether acting on this decision needs a person to say yes first."""
        return any(reason.code in APPROVAL_REASONS for reason in self.reasons)

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "action": self.action,
            "implementationId": self.implementation_id,
            "memoryGrantBytes": self.memory_grant_bytes,
            "cpuPercent": round(self.cpu_percent, 1),
            "fallback": self.fallback,
            "requiresApproval": self.requires_approval,
            "reasons": [reason.to_json() for reason in self.reasons],
            "checks": [check.to_json() for check in self.checks],
        }


@dataclass(frozen=True)
class ExecutionPlan:
    """The complete set of decisions for one evaluation."""

    decisions: Sequence[Decision] = ()
    generated_at: str = ""
    notes: Sequence[str] = ()
    #: Total memory granted across running services. Never exceeds the budget's
    #: allocatable figure; the engine asserts this before returning.
    granted_memory_bytes: int = 0
    #: What makes this plan *this* plan. ``None`` only for a plan assembled by
    #: hand in a test; :func:`capability.engine.evaluate` always sets it, and
    #: :mod:`capability.apply` refuses to apply a plan without one — an
    #: unidentified plan is a plan whose staleness cannot be checked.
    identity: PlanIdentity | None = None

    def by_id(self) -> Mapping[str, Decision]:
        return {decision.service_id: decision for decision in self.decisions}

    def decision(self, service_id: str) -> Decision | None:
        return self.by_id().get(service_id)

    def running(self) -> tuple[Decision, ...]:
        return tuple(decision for decision in self.decisions if decision.running)

    def awaiting_approval(self) -> tuple[Decision, ...]:
        return tuple(decision for decision in self.decisions if decision.requires_approval)

    @property
    def plan_id(self) -> str:
        return self.identity.plan_id if self.identity is not None else ""

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": PLAN_SCHEMA_VERSION,
            "identity": self.identity.to_json() if self.identity is not None else None,
            "generatedAt": self.generated_at,
            "grantedMemoryBytes": self.granted_memory_bytes,
            "summary": {
                "total": len(self.decisions),
                "running": len(self.running()),
                "local": sum(1 for item in self.decisions if item.action == "start_local"),
                "remote": sum(1 for item in self.decisions if item.action == "start_remote"),
                "suspended": sum(1 for item in self.decisions if item.action == "suspend"),
                "stopped": sum(1 for item in self.decisions if item.action == "stop"),
                "deferred": sum(1 for item in self.decisions if item.action == "defer"),
                "rejected": sum(1 for item in self.decisions if item.action == "reject"),
                "awaitingApproval": len(self.awaiting_approval()),
            },
            "decisions": [decision.to_json() for decision in self.decisions],
            "notes": list(self.notes),
        }

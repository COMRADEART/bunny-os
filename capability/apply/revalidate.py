# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply-time revalidation: is this plan still true?

A plan is a statement about a machine at an instant. Between that instant and
the moment a service is started, a user can open forty browser tabs, unplug a
laptop, withdraw a permission, or install a new manifest. Starting a service
against the memory figure from before any of that is how an adaptive system
becomes the thing that killed somebody's compiler.

So every resource-increasing action is revalidated immediately before it runs,
against fresh measurements, and the checks are ordered from cheapest and most
decisive to most expensive:

1. Has a newer plan superseded this one? — a comparison of two integers.
2. Has this plan expired?
3. Do the fingerprints still match — inventory, policy, manifests?
4. Is the budget still sufficient, and does the protected reserve still hold?
5. Are the dependencies still up?
6. Are the approvals still valid?
7. Is remote execution still permitted?

**A failed check never adjusts the plan.** The rule §5 states — *do not silently
mutate the old plan to make it fit* — is enforced by this module having no way
to do so: it returns a verdict, and the verdict's only remedies are "do not
apply" and "ask the engine again". There is no code path from here that writes a
smaller number into a decision and proceeds.

Revalidation is deliberately **not** run before releases. Stopping a service,
lowering a limit and suspending something all make the machine safer, and
refusing to do them because a fingerprint moved would leave a machine under
pressure holding onto exactly the work it needs to shed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .identity import (
    PlanIdentity,
    budget_fingerprint,
    inventory_fingerprint,
    policy_fingerprint,
    registry_fingerprint,
)
from .state import ActualState, DesiredService

__all__ = [
    "RevalidationVerdict",
    "revalidate_plan",
    "revalidate_transition",
]


@dataclass(frozen=True)
class RevalidationVerdict:
    """Whether an action may proceed, and what to do if not."""

    ok: bool
    failure_class: str | None = None
    #: One line per check that failed, in the order they were run.
    problems: tuple[str, ...] = ()
    #: What to tell the engine, when the right response is a fresh decision.
    reevaluation_reason: str | None = None
    #: Checks that passed, kept so an explanation can show the work rather than
    #: only the objection. A user told "validation failed" learns nothing; one
    #: told which five things were checked and which one moved learns what
    #: happened to their machine.
    checked: tuple[Mapping[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failureClass": self.failure_class,
            "problems": list(self.problems),
            "reevaluationReason": self.reevaluation_reason,
            "checked": [dict(item) for item in self.checked],
        }


def _check(name: str, satisfied: bool, required: Any, measured: Any, detail: str = "") -> dict[str, Any]:
    return {
        "check": name,
        "satisfied": satisfied,
        "required": required,
        "measured": measured,
        "detail": detail,
    }


def revalidate_plan(
    identity: PlanIdentity | None,
    *,
    inventory: Any,
    budget: Any,
    policy: Any,
    registry: Any,
    now: float,
    in_force: PlanIdentity | None = None,
    supported_schema_version: int,
) -> RevalidationVerdict:
    """Check that a plan as a whole may still be applied.

    Run once per reconciliation, before any transition. The per-transition
    checks in :func:`revalidate_transition` are the ones that must be repeated
    immediately before each resource-increasing act; these are the ones that
    would invalidate the whole batch, and running them once keeps a
    forty-service reconciliation from fingerprinting the inventory forty times.
    """
    problems: list[str] = []
    checked: list[Mapping[str, Any]] = []

    if identity is None:
        return RevalidationVerdict(
            False, "invalid_plan",
            ("this plan carries no identity, so its staleness cannot be checked",),
            reevaluation_reason="apply_time_validation_failed",
        )

    if identity.schema_version != supported_schema_version:
        return RevalidationVerdict(
            False, "invalid_plan",
            (
                f"this plan declares schema version {identity.schema_version} and this applicator "
                f"applies version {supported_schema_version}",
            ),
            reevaluation_reason="apply_time_validation_failed",
            checked=(_check("plan.schemaVersion", False, supported_schema_version, identity.schema_version),),
        )
    checked.append(_check("plan.schemaVersion", True, supported_schema_version, identity.schema_version))

    # Supersession first: it is the cheapest check and the most decisive. A plan
    # that has been replaced should not spend time proving its fingerprints.
    if in_force is not None and not identity.supersedes(in_force) and identity.plan_id != in_force.plan_id:
        return RevalidationVerdict(
            False, "superseded_plan",
            (
                f"revision {identity.revision} has been superseded by revision {in_force.revision} "
                f"({in_force.plan_id})",
            ),
            checked=(_check("plan.revision", False, f"> {in_force.revision}", identity.revision),),
        )
    checked.append(_check(
        "plan.revision", True,
        f"> {in_force.revision}" if in_force is not None else "any",
        identity.revision,
    ))

    expired = identity.expired(now)
    checked.append(_check(
        "plan.age", not expired, f"<= {identity.maximum_age_seconds}s",
        round(identity.age_seconds(now), 1),
        "measured on the engine's clock, not on wall clock",
    ))
    if expired:
        problems.append(
            f"this plan is {identity.age_seconds(now):.0f}s old against a "
            f"{identity.maximum_age_seconds:.0f}s maximum"
        )
        return RevalidationVerdict(
            False, "stale_plan", tuple(problems),
            reevaluation_reason="apply_time_validation_failed",
            checked=tuple(checked),
        )

    fingerprints = (
        ("inventory", identity.inventory_fingerprint, inventory_fingerprint(inventory),
         "the machine changed after this plan was decided", "stale_plan"),
        ("budget", identity.budget_fingerprint, budget_fingerprint(budget),
         "the resource budget changed after this plan was decided", "stale_plan"),
        ("policy", identity.policy_fingerprint, policy_fingerprint(policy),
         "policy changed after this plan was decided", "stale_plan"),
        ("registry", identity.registry_fingerprint, registry_fingerprint(registry),
         "a service manifest changed after this plan was decided", "stale_plan"),
    )
    failure_class: str | None = None
    for name, expected, observed, description, klass in fingerprints:
        matched = expected == observed
        checked.append(_check(f"fingerprint.{name}", matched, expected, observed, description))
        if not matched:
            problems.append(f"{description} ({name} fingerprint {expected} is now {observed})")
            failure_class = klass

    if problems:
        return RevalidationVerdict(
            False, failure_class or "stale_plan", tuple(problems),
            reevaluation_reason="apply_time_validation_failed",
            checked=tuple(checked),
        )
    return RevalidationVerdict(True, checked=tuple(checked))


def revalidate_transition(
    service: DesiredService,
    *,
    budget: Any,
    policy: Any,
    actual: ActualState,
    available_bytes: int,
    approvals: Sequence[str] = (),
    now: float = 0.0,
) -> RevalidationVerdict:
    """Check one resource-increasing transition, immediately before it runs.

    Called with **fresh** figures. Passing the same budget object the plan was
    made from would make this an expensive way of comparing a number to itself;
    the caller's contract is that ``budget`` and ``available_bytes`` were
    obtained after the plan was, and the applicator honours that by refreshing
    them at the top of each apply.
    """
    problems: list[str] = []
    checked: list[Mapping[str, Any]] = []
    failure_class: str | None = None

    grant = service.memory_limit_bytes
    fits = grant <= available_bytes
    checked.append(_check(
        "budget.available", fits, grant, available_bytes,
        "measured against what the ledger can still promise, not against free physical memory",
    ))
    if not fits:
        problems.append(
            f"starting {service.service_id} needs {grant} bytes and {available_bytes} bytes "
            "remain of the allocatable budget"
        )
        failure_class = "insufficient_resources"

    # The reserve is checked separately from the budget even though the budget
    # already excludes it. Two independent statements of the same invariant is
    # the point: if a future change to the budget engine ever let the reserve
    # into an allocatable figure, this check would catch it at the moment of
    # allocation rather than after the OOM killer did.
    reserve = getattr(budget, "protected_reserve_bytes", 0)
    currently_available = getattr(budget, "currently_available_bytes", None)
    if currently_available is not None:
        remaining_after = currently_available - grant
        reserve_held = remaining_after >= reserve
        checked.append(_check(
            "budget.protectedReserve", reserve_held, reserve, remaining_after,
            "memory that would remain free after this grant, against the reserve that nothing may take",
        ))
        if not reserve_held:
            problems.append(
                f"starting {service.service_id} would leave {remaining_after} bytes free against "
                f"a {reserve} byte protected reserve"
            )
            failure_class = "protected_reserve_violation"

    missing = [
        dependency for dependency in sorted(service.requires)
        if not actual.get(dependency).active
    ]
    checked.append(_check("dependencies", not missing, sorted(service.requires), missing))
    if missing:
        problems.append(f"{service.service_id} requires {', '.join(missing)}, which stopped being available")
        failure_class = failure_class or "dependency_unavailable"

    if service.requires_approval:
        approved = service.service_id in approvals
        checked.append(_check("approval", approved, "an unexpired approval", approved))
        if not approved:
            problems.append(f"{service.service_id} needs an approval and none is currently valid")
            failure_class = failure_class or "approval_missing"

    if service.locality == "remote":
        remote = getattr(policy, "remote_execution", None)
        enabled = bool(getattr(remote, "enabled", False))
        checked.append(_check("policy.remoteExecution", enabled, True, enabled))
        if not enabled:
            problems.append(
                f"{service.service_id} was planned to run remotely and remote execution is no "
                "longer permitted by policy"
            )
            failure_class = "stale_plan"

    if problems:
        return RevalidationVerdict(
            False, failure_class or "stale_plan", tuple(problems),
            reevaluation_reason="apply_time_validation_failed",
            checked=tuple(checked),
        )
    return RevalidationVerdict(True, checked=tuple(checked))

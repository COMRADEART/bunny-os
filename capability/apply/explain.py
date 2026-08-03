# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering what the applicator did, in a form a person can check.

Same rule as :mod:`capability.explain`: nothing here recomputes or paraphrases.
Every line comes from a structured record produced at the moment the thing
happened, so an explanation cannot drift from the act it describes.

The shape of every explanation is fixed, because the questions a person asks
about a machine that changed underneath them are always the same four:

    What happened?    — the service, and the operation
    Why?              — the measurements, side by side with the requirements
    What was done?    — including, explicitly, what was *not* done
    What does it mean for me?  — what still works, and what to do about it

The fourth section is not decoration. A user told that a transition was
postponed because of a protected reserve has been given a fact; a user told that
their machine is still fully usable without local AI, and that remote execution
remains off, has been given an answer.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ..explain import format_bytes
from .reconcile import Blocked, ReconciliationPlan
from .state import Transition

__all__ = [
    "render_blocked",
    "render_reconciliation",
    "render_report",
    "render_transition",
]

#: Plain-language names for the operations. The vocabulary a user sees is not
#: the vocabulary the code uses, and mapping between them here — once — is
#: better than either using code words in a UI or code that reads like prose.
_OPERATION_TITLES: Mapping[str, str] = {
    "start": "Start the service",
    "stop": "Stop the service",
    "suspend": "Suspend the service, keeping its state",
    "resume": "Resume the suspended service",
    "reload": "Reload the service's configuration",
    "apply_limits": "Adjust the service's resource limits",
    "probe": "Check the service's state",
    "rollback": "Undo a failed change",
}

_RESULT_HEADLINES: Mapping[str, str] = {
    "succeeded": "Transition completed.",
    "failed": "Transition failed.",
    "rolled_back": "Transition failed and was rolled back.",
    "postponed": "Transition was postponed.",
    "rejected": "Transition was rejected.",
    "cancelled": "Transition was cancelled.",
}

_BLOCK_HEADLINES: Mapping[str, str] = {
    "already_converged": "No change was needed.",
    "waiting_for_dependency": "Waiting for another service.",
    "waiting_for_resources": "Waiting for resources.",
    "waiting_for_approval": "Waiting for your approval.",
    "waiting_for_network": "Waiting for a network connection.",
    "conflict": "Blocked by a conflicting service.",
    "externally_managed": "Not Bunny OS's to change.",
    "essential_protected": "Refused, to protect an essential service.",
    "user_work_protected": "Refused, to protect work in progress.",
    "circuit_open": "Paused after repeated failures.",
    "retry_backoff": "Waiting before trying again.",
    "state_unknown": "The service's state could not be observed.",
    "not_authorized": "Not permitted on this backend.",
    "plan_forbids": "The plan does not permit this.",
}


def _bytes_or_value(value: Any) -> str:
    """Format a number as bytes when it plausibly is some, otherwise plainly."""
    if isinstance(value, bool) or not isinstance(value, int):
        return str(value)
    return format_bytes(value) if value > 4096 else str(value)


def render_transition(transition: Transition, *, service_title: str = "") -> str:
    """The full explanation for one transition, in the shape §16 specifies."""
    result = transition.result
    headline = _RESULT_HEADLINES.get(
        result.result if result is not None else "", "Transition is in progress.",
    )

    lines = [headline, "", "Service:", f"  {transition.service_id}"]
    if service_title:
        lines.append(f"  {service_title}")
    lines.extend([
        "",
        "Requested action:",
        f"  {_OPERATION_TITLES.get(transition.operation, transition.operation)}",
        f"  {transition.source_state} -> {transition.target_state}",
        "",
        "Reason:",
    ])

    for entry in transition.explanation:
        lines.extend(_explanation_lines(entry))

    if result is not None and result.detail:
        lines.append(f"  - {result.detail}")
    if result is not None and result.failure_class:
        lines.append(f"  - classified as: {result.failure_class}")

    lines.extend(["", "Action taken:"])
    lines.extend(_action_lines(transition))

    lines.extend(["", "User impact:"])
    lines.extend(_impact_lines(transition))

    duration = transition.duration_seconds()
    if duration is not None:
        lines.extend([
            "",
            f"Took {duration:.2f}s of a {transition.timeout_seconds:.0f}s deadline.",
        ])

    lines.extend([
        "",
        "This explanation describes system measurements and deterministic policy.",
        "It contains no model reasoning.",
    ])
    return "\n".join(lines)


def _explanation_lines(entry: Mapping[str, Any]) -> list[str]:
    """One structured explanation record, rendered.

    ``fact`` and ``inference`` are rendered differently and labelled, because
    the whole value of separating them upstream is lost if they are printed the
    same way.
    """
    lines: list[str] = []
    kind = entry.get("fact") or entry.get("inference")

    if entry.get("fact") == "desired":
        lines.append(
            f"  - The plan asked for {entry.get('action')}"
            + (f" using {entry.get('implementationId')}" if entry.get("implementationId") else "")
            + (
                f", with {_bytes_or_value(entry.get('memoryLimitBytes'))} of memory"
                if entry.get("memoryLimitBytes") else ""
            )
        )
    elif entry.get("fact") == "actual":
        lines.append(
            f"  - The service was observed {entry.get('state')} "
            f"(by {entry.get('observedBy')})"
        )
    elif entry.get("fact") == "operation":
        lines.append(
            f"  - The safe operation for that difference is {entry.get('operation')}, "
            f"bounded at {entry.get('timeoutSeconds')}s"
        )
    elif entry.get("fact") == "apply-time validation":
        for check in entry.get("checks", []):
            mark = {True: "ok  ", False: "FAIL", None: "?   "}.get(check.get("satisfied"), "?   ")
            lines.append(
                f"    {mark} {check.get('check')}: required "
                f"{_bytes_or_value(check.get('required'))}, "
                f"measured {_bytes_or_value(check.get('measured'))}"
            )
            if check.get("detail"):
                lines.append(f"         {check['detail']}")
    elif entry.get("fact") == "limits":
        enforced = entry.get("enforced")
        lines.append(
            "  - Resource limits were "
            + ("applied and confirmed in force" if enforced else "NOT enforced")
        )
        if not enforced:
            lines.append(
                "    Bunny OS does not claim a service is constrained when the limit was not applied."
            )
    elif entry.get("fact") == "resources":
        lines.append(f"  - {entry.get('note')}")
    elif entry.get("fact") == "health":
        lines.append(f"  - A bounded health check was run by {entry.get('checkedBy')} and passed")
    elif entry.get("fact") == "rollback":
        for step in entry.get("steps", []):
            lines.append(f"  - {step}")
    elif kind is not None:
        label = "inference" if entry.get("inference") else "fact"
        lines.append(f"  - [{label}] {kind}")
    return lines


def _action_lines(transition: Transition) -> list[str]:
    """What was actually done — and, for a refusal, what was deliberately not."""
    result = transition.result
    if result is None:
        return ["  - the transition has not finished"]

    if result.result == "succeeded":
        lines = [f"  - {_OPERATION_TITLES.get(transition.operation, transition.operation)} completed"]
        if transition.reservation_id:
            lines.append(f"  - reservation {transition.reservation_id} was committed")
        return lines

    if result.result == "postponed":
        return [
            "  - no process was started",
            "  - no reservation was held",
            "  - capability reevaluation was requested"
            if result.reevaluation_reason else "  - the transition will be retried when it is due",
        ]

    if result.result == "rolled_back":
        return [
            "  - the partially started service was stopped",
            "  - the reservation was released",
            "  - the machine was returned to the state it was in before the attempt",
        ]

    if result.result == "rejected":
        return ["  - nothing was attempted", "  - a fresh plan is required"]

    return [f"  - the operation failed and was recorded as {result.failure_class or 'unclassified'}"]


def _impact_lines(transition: Transition) -> list[str]:
    """What this means for the person using the machine."""
    result = transition.result
    if result is None:
        return ["  - none yet"]

    operation = transition.operation
    if result.result == "succeeded":
        return {
            "start": ["  - the service's features are now available"],
            "stop": ["  - the service's features are unavailable until it starts again"],
            "suspend": [
                "  - the service is paused and its state was kept",
                "  - it can resume without losing work",
            ],
            "resume": ["  - the service is available again, with the state it had"],
            "apply_limits": ["  - no feature changed; the service now uses fewer resources"],
        }.get(operation, ["  - the machine matches the plan for this service"])

    if result.result in ("postponed", "rolled_back", "failed"):
        return [
            "  - the service is not running, and nothing it would have provided is available",
            "  - no other service was affected",
            "  - nothing was sent anywhere and no data was discarded",
        ]
    return ["  - no change was made to the machine"]


def render_blocked(item: Blocked) -> str:
    """Why a difference between desired and actual was deliberately left alone."""
    lines = [
        _BLOCK_HEADLINES.get(item.reason, "Transition was not performed."),
        "",
        "Service:",
        f"  {item.service_id}",
        "",
        "Reason:",
        f"  - {item.detail}",
    ]
    if item.desired_action:
        lines.append(f"  - the plan asked for: {item.desired_action}")
    if item.actual_state:
        lines.append(f"  - the service was observed: {item.actual_state}")

    if item.adaptation is not None:
        lines.extend(["", "Adaptation cost:", f"  - class: {item.adaptation.adaptation_class}"])
        lines.append(f"  - user-work policy: {item.adaptation.user_work_policy}")
        lines.extend(f"  - {reason}" for reason in item.adaptation.reasons)

    lines.extend(["", "Action taken:", "  - nothing was started, stopped or sent"])
    if item.fallback:
        lines.extend(["", "User impact:", f"  - {item.fallback}"])
    return "\n".join(lines)


def render_reconciliation(plan: ReconciliationPlan) -> str:
    """A one-line-per-service summary of a reconciliation."""
    if plan.converged and not plan.blocked:
        return (
            f"Plan {plan.plan_id} (revision {plan.revision}) is already applied. "
            "No transition is needed."
        )

    lines = [f"Reconciliation for plan {plan.plan_id}, revision {plan.revision}", ""]
    if plan.transitions:
        lines.append("  Transitions, in the order they will run:")
        width = max(len(item.service_id) for item in plan.transitions)
        for item in plan.transitions:
            lines.append(
                f"    {item.sequence:>2}. {item.service_id:{width}}  {item.operation:<12} "
                f"{item.source_state} -> {item.target_state}"
            )
    else:
        lines.append("  No transition is safe to perform right now.")

    if plan.blocked:
        lines.extend(["", "  Differences deliberately left alone:"])
        width = max(len(item.service_id) for item in plan.blocked)
        for item in plan.blocked:
            lines.append(f"    {item.service_id:{width}}  {item.reason:<24} {item.detail[:72]}")

    if plan.notes:
        lines.append("")
        lines.extend(f"  note: {note}" for note in plan.notes)
    return "\n".join(lines)


def render_report(report: Any) -> str:
    """A summary of one apply pass, prefixed with what kind of pass it was."""
    banner = (
        "DRY RUN - nothing on this machine was changed."
        if report.dry_run else
        "REAL HOST OPERATION - services on this machine were changed."
    )
    lines = [banner, "", f"Plan {report.plan_id}, revision {report.revision}", ""]

    if report.validation is not None and not report.validation.ok:
        lines.extend(["Plan rejected before anything was attempted:", ""])
        lines.extend(f"  - {problem}" for problem in report.validation.problems)
        lines.extend([
            "",
            f"  classified as: {report.validation.failure_class}",
            "  No service was started, stopped or sent anywhere.",
        ])
        if report.reevaluation_reason:
            lines.append(f"  Capability reevaluation was requested: {report.reevaluation_reason}")
        return "\n".join(lines)

    if report.applied:
        lines.append("Transitions:")
        width = max(len(item.service_id) for item in report.applied)
        for item in report.applied:
            outcome = item.result.result if item.result is not None else "pending"
            lines.append(f"  {item.service_id:{width}}  {item.operation:<12} {outcome}")
            if item.result is not None and item.result.detail and outcome != "succeeded":
                lines.append(f"  {'':{width}}    {item.result.detail[:90]}")
    else:
        lines.append("No transition was performed; the machine already matches the plan.")

    if report.blocked:
        lines.extend(["", "Left alone:"])
        width = max(len(item.service_id) for item in report.blocked)
        for item in report.blocked:
            lines.append(f"  {item.service_id:{width}}  {item.reason}")

    if report.reclaimed:
        lines.extend([
            "",
            f"Reclaimed {len(report.reclaimed)} orphaned reservation(s) before reconciling.",
        ])

    if report.reevaluation_reason:
        lines.extend([
            "",
            f"Capability reevaluation was requested: {report.reevaluation_reason}",
        ])

    if report.notes:
        lines.append("")
        lines.extend(f"note: {note}" for note in report.notes)

    lines.extend([
        "",
        "Run 'bunny-os capability transitions --explain <transition-id>' for any line above.",
    ])
    return "\n".join(lines)

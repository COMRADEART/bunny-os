# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reviewers look and say what they think. That is the whole of their power.

The list of things a reviewer may not do — execute tools, modify files, approve
actions, control applications, change configuration, send task data anywhere, or
override the executor — is not enforced by asking reviewers nicely. It is
enforced by what a reviewer is given: a :class:`ReviewContext` holds no store,
no broker, no approval store, no runtime and no executor — only already-redacted
data, and a private copy of it. (``frozen=True`` on the dataclass freezes the
attribute bindings, not the dictionaries behind them; the isolation comes from
:func:`companion.coordination.run_review_round` copying, not from the keyword.) A reviewer that wanted to write a file would
have to import something itself, and a reviewer that did that is a reviewer
somebody installed deliberately, which is a packaging problem and not one an
interface can solve.

Two further defences exist for the case where a reviewer is hostile rather than
merely wrong. :meth:`companion.tools.ToolBroker.invoke` refuses any caller of
kind ``reviewer`` outright and records the attempt. And every observation is
validated by :func:`observation_from_json` before it reaches the event stream,
so a reviewer cannot smuggle structure into the record by returning something
shaped differently from what it declared.

What a reviewer *can* do is disagree, visibly and permanently. §10 requires
material disagreement to remain in the event record even when the executor
revises around it, so a ``reviewer_disagreement`` event is written and never
retracted. A future UI showing a completed task can therefore also show that
somebody objected and what was done about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .errors import MalformedOutput
from .privacy import MAX_SUMMARY_LENGTH, display_summary

__all__ = [
    "CATEGORIES",
    "DeterministicLocalReviewer",
    "ReviewContext",
    "ReviewObservation",
    "Reviewer",
    "SEVERITIES",
    "observation_from_json",
]

#: How serious the reviewer thinks it is. ``blocking`` does not stop the task —
#: reviewers cannot stop anything — but it is the level at which the runtime
#: records a disagreement rather than an observation, so it is the level that
#: survives into the permanent record as a dissent.
SEVERITIES = ("info", "low", "medium", "high", "blocking")

#: What the observation is about. Fixed so that a future UI can group and filter
#: without parsing English, and so that "privacy" concerns are countable.
CATEGORIES = ("correctness", "security", "privacy", "improvement", "policy")


@dataclass(frozen=True)
class ReviewObservation:
    """One structured remark. The shape is the brief's, field for field."""

    reviewer_id: str
    severity: str = "info"
    category: str = "correctness"
    summary: str = ""
    suggested_action: str = ""
    evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise MalformedOutput(f"severity must be one of {list(SEVERITIES)}")
        if self.category not in CATEGORIES:
            raise MalformedOutput(f"category must be one of {list(CATEGORIES)}")
        if not self.reviewer_id:
            raise MalformedOutput("an observation must name its reviewer")
        if not self.summary:
            raise MalformedOutput("an observation with no summary says nothing")
        if len(self.summary) > MAX_SUMMARY_LENGTH * 4:
            raise MalformedOutput("an observation summary is a summary, not a document")

    @property
    def material(self) -> bool:
        """Whether this rises to a recorded disagreement rather than a remark."""
        return self.severity in ("high", "blocking")

    def to_json(self) -> dict[str, Any]:
        return {
            "reviewerId": self.reviewer_id,
            "severity": self.severity,
            "category": self.category,
            "summary": self.summary,
            "suggestedAction": self.suggested_action,
            "evidenceEventIds": list(self.evidence_event_ids),
        }


def observation_from_json(value: Any, *, reviewer_id: str) -> ReviewObservation:
    """Validate whatever a reviewer returned.

    Reviewers are third-party code and their output is untrusted input. The
    ``reviewerId`` a reviewer puts in its own observation is checked against the
    identity the runtime invoked, so a reviewer cannot attribute a remark — or a
    disagreement — to somebody else.
    """
    if isinstance(value, ReviewObservation):
        observation = value
    elif isinstance(value, Mapping):
        evidence = value.get("evidenceEventIds", ())
        if not isinstance(evidence, (list, tuple)):
            raise MalformedOutput("evidenceEventIds must be an array")
        observation = ReviewObservation(
            reviewer_id=str(value.get("reviewerId", "")),
            severity=str(value.get("severity", "info")),
            category=str(value.get("category", "correctness")),
            summary=display_summary(str(value.get("summary", ""))),
            suggested_action=display_summary(str(value.get("suggestedAction", ""))),
            evidence_event_ids=tuple(str(item) for item in evidence),
        )
    else:
        raise MalformedOutput(
            f"a reviewer must return observation objects, not {type(value).__name__}"
        )
    if observation.reviewer_id != reviewer_id:
        raise MalformedOutput(
            f"{reviewer_id!r} returned an observation attributed to {observation.reviewer_id!r}; "
            "a reviewer may not speak for another"
        )
    return observation


@dataclass(frozen=True)
class ReviewContext:
    """Everything a reviewer sees. Read-only, redacted, and inert.

    ``events`` and ``task`` have already been through
    :func:`companion.privacy.project` at the ``reviewer`` ceiling, so content
    above ``internal`` arrives as a marker naming the class that was withheld.
    A reviewer therefore always knows when it is reviewing something it cannot
    fully read, which is what lets it say so instead of quietly approving.
    """

    task: Mapping[str, Any]
    plan: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...] = ()
    round_number: int = 1
    #: The classification of the task, so a reviewer can qualify its own remarks.
    classification: str = "internal"
    #: True when anything in this view was withheld from the reviewer.
    context_withheld: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "task": dict(self.task),
            "plan": dict(self.plan),
            "events": [dict(item) for item in self.events],
            "roundNumber": self.round_number,
            "classification": self.classification,
            "contextWithheld": self.context_withheld,
        }


class Reviewer(Protocol):
    """An observation-only critic."""

    reviewer_id: str

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        """Look at a redacted task and say what is wrong with it.

        Must return quickly. The runtime applies a timeout and continues without
        a reviewer that does not answer, because a review is advice and a task
        must not be held open waiting for advice.
        """


@dataclass
class DeterministicLocalReviewer:
    """The one shipped reviewer: local, pure, and always says the same thing.

    It checks one real property — that a plan which was asked to validate
    something actually contains a validation step — and reports honestly when
    the task's contents were withheld from it. Both are deliberate. The first
    gives the review-and-revise loop something true to be about. The second is
    the behaviour every reviewer should have and the one most likely to be
    omitted: a reviewer that cannot read the request should say its review is
    partial rather than return "no issues found".
    """

    reviewer_id: str = "local.test-reviewer"
    #: Set by a test to model a reviewer that never answers.
    hangs: bool = False
    #: Set by a test to model a reviewer returning something malformed.
    malformed: bool = False
    seen_contexts: list[Mapping[str, Any]] = field(default_factory=list)

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        self.seen_contexts.append(context.to_json())
        if self.hangs:
            raise TimeoutError(f"{self.reviewer_id} did not answer")
        if self.malformed:
            return [{"reviewerId": "somebody.else", "severity": "info", "summary": "x"}]  # type: ignore[list-item]

        observations: list[ReviewObservation] = []
        request = str(context.task.get("originalRequest", ""))
        operations = [str(item.get("name", "")) for item in context.plan.get("operations", ())]

        if context.context_withheld:
            observations.append(ReviewObservation(
                reviewer_id=self.reviewer_id,
                severity="info",
                category="privacy",
                summary=(
                    f"The task contents are classified {context.classification} and were withheld "
                    "from this reviewer; this review covers the plan only."
                ),
                suggested_action="Treat this review as partial.",
            ))

        wants_validation = "validat" in request.lower() or context.context_withheld
        has_validation = any("validate" in name for name in operations)
        if wants_validation and not has_validation:
            observations.append(ReviewObservation(
                reviewer_id=self.reviewer_id,
                severity="high",
                category="correctness",
                summary="The proposed output omits the requested validation step.",
                suggested_action="Run validation before completion.",
                evidence_event_ids=tuple(
                    str(event.get("eventId", ""))
                    for event in context.events
                    if event.get("eventType") == "planning_started"
                )[:4],
            ))
        elif has_validation:
            observations.append(ReviewObservation(
                reviewer_id=self.reviewer_id,
                severity="info",
                category="correctness",
                summary="The plan validates its own result before completing.",
            ))

        for operation in context.plan.get("operations", ()):
            if str(operation.get("destination", "local")) != "local":
                observations.append(ReviewObservation(
                    reviewer_id=self.reviewer_id,
                    severity="blocking",
                    category="privacy",
                    summary=(
                        f"Operation {operation.get('name')!r} sends task data to "
                        f"{operation.get('destination')!r}."
                    ),
                    suggested_action="Confirm the user approved this destination, or plan it locally.",
                ))
        return observations

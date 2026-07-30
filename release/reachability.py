"""Bounded reachability review for vulnerabilities with no available fix.

The brief fixes ten questions that a reachability review must answer, and fixes
the vocabulary of outcomes. Both are encoded here so a review cannot quietly
answer nine questions and conclude the tenth.

The load-bearing rule is that **an unanswered question is not a negative
answer**. Every question therefore has three states, and ``unknown`` propagates:
a review containing any ``unknown`` cannot reach ``Not reachable with
evidence``, because the evidence by definition does not exist. That is the
difference between "we looked and it is not reachable" and "we did not look".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from release.vulnerability import DISPOSITIONS, NON_BLOCKING_DISPOSITIONS

SCHEMA_VERSION = 1

#: The ten questions, in the brief's order. The key is the field name in a
#: review record; the value is the question as a reviewer would read it.
REACHABILITY_QUESTIONS: dict[str, str] = {
    "binaryInstalled": "Is the vulnerable binary installed in the shipped image?",
    "runsByDefault": "Does it run by default on a booted system?",
    "listensOnSocket": "Does it listen on a socket?",
    "unprivilegedInvocation": "Can an unprivileged user invoke it?",
    "bunnyOrPluginInvocation": "Can Bunny or a plugin invoke it?",
    "sandboxLimitsExposure": "Does sandboxing limit the exposure?",
    "vulnerableCodePathActive": "Is the vulnerable code path compiled in and active?",
    "packageRemovable": "Can the package be removed?",
    "functionalityIsolable": "Can the functionality be isolated?",
    "systemdOrSelinuxControl": "Does a systemd or SELinux control reduce exposure?",
}

ANSWERS = ("yes", "no", "unknown")

#: Answers that, taken together, describe something an attacker cannot reach.
#: Used only to *challenge* a claimed unreachability, never to infer one.
_EXPOSURE_INDICATORS = ("binaryInstalled", "runsByDefault", "listensOnSocket", "unprivilegedInvocation", "bunnyOrPluginInvocation", "vulnerableCodePathActive")


class ReachabilityError(ValueError):
    """Raised when a reachability review is malformed or overclaims."""


@dataclass(frozen=True)
class QuestionAnswer:
    answer: str
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {"answer": self.answer, "evidence": self.evidence}


@dataclass(frozen=True)
class ReachabilityReview:
    advisoryId: str
    package: str
    answers: Mapping[str, QuestionAnswer]
    outcome: str
    reviewer: str
    reviewedAt: str
    independentReviewReference: str | None = None
    notes: str = ""

    @property
    def unansweredQuestions(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.answers.items() if value.answer == "unknown"))

    @property
    def blocking(self) -> bool:
        return self.outcome not in NON_BLOCKING_DISPOSITIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "advisoryId": self.advisoryId,
            "package": self.package,
            "answers": {name: value.as_dict() for name, value in sorted(self.answers.items())},
            "unansweredQuestions": list(self.unansweredQuestions),
            "outcome": self.outcome,
            "reviewer": self.reviewer,
            "reviewedAt": self.reviewedAt,
            "independentReviewReference": self.independentReviewReference,
            "notes": self.notes,
            "blocking": self.blocking,
        }


def parse_review(
    record: Mapping[str, Any],
    *,
    completed_independent_reviews: Iterable[str] = (),
    criticalAdvisories: Iterable[str] = (),
) -> ReachabilityReview:
    """Validate one reachability review.

    ``criticalAdvisories`` names the advisories whose effective severity is
    Critical. A Critical advisory may only reach a non-blocking outcome through
    a completed independent security review, matching
    ``docs/STABLE_RELEASE_BLOCKERS.md``.
    """
    if not isinstance(record, Mapping):
        raise ReachabilityError("reachability review must be an object")
    for name in ("advisoryId", "package", "outcome", "reviewer", "reviewedAt"):
        if not record.get(name):
            raise ReachabilityError(f"reachability review missing {name}")

    advisory = str(record["advisoryId"])
    outcome = record["outcome"]
    if outcome not in DISPOSITIONS:
        raise ReachabilityError(f"{advisory}: outcome must be one of {', '.join(DISPOSITIONS)}")

    raw_answers = record.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise ReachabilityError(f"{advisory}: answers must be an object")
    unknown_keys = sorted(set(raw_answers) - set(REACHABILITY_QUESTIONS))
    if unknown_keys:
        raise ReachabilityError(f"{advisory}: unknown reachability questions: {', '.join(unknown_keys)}")
    missing_keys = sorted(set(REACHABILITY_QUESTIONS) - set(raw_answers))
    if missing_keys:
        raise ReachabilityError(
            f"{advisory}: reachability review must answer all ten questions; missing: {', '.join(missing_keys)}"
        )

    answers: dict[str, QuestionAnswer] = {}
    for name, value in raw_answers.items():
        if not isinstance(value, Mapping):
            raise ReachabilityError(f"{advisory}: answer for {name} must be an object")
        answer = value.get("answer")
        if answer not in ANSWERS:
            raise ReachabilityError(f"{advisory}: answer for {name} must be one of {', '.join(ANSWERS)}")
        evidence = value.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ReachabilityError(
                f"{advisory}: answer for {name} must cite evidence; an assertion is not a reachability result"
            )
        answers[name] = QuestionAnswer(answer=answer, evidence=evidence.strip())

    review = ReachabilityReview(
        advisoryId=advisory,
        package=str(record["package"]),
        answers=answers,
        outcome=outcome,
        reviewer=str(record["reviewer"]),
        reviewedAt=str(record["reviewedAt"]),
        independentReviewReference=record.get("independentReviewReference"),
        notes=str(record.get("notes", "")),
    )

    reviews = set(completed_independent_reviews)

    if outcome == "Not reachable with evidence":
        if review.unansweredQuestions:
            raise ReachabilityError(
                f"{advisory}: cannot conclude 'Not reachable with evidence' while these questions are "
                f"unanswered: {', '.join(review.unansweredQuestions)}"
            )
        exposed = [name for name in _EXPOSURE_INDICATORS if answers[name].answer == "yes"]
        if "binaryInstalled" in exposed and "vulnerableCodePathActive" in exposed and (
            answers["runsByDefault"].answer == "yes"
            or answers["listensOnSocket"].answer == "yes"
            or answers["unprivilegedInvocation"].answer == "yes"
            or answers["bunnyOrPluginInvocation"].answer == "yes"
        ):
            raise ReachabilityError(
                f"{advisory}: claims unreachability while the binary is installed, the vulnerable code "
                "path is active, and something can invoke it"
            )

    if outcome == "Unknown" and not review.blocking:  # defensive; Unknown is not in the non-blocking set
        raise ReachabilityError(f"{advisory}: 'Unknown' must remain blocking")

    if advisory in set(criticalAdvisories) and outcome in NON_BLOCKING_DISPOSITIONS:
        reference = review.independentReviewReference
        if not reference or reference not in reviews:
            raise ReachabilityError(
                f"{advisory}: a Critical advisory may only become non-blocking through an explicit, "
                "completed independent security review"
            )

    return review


def summarise(reviews: Iterable[ReachabilityReview]) -> dict[str, Any]:
    """Aggregate a set of reviews into a gate-usable verdict."""
    rows = list(reviews)
    by_outcome: dict[str, list[str]] = {name: [] for name in DISPOSITIONS}
    for review in rows:
        by_outcome[review.outcome].append(review.advisoryId)
    blocking = [review.advisoryId for review in rows if review.blocking]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reviewed": len(rows),
        "byOutcome": {name: sorted(values) for name, values in by_outcome.items() if values},
        "blockingAdvisories": sorted(blocking),
        "blocked": bool(blocking),
        "note": (
            "'Unknown' and 'Reachable but mitigated' both remain blocking. A mitigation is not a fix, "
            "and an unanswered question is not a negative answer."
        ),
    }


__all__ = [
    "ANSWERS",
    "REACHABILITY_QUESTIONS",
    "QuestionAnswer",
    "ReachabilityError",
    "ReachabilityReview",
    "parse_review",
    "summarise",
]

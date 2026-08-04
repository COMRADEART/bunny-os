# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ceilings, and the rule that only one thing may drive a task.

Every limit here exists because the unbounded version of it is a way for a task
to consume a machine that has very little to consume. A review loop with no
round ceiling is a conversation between an executor and a critic that neither
has a reason to end. A tool-call budget with no ceiling is a plan that can
decide to do a thousand things. On a 64 MB board these are not theoretical.

**Exactly one executor per task** is enforced by a lease rather than by
discipline. :class:`ExecutorLeases` hands out one lease per task id and refuses
the second, so two runtimes — or one runtime with a bug — cannot both drive the
same task. The lease is held in memory and therefore does not survive a restart,
which is correct: after a crash nothing is driving anything, and
:mod:`companion.recovery` decides what happens next.

**Reviewers do not talk to each other.** The round's
:class:`companion.reviewer.ReviewContext` is built once before any of them runs
and each reviewer receives its own **deep copy**, so a reviewer that scribbles on
what it was handed changes nothing anybody else will see. No reviewer sees
another's observations — not in its round and not in the next one. Observations go to the executor, which may answer them with
a new plan revision. A reviewer that could read another reviewer's remarks would
turn review into a debate whose length nobody bounded, and the debate would be
happening about a user's data.

**A reviewer that does not answer is left behind.** Review is advice. The
timeout is short, the task continues without the missing observation, and the
absence is recorded so that "no issues were raised" is never confused with "the
reviewer never replied".
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import threading
from typing import Any, Mapping, Sequence

from .errors import CoordinationLimitExceeded, MalformedOutput
from .privacy import DATA_CLASSES, rank
from .reviewer import ReviewContext, ReviewObservation, Reviewer, observation_from_json

__all__ = [
    "CoordinationPolicy",
    "ExecutorLease",
    "ExecutorLeases",
    "ReviewRound",
    "reviewer_context",
    "run_review_round",
]


@dataclass(frozen=True)
class CoordinationPolicy:
    """Every ceiling a task runs under, in one place.

    The defaults are small. A companion that needs more than two review rounds,
    thirty-two tool calls or five hundred events to answer a question is not
    being thorough; it is looping, and the honest response to a loop is to stop
    and say so rather than to raise the limit.
    """

    maximum_review_rounds: int = 2
    reviewer_timeout_seconds: float = 5.0
    maximum_reviewers: int = 4
    maximum_events_per_task: int = 500
    maximum_tool_calls: int = 32
    #: Whole currency minor units. Zero means nothing may be spent, and is the
    #: default, for the same reason as :class:`companion.session.CostPolicy`.
    cost_ceiling_units: int = 0
    execution_deadline_seconds: float = 300.0
    #: The most sensitive class a reviewer may be shown verbatim. Cannot exceed
    #: the audience ceiling in :mod:`companion.privacy`; this can only tighten.
    reviewer_context_ceiling: str = "internal"

    def __post_init__(self) -> None:
        if self.reviewer_context_ceiling not in DATA_CLASSES:
            raise MalformedOutput(f"reviewerContextCeiling must be one of {list(DATA_CLASSES)}")
        if rank(self.reviewer_context_ceiling) > rank("internal"):
            raise MalformedOutput(
                "reviewerContextCeiling cannot exceed 'internal'; the audience ceiling in "
                "companion.privacy is a maximum and a policy may only lower it"
            )
        for name in ("maximum_review_rounds", "maximum_reviewers", "maximum_events_per_task", "maximum_tool_calls"):
            if getattr(self, name) < 0:
                raise MalformedOutput(f"{name} cannot be negative")
        if self.reviewer_timeout_seconds <= 0 or self.execution_deadline_seconds <= 0:
            raise MalformedOutput("timeouts and deadlines must be positive")

    # -- the checks --------------------------------------------------------

    def check_review_rounds(self, rounds: int) -> None:
        if rounds >= self.maximum_review_rounds:
            raise CoordinationLimitExceeded(
                f"the review-round ceiling of {self.maximum_review_rounds} has been reached; "
                "the executor's current plan stands and the disagreements remain in the record",
                limit="reviewRounds", measured=rounds, allowed=self.maximum_review_rounds,
            )

    def check_events(self, count: int) -> None:
        if count >= self.maximum_events_per_task:
            raise CoordinationLimitExceeded(
                f"this task has produced {count} events against a ceiling of {self.maximum_events_per_task}",
                limit="events", measured=count, allowed=self.maximum_events_per_task,
            )

    def check_tool_calls(self, count: int) -> None:
        if count >= self.maximum_tool_calls:
            raise CoordinationLimitExceeded(
                f"this task has made {count} tool calls against a ceiling of {self.maximum_tool_calls}",
                limit="toolCalls", measured=count, allowed=self.maximum_tool_calls,
            )

    def check_cost(self, spent: int, proposed: int, *, task_limit: int) -> None:
        ceiling = min(self.cost_ceiling_units, task_limit) if task_limit else self.cost_ceiling_units
        if spent + proposed > ceiling:
            raise CoordinationLimitExceeded(
                f"this would spend {spent + proposed} units against a ceiling of {ceiling}",
                limit="cost", measured=spent + proposed, allowed=ceiling,
            )

    def check_deadline(self, consumed: float, *, task_deadline: float) -> None:
        ceiling = min(self.execution_deadline_seconds, task_deadline) if task_deadline > 0 else self.execution_deadline_seconds
        if consumed > ceiling:
            raise CoordinationLimitExceeded(
                f"this task has run for {consumed:.1f}s against a deadline of {ceiling:.1f}s",
                limit="deadline", measured=consumed, allowed=ceiling,
            )

    def check_reviewers(self, count: int) -> None:
        if count > self.maximum_reviewers:
            raise CoordinationLimitExceeded(
                f"{count} reviewers were selected against a ceiling of {self.maximum_reviewers}",
                limit="reviewers", measured=count, allowed=self.maximum_reviewers,
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "maximumReviewRounds": self.maximum_review_rounds,
            "reviewerTimeoutSeconds": self.reviewer_timeout_seconds,
            "maximumReviewers": self.maximum_reviewers,
            "maximumEventsPerTask": self.maximum_events_per_task,
            "maximumToolCalls": self.maximum_tool_calls,
            "costCeilingUnits": self.cost_ceiling_units,
            "executionDeadlineSeconds": self.execution_deadline_seconds,
            "reviewerContextCeiling": self.reviewer_context_ceiling,
        }


@dataclass(frozen=True)
class ExecutorLease:
    """Proof that one executor holds one task."""

    task_id: str
    executor_id: str
    acquired_at_monotonic: float


@dataclass
class ExecutorLeases:
    """One executor per task, or a refusal.

    In memory by design. A lease that persisted would survive the process that
    held it and would then have to be broken by something — and whatever broke
    it would be deciding, from outside, that a task nobody is driving may be
    driven. Recovery makes that decision, with the event record in front of it.
    """

    leases: dict[str, ExecutorLease] = field(default_factory=dict)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def acquire(self, task_id: str, executor_id: str, *, now: float) -> ExecutorLease:
        with self._guard:
            existing = self.leases.get(task_id)
            if existing is not None:
                raise CoordinationLimitExceeded(
                    f"task {task_id} is already held by {existing.executor_id!r}; "
                    "exactly one executor drives a task",
                    limit="executorLease", measured=executor_id, allowed=existing.executor_id,
                )
            lease = ExecutorLease(task_id=task_id, executor_id=executor_id, acquired_at_monotonic=now)
            self.leases[task_id] = lease
            return lease

    def release(self, task_id: str) -> None:
        with self._guard:
            self.leases.pop(task_id, None)

    def holder(self, task_id: str) -> str:
        lease = self.leases.get(task_id)
        return lease.executor_id if lease is not None else ""


@dataclass(frozen=True)
class ReviewRound:
    """What one round of review produced, including what it failed to produce."""

    round_number: int
    observations: tuple[ReviewObservation, ...] = ()
    #: Reviewers that did not answer inside the timeout, or answered with
    #: something that was not an observation. Recorded so that silence is never
    #: read as assent.
    absent: tuple[tuple[str, str], ...] = ()

    @property
    def disagreements(self) -> tuple[ReviewObservation, ...]:
        return tuple(item for item in self.observations if item.material)

    def to_json(self) -> dict[str, Any]:
        return {
            "roundNumber": self.round_number,
            "observations": [item.to_json() for item in self.observations],
            "absent": [{"reviewerId": name, "detail": detail} for name, detail in self.absent],
        }


def _invoke(reviewer: Reviewer, context: ReviewContext, timeout: float) -> tuple[list[Any], str]:
    """Call one reviewer with a bound on how long it may take.

    The worker is a daemon thread, so a reviewer that never returns cannot keep
    the process alive at shutdown. It does keep running, and this module cannot
    stop it — Python has no safe way to interrupt an arbitrary call. That is a
    real limitation and is recorded as one; what the runtime guarantees is that
    the *task* is not held up, not that a defective reviewer stops consuming
    CPU. A reviewer is in-process code that somebody installed.
    """
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = list(reviewer.observe(context))
        except BaseException as exc:  # third-party code; its faults are data
            box["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=worker, name=f"review-{reviewer.reviewer_id}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return [], f"did not answer within {timeout:g}s"
    if "error" in box:
        return [], str(box["error"])
    return list(box.get("value", [])), ""


def run_review_round(
    reviewers: Sequence[Reviewer],
    context: ReviewContext,
    policy: CoordinationPolicy,
    *,
    round_number: int,
) -> ReviewRound:
    """Run every reviewer against the same, already-built context.

    The context is constructed once by the caller and each reviewer receives its
    own deep copy. That is what keeps reviewers from influencing each other: a
    reviewer can scribble on what it was handed and nobody else will ever see
    it. Passing one shared instance — which an earlier version did, on the
    strength of the dataclass being ``frozen`` — left a mutable channel between
    reviewers running in sequence.
    """
    policy.check_reviewers(len(reviewers))
    observations: list[ReviewObservation] = []
    absent: list[tuple[str, str]] = []
    seen: set[str] = set()

    for reviewer in reviewers:
        # A fresh deep copy per reviewer. `@dataclass(frozen=True)` freezes the
        # attribute *bindings*, not the dicts they point at — a security review
        # showed one reviewer mutating `context.plan["operations"]` and thereby
        # flipping the next reviewer's verdict from a blocking disagreement to
        # "no issues". Reviewers run in sequence over one value, so sharing it
        # was a channel between them, which is precisely what this module says
        # does not exist.
        private = deepcopy(context)
        identity = getattr(reviewer, "reviewer_id", "")
        if not identity:
            absent.append(("<unnamed>", "the reviewer did not declare an identity"))
            continue
        if identity in seen:
            absent.append((identity, "the same reviewer was selected twice and ran once"))
            continue
        seen.add(identity)

        returned, failure = _invoke(reviewer, private, policy.reviewer_timeout_seconds)
        if failure:
            absent.append((identity, failure))
            continue
        for item in returned:
            try:
                observations.append(observation_from_json(item, reviewer_id=identity))
            except MalformedOutput as exc:
                absent.append((identity, str(exc)))
                break
    # Zero reviewers is a legitimate configuration — §10 says "zero or more" —
    # and produces an empty round rather than an error. A task with no critic is
    # a choice; a task whose critic silently vanished is the thing `absent`
    # exists to distinguish it from.
    return ReviewRound(round_number=round_number, observations=tuple(observations), absent=tuple(absent))


def reviewer_context(
    *,
    task_view: Mapping[str, Any],
    plan_view: Mapping[str, Any],
    event_views: Sequence[Mapping[str, Any]],
    classification: str,
    policy: CoordinationPolicy,
    round_number: int,
) -> ReviewContext:
    """Assemble the frozen view a round of reviewers will share."""
    withheld = rank(classification) > rank(policy.reviewer_context_ceiling)
    return ReviewContext(
        task=dict(task_view),
        plan=dict(plan_view),
        events=tuple(dict(item) for item in event_views),
        round_number=round_number,
        classification=classification,
        context_withheld=withheld,
    )

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-executor coordination and bounded, observation-only review."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .events import TaskEvent
from .model import AgentIdentity, ReviewerObservation, TaskSession, bounded_text, redact_text, safe_identifier


class CoordinationError(RuntimeError):
    pass


class CoordinationLimitExceeded(CoordinationError):
    pass


@dataclass(frozen=True)
class CoordinationLimits:
    maximum_review_rounds: int = 2
    maximum_provider_tokens: int = 16_000
    maximum_tool_calls: int = 32
    maximum_cost_minor_units: int = 0
    maximum_execution_seconds: float = 300.0
    maximum_shared_context_bytes: int = 32 * 1024

    def __post_init__(self) -> None:
        if min(
            self.maximum_review_rounds,
            self.maximum_provider_tokens,
            self.maximum_tool_calls,
            self.maximum_cost_minor_units,
        ) < 0:
            raise ValueError("coordination limits cannot be negative")
        if self.maximum_execution_seconds <= 0 or self.maximum_shared_context_bytes <= 0:
            raise ValueError("time and context limits must be positive")


@dataclass(frozen=True)
class ExecutionProposal:
    plan_id: str
    transition_id: str
    operation_id: str
    tool_id: str
    action_summary: str
    approval_required: bool
    approval_action: str = "local_task_record"
    data_affected: str = "sanitized task summary"
    destination: str = "local"
    provider_id: str | None = None
    estimated_cost_units: int | None = None
    resource_impact: Mapping[str, Any] = field(default_factory=dict)
    alternatives: tuple[str, ...] = ("Cancel the task without recording a result.",)

    def __post_init__(self) -> None:
        for value, name in (
            (self.plan_id, "proposal plan id"),
            (self.transition_id, "proposal transition id"),
            (self.operation_id, "proposal operation id"),
            (self.tool_id, "proposal tool id"),
            (self.approval_action, "proposal approval action"),
        ):
            safe_identifier(value, name)
        bounded_text(self.action_summary, "proposal action summary", 512)

    def to_json(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "operationId": self.operation_id,
            "toolId": self.tool_id,
            "actionSummary": self.action_summary,
            "approvalRequired": self.approval_required,
            "approvalAction": self.approval_action,
            "dataAffected": self.data_affected,
            "destination": self.destination,
            "providerId": self.provider_id,
            "estimatedCostUnits": self.estimated_cost_units,
            "resourceImpact": dict(self.resource_impact),
            "alternatives": list(self.alternatives),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ExecutionProposal":
        return cls(
            plan_id=str(value.get("planId", "")),
            transition_id=str(value.get("transitionId", "")),
            operation_id=str(value.get("operationId", "")),
            tool_id=str(value.get("toolId", "")),
            action_summary=str(value.get("actionSummary", "")),
            approval_required=bool(value.get("approvalRequired", False)),
            approval_action=str(value.get("approvalAction", "local_task_record")),
            data_affected=str(value.get("dataAffected", "sanitized task summary")),
            destination=str(value.get("destination", "local")),
            provider_id=str(value["providerId"]) if value.get("providerId") else None,
            estimated_cost_units=int(value["estimatedCostUnits"])
            if value.get("estimatedCostUnits") is not None else None,
            resource_impact=dict(value.get("resourceImpact") or {}),
            alternatives=tuple(str(item) for item in value.get("alternatives", ())),
        )


@dataclass(frozen=True)
class ExecutionResult:
    operation_id: str
    success: bool
    display_summary: str
    output_reference: str
    usage_tokens: int = 0
    cost_minor_units: int = 0

    def __post_init__(self) -> None:
        safe_identifier(self.operation_id, "execution result operation id")
        bounded_text(self.display_summary, "execution result summary", 2000)
        safe_identifier(self.output_reference, "execution result reference")
        if self.usage_tokens < 0 or self.cost_minor_units < 0:
            raise ValueError("execution usage cannot be negative")


@dataclass(frozen=True)
class ReadOnlyReviewContext:
    task_id: str
    display_summary: str
    task_classification: str
    required_capabilities: tuple[str, ...]
    privacy_classification: str
    event_records: tuple[Mapping[str, Any], ...]

    def encoded_size(self) -> int:
        return len(json.dumps(self.to_json(), sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "displaySummary": self.display_summary,
            "taskClassification": self.task_classification,
            "requiredCapabilities": list(self.required_capabilities),
            "privacyClassification": self.privacy_classification,
            "events": [dict(item) for item in self.event_records],
        }


class ExecutorAdapter(ABC):
    @property
    @abstractmethod
    def identity(self) -> AgentIdentity:
        raise NotImplementedError

    @abstractmethod
    def plan(self, task: TaskSession) -> ExecutionProposal:
        raise NotImplementedError

    @abstractmethod
    def execute(self, task: TaskSession, proposal: ExecutionProposal) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, task_id: str) -> bool:
        raise NotImplementedError


class ReviewerAdapter(ABC):
    """Reviewers receive immutable projections and have no tool method."""

    @property
    @abstractmethod
    def identity(self) -> AgentIdentity:
        raise NotImplementedError

    @abstractmethod
    def observe(self, context: ReadOnlyReviewContext) -> ReviewerObservation:
        raise NotImplementedError


@dataclass(frozen=True)
class ArbitrationResult:
    observations: tuple[ReviewerObservation, ...]
    disagreements: tuple[dict[str, Any], ...]
    executor_may_revise: bool
    user_escalation_required: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "observations": [item.to_json() for item in self.observations],
            "disagreements": list(self.disagreements),
            "executorMayRevise": self.executor_may_revise,
            "userEscalationRequired": self.user_escalation_required,
            "consensusGuaranteesCorrectness": False,
        }


def detect_disagreements(observations: Sequence[ReviewerObservation]) -> tuple[dict[str, Any], ...]:
    """Compare observations once; never start reviewer-to-reviewer dialogue."""
    disagreements: list[dict[str, Any]] = []
    by_subject: dict[tuple[str, tuple[str, ...]], list[ReviewerObservation]] = {}
    for observation in observations:
        key = (observation.category, tuple(sorted(observation.evidence_references)))
        by_subject.setdefault(key, []).append(observation)
    for (category, evidence), group in sorted(by_subject.items()):
        actions = {" ".join(item.suggested_action.casefold().split()) for item in group}
        if len(group) > 1 and len(actions) > 1:
            disagreements.append({
                "category": category,
                "reviewers": [item.reviewer for item in group],
                "suggestedActions": [item.suggested_action for item in group],
                "evidenceReferences": list(evidence),
            })
    return tuple(disagreements)


class AgentCoordinator:
    def __init__(self, limits: CoordinationLimits | None = None) -> None:
        self.limits = limits or CoordinationLimits()
        self._executors: dict[str, ExecutorAdapter] = {}
        self._reviewers: dict[str, list[ReviewerAdapter]] = {}
        self._review_rounds: dict[str, int] = {}
        self._tool_calls: dict[str, int] = {}
        self._tokens: dict[str, int] = {}
        self._cost: dict[str, int] = {}
        self._started: dict[str, float] = {}

    def assign_executor(self, task_id: str, executor: ExecutorAdapter) -> None:
        safe_identifier(task_id, "coordinator task id")
        if task_id in self._executors:
            raise CoordinationError("a task already has its one active executor")
        self._executors[task_id] = executor
        self._started[task_id] = time.monotonic()

    def executor(self, task_id: str) -> ExecutorAdapter:
        try:
            return self._executors[task_id]
        except KeyError as exc:
            raise CoordinationError("the task has no executor") from exc

    def add_reviewer(self, task_id: str, reviewer: ReviewerAdapter) -> None:
        if reviewer.identity.agent_id == self.executor(task_id).identity.agent_id:
            raise CoordinationError("the active executor cannot also be its reviewer")
        reviewers = self._reviewers.setdefault(task_id, [])
        if any(item.identity.agent_id == reviewer.identity.agent_id for item in reviewers):
            raise CoordinationError("the reviewer is already attached")
        reviewers.append(reviewer)

    def _check_elapsed(self, task_id: str) -> None:
        started = self._started.get(task_id, time.monotonic())
        if time.monotonic() - started > self.limits.maximum_execution_seconds:
            raise CoordinationLimitExceeded("task execution time limit was reached")

    def plan(self, task: TaskSession) -> ExecutionProposal:
        self._check_elapsed(task.task_id)
        return self.executor(task.task_id).plan(task)

    def execute(self, task: TaskSession, proposal: ExecutionProposal) -> ExecutionResult:
        self._check_elapsed(task.task_id)
        estimated_cost = proposal.estimated_cost_units or 0
        if proposal.destination == "remote" and (
            task.offline_required or "local-only" in task.data_locality_requirements
        ):
            raise CoordinationError("task privacy/locality policy forbids remote execution")
        if estimated_cost > 0 and not task.cost_policy.paid_providers_allowed:
            raise CoordinationLimitExceeded("paid provider use was not permitted")
        allowed_cost = min(task.cost_policy.ceiling_minor_units, self.limits.maximum_cost_minor_units)
        if estimated_cost > allowed_cost:
            raise CoordinationLimitExceeded("provider cost ceiling would be exceeded")
        calls = self._tool_calls.get(task.task_id, 0) + 1
        if calls > self.limits.maximum_tool_calls:
            raise CoordinationLimitExceeded("tool-call limit was reached")
        self._tool_calls[task.task_id] = calls
        result = self.executor(task.task_id).execute(task, proposal)
        tokens = self._tokens.get(task.task_id, 0) + result.usage_tokens
        cost = self._cost.get(task.task_id, 0) + result.cost_minor_units
        if tokens > self.limits.maximum_provider_tokens:
            raise CoordinationLimitExceeded("provider token limit was reached")
        if cost > allowed_cost:
            raise CoordinationLimitExceeded("provider cost ceiling was reached")
        self._tokens[task.task_id] = tokens
        self._cost[task.task_id] = cost
        return result

    def review(self, task: TaskSession, events: Sequence[TaskEvent]) -> ArbitrationResult:
        rounds = self._review_rounds.get(task.task_id, 0) + 1
        if rounds > self.limits.maximum_review_rounds:
            raise CoordinationLimitExceeded("review-round limit was reached")
        self._review_rounds[task.task_id] = rounds
        records = tuple(event.to_json() for event in events)
        context = ReadOnlyReviewContext(
            task_id=task.task_id,
            display_summary=task.display_summary,
            task_classification=task.task_classification,
            required_capabilities=task.required_capabilities,
            privacy_classification=task.privacy_classification.value,
            event_records=records,
        )
        if context.encoded_size() > self.limits.maximum_shared_context_bytes:
            raise CoordinationLimitExceeded("review context-sharing limit was reached")
        collected: list[ReviewerObservation] = []
        for reviewer in self._reviewers.get(task.task_id, ()):
            try:
                observation = reviewer.observe(context)
                if not isinstance(observation, ReviewerObservation):
                    raise ValueError("reviewer returned a malformed observation")
                collected.append(observation)
            except TimeoutError:
                collected.append(ReviewerObservation(
                    reviewer=reviewer.identity.agent_id,
                    severity="warning",
                    category="performance",
                    summary="The reviewer timed out; no reviewer verdict was inferred.",
                    suggested_action="Continue only under the executor's existing policy and limits.",
                ))
            except (TypeError, ValueError) as exc:
                collected.append(ReviewerObservation(
                    reviewer=reviewer.identity.agent_id,
                    severity="warning",
                    category="quality",
                    summary="The reviewer returned a malformed observation and it was ignored.",
                    suggested_action="Inspect or replace the reviewer adapter before relying on it.",
                ))
        observations = tuple(collected)
        disagreements = detect_disagreements(observations)
        return ArbitrationResult(
            observations=observations,
            disagreements=disagreements,
            executor_may_revise=bool(disagreements),
            user_escalation_required=any(
                item.severity == "critical" for item in observations
            ) or bool(disagreements),
        )

    def cancel(self, task_id: str) -> bool:
        return self.executor(task_id).cancel(task_id)


class HarmlessLocalExecutor(ExecutorAdapter):
    """Provider-free vertical-slice executor with one fixed, non-command tool.

    It records a digest and sanitized summary in the companion's own task
    history.  It cannot run a command, browse, control the desktop, or write to
    an arbitrary path.
    """

    _identity = AgentIdentity(agent_id="bunny/local-test-executor")

    @property
    def identity(self) -> AgentIdentity:
        return self._identity

    def plan(self, task: TaskSession) -> ExecutionProposal:
        suffix = task.task_id.rsplit("-", 1)[-1][:12]
        return ExecutionProposal(
            plan_id=f"plan-local-{suffix}",
            transition_id=f"transition-local-{suffix}",
            operation_id=f"operation-local-{suffix}",
            tool_id="bunny.task-history",
            action_summary="Record a harmless local result in the private companion task history.",
            approval_required=True,
            resource_impact={"memoryBytes": 65536, "network": "none", "systemModification": False},
        )

    def execute(self, task: TaskSession, proposal: ExecutionProposal) -> ExecutionResult:
        if proposal.tool_id != "bunny.task-history" or proposal.destination != "local":
            raise CoordinationError("the local test executor only supports its fixed local task-history tool")
        digest = hashlib.sha256(
            f"{task.request_sha256}:{proposal.operation_id}".encode("ascii")
        ).hexdigest()
        return ExecutionResult(
            operation_id=proposal.operation_id,
            success=True,
            display_summary="The harmless local task completed and its sanitized result was recorded.",
            output_reference=f"sha256:{digest}",
        )

    def cancel(self, task_id: str) -> bool:
        safe_identifier(task_id, "cancelled task id")
        return True


class LocalSafetyReviewer(ReviewerAdapter):
    _identity = AgentIdentity(agent_id="bunny/local-test-reviewer")

    @property
    def identity(self) -> AgentIdentity:
        return self._identity

    def observe(self, context: ReadOnlyReviewContext) -> ReviewerObservation:
        evidence = tuple(
            str(record["eventId"])
            for record in context.event_records
            if record.get("eventType") == "tool_requested"
        )
        return ReviewerObservation(
            reviewer=self.identity.agent_id,
            severity="info",
            category="security",
            summary="The proposed demonstration operation is local and confined to the companion task store.",
            suggested_action="Keep the scoped approval and proceed only after the user approves it.",
            evidence_references=evidence,
        )
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

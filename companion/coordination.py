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

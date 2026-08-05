# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The task: one thing the companion was asked to do, and everything about it.

Like the session, a task document is a projection of its events and can be
rebuilt from them. Unlike the session, several of its fields exist purely so
that a *crashed* runtime can reach a safe decision without replaying, and those
are worth naming because they look redundant until the machine loses power:

``operations``
    One reference per tool operation, keyed by the derived idempotency key from
    :func:`companion.ids.operation_key`. An operation that was started and never
    settled becomes ``unknown`` — not ``failed``, and certainly not "retry me".
``approvals``
    One reference per approval, carrying the plan and the destination it was
    granted against. An approval is consent to a specific act; the reference is
    what lets a restarted runtime notice the act has since changed.
``deadline_consumed_seconds``
    How much of the execution budget has already been spent. Monotonic time does
    not survive a reboot, so a deadline stored as an instant would be
    meaningless afterwards; stored as a *budget with a consumed amount* it
    survives, and the arithmetic is the same.

Two things are never here, and there is no field to put them in: credentials of
any kind, and an executor's hidden reasoning. The former is removed by
:func:`companion.privacy.sanitize` before anything is written; the latter has no
place to go, because the executor contract in :mod:`companion.executor` returns
plans and outputs and has no channel for a private train of thought.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from . import TASK_SCHEMA_VERSION
from .clock import iso8601
from .errors import SchemaError
from .ids import valid_id
from .privacy import DATA_CLASSES, MAX_REQUEST_LENGTH, display_summary, scrub_text
from .session import LOCALITY_PREFERENCES
from .states import INITIAL_STATE, STATES, TERMINAL_STATES

__all__ = [
    "ApprovalReference",
    "CANCELLATION_STATES",
    "CANCELLATION_CAUSES",
    "CompanionTask",
    "ErrorReference",
    "OPERATION_STATES",
    "OperationReference",
    "OutputReference",
    "TASK_TYPES",
]

#: What kind of work this is. Coarse on purpose: the type selects which
#: executors are eligible, and a taxonomy fine enough to be interesting would be
#: fine enough to be wrong.
TASK_TYPES = (
    "unclassified",
    "question",
    "summarise",
    "transform",
    "retrieve",
    "compute",
    "local_action",
)

#: How far cancellation has got. Separate from the task state so that a task
#: which failed *while* being cancelled still records that it was asked to stop.
CANCELLATION_STATES = ("none", "requested", "in_progress", "complete")

#: Why cancellation happened. Every one of these is a real path in §14, and
#: keeping them distinct is what lets a user tell "I stopped this" from "the
#: machine stopped this because the battery died".
CANCELLATION_CAUSES = (
    "",
    "user",
    "policy",
    "timeout",
    "capability_loss",
    "provider_loss",
    "supervisor_shutdown",
)

#: What is known about one operation. ``unknown`` is the important one: it means
#: the operation was started and the process died before anything settled it, so
#: whether the work happened is genuinely not known and must not be guessed.
OPERATION_STATES = ("started", "completed", "failed", "unknown")


@dataclass(frozen=True)
class OperationReference:
    """One tool operation, by its idempotency key."""

    key: str
    name: str
    status: str = "started"
    started_sequence: int = 0
    settled_sequence: int = 0
    #: Set when recovery decided about this operation, so a later reader can see
    #: that ``unknown`` was reached deliberately rather than left unfinished.
    recovery_note: str = ""

    def __post_init__(self) -> None:
        if self.status not in OPERATION_STATES:
            raise SchemaError(f"operation status must be one of {list(OPERATION_STATES)}")
        if not self.key:
            raise SchemaError("an operation reference needs its idempotency key")

    @property
    def settled(self) -> bool:
        return self.status in ("completed", "failed")

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status,
            "startedSequence": self.started_sequence,
            "settledSequence": self.settled_sequence,
            "recoveryNote": self.recovery_note,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "OperationReference":
        return cls(
            key=str(document.get("key", "")),
            name=str(document.get("name", "")),
            status=str(document.get("status", "started")),
            started_sequence=int(document.get("startedSequence", 0) or 0),
            settled_sequence=int(document.get("settledSequence", 0) or 0),
            recovery_note=str(document.get("recoveryNote", "")),
        )


@dataclass(frozen=True)
class ApprovalReference:
    """One approval, and the circumstances it was granted against.

    ``destination_fingerprint`` is a digest of where the approved act would send
    data. §12 requires an approval whose destination changed to be refused, and
    comparing a digest is the only way to notice that without storing the
    destination twice and hoping the copies agree.
    """

    request_id: str
    action: str
    decision: str = "pending"
    plan_id: str = ""
    plan_revision: int = 0
    transition_id: str = ""
    destination_fingerprint: str = ""
    resolved_sequence: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "action": self.action,
            "decision": self.decision,
            "planId": self.plan_id,
            "planRevision": self.plan_revision,
            "transitionId": self.transition_id,
            "destinationFingerprint": self.destination_fingerprint,
            "resolvedSequence": self.resolved_sequence,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "ApprovalReference":
        return cls(
            request_id=str(document.get("requestId", "")),
            action=str(document.get("action", "")),
            decision=str(document.get("decision", "pending")),
            plan_id=str(document.get("planId", "")),
            plan_revision=int(document.get("planRevision", 0) or 0),
            transition_id=str(document.get("transitionId", "")),
            destination_fingerprint=str(document.get("destinationFingerprint", "")),
            resolved_sequence=int(document.get("resolvedSequence", 0) or 0),
        )


@dataclass(frozen=True)
class OutputReference:
    """A produced output, by digest rather than by value.

    The task document carries the shape of an output — what kind, how big, what
    it hashes to — and never the output itself. A task document that grew with
    its outputs would eventually be too large to read on the machines this is
    for, and a document that must be read to recover is a document that must
    stay small.
    """

    output_id: str
    kind: str = "text"
    digest: str = ""
    byte_size: int = 0
    classification: str = "internal"
    summary: str = ""
    created_sequence: int = 0

    def __post_init__(self) -> None:
        if self.classification not in DATA_CLASSES:
            raise SchemaError(f"unknown output classification: {self.classification!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "outputId": self.output_id,
            "kind": self.kind,
            "digest": self.digest,
            "byteSize": self.byte_size,
            "classification": self.classification,
            "summary": self.summary,
            "createdSequence": self.created_sequence,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "OutputReference":
        return cls(
            output_id=str(document.get("outputId", "")),
            kind=str(document.get("kind", "text")),
            digest=str(document.get("digest", "")),
            byte_size=int(document.get("byteSize", 0) or 0),
            classification=str(document.get("classification", "internal")),
            summary=str(document.get("summary", "")),
            created_sequence=int(document.get("createdSequence", 0) or 0),
        )


@dataclass(frozen=True)
class ErrorReference:
    """One failure, coded so it can be handled and summarised so it can be read."""

    code: str
    summary: str = ""
    producer: str = "runtime"
    sequence: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "summary": self.summary,
            "producer": self.producer,
            "sequence": self.sequence,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "ErrorReference":
        return cls(
            code=str(document.get("code", "")),
            summary=str(document.get("summary", "")),
            producer=str(document.get("producer", "runtime")),
            sequence=int(document.get("sequence", 0) or 0),
        )


@dataclass(frozen=True)
class CompanionTask:
    """One request, from submission to history."""

    task_id: str
    session_id: str
    #: The user's words, sanitized of anything that may never be stored. Kept
    #: because a task whose original request was thrown away cannot be re-run,
    #: reviewed or explained, and a companion that cannot say what it was asked
    #: to do is not auditable.
    original_request: str
    display_summary: str
    created_at: str
    task_type: str = "unclassified"
    required_capabilities: tuple[str, ...] = ()
    classification: str = "personal"
    data_locality: str = "device-only"
    requires_offline: bool = False
    cost_limit_units: int = 0
    execution_deadline_seconds: float = 0.0
    deadline_consumed_seconds: float = 0.0
    executor_id: str = ""
    reviewer_ids: tuple[str, ...] = ()
    state: str = INITIAL_STATE
    #: The phase a pause interrupted, so resume returns to it rather than
    #: guessing. Empty whenever the task is not paused.
    paused_from: str = ""
    progress: float = 0.0
    plan_revision: int = 0
    approvals: tuple[ApprovalReference, ...] = ()
    operations: tuple[OperationReference, ...] = ()
    outputs: tuple[OutputReference, ...] = ()
    errors: tuple[ErrorReference, ...] = ()
    cancellation_state: str = "none"
    cancellation_cause: str = ""
    completed_at: str = ""
    capability_plan_reference: str = ""
    review_rounds: int = 0
    tool_call_count: int = 0
    spent_cost_units: int = 0
    schema_version: int = TASK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not valid_id(self.task_id):
            raise SchemaError(f"taskId is not a usable identifier: {self.task_id!r}")
        if not valid_id(self.session_id):
            raise SchemaError(f"sessionId is not a usable identifier: {self.session_id!r}")
        if self.task_type not in TASK_TYPES:
            raise SchemaError(f"taskType must be one of {list(TASK_TYPES)}")
        if self.classification not in DATA_CLASSES:
            raise SchemaError(f"unknown data classification: {self.classification!r}")
        if self.data_locality not in LOCALITY_PREFERENCES:
            raise SchemaError(f"dataLocality must be one of {list(LOCALITY_PREFERENCES)}")
        if self.state not in STATES:
            raise SchemaError(f"unknown task state: {self.state!r}")
        if self.cancellation_state not in CANCELLATION_STATES:
            raise SchemaError(f"cancellationState must be one of {list(CANCELLATION_STATES)}")
        if self.cancellation_cause not in CANCELLATION_CAUSES:
            raise SchemaError(f"cancellationCause must be one of {list(CANCELLATION_CAUSES)}")
        if not 0.0 <= self.progress <= 1.0:
            raise SchemaError("progress is a fraction between 0 and 1")
        if self.cost_limit_units < 0 or self.spent_cost_units < 0:
            raise SchemaError("cost figures cannot be negative")
        if self.execution_deadline_seconds < 0 or self.deadline_consumed_seconds < 0:
            raise SchemaError("deadline figures cannot be negative")
        if len(self.original_request) > MAX_REQUEST_LENGTH:
            raise SchemaError(
                f"the request is {len(self.original_request)} characters against a limit of "
                f"{MAX_REQUEST_LENGTH}; it was refused rather than silently shortened"
            )
        if self.requires_offline and self.data_locality != "device-only":
            raise SchemaError(
                "a task that requires offline operation must also be device-only; "
                "declaring otherwise asks for a contradiction to be resolved silently"
            )

    # -- derived -----------------------------------------------------------

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def deadline_remaining_seconds(self) -> float:
        """What is left of the execution budget. Zero means no budget remains.

        A task with no configured deadline returns infinity rather than zero:
        "unlimited" and "exhausted" are opposites and must not share a value.
        """
        if self.execution_deadline_seconds <= 0:
            return float("inf")
        return max(0.0, self.execution_deadline_seconds - self.deadline_consumed_seconds)

    def operation(self, key: str) -> OperationReference | None:
        for item in self.operations:
            if item.key == key:
                return item
        return None

    def approval(self, request_id: str) -> ApprovalReference | None:
        for item in self.approvals:
            if item.request_id == request_id:
                return item
        return None

    def completed_operation_keys(self) -> frozenset[str]:
        """Keys the record proves completed. Recovery hands these to the
        executor so a replan can skip work that demonstrably already happened —
        and only that work."""
        return frozenset(item.key for item in self.operations if item.status == "completed")

    def unknown_operation_keys(self) -> frozenset[str]:
        """Keys whose outcome the record cannot establish.

        The runtime refuses to perform these. Not because they failed — nobody
        knows whether they failed — but because performing one again is exactly
        the repetition §15 forbids.
        """
        return frozenset(item.key for item in self.operations if item.status == "unknown")

    def unsettled_operations(self) -> tuple[OperationReference, ...]:
        return tuple(item for item in self.operations if not item.settled)

    # -- transformation ----------------------------------------------------

    def with_state(self, state: str, *, paused_from: str = "") -> "CompanionTask":
        return replace(self, state=state, paused_from=paused_from)

    def with_operation(self, reference: OperationReference) -> "CompanionTask":
        existing = {item.key: item for item in self.operations}
        existing[reference.key] = reference
        ordered = tuple(sorted(existing.values(), key=lambda item: (item.started_sequence, item.key)))
        return replace(self, operations=ordered)

    def with_approval(self, reference: ApprovalReference) -> "CompanionTask":
        existing = {item.request_id: item for item in self.approvals}
        existing[reference.request_id] = reference
        ordered = tuple(sorted(existing.values(), key=lambda item: item.request_id))
        return replace(self, approvals=ordered)

    def with_output(self, reference: OutputReference) -> "CompanionTask":
        return replace(self, outputs=(*self.outputs, reference))

    def with_error(self, reference: ErrorReference) -> "CompanionTask":
        return replace(self, errors=(*self.errors, reference))

    def with_progress(self, progress: float) -> "CompanionTask":
        # Progress never goes backwards. A bar that retreats tells a user the
        # machine has lost track, which — if the executor is merely reporting
        # badly — is not true, and the record should not say it.
        return replace(self, progress=max(self.progress, min(1.0, max(0.0, float(progress)))))

    def finished(self, now: float) -> "CompanionTask":
        return replace(self, completed_at=iso8601(now), progress=1.0 if self.state == "completed" else self.progress)

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        session_id: str,
        request: str,
        now: float,
        classification: str = "personal",
        data_locality: str = "device-only",
        requires_offline: bool = False,
        cost_limit_units: int = 0,
        execution_deadline_seconds: float = 0.0,
    ) -> "CompanionTask":
        return cls(
            task_id=task_id,
            session_id=session_id,
            # Scrubbed before it is ever stored. The user's words are kept in
            # full; anything credential-shaped inside them is not, because the
            # task document is written to disk and read by every later phase.
            original_request=scrub_text(request),
            display_summary=display_summary(request),
            created_at=iso8601(now),
            classification=classification,
            data_locality=data_locality,
            requires_offline=requires_offline,
            cost_limit_units=cost_limit_units,
            execution_deadline_seconds=execution_deadline_seconds,
        )

    # -- serialization -----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "originalRequest": self.original_request,
            "displaySummary": self.display_summary,
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
            "taskType": self.task_type,
            "requiredCapabilities": list(self.required_capabilities),
            "classification": self.classification,
            "dataLocality": self.data_locality,
            "requiresOffline": self.requires_offline,
            "costLimitUnits": self.cost_limit_units,
            "spentCostUnits": self.spent_cost_units,
            "executionDeadlineSeconds": self.execution_deadline_seconds,
            "deadlineConsumedSeconds": self.deadline_consumed_seconds,
            "executorId": self.executor_id,
            "reviewerIds": list(self.reviewer_ids),
            "state": self.state,
            "pausedFrom": self.paused_from,
            "progress": self.progress,
            "planRevision": self.plan_revision,
            "reviewRounds": self.review_rounds,
            "toolCallCount": self.tool_call_count,
            "approvals": [item.to_json() for item in self.approvals],
            "operations": [item.to_json() for item in self.operations],
            "outputs": [item.to_json() for item in self.outputs],
            "errors": [item.to_json() for item in self.errors],
            "cancellationState": self.cancellation_state,
            "cancellationCause": self.cancellation_cause,
            "capabilityPlanReference": self.capability_plan_reference,
        }

    #: Fields of a task document that can carry the user's own material. Named
    #: explicitly rather than masked wholesale, because most of the document —
    #: the state, the counters, the operation ledger, the plan revision — is
    #: what a reviewer or an auditor is *for*, and blanking it would leave them
    #: nothing to work with.
    USER_CONTENT_FIELDS = ("originalRequest", "displaySummary")

    def view(self, audience: str) -> dict[str, Any]:
        """The task as one audience may read it.

        A security review found this masking only the request and the summary
        while ``outputs[].summary`` and ``errors[].summary`` — both of which are
        derived from task content — went out at every audience, including
        ``remote``. Each of those now travels at its *own* classification, so an
        output explicitly marked ``secret`` is withheld even from an audience
        cleared for the task as a whole.
        """
        from .privacy import visible_to, withheld_marker

        value = self.to_json()
        if not visible_to(audience, self.classification):
            marker = withheld_marker(self.classification)
            for field_name in self.USER_CONTENT_FIELDS:
                value[field_name] = marker
            # Errors quote what failed, and what failed is usually the content.
            for error in value["errors"]:
                error["summary"] = marker
        for stored, rendered in zip(self.outputs, value["outputs"]):
            if not visible_to(audience, stored.classification):
                rendered["summary"] = withheld_marker(stored.classification)
        return value

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "CompanionTask":
        if not isinstance(document, Mapping):
            raise SchemaError("a task document must be an object")
        version = document.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool):
            raise SchemaError("a task document must carry an integer schemaVersion")
        if version > TASK_SCHEMA_VERSION:
            raise SchemaError(f"task schemaVersion {version} is newer than this build understands")
        try:
            return cls(
                task_id=str(document.get("taskId", "")),
                session_id=str(document.get("sessionId", "")),
                original_request=str(document.get("originalRequest", "")),
                display_summary=str(document.get("displaySummary", "")),
                created_at=str(document.get("createdAt", "")),
                completed_at=str(document.get("completedAt", "")),
                task_type=str(document.get("taskType", "unclassified")),
                required_capabilities=tuple(str(item) for item in document.get("requiredCapabilities", ())),
                classification=str(document.get("classification", "personal")),
                data_locality=str(document.get("dataLocality", "device-only")),
                requires_offline=bool(document.get("requiresOffline", False)),
                cost_limit_units=int(document.get("costLimitUnits", 0) or 0),
                spent_cost_units=int(document.get("spentCostUnits", 0) or 0),
                execution_deadline_seconds=float(document.get("executionDeadlineSeconds", 0.0) or 0.0),
                deadline_consumed_seconds=float(document.get("deadlineConsumedSeconds", 0.0) or 0.0),
                executor_id=str(document.get("executorId", "")),
                reviewer_ids=tuple(str(item) for item in document.get("reviewerIds", ())),
                state=str(document.get("state", INITIAL_STATE)),
                paused_from=str(document.get("pausedFrom", "")),
                progress=float(document.get("progress", 0.0) or 0.0),
                plan_revision=int(document.get("planRevision", 0) or 0),
                review_rounds=int(document.get("reviewRounds", 0) or 0),
                tool_call_count=int(document.get("toolCallCount", 0) or 0),
                approvals=tuple(ApprovalReference.from_json(item) for item in document.get("approvals", ())),
                operations=tuple(OperationReference.from_json(item) for item in document.get("operations", ())),
                outputs=tuple(OutputReference.from_json(item) for item in document.get("outputs", ())),
                errors=tuple(ErrorReference.from_json(item) for item in document.get("errors", ())),
                cancellation_state=str(document.get("cancellationState", "none")),
                cancellation_cause=str(document.get("cancellationCause", "")),
                capability_plan_reference=str(document.get("capabilityPlanReference", "")),
                schema_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"a task document could not be parsed: {exc}") from exc

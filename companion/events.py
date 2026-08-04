# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed, bounded, replayable task events.

An event says whether its payload is an observed fact or a generated
description.  Generated text must cite the event ids it summarizes.  Neither
form may contain hidden reasoning or unredacted credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from typing import Any, Mapping
from uuid import UUID, uuid4

from . import EVENT_SCHEMA_VERSION
from .model import bounded_text, redact_text, safe_identifier, utc_now, validate_timestamp

EVENT_TYPES = (
    "task_created",
    "task_classified",
    "executor_selected",
    "reviewer_added",
    "planning_started",
    "tool_requested",
    "approval_requested",
    "approval_resolved",
    "tool_started",
    "tool_progress",
    "tool_completed",
    "tool_failed",
    "reviewer_observation",
    "reviewer_disagreement",
    "response_drafting",
    "speech_started",
    "speech_completed",
    "task_completed",
    "task_cancelled",
    "task_failed",
    "capability_degraded",
    "connection_lost",
    "connection_restored",
)

RECORD_KINDS = ("observed_fact", "generated_description")
MAX_EVENT_BYTES = 32 * 1024
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_ITEMS = 256
MAX_REPLAY_EVENTS = 1000

_SENSITIVE_KEY = re.compile(
    r"(?i)(api.?key|authorization|credential|password|private.?key|refresh.?token|secret|token)"
)


class EventValidationError(ValueError):
    pass


def _redact(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_PAYLOAD_DEPTH:
        return "[TRUNCATED:DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value, 4096)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= MAX_PAYLOAD_ITEMS:
                result["_truncated"] = True
                break
            key = str(raw_key)[:128]
            result[key] = "[REDACTED]" if _SENSITIVE_KEY.search(key) else _redact(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        items = list(value)
        redacted = [_redact(item, depth=depth + 1) for item in items[:MAX_PAYLOAD_ITEMS]]
        if len(items) > MAX_PAYLOAD_ITEMS:
            redacted.append("[TRUNCATED:ITEMS]")
        return redacted
    return redact_text(str(value), 1024)


def redacted_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EventValidationError("event payload must be an object")
    result = _redact(value)
    assert isinstance(result, dict)
    return result


def canonical_event_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    session_id: str
    task_id: str
    sequence: int
    event_type: str
    occurred_at: str
    source: str
    record_kind: str
    payload: Mapping[str, Any]
    description: str = ""
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            UUID(self.event_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise EventValidationError("event id must be a UUID") from exc
        safe_identifier(self.session_id, "event session id")
        safe_identifier(self.task_id, "event task id")
        if self.sequence < 0:
            raise EventValidationError("event sequence cannot be negative")
        if self.event_type not in EVENT_TYPES:
            raise EventValidationError(f"unsupported task event: {self.event_type!r}")
        validate_timestamp(self.occurred_at, "event timestamp")
        safe_identifier(self.source, "event source")
        if self.record_kind not in RECORD_KINDS:
            raise EventValidationError("event record kind is invalid")
        object.__setattr__(self, "payload", redacted_payload(self.payload))
        bounded_text(self.description, "event description", 1000, allow_empty=True)
        if self.record_kind == "generated_description" and not self.description:
            raise EventValidationError("generated descriptions must contain display text")
        if self.record_kind == "generated_description" and not self.evidence_references:
            raise EventValidationError("generated descriptions must cite observed event ids")
        for reference in self.evidence_references:
            try:
                UUID(reference)
            except (ValueError, TypeError, AttributeError) as exc:
                raise EventValidationError("event evidence reference must be a UUID") from exc
        if len(canonical_event_bytes(self.to_json())) > MAX_EVENT_BYTES:
            raise EventValidationError(f"event exceeds {MAX_EVENT_BYTES} bytes")

    def with_sequence(self, sequence: int) -> "TaskEvent":
        return replace(self, sequence=sequence)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": EVENT_SCHEMA_VERSION,
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "sequence": self.sequence,
            "eventType": self.event_type,
            "occurredAt": self.occurred_at,
            "source": self.source,
            "recordKind": self.record_kind,
            "payload": dict(self.payload),
            "description": redact_text(self.description, 1000),
            "evidenceReferences": list(self.evidence_references),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TaskEvent":
        if value.get("schemaVersion") != EVENT_SCHEMA_VERSION:
            raise EventValidationError("unsupported event schemaVersion")
        return cls(
            event_id=str(value.get("eventId", "")),
            session_id=str(value.get("sessionId", "")),
            task_id=str(value.get("taskId", "")),
            sequence=int(value.get("sequence", 0)),
            event_type=str(value.get("eventType", "")),
            occurred_at=str(value.get("occurredAt", "")),
            source=str(value.get("source", "")),
            record_kind=str(value.get("recordKind", "")),
            payload=value.get("payload") if isinstance(value.get("payload"), Mapping) else {},
            description=str(value.get("description", "")),
            evidence_references=tuple(str(item) for item in value.get("evidenceReferences", ())),
        )


def observed_event(
    *,
    session_id: str,
    task_id: str,
    event_type: str,
    source: str,
    payload: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    sequence: int = 0,
    occurred_at: str | None = None,
) -> TaskEvent:
    return TaskEvent(
        event_id=event_id or str(uuid4()),
        session_id=session_id,
        task_id=task_id,
        sequence=sequence,
        event_type=event_type,
        occurred_at=occurred_at or utc_now(),
        source=source,
        record_kind="observed_fact",
        payload=payload or {},
    )


def generated_event(
    *,
    session_id: str,
    task_id: str,
    event_type: str,
    source: str,
    description: str,
    evidence_references: tuple[str, ...],
    payload: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    sequence: int = 0,
) -> TaskEvent:
    return TaskEvent(
        event_id=event_id or str(uuid4()),
        session_id=session_id,
        task_id=task_id,
        sequence=sequence,
        event_type=event_type,
        occurred_at=utc_now(),
        source=source,
        record_kind="generated_description",
        payload=payload or {},
        description=description,
        evidence_references=evidence_references,
    )

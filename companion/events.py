# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The task event stream: what happened, in order, provably unedited.

Everything else in this package is a projection of this. A session document and
a task document can both be rebuilt by replaying events; if one of them ever
disagrees with the stream, the stream is right. That is not a stylistic
preference — it is what makes recovery possible, because after a crash the only
thing on disk that is known to be true is what was appended before the power
went.

Each event carries the hash of the one before it. The chain is what turns four
separate requirements into one mechanism:

* **ordering** — a reordered stream fails to verify, because the hashes name a
  specific predecessor rather than merely "the previous line";
* **corruption detection** — a rewritten payload changes its own hash and every
  hash after it;
* **incomplete final writes** — a truncated last line has no valid hash, so the
  reader can drop exactly one event and keep the rest, rather than either
  trusting a half-written record or discarding a whole history;
* **deduplication** — a replayed event carries a hash that does not follow the
  current tip, so it is refused rather than appended twice.

The chain is not a defence against an attacker who can rewrite the whole file:
it is unkeyed, so anyone able to edit the store can recompute it. It defends
against the things that actually happen to a file on a constrained device —
partial writes, bit rot, a crashed process, a well-meaning tool that reordered
JSON. Detecting a hostile rewrite is the signing layer's job and is out of scope
for this phase; see the report's known limitations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from capability.apply.identity import canonical_json

from . import EVENT_SCHEMA_VERSION
from .errors import IntegrityError, SchemaError, UnknownEventType
from .ids import valid_id
from .model import bounded_text, redact_text
from .privacy import DATA_CLASSES, Sanitized, project, rank, sanitize

__all__ = [
    "EVENT_TYPES",
    "GENESIS_HASH",
    "PRODUCER_KINDS",
    "RECORD_KINDS",
    "SESSION_EVENT_TYPES",
    "DescribedEvent",
    "EventValidationError",
    "TaskEvent",
    "HASHED_FIELDS_BY_VERSION",
    "USER_CONTENT_EVENTS",
    "build_event",
    "classification_for",
    "deduplicate",
    "generated_event",
    "observed_event",
    "verify_chain",
]

#: Every event type this build understands. An event naming anything else is
#: refused on read rather than skipped: a stream containing a record whose
#: meaning is unknown cannot be replayed, and replaying it minus the unknown
#: record would produce a state the machine never actually held.
EVENT_TYPES = (
    "session_created",
    "task_created",
    "task_classified",
    "capability_checked",
    "executor_selected",
    "reviewer_selected",
    "approval_requested",
    "approval_resolved",
    "planning_started",
    "execution_started",
    "operation_started",
    "operation_progress",
    "operation_completed",
    "operation_failed",
    "reviewer_observation",
    "reviewer_disagreement",
    "result_created",
    "task_paused",
    "task_resumed",
    "task_cancelled",
    "task_failed",
    "task_completed",
    "recovery_started",
    "recovery_completed",
    # Not in the brief's list. Emitted by lifecycle moves that carry no meaning
    # beyond the move itself; see companion.states.GENERIC_TRANSITION_EVENT.
    "task_state_changed",
    # Presentation-surface types, admitted additively when the companion state
    # projection (companion.state) was integrated with this stream. They name
    # things the operation_* vocabulary deliberately does not: drafting and
    # speaking are presentation facts, not operations, and losing the network
    # is an observation about the world rather than a step in a plan. Additive
    # only: no stream written before these existed can contain them, so no
    # stored record changes meaning.
    "response_drafting",
    "speech_started",
    "speech_completed",
    "connection_lost",
    "connection_restored",
    "capability_degraded",
)

#: Events that belong to a session rather than to a task. They carry an empty
#: ``taskId`` and are the only events permitted to.
SESSION_EVENT_TYPES = frozenset({"session_created"})

#: Who may produce an event. The producer is part of the hashed material, so an
#: event cannot be re-attributed after the fact without breaking the chain —
#: which matters most for ``reviewer``: a reviewer observation that could be
#: relabelled as a runtime decision would erase the boundary this package
#: exists to enforce.
PRODUCER_KINDS = ("runtime", "executor", "reviewer", "user", "policy", "recovery", "supervisor")

_PRODUCER = re.compile(r"^(" + "|".join(PRODUCER_KINDS) + r")(:[A-Za-z0-9][A-Za-z0-9._-]{0,63})?\Z")

#: The predecessor hash of the first event in a stream.
GENESIS_HASH = "0" * 64

#: Which fields each event schema version covered with its hash.
#:
#: This table is the reason an old store stays readable. A record must be
#: authenticated against the rule it was *written* under, not the current one —
#: and the mistake that made this table necessary in the reader (rather than
#: only in the migrator) was adding a field to version 1's rule instead of
#: creating version 2. Every event the previous build had written then failed
#: its own hash, `validate()` reported legitimate data as tampering, and
#: `migrate()` refused to help because the version number had not moved. There
#: was no recovery path.
#:
#: So: **adding a field to the hashed material is a new version, always.**
HASHED_FIELDS_BY_VERSION: Mapping[int, tuple[str, ...]] = {
    # Version 0: before the redaction record and the audit reference existed.
    0: (
        "schemaVersion", "eventId", "sessionId", "taskId", "sequence", "eventType",
        "timestamp", "producer", "payload", "classification", "previousHash",
    ),
    # Version 1: adds what was redacted, and the audit reference.
    1: (
        "schemaVersion", "eventId", "sessionId", "taskId", "sequence", "eventType",
        "timestamp", "producer", "payload", "classification", "auditReference",
        "redactions", "previousHash",
    ),
    # Version 2: adds the per-field classification list.
    2: (
        "schemaVersion", "eventId", "sessionId", "taskId", "sequence", "eventType",
        "timestamp", "producer", "payload", "classification", "auditReference",
        "redactions", "internalFields", "previousHash",
    ),
}

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

#: Payload fields each event type must carry. Absence is a schema error rather
#: than a default, because every one of these is a field some later reader will
#: branch on, and a defaulted branch is a decision nobody made.
_REQUIRED_PAYLOAD: Mapping[str, frozenset[str]] = {
    "session_created": frozenset({"title", "privacyPolicy", "localityPreference"}),
    "task_created": frozenset({"summary"}),
    "task_classified": frozenset({"taskType", "classification", "requiredCapabilities"}),
    "capability_checked": frozenset({"planId", "eligible", "reasons"}),
    "executor_selected": frozenset({"executorId", "local"}),
    "reviewer_selected": frozenset({"reviewerIds"}),
    "approval_requested": frozenset({"requestId", "action", "destination", "planId"}),
    "approval_resolved": frozenset({"requestId", "decision"}),
    "planning_started": frozenset({"planRevision"}),
    "execution_started": frozenset({"planRevision"}),
    "operation_started": frozenset({"operationKey", "name"}),
    "operation_progress": frozenset({"operationKey", "progress"}),
    "operation_completed": frozenset({"operationKey"}),
    "operation_failed": frozenset({"operationKey", "error"}),
    "reviewer_observation": frozenset({"reviewerId", "severity", "category", "summary"}),
    "reviewer_disagreement": frozenset({"reviewerId", "summary"}),
    "result_created": frozenset({"resultId"}),
    "task_paused": frozenset({"pausedFrom"}),
    "task_resumed": frozenset({"resumedTo"}),
    "task_cancelled": frozenset({"reason"}),
    "task_failed": frozenset({"error"}),
    "task_completed": frozenset({"resultId"}),
    "recovery_started": frozenset({"detectedState"}),
    "recovery_completed": frozenset({"decision"}),
    "task_state_changed": frozenset({"from", "to"}),
    # The presentation types carry their meaning in the description or in
    # self-evident payload; only losing the connection is required to say why.
    "response_drafting": frozenset(),
    "speech_started": frozenset(),
    "speech_completed": frozenset(),
    "connection_lost": frozenset({"reason"}),
    "connection_restored": frozenset(),
    "capability_degraded": frozenset({"reason"}),
}


#: Event types whose payload can contain the user's own material, and which are
#: therefore classified at the *task's* level rather than at the runtime's.
#:
#: The distinction matters more than it looks. Classifying every event at the
#: task's level is the obvious implementation and it is wrong in a way that
#: quietly breaks review: a reviewer looking at a ``personal`` task would find
#: the executor's name, the memory figures and the plan's step count all
#: withheld, and would have nothing left to review. These are the events that
#: actually carry the user's words, values or outputs; the rest carry facts
#: about the machine and the decision, which are ``internal`` and which a
#: reviewer, an audit log and a support transcript may all see.
USER_CONTENT_EVENTS = frozenset({
    "session_created",   # the title, which the user wrote
    "task_created",        # the display summary of what was asked
    "planning_started",    # the plan, whose operation arguments hold the request
    "operation_started",   # the arguments an operation was given
    "operation_completed", # the value an operation produced
    "result_created",      # the outputs
    # A tool's exception message routinely quotes the value that offended it,
    # and a task's failure summary can quote its request. A security review
    # found a `secret` task's contents leaving in an `operation_failed` payload
    # that had been pinned at `internal` — so failure text is treated as user
    # material, which is what it is.
    "operation_failed",
    "task_failed",
})


def classification_for(event_type: str, task_classification: str) -> str:
    """The classification one event should carry.

    Never above the task's own class: an event about a ``public`` task is not
    made ``personal`` by being a ``result_created``. This function raises the
    floor for events that carry user material and leaves everything else at
    ``internal``, which is the level at which the record stays useful.
    """
    if event_type in USER_CONTENT_EVENTS:
        return task_classification
    return "internal" if rank(task_classification) > rank("internal") else task_classification


@dataclass(frozen=True)
class TaskEvent:
    """One immutable record in a session's stream."""

    event_id: str
    session_id: str
    task_id: str
    sequence: int
    event_type: str
    timestamp: str
    producer: str
    payload: Mapping[str, Any]
    classification: str
    audit_reference: str
    previous_hash: str
    event_hash: str
    #: Field paths removed by :func:`companion.privacy.sanitize` before the
    #: event was built. Part of the hashed material: the record of what was
    #: taken out is as unforgeable as the record of what was kept.
    redactions: tuple[str, ...] = ()
    #: Top-level payload keys that are *runtime fact* rather than the user's
    #: material, and are therefore rendered at ``internal`` however the event as
    #: a whole is classified. Empty means "none of them" — every key carries the
    #: event's class, which is the safe default.
    #:
    #: Named this way round deliberately. The first attempt named the
    #: *sensitive* fields and treated everything unnamed as ``internal``, which
    #: is fail-open: a payload key added later would render at ``internal``
    #: silently and nothing would fail. Naming what is safe to reveal means
    #: forgetting over-classifies, which matches ``ToolDeclaration`` and
    #: ``ExecutorDeclaration`` — undeclared fails closed.
    #:
    #: The motivating case is ``session_created``, which carries a title the
    #: user wrote alongside the privacy, cost and locality policies that were in
    #: force. Classifying the whole event at the title's level withheld the
    #: policy from the audit audience — the audience whose job is to check a
    #: claim like "nothing was permitted to leave this device". Hashed like
    #: everything else, so the list cannot be widened after the fact.
    internal_fields: tuple[str, ...] = ()
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_fields(
            event_id=self.event_id,
            session_id=self.session_id,
            task_id=self.task_id,
            sequence=self.sequence,
            event_type=self.event_type,
            timestamp=self.timestamp,
            producer=self.producer,
            payload=self.payload,
            classification=self.classification,
            previous_hash=self.previous_hash,
            schema_version=self.schema_version,
        )
        if self.event_hash != self.computed_hash():
            raise IntegrityError(
                f"event {self.event_id!r} does not match its own hash; the record was altered"
            )

    def hashed_material(self) -> dict[str, Any]:
        """Exactly what the hash covers. Every field that means anything.

        ``eventHash`` is of course excluded. Nothing else is: a field outside
        the hash is a field somebody can change without the chain noticing, and
        there is no field here worth leaving changeable.
        """
        return _material(
            schema_version=self.schema_version,
            event_id=self.event_id,
            session_id=self.session_id,
            task_id=self.task_id,
            sequence=self.sequence,
            event_type=self.event_type,
            timestamp=self.timestamp,
            producer=self.producer,
            payload=self.payload,
            classification=self.classification,
            audit_reference=self.audit_reference,
            redactions=self.redactions,
            internal_fields=self.internal_fields,
            previous_hash=self.previous_hash,
        )

    def computed_hash(self) -> str:
        return _seal(self.hashed_material(), self.schema_version)

    @property
    def producer_kind(self) -> str:
        return self.producer.split(":", 1)[0]

    def to_json(self) -> dict[str, Any]:
        value = self.hashed_material()
        value["eventHash"] = self.event_hash
        return value

    def view(self, audience: str) -> dict[str, Any]:
        """The event as one audience is permitted to read it.

        Structure survives, content above the audience's ceiling does not. The
        classification stays visible so a reader always knows it is looking at a
        redacted view rather than at an empty one.
        """
        value = self.to_json()
        payload = dict(self.payload)
        if not self.internal_fields:
            value["payload"] = project(payload, audience=audience, classification=self.classification)
            return value
        # A mixed payload: only the named keys carry this event's class, and the
        # rest are runtime fact at `internal`. Doing it per field rather than
        # per event is what lets an auditor read the policy that was in force
        # without also reading the title the user typed.
        rendered = {
            key: project(
                {key: item},
                audience=audience,
                classification="internal" if key in self.internal_fields else self.classification,
            )[key]
            for key, item in payload.items()
        }
        value["payload"] = rendered
        return value

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "TaskEvent":
        """Parse a stored event, verifying its schema and its own hash."""
        if not isinstance(document, Mapping):
            raise SchemaError("an event record must be an object")
        version = document.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool):
            raise SchemaError("an event record must carry an integer schemaVersion")
        if version > EVENT_SCHEMA_VERSION:
            raise SchemaError(
                f"event schemaVersion {version} is newer than this build understands "
                f"({EVENT_SCHEMA_VERSION}); refusing rather than guessing"
            )
        payload = document.get("payload")
        if not isinstance(payload, Mapping):
            raise SchemaError("an event payload must be an object")
        redactions = document.get("redactions", [])
        if not isinstance(redactions, (list, tuple)) or any(not isinstance(item, str) for item in redactions):
            raise SchemaError("redactions must be an array of strings")
        internal = document.get("internalFields", [])
        if not isinstance(internal, (list, tuple)) or any(not isinstance(item, str) for item in internal):
            raise SchemaError("internalFields must be an array of strings")
        try:
            return cls(
                event_id=str(document.get("eventId", "")),
                session_id=str(document.get("sessionId", "")),
                task_id=str(document.get("taskId", "")),
                sequence=_require_int(document.get("sequence"), "sequence"),
                event_type=str(document.get("eventType", "")),
                timestamp=str(document.get("timestamp", "")),
                producer=str(document.get("producer", "")),
                payload=dict(payload),
                classification=str(document.get("classification", "")),
                audit_reference=str(document.get("auditReference", "")),
                previous_hash=str(document.get("previousHash", "")),
                event_hash=str(document.get("eventHash", "")),
                redactions=tuple(str(item) for item in redactions),
                internal_fields=tuple(str(item) for item in internal),
                schema_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"an event record could not be parsed: {exc}") from exc


def _material(
    *,
    schema_version: int,
    event_id: str,
    session_id: str,
    task_id: str,
    sequence: int,
    event_type: str,
    timestamp: str,
    producer: str,
    payload: Mapping[str, Any],
    classification: str,
    audit_reference: str,
    redactions: Sequence[str],
    internal_fields: Sequence[str],
    previous_hash: str,
) -> dict[str, Any]:
    """The canonical field set. One definition, so the writer and the verifier
    cannot drift apart — which they would the moment the hash was computed from
    a dict assembled separately at each site."""
    return {
        "schemaVersion": schema_version,
        "eventId": event_id,
        "sessionId": session_id,
        "taskId": task_id,
        "sequence": sequence,
        "eventType": event_type,
        "timestamp": timestamp,
        "producer": producer,
        "payload": dict(payload),
        "classification": classification,
        "auditReference": audit_reference,
        "redactions": list(redactions),
        "internalFields": list(internal_fields),
        "previousHash": previous_hash,
    }


def _seal(material: Mapping[str, Any], version: int) -> str:
    """Hash a record against the field set of the version it declares.

    Restricting the material by version is what lets a store written by an
    older build still verify. A version this build has no rule for cannot be
    authenticated at all, and saying so is better than hashing it under a rule
    it was not written with and calling the mismatch tampering.
    """
    covered = HASHED_FIELDS_BY_VERSION.get(version)
    if covered is None:
        raise SchemaError(
            f"event schema version {version} has no hashing rule in this build, so the "
            "record's authenticity cannot be established"
        )
    return hashlib.sha256(
        canonical_json({key: material[key] for key in covered if key in material}).encode("ascii")
    ).hexdigest()


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{name} must be an integer")
    return value


def _validate_fields(
    *,
    event_id: str,
    session_id: str,
    task_id: str,
    sequence: int,
    event_type: str,
    timestamp: str,
    producer: str,
    payload: Mapping[str, Any],
    classification: str,
    previous_hash: str,
    schema_version: int,
) -> None:
    if event_type not in EVENT_TYPES:
        raise UnknownEventType(f"unknown event type: {event_type!r}")
    if not valid_id(event_id):
        raise SchemaError(f"eventId is not a usable identifier: {event_id!r}")
    if not valid_id(session_id):
        raise SchemaError(f"sessionId is not a usable identifier: {session_id!r}")
    if event_type in SESSION_EVENT_TYPES:
        if task_id:
            raise SchemaError(f"{event_type!r} belongs to a session and must not name a task")
    elif not valid_id(task_id):
        raise SchemaError(f"taskId is not a usable identifier: {task_id!r}")
    if sequence < 1:
        raise SchemaError("sequence numbers begin at 1")
    if not _TIMESTAMP.match(timestamp):
        raise SchemaError(f"timestamp must be ISO-8601 UTC to the second: {timestamp!r}")
    if not _PRODUCER.match(producer):
        raise SchemaError(f"producer must be one of {PRODUCER_KINDS} optionally followed by ':id': {producer!r}")
    if classification not in DATA_CLASSES:
        raise SchemaError(f"unknown data classification: {classification!r}")
    if len(previous_hash) != 64 or not re.fullmatch(r"[0-9a-f]{64}", previous_hash):
        raise SchemaError("previousHash must be 64 lowercase hex characters")
    if schema_version < 1:
        raise SchemaError("schemaVersion must be positive")
    missing = _REQUIRED_PAYLOAD.get(event_type, frozenset()) - set(payload)
    if missing:
        raise SchemaError(
            f"{event_type!r} requires payload fields: {', '.join(sorted(missing))}"
        )


def build_event(
    *,
    event_id: str,
    session_id: str,
    task_id: str,
    sequence: int,
    event_type: str,
    timestamp: str,
    producer: str,
    payload: Mapping[str, Any],
    classification: str,
    previous_hash: str,
    audit_reference: str = "",
    internal_fields: Sequence[str] = (),
) -> TaskEvent:
    """Sanitize a payload and seal it into an event.

    The only supported way to make one. Sanitization happens *here* rather than
    at the call sites so that there is no path by which an event reaches the
    store with a credential in it — a call site that forgot to sanitize would
    otherwise be a single missing line between a token and a permanent record.
    """
    cleaned: Sanitized = sanitize(dict(payload))
    redactions = tuple(sorted(set(cleaned.removed) | set(cleaned.scrubbed)))
    material = _material(
        schema_version=EVENT_SCHEMA_VERSION,
        event_id=event_id,
        session_id=session_id,
        task_id=task_id,
        sequence=sequence,
        event_type=event_type,
        timestamp=timestamp,
        producer=producer,
        payload=cleaned.value,
        classification=classification,
        audit_reference=audit_reference,
        redactions=redactions,
        internal_fields=tuple(internal_fields),
        previous_hash=previous_hash,
    )
    return TaskEvent(
        event_id=event_id,
        session_id=session_id,
        task_id=task_id,
        sequence=sequence,
        event_type=event_type,
        timestamp=timestamp,
        producer=producer,
        payload=cleaned.value,
        classification=classification,
        audit_reference=audit_reference,
        previous_hash=previous_hash,
        event_hash=_seal(material, EVENT_SCHEMA_VERSION),
        redactions=redactions,
        internal_fields=tuple(internal_fields),
    )


def verify_chain(events: Sequence[TaskEvent]) -> None:
    """Check a whole stream. Raises :class:`IntegrityError` on the first fault.

    Three separate faults, reported separately, because they mean different
    things to recovery: a broken link means the file was edited, a sequence gap
    means an event was lost, and a duplicate id means a writer ran twice.
    """
    previous = GENESIS_HASH
    expected = 1
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            raise IntegrityError(f"event {event.event_id!r} appears more than once")
        seen.add(event.event_id)
        if event.sequence != expected:
            raise IntegrityError(
                f"expected sequence {expected} and found {event.sequence}; the stream has a gap or a reorder"
            )
        if event.previous_hash != previous:
            raise IntegrityError(
                f"event {event.sequence} does not follow event {event.sequence - 1}; the chain is broken"
            )
        if event.event_hash != event.computed_hash():
            raise IntegrityError(f"event {event.sequence} does not match its own hash")
        previous = event.event_hash
        expected += 1


def deduplicate(events: Sequence[TaskEvent]) -> tuple[TaskEvent, ...]:
    """Drop exact repeats of an event already seen, keeping the first.

    Only an *exact* repeat — same id and same hash — is a duplicate. Two events
    sharing an id but not a hash are a conflict, not a duplication, and are
    raised rather than silently resolved in favour of whichever came first.
    """
    kept: list[TaskEvent] = []
    by_id: dict[str, str] = {}
    for event in events:
        existing = by_id.get(event.event_id)
        if existing is None:
            by_id[event.event_id] = event.event_hash
            kept.append(event)
            continue
        if existing != event.event_hash:
            raise IntegrityError(
                f"two different events share the id {event.event_id!r}"
            )
    return tuple(kept)


# -- Presentation-layer events ---------------------------------------------
#
# The companion state projection (``companion.state``) needs two things this
# core format deliberately does not carry: *what produced the words the user
# sees* (an observed fact versus a generated description that must cite its
# evidence) and the display text itself. The earlier prototype carried them as
# top-level fields of a simpler, unchained event record. This build keeps the
# chained format and carries the presentation fields on a subclass instead:
# they are validated here, bounded here, and serialized by :meth:`to_json`,
# but they sit **outside** the sealed field set — ``_seal`` hashes exactly the
# version-2 fields and nothing else, so these ride along unprotected exactly
# as protected as they were in the prototype that never hashed anything.
# Promoting them into the hash is a schema-version bump, deliberately not
# taken here; see ``HASHED_FIELDS_BY_VERSION``.

#: The two kinds of record a presentation event can be. An observed fact says
#: something happened; a generated description says something about what
#: happened and must cite the events it summarises.
RECORD_KINDS = ("observed_fact", "generated_description")

#: Bounds carried over from the prototype contract. A single event may not be
#: arbitrarily large, and a payload may not nest without limit — a deeply
#: nested payload is a denial-of-service against every later reader.
MAX_EVENT_BYTES = 32 * 1024
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_ITEMS = 256

_SENSITIVE_KEY = re.compile(
    r"(?i)(api.?key|authorization|credential|password|private.?key|refresh.?token|secret|token)"
)


class EventValidationError(SchemaError):
    """A proposed event failed its own validation.

    A subclass of :class:`~companion.errors.SchemaError` so existing handlers
    that catch schema faults keep catching these; the distinct name lets the
    presentation layer report "your text was refused" differently from "the
    record was malformed".
    """


def canonical_event_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _redact(value: Any, *, depth: int = 0) -> Any:
    """Mark credential-shaped keys and scrub credential shapes in free text."""
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
    """The payload as it may be built into an event: bounded, marked, scrubbed.

    Runs *before* :func:`build_event`'s own sanitization. The two layers do
    different jobs: this one marks a secret-shaped key's value so the record
    shows that the key existed and was withheld; ``sanitize`` removes what may
    never be stored and records the removal in the event's ``redactions``.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EventValidationError("event payload must be an object")
    result = _redact(value)
    assert isinstance(result, dict)
    return result


def _utc_now_seconds() -> str:
    """The stream's timestamp format: ISO-8601 UTC to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _producer_from(source: str) -> str:
    """Map a free-form source label onto the stream's producer grammar.

    A source already in ``PRODUCER_KINDS[:id]`` form passes through untouched.
    Anything else becomes a named runtime producer — ``companion.runtime``
    arrives as ``runtime:companion.runtime`` — so attribution survives without
    widening who may claim to be an executor or a reviewer.
    """
    if _PRODUCER.match(source):
        return source
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", str(source))[:63]
    slug = re.sub(r"^[^A-Za-z0-9]+", "", slug).rstrip("-") or "runtime"
    return f"runtime:{slug}"


@dataclass(frozen=True)
class DescribedEvent(TaskEvent):
    """A task event carrying the presentation fields the state projection reads.

    ``recordKind``, ``description`` and ``evidenceReferences`` are outside the
    sealed field set (see the block comment above); everything else — ids,
    ordering, payload, classification, chain position — is the ordinary hashed
    record, and the hash is unchanged from the same event built without them.
    """

    record_kind: str = "observed_fact"
    description: str = ""
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.record_kind not in RECORD_KINDS:
            raise EventValidationError("event record kind is invalid")
        bounded_text(self.description, "event description", 1000, allow_empty=True)
        if self.record_kind == "generated_description":
            if not self.description:
                raise EventValidationError("generated descriptions must contain display text")
            if not self.evidence_references:
                raise EventValidationError("generated descriptions must cite observed event ids")
        elif self.evidence_references:
            raise EventValidationError("only generated descriptions cite evidence")
        for reference in self.evidence_references:
            try:
                UUID(reference)
            except (ValueError, TypeError, AttributeError) as exc:
                raise EventValidationError("event evidence reference must be a UUID") from exc
        if len(canonical_event_bytes(self.to_json())) > MAX_EVENT_BYTES:
            raise EventValidationError(f"event exceeds {MAX_EVENT_BYTES} bytes")

    def with_sequence(self, sequence: int) -> "DescribedEvent":
        """Re-key this event to another stream position, resealing the hash.

        Sequence is hashed material, so unlike a plain renumber this recomputes
        the seal — an event whose sequence could be edited without breaking its
        own hash would make replay detection worthless.
        """
        material = self.hashed_material()
        material["sequence"] = sequence
        return DescribedEvent(
            event_id=self.event_id,
            session_id=self.session_id,
            task_id=self.task_id,
            sequence=sequence,
            event_type=self.event_type,
            timestamp=self.timestamp,
            producer=self.producer,
            payload=dict(self.payload),
            classification=self.classification,
            audit_reference=self.audit_reference,
            previous_hash=self.previous_hash,
            event_hash=_seal(material, self.schema_version),
            redactions=self.redactions,
            internal_fields=self.internal_fields,
            schema_version=self.schema_version,
            record_kind=self.record_kind,
            description=self.description,
            evidence_references=self.evidence_references,
        )

    def to_json(self) -> dict[str, Any]:
        value = super().to_json()
        value["recordKind"] = self.record_kind
        value["description"] = self.description
        value["evidenceReferences"] = list(self.evidence_references)
        return value

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "DescribedEvent":
        if not isinstance(document, Mapping):
            raise SchemaError("an event record must be an object")
        references = document.get("evidenceReferences", [])
        if not isinstance(references, (list, tuple)) or any(not isinstance(item, str) for item in references):
            raise EventValidationError("evidenceReferences must be an array of strings")
        return cls(
            event_id=str(document.get("eventId", "")),
            session_id=str(document.get("sessionId", "")),
            task_id=str(document.get("taskId", "")),
            sequence=_require_int(document.get("sequence"), "sequence"),
            event_type=str(document.get("eventType", "")),
            timestamp=str(document.get("timestamp", "")),
            producer=str(document.get("producer", "")),
            payload=dict(document.get("payload")) if isinstance(document.get("payload"), Mapping) else {},
            classification=str(document.get("classification", "")),
            audit_reference=str(document.get("auditReference", "")),
            previous_hash=str(document.get("previousHash", "")),
            event_hash=str(document.get("eventHash", "")),
            redactions=tuple(str(item) for item in document.get("redactions", [])),
            internal_fields=tuple(str(item) for item in document.get("internalFields", [])),
            record_kind=str(document.get("recordKind", "observed_fact")),
            description=str(document.get("description", "")),
            evidence_references=tuple(str(item) for item in references),
        )


def observed_event(
    *,
    session_id: str,
    task_id: str,
    event_type: str,
    source: str,
    payload: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    sequence: int = 1,
    occurred_at: str | None = None,
    previous_hash: str = GENESIS_HASH,
    classification: str = "internal",
) -> DescribedEvent:
    """Build an observed-fact event: something happened, and this says what.

    The presentation-layer constructor. Free-text values are scrubbed of
    credential shapes before the payload is sanitized and sealed, so nothing
    that only ever existed in a caller's scratch dictionary reaches the stream.
    """
    return _described(
        build_event(
            event_id=event_id or str(uuid4()),
            session_id=session_id,
            task_id=task_id,
            sequence=int(sequence),
            event_type=event_type,
            timestamp=occurred_at or _utc_now_seconds(),
            producer=_producer_from(source),
            payload=redacted_payload(payload),
            classification=classification,
            previous_hash=previous_hash,
        ),
        record_kind="observed_fact",
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
    sequence: int = 1,
    occurred_at: str | None = None,
    previous_hash: str = GENESIS_HASH,
    classification: str = "internal",
) -> DescribedEvent:
    """Build a generated description that cites the events it summarises.

    A description nobody can trace back to observed facts is exactly the kind
    of text this package exists to refuse, so the citation rule is enforced
    here rather than left to whoever renders the words later.
    """
    return _described(
        build_event(
            event_id=event_id or str(uuid4()),
            session_id=session_id,
            task_id=task_id,
            sequence=int(sequence),
            event_type=event_type,
            timestamp=occurred_at or _utc_now_seconds(),
            producer=_producer_from(source),
            payload=redacted_payload(payload),
            classification=classification,
            previous_hash=previous_hash,
        ),
        record_kind="generated_description",
        description=redact_text(description, 1000),
        evidence=tuple(evidence_references),
    )


def _described(
    base: TaskEvent,
    *,
    record_kind: str,
    description: str = "",
    evidence: tuple[str, ...] = (),
) -> DescribedEvent:
    """Re-present an already-sealed event as a :class:`DescribedEvent`.

    The hash travels across untouched: the presentation fields sit outside the
    sealed set, so re-presenting cannot change what the chain attests to.
    """
    return DescribedEvent(
        event_id=base.event_id,
        session_id=base.session_id,
        task_id=base.task_id,
        sequence=base.sequence,
        event_type=base.event_type,
        timestamp=base.timestamp,
        producer=base.producer,
        payload=dict(base.payload),
        classification=base.classification,
        audit_reference=base.audit_reference,
        previous_hash=base.previous_hash,
        event_hash=base.event_hash,
        redactions=base.redactions,
        internal_fields=base.internal_fields,
        schema_version=base.schema_version,
        record_kind=record_kind,
        description=description,
        evidence_references=evidence,
    )

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured audit records for everything the applicator does.

Two rules shape this module.

**Observed fact and inferred explanation are different fields.** A record says
what was measured and, separately, what the applicator concluded from it. Mixing
them produces a log in which "the service was stopped because memory was low"
cannot be checked, because nobody can tell which half was read off a meter and
which half was reasoning. Every record carries ``observed`` and ``inferred``
blocks and the renderer keeps them apart.

**Nothing sensitive is written, and the guarantee is structural.** There is no
field for a credential, a prompt, or a task payload, so there is no path by
which one is logged. Free-text details pass through a redactor on the way in
rather than on the way out, because a redactor at the read end protects nothing
once the bytes are on disk.

Retention is bounded by count, and the sink writes only when something happened.
A monitor that samples every thirty seconds and finds nothing writes nothing:
on a node with an SD card for storage, an audit log that records "no change"
1,700 times a day is a hardware failure being scheduled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from . import AUDIT_SCHEMA_VERSION

__all__ = [
    "AuditRecord",
    "AuditSink",
    "EVENT_TYPES",
    "InMemoryAuditSink",
    "JsonLinesAuditSink",
    "redact",
]

#: Stable event identifiers. A consumer matches on these, never on a message.
EVENT_TYPES = (
    "plan.generated",
    "plan.superseded",
    "plan.rejected",
    "reconcile.started",
    "reconcile.finished",
    "transition.attempted",
    "transition.succeeded",
    "transition.failed",
    "transition.postponed",
    "transition.rolled_back",
    "backend.operation",
    "reservation.taken",
    "reservation.committed",
    "reservation.released",
    "reservation.reclaimed",
    "approval.requested",
    "approval.resolved",
    "policy.rejected",
    "runtime.pressure",
    "circuit.changed",
    "remote.state_changed",
)

#: Patterns whose matches never reach a record. Written as shapes rather than as
#: a list of known key names, because the next credential format will not be on
#: a list somebody maintained.
_REDACTIONS = (
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*\S+"),
     r"\1=[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}"), "bearer [redacted]"),
    (re.compile(r"\b(sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{12,}\b"), "[redacted-credential]"),
    # An IPv4 literal identifies a network and often a household. Ports are kept
    # because they say what kind of service was involved and identify nobody.
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "[redacted-address]"),
    # MAC addresses identify a machine permanently.
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "[redacted-hardware-address]"),
)

#: Free text is bounded. A service that emits a megabyte of diagnostics must not
#: be able to fill a constrained node's storage through the audit log.
_MAXIMUM_DETAIL = 1024


def redact(value: Any) -> Any:
    """Strip identifying and secret material from anything bound for a record.

    Applied recursively to strings inside mappings and sequences, so a nested
    diagnostic cannot smuggle a key past a check that only looked at the top
    level.
    """
    if isinstance(value, str):
        text = value
        for pattern, replacement in _REDACTIONS:
            text = pattern.sub(replacement, text)
        home = os.path.expanduser("~")
        if home and home not in ("/", ""):
            text = text.replace(home, "~")
        return text[:_MAXIMUM_DETAIL]
    if isinstance(value, Mapping):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


@dataclass(frozen=True)
class AuditRecord:
    """One thing that happened, with its evidence and its reasoning separated."""

    event: str
    #: Monotonic clock, matching every other time in this package.
    at_monotonic: float
    plan_id: str = ""
    service_id: str = ""
    transition_id: str = ""
    #: What was measured or returned. Facts.
    observed: Mapping[str, Any] = field(default_factory=dict)
    #: What the applicator concluded. Reasoning, and labelled as such.
    inferred: Mapping[str, Any] = field(default_factory=dict)
    #: "info" | "notice" | "warning"
    severity: str = "info"

    def __post_init__(self) -> None:
        if self.event not in EVENT_TYPES:
            raise ValueError(f"unknown audit event: {self.event!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": AUDIT_SCHEMA_VERSION,
            "event": self.event,
            "atMonotonic": self.at_monotonic,
            "severity": self.severity,
            "planId": self.plan_id,
            "serviceId": self.service_id,
            "transitionId": self.transition_id,
            "observed": redact(dict(self.observed)),
            "inferred": redact(dict(self.inferred)),
        }


class AuditSink:
    """Where records go. Subclassed rather than protocol'd so the bounded
    retention and the redaction cannot be bypassed by a partial implementation."""

    def write(self, record: AuditRecord) -> None:
        raise NotImplementedError

    def record(
        self, event: str, *, at_monotonic: float, observed: Mapping[str, Any] | None = None,
        inferred: Mapping[str, Any] | None = None, severity: str = "info", **identity: str,
    ) -> AuditRecord:
        entry = AuditRecord(
            event=event, at_monotonic=at_monotonic,
            observed=observed or {}, inferred=inferred or {},
            severity=severity, **identity,
        )
        self.write(entry)
        return entry


@dataclass
class InMemoryAuditSink(AuditSink):
    """The default. Bounded, inspectable, writes nothing to disk."""

    limit: int = 512
    records: list[AuditRecord] = field(default_factory=list)

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)
        if len(self.records) > self.limit:
            del self.records[: len(self.records) - self.limit]

    def events(self) -> tuple[str, ...]:
        return tuple(item.event for item in self.records)

    def for_service(self, service_id: str) -> tuple[AuditRecord, ...]:
        return tuple(item for item in self.records if item.service_id == service_id)

    def for_transition(self, transition_id: str) -> tuple[AuditRecord, ...]:
        return tuple(item for item in self.records if item.transition_id == transition_id)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": AUDIT_SCHEMA_VERSION,
            "limit": self.limit,
            "records": [item.to_json() for item in self.records],
        }


@dataclass
class JsonLinesAuditSink(AuditSink):
    """Appends to a JSON Lines file, with rotation by line count.

    One line per record so a truncated write costs one record rather than the
    file. Rotation is by count rather than by size because a count is knowable
    without stat-ing the file on every write, and on a constrained node the
    stat is a measurable share of the cost of logging at all.
    """

    path: Path
    limit: int = 2000
    _written: int = 0

    def __post_init__(self) -> None:
        # Count what is already there once, at construction, so that a process
        # restart does not reset the retention window and grow the file forever.
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._written = sum(1 for _ in handle)
        except OSError:
            self._written = 0

    def write(self, record: AuditRecord) -> None:
        line = json.dumps(record.to_json(), sort_keys=True, separators=(",", ":"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._written += 1
        except OSError:
            # An audit log that cannot be written must not stop the machine
            # adapting. The failure is itself worth knowing about, but the place
            # to report it is the caller's status output, not an exception
            # thrown out of a logging call in the middle of a transition.
            return
        if self._written > self.limit:
            self._rotate()

    def _rotate(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        keep = lines[-(self.limit // 2):]
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text("\n".join(keep) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
            self._written = len(keep)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass


def summarize(records: Sequence[AuditRecord]) -> dict[str, Any]:
    """Counts by event and by severity, for a status line."""
    by_event: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for item in records:
        by_event[item.event] = by_event.get(item.event, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
    return {
        "total": len(records),
        "byEvent": dict(sorted(by_event.items())),
        "bySeverity": dict(sorted(by_severity.items())),
    }

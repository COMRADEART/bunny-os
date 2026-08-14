# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the model bridge writes down, and the much longer list of what it does not.

These are subsystem lifecycle events, not task events. :mod:`companion.events`
is a hash-chained stream about *a task* — every entry belongs to one, and its
integrity model exists because a task's history has to survive a crash. A model
being validated belongs to no task, so putting it there would mean inventing a
task id for it, which is how an audit trail starts describing things that did
not happen.

So this is a separate, simpler record: one JSON object per line, appended and
flushed, in the registry's own state directory.

**The payload is a closed set of keys, enforced here.** Not a convention — a
:data:`_PAYLOAD_KEYS` check that drops anything else and records that it did.
The reason is the rule this milestone inherits from Model Studio: a training
corpus is the most private thing in the system, and the events most likely to
be attached to one are exactly these. There is no key in this vocabulary for a
prompt, a completion, a dataset row, a file path the user named, or a
credential. A caller that passes one gets it dropped, and the log says a key
was dropped so the omission is visible rather than silent.

Paths that *are* recorded are artifact and adapter paths — machine-owned
locations under a trusted root, not user content — because "which bytes were
activated" is the question this log exists to answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

__all__ = [
    "EVENT_TYPES",
    "ModelEvent",
    "ModelEventLog",
    "NullEventLog",
    "utc_now",
]

#: Phase 16's vocabulary. A type outside this set is refused rather than
#: written, so a typo cannot create a category nobody greps for.
EVENT_TYPES: tuple[str, ...] = (
    "model.discovered",
    "model.validation_started",
    "model.validation_passed",
    "model.validation_failed",
    "model.validation_unknown",
    "model.loaded",
    "model.load_failed",
    "model.enabled",
    "model.disabled",
    "model.released",
    "model.fallback_selected",
)

#: Everything an event may carry. Anything else is dropped and counted.
_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "modelId", "status", "code", "field", "reason", "backendId", "adapterFormat",
    "adapterSha256", "adapterPath", "artifactPath", "baseModel", "baseRevision",
    "scale", "verified", "applied", "findings", "previousModelId", "endpoint",
    "requestedModelId",
    "bunnyCommit", "createdBy", "jobId",
})

_MAX_VALUE_CHARS = 512
_MAX_EVENTS_BYTES = 8 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bounded(value: Any) -> Any:
    """Values are scalars or short lists of scalars, and never long."""
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_VALUE_CHARS else value[:_MAX_VALUE_CHARS] + "…"
    if isinstance(value, (list, tuple)):
        return [_bounded(item) for item in list(value)[:16]]
    if isinstance(value, Mapping):
        return {str(key): _bounded(item) for key, item in list(value.items())[:16]}
    return str(value)[:_MAX_VALUE_CHARS]


@dataclass(frozen=True)
class ModelEvent:
    """One thing that happened to a model, said in a fixed vocabulary."""

    event_type: str
    at: str = field(default_factory=utc_now)
    payload: Mapping[str, Any] = field(default_factory=dict)
    #: How many keys were dropped for not being in the vocabulary. Recorded
    #: rather than silently zero, so an omission is visible.
    dropped_keys: tuple[str, ...] = ()

    @classmethod
    def build(cls, event_type: str, **payload: Any) -> "ModelEvent":
        if event_type not in EVENT_TYPES:
            raise ValueError(f"{event_type!r} is not one of {EVENT_TYPES}")
        kept = {key: _bounded(value) for key, value in payload.items() if key in _PAYLOAD_KEYS}
        dropped = tuple(sorted(set(payload) - _PAYLOAD_KEYS))
        return cls(event_type=event_type, payload=kept, dropped_keys=dropped)

    def to_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "eventType": self.event_type,
            "at": self.at,
            **dict(self.payload),
        }
        if self.dropped_keys:
            document["droppedKeys"] = list(self.dropped_keys)
        return document


class NullEventLog:
    """Records nothing. The default, so no caller has to check for a log."""

    def record(self, event: ModelEvent) -> ModelEvent:
        return event

    def read(self) -> tuple[ModelEvent, ...]:
        return ()


class ModelEventLog:
    """Append-only JSON Lines beside the registry state.

    Flushed and fsynced per line for the same reason Model Studio's training log
    is: the moment this record matters most is the one where the process did not
    get to close the file.
    """

    def __init__(self, path: Path | str, *, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def record(self, event: ModelEvent) -> ModelEvent:
        stamped = ModelEvent(
            event_type=event.event_type,
            at=self._clock(),
            payload=event.payload,
            dropped_keys=event.dropped_keys,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.exists() and self.path.stat().st_size > _MAX_EVENTS_BYTES:
                self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
        except OSError:  # pragma: no cover - rotation is best effort
            pass
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(stamped.to_json(), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return stamped

    def read(self) -> tuple[ModelEvent, ...]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return ()
        events: list[ModelEvent] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = str(document.pop("eventType", ""))
            at = str(document.pop("at", ""))
            dropped = tuple(document.pop("droppedKeys", ()) or ())
            if event_type not in EVENT_TYPES:
                continue
            events.append(ModelEvent(event_type=event_type, at=at, payload=document,
                                     dropped_keys=dropped))
        return tuple(events)

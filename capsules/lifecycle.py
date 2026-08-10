# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which states a capsule may be in, and which moves between them are legal.

The table is the whole of the lifecycle, and it is data rather than control flow
for the same reason :mod:`companion.states` is: an ``if`` chain spread across a
runtime can be made to permit a move nobody intended by adding one branch,
whereas a move that is not in :data:`TRANSITIONS` cannot happen, and a test can
enumerate every pair and assert on the ones that are refused.

Four rules shaped it.

**A capsule found running after a crash goes to ``unknown``, not to ``running``.**
The Bunny runtime restarting does not tell it whether the application it started
is still there. ``unknown`` exists so that the next operation *reconciles* — asks
the backend what is actually running — rather than trusting a record written
before the crash. Believing a stale ``running`` is how a second copy of an
application gets started on top of the first.

**Destructive operations are only legal from ``stopped``.** Reset, delete-data
and uninstall all require the capsule to be stopped, because deleting the
directories underneath a running application produces a mess whose cause is
invisible afterwards. The runtime stops first and the *table* is what makes that
mandatory rather than customary.

**``broken`` is not terminal.** A capsule whose manifest failed to parse or whose
isolation plan could not be built is broken, and the repair path — reset, or
reinstall — must be reachable. §23 requires a recovery path for a broken capsule,
and a terminal failure state would be a design that has none.

**``removed`` is terminal and means the directory is gone.** Nothing transitions
out of it; a reinstall is a new capsule that happens to have the same identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from trust.persistence import atomic_write_json, read_json

from .errors import CapsuleSchemaError, CapsuleStateError

__all__ = [
    "ACTIVE_STATES",
    "DESTRUCTIVE_FROM",
    "INITIAL_STATE",
    "STATES",
    "STATE_SCHEMA_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "CapsuleState",
    "require_transition",
    "transition_allowed",
]

STATE_SCHEMA_VERSION = 1

STATES = (
    "absent",
    "provisioning",
    "ready",
    "starting",
    "running",
    "stopping",
    "stopped",
    "resetting",
    "unknown",
    "broken",
    "removed",
)

INITIAL_STATE = "absent"

TERMINAL_STATES = frozenset({"removed"})

#: States in which the capsule owns processes, or might.
ACTIVE_STATES = frozenset({"starting", "running", "stopping", "unknown"})

#: The only state a reset, a data deletion or an uninstall may begin from. See
#: the module docstring.
DESTRUCTIVE_FROM = frozenset({"stopped", "ready", "broken"})

#: (from, to). A set rather than a mapping to an event name, because a capsule
#: transition is recorded by the runtime with its own reason string; the table's
#: job here is only to say which moves exist.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("absent", "provisioning"),
        ("provisioning", "ready"),
        ("provisioning", "broken"),
        ("ready", "starting"),
        ("ready", "resetting"),
        ("ready", "removed"),
        ("ready", "broken"),
        ("starting", "running"),
        ("starting", "broken"),
        # A start that failed before anything ran leaves the capsule usable.
        ("starting", "stopped"),
        ("running", "stopping"),
        # The process went away without us asking.
        ("running", "stopped"),
        ("running", "unknown"),
        ("stopping", "stopped"),
        ("stopping", "unknown"),
        ("stopped", "starting"),
        ("stopped", "resetting"),
        ("stopped", "removed"),
        ("stopped", "broken"),
        ("resetting", "ready"),
        ("resetting", "broken"),
        # Reconciliation with the backend is what leaves `unknown`.
        ("unknown", "running"),
        ("unknown", "stopped"),
        ("unknown", "broken"),
        ("broken", "resetting"),
        ("broken", "removed"),
        ("broken", "stopped"),
    }
)


def transition_allowed(current: str, target: str) -> bool:
    return (current, target) in TRANSITIONS


def require_transition(current: str, target: str) -> None:
    """Raise unless the move is in the table."""
    if current not in STATES:
        raise CapsuleSchemaError(f"unknown capsule state: {current!r}")
    if target not in STATES:
        raise CapsuleSchemaError(f"unknown capsule state: {target!r}")
    if not transition_allowed(current, target):
        raise CapsuleStateError(f"a capsule cannot go from {current} to {target}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class CapsuleState:
    """The persisted lifecycle record for one capsule.

    Small on purpose. It is read on every launch and written on every transition,
    and anything expensive in here would show up as launch latency — which §24
    asks to be measured rather than assumed.
    """

    state: str = INITIAL_STATE
    since: str = field(default_factory=_now)
    launch_count: int = 0
    last_started_at: str | None = None
    last_stopped_at: str | None = None
    last_exit_code: int | None = None
    last_failure: str | None = None
    backend: str | None = None
    scope_name: str | None = None
    #: The session the capsule was last started in. Compared on load: a record
    #: saying ``running`` from a previous session cannot be true, and the state
    #: becomes ``unknown`` so the next operation reconciles instead of trusting
    #: it. This is the crash rule from the module docstring, implemented once.
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise CapsuleSchemaError(f"unknown capsule state: {self.state!r}")

    def move(self, target: str, *, failure: str | None = None) -> "CapsuleState":
        require_transition(self.state, target)
        self.state = target
        self.since = _now()
        self.last_failure = failure
        return self

    def reconcile_for_session(self, session_id: str) -> "CapsuleState":
        """Downgrade a stale active state to ``unknown`` for a new session."""
        if self.state in ACTIVE_STATES and self.session_id != session_id:
            self.state = "unknown"
            self.since = _now()
            self.last_failure = "found active from a previous session"
        return self

    def as_record(self) -> Mapping[str, Any]:
        return {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "state": self.state,
            "since": self.since,
            "launchCount": self.launch_count,
            "lastStartedAt": self.last_started_at,
            "lastStoppedAt": self.last_stopped_at,
            "lastExitCode": self.last_exit_code,
            "lastFailure": self.last_failure,
            "backend": self.backend,
            "scopeName": self.scope_name,
            "sessionId": self.session_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CapsuleState":
        if not isinstance(record, Mapping):
            raise CapsuleSchemaError("a capsule state must be a record")
        version = record.get("schemaVersion")
        if version != STATE_SCHEMA_VERSION:
            raise CapsuleSchemaError(
                f"state schema version {version!r}; this build understands {STATE_SCHEMA_VERSION}"
            )
        return cls(
            state=str(record.get("state", INITIAL_STATE)),
            since=str(record.get("since", _now())),
            launch_count=int(record.get("launchCount", 0)),
            last_started_at=_optional_str(record.get("lastStartedAt")),
            last_stopped_at=_optional_str(record.get("lastStoppedAt")),
            last_exit_code=(int(record["lastExitCode"]) if record.get("lastExitCode") is not None else None),
            last_failure=_optional_str(record.get("lastFailure")),
            backend=_optional_str(record.get("backend")),
            scope_name=_optional_str(record.get("scopeName")),
            session_id=_optional_str(record.get("sessionId")),
        )

    def write(self, path) -> None:  # type: ignore[no-untyped-def]
        atomic_write_json(path, dict(self.as_record()))

    @classmethod
    def read(cls, path) -> "CapsuleState":  # type: ignore[no-untyped-def]
        document = read_json(path, default=None)
        if document is None:
            return cls()
        return cls.from_record(document)


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None

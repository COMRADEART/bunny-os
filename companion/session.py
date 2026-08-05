# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The companion session: the standing context a task is submitted into.

A session is where the answers that should not be re-asked per task live. How
private is this work. How much may it cost. May any of it leave the machine. Ask
those once per session and a user can submit ten tasks; ask them per task and
they stop reading the question by the third one, which is how consent becomes a
reflex.

The session document is a **projection**. Everything in it can be rebuilt by
replaying the session's events, and :meth:`CompanionSession.touch` and friends
return new instances rather than mutating, so a session held by two callers
cannot drift. The stored document exists so that opening a session does not cost
a full replay on a machine with 64 MB of RAM; :mod:`companion.recovery` checks it
against the stream and prefers the stream whenever they disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from . import SESSION_SCHEMA_VERSION
from .clock import iso8601
from .errors import SchemaError
from .ids import valid_id
from .privacy import DATA_CLASSES, display_summary, rank

__all__ = [
    "CostPolicy",
    "LOCALITY_PREFERENCES",
    "PrivacyPolicy",
    "SESSION_STATUSES",
    "CompanionSession",
]

#: What a session may be doing. Narrower than a task's lifecycle: a session is a
#: container, and the interesting states belong to the tasks inside it.
SESSION_STATUSES = ("active", "paused", "closed")

#: Where the user is willing to have work done. The names are
#: :data:`capability.router.DATA_LOCALITIES` unchanged, so that a preference set
#: here reaches the router without a translation table that could be wrong.
LOCALITY_PREFERENCES = ("device-only", "trusted-remote", "any")


@dataclass(frozen=True)
class PrivacyPolicy:
    """What may be classified how, and what may leave.

    The defaults are the strict end. A session created without an explicit
    policy treats its content as ``personal`` and permits nothing off-device,
    because the alternative — defaulting to permissive and relying on the caller
    to tighten it — means every forgotten argument is a disclosure.
    """

    #: How an unclassified request is treated until classification says otherwise.
    default_classification: str = "personal"
    #: Nothing above this may be sent off-device, whatever else permits it.
    maximum_remote_classification: str = "internal"
    #: Whether remote execution is permitted at all from this session.
    allow_remote: bool = False

    def __post_init__(self) -> None:
        for name in ("default_classification", "maximum_remote_classification"):
            value = getattr(self, name)
            if value not in DATA_CLASSES:
                raise SchemaError(f"{name} must be one of {list(DATA_CLASSES)}")
        if rank(self.maximum_remote_classification) > rank("sensitive"):
            raise SchemaError(
                "maximumRemoteClassification cannot be 'secret'; secret data never leaves the device"
            )

    def permits_remote(self, classification: str) -> bool:
        return self.allow_remote and rank(classification) <= rank(self.maximum_remote_classification)

    def to_json(self) -> dict[str, Any]:
        return {
            "defaultClassification": self.default_classification,
            "maximumRemoteClassification": self.maximum_remote_classification,
            "allowRemote": self.allow_remote,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "PrivacyPolicy":
        return cls(
            default_classification=str(document.get("defaultClassification", "personal")),
            maximum_remote_classification=str(document.get("maximumRemoteClassification", "internal")),
            allow_remote=bool(document.get("allowRemote", False)),
        )


@dataclass(frozen=True)
class CostPolicy:
    """What may be spent, in whole currency minor units.

    ``0`` is the default and means *nothing may be spent*, which is a different
    statement from "no limit is configured". There is no way to express "no
    limit" here, and that is deliberate: an unbounded spend authorised by
    omission is not an authorisation.
    """

    task_limit_units: int = 0
    session_limit_units: int = 0
    #: Spend at or above this figure needs a person even when it is under the
    #: limits. Zero means every non-free act is asked about.
    approval_threshold_units: int = 0

    def __post_init__(self) -> None:
        for name in ("task_limit_units", "session_limit_units", "approval_threshold_units"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SchemaError(f"{name} must be a non-negative integer")
        if self.task_limit_units > self.session_limit_units and self.session_limit_units > 0:
            raise SchemaError("a task may not be permitted to spend more than its whole session")

    def to_json(self) -> dict[str, Any]:
        return {
            "taskLimitUnits": self.task_limit_units,
            "sessionLimitUnits": self.session_limit_units,
            "approvalThresholdUnits": self.approval_threshold_units,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "CostPolicy":
        return cls(
            task_limit_units=int(document.get("taskLimitUnits", 0) or 0),
            session_limit_units=int(document.get("sessionLimitUnits", 0) or 0),
            approval_threshold_units=int(document.get("approvalThresholdUnits", 0) or 0),
        )


@dataclass(frozen=True)
class CompanionSession:
    """One standing conversation between a person and the companion."""

    session_id: str
    title: str
    created_at: str
    last_activity_at: str
    status: str = "active"
    active_task_ids: tuple[str, ...] = ()
    completed_task_ids: tuple[str, ...] = ()
    privacy_policy: PrivacyPolicy = field(default_factory=PrivacyPolicy)
    cost_policy: CostPolicy = field(default_factory=CostPolicy)
    locality_preference: str = "device-only"
    #: The executor the session most recently selected. Advisory: every task
    #: re-runs the capability check, because a session that pinned an executor
    #: would keep using it after the machine stopped being able to.
    selected_executor: str = ""
    selected_reviewers: tuple[str, ...] = ()
    #: The capability plan the last decision in this session was made against.
    capability_plan_reference: str = ""
    #: Sequence number of the last event written to this session's stream. The
    #: store's tip and this field are compared on load; a disagreement is a
    #: crash between the append and the projection write, and the stream wins.
    event_stream_revision: int = 0
    schema_version: int = SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not valid_id(self.session_id):
            raise SchemaError(f"sessionId is not a usable identifier: {self.session_id!r}")
        if self.status not in SESSION_STATUSES:
            raise SchemaError(f"session status must be one of {list(SESSION_STATUSES)}")
        if self.locality_preference not in LOCALITY_PREFERENCES:
            raise SchemaError(f"localityPreference must be one of {list(LOCALITY_PREFERENCES)}")
        if self.event_stream_revision < 0:
            raise SchemaError("eventStreamRevision cannot be negative")
        overlap = set(self.active_task_ids) & set(self.completed_task_ids)
        if overlap:
            raise SchemaError(
                f"a task cannot be both active and completed: {', '.join(sorted(overlap))}"
            )

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        title: str,
        now: float,
        privacy_policy: PrivacyPolicy | None = None,
        cost_policy: CostPolicy | None = None,
        locality_preference: str = "device-only",
    ) -> "CompanionSession":
        stamp = iso8601(now)
        return cls(
            session_id=session_id,
            title=display_summary(title or "Untitled session", limit=120),
            created_at=stamp,
            last_activity_at=stamp,
            privacy_policy=privacy_policy or PrivacyPolicy(),
            cost_policy=cost_policy or CostPolicy(),
            locality_preference=locality_preference,
        )

    def touch(self, now: float, *, revision: int | None = None) -> "CompanionSession":
        return replace(
            self,
            last_activity_at=iso8601(now),
            event_stream_revision=self.event_stream_revision if revision is None else revision,
        )

    def paused(self, now: float) -> "CompanionSession":
        return replace(self, status="paused", last_activity_at=iso8601(now))

    def resumed(self, now: float) -> "CompanionSession":
        if self.status == "closed":
            raise SchemaError("a closed session cannot be resumed; create a new one")
        return replace(self, status="active", last_activity_at=iso8601(now))

    def closed(self, now: float) -> "CompanionSession":
        return replace(self, status="closed", last_activity_at=iso8601(now))

    def with_task(self, task_id: str, now: float) -> "CompanionSession":
        if task_id in self.active_task_ids or task_id in self.completed_task_ids:
            return self.touch(now)
        return replace(
            self,
            active_task_ids=(*self.active_task_ids, task_id),
            last_activity_at=iso8601(now),
        )

    def task_finished(self, task_id: str, now: float) -> "CompanionSession":
        """Move a task from active to completed. Idempotent.

        "Completed" here means "no longer running" and covers failure and
        cancellation too — the session's job is to know what still needs
        attention, and a failed task does not.
        """
        return replace(
            self,
            active_task_ids=tuple(item for item in self.active_task_ids if item != task_id),
            completed_task_ids=(
                self.completed_task_ids
                if task_id in self.completed_task_ids
                else (*self.completed_task_ids, task_id)
            ),
            last_activity_at=iso8601(now),
        )

    def with_selection(
        self,
        *,
        executor: str = "",
        reviewers: Sequence[str] = (),
        plan_reference: str = "",
    ) -> "CompanionSession":
        return replace(
            self,
            selected_executor=executor or self.selected_executor,
            selected_reviewers=tuple(reviewers) or self.selected_reviewers,
            capability_plan_reference=plan_reference or self.capability_plan_reference,
        )

    # -- serialization -----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "title": self.title,
            "createdAt": self.created_at,
            "lastActivityAt": self.last_activity_at,
            "status": self.status,
            "activeTaskIds": list(self.active_task_ids),
            "completedTaskIds": list(self.completed_task_ids),
            "privacyPolicy": self.privacy_policy.to_json(),
            "costPolicy": self.cost_policy.to_json(),
            "localityPreference": self.locality_preference,
            "selectedExecutor": self.selected_executor,
            "selectedReviewers": list(self.selected_reviewers),
            "capabilityPlanReference": self.capability_plan_reference,
            "eventStreamRevision": self.event_stream_revision,
        }

    def view(self, audience: str, *, classification: str | None = None) -> dict[str, Any]:
        """The session as one audience may read it.

        Only the title is masked. Everything else — the id, the status, the
        policies, the task lists, the revision — is machine fact, and an export
        that blanked it would be unreadable for the audit and support cases it
        exists to serve. The title is the one field the user wrote.

        ``classification`` defaults to the policy's own default class, and a
        caller that knows the session holds something more sensitive (the
        strictest of its tasks, say) can pass that instead.
        """
        from .privacy import visible_to, withheld_marker

        level = classification or self.privacy_policy.default_classification
        value = self.to_json()
        if not visible_to(audience, level):
            value["title"] = withheld_marker(level)
        return value

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "CompanionSession":
        if not isinstance(document, Mapping):
            raise SchemaError("a session document must be an object")
        version = document.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool):
            raise SchemaError("a session document must carry an integer schemaVersion")
        if version > SESSION_SCHEMA_VERSION:
            raise SchemaError(
                f"session schemaVersion {version} is newer than this build understands"
            )
        try:
            return cls(
                session_id=str(document.get("sessionId", "")),
                title=str(document.get("title", "")),
                created_at=str(document.get("createdAt", "")),
                last_activity_at=str(document.get("lastActivityAt", "")),
                status=str(document.get("status", "active")),
                active_task_ids=tuple(str(item) for item in document.get("activeTaskIds", ())),
                completed_task_ids=tuple(str(item) for item in document.get("completedTaskIds", ())),
                privacy_policy=PrivacyPolicy.from_json(document.get("privacyPolicy") or {}),
                cost_policy=CostPolicy.from_json(document.get("costPolicy") or {}),
                locality_preference=str(document.get("localityPreference", "device-only")),
                selected_executor=str(document.get("selectedExecutor", "")),
                selected_reviewers=tuple(str(item) for item in document.get("selectedReviewers", ())),
                capability_plan_reference=str(document.get("capabilityPlanReference", "")),
                event_stream_revision=int(document.get("eventStreamRevision", 0) or 0),
                schema_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"a session document could not be parsed: {exc}") from exc

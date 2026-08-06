# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one object that crosses from the canonical runtime into the broker.

§3's field list, and — as much as the list itself — §3's *absences*. There is no
field here for a shell command, an executable path, an argument vector, an
environment variable, a D-Bus destination, a raw provider string, a credential,
a screen capture or an unbounded path. A structural test asserts that over the
dataclass rather than over this paragraph, because a paragraph does not fail
when somebody adds a field.

Every authority fact arrives as a **value**. The broker is handed the task id,
the lifecycle epoch, the plan id, the operation id and the approval reference;
it is not handed the task, the runtime, the store or the approval gate, and it
has no way to reach any of them. That is what lets ``companion/desktop/`` be
checked for runtime independence by reading one directory, and it is also what
makes "revalidate current task and approval authority" (§1) a comparison of
values the caller supplied against values the ledger holds, rather than a second
opinion about state the runtime already owns.

Three time fields, and they are not redundant:

``created_at``
    wall time, for a person reading a history.
``expires_at_monotonic``
    when the *approval* stops being consent. Monotonic, because a wall-clock
    expiry can be extended by changing a timezone, which is a consent bypass
    with a settings dialog.
``deadline_monotonic``
    when the *attempt* must have finished. A portal request that never answers
    has to end somewhere, and it must end before the approval does — otherwise
    the act could complete after the consent for it lapsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from ..clock import iso8601
from ..ids import valid_id
from ..privacy import DATA_CLASSES
from . import DESKTOP_ACTION_SCHEMA_VERSION
from .binding import ApprovalBinding
from .catalogue import descriptor_for
from .errors import DesktopSchemaError
from .idempotency import action_key
from .parameters import NormalisedAction

__all__ = [
    "DesktopActionRequest",
    "FORBIDDEN_REQUEST_FIELD_WORDS",
    "MAX_DEADLINE_SECONDS",
]

#: The longest any one attempt may take. A portal dialog a user never answers,
#: a D-Bus call to a service that has wedged, an application that takes the
#: activation and never returns — each of them ends here rather than holding the
#: broker open for the life of the process.
MAX_DEADLINE_SECONDS = 120.0

#: Words that must not appear in a field name on this object. Used by the
#: structural test in ``tests/companion/test_desktop_authority.py``; kept here so
#: the list and the object it constrains are read together.
FORBIDDEN_REQUEST_FIELD_WORDS = (
    "command", "argv", "arguments_list", "executable", "binary", "shell",
    "environment", "env", "credential", "password", "secret", "token_value",
    "bus_name", "dbus", "interface", "screen", "framebuffer", "capture",
)


@dataclass(frozen=True)
class DesktopActionRequest:
    """One validated, approved-or-approvable desktop action attempt.

    Constructed by :meth:`build` from a :class:`~companion.desktop.parameters.NormalisedAction`
    and the authority facts. Never constructed from provider material directly:
    the normalisation that produced the action has already refused everything
    the schemas refuse, so a request that exists is a request whose parameters
    have been checked.
    """

    schema_version: int
    request_id: str
    session_id: str
    task_id: str
    lifecycle_epoch: int
    plan_id: str
    operation_id: str
    idempotency_key: str
    action_id: str
    parameters: Mapping[str, Any]
    expected_effect: str
    #: The exact application, page, address, sink or file this acts on.
    target: str
    target_kind: str
    classification: str
    approval_class: str
    #: The canonical approval this attempt is authorised by. Empty only for an
    #: attempt that has not yet been approved — the broker refuses to execute
    #: one, so an empty reference is a request in flight rather than a hole.
    approval_reference: str
    created_at: str
    expires_at_monotonic: float
    deadline_monotonic: float
    cancellation_token: str
    reversibility: str
    undo_action_id: str
    #: §18's sentence. Carried on the request so that the prompt, the record and
    #: the result all quote one string.
    presentation: str
    #: What is being disclosed, in words. Never the data.
    disclosure: str
    #: The canonical audit record this attempt belongs to.
    audit_reference: str = ""
    #: Whether this attempt is itself an undo of an earlier one. §11 requires an
    #: undo to be a new action with its own lifecycle; this field is how the
    #: record shows the relationship without the undo borrowing the original's
    #: identity.
    undo_of: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != DESKTOP_ACTION_SCHEMA_VERSION:
            raise DesktopSchemaError(
                f"a desktop action request of version {self.schema_version} was built by a "
                f"runtime that speaks version {DESKTOP_ACTION_SCHEMA_VERSION}"
            )
        for name, value in (
            ("requestId", self.request_id),
            ("sessionId", self.session_id),
            ("taskId", self.task_id),
        ):
            if not valid_id(value):
                raise DesktopSchemaError(f"{name} is not a usable identifier: {value!r}")
        if self.lifecycle_epoch < 0:
            raise DesktopSchemaError("a lifecycle epoch cannot be negative")
        if self.classification not in DATA_CLASSES:
            raise DesktopSchemaError(f"unknown classification: {self.classification!r}")
        if not self.operation_id:
            raise DesktopSchemaError("a desktop action request names the operation it performs")
        if not self.idempotency_key:
            raise DesktopSchemaError("a desktop action request carries its idempotency key")
        if not self.presentation:
            raise DesktopSchemaError(
                "a desktop action request carries the sentence shown to the user; §18 forbids "
                "a surface inventing its own"
            )
        descriptor = descriptor_for(self.action_id)
        if descriptor.approval_class != self.approval_class:
            raise DesktopSchemaError(
                f"{self.action_id} is approved under {descriptor.approval_class!r} and this "
                f"request claims {self.approval_class!r}"
            )
        if descriptor.reversibility != self.reversibility:
            raise DesktopSchemaError(
                f"{self.action_id} is {descriptor.reversibility} and this request claims "
                f"{self.reversibility}"
            )
        if not descriptor.accepts(self.classification):
            raise DesktopSchemaError(
                f"{self.action_id} may be given data up to {descriptor.privacy_ceiling} and "
                f"this request is {self.classification}"
            )
        if self.expires_at_monotonic and self.deadline_monotonic > self.expires_at_monotonic:
            # An attempt allowed to outlive its approval could complete after
            # consent lapsed, which is the same act happening without consent
            # and a slower way to reach it.
            raise DesktopSchemaError(
                "the attempt's deadline is later than the approval's expiry; an act must not "
                "be able to finish after the consent for it has run out"
            )

    @property
    def approved(self) -> bool:
        return bool(self.approval_reference)

    @property
    def binding(self) -> ApprovalBinding:
        """The act, as §8 compares acts."""
        return ApprovalBinding(
            task_id=self.task_id,
            lifecycle_epoch=self.lifecycle_epoch,
            plan_id=self.plan_id,
            operation_id=self.operation_id,
            action_id=self.action_id,
            target=self.target,
            parameters=dict(self.parameters),
            classification=self.classification,
            expected_effect=self.expected_effect,
            reversibility=self.reversibility,
            undo_action_id=self.undo_action_id,
            expires_at_monotonic=self.expires_at_monotonic,
            destination=self.target,
            disclosure=self.disclosure,
        )

    def with_approval(self, reference: str) -> "DesktopActionRequest":
        """The same act, now carrying the approval that authorises it."""
        if not reference:
            raise DesktopSchemaError("an approval reference cannot be empty")
        return replace(self, approval_reference=reference)

    def expired(self, monotonic_now: float) -> bool:
        return bool(self.expires_at_monotonic) and monotonic_now > self.expires_at_monotonic

    def past_deadline(self, monotonic_now: float) -> bool:
        return bool(self.deadline_monotonic) and monotonic_now > self.deadline_monotonic

    @classmethod
    def build(
        cls,
        action: NormalisedAction,
        *,
        request_id: str,
        session_id: str,
        task_id: str,
        lifecycle_epoch: int,
        plan_id: str,
        operation_id: str,
        cancellation_token: str,
        wall_now: float,
        monotonic_now: float,
        approval_ttl_seconds: float,
        deadline_seconds: float = MAX_DEADLINE_SECONDS,
        audit_reference: str = "",
        undo_of: str = "",
    ) -> "DesktopActionRequest":
        """Assemble a request from a normalised action and the authority facts.

        The idempotency key is derived here, from the *normalised* parameters,
        which is the only point at which they are guaranteed to be the ones that
        will execute. Deriving it from the proposal instead would give two keys
        for one act whenever normalisation changed anything — and normalisation
        changes something on nearly every action.
        """
        descriptor = descriptor_for(action.action_id)
        deadline = min(max(1.0, float(deadline_seconds)), MAX_DEADLINE_SECONDS)
        expires_at = monotonic_now + max(0.0, float(approval_ttl_seconds))
        return cls(
            schema_version=DESKTOP_ACTION_SCHEMA_VERSION,
            request_id=request_id,
            session_id=session_id,
            task_id=task_id,
            lifecycle_epoch=int(lifecycle_epoch),
            plan_id=plan_id,
            operation_id=operation_id,
            idempotency_key=action_key(
                task_id=task_id,
                lifecycle_epoch=lifecycle_epoch,
                plan_id=plan_id,
                operation_id=operation_id,
                action_id=action.action_id,
                parameters=action.parameters,
            ),
            action_id=action.action_id,
            parameters=dict(action.parameters),
            expected_effect=action.expected_effect,
            target=action.target,
            target_kind=action.target_kind,
            classification=action.classification,
            approval_class=descriptor.approval_class,
            approval_reference="",
            created_at=iso8601(wall_now),
            expires_at_monotonic=expires_at,
            deadline_monotonic=min(monotonic_now + deadline, expires_at),
            cancellation_token=cancellation_token,
            reversibility=descriptor.reversibility,
            undo_action_id=descriptor.undo_action_id,
            presentation=action.presentation,
            disclosure=action.disclosure,
            audit_reference=audit_reference,
            undo_of=undo_of,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "lifecycleEpoch": self.lifecycle_epoch,
            "planId": self.plan_id,
            "operationId": self.operation_id,
            "idempotencyKey": self.idempotency_key,
            "actionId": self.action_id,
            "parameters": dict(self.parameters),
            "expectedEffect": self.expected_effect,
            "target": self.target,
            "targetKind": self.target_kind,
            "classification": self.classification,
            "approvalClass": self.approval_class,
            "approvalReference": self.approval_reference,
            "createdAt": self.created_at,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "deadlineMonotonic": self.deadline_monotonic,
            "cancellationToken": self.cancellation_token,
            "reversibility": self.reversibility,
            "undoActionId": self.undo_action_id,
            "presentation": self.presentation,
            "disclosure": self.disclosure,
            "auditReference": self.audit_reference,
            "undoOf": self.undo_of,
            "bindingDigest": self.binding.digest,
        }

    def to_record_json(self) -> dict[str, Any]:
        """The request as a durable record and a log line may hold it (§13).

        The parameters are replaced by the binding digest. A clipboard write's
        parameters are the text; a URI open's are the address with its query.
        Neither belongs in a file that outlives the action, and the digest is
        what the comparisons actually need.
        """
        value = self.to_json()
        value.pop("parameters", None)
        return value

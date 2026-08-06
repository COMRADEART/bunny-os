# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What consent was given to, in one comparable object.

An approval for a desktop action is consent to a **specific act**, and §8 is a
list of the ways an act can stop being that one. This module holds the fourteen
facts an approval is granted against and the comparison that notices when any of
them moved.

The comparison is field-by-field and not digest-only, and that is a deliberate
cost. A digest answers "is this the same act?" and nothing else; when the answer
is no, a user is owed the sentence "the address changed" rather than "the
approval no longer matches". :meth:`ApprovalBinding.differences` produces those
sentences, and the digest is kept beside them for the cases where only equality
matters — the durable record, the replay check, the event payload.

Two of §8's rejection conditions are not fields and are checked by the caller
with facts this object cannot see: an approval that has been **replayed**, and
an action that has **already completed**. They live in
:class:`companion.desktop.broker.DesktopActionBroker` and
:mod:`companion.desktop.ledger` respectively, and :func:`reject_reasons` names
them so a reader of this module finds out they exist rather than assuming the
list here is the whole of §8.

The privacy rule is one-directional and worth stating plainly: an approval
survives the classification going *down* and never up. A user who agreed to
disclose internal text has not agreed to disclose personal text; a user who
agreed to disclose personal text has, in substance, agreed to the lesser
disclosure. Encoding that asymmetry is what stops a reclassification being a
consent bypass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from capability.apply.identity import canonical_json, digest

from ..privacy import DATA_CLASSES, rank
from .errors import DesktopApprovalMismatch

__all__ = [
    "ApprovalBinding",
    "BINDING_FIELDS",
    "reject_reasons",
]

#: The fields an approval is granted against, in the order §8 lists them. Named
#: as data so the structural test can assert the object carries all of them
#: rather than checking that a docstring mentions them.
BINDING_FIELDS = (
    "taskId",
    "lifecycleEpoch",
    "planId",
    "operationId",
    "actionId",
    "target",
    "parameters",
    "classification",
    "expectedEffect",
    "reversibility",
    "undoActionId",
    "expiresAtMonotonic",
    "destination",
    "disclosure",
)


def reject_reasons() -> tuple[str, ...]:
    """Every §8 condition, including the two this module does not check itself.

    Returned as data so the report and the tests enumerate the same list, and so
    that a condition added to §8 without an implementation shows up as a name
    with nothing asserting it.
    """
    return (
        "target-changed",
        "uri-changed",
        "path-changed",
        "clipboard-digest-changed",
        "volume-changed",
        "action-type-changed",
        "new-parameter",
        "classification-increased",
        "plan-superseded",
        "lifecycle-epoch-changed",
        # Checked by the broker against its consumed set.
        "approval-replayed",
        # Checked by the ledger.
        "already-completed",
    )


@dataclass(frozen=True)
class ApprovalBinding:
    """The act an approval is for.

    ``destination`` is separate from ``target`` because they answer different
    questions for different actions. For a URI open they are the same string;
    for a launch that opens files, the target is the application and the
    destination is where the files go — which is the same application, said in
    the vocabulary the approval prompt uses. Keeping both means the prompt and
    the check read the same fields.
    """

    task_id: str
    lifecycle_epoch: int
    plan_id: str
    operation_id: str
    action_id: str
    target: str
    parameters: Mapping[str, Any]
    classification: str
    expected_effect: str
    reversibility: str
    undo_action_id: str = ""
    expires_at_monotonic: float = 0.0
    destination: str = "local"
    disclosure: str = "nothing"

    def __post_init__(self) -> None:
        if self.classification not in DATA_CLASSES:
            raise DesktopApprovalMismatch(f"unknown classification {self.classification!r}")

    @property
    def material(self) -> dict[str, Any]:
        """Exactly the fields, in a form two runs produce identically.

        The expiry is *not* in here. It is a property of the question rather
        than of the act, it is measured on a monotonic clock that does not
        survive a restart, and including it would make every binding unequal to
        itself a second later.
        """
        return {
            "taskId": self.task_id,
            "lifecycleEpoch": int(self.lifecycle_epoch),
            "planId": self.plan_id,
            "operationId": self.operation_id,
            "actionId": self.action_id,
            "target": self.target,
            "parameters": dict(self.parameters),
            "classification": self.classification,
            "expectedEffect": self.expected_effect,
            "reversibility": self.reversibility,
            "undoActionId": self.undo_action_id,
            "destination": self.destination,
            "disclosure": self.disclosure,
        }

    @property
    def digest(self) -> str:
        return digest(self.material)

    @property
    def canonical(self) -> str:
        return canonical_json(self.material)

    def differences(self, other: "ApprovalBinding") -> tuple[str, ...]:
        """Every way ``other`` is not the act ``self`` was approved for.

        ``self`` is what was approved and ``other`` is what is about to happen.
        The direction matters for the classification check and for nothing else,
        which is why it is stated rather than left to the caller's memory.
        """
        reasons: list[str] = []
        if self.action_id != other.action_id:
            reasons.append(
                f"the action changed from {self.action_id} to {other.action_id}"
            )
        if self.task_id != other.task_id:
            reasons.append("the approval belongs to a different task")
        if int(self.lifecycle_epoch) != int(other.lifecycle_epoch):
            reasons.append(
                f"the task was paused and resumed since this was approved "
                f"(attempt {self.lifecycle_epoch} became {other.lifecycle_epoch})"
            )
        if self.plan_id != other.plan_id:
            reasons.append(f"the plan changed from {self.plan_id} to {other.plan_id}")
        if self.operation_id != other.operation_id:
            reasons.append("the approval was granted for a different step of the plan")
        if self.target != other.target:
            reasons.append(_target_sentence(self.action_id, self.target, other.target))
        if self.destination != other.destination:
            reasons.append(
                f"the destination changed from {self.destination!r} to {other.destination!r}"
            )

        mine = dict(self.parameters)
        theirs = dict(other.parameters)
        appeared = sorted(set(theirs) - set(mine))
        vanished = sorted(set(mine) - set(theirs))
        if appeared:
            reasons.append(
                f"a parameter that was not approved appeared: {', '.join(appeared)}"
            )
        if vanished:
            reasons.append(f"an approved parameter is now absent: {', '.join(vanished)}")
        changed = sorted(
            name for name in set(mine) & set(theirs) if mine[name] != theirs[name]
        )
        for name in changed:
            reasons.append(_parameter_sentence(self.action_id, name, mine[name], theirs[name]))

        if rank(other.classification) > rank(self.classification):
            reasons.append(
                f"the data is now classified {other.classification} and was approved as "
                f"{self.classification}"
            )
        if self.reversibility != other.reversibility:
            reasons.append(
                f"the action was approved as {self.reversibility} and is now "
                f"{other.reversibility}"
            )
        if self.undo_action_id != other.undo_action_id:
            reasons.append("the undo available for this action changed")
        if self.expected_effect != other.expected_effect:
            reasons.append("what this action would visibly do has changed")
        if self.disclosure != other.disclosure:
            reasons.append(
                f"what would be disclosed changed from {self.disclosure!r} to "
                f"{other.disclosure!r}"
            )
        return tuple(reasons)

    def require_match(self, other: "ApprovalBinding") -> None:
        """Refuse unless ``other`` is exactly the approved act."""
        reasons = self.differences(other)
        if reasons:
            raise DesktopApprovalMismatch(
                "this is not the action that was approved: " + "; ".join(reasons)
            )

    def to_json(self) -> dict[str, Any]:
        value = self.material
        value["expiresAtMonotonic"] = self.expires_at_monotonic
        value["digest"] = self.digest
        return value


def _target_sentence(action_id: str, before: str, after: str) -> str:
    """Name the change in the vocabulary of the action it happened to.

    "the address changed" and "the file changed" are the sentences §8's list is
    written in, and a user reading a refusal should see the one that applies to
    what they were looking at rather than the word "target".
    """
    if action_id == "desktop.uri.open":
        return f"the address changed from {before} to {after}"
    if action_id == "desktop.file.reveal":
        return "the file this points at changed after it was approved"
    if action_id == "desktop.clipboard.copy-text":
        return "the text to be copied changed after it was approved"
    if action_id in ("desktop.application.launch", "desktop.application.present"):
        return f"the application changed from {before} to {after}"
    if action_id == "desktop.audio.set-volume":
        return f"the audio output changed from {before} to {after}"
    if action_id == "desktop.settings.open":
        return f"the settings page changed from {before} to {after}"
    return f"the target changed from {before!r} to {after!r}"


def _parameter_sentence(action_id: str, name: str, before: Any, after: Any) -> str:
    if action_id == "desktop.audio.set-volume" and name == "percent":
        return f"the volume changed from {before}% to {after}% after it was approved"
    if action_id == "desktop.notifications.set-do-not-disturb" and name == "enabled":
        return "the do-not-disturb value changed after it was approved"
    if action_id == "desktop.clipboard.copy-text" and name == "text":
        # The values are never quoted. §13: the text does not reach a record,
        # and a refusal message is a record.
        return "the text to be copied changed after it was approved"
    return f"the {name} parameter changed after it was approved"

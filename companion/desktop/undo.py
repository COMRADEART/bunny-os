# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Taking something back, when that is a thing that can honestly be done.

§11 classifies actions four ways and the classification is on the descriptor.
What is here is the consequence: given a *recorded* attempt, what — if anything —
would undo it, and what would that cost.

Three shapes, and the distinctions are the substance:

``reverse``
    a new action of the same type that restores the value that was there. Only
    possible when the previous value was **read before the change** and written
    into the ledger. An action declared reversible whose previous state could
    not be read offers no undo, because the alternative is a button that either
    fails or guesses.
``compensate``
    an operation that offsets the effect without restoring the previous state.
    Releasing clipboard ownership is the only one in this phase. It is not a
    reversal and is not described as one: whatever was on the clipboard before
    is gone, nobody read it, and nobody can put it back.
``none``
    nothing honest is available. A delivered notification, a started
    application, an opened URI, an opened settings page. §11 is explicit about
    the tempting wrong answer — *do not silently kill an application as "undo
    launch"* — and the reason is that killing a program a user has since typed
    into is a larger harm than the launch was.

**An undo is a new action with its own approval.** It gets a new request, a new
idempotency key, a new entry in the ledger and its own place in the audit trail.
The original moves to ``undone`` rather than back to un-attempted, because it
did happen. Two records, joined by
:meth:`companion.desktop.ledger.OperationLedger.link_undo`.

The one exception is compensation, and it is deliberate: releasing the clipboard
*reduces* what has been disclosed. Requiring a person to approve the withdrawal
of a disclosure they already approved would mean a cancelled task keeps holding
their clipboard until somebody clicks something, which is worse for them in
every direction. It is still recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .catalogue import descriptor_for
from .errors import DesktopRefused
from .ledger import LedgerEntry

__all__ = ["UNDO_KINDS", "UndoPlan", "undo_plan_for"]

#: What kind of taking-back is on offer.
UNDO_KINDS = ("reverse", "compensate", "none")


@dataclass(frozen=True)
class UndoPlan:
    """What would undo one recorded attempt, and what to tell the user.

    ``requires_approval`` is ``True`` for every reversal. An undo is an act on
    the user's desktop like any other, and "it puts things back" is a claim they
    are entitled to check before it happens — particularly since a reversal
    happens some time after the thing it reverses, when the desk may have moved
    on.
    """

    kind: str
    action_id: str = ""
    parameters: Mapping[str, Any] | None = None
    presentation: str = ""
    #: Why there is no undo, when there is none. Shown to the user.
    reason: str = ""
    requires_approval: bool = True

    @property
    def available(self) -> bool:
        return self.kind != "none"

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "available": self.available,
            "actionId": self.action_id,
            "parameters": dict(self.parameters or {}),
            "presentation": self.presentation,
            "reason": self.reason,
            "requiresApproval": self.requires_approval,
        }


def _none(reason: str) -> UndoPlan:
    return UndoPlan(kind="none", reason=reason, requires_approval=False)


def undo_plan_for(entry: LedgerEntry) -> UndoPlan:
    """What would take back ``entry``, given what the record actually holds.

    Reads the ledger entry rather than the live machine on purpose. An undo
    offered on the strength of a *current* reading would restore the value that
    is there now, which is not the same as the value that was there before —
    and after a restart it is the only value available, which is exactly when
    the difference matters.
    """
    if entry.state == "undone":
        return _none("this action has already been undone")
    if entry.state in ("not-started", "cancelled"):
        return _none("this action did not happen, so there is nothing to take back")
    if entry.state == "failed":
        return _none("this action failed, so there is nothing to take back")
    if entry.state == "unknown":
        # The load-bearing refusal, and the one most likely to be argued with.
        # Undoing an act that may not have happened is itself an act: setting a
        # volume "back" to a value it may never have left is a change the user
        # did not ask for.
        return _none(
            "whether this action happened is not known, so undoing it could change something "
            "that was never changed; a new decision is needed rather than an undo"
        )

    descriptor = descriptor_for(entry.action_id)

    if entry.action_id == "desktop.audio.set-volume":
        previous = entry.previous_state
        percent = previous.get("percent")
        if not isinstance(percent, int):
            return _none(
                "the volume before this change was not readable, so there is no value to "
                "restore; guessing one would be a change of its own"
            )
        parameters: dict[str, Any] = {
            "percent": percent,
            "outputId": str(previous.get("outputId", "")) or entry.target,
        }
        if isinstance(previous.get("muted"), bool):
            parameters["muted"] = previous["muted"]
        return UndoPlan(
            kind="reverse",
            action_id="desktop.audio.set-volume",
            parameters=parameters,
            presentation=f"Set the volume back to {percent}%",
        )

    if entry.action_id == "desktop.notifications.set-do-not-disturb":
        previous = entry.previous_state.get("enabled")
        if not isinstance(previous, bool):
            return _none(
                "the do-not-disturb value before this change was not readable, so there is no "
                "value to restore"
            )
        return UndoPlan(
            kind="reverse",
            action_id="desktop.notifications.set-do-not-disturb",
            parameters={"enabled": previous},
            presentation=(
                "Turn do-not-disturb back on" if previous else "Turn do-not-disturb back off"
            ),
        )

    if entry.action_id == "desktop.clipboard.copy-text":
        return UndoPlan(
            kind="compensate",
            action_id="desktop.clipboard.copy-text",
            parameters={},
            presentation="Release the clipboard",
            reason=(
                "Releasing the clipboard stops this text being available to paste. It does not "
                "restore what was on the clipboard before — that was never read, so it cannot "
                "be put back."
            ),
            # A withdrawal of a disclosure the user already approved. Asking
            # them to approve *stopping* it would leave a cancelled task holding
            # their clipboard until they clicked something.
            requires_approval=False,
        )

    if entry.action_id == "desktop.application.launch":
        return _none(
            "an application that was started stays started. Closing it is not an undo — it is a "
            "separate act that could discard work you have done since."
        )
    if entry.action_id == "desktop.notification.show":
        return _none(
            "a notification that has been delivered cannot be un-shown. It may already have been "
            "read."
        )
    if entry.action_id == "desktop.uri.open":
        return _none("an address that has been opened cannot be un-opened.")
    if entry.action_id == "desktop.settings.open":
        return _none("a settings page that has been opened cannot be un-opened. You can close it.")
    if entry.action_id == "desktop.application.present":
        return _none("a window that came forward cannot be put back where it was.")
    if entry.action_id == "desktop.file.reveal":
        return _none("a file manager window that opened cannot be un-opened. You can close it.")

    # Unreachable while the catalogue and this function agree; kept because
    # "unreachable" is not a property, and the failure mode of falling through
    # would be an undo silently offered for an action nobody classified.
    if descriptor.reversibility == "irreversible":
        return _none(f"{descriptor.summary.lower()} cannot be undone")
    raise DesktopRefused(
        f"{entry.action_id} is declared {descriptor.reversibility} and this build has no undo "
        "for it; the classification and the implementation disagree"
    )

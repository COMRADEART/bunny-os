# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What makes an act *that* act, and what may be done about doing it twice.

The key is derived, never minted. :func:`action_key` digests the six facts §9
names — task, lifecycle epoch, plan, operation, action type, normalised
parameters — so that after a restart the same act produces the same key and the
ledger can answer "has this already happened?" with something other than a
guess. A random identifier regenerated on restart makes every recovered action
look new, and "looks new" is how a machine opens the same link twice.

**The plan revision is deliberately absent, and the lifecycle epoch is
deliberately present.** :func:`companion.ids.operation_key` records why the
first is left out: with a revision in the key, every replan produces fresh keys,
nothing ever matches a completed one, and the skip branch is unreachable while
the ledger beside it claims work will not be repeated. The epoch is different in
kind. A task that was paused and resumed is being attempted *again*, deliberately,
by a person who watched the first attempt not finish — and an act performed
under the previous attempt must not silently satisfy the current one.

**Retry semantics are per-action and are written down.** §9 asks for this
explicitly, and the reason is that the right answer genuinely differs:

======================================  =========================================
action                                  what may be done with an uncertain attempt
======================================  =========================================
``desktop.notification.show``           suppress: a duplicate notification is
                                        noise, and the cost of not sending one
                                        is lower than the cost of two.
``desktop.application.launch``          reconcile: activation state is
                                        observable, so an attempt whose outcome
                                        is unknown can be *checked* rather than
                                        repeated.
``desktop.application.present``         reconcile, and cheap either way.
``desktop.settings.open``               reconcile; repeating opens a second
                                        window of a page, which is untidy and
                                        not harmful.
``desktop.audio.set-volume``            reconcile: the current volume can be
                                        read, so "did it happen" is answerable
                                        exactly.
``desktop.notifications.set-do-not-disturb``  reconcile, for the same reason.
``desktop.clipboard.copy-text``         repeat only under explicit policy:
                                        writing the same text twice is harmless,
                                        writing it after the user has copied
                                        something else is not.
``desktop.uri.open``                    never: §9 says so in as many words. Two
                                        browser tabs is the harmless case; two
                                        of anything a URI can trigger is not.
``desktop.file.reveal``                 reconcile; a second file-manager window
                                        is untidy and not harmful.
======================================  =========================================

None of these is a licence to retry *automatically*. :data:`RETRY_POLICIES` says
what a **user** may be offered, and the broker never acts on one by itself: §20
requires a new decision for an uncertain action, and the policy is what shapes
the question rather than what answers it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .catalogue import ACTION_IDS
from .errors import DesktopSchemaError

__all__ = [
    "OPERATION_STATES",
    "RETRY_POLICIES",
    "RetryPolicy",
    "action_key",
    "retry_policy_for",
    "settled",
]

#: §9's seven. ``unknown`` is the load-bearing one, and ``undone`` is separate
#: from ``completed`` because an undone action *did* happen — the record must
#: not read as though it never did.
OPERATION_STATES = (
    "not-started",
    "started",
    "completed",
    "failed",
    "cancelled",
    "unknown",
    "undone",
)

#: States after which no further attempt is made under the same key.
_SETTLED = frozenset({"completed", "failed", "cancelled", "undone"})


def settled(state: str) -> bool:
    if state not in OPERATION_STATES:
        raise DesktopSchemaError(f"{state!r} is not an operation state")
    return state in _SETTLED


@dataclass(frozen=True)
class RetryPolicy:
    """What may be *offered* about an act whose outcome is not known.

    ``duplicate_is_safe`` and ``reconcilable`` are not the same claim.
    A notification is safe to send twice and cannot be checked; a volume change
    is unsafe to guess at and can be checked exactly. Reading them as one field
    would give the wrong answer for both.
    """

    action_id: str
    #: Whether performing it a second time is harmless.
    duplicate_is_safe: bool
    #: Whether the machine can be asked what the state now is, so that an
    #: uncertain attempt can be settled by observation rather than by repetition.
    reconcilable: bool
    #: The sentence the user is shown when an attempt's outcome is unknown.
    explanation: str

    @property
    def may_offer_repeat(self) -> bool:
        """Whether repeating may be offered as a choice. Never taken silently."""
        return self.duplicate_is_safe

    def to_json(self) -> dict[str, Any]:
        return {
            "actionId": self.action_id,
            "duplicateIsSafe": self.duplicate_is_safe,
            "reconcilable": self.reconcilable,
            "mayOfferRepeat": self.may_offer_repeat,
            "explanation": self.explanation,
        }


RETRY_POLICIES: Mapping[str, RetryPolicy] = {
    item.action_id: item
    for item in (
        RetryPolicy(
            "desktop.notification.show",
            duplicate_is_safe=True,
            reconcilable=False,
            explanation=(
                "Whether the notification was delivered is not known. Nothing can be read "
                "back to find out; sending it again would at worst show it twice."
            ),
        ),
        RetryPolicy(
            "desktop.application.launch",
            duplicate_is_safe=False,
            reconcilable=True,
            explanation=(
                "Whether the application started is not known. Whether it is running now "
                "can be checked, so this is settled by looking rather than by launching again."
            ),
        ),
        RetryPolicy(
            "desktop.application.present",
            duplicate_is_safe=True,
            reconcilable=True,
            explanation="Whether the window was raised is not known. Asking again is harmless.",
        ),
        RetryPolicy(
            "desktop.settings.open",
            duplicate_is_safe=True,
            reconcilable=True,
            explanation=(
                "Whether the settings page opened is not known. Opening it again would at "
                "worst show a second window."
            ),
        ),
        RetryPolicy(
            "desktop.audio.set-volume",
            duplicate_is_safe=False,
            reconcilable=True,
            explanation=(
                "Whether the volume changed is not known. The current volume can be read, "
                "so this is settled by reading it rather than by setting it again."
            ),
        ),
        RetryPolicy(
            "desktop.notifications.set-do-not-disturb",
            duplicate_is_safe=False,
            reconcilable=True,
            explanation=(
                "Whether the setting changed is not known. Its current value can be read, "
                "so this is settled by reading it."
            ),
        ),
        RetryPolicy(
            "desktop.clipboard.copy-text",
            duplicate_is_safe=False,
            reconcilable=True,
            explanation=(
                "Whether the clipboard was taken is not known. Ownership can be checked; the "
                "contents are never read. Copying again may overwrite something you have "
                "since copied yourself, so it is offered rather than done."
            ),
        ),
        RetryPolicy(
            "desktop.uri.open",
            duplicate_is_safe=False,
            reconcilable=False,
            explanation=(
                "Whether the address was opened is not known, and nothing can be read back "
                "to find out. Opening a URI is not repeated after an uncertain attempt."
            ),
        ),
        RetryPolicy(
            "desktop.file.reveal",
            duplicate_is_safe=True,
            reconcilable=True,
            explanation=(
                "Whether the file manager opened is not known. Revealing again would at "
                "worst show a second window."
            ),
        ),
    )
}


def retry_policy_for(action_id: str) -> RetryPolicy:
    policy = RETRY_POLICIES.get(action_id)
    if policy is None:
        raise DesktopSchemaError(f"{action_id!r} has no declared retry policy")
    return policy


def action_key(
    *,
    task_id: str,
    lifecycle_epoch: int,
    plan_id: str,
    operation_id: str,
    action_id: str,
    parameters: Mapping[str, Any],
) -> str:
    """The idempotency key for one desktop action.

    Encoded as canonical JSON of the whole tuple rather than joined with a
    separator. :func:`companion.ids.operation_key` records what went wrong with
    the separator form: three of its fields were free strings, and shifting the
    separator across a field boundary produced identical material for two
    genuinely different acts — so one could be deduplicated away against the
    other and never performed, while the record said it "was not repeated". A
    JSON encoder escapes the separator inside a value, so the encoding of the
    fields determines the fields.
    """
    from capability.apply.identity import canonical_json

    material = canonical_json([
        "bunny-desktop-action/1",
        task_id,
        int(lifecycle_epoch),
        plan_id,
        operation_id,
        action_id,
        dict(parameters),
    ])
    return "dact-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _check_policies() -> None:
    missing = [item for item in ACTION_IDS if item not in RETRY_POLICIES]
    if missing:
        raise DesktopSchemaError(
            f"{missing} are declared actions with no retry policy; §9 requires the semantics "
            "of an uncertain attempt to be written down for every action"
        )


_check_policies()

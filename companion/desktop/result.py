# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What happened, and how much of that is actually known.

§12's seven words exist because a backend acknowledging a request is not a desk
that changed, and a companion that reports the first as the second teaches a
person to stop checking. The distinction is enforced rather than encouraged:
:class:`DesktopActionResult` refuses to be constructed as ``confirmed`` without
an :class:`Observation` that says it verified something.

    confirmed
        something was read back and matched what was asked for. Only three
        actions can reach this: a volume, a do-not-disturb value, and clipboard
        ownership. Everything else in this catalogue has no read-back, and
        saying so is more useful than a word that implies one.
    accepted-not-confirmed
        the backend took the request and returned success. This is the honest
        state for a notification, a launch, a URI open and a reveal, and it is
        the *normal* outcome for them rather than a degraded one.
    refused
        the broker declined. Always a policy decision, always recorded, and
        never a backend failure wearing a policy word.
    failed
        the backend was reached and did not do it.
    cancelled
        a stop arrived. Carries whether the effect is known to have been
        prevented, because §10 forbids claiming a rollback nobody verified.
    unknown
        it was begun and nothing settled it. §20 forbids repeating one of these
        automatically.
    unsupported
        this environment cannot do it. Distinguished from ``failed`` because the
        remedy is different and a user is owed the difference.

**Nothing here holds the data an action carried.** No clipboard text, no URI
query, no path, no notification body. §13 permits an action id, digests,
bounded target metadata, a result and a timing, and this object is exactly that
list — so a result can be written into an event, a log and a protocol reply
without three separate redaction passes that could each forget something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .errors import DesktopSchemaError

__all__ = [
    "CONFIDENT_STATES",
    "OBSERVATION_KINDS",
    "RESULT_STATES",
    "TERMINAL_RESULT_STATES",
    "DesktopActionResult",
    "Observation",
]

RESULT_STATES = (
    "confirmed",
    "accepted-not-confirmed",
    "refused",
    "failed",
    "cancelled",
    "unknown",
    "unsupported",
)

#: The one state that asserts the desk changed. Kept as a set of one so that a
#: second verifiable outcome added later has an obvious place to go, and so the
#: check below reads as a rule rather than as a special case.
CONFIDENT_STATES = frozenset({"confirmed"})

#: States after which nothing further will be attempted under this key.
TERMINAL_RESULT_STATES = frozenset({
    "confirmed", "accepted-not-confirmed", "refused", "failed", "cancelled", "unsupported",
})

#: What an observation can be *of*. Closed, because "we observed something"
#: with no vocabulary for what is how an acknowledgement becomes a confirmation
#: in a later reading of the record.
OBSERVATION_KINDS = (
    # The backend returned success. Proves acceptance and nothing more.
    "acknowledgement",
    # A value was read back from the machine and compared. This is the only kind
    # that may justify `confirmed`.
    "read-back",
    # A resource was acquired and its ownership checked.
    "ownership",
    # The backend reported a failure.
    "error",
    # Nothing could be observed, and the record says so rather than omitting it.
    "none",
)

#: Kinds that can justify a confident result.
_VERIFYING = frozenset({"read-back", "ownership"})


@dataclass(frozen=True)
class Observation:
    """One thing the broker actually looked at.

    ``matched`` is tri-state through ``None``: an acknowledgement matches
    nothing because it compares nothing, and recording it as ``False`` would
    read as a mismatch. That distinction is the difference between "we did not
    check" and "we checked and it was wrong".
    """

    kind: str
    #: What was looked at, in words. Never the value if the value is user data.
    detail: str = ""
    matched: bool | None = None
    #: The value read back, when it is not user content. A volume percentage is
    #: safe to record; a clipboard's contents would not be, and are never read.
    observed_value: Any = None

    def __post_init__(self) -> None:
        if self.kind not in OBSERVATION_KINDS:
            raise DesktopSchemaError(
                f"{self.kind!r} is not an observation kind; expected one of {list(OBSERVATION_KINDS)}"
            )

    @property
    def verifies(self) -> bool:
        """Whether this observation can justify a ``confirmed`` result."""
        return self.kind in _VERIFYING and self.matched is True

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "matched": self.matched,
            "observedValue": self.observed_value,
            "verifies": self.verifies,
        }


@dataclass(frozen=True)
class DesktopActionResult:
    """The outcome of one attempt, sanitized by construction.

    ``undo_available`` is computed by the broker rather than copied from the
    descriptor, and the difference matters: an action *declared* reversible whose
    previous state could not be read has no undo in practice, and offering one
    would produce a button that fails when pressed.
    """

    request_id: str
    action_id: str
    idempotency_key: str
    state: str
    #: The observation the state rests on. Always present, including when it is
    #: the ``none`` kind, so that "nothing was observed" is a recorded fact.
    observation: Observation = field(default_factory=lambda: Observation("none"))
    #: A sentence for a person. Bounded, and never carrying action data.
    explanation: str = ""
    #: Bounded target metadata: which application, which page, which digest.
    #: §13's permitted list, and nothing outside it.
    target: str = ""
    target_kind: str = "none"
    #: Whether an undo is genuinely offerable now.
    undo_available: bool = False
    undo_action_id: str = ""
    #: What would have to be restored, when it was read. Never user content.
    previous_state: Mapping[str, Any] = field(default_factory=dict)
    #: §10: whether a cancellation is known to have prevented the effect.
    effect_prevented: bool | None = None
    duration_seconds: float = 0.0
    #: Secondary observations — a read-back that disagreed, a fallback that was
    #: not taken. Bounded so a result cannot grow without limit.
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in RESULT_STATES:
            raise DesktopSchemaError(
                f"{self.state!r} is not a result state; expected one of {list(RESULT_STATES)}"
            )
        if self.state in CONFIDENT_STATES and not self.observation.verifies:
            # The rule the whole module exists for. A `confirmed` with an
            # acknowledgement behind it is the lie §12 forbids, and it is
            # refused at construction so no code path can produce one.
            raise DesktopSchemaError(
                f"{self.action_id} reported {self.state!r} with a "
                f"{self.observation.kind!r} observation; a confident result requires an "
                "observation that verified something, and an acknowledgement verifies nothing"
            )
        if self.state != "cancelled" and self.effect_prevented is not None:
            raise DesktopSchemaError(
                "effectPrevented describes a cancellation and was set on a "
                f"{self.state!r} result"
            )
        if len(self.notes) > 8:
            raise DesktopSchemaError("a result carries at most eight notes")

    @property
    def settled(self) -> bool:
        return self.state in TERMINAL_RESULT_STATES

    @property
    def succeeded(self) -> bool:
        """Whether the act is believed to have happened.

        ``accepted-not-confirmed`` counts, because refusing to call it a success
        would leave a notification permanently reading as a failure. What it
        does not do is claim confirmation, and
        :attr:`confidence` is where that difference is available to a caller.
        """
        return self.state in ("confirmed", "accepted-not-confirmed")

    @property
    def confidence(self) -> str:
        """``verified``, ``reported``, or ``none``. What §18 displays."""
        if self.state == "confirmed":
            return "verified"
        if self.state == "accepted-not-confirmed":
            return "reported"
        return "none"

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "actionId": self.action_id,
            "idempotencyKey": self.idempotency_key,
            "state": self.state,
            "confidence": self.confidence,
            "succeeded": self.succeeded,
            "settled": self.settled,
            "observation": self.observation.to_json(),
            "explanation": self.explanation,
            "target": self.target,
            "targetKind": self.target_kind,
            "undoAvailable": self.undo_available,
            "undoActionId": self.undo_action_id,
            "previousState": dict(self.previous_state),
            "effectPrevented": self.effect_prevented,
            "durationSeconds": round(self.duration_seconds, 6),
            "notes": list(self.notes),
        }

    def to_tool_json(self) -> dict[str, Any]:
        """The result as a **provider** may see it (§15).

        Narrower than :meth:`to_json`. A provider is told what happened and how
        confident that is; it is not told the previous state, the idempotency
        key or the observation's internals, because none of those help it
        propose the next operation and all of them are facts about the machine
        rather than about the task.
        """
        return {
            "actionId": self.action_id,
            "state": self.state,
            "confidence": self.confidence,
            "succeeded": self.succeeded,
            "explanation": self.explanation,
            "undoAvailable": self.undo_available,
        }


def unsupported(
    *,
    request_id: str,
    action_id: str,
    idempotency_key: str = "",
    explanation: str,
    target: str = "",
    target_kind: str = "none",
) -> DesktopActionResult:
    """The typed absence §5 asks for, rather than a placeholder implementation."""
    return DesktopActionResult(
        request_id=request_id,
        action_id=action_id,
        idempotency_key=idempotency_key,
        state="unsupported",
        observation=Observation("none", detail="the action was not attempted"),
        explanation=explanation,
        target=target,
        target_kind=target_kind,
    )


def refused(
    *,
    request_id: str,
    action_id: str,
    idempotency_key: str = "",
    explanation: str,
    target: str = "",
    target_kind: str = "none",
    notes: Sequence[str] = (),
) -> DesktopActionResult:
    return DesktopActionResult(
        request_id=request_id,
        action_id=action_id,
        idempotency_key=idempotency_key,
        state="refused",
        observation=Observation("none", detail="the action was not attempted"),
        explanation=explanation,
        target=target,
        target_kind=target_kind,
        notes=tuple(notes)[:8],
    )

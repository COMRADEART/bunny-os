# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way a desktop action is refused, named separately.

The distinctions here are not taxonomy for its own sake. Each one leads to a
different sentence in front of a user and a different decision by the caller:

``DesktopUnavailable``
    the environment cannot do this at all — headless, no portal, no audio
    session. The honest answer is "not here", and §17 requires it be given
    rather than worked around with a hidden fallback.
``DesktopUnsupported``
    the environment exists and this *particular* thing is not possible in it —
    Wayland preventing focus control is the canonical case. Distinguished from
    unavailable because the answer is "this compositor will not", not "there is
    no desktop".
``DesktopRefused``
    the request was well-formed and the broker declined it: a scheme that is
    not allowlisted, a path outside the approved roots, a desktop entry that
    resolves somewhere it should not. This is the security refusal and it is
    always recorded.
``DesktopApprovalMismatch``
    the act changed after consent was given. Separate from a plain refusal
    because the remedy is to ask again, not to give up.
``DesktopAlreadyPerformed`` / ``DesktopEffectUnknown``
    §9's two halves of "do not do it twice". The first is a fact; the second is
    the absence of one, and the absence is the more important of the two —
    §20 forbids repeating it automatically.
``DesktopCancelled``
    a stop arrived. Carries whether a side effect is known to have happened, so
    the caller records the truth instead of assuming rollback.

Every class derives from :class:`companion.errors.CompanionError`, so a caller
that only wants "the runtime declined and said why" keeps working.
"""

from __future__ import annotations

from ..errors import CompanionError

__all__ = [
    "DesktopActionError",
    "DesktopAlreadyPerformed",
    "DesktopApprovalMismatch",
    "DesktopCancelled",
    "DesktopEffectUnknown",
    "DesktopRefused",
    "DesktopSchemaError",
    "DesktopUnavailable",
    "DesktopUnsupported",
]


class DesktopActionError(CompanionError):
    """A desktop action could not be performed, and the broker can say why."""

    #: The :data:`companion.desktop.result.RESULT_STATES` value this becomes.
    result_state = "failed"


class DesktopSchemaError(DesktopActionError):
    """A request does not match the schema of the action it names.

    Raised before anything is shown to a user, so a malformed proposal never
    reaches an approval prompt. A prompt built from an unvalidated request would
    describe an act that could not be performed as described.
    """

    result_state = "refused"


class DesktopRefused(DesktopActionError):
    """The broker declined a well-formed request on policy grounds."""

    result_state = "refused"


class DesktopApprovalMismatch(DesktopRefused):
    """The act is not the act that was approved.

    §8's whole list arrives here: a changed target, a changed URI, a changed
    path, a changed clipboard digest, a changed volume, a new parameter, a
    raised privacy class, a superseded plan, a different lifecycle epoch, a
    replayed approval, or an action that has already completed.
    """


class DesktopUnavailable(DesktopActionError):
    """This environment has no way to perform actions of this kind."""

    result_state = "unsupported"


class DesktopUnsupported(DesktopActionError):
    """The environment exists and cannot perform this particular action.

    The compositor that will not raise a window on request is the reason this is
    separate from :class:`DesktopUnavailable`: faking success there would be a
    lie about the user's own screen, and §4.3 forbids it explicitly.
    """

    result_state = "unsupported"


class DesktopAlreadyPerformed(DesktopActionError):
    """The ledger proves this exact act already completed.

    Not an error in the sense of something going wrong: it is the idempotency
    guarantee holding. The caller reports the recorded result rather than
    performing the act a second time.
    """

    result_state = "confirmed"

    def __init__(self, message: str, *, recorded: object = None) -> None:
        super().__init__(message)
        #: The :class:`companion.desktop.result.DesktopActionResult` the first
        #: attempt produced, so the caller returns what happened rather than a
        #: fresh claim about it.
        self.recorded = recorded


class DesktopEffectUnknown(DesktopActionError):
    """An act was begun and nothing settled it; whether it happened is unknown.

    The load-bearing refusal. §9 and §20 both forbid repeating one of these
    automatically, and the way that guarantee is kept is that the only thing
    which can clear an unknown is a *new user decision* or an observation that
    establishes the state.
    """

    result_state = "unknown"


class DesktopCancelled(DesktopActionError):
    """A stop arrived before or during the attempt.

    ``effect_known`` is the field that stops this becoming a lie. Cancellation
    before dispatch prevents the effect; cancellation after the backend
    acknowledged does not, and §10 requires the record say which happened rather
    than claiming a rollback nobody verified.
    """

    result_state = "cancelled"

    def __init__(
        self,
        message: str,
        *,
        effect_known: bool = False,
        effect_prevented: bool = True,
    ) -> None:
        super().__init__(message)
        self.effect_known = effect_known
        self.effect_prevented = effect_prevented

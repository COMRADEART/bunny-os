# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""When the companion stops drawing, and the states in which it never may.

§3 asks for "no unnecessary background rendering" and §12 makes the idle cost a
first-class requirement. Neither is satisfied by a low frame rate. A companion
looping a six-frame idle animation at 12 fps is still a process that wakes
twelve times a second forever, and on a laptop that is the difference between a
timer that lets the CPU reach a deep idle state and one that does not.

So the policy here is not "animate more slowly when idle". It is **stop**, and
then hold the frame until something happens. The ladder has three levels:

``ACTIVE``
    Draw at whatever cap the selector set. Every state that is telling the user
    something in motion is here.

``DROWSY``
    A reduced cap. The companion is idle but recently was not, so it keeps
    breathing — this is the window in which a person who is still watching sees
    a living character rather than one that froze the moment they stopped
    typing.

``QUIESCENT``
    No timer at all. The last frame stays on screen and the renderer is not
    called again until the state changes, the user interacts, or something
    external asks for a redraw.

The important half of this module is which states are **excluded**. A companion
that quiesced while waiting for permission would be a frozen dialog, and §15
names "a frozen companion" as the exact thing never to leave a user with. So
:data:`NEVER_QUIESCENT` is checked first and it contains every state in which
the user is owed either an answer or evidence of life.

Waking is not a level in the ladder. It is a *transition* — any state change at
all leaves quiescence immediately, which is why :meth:`QuiescencePolicy.evaluate`
takes the current state rather than being told to wake up. A wake that had to be
requested is a wake somebody can forget to request.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .mapper import CharacterState

__all__ = [
    "DEFAULT_POLICY",
    "NEVER_QUIESCENT",
    "QuiescenceDecision",
    "QuiescenceLevel",
    "QuiescencePolicy",
]


class QuiescenceLevel(str, Enum):
    ACTIVE = "active"
    DROWSY = "drowsy"
    QUIESCENT = "quiescent"


#: States in which the companion always keeps drawing, whatever the idle timer
#: says.
#:
#: Two different reasons are mixed here on purpose, because the *effect* is the
#: same and splitting them would let one half be forgotten:
#:
#: - the user is being asked for something and a still image reads as a hang
#:   (``waiting_for_approval``, ``waiting_for_user``, ``error``, ``blocked``,
#:   ``warning``);
#: - the companion is mid-utterance or mid-listen and freezing would drop the
#:   only feedback that the microphone or the speaker is live (``listening``,
#:   ``transcribing``, ``speaking``).
#:
#: ``sleeping`` is deliberately absent: it is the one state whose *whole meaning*
#: is that nothing is happening, and it quiesces fastest of all.
NEVER_QUIESCENT = frozenset({
    CharacterState.WAITING_FOR_APPROVAL,
    CharacterState.WAITING_FOR_USER,
    CharacterState.ERROR,
    CharacterState.BLOCKED,
    CharacterState.WARNING,
    CharacterState.LISTENING,
    CharacterState.TRANSCRIBING,
    CharacterState.SPEAKING,
})

#: States that are quiet enough to quiesce, and how long each waits first.
#:
#: Everything not listed is active work and never reaches the timer at all. The
#: numbers are seconds and they are short: the point of the drowsy window is to
#: cover the case where a person is still looking at the character, and a person
#: who has not interacted for eight seconds has usually looked away.
_SETTLE_SECONDS: Mapping[CharacterState, float] = {
    CharacterState.IDLE: 8.0,
    CharacterState.SUCCESS: 6.0,
    CharacterState.PAUSED: 4.0,
    CharacterState.CANCELLED: 4.0,
    CharacterState.DISCONNECTED: 4.0,
    CharacterState.UNAVAILABLE: 2.0,
    # Sleeping is the state that means "nothing is happening". It holds its
    # frame almost at once and never draws again until it is woken.
    CharacterState.SLEEPING: 0.5,
}


@dataclass(frozen=True)
class QuiescenceDecision:
    """What to do next, and the sentence explaining it.

    ``frame_rate_cap`` of ``0`` is the load-bearing value: it means *no timer*,
    not "as slow as possible". A caller that treats zero as a rate divides by it
    and gets an infinite interval, which is the same thing by accident; treating
    it as a signal to cancel the timer is the same thing on purpose, and only
    the second one lets the CPU idle.
    """

    level: QuiescenceLevel
    frame_rate_cap: int
    reason: str

    @property
    def draws(self) -> bool:
        return self.frame_rate_cap > 0

    def to_json(self) -> dict[str, object]:
        return {
            "level": self.level.value,
            "frameRateCap": self.frame_rate_cap,
            "draws": self.draws,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class QuiescencePolicy:
    """Thresholds, separated from the decision so a test can move them.

    ``drowsy_fps`` is 8 rather than something rounder because it is below the
    rate at which a looping idle animation reads as motion but above the rate at
    which it reads as a slideshow. It only ever applies for a few seconds.
    """

    drowsy_fps: int = 8
    #: How long after settling the drowsy window lasts before the timer stops.
    drowsy_seconds: float = 6.0
    #: Set false to keep a low-rate timer forever instead of stopping. Exists
    #: for the setting §10 calls "enable/disable idle animation" — a user who
    #: turns idle animation *off* gets a still character, which quiesces sooner
    #: rather than later, so this is not that setting's implementation. It is
    #: the escape hatch for a compositor that will not repaint without a timer.
    may_stop: bool = True

    def evaluate(
        self,
        state: CharacterState,
        *,
        seconds_in_state: float,
        active_cap: int,
        idle_animation: bool = True,
        loops: bool = True,
    ) -> QuiescenceDecision:
        """Decide the tick rate for a character that has held ``state``.

        ``loops`` is whether the animation currently playing repeats. A one-shot
        that has not finished must be allowed to finish — stopping the timer
        halfway through a success animation would leave the character frozen
        mid-gesture, which looks exactly like a crash. The caller passes the
        playing animation's own loop flag, so this is the renderer's fact rather
        than a guess made here.
        """
        cap = max(0, int(active_cap))
        if state in NEVER_QUIESCENT:
            return QuiescenceDecision(
                QuiescenceLevel.ACTIVE, cap or 1,
                f"{state.value} always keeps drawing; the user is owed visible feedback",
            )
        settle = _SETTLE_SECONDS.get(state)
        if settle is None:
            return QuiescenceDecision(
                QuiescenceLevel.ACTIVE, cap,
                f"{state.value} is active work and does not idle",
            )
        if not idle_animation:
            # The user turned idle animation off. There is nothing to advance,
            # so the timer stops as soon as the current animation is not mid
            # one-shot, rather than after the settle window.
            if loops or seconds_in_state >= settle:
                return self._stopped(
                    "idle animation is turned off, so the character holds its frame"
                )
        if seconds_in_state < settle:
            return QuiescenceDecision(
                QuiescenceLevel.ACTIVE, cap,
                f"{state.value} has held for {seconds_in_state:.1f}s of its {settle:.1f}s settle window",
            )
        if not loops:
            # A one-shot still running. Let it land.
            return QuiescenceDecision(
                QuiescenceLevel.ACTIVE, cap,
                "a one-shot animation is still playing and is allowed to finish",
            )
        if seconds_in_state < settle + self.drowsy_seconds:
            return QuiescenceDecision(
                QuiescenceLevel.DROWSY, min(cap, self.drowsy_fps) or 1,
                f"{state.value} settled; animation continues at a reduced rate",
            )
        return self._stopped(
            f"{state.value} has been still for {seconds_in_state:.1f}s; the frame is held and no timer runs"
        )

    def _stopped(self, reason: str) -> QuiescenceDecision:
        if not self.may_stop:
            return QuiescenceDecision(QuiescenceLevel.DROWSY, 1, reason + " (a timer is kept: may_stop is off)")
        return QuiescenceDecision(QuiescenceLevel.QUIESCENT, 0, reason)


DEFAULT_POLICY = QuiescencePolicy()

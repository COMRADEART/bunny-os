# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the companion is *for* right now, and what that permits.

§2 asks for a centralized attention model and, in the same breath, forbids a
second state system. Both halves matter, so this module is a **projection over
:class:`companion.character.mapper.CharacterState`, not a state machine beside
it**. It holds no state, it decides nothing about what happens next, and every
value it produces is a pure function of a character state plus two facts about
the person in front of the machine.

The distinction it adds is a real one that the character vocabulary does not
carry. ``idle`` answers "what is the task doing" — nothing. It does not answer
"is Bunny reachable" or "has Bunny noticed me", and those are different
situations that should not look identical:

======================  ==============================================
``IDLE``                nothing is happening and nobody is here
``AVAILABLE``           nothing is happening and Bunny can be asked
``ATTENTION``           somebody is engaging and the microphone is *not* open
======================  ==============================================

``ATTENTION`` is the step §1's loop puts between the user and ``LISTENING``, and
keeping it distinct from ``LISTENING`` is a §13 requirement rather than a
nicety: a companion that looked like it was listening because a pointer moved
over it would be claiming a microphone it had not opened.

**Why this is not a new CharacterState.** ``attention`` cannot join
:data:`companion.character.schema.REQUIRED_CHARACTER_STATES` without every
bundled package gaining a ``stateMap`` entry — a test requires the bundled
manifest to map every required state — and editing those manifests changes their
package digest. That digest is recorded in ``qualification/public-alpha/gate-vm-*.json``,
evidence taken from a real VM boot that cannot be regenerated without another
one. Ten states' worth of vocabulary is not worth invalidating a boot's
evidence, so the vocabulary lives here and the renderers keep the contract they
were qualified against.

The five questions §2 asks are answered by :class:`AttentionDecision`, and they
are answered *together*. Asking them separately is what produced the bug this
module's shape is designed to prevent: a surface that decided visibility from
one rule, animation from another, and quiescence from a third, and could
therefore be invisible and animating at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .mapper import CharacterState

__all__ = [
    "ATTENTION_LEVELS",
    "AttentionDecision",
    "AttentionInput",
    "AttentionLevel",
    "attention_for",
]


class AttentionLevel(str, Enum):
    """§2's vocabulary. A *view* of the character state, never a second source."""

    IDLE = "idle"
    AVAILABLE = "available"
    ATTENTION = "attention"
    LISTENING = "listening"
    THINKING = "thinking"
    WORKING = "working"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    COMPLETED = "completed"
    ERROR = "error"
    SLEEPING = "sleeping"


#: Declaration order, which is also roughly the interaction loop's order. Not a
#: priority: priority already exists once, in
#: :data:`companion.character.mapper.STATE_PRIORITY`, and a second ordering here
#: would be the competing abstraction §2 forbids.
ATTENTION_LEVELS = tuple(AttentionLevel)

#: Character state -> attention level. Total over ``CharacterState``; a test
#: iterates the enum and asserts that, so a state added later cannot silently
#: fall through to idle and be treated as "nothing is happening".
#:
#: Several character states collapse onto one level on purpose. ``planning``,
#: ``understanding``, ``researching`` and ``reviewing`` are all *thinking* as far
#: as a person watching is concerned; the character still draws them
#: differently, because the mapper still has the finer state. This module is
#: about what is permitted, and the same things are permitted for all four.
_LEVELS: Mapping[CharacterState, AttentionLevel] = {
    CharacterState.UNAVAILABLE: AttentionLevel.ERROR,
    CharacterState.DISCONNECTED: AttentionLevel.ERROR,
    CharacterState.STARTING: AttentionLevel.AVAILABLE,
    CharacterState.IDLE: AttentionLevel.AVAILABLE,
    CharacterState.GREETING: AttentionLevel.ATTENTION,
    CharacterState.LISTENING: AttentionLevel.LISTENING,
    CharacterState.TRANSCRIBING: AttentionLevel.LISTENING,
    CharacterState.UNDERSTANDING: AttentionLevel.THINKING,
    CharacterState.PLANNING: AttentionLevel.THINKING,
    CharacterState.RESEARCHING: AttentionLevel.THINKING,
    CharacterState.REVIEWING: AttentionLevel.THINKING,
    CharacterState.WORKING: AttentionLevel.WORKING,
    CharacterState.TYPING: AttentionLevel.WORKING,
    CharacterState.WAITING_FOR_APPROVAL: AttentionLevel.WAITING_FOR_PERMISSION,
    CharacterState.WAITING_FOR_USER: AttentionLevel.ATTENTION,
    CharacterState.SPEAKING: AttentionLevel.COMPLETED,
    CharacterState.PRESENTING_RESULT: AttentionLevel.COMPLETED,
    CharacterState.SUCCESS: AttentionLevel.COMPLETED,
    CharacterState.WARNING: AttentionLevel.ERROR,
    CharacterState.BLOCKED: AttentionLevel.ERROR,
    CharacterState.ERROR: AttentionLevel.ERROR,
    CharacterState.DEGRADED: AttentionLevel.AVAILABLE,
    CharacterState.PAUSED: AttentionLevel.AVAILABLE,
    CharacterState.CANCELLED: AttentionLevel.AVAILABLE,
    CharacterState.SLEEPING: AttentionLevel.SLEEPING,
    CharacterState.MOVING: AttentionLevel.AVAILABLE,
    CharacterState.REPOSITIONING: AttentionLevel.AVAILABLE,
}

#: Levels during which the companion must be on screen whatever else is set.
#:
#: A hidden companion cannot ask a question, and §12 requires the companion
#: state and the permission UI to agree. Hiding is a preference about the
#: *resting* companion; it is not a way to dismiss a question, and a user who
#: hid the companion and then triggered a permission prompt must still see who
#: is asking.
_ALWAYS_VISIBLE = frozenset({
    AttentionLevel.WAITING_FOR_PERMISSION,
    AttentionLevel.ERROR,
    AttentionLevel.LISTENING,
})

#: Levels during which speaking aloud is appropriate.
#:
#: Deliberately narrow. Voice on every completion would make a quiet machine
#: chatty, and voice while *thinking* would talk over the person who is still
#: finishing their sentence. ``LISTENING`` is absent for the obvious reason.
_VOICE_APPROPRIATE = frozenset({
    AttentionLevel.WAITING_FOR_PERMISSION,
    AttentionLevel.COMPLETED,
    AttentionLevel.ERROR,
})

#: Levels that may stop drawing when they settle. The complement of
#: :data:`companion.character.quiescence.NEVER_QUIESCENT`, expressed in this
#: vocabulary — the two are cross-checked by a test rather than maintained by
#: hand, because two lists of "when may the companion freeze" that disagree is
#: exactly how a companion comes to freeze while asking a question.
_MAY_QUIESCE = frozenset({
    AttentionLevel.IDLE,
    AttentionLevel.AVAILABLE,
    AttentionLevel.SLEEPING,
})


@dataclass(frozen=True)
class AttentionInput:
    """The character state, plus what only the client knows.

    Both extra facts are about the *person*, not the task, which is why they
    cannot come from the projection: whether anyone is at the machine, and
    whether they are currently engaging the companion.
    """

    state: CharacterState
    #: Somebody is engaging the companion — pointer over it, hotkey held, wake
    #: word heard — but no microphone is open yet. This is what raises
    #: ``AVAILABLE`` to ``ATTENTION`` and it is deliberately not able to raise
    #: anything to ``LISTENING``.
    engaged: bool = False
    #: The runtime is reachable. False makes the resting companion ``IDLE``
    #: rather than ``AVAILABLE``: a companion that cannot be asked anything
    #: should not present itself as ready.
    reachable: bool = True
    #: The user asked for the companion to be hidden while resting.
    hidden_by_preference: bool = False
    #: The accessibility preference. Simplifies animation; never removes state.
    reduced_motion: bool = False


@dataclass(frozen=True)
class AttentionDecision:
    """§2's five questions, answered together so they cannot contradict."""

    level: AttentionLevel
    visible: bool
    animate: bool
    voice_appropriate: bool
    may_quiesce: bool
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "level": self.level.value,
            "visible": self.visible,
            "animate": self.animate,
            "voiceAppropriate": self.voice_appropriate,
            "mayQuiesce": self.may_quiesce,
            "reason": self.reason,
        }


def attention_for(value: AttentionInput) -> AttentionDecision:
    """Project a character state into the attention model. Pure."""
    level = _LEVELS.get(value.state, AttentionLevel.AVAILABLE)
    reason = f"{value.state.value} is {level.value}"

    if level is AttentionLevel.AVAILABLE and not value.reachable:
        level = AttentionLevel.IDLE
        reason = "the runtime is not reachable, so the companion is idle rather than available"
    elif level is AttentionLevel.AVAILABLE and value.engaged:
        level = AttentionLevel.ATTENTION
        reason = "somebody is engaging the companion; no microphone is open"

    forced = level in _ALWAYS_VISIBLE
    visible = forced or not value.hidden_by_preference
    if forced and value.hidden_by_preference:
        reason += "; the companion is shown despite the hide preference because it needs an answer"

    may_quiesce = level in _MAY_QUIESCE
    # Animation is permitted whenever the companion is visible and not resting.
    # Reduced motion does not appear here: §9 and §15 both say it *simplifies*
    # animation rather than removing it, and a decision that turned animation
    # off would delete the state information the motion was carrying.
    animate = visible and not may_quiesce
    return AttentionDecision(
        level=level,
        visible=visible,
        animate=animate,
        voice_appropriate=level in _VOICE_APPROPRIATE,
        may_quiesce=may_quiesce,
        reason=reason,
    )

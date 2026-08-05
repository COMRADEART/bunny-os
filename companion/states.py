# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which states a task may be in, and which moves between them are legal.

The table below is the whole of the task lifecycle. It is data rather than
control flow on purpose: an ``if`` chain spread across the runtime can be made
to permit a move nobody intended by adding one branch, whereas a move that is
not in :data:`TRANSITIONS` cannot happen at all, and the tests can enumerate
every pair and assert on the ones that are refused.

Three rules shaped it.

**Recovery never resumes straight into execution.** A task found mid-execution
after a crash goes to ``planning``, not back to ``executing``. The executor then
replans with the completed operation keys in front of it, so an operation whose
outcome is unknown is *decided about* rather than *repeated*. Allowing
``recovering -> executing`` would make that decision skippable, so the table
does not contain it.

**Cancellation has a state of its own.** ``cancelling`` exists because stopping
takes time: pending operations have to be signalled, approvals invalidated and
partial output written down. During that window the task must accept no new
work, and a state that says so is more reliable than a boolean somebody has to
remember to check.

**Blocked is not terminal.** A task blocked for want of an eligible executor
becomes runnable again when the machine changes, and forcing the user to
resubmit would lose the original request and every event attached to it. It
returns through ``classifying``, so the capability question is asked again from
the beginning rather than the old answer being reused.
"""

from __future__ import annotations

from typing import Mapping

from .errors import InvalidTransition

__all__ = [
    "ACTIVE_STATES",
    "INITIAL_STATE",
    "OPERATION_PERMITTED_STATES",
    "RESUMABLE_STATES",
    "STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "event_for",
    "may_start_operation",
    "require_transition",
    "transition_allowed",
]

#: Every state a task may hold. ``cancelling`` is the addition to the brief's
#: list; see the module docstring for why stopping needs a state and not a flag.
STATES = (
    "created",
    "classifying",
    "waiting_for_capability",
    "waiting_for_executor",
    "waiting_for_approval",
    "planning",
    "executing",
    "reviewing",
    "presenting",
    "completed",
    "blocked",
    "failed",
    "cancelled",
    "cancelling",
    "paused",
    "recovering",
)

INITIAL_STATE = "created"

#: States from which nothing further happens. A task in one of these is history.
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

#: States in which the task is somebody's current business.
ACTIVE_STATES = frozenset(STATES) - TERMINAL_STATES - {"blocked", "paused"}

#: The only states in which a new tool operation may begin. Cancellation works
#: by leaving this set, which is what makes "cancellation stops new operations"
#: a property of the state machine rather than a promise made by every call site.
OPERATION_PERMITTED_STATES = frozenset({"executing"})

#: Where a paused task may be sent when it resumes: exactly the phase it was
#: paused from. Pause records the state it interrupted and resume restores it,
#: so pausing is not a way to move a task sideways through the lifecycle.
RESUMABLE_STATES = frozenset({
    "classifying",
    "waiting_for_capability",
    "waiting_for_executor",
    "waiting_for_approval",
    "planning",
    "executing",
    "reviewing",
    "presenting",
})

#: A transition with no dedicated event in the brief's vocabulary. The brief
#: lists the events that carry meaning to a reader; a few moves — entering
#: classification, beginning to cancel — carry only the move itself. They still
#: emit an event, because §5 requires every transition to be typed and an
#: untyped gap in the stream is a gap in the replay.
GENERIC_TRANSITION_EVENT = "task_state_changed"

#: (from, to) -> the event type the transition emits.
#:
#: One event per transition, fixed. A transition whose event type varied with
#: the caller would let two runs of the same lifecycle produce two different
#: histories, and the replay check in the vertical slice would then be comparing
#: a choice rather than a record.
TRANSITIONS: Mapping[tuple[str, str], str] = {
    ("created", "classifying"): GENERIC_TRANSITION_EVENT,
    ("created", "cancelling"): GENERIC_TRANSITION_EVENT,

    ("classifying", "waiting_for_capability"): "task_classified",
    ("classifying", "blocked"): GENERIC_TRANSITION_EVENT,

    ("waiting_for_capability", "waiting_for_executor"): "capability_checked",
    ("waiting_for_capability", "blocked"): "capability_checked",

    ("waiting_for_executor", "planning"): "planning_started",
    ("waiting_for_executor", "waiting_for_approval"): "approval_requested",
    ("waiting_for_executor", "blocked"): GENERIC_TRANSITION_EVENT,

    ("planning", "waiting_for_approval"): "approval_requested",
    ("planning", "executing"): "execution_started",
    ("planning", "presenting"): "result_created",
    ("planning", "blocked"): GENERIC_TRANSITION_EVENT,

    ("waiting_for_approval", "planning"): "planning_started",
    ("waiting_for_approval", "executing"): "approval_resolved",
    ("waiting_for_approval", "blocked"): "approval_resolved",

    ("executing", "reviewing"): GENERIC_TRANSITION_EVENT,
    ("executing", "presenting"): "result_created",
    ("executing", "waiting_for_approval"): "approval_requested",

    ("reviewing", "planning"): "planning_started",
    ("reviewing", "executing"): "execution_started",
    ("reviewing", "presenting"): "result_created",

    ("presenting", "completed"): "task_completed",

    ("cancelling", "cancelled"): "task_cancelled",

    ("blocked", "classifying"): GENERIC_TRANSITION_EVENT,
    ("blocked", "cancelling"): GENERIC_TRANSITION_EVENT,

    ("recovering", "classifying"): "recovery_completed",
    ("recovering", "planning"): "recovery_completed",
    ("recovering", "presenting"): "recovery_completed",
    ("recovering", "paused"): "recovery_completed",
    ("recovering", "blocked"): "recovery_completed",
    ("recovering", "failed"): "recovery_completed",
    ("recovering", "cancelled"): "recovery_completed",
}

# Pause, resume, failure, cancellation and recovery apply broadly, so they are
# expanded here rather than written out sixteen times above. Building the table
# in code keeps the general rules visible as rules: "anything active can fail"
# is one line, and a state added to STATES later inherits it instead of silently
# lacking it.
_MUTABLE: dict[tuple[str, str], str] = dict(TRANSITIONS)

for _state in ACTIVE_STATES | {"blocked"}:
    # Anything that has not finished can fail, and can be told to stop.
    if _state not in ("failed", "cancelling", "recovering"):
        _MUTABLE.setdefault((_state, "failed"), "task_failed")
    if _state not in ("cancelling", "recovering"):
        _MUTABLE.setdefault((_state, "cancelling"), GENERIC_TRANSITION_EVENT)

for _state in RESUMABLE_STATES:
    _MUTABLE.setdefault((_state, "paused"), "task_paused")
    _MUTABLE.setdefault(("paused", _state), "task_resumed")

for _state in (ACTIVE_STATES | {"paused", "blocked"}) - {"recovering"}:
    # Recovery may take hold of anything that was not finished. Deliberately
    # including "cancelling": a crash during cancellation leaves a task that
    # must be finished being cancelled, not one that quietly resumes.
    _MUTABLE.setdefault((_state, "recovering"), "recovery_started")

_MUTABLE.setdefault(("paused", "cancelling"), GENERIC_TRANSITION_EVENT)
_MUTABLE.setdefault(("paused", "failed"), "task_failed")
_MUTABLE.setdefault(("cancelling", "failed"), "task_failed")

TRANSITIONS = dict(sorted(_MUTABLE.items()))
del _MUTABLE, _state

# A guard against the table drifting out of the state list. Cheap at import and
# it has already caught one typo that would have produced an unreachable state.
for _from, _to in TRANSITIONS:
    if _from not in STATES or _to not in STATES:
        raise AssertionError(f"transition {_from!r} -> {_to!r} names a state outside STATES")
for _terminal in TERMINAL_STATES:
    if any(source == _terminal for source, _ in TRANSITIONS):
        raise AssertionError(f"{_terminal!r} is terminal but has an outgoing transition")


def transition_allowed(current: str, target: str) -> bool:
    """Whether a task in ``current`` may move to ``target``."""
    return (current, target) in TRANSITIONS


def event_for(current: str, target: str) -> str:
    """The event type a legal transition emits. Raises if it is not legal."""
    try:
        return TRANSITIONS[(current, target)]
    except KeyError:
        raise InvalidTransition(
            f"a task in {current!r} cannot move to {target!r}"
        ) from None


def require_transition(current: str, target: str) -> str:
    """Assert a transition is legal and return its event type.

    The refusal message names both states and, where the target is reachable by
    another route, says so — a caller that tried ``executing -> completed``
    should be told that a result has to be presented first, not merely that it
    was wrong.
    """
    if current not in STATES:
        raise InvalidTransition(f"unknown current state: {current!r}")
    if target not in STATES:
        raise InvalidTransition(f"unknown target state: {target!r}")
    if (current, target) in TRANSITIONS:
        return TRANSITIONS[(current, target)]
    if current in TERMINAL_STATES:
        raise InvalidTransition(
            f"the task is {current!r}, which is final; it cannot move to {target!r}"
        )
    reachable = sorted(to for source, to in TRANSITIONS if source == current)
    raise InvalidTransition(
        f"a task in {current!r} cannot move to {target!r}; "
        f"it may move to: {', '.join(reachable) if reachable else 'nothing'}"
    )


def may_start_operation(state: str) -> bool:
    """Whether a new tool operation may begin in this state."""
    return state in OPERATION_PERMITTED_STATES

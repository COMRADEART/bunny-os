# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The job state machine: ten states, one way into ``completed``.

    created -> preflighting -> ready -> preparing -> training -> evaluating -> completed
                    |            |         |            |            |
                    +------------+---------+------------+------------+--> failed / cancelled
                    |
                    +--> blocked --> preflighting

The shape matters less than one property of it, which is the reason this is a
table and not a string field somebody assigns:

    ``completed`` has exactly one predecessor, and it is ``evaluating``.

A run cannot become complete by finishing, by exiting zero, by writing its
files, or by any path that does not go through the evaluation that checks the
adapter is different from nothing. And because the transition table is the only
way the field ever changes, that is a property of the type rather than a
convention every caller has to remember.

``blocked`` returns to ``preflighting`` rather than being terminal, because the
thing that blocks a run is usually a missing package or a busy GPU, and a job
that has to be recreated after ``pip install peft`` teaches people to skip
preflight. ``failed`` and ``cancelled`` are terminal: they describe a run that
touched the model, and re-entering one would mean a second run with the first
one's identity and provenance.
"""

from __future__ import annotations

from typing import Mapping

from ..errors import JobStateError

__all__ = [
    "ACTIVE",
    "BLOCKED",
    "CANCELLED",
    "COMPLETED",
    "CREATED",
    "EVALUATING",
    "FAILED",
    "PREFLIGHTING",
    "PREPARING",
    "READY",
    "STATES",
    "TERMINAL",
    "TRAINING",
    "TRANSITIONS",
    "check_transition",
    "is_active",
    "is_terminal",
]

CREATED = "created"
PREFLIGHTING = "preflighting"
READY = "ready"
PREPARING = "preparing"
TRAINING = "training"
EVALUATING = "evaluating"
COMPLETED = "completed"
BLOCKED = "blocked"
FAILED = "failed"
CANCELLED = "cancelled"

STATES: tuple[str, ...] = (
    CREATED, PREFLIGHTING, READY, PREPARING, TRAINING, EVALUATING,
    COMPLETED, BLOCKED, FAILED, CANCELLED,
)

#: A state in which a process is supposed to be doing something. A record found
#: in one of these whose owner is gone did not finish; see
#: :meth:`model_studio.jobs.store.JobStore.recover`.
ACTIVE: frozenset[str] = frozenset({PREFLIGHTING, PREPARING, TRAINING, EVALUATING})

#: No transition leaves these.
TERMINAL: frozenset[str] = frozenset({COMPLETED, FAILED, CANCELLED})

TRANSITIONS: Mapping[str, frozenset[str]] = {
    CREATED: frozenset({PREFLIGHTING, CANCELLED, FAILED}),
    PREFLIGHTING: frozenset({READY, BLOCKED, FAILED, CANCELLED}),
    READY: frozenset({PREPARING, BLOCKED, CANCELLED, FAILED}),
    PREPARING: frozenset({TRAINING, BLOCKED, FAILED, CANCELLED}),
    TRAINING: frozenset({EVALUATING, FAILED, CANCELLED}),
    # The only edge into COMPLETED in the whole table.
    EVALUATING: frozenset({COMPLETED, FAILED, CANCELLED}),
    BLOCKED: frozenset({PREFLIGHTING, CANCELLED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}


def is_active(state: str) -> bool:
    return state in ACTIVE


def is_terminal(state: str) -> bool:
    return state in TERMINAL


def check_transition(current: str, target: str) -> None:
    """Raise unless ``current -> target`` is an edge of the machine."""
    if current not in TRANSITIONS:
        raise JobStateError(f"{current!r} is not a job state")
    if target not in TRANSITIONS:
        raise JobStateError(f"{target!r} is not a job state")
    if target not in TRANSITIONS[current]:
        allowed = ", ".join(sorted(TRANSITIONS[current])) or "nothing; it is terminal"
        raise JobStateError(
            f"a job in {current!r} cannot move to {target!r}. From {current!r} it may go to: {allowed}"
        )

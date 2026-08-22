# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny Companion runtime core, headless.

This package is the part of the companion that has to be right before anything
is drawn on a screen: what a session is, what a task is, which states a task may
move between, what happened to it and in what order, who was allowed to act, and
what survives the machine being switched off in the middle.

It deliberately renders nothing. There is no window, no character, no voice and
no commercial provider anywhere in this package, and none may be added to it.
Those are later phases and they consume this one; building them first would mean
deciding the shape of the record from the shape of the animation, which is how a
companion ends up with a beautiful surface over an event log nobody can replay.

The pipeline is one direction:

    request -> session -> task -> classification -> capability -> executor
            -> approval -> execution events -> review -> result -> history

Three properties are load-bearing and everything else is arranged around them.

**The event stream is the truth.** Session and task documents are projections of
their events and can always be rebuilt from them. A field that cannot be derived
from the record is a field that will eventually disagree with it.

**Uncertainty never becomes action.** An approval nobody answered is a denial. A
capability that could not be established is not a capability. An operation whose
completion event is missing is *unknown*, not *incomplete*, and an unknown
operation is never repeated — the runtime refuses to perform one, and says so in
the stream. That is only possible because :func:`companion.ids.operation_key`
identifies the *act* rather than its position in a plan, so the same operation
under a later plan revision is recognisable as the same operation.

**The executor acts and the reviewers only look.** Exactly one executor holds a
task at a time; reviewers can read a redacted view and say what they think, and
that is the whole of their power. The separation is enforced by the interfaces
in :mod:`companion.executor` and :mod:`companion.reviewer`, not by convention.
"""

from __future__ import annotations

#: Version of the persisted session document (``schemas/companion-session.schema.json``).
SESSION_SCHEMA_VERSION = 1

#: Version of the persisted task document (``schemas/companion-task.schema.json``).
TASK_SCHEMA_VERSION = 1

#: Version of the task event record (``schemas/companion-event.schema.json``).
#:
#: Version 2 added ``internalFields``, the per-field classification list, so a
#: mixed payload can reveal the runtime facts an auditor needs without revealing
#: the user's words beside them.
#:
#: The version moved because the *hashed material* changed. Adding the field to
#: version 1's rule instead — which an earlier revision of this work did — made
#: every event the previous build had written fail its own hash, turned
#: legitimate data into reported tampering, and left no recovery path because
#: ``migrate()`` saw no version change to act on. Adding a field to the hash is
#: a new version, always; see :data:`companion.events.HASHED_FIELDS_BY_VERSION`.
#:
#: The store migrates forward from every version it has ever written; see
#: :mod:`companion.store`. A reader that meets a *higher* version than it knows
#: refuses the file rather than guessing, because a partially understood event
#: stream is worse than an unreadable one.
EVENT_SCHEMA_VERSION = 2

#: Version of the on-disk store layout as a whole.
STORE_SCHEMA_VERSION = 1

#: Version of the projected companion state document
#: (``schemas/companion-state.schema.json``). State is a projection of the
#: event stream rather than an independent record, so this version moves only
#: when the projection itself changes shape, never when an event field does.
COMPANION_STATE_SCHEMA_VERSION = 1

#: Version of the character package manifest
#: (``schemas/companion-character-package.schema.json``), validated by
#: :func:`companion.characters.validate_directory` / ``validate_archive``.
CHARACTER_PACKAGE_SCHEMA_VERSION = 1

__all__ = [
    "CHARACTER_PACKAGE_SCHEMA_VERSION",
    "COMPANION_STATE_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
    "TASK_SCHEMA_VERSION",
]

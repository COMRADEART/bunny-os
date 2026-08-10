# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers, and the one kind that must survive a crash.

Most identifiers here are opaque and only need to be unique: a session id, a
task id, an event id. They come from an injectable :class:`IdSource` so that the
vertical slice and the tests can produce the same document twice, which is what
makes "the completed result is unchanged after restart" a check rather than an
assertion of faith.

**Operation keys are different and are not opaque.** They are derived, by
:func:`operation_key`, from the facts that make an operation *that* operation:
the task, the plan revision it was planned under, its position in that plan, and
its name. This is what makes recovery safe. After a crash the runtime finds an
operation that was started and has no completion event; it must decide whether
the work happened. It cannot know. What it *can* know is whether an operation
with this exact key was already recorded as completed, and a derived key is the
only way that question has an answer — a random id regenerated on restart would
make every recovered operation look new, and "looks new" is how a machine sends
the same message twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import itertools
import re
import uuid
from typing import Any, Mapping, Protocol

__all__ = [
    "ID_PATTERN",
    "IdSource",
    "RandomIds",
    "SequentialIds",
    "operation_key",
    "valid_id",
]

#: What an identifier may look like. Bounded and restricted because these end up
#: in file names, JSON keys, log lines and one day a URL, and an id containing a
#: path separator is a directory traversal waiting for somewhere to happen.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def valid_id(value: str) -> bool:
    return isinstance(value, str) and ID_PATTERN.match(value) is not None


class IdSource(Protocol):
    """Where new identifiers come from."""

    def next(self, prefix: str) -> str:
        """A fresh identifier beginning with ``prefix``."""


@dataclass
class RandomIds:
    """Production identifiers: a prefix and a UUID4.

    No time, no counter and no host information. An identifier that encoded when
    or where it was minted would leak both into every export of a sanitized
    history, and the history has a timestamp field already for the cases where
    the time is legitimately wanted.
    """

    def next(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


@dataclass
class SequentialIds:
    """Deterministic identifiers for tests, demos and the vertical slice.

    Not a weaker :class:`RandomIds`: it is used where reproducibility is the
    property under test. Nothing in the runtime treats a sequential id
    differently, so a slice run against this source exercises the same code the
    installed system runs.
    """

    counters: dict[str, itertools.count] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        counter = self.counters.get(prefix)
        if counter is None:
            counter = itertools.count(1)
            self.counters[prefix] = counter
        return f"{prefix}-{next(counter):06d}"


def operation_key(
    *,
    task_id: str,
    name: str,
    tool: str,
    arguments: Mapping[str, Any],
    destination: str = "local",
) -> str:
    """The idempotency key for one operation: a digest of *the act*.

    Derived, not minted, and derived from what makes an operation *that*
    operation — the task it belongs to, what it is called, which tool it uses,
    what it is given and where it goes. Two plans that would perform the same
    act produce the same key whatever revision they are, which is precisely what
    lets :mod:`companion.recovery` ask "has this already happened?" and get a
    real answer.

    **The plan revision is deliberately not in the key**, and an earlier version
    of this function that included it was wrong in a way worth recording. With
    the revision in the key, every replan produced fresh keys, no key ever
    matched a completed one, and the skip branch in the runtime was unreachable
    — so a task recovered after a crash re-ran work the record already proved
    had happened, while the ledger entry beside it still said "this will not be
    repeated". The guarantee was stated in three module docstrings and held in
    none of them. Keying the act rather than its position in a plan is what
    makes the guarantee true.

    The consequence to be aware of: two operations that genuinely should run
    twice — the same tool with the same arguments, deliberately repeated — share
    a key. That is the correct default for a companion, where the dangerous
    error is doing something twice rather than once; an operation that must
    repeat can carry a distinguishing argument.

    Note the *encoding*, not just the fields. An earlier version joined the
    fields with a ``\\x1f`` separator, and three of them — ``name``, ``tool``,
    ``destination`` — are free strings an executor controls. Shifting a
    ``\\x1f`` across a field boundary produced identical material for two
    genuinely different acts, so one could be deduplicated away against the
    other and never performed while the record claimed it "was not repeated".
    Canonical JSON of the whole tuple has no such boundary to move: the encoder
    escapes the separator inside a value, so the encoding of the fields
    determines the fields.
    """
    from capability.apply.identity import canonical_json

    material = canonical_json([task_id, name, tool, destination, dict(arguments)])
    return "op-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

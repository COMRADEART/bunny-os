# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The durable record of what was attempted, and what a restart may conclude.

A desktop effect outlives the process that caused it. That single fact is why
this file exists: after a crash, the runtime has to decide whether a link was
opened, and the only thing that can help is a record written *before* the act
and updated after it.

**The write ordering is the guarantee.** An entry reaches the disk in state
``started`` before the adapter is called, and is updated afterwards. A process
that dies in between leaves a ``started`` entry from a run that is over, and
:meth:`OperationLedger.load` turns exactly those into ``unknown`` — never into
``failed``, and never into "retry me". §20 forbids repeating an incomplete
desktop action automatically, and this is the mechanism rather than the
intention.

**A run identifier is what makes "from a previous run" answerable.** Entries
carry the run that wrote them. An entry in ``started`` bearing *this* run's id
is genuinely in flight; one bearing another run's id is the wreckage of a crash.
Without the id the two are indistinguishable and a concurrent attempt would be
reclassified as unknown while it was still running.

**Approvals are not in here and are not reused.** §20 says a restarted runtime
must not reuse a prior approval, and the way that is kept is that this ledger
holds no approval — it holds the *binding digest*, which is enough to notice
that a re-proposed act is the same one and not enough to authorise it.
:class:`companion.approvals.CompanionApprovalStore` expires everything from a
previous run on load, and nothing here works around that.

**No user content, ever.** An entry holds the action id, the digests, bounded
target metadata, the state and the timings — §13's permitted list. A clipboard
write's text is not here; its digest is. A URI's query is not here; the
normalised address without it is the target, and the binding digest covers the
whole.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Mapping, Sequence

from ..errors import StoreError
from .errors import DesktopSchemaError
from .idempotency import OPERATION_STATES, settled
from .result import DesktopActionResult

__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "LedgerEntry",
    "OperationLedger",
]

LEDGER_SCHEMA_VERSION = 1

#: The most entries kept. A ledger that grew without bound would eventually be
#: too large to read at start-up, and a record that must be read to recover is a
#: record that must stay readable. Oldest settled entries are dropped first;
#: unsettled ones are never dropped, because an unknown that fell out of the
#: ledger is an unknown nobody will ever decide about.
MAX_ENTRIES = 2048


@dataclass(frozen=True)
class LedgerEntry:
    """One desktop action attempt, as the record holds it."""

    key: str
    action_id: str
    task_id: str
    session_id: str
    lifecycle_epoch: int
    plan_id: str
    operation_id: str
    state: str
    binding_digest: str
    target: str = ""
    target_kind: str = "none"
    run_id: str = ""
    request_id: str = ""
    started_at: str = ""
    settled_at: str = ""
    #: The result, as :meth:`companion.desktop.result.DesktopActionResult.to_json`
    #: produced it. Present only once the attempt settled.
    result: Mapping[str, Any] = field(default_factory=dict)
    #: What would have to be restored. Read before the act, so an undo offered
    #: after a restart restores a state that was observed rather than assumed.
    previous_state: Mapping[str, Any] = field(default_factory=dict)
    #: Set when a *later* attempt undid this one, and to that attempt's key.
    undone_by: str = ""
    #: Set on an undo attempt, to the key of what it undoes.
    undo_of: str = ""
    #: Why this entry is in the state it is, when the state was reached by
    #: recovery rather than by the attempt finishing.
    recovery_note: str = ""

    def __post_init__(self) -> None:
        if self.state not in OPERATION_STATES:
            raise DesktopSchemaError(f"{self.state!r} is not an operation state")
        if not self.key:
            raise DesktopSchemaError("a ledger entry needs its idempotency key")

    @property
    def settled(self) -> bool:
        return settled(self.state)

    @property
    def repeatable(self) -> bool:
        """Whether this key may be attempted again at all.

        ``False`` for everything settled and for ``unknown``. An unknown is not
        repeatable *by the broker*; a person may still decide to, and that
        decision arrives as a new operation with a new key rather than as a
        retry of this one.
        """
        return self.state in ("not-started",)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "actionId": self.action_id,
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "lifecycleEpoch": self.lifecycle_epoch,
            "planId": self.plan_id,
            "operationId": self.operation_id,
            "state": self.state,
            "bindingDigest": self.binding_digest,
            "target": self.target,
            "targetKind": self.target_kind,
            "runId": self.run_id,
            "requestId": self.request_id,
            "startedAt": self.started_at,
            "settledAt": self.settled_at,
            "result": dict(self.result),
            "previousState": dict(self.previous_state),
            "undoneBy": self.undone_by,
            "undoOf": self.undo_of,
            "recoveryNote": self.recovery_note,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "LedgerEntry":
        if not isinstance(document, Mapping):
            raise StoreError("a ledger entry must be an object")
        state = str(document.get("state", "unknown"))
        if state not in OPERATION_STATES:
            raise StoreError(f"unknown stored operation state: {state!r}")
        return cls(
            key=str(document.get("key", "")),
            action_id=str(document.get("actionId", "")),
            task_id=str(document.get("taskId", "")),
            session_id=str(document.get("sessionId", "")),
            lifecycle_epoch=int(document.get("lifecycleEpoch", 0) or 0),
            plan_id=str(document.get("planId", "")),
            operation_id=str(document.get("operationId", "")),
            state=state,
            binding_digest=str(document.get("bindingDigest", "")),
            target=str(document.get("target", "")),
            target_kind=str(document.get("targetKind", "none")),
            run_id=str(document.get("runId", "")),
            request_id=str(document.get("requestId", "")),
            started_at=str(document.get("startedAt", "")),
            settled_at=str(document.get("settledAt", "")),
            result=dict(document.get("result") or {}),
            previous_state=dict(document.get("previousState") or {}),
            undone_by=str(document.get("undoneBy", "")),
            undo_of=str(document.get("undoOf", "")),
            recovery_note=str(document.get("recoveryNote", "")),
        )


@dataclass
class OperationLedger:
    """Every attempt, durable, keyed by :func:`companion.desktop.idempotency.action_key`.

    In-memory when :attr:`path` is ``None``, which is what the unit tests use.
    The durability is the *point* of the class, so the tests that matter about
    recovery use a real file and a real restart.
    """

    path: Path | None = None
    run_id: str = ""
    entries: dict[str, LedgerEntry] = field(default_factory=dict)
    #: What loading found and had to reclassify. Surfaced by the broker as
    #: recovery warnings rather than swallowed.
    warnings: tuple[str, ...] = ()
    _guard: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = "drun-" + os.urandom(8).hex()

    # -- reading -----------------------------------------------------------

    def get(self, key: str) -> LedgerEntry | None:
        with self._guard:
            return self.entries.get(key)

    def state_of(self, key: str) -> str:
        entry = self.get(key)
        return entry.state if entry is not None else "not-started"

    def for_task(self, task_id: str) -> tuple[LedgerEntry, ...]:
        with self._guard:
            return tuple(
                self.entries[key]
                for key in sorted(self.entries)
                if self.entries[key].task_id == task_id
            )

    def unsettled(self) -> tuple[LedgerEntry, ...]:
        with self._guard:
            return tuple(
                self.entries[key] for key in sorted(self.entries) if not self.entries[key].settled
            )

    def unknown(self) -> tuple[LedgerEntry, ...]:
        with self._guard:
            return tuple(
                self.entries[key] for key in sorted(self.entries) if self.entries[key].state == "unknown"
            )

    def history(self, *, task_id: str = "", limit: int = 50) -> tuple[LedgerEntry, ...]:
        with self._guard:
            items = [
                self.entries[key]
                for key in sorted(self.entries, key=lambda item: (self.entries[item].started_at, item))
                if not task_id or self.entries[key].task_id == task_id
            ]
        return tuple(items[-max(1, int(limit)):])

    # -- writing -----------------------------------------------------------

    def begin(self, entry: LedgerEntry) -> LedgerEntry:
        """Record an attempt as ``started``, durably, **before** it is made.

        The order is the whole guarantee. A process that dies after this call
        and before :meth:`settle` leaves an entry that recovery can find; a
        process that dies before it leaves nothing, which is also correct —
        nothing was attempted.
        """
        with self._guard:
            existing = self.entries.get(entry.key)
            if existing is not None and existing.state != "not-started":
                raise DesktopSchemaError(
                    f"{entry.key} is already recorded as {existing.state!r}; an attempt is not "
                    "begun twice"
                )
            recorded = replace(entry, state="started", run_id=self.run_id)
            self.entries[recorded.key] = recorded
        self.save()
        return recorded

    def settle(
        self,
        key: str,
        *,
        state: str,
        result: DesktopActionResult | None = None,
        settled_at: str = "",
        recovery_note: str = "",
    ) -> LedgerEntry:
        if state not in OPERATION_STATES:
            raise DesktopSchemaError(f"{state!r} is not an operation state")
        with self._guard:
            entry = self.entries.get(key)
            if entry is None:
                raise DesktopSchemaError(f"no attempt with key {key!r} was begun")
            updated = replace(
                entry,
                state=state,
                result=result.to_json() if result is not None else dict(entry.result),
                settled_at=settled_at or entry.settled_at,
                recovery_note=recovery_note or entry.recovery_note,
            )
            self.entries[key] = updated
            self._trim()
        self.save()
        return updated

    def record_previous_state(self, key: str, previous: Mapping[str, Any]) -> None:
        with self._guard:
            entry = self.entries.get(key)
            if entry is None:
                return
            self.entries[key] = replace(entry, previous_state=dict(previous))
        self.save()

    def link_undo(self, *, original_key: str, undo_key: str) -> None:
        """Tie an undo attempt to what it undid, in both directions.

        §11 requires an undo to be a new action with its own lifecycle and audit
        record, and this is what keeps that from making the pair unfindable. The
        original moves to ``undone`` — not back to ``not-started``, because it
        *did* happen and a record that said otherwise would be false.
        """
        with self._guard:
            original = self.entries.get(original_key)
            undo = self.entries.get(undo_key)
            if original is None or undo is None:
                raise DesktopSchemaError("an undo can only be linked to two recorded attempts")
            self.entries[original_key] = replace(original, state="undone", undone_by=undo_key)
            self.entries[undo_key] = replace(undo, undo_of=original_key)
        self.save()

    def _trim(self) -> None:
        if len(self.entries) <= MAX_ENTRIES:
            return
        settled_keys = [
            key for key in sorted(self.entries, key=lambda item: self.entries[item].settled_at or "")
            if self.entries[key].settled
        ]
        for key in settled_keys[: len(self.entries) - MAX_ENTRIES]:
            self.entries.pop(key, None)

    # -- persistence -------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        with self._guard:
            return {
                "schemaVersion": LEDGER_SCHEMA_VERSION,
                "kind": "bunny-companion-desktop-ledger",
                "runId": self.run_id,
                "entries": [self.entries[key].to_json() for key in sorted(self.entries)],
            }

    def save(self) -> None:
        """Atomic replace, mode 0600, fsync before rename.

        The same discipline as :mod:`companion.store` and
        :class:`companion.approvals.CompanionApprovalStore`, and for a sharper
        reason here: a half-written ledger is a file that might read as "this
        action completed", and acting on that would be exactly the repetition
        the ledger exists to prevent — in the other direction.
        """
        if self.path is None:
            return
        encoded = json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=str(self.path.parent),
            prefix=self.path.name + ".", suffix=".tmp", delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise StoreError(f"{self.path} could not be written: {exc}") from exc

    @classmethod
    def load(cls, path: Path, *, run_id: str = "") -> "OperationLedger":
        """Read a ledger, reclassifying everything a crash left in flight.

        The reclassification is the recovery, and it is deliberately narrow:

        * ``started`` from another run becomes ``unknown``. Not ``failed`` —
          nobody knows whether it failed — and not repeated, because §20 says an
          incomplete desktop action is not automatically repeated;
        * everything settled is left exactly as it was. §20 requires completed
          action results to be preserved, and rewriting them would lose the only
          evidence that the act happened;
        * ``unknown`` stays ``unknown``. A second restart does not make an
          unknown any more knowable, and quietly ageing one into ``failed``
          would let a user's decision be skipped.
        """
        ledger = cls(path=path, run_id=run_id)
        if not path.is_file():
            return ledger
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not a readable desktop ledger: {exc}") from exc
        if not isinstance(document, Mapping) or document.get("kind") != "bunny-companion-desktop-ledger":
            raise StoreError(f"{path} is not a companion desktop ledger")
        version = document.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool) or version > LEDGER_SCHEMA_VERSION:
            raise StoreError(f"desktop ledger schemaVersion {version!r} is not one this build reads")

        previous_run = str(document.get("runId", ""))
        reclassified: list[str] = []
        for item in document.get("entries", ()):
            entry = LedgerEntry.from_json(item)
            if entry.state == "started" and entry.run_id != ledger.run_id:
                entry = replace(
                    entry,
                    state="unknown",
                    recovery_note=(
                        "this attempt began before the runtime stopped and nothing settled it; "
                        "whether the desktop changed is not known, so it was not repeated and "
                        "a new decision is required"
                    ),
                )
                reclassified.append(entry.key)
            ledger.entries[entry.key] = entry

        if reclassified:
            ledger.warnings = (
                f"{len(reclassified)} desktop action(s) from run {previous_run or 'an earlier run'} "
                "were in flight when the runtime stopped; their effect is unknown and none was "
                "repeated",
            )
        return ledger


def summarise(entries: Sequence[LedgerEntry]) -> dict[str, int]:
    """How many attempts are in each state. The §23 gate reads this."""
    counts = {state: 0 for state in OPERATION_STATES}
    for entry in entries:
        counts[entry.state] = counts.get(entry.state, 0) + 1
    return counts

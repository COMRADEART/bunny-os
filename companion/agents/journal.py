# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generation journal: what was in flight, so a restart repeats nothing.

§19's rule has a price attached: an interrupted *paid* generation that is
quietly retried is money spent without a decision. So the journal records a
start before any dispatch and a settlement after every outcome, and
:func:`reconcile` — run once at service construction, before the worker
thread exists — turns every unsettled start into an explicit
``interrupted-not-repeated`` record. Nothing re-enqueues it. The task that
owned it comes back through the canonical runtime's own recovery, which
re-plans under a fresh lifecycle decision; the *generation* is gone, and the
record says so rather than saying nothing.

The journal is process-local bookkeeping (mode 0600, bounded, rewritten at
reconcile). It is not the event stream and holds no message content — request
ids, provider ids, purposes and dispositions only, so even its loss costs
accounting, never privacy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = ["GenerationJournal", "JournalEntry", "reconcile"]

_MAX_JOURNAL_BYTES = 256 * 1024


@dataclass(frozen=True)
class JournalEntry:
    """One line of the journal, both directions."""

    event: str
    request_id: str
    provider_id: str = ""
    session_id: str = ""
    task_id: str = ""
    purpose: str = ""
    remote: bool = False
    paid: bool = False
    disposition: str = ""
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "purpose": self.purpose,
            "remote": self.remote,
            "paid": self.paid,
            "disposition": self.disposition,
            "detail": self.detail,
        }


class GenerationJournal:
    """Append-only within a run; compacted only by :func:`reconcile`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self._path.parent, 0o700)

    @property
    def path(self) -> Path:
        return self._path

    def _append(self, entry: JournalEntry) -> None:
        line = json.dumps(entry.to_json(), ensure_ascii=False) + "\n"
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(line)
        if os.name == "posix":
            os.chmod(self._path, 0o600)

    def record_start(
        self, *, request_id: str, provider_id: str, session_id: str,
        task_id: str, purpose: str, remote: bool, paid: bool,
    ) -> None:
        self._append(JournalEntry(
            event="generation_started", request_id=request_id, provider_id=provider_id,
            session_id=session_id, task_id=task_id, purpose=purpose,
            remote=remote, paid=paid,
        ))

    def record_settled(self, request_id: str, disposition: str, detail: str = "") -> None:
        self._append(JournalEntry(
            event="generation_settled", request_id=request_id,
            disposition=disposition, detail=detail[:400],
        ))

    def entries(self) -> tuple[JournalEntry, ...]:
        if not self._path.exists():
            return ()
        collected: list[JournalEntry] = []
        raw = self._path.read_bytes()
        if len(raw) > _MAX_JOURNAL_BYTES:
            # Keep the tail; the head is history reconcile already acted on.
            raw = raw[-_MAX_JOURNAL_BYTES:]
            raw = raw[raw.find(b"\n") + 1:]
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(document, Mapping):
                continue
            collected.append(JournalEntry(
                event=str(document.get("event", "")),
                request_id=str(document.get("requestId", "")),
                provider_id=str(document.get("providerId", "")),
                session_id=str(document.get("sessionId", "")),
                task_id=str(document.get("taskId", "")),
                purpose=str(document.get("purpose", "")),
                remote=bool(document.get("remote", False)),
                paid=bool(document.get("paid", False)),
                disposition=str(document.get("disposition", "")),
                detail=str(document.get("detail", "")),
            ))
        return tuple(collected)

    def unsettled(self) -> tuple[JournalEntry, ...]:
        started: dict[str, JournalEntry] = {}
        for entry in self.entries():
            if entry.event == "generation_started":
                started[entry.request_id] = entry
            elif entry.event == "generation_settled":
                started.pop(entry.request_id, None)
        return tuple(started.values())

    def rewrite(self, entries: tuple[JournalEntry, ...]) -> None:
        temporary = self._path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry.to_json(), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)
        if os.name == "posix":
            os.chmod(self._path, 0o600)


def reconcile(journal: GenerationJournal) -> dict[str, Any]:
    """Mark every unsettled start interrupted. Run before the worker exists.

    Returns the §19 report: which generations were in flight, which were
    paid, and the one disposition all of them received. Nothing is retried
    from here — a retry is a new lifecycle decision the canonical runtime
    makes with the user, not a side effect of coming back up.
    """
    interrupted = journal.unsettled()
    for entry in interrupted:
        journal.record_settled(
            entry.request_id, "interrupted-not-repeated",
            "found unsettled at startup; a restart repeats nothing on its own",
        )
    # Compact: history that is fully settled collapses to nothing.
    journal.rewrite(())
    return {
        "interrupted": [
            {
                "requestId": entry.request_id,
                "providerId": entry.provider_id,
                "taskId": entry.task_id,
                "purpose": entry.purpose,
                "remote": entry.remote,
                "paid": entry.paid,
                "disposition": "interrupted-not-repeated",
            }
            for entry in interrupted
        ],
        "interruptedCount": len(interrupted),
        "paidInterrupted": sum(1 for entry in interrupted if entry.paid),
    }

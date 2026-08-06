# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What to do with a store the UX prototype left behind.

Development machines that ran the ``codex/companion-runtime-ux-shell`` branch
have a SQLite file — ``companion.sqlite3``, with ``companion_tasks`` and
``companion_events`` — written by a *different* companion runtime with a
different event vocabulary, a different task model and no hash chain. This
module deals with it, and the shape of what it does is the whole decision.

**It does not import that data into the canonical store, and it never will.**
Not because it would be difficult, but because it cannot be done truthfully.
The canonical stream is a hash chain in which every event follows a specific
predecessor; the donor stream has no chain, so importing would mean *minting*
hashes. Its event vocabulary — ``tool_requested``, ``speech_started``,
``response_drafting``, ``connection_lost`` — has no canonical equivalent, so
importing would mean *choosing* one. And a donor task whose last row says
``terminal=1`` would arrive in the canonical store as a completed task with no
events proving it completed, which is precisely the "invented task completion"
§20 forbids. A migration that manufactures a chain is a migration that launders
one, and :func:`companion.store.CompanionStore.migrate` already refuses to do
that to a stream of its own.

**What it does instead is archive.** :func:`import_donor_store` copies the
SQLite file itself, verifies the copy by digest, transcribes every row to JSON
beside it, and writes a manifest saying what was found and what could not be
established. Nothing enters ``sessions/``. The canonical store is not opened for
writing at any point, and rolling back is deleting one directory.

Everything §20 asks for holds because of that shape rather than in spite of it:

* the runtime-core store stays readable — it is never written;
* the donor store is preserved — it is copied, never moved or deleted;
* nothing is automatic — :func:`import_donor_store` defaults to a dry run and
  the caller must pass ``dry_run=False``;
* there is a backup — the copied database *is* it, with its digest recorded;
* uncertainty survives — a task the donor record cannot settle is transcribed
  with ``outcome: "uncertain"`` and stays that way;
* approvals are not copied unless every binding field is present, and the ones
  that are dropped are listed with the field that was missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from .errors import StoreError

__all__ = [
    "DONOR_TABLES",
    "DonorImportReport",
    "default_donor_paths",
    "import_donor_store",
    "inspect_donor_store",
    "rollback_donor_import",
]

#: The tables the donor store is known to have. A file without them is not a
#: donor companion store and is refused rather than read speculatively.
DONOR_TABLES = ("companion_meta", "companion_tasks", "companion_events")

#: Binding fields an approval decision must all carry to be transcribed as a
#: decision. §20: an approval whose binding is incomplete is not a decision, it
#: is a yes with nothing attached, and copying it forward would create consent
#: for an act nobody could name.
_APPROVAL_BINDING = ("requestId", "planId", "transitionId", "action", "destination")

#: Where a donor store is usually found, in the layout that branch used.
def default_donor_paths() -> tuple[Path, ...]:
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return (
        base / "bunny-companion" / "companion.sqlite3",
        base / "bunny-os" / "companion" / "companion.sqlite3",
    )


@dataclass
class DonorImportReport:
    """What the import found, did, and could not establish."""

    source: str = ""
    destination: str = ""
    dry_run: bool = True
    performed: bool = False
    source_digest: str = ""
    copy_digest: str = ""
    sessions: int = 0
    tasks: int = 0
    events: int = 0
    uncertain_tasks: tuple[str, ...] = ()
    withheld_approvals: tuple[tuple[str, str], ...] = ()
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "dryRun": self.dry_run,
            "performed": self.performed,
            "sourceDigest": self.source_digest,
            "copyDigest": self.copy_digest,
            "sessions": self.sessions,
            "tasks": self.tasks,
            "events": self.events,
            "uncertainTasks": list(self.uncertain_tasks),
            "withheldApprovals": [
                {"requestId": request_id, "reason": reason}
                for request_id, reason in self.withheld_approvals
            ],
            "problems": list(self.problems),
            "notes": list(self.notes),
            "ok": self.ok,
            "canonicalStoreModified": False,
        }


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _open_readonly(path: Path) -> sqlite3.Connection:
    """Open the donor database in a mode that cannot write to it.

    ``mode=ro`` in the URI, and ``immutable=0`` so a live WAL is still read
    correctly. The point is not performance: a migration tool that opened the
    old store read-write would create a journal beside it, and the first thing
    a nervous user does is check whether the old data was touched.
    """
    try:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise StoreError(f"{path} could not be opened for reading: {exc}") from exc


def inspect_donor_store(path: Path) -> dict[str, Any]:
    """Look at a donor store without changing anything at all."""
    path = Path(path)
    document: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "isDonorStore": False,
        "tables": [],
        "sessions": 0,
        "tasks": 0,
        "events": 0,
        "terminalTasks": 0,
        "problems": [],
        "supported": False,
        "disposition": (
            "unsupported development data: preserved, transcribed on request, "
            "and never merged into the canonical event store"
        ),
    }
    if not path.is_file():
        document["problems"] = [f"{path} does not exist"]
        return document
    if path.is_symlink():
        document["problems"] = [f"{path} is a symbolic link and was not followed"]
        return document
    connection = _open_readonly(path)
    try:
        tables = sorted(
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        )
        document["tables"] = tables
        missing = [name for name in DONOR_TABLES if name not in tables]
        if missing:
            document["problems"] = [
                f"{path} is not a companion UX store; it has no {', '.join(missing)}"
            ]
            return document
        document["isDonorStore"] = True
        document["tasks"] = connection.execute("SELECT count(*) FROM companion_tasks").fetchone()[0]
        document["events"] = connection.execute("SELECT count(*) FROM companion_events").fetchone()[0]
        document["sessions"] = connection.execute(
            "SELECT count(DISTINCT session_id) FROM companion_tasks"
        ).fetchone()[0]
        document["terminalTasks"] = connection.execute(
            "SELECT count(*) FROM companion_tasks WHERE terminal=1"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        document["problems"] = [f"{path} could not be read: {exc}"]
    finally:
        connection.close()
    return document


def import_donor_store(
    source: Path,
    root: Path,
    *,
    name: str = "ux-shell-sqlite",
    dry_run: bool = True,
) -> DonorImportReport:
    """Archive a donor store beside the canonical one. Never into it.

    ``dry_run=True`` is the default and reads everything, counts everything and
    reports everything without creating a file. A caller that wants the import
    has to say so; §20's "no automatic destructive migration" is met by there
    being no automatic migration of any kind.
    """
    source = Path(source)
    destination = Path(root) / "imported" / name
    report = DonorImportReport(
        source=str(source), destination=str(destination), dry_run=dry_run
    )
    inspection = inspect_donor_store(source)
    if inspection["problems"]:
        report.problems = tuple(str(item) for item in inspection["problems"])
        return report
    if not inspection["isDonorStore"]:
        report.problems = (f"{source} is not a companion UX store",)
        return report

    report.source_digest = _digest(source)
    report.sessions = int(inspection["sessions"])
    report.tasks = int(inspection["tasks"])
    report.events = int(inspection["events"])

    connection = _open_readonly(source)
    try:
        tasks, uncertain, withheld = _transcribe_tasks(connection)
        events = _transcribe_events(connection)
    finally:
        connection.close()
    report.uncertain_tasks = uncertain
    report.withheld_approvals = withheld
    report.notes = (
        "the canonical event store was not opened for writing and holds nothing from this import",
        "donor events are transcribed as they were found; no canonical event was constructed, "
        "because constructing one would mean minting a hash for a record that never had one",
        f"{len(uncertain)} task(s) could not be settled from the donor record and are marked uncertain",
    )
    if dry_run:
        return report

    if destination.exists():
        report.problems = (
            f"{destination} already exists; an import is performed once. Roll it back first.",
        )
        return report

    try:
        (destination / "source").mkdir(parents=True)
        try:
            destination.chmod(0o700)
            (destination / "source").chmod(0o700)
        except OSError:
            pass
        # The copy is the backup, and it is verified rather than assumed. A
        # backup nobody checked is a backup that is discovered to be empty on
        # the day it is needed.
        copy = destination / "source" / source.name
        shutil.copy2(source, copy)
        report.copy_digest = _digest(copy)
        if report.copy_digest != report.source_digest:
            report.problems = (
                "the copy of the donor store does not match the original by digest; "
                "the archive was left in place for inspection and nothing else was written",
            )
            return report
        _write(destination / "tasks.json", {"schemaVersion": 1, "tasks": tasks})
        _write(destination / "events.json", {"schemaVersion": 1, "events": events})
        _write(destination / "manifest.json", {
            "schemaVersion": 1,
            "kind": "bunny-companion-donor-archive",
            "origin": "codex/companion-runtime-ux-shell",
            "sourcePath": str(source),
            "sourceDigest": report.source_digest,
            "copyDigest": report.copy_digest,
            **report.to_json(),
            "authority": (
                "none. This is preserved development data from a superseded runtime. "
                "It is not a companion store, is never replayed, and no task in it is "
                "treated as having happened."
            ),
        })
    except OSError as exc:
        report.problems = (f"the archive could not be written: {exc}",)
        return report
    report.performed = True
    return report


def rollback_donor_import(root: Path, *, name: str = "ux-shell-sqlite") -> dict[str, Any]:
    """Undo an import. Removes the archive and nothing else.

    Safe because the import wrote nothing outside the archive: there is no
    canonical row to unpick, no event to retract and no projection to rebuild.
    The donor database at its original path is untouched by both directions.
    """
    destination = Path(root) / "imported" / name
    if not destination.is_dir():
        return {"removed": False, "destination": str(destination), "detail": "there was no import to roll back"}
    manifest = destination / "manifest.json"
    if not manifest.is_file():
        # Refused. This directory was not written by `import_donor_store`, and
        # removing a tree because it happens to sit at the expected path is how
        # a rollback becomes a data loss.
        return {
            "removed": False,
            "destination": str(destination),
            "detail": "this is not a donor archive — it has no manifest — and was left alone",
        }
    shutil.rmtree(destination)
    return {
        "removed": True,
        "destination": str(destination),
        "detail": "the archive was removed; the donor database at its original path is untouched",
    }


def _write(path: Path, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)


def _transcribe_tasks(
    connection: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[tuple[str, str], ...]]:
    tasks: list[dict[str, Any]] = []
    uncertain: list[str] = []
    withheld: list[tuple[str, str]] = []
    for task_id, session_id, terminal, updated_at, record in connection.execute(
        "SELECT task_id, session_id, terminal, updated_at, record_json "
        "FROM companion_tasks ORDER BY task_id"
    ):
        try:
            document = json.loads(record)
        except json.JSONDecodeError:
            document = {}
            uncertain.append(str(task_id))
        outcome = _outcome(bool(terminal), document)
        if outcome == "uncertain":
            uncertain.append(str(task_id))
        approvals, dropped = _approvals(document)
        withheld.extend(dropped)
        tasks.append({
            "taskId": str(task_id),
            "sessionId": str(session_id),
            "updatedAt": str(updated_at),
            "outcome": outcome,
            "donorRecord": document,
            "approvals": approvals,
        })
    return tasks, tuple(dict.fromkeys(uncertain)), tuple(withheld)


def _transcribe_events(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Copy the donor events out as they were found, and say what they are not.

    Deliberately *not* translated into canonical event types. The donor
    vocabulary — ``tool_requested``, ``speech_started``, ``response_drafting`` —
    has no canonical equivalent, and picking one would be inventing a record of
    something that was never written. They are transcribed verbatim, marked as
    having no chain, and are never replayed by anything.
    """
    events: list[dict[str, Any]] = []
    for event_id, task_id, session_id, sequence, occurred_at, event_type, record in connection.execute(
        "SELECT event_id, task_id, session_id, sequence, occurred_at, event_type, record_json "
        "FROM companion_events ORDER BY task_id, sequence"
    ):
        try:
            document = json.loads(record)
        except json.JSONDecodeError:
            document = {"unreadable": True}
        events.append({
            "eventId": str(event_id),
            "taskId": str(task_id),
            "sessionId": str(session_id),
            "sequence": int(sequence),
            "occurredAt": str(occurred_at),
            "donorEventType": str(event_type),
            "donorRecord": document,
            "canonicalEventType": None,
            "integrity": "none: the donor stream carried no hash chain",
        })
    return events


def _outcome(terminal: bool, document: dict[str, Any]) -> str:
    """What the donor record can actually establish about a task.

    ``terminal=1`` in the donor table means "no longer running", which is not
    the same claim as "completed". Only a donor phase that names its own
    ending is transcribed as that ending; everything else is ``uncertain``,
    including a task the donor marked terminal without saying how it ended.
    """
    phase = str(document.get("currentPhase", "")) if isinstance(document, dict) else ""
    if phase in ("completed", "failed", "cancelled"):
        return phase
    if terminal:
        return "uncertain"
    return "uncertain"


def _approvals(document: Any) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    if not isinstance(document, dict):
        return [], []
    raw = document.get("approvals")
    if not isinstance(raw, list):
        return [], []
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            dropped.append(("<unreadable>", "the approval record is not an object"))
            continue
        missing = [name for name in _APPROVAL_BINDING if not item.get(name)]
        if missing:
            dropped.append((
                str(item.get("requestId", "<unnamed>")),
                "the binding is incomplete: missing " + ", ".join(missing),
            ))
            continue
        kept.append({name: item[name] for name in _APPROVAL_BINDING} | {
            "decision": str(item.get("decision", "unknown")),
            "authority": "record only; this decision authorises nothing in the canonical runtime",
        })
    return kept, dropped

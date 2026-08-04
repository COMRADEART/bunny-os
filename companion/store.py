# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private SQLite persistence for task sessions and their event streams."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable

from .events import MAX_REPLAY_EVENTS, TaskEvent, canonical_event_bytes
from .model import TaskSession

STORE_SCHEMA_VERSION = 1
MAX_TASK_BYTES = 128 * 1024


class StoreError(RuntimeError):
    pass


class DuplicateEventError(StoreError):
    pass


class OutOfOrderEventError(StoreError):
    pass


@dataclass(frozen=True)
class AppendResult:
    event: TaskEvent
    appended: bool


def default_state_directory() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".local/state"
    return base / "bunny-companion"


def default_database_path() -> Path:
    return default_state_directory() / "companion.sqlite3"


def _private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise PermissionError(f"refusing symlinked companion state directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _assert_private_file(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink():
        raise PermissionError(f"refusing symlinked companion state file: {path}")
    status = path.stat()
    if os.name == "posix" and (status.st_uid != os.getuid() or status.st_mode & 0o077):
        raise PermissionError("companion state must be owned by and private to the session user")


class CompanionStore:
    """Event source plus task snapshots.

    The event stream is authoritative for presentation and audit.  The task
    snapshot is a bounded recovery accelerator and is replaced transactionally
    after each material task change.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or default_database_path())
        _private_directory(self.path.parent)
        _assert_private_file(self.path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._initialise()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _initialise(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS companion_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS companion_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    terminal INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS companion_tasks_session
                    ON companion_tasks(session_id, updated_at);
                CREATE TABLE IF NOT EXISTS companion_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    UNIQUE(task_id, sequence),
                    FOREIGN KEY(task_id) REFERENCES companion_tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS companion_events_replay
                    ON companion_events(task_id, sequence);
                INSERT OR IGNORE INTO companion_meta(key, value) VALUES('schemaVersion', '1');
                COMMIT;
                """
            )
            version = self._connection.execute(
                "SELECT value FROM companion_meta WHERE key='schemaVersion'"
            ).fetchone()
            if version is None or int(version["value"]) != STORE_SCHEMA_VERSION:
                raise StoreError("unsupported companion store schema")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "CompanionStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def save_task(self, task: TaskSession) -> None:
        document = task.to_json()
        encoded = canonical_event_bytes(document)
        if len(encoded) > MAX_TASK_BYTES:
            raise StoreError(f"task record exceeds {MAX_TASK_BYTES} bytes")
        payload = encoded.decode("utf-8")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO companion_tasks(task_id, session_id, terminal, updated_at, record_json)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    terminal=excluded.terminal,
                    updated_at=excluded.updated_at,
                    record_json=excluded.record_json
                """,
                (task.task_id, task.session_id, int(task.terminal), task.completed_at or task.created_at, payload),
            )

    def load_task(self, task_id: str) -> TaskSession | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM companion_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return TaskSession.from_json(json.loads(row["record_json"]))

    def list_tasks(self, *, session_id: str | None = None, include_terminal: bool = True) -> tuple[TaskSession, ...]:
        conditions: list[str] = []
        values: list[Any] = []
        if session_id is not None:
            conditions.append("session_id=?")
            values.append(session_id)
        if not include_terminal:
            conditions.append("terminal=0")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT record_json FROM companion_tasks{where} ORDER BY updated_at, task_id", values
            ).fetchall()
        return tuple(TaskSession.from_json(json.loads(row["record_json"])) for row in rows)

    @staticmethod
    def _same_event(left: TaskEvent, right: TaskEvent) -> bool:
        first = left.to_json()
        second = right.to_json()
        first["sequence"] = 0
        second["sequence"] = 0
        return canonical_event_bytes(first) == canonical_event_bytes(second)

    def append(self, event: TaskEvent) -> AppendResult:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._connection.execute(
                    "SELECT record_json FROM companion_events WHERE event_id=?", (event.event_id,)
                ).fetchone()
                if existing is not None:
                    restored = TaskEvent.from_json(json.loads(existing["record_json"]))
                    if not self._same_event(restored, event):
                        raise DuplicateEventError(
                            f"event id {event.event_id} was replayed with different content"
                        )
                    self._connection.execute("COMMIT")
                    return AppendResult(restored, False)

                task = self._connection.execute(
                    "SELECT session_id FROM companion_tasks WHERE task_id=?", (event.task_id,)
                ).fetchone()
                if task is None:
                    raise StoreError("event task does not exist")
                if task["session_id"] != event.session_id:
                    raise StoreError("event session does not match its task")
                latest = self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS latest FROM companion_events WHERE task_id=?",
                    (event.task_id,),
                ).fetchone()
                expected = int(latest["latest"]) + 1
                if event.sequence not in (0, expected):
                    raise OutOfOrderEventError(
                        f"task {event.task_id} expected event {expected}, received {event.sequence}"
                    )
                stored = event.with_sequence(expected)
                payload = canonical_event_bytes(stored.to_json()).decode("utf-8")
                self._connection.execute(
                    """
                    INSERT INTO companion_events(
                        event_id, task_id, session_id, sequence, occurred_at, event_type, record_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored.event_id,
                        stored.task_id,
                        stored.session_id,
                        stored.sequence,
                        stored.occurred_at,
                        stored.event_type,
                        payload,
                    ),
                )
                self._connection.execute("COMMIT")
                return AppendResult(stored, True)
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def append_many(self, events: Iterable[TaskEvent]) -> tuple[AppendResult, ...]:
        return tuple(self.append(event) for event in events)

    def replay(self, task_id: str, *, after_sequence: int = 0, limit: int = MAX_REPLAY_EVENTS) -> tuple[TaskEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if not 1 <= limit <= MAX_REPLAY_EVENTS:
            raise ValueError(f"replay limit must be between 1 and {MAX_REPLAY_EVENTS}")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT record_json FROM companion_events
                WHERE task_id=? AND sequence>?
                ORDER BY sequence ASC LIMIT ?
                """,
                (task_id, after_sequence, limit),
            ).fetchall()
        return tuple(TaskEvent.from_json(json.loads(row["record_json"])) for row in rows)

    def latest_sequence(self, task_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS latest FROM companion_events WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return int(row["latest"])

    def event_count(self, task_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM companion_events WHERE task_id=?", (task_id,)
            ).fetchone()
        return int(row["count"])

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Layer 2 — disposable SQLite index.

Never authoritative. ``reindex`` deletes and rebuilds from files. A failed
FTS5 probe or a failed open degrades to file scan. No ANN, no HNSW, no
embedding BLOBs in v1 — the column is omitted rather than reserved-as-used.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence

from companion.errors import MemoryError
from companion.memory.record import MemoryRecord

__all__ = [
    "INDEX_FILE_NAME",
    "MemoryIndex",
    "probe_fts5",
]

INDEX_FILE_NAME = "memory.sqlite"

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    rev INTEGER NOT NULL,
    plugin TEXT NOT NULL,
    category TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    state TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    expires_at TEXT,
    taints TEXT NOT NULL,
    confirmation TEXT NOT NULL,
    writer_kind TEXT NOT NULL,
    snippet TEXT NOT NULL,
    file_path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS derivation_edge (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    parent_rev INTEGER NOT NULL,
    parent_body_hash TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id),
    FOREIGN KEY (child_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES records(id) ON DELETE CASCADE
);
"""


def probe_fts5(connection: sqlite3.Connection) -> bool:
    """Runtime capability probe. Documentation is not evidence."""
    try:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        connection.execute("DROP TABLE IF EXISTS _fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


class MemoryIndex:
    """Derived index. Rebuild it; never treat a miss as a missing file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fts5 = False
        self.available = False
        self.failure: str | None = None

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def open(self) -> None:
        try:
            connection = self.connect()
            try:
                connection.executescript(_SCHEMA)
                self.fts5 = probe_fts5(connection)
                if self.fts5:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS records_fts "
                        "USING fts5(id UNINDEXED, text)"
                    )
                connection.commit()
                self.available = True
                self.failure = None
            finally:
                connection.close()
        except sqlite3.Error as exc:
            self.available = False
            self.fts5 = False
            self.failure = str(exc)

    def wipe(self) -> None:
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError as exc:
                raise MemoryError(f"could not drop disposable index: {exc}") from exc
        for sidecar in (
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
        ):
            try:
                sidecar.unlink()
            except OSError:
                pass
        self.available = False
        self.fts5 = False

    def replace_all(self, records: Iterable[tuple[MemoryRecord, Path]]) -> int:
        """Rebuild from files. The only legal way to populate the index."""
        self.wipe()
        self.open()
        if not self.available:
            return 0
        count = 0
        connection = self.connect()
        try:
            for record, path in records:
                if record.state in ("tombstoned", "shredded"):
                    continue
                self._upsert(connection, record, path)
                count += 1
            connection.commit()
        finally:
            connection.close()
        return count

    def upsert(self, record: MemoryRecord, path: Path) -> None:
        if not self.available:
            return
        connection = self.connect()
        try:
            self._upsert(connection, record, path)
            connection.commit()
        except sqlite3.Error as exc:
            self.available = False
            self.failure = str(exc)
        finally:
            connection.close()

    def delete(self, record_id: str) -> None:
        if not self.available:
            return
        connection = self.connect()
        try:
            connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
            if self.fts5:
                connection.execute("DELETE FROM records_fts WHERE id = ?", (record_id,))
            connection.commit()
        except sqlite3.Error as exc:
            self.available = False
            self.failure = str(exc)
        finally:
            connection.close()

    def children_of(self, record_id: str) -> tuple[str, ...]:
        if not self.available:
            return ()
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT child_id FROM derivation_edge WHERE parent_id = ?",
                (record_id,),
            ).fetchall()
            return tuple(str(row["child_id"]) for row in rows)
        except sqlite3.Error:
            return ()
        finally:
            connection.close()

    def search(
        self,
        *,
        text: str = "",
        plugin: str | None = None,
        category: str | None = None,
        scope_kind: str | None = None,
        scope_id: str | None = None,
        state: str = "active",
        limit: int = 8,
    ) -> tuple[dict[str, Any], ...]:
        if not self.available:
            raise MemoryError("index unavailable")
        clauses = ["state = ?"]
        values: list[object] = [state]
        if plugin:
            clauses.append("plugin = ?")
            values.append(plugin)
        if category:
            clauses.append("category = ?")
            values.append(category)
        if scope_kind:
            clauses.append("scope_kind = ?")
            values.append(scope_kind)
        if scope_id:
            clauses.append("scope_id = ?")
            values.append(scope_id)
        where = " AND ".join(clauses)
        connection = self.connect()
        try:
            if text and self.fts5:
                try:
                    rows = connection.execute(
                        "SELECT records.* FROM records "
                        "JOIN records_fts ON records.id = records_fts.id "
                        "WHERE records_fts MATCH ? AND " + where + " "
                        "ORDER BY recorded_at DESC LIMIT ?",
                        (text, *values, limit),
                    ).fetchall()
                    return tuple(dict(row) for row in rows)
                except sqlite3.OperationalError:
                    pass
            if text:
                clauses.append("(snippet LIKE ? OR body_hash = ? OR id = ?)")
                values.extend((f"%{text}%", text, text))
                where = " AND ".join(clauses)
            rows = connection.execute(
                f"SELECT * FROM records WHERE {where} "
                "ORDER BY recorded_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            connection.close()

    def _upsert(self, connection: sqlite3.Connection, record: MemoryRecord, path: Path) -> None:
        snippet = record.snippet()
        connection.execute(
            "INSERT INTO records ("
            "id, rev, plugin, category, scope_kind, scope_id, owner, "
            "sensitivity, state, body_hash, valid_from, valid_to, observed_at, "
            "recorded_at, expires_at, taints, confirmation, writer_kind, "
            "snippet, file_path"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "rev=excluded.rev, plugin=excluded.plugin, category=excluded.category, "
            "scope_kind=excluded.scope_kind, scope_id=excluded.scope_id, "
            "owner=excluded.owner, sensitivity=excluded.sensitivity, "
            "state=excluded.state, body_hash=excluded.body_hash, "
            "valid_from=excluded.valid_from, valid_to=excluded.valid_to, "
            "observed_at=excluded.observed_at, recorded_at=excluded.recorded_at, "
            "expires_at=excluded.expires_at, taints=excluded.taints, "
            "confirmation=excluded.confirmation, writer_kind=excluded.writer_kind, "
            "snippet=excluded.snippet, file_path=excluded.file_path",
            (
                record.id, record.rev, record.plugin, record.category,
                record.scope_kind, record.scope_id, record.owner,
                record.sensitivity, record.state, record.body_hash,
                record.valid_from, record.valid_to, record.observed_at,
                record.recorded_at, record.expires_at,
                json.dumps(list(record.taints)), record.confirmation,
                record.writer_kind, snippet, str(path),
            ),
        )
        connection.execute("DELETE FROM derivation_edge WHERE child_id = ?", (record.id,))
        for parent in record.derived_from:
            parent_id = str(parent.get("id") or "")
            if not parent_id:
                continue
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO derivation_edge "
                    "(child_id, parent_id, parent_rev, parent_body_hash) "
                    "VALUES (?,?,?,?)",
                    (
                        record.id,
                        parent_id,
                        int(parent.get("rev") or 1),
                        str(parent.get("body_hash") or parent.get("bodyHash") or ""),
                    ),
                )
            except sqlite3.IntegrityError:
                # Parent not in the index yet (reindex order). Files remain
                # authoritative; the next reindex after both exist links them.
                pass
        if self.fts5:
            connection.execute("DELETE FROM records_fts WHERE id = ?", (record.id,))
            searchable = " ".join(
                part for part in (record.id, record.plugin, record.category, snippet, record.body_text if not record.is_sensitive else "")
                if part
            )
            connection.execute(
                "INSERT INTO records_fts(id, text) VALUES (?, ?)",
                (record.id, searchable),
            )

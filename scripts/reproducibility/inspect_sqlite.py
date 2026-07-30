#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure a SQLite database's structure, so a byte difference can be explained.

Two builds produced ``usr/share/rpm/rpmdb.sqlite`` files of identical length and
different content. "SQLite page allocation" is the obvious explanation and it is
not evidence; this reads the file header, every PRAGMA the brief names, the full
schema and the shape of every table, so the explanation is a measurement.

The database is opened read-only through a URI. That matters more than it looks:
opening a SQLite database read-write increments the file change counter in the
header even if nothing is written, so an inspector that opened normally would
alter the fourth field of the very structure it exists to report.

The header is parsed from the raw bytes rather than asked for through PRAGMAs.
Some of what the brief requires — the change counter, the version-valid-for
field, the SQLite version that last wrote the file — has no PRAGMA at all, and
the fields that do have one are worth cross-checking against the bytes.

Where the file is inspected matters too. ``--require-sqlite-version`` exists so
a qualification caller can refuse a measurement taken with a different SQLite
than the one the finaliser uses; a structural report produced by another library
version describes a different on-disk format contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import sys
from typing import Any

REFUSED = 2

#: Offsets and widths of the 100-byte database header, from the SQLite file
#: format specification. Named here rather than inline so the report and the
#: specification can be read side by side.
HEADER_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("pageSizeField", 16, 2),
    ("writeVersion", 18, 1),
    ("readVersion", 19, 1),
    ("reservedBytesPerPage", 20, 1),
    ("maxEmbeddedPayloadFraction", 21, 1),
    ("minEmbeddedPayloadFraction", 22, 1),
    ("leafPayloadFraction", 23, 1),
    ("fileChangeCounter", 24, 4),
    ("databaseSizeInPages", 28, 4),
    ("firstFreelistTrunkPage", 32, 4),
    ("freelistPageCount", 36, 4),
    ("schemaCookie", 40, 4),
    ("schemaFormatNumber", 44, 4),
    ("defaultPageCacheSize", 48, 4),
    ("largestRootBTreePage", 52, 4),
    ("textEncodingField", 56, 4),
    ("userVersionField", 60, 4),
    ("incrementalVacuumMode", 64, 4),
    ("applicationIdField", 68, 4),
    ("versionValidForNumber", 92, 4),
    ("sqliteVersionNumber", 96, 4),
)

TEXT_ENCODING = {1: "UTF-8", 2: "UTF-16le", 3: "UTF-16be"}

SIMPLE_PRAGMAS = (
    "encoding",
    "page_size",
    "page_count",
    "freelist_count",
    "auto_vacuum",
    "journal_mode",
    "synchronous",
    "schema_version",
    "user_version",
    "application_id",
    "locking_mode",
    "temp_store",
    "cache_size",
    "max_page_count",
    "secure_delete",
    "legacy_file_format",
)


def parse_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(100)
    if len(raw) < 100:
        raise SystemExit(f"BLOCKED: {path} is shorter than a SQLite header")
    magic = raw[:16]
    if magic != b"SQLite format 3\x00":
        raise SystemExit(f"BLOCKED: {path} does not carry the SQLite format 3 magic")

    header: dict[str, Any] = {"magic": magic.decode("ascii", "replace").rstrip("\x00")}
    for name, offset, width in HEADER_FIELDS:
        chunk = raw[offset : offset + width]
        if width == 1:
            value = chunk[0]
        elif width == 2:
            value = struct.unpack(">H", chunk)[0]
        else:
            value = struct.unpack(">I", chunk)[0]
        header[name] = value

    # A page-size field of 1 means 65536; the field is 16 bits and cannot hold it.
    if header["pageSizeField"] == 1:
        header["pageSizeBytes"] = 65536
    else:
        header["pageSizeBytes"] = header["pageSizeField"]

    header["textEncoding"] = TEXT_ENCODING.get(
        header["textEncodingField"], f"unknown({header['textEncodingField']})"
    )
    header["writeFormat"] = {1: "rollback-journal", 2: "wal"}.get(
        header["writeVersion"], f"unknown({header['writeVersion']})"
    )
    header["readFormat"] = {1: "rollback-journal", 2: "wal"}.get(
        header["readVersion"], f"unknown({header['readVersion']})"
    )
    number = header["sqliteVersionNumber"]
    header["sqliteVersionThatLastWrote"] = (
        f"{number // 1000000}.{(number // 1000) % 1000}.{number % 1000}"
    )
    header["headerSha256"] = hashlib.sha256(raw).hexdigest()
    return header


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open without taking a write lock and without touching the change counter."""
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.text_factory = bytes
    return connection


def _rows(connection: sqlite3.Connection, statement: str, *parameters: Any) -> list[tuple]:
    cursor = connection.execute(statement, parameters)
    try:
        return cursor.fetchall()
    finally:
        cursor.close()


def _text(value: Any) -> Any:
    """Decode the bytes text_factory hands back, keeping real blobs distinguishable."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return {"blobSha256": hashlib.sha256(value).hexdigest(), "blobLength": len(value)}
    return value


def _scalar(connection: sqlite3.Connection, statement: str) -> Any:
    rows = _rows(connection, statement)
    if not rows or not rows[0]:
        return None
    return _text(rows[0][0])


def collect_pragmas(connection: sqlite3.Connection) -> dict[str, Any]:
    pragmas: dict[str, Any] = {}
    for name in SIMPLE_PRAGMAS:
        try:
            pragmas[name] = _scalar(connection, f"PRAGMA {name}")
        except sqlite3.Error as error:
            pragmas[name] = {"error": str(error)}
    pragmas["compile_options"] = sorted(
        str(_text(row[0])) for row in _rows(connection, "PRAGMA compile_options")
    )
    pragmas["database_list"] = [
        {"seq": row[0], "name": _text(row[1]), "file": _text(row[2])}
        for row in _rows(connection, "PRAGMA database_list")
    ]
    pragmas["integrity_check"] = [
        str(_text(row[0])) for row in _rows(connection, "PRAGMA integrity_check")
    ]
    pragmas["quick_check"] = [
        str(_text(row[0])) for row in _rows(connection, "PRAGMA quick_check")
    ]
    pragmas["foreign_key_check"] = [
        [_text(cell) for cell in row] for row in _rows(connection, "PRAGMA foreign_key_check")
    ]
    return pragmas


def _table_list(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """``PRAGMA table_list`` answers WITHOUT ROWID and STRICT directly.

    Deriving those from the schema text was the alternative and it is worse: a
    table declared ``WITHOUT ROWID`` inside a comment, or across a line break,
    would be classified by a regular expression rather than by SQLite.
    """
    listed: dict[str, dict[str, Any]] = {}
    try:
        rows = _rows(connection, "PRAGMA table_list")
    except sqlite3.Error:
        return listed
    for row in rows:
        schema, name, kind, columns, without_rowid, strict = (
            _text(row[0]),
            _text(row[1]),
            _text(row[2]),
            row[3],
            row[4],
            row[5],
        )
        if schema != "main":
            continue
        listed[str(name)] = {
            "type": kind,
            "declaredColumnCount": columns,
            "withoutRowid": bool(without_rowid),
            "strict": bool(strict),
        }
    return listed


def describe_objects(connection: sqlite3.Connection) -> dict[str, Any]:
    schema_rows = _rows(
        connection,
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_schema ORDER BY type, name",
    )
    objects = [
        {
            "type": _text(row[0]),
            "name": _text(row[1]),
            "table": _text(row[2]),
            "rootPage": row[3],
            "sql": _text(row[4]),
        }
        for row in schema_rows
    ]

    listed = _table_list(connection)
    tables: dict[str, Any] = {}
    for entry in objects:
        if entry["type"] != "table":
            continue
        name = str(entry["name"])
        meta = listed.get(name, {})
        is_virtual = bool(entry["sql"] and re.match(r"(?is)^\s*CREATE\s+VIRTUAL\s+TABLE", str(entry["sql"])))

        columns = []
        blob_columns = []
        generated = []
        try:
            info = _rows(connection, f'PRAGMA table_xinfo("{name}")')
        except sqlite3.Error:
            info = []
        for cid, column_name, declared, notnull, default, pk, *rest in info:
            hidden = rest[0] if rest else 0
            column_name = str(_text(column_name))
            declared = str(_text(declared) or "")
            record = {
                "cid": cid,
                "name": column_name,
                "declaredType": declared,
                "notNull": bool(notnull),
                "default": _text(default),
                "primaryKeyPosition": pk,
                "hidden": hidden,
            }
            columns.append(record)
            if declared.upper().startswith("BLOB"):
                blob_columns.append(column_name)
            # hidden 2 is a VIRTUAL generated column, 3 is STORED.
            if hidden in (2, 3):
                generated.append({"column": column_name, "kind": "virtual" if hidden == 2 else "stored"})

        primary_key = [
            column["name"]
            for column in sorted(
                (item for item in columns if item["primaryKeyPosition"]),
                key=lambda item: item["primaryKeyPosition"],
            )
        ]

        row_count = None
        if not is_virtual:
            try:
                row_count = _scalar(connection, f'SELECT COUNT(*) FROM "{name}"')
            except sqlite3.Error as error:
                row_count = {"error": str(error)}

        has_rowid = not meta.get("withoutRowid", False) and not is_virtual
        # A table can be a rowid table and still have no usable rowid alias; what
        # matters for canonical ordering is whether `rowid` can be selected.
        rowid_selectable = False
        if has_rowid:
            try:
                _rows(connection, f'SELECT rowid FROM "{name}" LIMIT 1')
                rowid_selectable = True
            except sqlite3.Error:
                rowid_selectable = False

        tables[name] = {
            "sql": entry["sql"],
            "rootPage": entry["rootPage"],
            "virtual": is_virtual,
            "withoutRowid": meta.get("withoutRowid", False),
            "strict": meta.get("strict", False),
            "columns": columns,
            "columnCount": len(columns),
            "primaryKey": primary_key,
            "compositePrimaryKey": len(primary_key) > 1,
            "hasRowid": has_rowid,
            "rowidSelectable": rowid_selectable,
            "blobColumns": blob_columns,
            "generatedColumns": generated,
            "rowCount": row_count,
        }

    indexes: dict[str, Any] = {}
    for entry in objects:
        if entry["type"] != "index":
            continue
        name = str(entry["name"])
        columns = []
        collations = []
        try:
            for row in _rows(connection, f'PRAGMA index_xinfo("{name}")'):
                seqno, cid, column_name, desc, coll, key = row
                columns.append(
                    {
                        "seqno": seqno,
                        "cid": cid,
                        "name": _text(column_name),
                        "descending": bool(desc),
                        "collation": _text(coll),
                        "isKey": bool(key),
                    }
                )
                collation = _text(coll)
                if collation:
                    collations.append(str(collation))
        except sqlite3.Error as error:
            columns = [{"error": str(error)}]
        indexes[name] = {
            "table": entry["table"],
            # An index SQL of NULL is an implicit index SQLite created for a
            # UNIQUE or PRIMARY KEY constraint. It is still part of the physical
            # layout, so it is reported rather than skipped.
            "sql": entry["sql"],
            "implicit": entry["sql"] is None,
            "rootPage": entry["rootPage"],
            "columns": columns,
            "collations": sorted(set(collations)),
        }

    triggers = {
        str(entry["name"]): {"table": entry["table"], "sql": entry["sql"]}
        for entry in objects
        if entry["type"] == "trigger"
    }
    views = {
        str(entry["name"]): {"sql": entry["sql"]}
        for entry in objects
        if entry["type"] == "view"
    }

    schema_sql = "\n".join(
        str(entry["sql"]) for entry in objects if entry["sql"]
    )

    return {
        "objects": objects,
        "tables": tables,
        "indexes": indexes,
        "triggers": triggers,
        "views": views,
        "tableCount": len(tables),
        "indexCount": len(indexes),
        "triggerCount": len(triggers),
        "viewCount": len(views),
        "virtualTables": sorted(name for name, meta in tables.items() if meta["virtual"]),
        "withoutRowidTables": sorted(name for name, meta in tables.items() if meta["withoutRowid"]),
        "schemaSql": schema_sql,
        "schemaSha256": hashlib.sha256(schema_sql.encode("utf-8")).hexdigest(),
        "collationsInSchema": sorted(
            set(re.findall(r"(?i)\bCOLLATE\s+([A-Za-z_][A-Za-z0-9_]*)", schema_sql))
        ),
    }


def _stream_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def inspect(path: Path, *, owner: str | None = None) -> dict[str, Any]:
    header = parse_header(path)
    connection = open_readonly(path)
    try:
        pragmas = collect_pragmas(connection)
        structure = describe_objects(connection)
    finally:
        connection.close()

    integrity = pragmas["integrity_check"]
    quick = pragmas["quick_check"]

    return {
        "schemaVersion": 1,
        "path": str(path),
        "fileName": path.name,
        "fileSize": path.stat().st_size,
        "fileSha256": _stream_digest(path),
        "packageManagerOwner": owner,
        "inspectedWith": {
            "sqliteLibraryVersion": sqlite3.sqlite_version,
            "sqliteLibraryVersionNumber": sqlite3.sqlite_version_info,
            "python": sys.version.split()[0],
        },
        "header": header,
        "pragmas": pragmas,
        "structure": structure,
        "integrityOk": integrity == ["ok"],
        "quickCheckOk": quick == ["ok"],
        "sidecars": {
            "wal": (path.parent / (path.name + "-wal")).exists(),
            "shm": (path.parent / (path.name + "-shm")).exists(),
            "journal": (path.parent / (path.name + "-journal")).exists(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="inspect_sqlite")
    parser.add_argument("--database", required=True, action="append", type=Path)
    parser.add_argument(
        "--owner",
        action="append",
        default=None,
        help="package-manager owner of the corresponding --database; repeatable",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--require-sqlite-version",
        help="exit 2 unless the linked SQLite library is exactly this version",
    )
    parser.add_argument(
        "--require-integrity",
        action="store_true",
        help="exit 2 when any database fails integrity_check or quick_check",
    )
    args = parser.parse_args()

    if args.require_sqlite_version and sqlite3.sqlite_version != args.require_sqlite_version:
        raise SystemExit(
            f"BLOCKED: this inspection is linked against SQLite {sqlite3.sqlite_version}, and "
            f"{args.require_sqlite_version} was required. A structural report taken with a "
            "different library describes a different on-disk format contract, and comparing one "
            "against the other would attribute a library difference to the build."
        )

    owners = args.owner or []
    databases = []
    for position, path in enumerate(args.database):
        if not path.is_file():
            raise SystemExit(f"BLOCKED: database does not exist: {path}")
        owner = owners[position] if position < len(owners) else None
        databases.append(inspect(path, owner=owner))

    payload = {
        "schemaVersion": 1,
        "sqliteLibraryVersion": sqlite3.sqlite_version,
        "databases": databases,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    unhealthy = [
        entry["path"] for entry in databases if not (entry["integrityOk"] and entry["quickCheckOk"])
    ]
    for entry in databases:
        header = entry["header"]
        print(
            f"{entry['fileName']}: {entry['fileSize']} bytes, "
            f"page {header['pageSizeBytes']}, {header['databaseSizeInPages']} pages, "
            f"freelist {header['freelistPageCount']}, "
            f"schema cookie {header['schemaCookie']}, "
            f"change counter {header['fileChangeCounter']}, "
            f"{entry['structure']['tableCount']} tables, "
            f"{entry['structure']['indexCount']} indexes, "
            f"integrity {'ok' if entry['integrityOk'] else 'FAILED'}"
        )
    print(f"wrote {args.output}")

    if unhealthy and args.require_integrity:
        raise SystemExit(
            "BLOCKED: integrity check failed for " + ", ".join(unhealthy)
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

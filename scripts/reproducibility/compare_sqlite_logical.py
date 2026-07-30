#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two SQLite databases by content, as a diagnostic beside the byte gate.

This exists to explain a byte difference, not to excuse one. A
``LOGICALLY_IDENTICAL`` result here says the two databases hold the same rows and
therefore that the byte difference is an encoding difference; it does **not**
satisfy the reproducibility requirement, which is that the files match. Nothing
in this module writes a gate decision, and the reproducibility gate does not read
its output as evidence of equality.

Type fidelity is the whole difficulty. SQLite stores five storage classes and a
comparison that stringified them would report ``NULL``, the empty string and the
integer zero as the same value — which is how a real difference gets normalised
into a false match. Every value is therefore tagged with the class SQLite
reports through ``typeof()``, and blobs are carried as a digest with their length
rather than decoded.

Row ordering is chosen per table and recorded per table:

    primary-key         ordered by the declared primary key
    rowid               ordered by rowid, for a rowid table with no declared key
    full-row-multiset   sorted by the canonical form of the whole row
    unavailable         virtual tables and anything whose rows cannot be read

``full-row-multiset`` compares the two tables as multisets, which is the right
comparison for asking "is the content the same" and is deliberately blind to
insertion order. Insertion order is reported separately, in ``rowidOrderMatches``,
because a table whose rows match as a multiset and differ in rowid order is the
signature of a nondeterministic writer and that is worth knowing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

REFUSED = 2

IDENTICAL = "LOGICALLY_IDENTICAL"
DIFFERENT = "LOGICALLY_DIFFERENT"
INCONCLUSIVE = "INCONCLUSIVE"

BLOB_INLINE_LIMIT = 96


def canonical_value(value: Any, storage_class: str) -> list[Any]:
    """A type-tagged form of one cell, exact enough to compare on."""
    if storage_class == "null" or value is None:
        return ["null"]
    if storage_class == "integer":
        return ["integer", str(int(value))]
    if storage_class == "real":
        # float.hex() is exact; repr() is not guaranteed to be across builds.
        return ["real", float(value).hex()]
    if storage_class == "blob":
        raw = bytes(value)
        record: list[Any] = ["blob", str(len(raw)), hashlib.sha256(raw).hexdigest()]
        if len(raw) <= BLOB_INLINE_LIMIT:
            record.append(raw.hex())
        return record
    if isinstance(value, bytes):
        try:
            return ["text", value.decode("utf-8")]
        except UnicodeDecodeError:
            return ["text-invalid-utf8", hashlib.sha256(value).hexdigest()]
    return ["text", str(value)]


def canonical_row(row: tuple, classes: tuple) -> list[list[Any]]:
    return [canonical_value(value, str(cls)) for value, cls in zip(row, classes)]


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.text_factory = bytes
    return connection


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def schema_of(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
    ).fetchall()
    entries = [
        {
            "type": _decode(kind),
            "name": _decode(name),
            "table": _decode(table),
            "sql": _decode(sql),
        }
        for kind, name, table, sql in rows
    ]
    return {
        "objects": entries,
        "tables": sorted(
            str(entry["name"]) for entry in entries if entry["type"] == "table"
        ),
        "indexes": {
            str(entry["name"]): entry["sql"]
            for entry in entries
            if entry["type"] == "index"
        },
        "triggers": {
            str(entry["name"]): entry["sql"]
            for entry in entries
            if entry["type"] == "trigger"
        },
        "views": {
            str(entry["name"]): entry["sql"]
            for entry in entries
            if entry["type"] == "view"
        },
        "digest": hashlib.sha256(
            json.dumps(entries, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def table_plan(connection: sqlite3.Connection, name: str) -> dict[str, Any]:
    """Decide how this table's rows are to be ordered, and say why."""
    is_virtual = False
    row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)
    ).fetchone()
    if row and row[0]:
        is_virtual = bool(re.match(r"(?is)^\s*CREATE\s+VIRTUAL\s+TABLE", str(_decode(row[0]))))

    without_rowid = False
    try:
        for entry in connection.execute("PRAGMA table_list").fetchall():
            if _decode(entry[0]) == "main" and _decode(entry[1]) == name:
                without_rowid = bool(entry[4])
    except sqlite3.Error:
        pass

    columns = []
    primary_key: list[tuple[int, str]] = []
    for cid, column, declared, notnull, default, pk in connection.execute(
        f'PRAGMA table_info("{name}")'
    ).fetchall():
        column = str(_decode(column))
        columns.append(column)
        if pk:
            primary_key.append((int(pk), column))
    key_columns = [column for _, column in sorted(primary_key)]

    if is_virtual:
        return {
            "columns": columns,
            "virtual": True,
            "withoutRowid": without_rowid,
            "primaryKey": key_columns,
            "ordering": "unavailable",
            "orderingReason": "virtual table; its rows are produced by a module, not stored",
        }

    if key_columns:
        ordering = "primary-key"
        reason = "ordered by the declared primary key"
    elif not without_rowid:
        ordering = "rowid"
        reason = "rowid table with no declared primary key; ordered by rowid"
    else:
        ordering = "full-row-multiset"
        reason = (
            "WITHOUT ROWID table with no readable declared key; compared as a multiset of "
            "canonical rows"
        )

    return {
        "columns": columns,
        "virtual": False,
        "withoutRowid": without_rowid,
        "primaryKey": key_columns,
        "compositePrimaryKey": len(key_columns) > 1,
        "ordering": ordering,
        "orderingReason": reason,
    }


def read_table(connection: sqlite3.Connection, name: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Read every row as a canonical, type-tagged structure."""
    if plan["ordering"] == "unavailable":
        return {"rows": None, "rowidOrder": None, "unreadable": plan["orderingReason"]}

    columns = plan["columns"]
    quoted = ", ".join(f'"{column}"' for column in columns)
    type_expression = ", ".join(f'typeof("{column}")' for column in columns)
    width = len(columns)

    select_rowid = plan["ordering"] == "rowid" or (
        not plan["withoutRowid"] and not plan["virtual"]
    )
    prefix = "rowid, " if select_rowid else ""
    statement = f'SELECT {prefix}{quoted}, {type_expression} FROM "{name}"'
    if plan["ordering"] == "rowid":
        statement += " ORDER BY rowid"
    elif plan["ordering"] == "primary-key":
        statement += " ORDER BY " + ", ".join(f'"{column}"' for column in plan["primaryKey"])

    try:
        cursor = connection.execute(statement)
    except sqlite3.Error as error:
        return {"rows": None, "rowidOrder": None, "unreadable": str(error)}

    in_read_order: list[list[list[Any]]] = []
    rowid_sequence: list[Any] = []
    for record in cursor:
        offset = 1 if select_rowid else 0
        if select_rowid:
            rowid_sequence.append(record[0])
        values = record[offset : offset + width]
        classes = record[offset + width : offset + 2 * width]
        in_read_order.append(canonical_row(tuple(values), tuple(_decode(c) for c in classes)))
    cursor.close()

    # The comparable form is always sorted, so a table whose declared ordering
    # still leaves ties compares as a multiset rather than by luck of retrieval.
    encoded = [json.dumps(row, sort_keys=True, separators=(",", ":")) for row in in_read_order]
    return {
        "rows": sorted(encoded),
        "readOrder": encoded,
        "rowidOrder": [str(value) for value in rowid_sequence] if select_rowid else None,
        "unreadable": None,
    }


def digest_of(encoded: list[str]) -> str:
    value = hashlib.sha256()
    for line in encoded:
        value.update(line.encode("utf-8"))
        value.update(b"\n")
    return value.hexdigest()


def compare(first: Path, second: Path, *, sample: int) -> dict[str, Any]:
    left = _connect(first)
    right = _connect(second)
    try:
        left_schema = schema_of(left)
        right_schema = schema_of(right)

        schema_match = left_schema["digest"] == right_schema["digest"]
        tables = sorted(set(left_schema["tables"]) | set(right_schema["tables"]))

        results: dict[str, Any] = {}
        inconclusive: list[str] = []
        differing: list[str] = []

        for name in tables:
            if name not in left_schema["tables"] or name not in right_schema["tables"]:
                results[name] = {
                    "verdict": DIFFERENT,
                    "reason": "table present in only one database",
                    "presentInA": name in left_schema["tables"],
                    "presentInB": name in right_schema["tables"],
                }
                differing.append(name)
                continue

            left_plan = table_plan(left, name)
            right_plan = table_plan(right, name)
            if left_plan["ordering"] == "unavailable" or right_plan["ordering"] == "unavailable":
                results[name] = {
                    "verdict": INCONCLUSIVE,
                    "ordering": left_plan["ordering"],
                    "reason": left_plan["orderingReason"],
                }
                inconclusive.append(name)
                continue

            left_rows = read_table(left, name, left_plan)
            right_rows = read_table(right, name, right_plan)
            if left_rows["unreadable"] or right_rows["unreadable"]:
                results[name] = {
                    "verdict": INCONCLUSIVE,
                    "reason": left_rows["unreadable"] or right_rows["unreadable"],
                }
                inconclusive.append(name)
                continue

            same = left_rows["rows"] == right_rows["rows"]
            entry: dict[str, Any] = {
                "verdict": IDENTICAL if same else DIFFERENT,
                "ordering": left_plan["ordering"],
                "orderingReason": left_plan["orderingReason"],
                "primaryKey": left_plan["primaryKey"],
                "compositePrimaryKey": left_plan.get("compositePrimaryKey", False),
                "withoutRowid": left_plan["withoutRowid"],
                "rowCountA": len(left_rows["rows"]),
                "rowCountB": len(right_rows["rows"]),
                "rowCountMatch": len(left_rows["rows"]) == len(right_rows["rows"]),
                "digestA": digest_of(left_rows["rows"]),
                "digestB": digest_of(right_rows["rows"]),
            }
            if left_rows["rowidOrder"] is not None and right_rows["rowidOrder"] is not None:
                entry["rowidOrderMatches"] = left_rows["rowidOrder"] == right_rows["rowidOrder"]
                entry["readOrderMatches"] = left_rows["readOrder"] == right_rows["readOrder"]

            if not same:
                only_a = sorted(set(left_rows["rows"]) - set(right_rows["rows"]))
                only_b = sorted(set(right_rows["rows"]) - set(left_rows["rows"]))
                entry["rowsOnlyInA"] = len(only_a)
                entry["rowsOnlyInB"] = len(only_b)
                entry["sampleOnlyInA"] = [json.loads(row) for row in only_a[:sample]]
                entry["sampleOnlyInB"] = [json.loads(row) for row in only_b[:sample]]
                differing.append(name)

            results[name] = entry

        overall_digest_a = hashlib.sha256()
        overall_digest_b = hashlib.sha256()
        for name in tables:
            entry = results.get(name, {})
            overall_digest_a.update(f"{name}:{entry.get('digestA', '')}\n".encode("utf-8"))
            overall_digest_b.update(f"{name}:{entry.get('digestB', '')}\n".encode("utf-8"))

        if not schema_match:
            verdict = DIFFERENT
        elif differing:
            verdict = DIFFERENT
        elif inconclusive:
            verdict = INCONCLUSIVE
        else:
            verdict = IDENTICAL

        return {
            "schemaVersion": 1,
            "a": str(first),
            "b": str(second),
            "verdict": verdict,
            "note": (
                "A diagnostic comparison of content. It explains a byte difference; it does not "
                "satisfy the byte-level reproducibility requirement and no gate reads it as if it "
                "did."
            ),
            "schemaMatch": schema_match,
            "schemaDigestA": left_schema["digest"],
            "schemaDigestB": right_schema["digest"],
            "indexesMatch": left_schema["indexes"] == right_schema["indexes"],
            "triggersMatch": left_schema["triggers"] == right_schema["triggers"],
            "viewsMatch": left_schema["views"] == right_schema["views"],
            "tableNamesMatch": left_schema["tables"] == right_schema["tables"],
            "logicalContentDigestA": overall_digest_a.hexdigest(),
            "logicalContentDigestB": overall_digest_b.hexdigest(),
            "differingTables": differing,
            "inconclusiveTables": inconclusive,
            "tables": results,
        }
    finally:
        left.close()
        right.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="compare_sqlite_logical")
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample", type=int, default=5)
    parser.add_argument(
        "--expect",
        choices=[IDENTICAL, DIFFERENT, INCONCLUSIVE],
        help="exit 2 unless the verdict is exactly this",
    )
    args = parser.parse_args()

    for path in (args.first, args.second):
        if not path.is_file():
            raise SystemExit(f"BLOCKED: database does not exist: {path}")

    report = compare(args.first, args.second, sample=args.sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"verdict: {report['verdict']}")
    print(f"schema match: {report['schemaMatch']}")
    for name in report["differingTables"]:
        entry = report["tables"][name]
        print(
            f"  DIFFER  {name}: {entry.get('rowCountA')} vs {entry.get('rowCountB')} rows, "
            f"{entry.get('rowsOnlyInA', '?')} only in A, {entry.get('rowsOnlyInB', '?')} only in B"
        )
    for name in report["inconclusiveTables"]:
        print(f"  INCONCLUSIVE  {name}: {report['tables'][name].get('reason')}")
    mismatched_order = sorted(
        name
        for name, entry in report["tables"].items()
        if entry.get("rowidOrderMatches") is False
    )
    if mismatched_order:
        print(f"  rowid order differs in: {', '.join(mismatched_order)}")
    print(f"wrote {args.output}")

    if args.expect and report["verdict"] != args.expect:
        raise SystemExit(
            f"BLOCKED: expected {args.expect} and measured {report['verdict']}"
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

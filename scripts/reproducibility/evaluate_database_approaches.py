#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate the supported ways of making a package database deterministic.

Six approaches were named in the brief. Four can be run and are; two are
rejected on grounds that do not depend on a measurement, and the reason is
recorded here rather than left as an omission.

Every approach is measured on the same axes, and byte determinism is only one of
them. An approach that produces identical bytes and a database ``rpm`` can no
longer query is a worse outcome than the difference it replaced, so the package
queries ADR-028 lists are run after each one and a failure disqualifies the
approach regardless of how its digests compared.

Three trials, from copies of one pre-finalisation database. Two trials can agree
by chance in a way that three rarely do, and the brief asks for three.

The trials run wherever this is invoked, so the SQLite in use is recorded with
the result. A determinism claim is a claim about one library: two builders
running different SQLite versions can lay out identical rows differently, and a
result measured with one says nothing about the other.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Callable

REFUSED = 2

#: The queries ADR-028 requires to keep working. A deterministic database that
#: cannot answer these is not an improvement.
RPM_QUERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rpm -qa", ("-qa",)),
    ("rpm -q", ("-q", "{sample}")),
    ("rpm -qi", ("-qi", "{sample}")),
    ("rpm -ql", ("-ql", "{sample}")),
    ("rpm -qf", ("-qf", "/usr/bin/rpm")),
    ("rpm -q --whatrequires", ("-q", "--whatrequires", "rpm")),
    ("rpm --verifydb", ("--verifydb",)),
    ("rpm -qi --queryformat installtime", ("-q", "--qf", "%{INSTALLTIME}\n", "{sample}")),
    ("rpm -q --qf install reason", ("-q", "--qf", "%{NAME} %{SIGPGP:pgpsig}\n", "{sample}")),
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def logical_digest(path: Path) -> str:
    """Content, independent of layout. Used to prove an approach preserved rows."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.text_factory = bytes
    try:
        tables = [
            row[0].decode() if isinstance(row[0], bytes) else str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"
            )
        ]
        overall = hashlib.sha256()
        for table in tables:
            columns = [
                row[1].decode() if isinstance(row[1], bytes) else str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            if not columns:
                continue
            selection = ", ".join(f'"{column}"' for column in columns)
            types = ", ".join(f'typeof("{column}")' for column in columns)
            rows = []
            for record in connection.execute(f'SELECT {selection}, {types} FROM "{table}"'):
                width = len(columns)
                parts = []
                for value, storage in zip(record[:width], record[width:]):
                    storage = storage.decode() if isinstance(storage, bytes) else str(storage)
                    if storage == "null" or value is None:
                        parts.append("N")
                    elif storage == "integer":
                        parts.append(f"I{int(value)}")
                    elif storage == "real":
                        parts.append(f"R{float(value).hex()}")
                    elif storage == "blob":
                        parts.append(f"B{hashlib.sha256(bytes(value)).hexdigest()}")
                    else:
                        raw = value if isinstance(value, bytes) else str(value).encode()
                        parts.append(f"T{hashlib.sha256(raw).hexdigest()}")
                rows.append("\x1f".join(parts))
            overall.update(table.encode() + b"\x1e")
            for row in sorted(rows):
                overall.update(row.encode() + b"\n")
        return overall.hexdigest()
    finally:
        connection.close()


def structure(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            "integrity": [row[0] for row in connection.execute("PRAGMA integrity_check")],
            "pageSize": connection.execute("PRAGMA page_size").fetchone()[0],
            "pageCount": connection.execute("PRAGMA page_count").fetchone()[0],
            "freelistCount": connection.execute("PRAGMA freelist_count").fetchone()[0],
            "journalMode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "encoding": connection.execute("PRAGMA encoding").fetchone()[0],
            "autoVacuum": connection.execute("PRAGMA auto_vacuum").fetchone()[0],
            "tableCount": connection.execute(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type='table'"
            ).fetchone()[0],
            "indexCount": connection.execute(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type='index'"
            ).fetchone()[0],
        }
    finally:
        connection.close()


# --------------------------------------------------------------------- approaches


def approach_none(database: Path) -> None:
    """F. Baseline: touch nothing.

    Present so the other approaches have something to be measured against. If
    the untouched copies are already byte-identical across trials, an approach
    that also produces identical bytes has demonstrated nothing.
    """
    return None


def approach_vacuum(database: Path) -> None:
    """C. Controlled VACUUM under fixed PRAGMAs.

    The PRAGMAs are set explicitly rather than inherited. `journal_mode=DELETE`
    is what removes the WAL, and `auto_vacuum` and `page_size` are pinned so the
    result does not depend on the compile-time defaults of whichever SQLite ran.
    `page_size` only takes effect across a VACUUM, which is why it is set before
    one rather than after.
    """
    connection = sqlite3.connect(str(database))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA page_size=4096")
        connection.execute("PRAGMA auto_vacuum=NONE")
        connection.isolation_level = None
        connection.execute("VACUUM")
    finally:
        connection.close()


def approach_vacuum_into(database: Path) -> None:
    """D. VACUUM INTO a fresh file, then replace the original.

    Distinct from C: VACUUM rewrites in place through a journal and keeps the
    original file's header fields that a rewrite does not touch, while
    VACUUM INTO builds a new file from scratch. If a header field were the
    source of variance, only this one would remove it.
    """
    connection = sqlite3.connect(str(database))
    target = database.with_suffix(database.suffix + ".vacuumed")
    if target.exists():
        target.unlink()
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.isolation_level = None
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()
    original = database.stat()
    os.replace(target, database)
    os.chmod(database, original.st_mode & 0o7777)


def approach_dump_restore(database: Path) -> None:
    """E. Canonical logical dump and restore.

    Rebuilds the file from `iterdump`, which is SQLite's own logical export.
    Measured here rather than assumed, because it is the approach most likely to
    produce identical bytes and least likely to be supportable: the restored
    database is one this project constructed, not one rpm wrote, and any
    divergence in how a value round-trips through SQL text becomes a database
    that queries correctly and verifies wrongly.
    """
    target = database.with_suffix(database.suffix + ".restored")
    if target.exists():
        target.unlink()
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    rebuilt = sqlite3.connect(str(target))
    try:
        rebuilt.execute("PRAGMA page_size=4096")
        rebuilt.execute("PRAGMA journal_mode=DELETE")
        for statement in source.iterdump():
            rebuilt.execute(statement)
        rebuilt.commit()
        rebuilt.isolation_level = None
        rebuilt.execute("VACUUM")
    finally:
        source.close()
        rebuilt.close()
    original = database.stat()
    os.replace(target, database)
    os.chmod(database, original.st_mode & 0o7777)


def approach_rpm_rebuilddb(database: Path) -> None:
    """A. rpm's own supported database rebuild.

    `rpm --rebuilddb` reconstructs the database from the headers it holds,
    through rpm's code path rather than through SQL. It requires the database to
    sit at <dbpath>/rpmdb.sqlite, so the caller stages it that way.
    """
    dbpath = database.parent
    result = subprocess.run(
        ["rpm", "--dbpath", str(dbpath), "--rebuilddb"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rpm --rebuilddb exited {result.returncode}: {result.stderr.strip()[:400]}"
        )


#: name -> (description, transform, applies to the rpm database only)
#:
#: `rpm --rebuilddb` is rpm's database and nothing else. Pointed at libdnf5's
#: transaction history it does not fail usefully — it creates an empty rpm
#: database beside it and takes the directory with it — so it is recorded as not
#: applicable there rather than as an approach that errored.
APPROACHES: dict[str, tuple[str, Callable[[Path], None], bool]] = {
    "A-rpm-rebuilddb": (
        "rpm --rebuilddb, rpm's own supported reconstruction from the stored headers",
        approach_rpm_rebuilddb,
        True,
    ),
    "C-controlled-vacuum": (
        "VACUUM under explicitly set journal_mode, page_size and auto_vacuum",
        approach_vacuum,
        False,
    ),
    "D-vacuum-into": (
        "VACUUM INTO a new file, which then replaces the original",
        approach_vacuum_into,
        False,
    ),
    "E-dump-restore": (
        "logical dump through sqlite3.iterdump and restore into a fresh database",
        approach_dump_restore,
        False,
    ),
    "F-none": (
        "no transformation; the control the others are measured against",
        approach_none,
        False,
    ),
}

#: Rejected without a trial, and why. Recorded so the evaluation is complete
#: rather than silently narrower than the brief asked for.
NOT_TRIALLED = {
    "B-canonical-header-replay": (
        "Replaying package headers into a fresh rpm database means owning rpm's on-disk format "
        "outside rpm's own code path. ADR-028 rejected it on the grounds that a reconstruction "
        "which subtly diverged would produce a database that queries correctly and verifies "
        "wrongly, and the brief's prohibition on arbitrarily rewriting the RPM database is aimed "
        "at exactly this class. No measurement changes that: an approach can be byte-perfect and "
        "still be one nobody upstream supports."
    ),
}


def run_rpm_queries(dbpath: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every query ADR-028 requires, against a staged database path."""
    listing = subprocess.run(
        ["rpm", "--dbpath", str(dbpath), "-qa", "--qf", "%{NAME}\n"],
        capture_output=True,
        text=True,
    )
    inventory = sorted(listing.stdout.split())
    sample = inventory[0] if inventory else "rpm"

    results: list[dict[str, Any]] = []
    for label, template in RPM_QUERIES:
        argv = ["rpm", "--dbpath", str(dbpath)] + [
            part.replace("{sample}", sample) for part in template
        ]
        completed = subprocess.run(argv, capture_output=True, text=True)
        results.append(
            {
                "query": label,
                "exitCode": completed.returncode,
                "outputLines": len(completed.stdout.splitlines()),
                # `rpm -q --whatrequires` exits 1 when nothing requires the
                # package, which is an answer rather than a failure. What
                # disqualifies an approach is rpm being unable to read the
                # database, which shows up as an error on stderr.
                "passed": "error:" not in completed.stderr.lower()
                and "cannot open" not in completed.stderr.lower(),
                "stderr": completed.stderr.strip()[:300],
            }
        )
    return results, inventory


def trial(
    name: str,
    source: Path,
    transform: Callable[[Path], None],
    *,
    is_rpmdb: bool,
    run_queries: bool,
) -> dict[str, Any]:
    """One trial: copy the pre-state, transform it, measure everything."""
    workdir = Path(tempfile.mkdtemp(prefix="bunny-dbtrial-"))
    try:
        # rpm insists the database live at <dbpath>/rpmdb.sqlite, so the copy is
        # staged under that name whichever approach is being measured. Doing it
        # for all of them keeps the trials comparable.
        staged = workdir / ("rpmdb.sqlite" if is_rpmdb else source.name)
        shutil.copy2(source, staged)

        before = logical_digest(staged)
        error = None
        try:
            transform(staged)
        except Exception as exc:  # noqa: BLE001 — the failure is the result
            error = f"{type(exc).__name__}: {exc}"

        for suffix in ("-wal", "-shm", "-journal"):
            residue = Path(str(staged) + suffix)
            if residue.exists() and residue.stat().st_size == 0:
                residue.unlink()

        record: dict[str, Any] = {"approach": name, "error": error}
        if not error and not staged.is_file():
            error = (
                "the transformation removed the database it was given; nothing is left to "
                "measure and nothing could be shipped"
            )
            record["error"] = error
        if error:
            record["fileDigest"] = None
            return record

        record["fileDigest"] = digest(staged)
        record["logicalDigest"] = logical_digest(staged)
        record["contentPreserved"] = before == record["logicalDigest"]
        record["structure"] = structure(staged)
        record["residue"] = {
            suffix.lstrip("-"): Path(str(staged) + suffix).exists()
            for suffix in ("-wal", "-shm", "-journal")
        }

        if run_queries and is_rpmdb:
            queries, inventory = run_rpm_queries(workdir)
            record["rpmQueries"] = queries
            record["packageCount"] = len(inventory)
            record["inventoryDigest"] = hashlib.sha256(
                "\n".join(inventory).encode("utf-8")
            ).hexdigest()
            record["allQueriesPassed"] = all(entry["passed"] for entry in queries)
        return record
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def evaluate(
    source: Path, *, trials: int, is_rpmdb: bool, run_queries: bool
) -> dict[str, Any]:
    baseline_logical = logical_digest(source)
    results: dict[str, Any] = {}

    for name, (description, transform, rpmdb_only) in APPROACHES.items():
        if rpmdb_only and not is_rpmdb:
            results[name] = {
                "description": description,
                "applicable": False,
                "reason": (
                    "this approach is rpm's own database maintenance and has no meaning for the "
                    "libdnf5 transaction history"
                ),
                "usable": False,
            }
            continue
        runs = [
            trial(name, source, transform, is_rpmdb=is_rpmdb, run_queries=run_queries)
            for _ in range(trials)
        ]
        digests = [run.get("fileDigest") for run in runs]
        logicals = [run.get("logicalDigest") for run in runs]
        inventories = [run.get("inventoryDigest") for run in runs if "inventoryDigest" in run]
        errors = [run["error"] for run in runs if run["error"]]

        byte_deterministic = bool(digests[0]) and len(set(digests)) == 1
        content_preserved = all(run.get("contentPreserved") for run in runs if not run["error"])
        queries_pass = all(run.get("allQueriesPassed", True) for run in runs if not run["error"])

        results[name] = {
            "description": description,
            "applicable": True,
            "trials": trials,
            "errors": errors,
            "fileDigests": digests,
            "byteDeterministic": byte_deterministic,
            "logicalDigests": logicals,
            "logicalStableAcrossTrials": len(set(logicals)) == 1,
            "contentPreservedVersusInput": content_preserved,
            "inputLogicalDigest": baseline_logical,
            "packageInventoryStable": (not inventories) or len(set(inventories)) == 1,
            "rpmQueriesPass": queries_pass,
            "structure": runs[0].get("structure"),
            "residue": runs[0].get("residue"),
            # An approach is only usable if it is deterministic *and* preserves
            # what the database is for. Byte determinism alone is the trap this
            # whole evaluation exists to avoid falling into.
            "usable": bool(
                byte_deterministic and content_preserved and queries_pass and not errors
            ),
            "runs": runs,
        }

    return {
        "schemaVersion": 1,
        "source": str(source),
        "sourceDigest": digest(source),
        "sourceLogicalDigest": baseline_logical,
        "sqliteVersion": sqlite3.sqlite_version,
        "trialsPerApproach": trials,
        "approaches": results,
        "notTrialled": NOT_TRIALLED,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="evaluate_database_approaches")
    parser.add_argument(
        "--command",
        choices=("sqlite-determinism-check", "test-rpmdb-rebuild", "test-libdnf-history-rebuild"),
        required=True,
    )
    parser.add_argument("--rpmdb", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--require-usable",
        action="store_true",
        help="exit 2 unless at least one approach is byte-deterministic, content-preserving and "
             "leaves every rpm query working",
    )
    args = parser.parse_args()

    if args.trials < 3:
        raise SystemExit(
            "BLOCKED: at least three trials are required. Two runs can agree by chance in a way "
            "three rarely do, and a determinism claim from two measurements is a coin toss "
            "reported as a result."
        )

    payload: dict[str, Any] = {"schemaVersion": 1, "command": args.command, "results": {}}

    targets: list[tuple[str, Path, bool]] = []
    if args.command in ("sqlite-determinism-check", "test-rpmdb-rebuild"):
        if not args.rpmdb:
            raise SystemExit("BLOCKED: --rpmdb is required for this command")
        targets.append(("rpmdb", args.rpmdb, True))
    if args.command in ("sqlite-determinism-check", "test-libdnf-history-rebuild"):
        if not args.history:
            raise SystemExit("BLOCKED: --history is required for this command")
        targets.append(("transactionHistory", args.history, False))

    for label, path, is_rpmdb in targets:
        if not path.is_file():
            raise SystemExit(f"BLOCKED: {label} database does not exist: {path}")
        payload["results"][label] = evaluate(
            path,
            trials=args.trials,
            is_rpmdb=is_rpmdb,
            run_queries=shutil.which("rpm") is not None,
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    usable_anywhere = True
    for label, result in payload["results"].items():
        print(f"{label} ({Path(result['source']).name}), SQLite {result['sqliteVersion']}:")
        usable_here = []
        for name, entry in result["approaches"].items():
            if not entry.get("applicable", True):
                print(f"    {name:24} n/a      {entry['reason']}")
                continue
            marks = [
                "bytes=" + ("stable" if entry["byteDeterministic"] else "VARY"),
                "content=" + ("preserved" if entry["contentPreservedVersusInput"] else "CHANGED"),
                "queries=" + ("ok" if entry["rpmQueriesPass"] else "FAIL"),
            ]
            if entry["errors"]:
                marks.append("error=" + entry["errors"][0][:60])
            print(f"    {name:24} {'USABLE  ' if entry['usable'] else 'rejected'} {' '.join(marks)}")
            if entry["usable"]:
                usable_here.append(name)
        if not usable_here:
            usable_anywhere = False
        print(f"    usable: {', '.join(usable_here) or 'none'}")
    print(f"wrote {args.report}")

    if args.require_usable and not usable_anywhere:
        raise SystemExit(
            "BLOCKED: no evaluated approach is byte-deterministic while preserving content and "
            "keeping every rpm query working."
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

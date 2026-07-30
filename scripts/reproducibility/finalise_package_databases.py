#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic finalisation of the rpm and libdnf5 SQLite databases.

The logic behind ``build/scripts/finalise-package-databases.sh``, importable so
the regression fixtures exercise the code that ships rather than a copy of it.
The bash wrapper stages arguments and exits early when there is nothing to
finalise; everything with a failure mode lives here.

Invoked as::

    finalise_package_databases.py <rpmdb> <history> <report> <expect_sqlite> \\
                                  <functional 0|1> <root>

``finalise()`` raises :class:`Refused` rather than exiting, so a caller — the
regression fixtures, in practice — can assert on *which* condition tripped
instead of on an exit code that is 2 for all of them.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

REFUSED = 2


class Refused(Exception):
    """A fail-closed condition. Carries the message the operator sees."""


def fail(message: str) -> None:
    raise Refused(message)

#: What each database is required to contain. A schema that lost a table is a
#: different database, and finalising it as if nothing happened would ship the
#: loss. These are the tables this project has established are present; a table
#: appearing is reported, a required table disappearing is fatal.
REQUIRED_TABLES = {
    "rpmdb": {"Packages", "Name", "Basenames", "Providename", "Requirename", "Installtid"},
    "history": {"trans", "trans_item", "rpm", "item", "pkg_name", "repo", "config"},
}

#: Table types SQLite can hold that this finaliser has not established it can
#: handle. Encountering one is a refusal rather than a shrug: a virtual table's
#: content lives outside the file and a VACUUM does not move it, so a database
#: containing one has not been finalised even if the command succeeded.
UNSUPPORTED_TABLE_TYPES = {"virtual"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def logical_digest(path: Path) -> tuple[str, dict[str, int]]:
    """A content digest that is blind to page layout and not to rows.

    This is what makes "VACUUM preserved the content" a checkable claim rather
    than a citation. Values are tagged with the storage class SQLite reports,
    so a NULL that became an empty string moves the digest.
    """
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
        counts: dict[str, int] = {}
        for table in tables:
            columns = [
                row[1].decode() if isinstance(row[1], bytes) else str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            if not columns:
                counts[table] = 0
                continue
            selection = ", ".join(f'"{column}"' for column in columns)
            types = ", ".join(f'typeof("{column}")' for column in columns)
            rows = []
            for record in connection.execute(f'SELECT {selection}, {types} FROM "{table}"'):
                width = len(columns)
                values = record[:width]
                classes = record[width:]
                encoded = []
                for value, storage in zip(values, classes):
                    storage = storage.decode() if isinstance(storage, bytes) else str(storage)
                    if storage == "null" or value is None:
                        encoded.append("N")
                    elif storage == "integer":
                        encoded.append(f"I{int(value)}")
                    elif storage == "real":
                        encoded.append(f"R{float(value).hex()}")
                    elif storage == "blob":
                        encoded.append(f"B{hashlib.sha256(bytes(value)).hexdigest()}")
                    else:
                        raw = value if isinstance(value, bytes) else str(value).encode()
                        encoded.append(f"T{hashlib.sha256(raw).hexdigest()}")
                rows.append("\x1f".join(encoded))
            counts[table] = len(rows)
            overall.update(table.encode() + b"\x1e")
            for row in sorted(rows):
                overall.update(row.encode() + b"\n")
        return overall.hexdigest(), counts
    finally:
        connection.close()


def structure(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        quick = [row[0] for row in connection.execute("PRAGMA quick_check")]
        tables = set()
        virtual = set()
        for name, sql in connection.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type='table'"
        ):
            tables.add(str(name))
            if sql and str(sql).strip().upper().startswith("CREATE VIRTUAL TABLE"):
                virtual.add(str(name))
        return {
            "integrity": integrity,
            "quickCheck": quick,
            "tables": sorted(tables),
            "virtualTables": sorted(virtual),
            "pageSize": connection.execute("PRAGMA page_size").fetchone()[0],
            "pageCount": connection.execute("PRAGMA page_count").fetchone()[0],
            "freelistCount": connection.execute("PRAGMA freelist_count").fetchone()[0],
            "journalMode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "encoding": connection.execute("PRAGMA encoding").fetchone()[0],
            "autoVacuum": connection.execute("PRAGMA auto_vacuum").fetchone()[0],
            "schemaVersion": connection.execute("PRAGMA schema_version").fetchone()[0],
            "userVersion": connection.execute("PRAGMA user_version").fetchone()[0],
            "applicationId": connection.execute("PRAGMA application_id").fetchone()[0],
        }
    finally:
        connection.close()


def ownership(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"mode": oct(stat.st_mode & 0o7777), "uid": stat.st_uid, "gid": stat.st_gid}


def finalise(
    rpmdb: Path,
    history: Path,
    report: str,
    expect_sqlite: str,
    functional: bool,
    root: str,
    *,
    quiet: bool = False,
) -> dict:
    """Finalise both databases, or raise Refused saying which check tripped."""
    # ---------------------------------------------------------------- step 0
    # The SQLite doing the finalising must be the SQLite that is pinned. A different
    # library can lay the file out differently from identical rows, so a build whose
    # SQLite drifted would produce an artifact that cannot reproduce against the one
    # that did not — and would say nothing about why.
    if expect_sqlite and sqlite3.sqlite_version != expect_sqlite:
        fail(
            f"this container's SQLite is {sqlite3.sqlite_version} and the builder lock pins "
            f"{expect_sqlite}. Two builders must finalise these databases with the same library; "
            "a different one can write different bytes from identical rows."
        )

    databases = [("rpmdb", rpmdb)]
    if history.is_file():
        databases.append(("history", history))
    else:
        # libdnf5's history is created by the first transaction. Its absence after a
        # package install means no transaction was recorded, which is a build defect
        # and not a state to finalise quietly.
        fail(
            f"{history} is not present. A build that installed packages has a libdnf5 transaction "
            "history; its absence means the transaction was not recorded, and the artifact would "
            "ship without the record that supports repair, audit and licence inventory."
        )

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "sqliteVersion": sqlite3.sqlite_version,
        "expectedSqliteVersion": expect_sqlite or None,
        "canonicalisation": (
            "approach C: PRAGMA wal_checkpoint(TRUNCATE); journal_mode=DELETE; page_size=4096; "
            "auto_vacuum=NONE; VACUUM"
        ),
        "canonicalisationRationale": (
            "VACUUM is SQLite's own supported rewrite and is defined to preserve content. It is the "
            "only transformation applied. No row is written, no schema is altered, and the logical "
            "content digest is compared either side of it so that a VACUUM which did move content "
            "would fail the build rather than be trusted. Selected as approach C of the six the brief "
            "names, from a three-trial evaluation (evaluate_database_approaches.py): C, D and E were "
            "all byte-deterministic and content-preserving; C is the one that operates through "
            "sqlite's supported maintenance path without constructing a new file this project would "
            "then own. rpm --rebuilddb was measured to renumber every header (594 of 1015 Packages "
            "rows moved) and is rejected for exactly the reason ADR-028 predicted."
        ),
        "databases": [],
    }

    for label, path in databases:
        before_digest = digest(path)
        # Corruption bad enough to stop SQLite reading the schema raises here
        # rather than returning a failed integrity_check, and an unhandled
        # DatabaseError would reach the operator as a traceback that names a
        # line number instead of a database. Both paths have to refuse, and
        # they have to refuse legibly.
        try:
            before_structure = structure(path)
        except sqlite3.Error as error:
            fail(
                f"{path} cannot be read by SQLite: {error}. A database this damaged must not be "
                "canonicalised into one that looks sound."
            )
        before_ownership = ownership(path)

        if before_structure["integrity"] != ["ok"]:
            fail(
                f"{path} fails PRAGMA integrity_check before finalisation: "
                f"{before_structure['integrity']}. A corrupt database must not be canonicalised into "
                "one that looks sound."
            )
        if before_structure["quickCheck"] != ["ok"]:
            fail(f"{path} fails PRAGMA quick_check before finalisation: {before_structure['quickCheck']}")

        missing = REQUIRED_TABLES[label] - set(before_structure["tables"])
        if missing:
            fail(
                f"{path} is missing required tables {sorted(missing)}. This is not the schema this "
                "finaliser was written against, and canonicalising an unexpected schema would produce "
                "a database nobody has reasoned about."
            )
        if before_structure["virtualTables"]:
            fail(
                f"{path} contains virtual tables {before_structure['virtualTables']}. A virtual "
                "table's content lives outside the file and VACUUM does not move it, so this database "
                "would not be finalised even though the command succeeded."
            )

        try:
            before_logical, before_counts = logical_digest(path)
        except sqlite3.Error as error:
            fail(
                f"{path} passes its integrity check and its rows cannot be read: {error}. "
                "Without a content digest there is no way to show the canonicalisation preserved "
                "anything, and an unverifiable canonicalisation is the one thing this script is "
                "for refusing."
            )

        # ------------------------------------------------------------ canonicalise
        #
        # Convergent, not merely repeatable. VACUUM increments the file change
        # counter in the database header on every run — measured: a second VACUUM of
        # an already-vacuumed database changed the bytes again — so "run the same
        # commands" is not idempotence. The canonical state is recognisable from the
        # file itself (rollback-journal mode, the pinned page size, no auto-vacuum,
        # an empty freelist, no sidecar residue), and a database already in it is
        # not written to at all: zero writes is the only number of writes that
        # leaves the bytes alone.
        #
        # The recognition is sound in this build because rpm and libdnf5 both leave
        # their databases in WAL mode, so a database that has not been finalised
        # cannot present as canonical.
        already_canonical = (
            str(before_structure["journalMode"]).lower() == "delete"
            and before_structure["pageSize"] == 4096
            and before_structure["autoVacuum"] == 0
            and before_structure["freelistCount"] == 0
            and not any(
                Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
            )
        )

        if not already_canonical:
            connection = sqlite3.connect(str(path))
            try:
                # TRUNCATE rather than PASSIVE: a passive checkpoint leaves the WAL
                # file in place at whatever length it reached, which is the residue
                # the mutable-state policy requires to be absent.
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode=DELETE")
                # Pinned explicitly rather than inherited from whichever SQLite ran.
                # Both take effect across the VACUUM below, which is why they are
                # set before it. 4096 is what rpm and libdnf5 both currently
                # produce; if either ever changes its default, this build keeps
                # producing the same file and the change arrives as a reviewed edit
                # here instead of as an unexplained archive difference.
                connection.execute("PRAGMA page_size=4096")
                connection.execute("PRAGMA auto_vacuum=NONE")
                connection.isolation_level = None
                connection.execute("VACUUM")
            finally:
                connection.close()

            # -------------------------------------------------------- residue
            for suffix in ("-wal", "-shm", "-journal"):
                residue = Path(str(path) + suffix)
                if residue.exists():
                    if residue.stat().st_size:
                        fail(
                            f"{residue} still holds {residue.stat().st_size} bytes after a TRUNCATE "
                            "checkpoint. Removing it would discard a transaction the database does "
                            "not yet contain."
                        )
                    residue.unlink()

        after_digest = digest(path)
        after_structure = structure(path)
        after_ownership = ownership(path)
        after_logical, after_counts = logical_digest(path)

        if after_structure["integrity"] != ["ok"]:
            fail(f"{path} fails integrity_check after finalisation: {after_structure['integrity']}")
        if after_structure["quickCheck"] != ["ok"]:
            fail(f"{path} fails quick_check after finalisation: {after_structure['quickCheck']}")

        # The central guarantee. If these differ, the canonicalisation changed
        # content, and a canonicalisation that changes content is the failure mode
        # this whole approach was chosen to avoid.
        if before_logical != after_logical:
            fail(
                f"{path}: the logical content digest changed across finalisation "
                f"({before_logical} -> {after_logical}). VACUUM is defined to preserve content; a "
                "measured change means the artifact's package-manager state was altered, and that is "
                "a defect rather than a normalisation."
            )
        if before_counts != after_counts:
            changed = {
                table: (before_counts.get(table), after_counts.get(table))
                for table in set(before_counts) | set(after_counts)
                if before_counts.get(table) != after_counts.get(table)
            }
            fail(f"{path}: row counts changed across finalisation: {changed}")
        if set(before_structure["tables"]) != set(after_structure["tables"]):
            fail(f"{path}: the set of tables changed across finalisation")
        if before_ownership != after_ownership:
            fail(
                f"{path}: ownership or permissions changed across finalisation "
                f"({before_ownership} -> {after_ownership})"
            )

        if already_canonical and after_digest != before_digest:
            fail(
                f"{path} presented as already canonical and its bytes changed anyway "
                f"({before_digest} -> {after_digest}); something other than this script wrote to it "
                "during finalisation."
            )

        manifest["databases"].append(
            {
                "path": str(path),
                "label": label,
                "digestBefore": before_digest,
                "digestAfter": after_digest,
                "bytesChanged": before_digest != after_digest,
                "alreadyCanonical": already_canonical,
                "logicalDigest": after_logical,
                "logicalDigestPreserved": before_logical == after_logical,
                "rowCounts": after_counts,
                "structureBefore": before_structure,
                "structureAfter": after_structure,
                "ownership": after_ownership,
                "residuePresent": {
                    suffix.lstrip("-"): Path(str(path) + suffix).exists()
                    for suffix in ("-wal", "-shm", "-journal")
                },
            }
        )

    # ---------------------------------------------------------------- functional
    # A database that canonicalises perfectly and can no longer answer `rpm -qa` is
    # a worse outcome than the difference it replaced. ADR-028 says both are
    # required; this is where the second one is checked.
    checks: list[dict[str, object]] = []
    if functional:
        dbpath = str(Path(root or "/") / "usr/share/rpm")

        def run(name: str, argv: list[str], *, expect_output: bool = True) -> bool:
            result = subprocess.run(argv, capture_output=True, text=True)
            ok = result.returncode == 0 and (bool(result.stdout.strip()) or not expect_output)
            checks.append(
                {
                    "check": name,
                    "command": " ".join(argv),
                    "exitCode": result.returncode,
                    "outputLines": len(result.stdout.splitlines()),
                    "passed": ok,
                    "stderr": result.stderr.strip()[:400],
                }
            )
            return ok

        installed = subprocess.run(
            ["rpm", "--dbpath", dbpath, "-qa", "--qf", "%{NAME}\n"],
            capture_output=True,
            text=True,
        )
        package_names = sorted(installed.stdout.split())
        checks.append(
            {
                "check": "rpm -qa",
                "command": f"rpm --dbpath {dbpath} -qa",
                "exitCode": installed.returncode,
                "outputLines": len(package_names),
                "passed": installed.returncode == 0 and len(package_names) > 0,
                "stderr": installed.stderr.strip()[:400],
            }
        )
        sample = package_names[0] if package_names else "rpm"
        run("rpm -q", ["rpm", "--dbpath", dbpath, "-q", sample])
        run("rpm -qi", ["rpm", "--dbpath", dbpath, "-qi", sample])
        run("rpm -ql", ["rpm", "--dbpath", dbpath, "-ql", sample], expect_output=False)
        run("rpm -qf", ["rpm", "--dbpath", dbpath, "-qf", "/usr/bin/rpm"])
        run("rpm -q --whatrequires", ["rpm", "--dbpath", dbpath, "-q", "--whatrequires", "rpm"],
            expect_output=False)
        run("rpm --verifydb", ["rpm", "--dbpath", dbpath, "--verifydb"], expect_output=False)
        # `rpm -V` exits non-zero whenever any file differs from its header, which is
        # normal on a built image — configuration files get rewritten by the build.
        # What is checked is that verification *runs*, not that nothing differs.
        verify = subprocess.run(
            ["rpm", "--dbpath", dbpath, "-V", sample], capture_output=True, text=True
        )
        checks.append(
            {
                "check": "rpm -V",
                "command": f"rpm --dbpath {dbpath} -V {sample}",
                "exitCode": verify.returncode,
                "outputLines": len(verify.stdout.splitlines()),
                "passed": "error:" not in verify.stderr.lower(),
                "stderr": verify.stderr.strip()[:400],
                "note": "a non-zero exit means files differ from their headers, which a built image "
                        "expects; a failure here is rpm being unable to read the database at all",
            }
        )

        manifest["packageCount"] = len(package_names)
        failed = [entry["check"] for entry in checks if not entry["passed"]]
        if failed:
            manifest["functionalChecks"] = checks
            if report:
                Path(report).parent.mkdir(parents=True, exist_ok=True)
            if report:
                Path(report).write_text(
                    json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            fail(
                "these package-manager checks failed after finalisation: "
                + ", ".join(failed)
                + ". A database that canonicalises and can no longer be queried is a worse outcome "
                "than the difference it replaced."
            )

    manifest["functionalChecks"] = checks
    manifest["result"] = "PASS"

    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    for entry in (manifest["databases"] if not quiet else []):
        print(
            f"  {entry['label']:8} {Path(entry['path']).name}: "
            f"{entry['structureAfter']['pageCount']} pages, "
            f"freelist {entry['structureAfter']['freelistCount']}, "
            f"{'bytes changed' if entry['bytesChanged'] else 'byte-identical'}, "
            f"content preserved: {entry['logicalDigestPreserved']}"
        )
    if functional and not quiet:
        print(f"  {manifest.get('packageCount', 0)} packages queryable; {len(checks)} checks passed")
    if report and not quiet:
        print(f"  wrote {report}")

    return manifest



def main(argv: list[str]) -> int:
    try:
        finalise(
            Path(argv[1]),
            Path(argv[2]),
            argv[3],
            argv[4],
            argv[5] == "1",
            argv[6],
        )
    except Refused as refusal:
        print(f"BLOCKED: {refusal}", file=sys.stderr)
        return REFUSED
    except sqlite3.Error as error:
        # A last resort. Every known path wraps its own SQLite failures, so
        # reaching here means one was missed — which still has to leave the
        # operator with a sentence rather than a stack trace.
        print(
            f"BLOCKED: SQLite failed during finalisation and the failure was not anticipated: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return REFUSED
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

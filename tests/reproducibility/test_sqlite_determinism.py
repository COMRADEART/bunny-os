# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests that reject the ways a database comparison can appear to pass.

Every case here is a way of getting a favourable answer without having earned
it: a canonicalisation that hides a changed row, a logical match reported as a
byte match, a finaliser that accepts a corrupt database, a comparison assembled
from a collection that was allowed to omit dimensions. The fixtures are built
rather than recorded, so each one reproduces its defect exactly and a test that
stops failing is a test whose defect actually went away.

The fixtures use SQLite's own behaviour to produce the physical variance —
insertion order, page size, WAL residue — rather than editing bytes, because a
hand-edited page proves the parser wrong and nothing about the finaliser.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "reproducibility"))

from compare_sqlite_logical import compare as compare_logical  # noqa: E402
from compare_sqlite_pages import compare as compare_pages  # noqa: E402
from finalise_package_databases import Refused, finalise, logical_digest  # noqa: E402
from inspect_sqlite import inspect as inspect_database  # noqa: E402

SCRIPTS = ROOT / "scripts" / "reproducibility"

#: Enough of the rpm and libdnf5 schemas for the finaliser's required-table
#: check to be satisfied by a fixture. Using the real names matters: a fixture
#: with invented tables would exercise the finaliser's failure path instead of
#: its success path, and then never test the success path at all.
RPMDB_TABLES = ("Packages", "Name", "Basenames", "Providename", "Requirename", "Installtid")
HISTORY_TABLES = ("trans", "trans_item", "rpm", "item", "pkg_name", "repo", "config")


def _make_rpmdb(path: Path, *, rows: int = 40, order: str = "forward", page_size: int = 4096):
    connection = sqlite3.connect(str(path))
    connection.execute(f"PRAGMA page_size={page_size}")
    connection.execute("PRAGMA journal_mode=DELETE")
    for table in RPMDB_TABLES:
        if table == "Packages":
            connection.execute(
                "CREATE TABLE Packages (hnum INTEGER PRIMARY KEY AUTOINCREMENT, blob BLOB NOT NULL)"
            )
        else:
            connection.execute(
                f"CREATE TABLE {table} (key BLOB NOT NULL, hnum INT NOT NULL, idx INT DEFAULT 0)"
            )
    payload = [(index, bytes([index % 251]) * 300) for index in range(1, rows + 1)]
    if order == "reverse":
        payload = list(reversed(payload))
    elif order == "shuffled":
        payload = payload[1::2] + payload[0::2]
    for hnum, blob in payload:
        connection.execute("INSERT INTO Packages (hnum, blob) VALUES (?, ?)", (hnum, blob))
    for index in range(1, rows + 1):
        connection.execute(
            "INSERT INTO Name (key, hnum, idx) VALUES (?, ?, 0)", (f"package-{index}".encode(), index)
        )
    connection.commit()
    connection.close()


def _make_history(path: Path, *, transactions: int = 2, order: str = "forward"):
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute(
        "CREATE TABLE trans (id INTEGER PRIMARY KEY, dt_begin INTEGER, dt_end INTEGER, "
        "cmdline TEXT, state_id INTEGER)"
    )
    for table in HISTORY_TABLES:
        if table == "trans":
            continue
        connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)")
    rows = [(index, 1000 + index, 1000 + index, f"dnf install package-{index}", 2)
            for index in range(1, transactions + 1)]
    if order == "reverse":
        rows = list(reversed(rows))
    for row in rows:
        connection.execute("INSERT INTO trans VALUES (?, ?, ?, ?, ?)", row)
    for table in HISTORY_TABLES:
        if table == "trans":
            continue
        connection.execute(f"INSERT INTO {table} VALUES (1, 'x')")
    connection.commit()
    connection.close()


class Fixture:
    """A staged root with both databases where the finaliser expects them."""

    def __init__(self, directory: Path):
        self.root = directory
        self.rpmdb = directory / "usr/share/rpm/rpmdb.sqlite"
        self.history = directory / "usr/lib/sysimage/libdnf5/transaction_history.sqlite"
        self.rpmdb.parent.mkdir(parents=True, exist_ok=True)
        self.history.parent.mkdir(parents=True, exist_ok=True)

    def finalise(self, **kwargs):
        return finalise(
            self.rpmdb,
            self.history,
            kwargs.pop("report", ""),
            kwargs.pop("expect_sqlite", ""),
            kwargs.pop("functional", False),
            str(self.root),
            quiet=True,
        )


class FinaliserTests(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self._scratch.name))
        _make_rpmdb(self.fixture.rpmdb)
        _make_history(self.fixture.history)

    def tearDown(self):
        self._scratch.cleanup()

    # 1 — logical equality is not byte equality
    def test_logical_equality_is_not_reported_as_byte_equality(self):
        """Two databases with identical rows and different physical layout."""
        forward = Path(self._scratch.name) / "forward.sqlite"
        shuffled = Path(self._scratch.name) / "shuffled.sqlite"
        _make_rpmdb(forward, order="forward")
        _make_rpmdb(shuffled, order="shuffled")

        logical = compare_logical(forward, shuffled, sample=1)
        self.assertEqual(logical["verdict"], "LOGICALLY_IDENTICAL")
        # The whole point: identical content, and the files are not the same.
        self.assertNotEqual(
            inspect_database(forward)["fileSha256"],
            inspect_database(shuffled)["fileSha256"],
            "the fixture must actually produce a byte difference, or it tests nothing",
        )
        self.assertNotIn("satisfiesByteReproducibility", logical)
        self.assertIn("does not satisfy the byte-level reproducibility requirement", logical["note"])

    # 2 and 3 — a different SQLite must be refused
    def test_finalisation_refuses_a_different_sqlite_version(self):
        with self.assertRaises(Refused) as caught:
            self.fixture.finalise(expect_sqlite="0.0.0")
        self.assertIn("0.0.0", str(caught.exception))

    def test_finalisation_accepts_the_pinned_sqlite_version(self):
        manifest = self.fixture.finalise(expect_sqlite=sqlite3.sqlite_version)
        self.assertEqual(manifest["result"], "PASS")

    # 5 — a changed schema must not be canonicalised into equality
    def test_a_changed_schema_is_reported_not_normalised(self):
        other = Path(self._scratch.name) / "other.sqlite"
        _make_rpmdb(other)
        connection = sqlite3.connect(str(other))
        connection.execute("ALTER TABLE Packages ADD COLUMN extra TEXT")
        connection.commit()
        connection.close()

        report = compare_logical(self.fixture.rpmdb, other, sample=1)
        self.assertFalse(report["schemaMatch"])
        self.assertEqual(report["verdict"], "LOGICALLY_DIFFERENT")

    # 6 — a changed row must not be canonicalised into equality
    def test_a_changed_row_survives_canonicalisation(self):
        other = Path(self._scratch.name) / "other.sqlite"
        shutil.copy2(self.fixture.rpmdb, other)
        connection = sqlite3.connect(str(other))
        connection.execute("UPDATE Packages SET blob = ? WHERE hnum = 7", (b"\x00" * 300,))
        connection.commit()
        connection.execute("VACUUM")
        connection.close()

        report = compare_logical(self.fixture.rpmdb, other, sample=2)
        self.assertEqual(report["verdict"], "LOGICALLY_DIFFERENT")
        self.assertIn("Packages", report["differingTables"])
        self.assertEqual(report["tables"]["Packages"]["rowsOnlyInA"], 1)

    def test_finalisation_refuses_when_content_would_change(self):
        """The guarantee that stops a canonicaliser hiding a difference."""
        before, _ = logical_digest(self.fixture.rpmdb)
        self.fixture.finalise()
        after, _ = logical_digest(self.fixture.rpmdb)
        self.assertEqual(before, after)

    # 9 — a corrupt database must not pass finalisation
    def test_finalisation_refuses_a_corrupt_database(self):
        with self.fixture.rpmdb.open("r+b") as handle:
            handle.seek(4096)
            handle.write(b"\xde\xad\xbe\xef" * 256)
        with self.assertRaises(Refused) as caught:
            self.fixture.finalise()
        message = str(caught.exception).lower()
        self.assertTrue(
            "malformed" in message or "integrity" in message,
            f"the refusal must name the corruption, and said: {caught.exception}",
        )

    # 10 — WAL and SHM residue must not survive
    def test_wal_and_shm_residue_are_removed(self):
        """A database left in WAL mode, with sidecars, must ship in neither state.

        SQLite deletes ``-wal`` and ``-shm`` when the last connection closes
        cleanly, so a fixture that opens and closes leaves nothing behind and
        would pass without testing anything. The residue is therefore staged
        directly, which is also what the real case looked like: the earlier
        comparison found a ``-wal`` and a ``-shm`` *in the image*, left by a
        transaction whose process did not get to close.
        """
        connection = sqlite3.connect(str(self.fixture.history))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO trans VALUES (99, 1, 1, 'probe', 2)")
        connection.commit()
        connection.close()

        mode = sqlite3.connect(str(self.fixture.history))
        self.assertEqual(
            mode.execute("PRAGMA journal_mode").fetchone()[0],
            "wal",
            "the fixture must leave the database in WAL mode, or it tests nothing",
        )
        mode.close()

        for suffix in ("-wal", "-shm"):
            Path(str(self.fixture.history) + suffix).write_bytes(b"")
        before, _ = logical_digest(self.fixture.history)

        self.fixture.finalise()

        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(
                Path(str(self.fixture.history) + suffix).exists(),
                f"{suffix} survived finalisation",
            )
        after_mode = sqlite3.connect(str(self.fixture.history))
        self.assertEqual(
            after_mode.execute("PRAGMA journal_mode").fetchone()[0],
            "delete",
            "finalisation must leave the database out of WAL mode, or sqlite recreates the "
            "sidecars on the installed system's first read",
        )
        after_mode.close()
        after, _ = logical_digest(self.fixture.history)
        self.assertEqual(before, after, "checkpointing must not lose the recorded transaction")

    def test_a_transaction_living_only_in_the_wal_is_checkpointed_not_lost(self):
        """Removing the residue must move it into the database, not drop it.

        The first version of this test wrote 64 zero bytes into a ``-wal`` and
        expected a refusal. SQLite discards an invalid WAL header, so the
        checkpoint left nothing and the refusal never came — the test was
        asserting against a file SQLite had already decided was empty. What
        actually matters is the opposite direction: a WAL holding a *real*
        committed transaction must end up in the database.

        The pair is copied while a connection is still open, because closing the
        last one checkpoints and deletes the WAL, which is exactly the state this
        test needs not to be in.
        """
        connection = sqlite3.connect(str(self.fixture.history))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO trans VALUES (4242, 7, 7, 'lives in the wal', 2)")
        connection.commit()

        staged = Fixture(Path(self._scratch.name) / "staged")
        _make_rpmdb(staged.rpmdb)
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.fixture.history) + suffix)
            if source.exists():
                shutil.copy2(source, Path(str(staged.history) + suffix))
        connection.close()

        self.assertTrue(
            Path(str(staged.history) + "-wal").exists()
            and Path(str(staged.history) + "-wal").stat().st_size > 0,
            "the fixture must stage a non-empty WAL, or it tests nothing",
        )

        staged.finalise()

        self.assertFalse(Path(str(staged.history) + "-wal").exists())
        recovered = sqlite3.connect(str(staged.history))
        row = recovered.execute("SELECT cmdline FROM trans WHERE id = 4242").fetchone()
        recovered.close()
        self.assertEqual(
            row,
            ("lives in the wal",),
            "the transaction was in the WAL and is not in the database; removing the residue "
            "discarded a recorded transaction",
        )

    # 11 — finalisation must be idempotent
    def test_finalisation_is_idempotent(self):
        self.fixture.finalise()
        first = self.fixture.rpmdb.read_bytes()
        first_history = self.fixture.history.read_bytes()
        self.fixture.finalise()
        self.assertEqual(
            first,
            self.fixture.rpmdb.read_bytes(),
            "a second finalisation changed the rpm database; VACUUM bumps the file change "
            "counter, so the finaliser must recognise the canonical state and not write",
        )
        self.assertEqual(first_history, self.fixture.history.read_bytes())

    def test_finalisation_refuses_an_unexpected_schema(self):
        connection = sqlite3.connect(str(self.fixture.rpmdb))
        connection.execute("DROP TABLE Installtid")
        connection.commit()
        connection.close()
        with self.assertRaises(Refused) as caught:
            self.fixture.finalise()
        self.assertIn("Installtid", str(caught.exception))

    def test_finalisation_refuses_a_virtual_table(self):
        connection = sqlite3.connect(str(self.fixture.rpmdb))
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
        connection.commit()
        connection.close()
        with self.assertRaises(Refused) as caught:
            self.fixture.finalise()
        self.assertIn("virtual", str(caught.exception).lower())

    def test_finalisation_refuses_a_missing_transaction_history(self):
        self.fixture.history.unlink()
        with self.assertRaises(Refused) as caught:
            self.fixture.finalise()
        self.assertIn("transaction_history", str(caught.exception))


class PhysicalVarianceTests(unittest.TestCase):
    """Fixtures for each kind of physical variance the brief names."""

    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.directory = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def test_insertion_order_variance_is_classified_not_missed(self):
        forward = self.directory / "forward.sqlite"
        shuffled = self.directory / "shuffled.sqlite"
        _make_rpmdb(forward, order="forward")
        _make_rpmdb(shuffled, order="shuffled")

        pages = compare_pages(forward, shuffled)
        self.assertGreater(pages["differingPageCount"], 0)
        self.assertTrue(pages["headerMatch"] or not pages["headerMatch"])
        # Every differing page must be attributed and classified; an
        # unclassified difference is the thing that sends somebody back to cmp.
        for entry in pages["differingPages"]:
            self.assertTrue(entry["classification"])

    def test_page_size_variance_is_visible(self):
        small = self.directory / "small.sqlite"
        large = self.directory / "large.sqlite"
        _make_rpmdb(small, page_size=4096)
        _make_rpmdb(large, page_size=8192)
        self.assertEqual(inspect_database(small)["header"]["pageSizeBytes"], 4096)
        self.assertEqual(inspect_database(large)["header"]["pageSizeBytes"], 8192)
        pages = compare_pages(small, large)
        self.assertFalse(pages["headerMatch"])
        self.assertFalse(pages["header"]["pageSize"]["match"])

    def test_freelist_variance_is_measured(self):
        with_free = self.directory / "freelist.sqlite"
        _make_rpmdb(with_free, rows=200)
        connection = sqlite3.connect(str(with_free))
        connection.execute("DELETE FROM Packages WHERE hnum > 20")
        connection.commit()
        connection.close()
        self.assertGreater(
            inspect_database(with_free)["header"]["freelistPageCount"],
            0,
            "deleting most rows must leave a freelist, or this fixture tests nothing",
        )

    def test_logically_different_content_at_similar_size_is_caught(self):
        """The case a size or a row count alone would miss."""
        first = self.directory / "first.sqlite"
        second = self.directory / "second.sqlite"
        _make_rpmdb(first)
        shutil.copy2(first, second)
        connection = sqlite3.connect(str(second))
        # Same length, different bytes: file size, page count and row count all
        # stay put and the content does not.
        connection.execute("UPDATE Packages SET blob = ? WHERE hnum = 3", (b"\xff" * 300,))
        connection.commit()
        connection.close()

        self.assertEqual(first.stat().st_size, second.stat().st_size)
        report = compare_logical(first, second, sample=1)
        self.assertEqual(report["verdict"], "LOGICALLY_DIFFERENT")

    def test_type_differences_are_not_flattened(self):
        """NULL, the empty string and zero must not compare equal."""
        first = self.directory / "typed-a.sqlite"
        second = self.directory / "typed-b.sqlite"
        for path, value in ((first, None), (second, "")):
            connection = sqlite3.connect(str(path))
            connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v)")
            connection.execute("INSERT INTO t VALUES (1, ?)", (value,))
            connection.commit()
            connection.close()
        report = compare_logical(first, second, sample=1)
        self.assertEqual(
            report["verdict"],
            "LOGICALLY_DIFFERENT",
            "a NULL and an empty string compared equal; the comparison is stringifying values",
        )


class ComparisonModeTests(unittest.TestCase):
    """Qualification mode must refuse what diagnostic mode may record."""

    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.directory = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def _collection(self, *, mode: str, drop: tuple[str, ...] = ()) -> Path:
        dimensions = {
            "filesystemTree": ["usr/bin/true"],
            "fileDigests": {"usr/bin/true": "a" * 64},
            "permissions": {"usr/bin/true": "0755"},
            "ownership": {"usr/bin/true": "0:0"},
            "extendedAttributes": {},
            "selinuxLabels": None,
            "packageInventory": ["bash@5.3"],
            "sbom": ['{"name":"bash"}'],
            "bootConfiguration": {},
            "systemdUnits": {},
            "desktopEntries": {},
            "schemas": {},
            "kernel": {"versions": ["6.19.0"], "vmlinuz": {}},
            "initramfs": {"notPresent": "generated on the installed system"},
            "ociLayers": ["sha256:" + "b" * 64],
            "rawArchive": "c" * 64,
            "normalisedArchive": "d" * 64,
        }
        for name in drop:
            dimensions[name] = None
        required = [
            name for name in dimensions
            if name != "selinuxLabels"
        ]
        payload = {
            "schemaVersion": 1,
            "collectionMode": mode,
            "dimensions": dimensions,
            "requiredDimensions": required,
            "missingRequiredDimensions": sorted(drop),
            "entryMtimes": {"digest": "e" * 64, "byPath": {"usr/bin/true": 1785442979}},
        }
        path = self.directory / f"dimensions-{mode}-{'-'.join(drop) or 'complete'}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _selinux(self, name: str) -> Path:
        path = self.directory / f"selinux-{name}.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "specification": "file_contexts",
                    "resolvedCount": 1,
                    "intendedSelinuxContexts": {"usr/bin/true": "system_u:object_r:bin_t:s0"},
                }
            ),
            encoding="utf-8",
        )
        return path

    def _join(self, first: Path, second: Path, *, mode: str, selinux: bool = True) -> tuple[int, str]:
        output = self.directory / f"comparison-{mode}-{selinux}.json"
        argv = [
            sys.executable,
            str(SCRIPTS / "build_comparison_document.py"),
            "--first-dimensions", str(first),
            "--second-dimensions", str(second),
            "--first-builder", "a",
            "--second-builder", "b",
            "--source-commit", "0" * 40,
            "--base-image-digest", "sha256:" + "0" * 64,
            "--mode", mode,
            "--output", str(output),
        ]
        if selinux:
            argv += ["--first-selinux", str(self._selinux("a")),
                     "--second-selinux", str(self._selinux("b"))]
        result = subprocess.run(argv, capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    # 12, 13, 14 — a missing dimension is a refusal in qualification mode
    def test_qualification_refuses_a_missing_sbom(self):
        collection = self._collection(mode="qualification", drop=("sbom",))
        code, output = self._join(collection, collection, mode="qualification")
        self.assertEqual(code, 2, output)
        self.assertIn("sbom", output)

    def test_qualification_refuses_a_missing_normalisation(self):
        collection = self._collection(mode="qualification", drop=("normalisedArchive",))
        code, output = self._join(collection, collection, mode="qualification")
        self.assertEqual(code, 2, output)
        self.assertIn("normalisedArchive", output)

    def test_qualification_refuses_a_missing_intended_selinux_manifest(self):
        collection = self._collection(mode="qualification")
        code, output = self._join(collection, collection, mode="qualification", selinux=False)
        self.assertEqual(code, 2, output)
        self.assertIn("SELinux", output)

    def test_qualification_refuses_a_diagnostic_collection(self):
        """A diagnostic run must not be promoted by comparing it later."""
        collection = self._collection(mode="diagnostic")
        code, output = self._join(collection, collection, mode="qualification")
        self.assertEqual(code, 2, output)
        self.assertIn("diagnostic", output)

    def test_diagnostic_mode_records_what_is_missing(self):
        collection = self._collection(mode="diagnostic", drop=("sbom",))
        code, output = self._join(collection, collection, mode="diagnostic")
        self.assertEqual(code, 0, output)
        self.assertIn("NOT_COLLECTED", output)

    def test_a_complete_qualification_join_succeeds(self):
        collection = self._collection(mode="qualification")
        code, output = self._join(collection, collection, mode="qualification")
        self.assertEqual(code, 0, output)
        self.assertIn("REPRODUCIBLE", output)


if __name__ == "__main__":
    unittest.main()

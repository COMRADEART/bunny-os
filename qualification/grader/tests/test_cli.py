# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The command line, which is what the harness actually calls.

`build/scripts/vm-login-story.sh` ends by invoking
``python3 -m qualification.grader.cli`` and reading its exit status. Everything
the rules do is worthless if that call is wrong, and the call cannot be
exercised by the VM harness without a sixteen-minute run — which is the same
argument that got the grader extracted in the first place.

The defect these were written after finding: ``--merge-into`` did
``merged.update(document)``, so the grader's ``schemaVersion: 1`` silently
overwrote the collector's ``schemaVersion: 2``. A reader checking the record's
shape would have been told it was an older format than it is. Two different
things were sharing one key.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from qualification.grader.cli import main

ROOT = Path(__file__).resolve().parents[3]
RECORDED = ROOT / "qualification" / "phase4" / "release-candidate"


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-grader-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def build(self, source: str, *, journey: str, collector_schema: int = 2) -> Path:
        """A run directory shaped exactly as the collector leaves one."""
        run = self.root / source
        run.mkdir()
        for name in ("interaction.json", "journal-lastboot.log"):
            (run / name).write_bytes((RECORDED / source / name).read_bytes())
        # The shell injects the driver's status into interaction.json.
        document = json.loads((run / "interaction.json").read_text(encoding="utf-8"))
        document["status"] = "complete"
        (run / "interaction.json").write_text(
            json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
        )
        (run / "result.json").write_text(
            json.dumps(
                {
                    "schemaVersion": collector_schema,
                    "harness": "vm-login-story",
                    "collector": "vm-login-story.sh",
                    "machine": "machine.qcow2",
                    "user": "alex",
                    "interactionStatus": "complete",
                    "systemReport": {"etcHostname": "warren"},
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        (run / "expectation.json").write_text(
            json.dumps({"journey": journey, "interaction": True, "graphicalSession": True}),
            encoding="utf-8",
        )
        return run

    @staticmethod
    def run_cli(argv: list[str]) -> int:
        """Call the CLI with its output captured.

        It prints the verdict to stdout by design — a person running it wants
        to see it — and a test suite that let that through would bury its own
        results under a megabyte of JSON.
        """
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(argv)

    def grade(self, run: Path) -> int:
        return self.run_cli(
            [
                str(run),
                "--user", "alex",
                "--merge-into", str(run / "result.json"),
                "--output", str(run / "result.json"),
            ]
        )

    def test_a_good_run_exits_zero(self) -> None:
        self.assertEqual(self.grade(self.build("g12", journey="granted")), 0)

    def test_the_historical_false_pass_exits_six(self) -> None:
        """6, not 1, because the shell harness this replaces used 6 and a caller
        that tested for it keeps working."""
        self.assertEqual(self.grade(self.build("g7", journey="granted")), 6)

    def test_an_empty_run_exits_seven(self) -> None:
        """NOT_RUN has its own status. Under the shell harness it shared 0 with
        a run that measured everything and was fine."""
        run = self.root / "nothing"
        run.mkdir()
        self.assertEqual(self.run_cli([str(run), "--output", "-"]), 7)

    def test_a_missing_directory_exits_two(self) -> None:
        self.assertEqual(self.run_cli([str(self.root / "absent"), "--output", "-"]), 2)

    def test_the_collectors_schema_version_survives_the_merge(self) -> None:
        """The regression this file was written for.

        Both sides own ``schemaVersion`` and it means a different thing to each:
        the collector's describes the file, the grader's describes the verdict
        inside it. They are versioned independently because they change for
        different reasons, so neither may silently overwrite the other.
        """
        run = self.build("g12", journey="granted", collector_schema=2)
        self.grade(run)
        document = json.loads((run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(document["schemaVersion"], 2, "the collector's version was overwritten")
        self.assertEqual(document["graderSchemaVersion"], 1)

    def test_everything_the_collector_recorded_is_carried_through(self) -> None:
        """A grader that dropped what it does not model would be narrowing the
        record every time it ran."""
        run = self.build("g12", journey="granted")
        self.grade(run)
        document = json.loads((run / "result.json").read_text(encoding="utf-8"))
        for field in ("harness", "collector", "machine", "user", "interactionStatus"):
            with self.subTest(field=field):
                self.assertIn(field, document)
        self.assertEqual(document["systemReport"], {"etcHostname": "warren"})

    def test_the_verdict_is_in_the_record(self) -> None:
        run = self.build("g12", journey="granted")
        self.grade(run)
        document = json.loads((run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(document["outcome"], "PASS")
        self.assertTrue(document["explanation"])
        self.assertEqual(document["grader"], "qualification.grader")
        self.assertIn("machine", document["dimensions"])

    def test_output_dash_writes_nothing(self) -> None:
        """The mode a replay over committed evidence should use.

        §6 holds for the library unconditionally; the CLI is the one module
        allowed to write, so the mode that does not write has to exist and has
        to be checked.
        """
        run = self.build("g12", journey="granted")
        before = sorted(p.name for p in run.iterdir())
        digest = (run / "result.json").read_bytes()
        self.run_cli([str(run), "--user", "alex", "--output", "-"])
        self.assertEqual(sorted(p.name for p in run.iterdir()), before)
        self.assertEqual((run / "result.json").read_bytes(), digest)

    def test_an_explicit_flag_declares_the_run_even_without_a_sidecar(self) -> None:
        """A caller that names what the run was for has declared it.

        Otherwise a chain that passes `--expect-journey` on the command line
        would still be told, by RI03, that it declared nothing.
        """
        run = self.build("g12", journey="granted")
        (run / "expectation.json").unlink()
        status = self.run_cli([str(run), "--user", "alex", "--expect-journey", "granted",
                               "--output", str(run / "verdict.json")])
        self.assertEqual(status, 0)
        document = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
        self.assertTrue(document["expectation"]["declared"])
        self.assertNotIn("RI03", {finding["rule"] for finding in document["findings"]})


if __name__ == "__main__":
    unittest.main()

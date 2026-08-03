# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the evidence byte-policy verifier.

The verifier exists to remove a hand-edit. Before it, the collector wrote null
for ``git.byteRoundtripTestsPass`` and the operator checklist asked a human to
change it to true, which made one mandatory gate condition satisfiable by typing
a word — the condition guarding the property that a whole PR was written to
protect.

So the property under test is not "does it say true when things are fine". It is
"does it say false when they are not", because a field that only ever gains a
true is a field nobody is measuring.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parents[2]

spec = importlib.util.spec_from_file_location("byte_policy", SCRIPTS / "verify-git-byte-policy.py")
byte_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(byte_policy)


def environment_stub(value=None) -> dict:
    return {"git": {"version": "git 2.47", "autocrlf": "false", "byteRoundtripTestsPass": value}}


class DiscoveryTests(unittest.TestCase):
    def test_it_points_at_the_repository_root(self):
        self.assertTrue((byte_policy.ROOT / ".git").exists(), byte_policy.ROOT)

    def test_the_attested_paths_are_discovered(self):
        self.assertGreaterEqual(len(byte_policy.attested_paths()), 7)

    def test_every_declared_check_is_callable(self):
        for name, check in byte_policy.CHECKS:
            self.assertTrue(callable(check), name)


class RecordingTests(unittest.TestCase):
    """The field must be written from a measurement, in both directions."""

    def _write(self, value: bool) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "environment.json"
            path.write_text(json.dumps(environment_stub()), encoding="utf-8")
            byte_policy.update_environment(path, value)
            return json.loads(path.read_text(encoding="utf-8"))["git"]["byteRoundtripTestsPass"]

    def test_a_passing_measurement_records_true(self):
        self.assertIs(self._write(True), True)

    def test_a_failing_measurement_records_false(self):
        """The outcome a hand-edit would never produce."""
        self.assertIs(self._write(False), False)

    def test_it_overwrites_an_existing_true_with_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "environment.json"
            path.write_text(json.dumps(environment_stub(True)), encoding="utf-8")
            byte_policy.update_environment(path, False)
            self.assertIs(
                json.loads(path.read_text(encoding="utf-8"))["git"]["byteRoundtripTestsPass"],
                False,
                "a stale true must not survive a failing measurement",
            )

    def test_it_leaves_the_rest_of_the_report_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "environment.json"
            original = {"role": "host", "git": {"version": "git 2.47",
                                                "autocrlf": "false",
                                                "byteRoundtripTestsPass": None}}
            path.write_text(json.dumps(original), encoding="utf-8")
            byte_policy.update_environment(path, True)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["role"], "host")
            self.assertEqual(updated["git"]["version"], "git 2.47")


class MeasurementTests(unittest.TestCase):
    def test_this_repository_currently_satisfies_the_policy(self):
        result = byte_policy.measure()
        failed = [c for c in result["checks"] if not c["passed"]]
        self.assertEqual(failed, [], f"byte policy failing: {failed}")
        self.assertTrue(result["passed"])

    def test_the_invalidated_record_check_is_wired_in(self):
        names = [name for name, _ in byte_policy.CHECKS]
        self.assertIn("invalidated-record-remains-invalidated", names)

    def test_the_invalidated_record_is_still_invalidated(self):
        passed, problems = byte_policy.check_invalidated_registry()
        self.assertTrue(passed, problems)


class ExitCodeTests(unittest.TestCase):
    def test_a_satisfied_policy_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify-git-byte-policy.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)


class ChecklistTests(unittest.TestCase):
    """The instruction this script replaces must be gone from the checklist.

    A verifier that nobody is told to run leaves the hand-edit in place, so the
    documentation is part of the fix rather than a description of it.
    """

    def test_the_checklist_no_longer_asks_for_a_hand_edit(self):
        checklist = (HERE.parent / "OPERATOR_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "Set `git.byteRoundtripTestsPass` to `true`",
            checklist,
            "the checklist still instructs a hand-edit of a mandatory gate condition",
        )

    def test_the_checklist_invokes_the_verifier(self):
        checklist = (HERE.parent / "OPERATOR_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("verify-git-byte-policy.py", checklist)


if __name__ == "__main__":
    unittest.main()

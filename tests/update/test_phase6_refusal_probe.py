# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Phase 6 update-refusal probe and the evidence it produced.

The probe itself can only run inside a container built from the subject image,
so the reference suite cannot execute it. What the reference suite *can* do is
test the part that decides the verdict, and check that the recorded evidence
says what the policy claims it says.

Both halves matter, and for different reasons.

``summarise`` is tested because a probe that silently stops running checks is
the failure this project keeps finding: four separate harnesses have reported
PASS while measuring nothing. ``summarise`` refuses a run that is missing a
required check, so the instrument cannot be quietly narrowed and stay green.

The evidence fixtures are tested because §10 option B rests on them. A policy
that declares updates unsupported is only as good as the run that showed the
refusal is real, and a run whose negative control did not fire showed nothing.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "qualification" / "phase6" / "update" / "refusal_probe.py"
EVIDENCE = ROOT / "qualification" / "phase6" / "update" / "evidence"
RUN = EVIDENCE / "refusal-qualification.json"
CONTROL = EVIDENCE / "negative-control" / "refusal-qualification.json"


def load_probe():
    loader = importlib.machinery.SourceFileLoader("phase6_refusal_probe", str(PROBE))
    spec = importlib.util.spec_from_loader("phase6_refusal_probe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def check(ident, verdict="AS_INTENDED"):
    return {
        "id": ident,
        "question": "q",
        "expected": "e",
        "observed": "o",
        "verdict": verdict,
        "detail": None,
    }


class SummariseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.probe = load_probe()

    def complete(self, **overrides):
        return [check(ident, overrides.get(ident, "AS_INTENDED"))
                for ident in self.probe.REQUIRED_CHECKS]

    def test_a_complete_run_with_every_check_intended_is_as_intended(self) -> None:
        summary = self.probe.summarise(self.complete())
        self.assertEqual(summary["result"], "AS_INTENDED")
        self.assertEqual(summary["missingChecks"], [])
        self.assertEqual(summary["unexpectedChecks"], [])
        self.assertEqual(summary["asIntended"], len(self.probe.REQUIRED_CHECKS))

    def test_one_unexpected_check_fails_the_whole_run(self) -> None:
        summary = self.probe.summarise(self.complete(B3="UNEXPECTED"))
        self.assertEqual(summary["result"], "UNEXPECTED")
        self.assertEqual(summary["unexpectedChecks"], ["B3"])

    def test_a_run_missing_a_required_check_is_incomplete_not_passing(self) -> None:
        """The failure mode this guards: a probe that stops early and looks green."""
        results = [record for record in self.complete() if record["id"] != "B3"]
        summary = self.probe.summarise(results)
        self.assertEqual(summary["result"], "INCOMPLETE")
        self.assertEqual(summary["missingChecks"], ["B3"])
        # Every check it *did* run was intended. That must not be enough.
        self.assertEqual(summary["unexpectedChecks"], [])

    def test_an_empty_run_is_incomplete_rather_than_vacuously_intended(self) -> None:
        summary = self.probe.summarise([])
        self.assertEqual(summary["result"], "INCOMPLETE")
        self.assertEqual(summary["checks"], 0)
        self.assertEqual(len(summary["missingChecks"]), len(self.probe.REQUIRED_CHECKS))

    def test_a_duplicated_check_invalidates_the_run(self) -> None:
        """Two records for one id means one of them was overwritten in reporting."""
        summary = self.probe.summarise(self.complete() + [check("B3")])
        self.assertEqual(summary["result"], "INVALID")
        self.assertEqual(summary["duplicateChecks"], ["B3"])

    def test_the_negative_control_is_a_required_check(self) -> None:
        """B3 is what makes every refusal in the run mean something."""
        self.assertIn("B3", self.probe.REQUIRED_CHECKS)

    def test_status_is_asked_before_anything_writes_a_status_file(self) -> None:
        """A0 must precede A4-A7, or it reads a stale record instead of idle.

        This ordering is not cosmetic: the first version of the probe asked
        ``status`` last, observed the leftover failure from ``check``, and
        passed anyway because it only asserted the exit code.
        """
        order = list(self.probe.REQUIRED_CHECKS)
        for later in ("A4", "A5", "A6", "A7"):
            self.assertLess(order.index("A0"), order.index(later))


class RecordedEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.probe = load_probe()

    def test_the_run_against_the_subject_image_is_complete_and_as_intended(self) -> None:
        document = json.loads(RUN.read_text(encoding="utf-8"))
        self.assertEqual(document["result"], "AS_INTENDED")
        self.assertEqual(document["missingChecks"], [])
        self.assertEqual(document["duplicateChecks"], [])
        self.assertEqual(document["checks"], len(self.probe.REQUIRED_CHECKS))

    def test_the_recorded_run_covers_every_currently_required_check(self) -> None:
        """Adding a required check must invalidate the old evidence, not pass on it."""
        document = json.loads(RUN.read_text(encoding="utf-8"))
        recorded = {record["id"] for record in document["results"]}
        self.assertEqual(recorded, set(self.probe.REQUIRED_CHECKS))

    def test_the_negative_control_run_actually_failed(self) -> None:
        """Without this, AS_INTENDED above could mean the probe cannot fail."""
        document = json.loads(CONTROL.read_text(encoding="utf-8"))
        self.assertEqual(document["result"], "UNEXPECTED")
        self.assertGreater(len(document["unexpectedChecks"]), 0)

    def test_the_negative_control_flipped_the_checks_the_policy_relies_on(self) -> None:
        """Planting a key and enabling updates must break the trust-store checks.

        If A1 (empty store) and C1 (disabled config refuses independently)
        stayed green under those conditions, they were never measuring the
        conditions the unsupported-update policy names.
        """
        document = json.loads(CONTROL.read_text(encoding="utf-8"))
        flipped = set(document["unexpectedChecks"])
        for ident in ("A1", "A2", "A4", "C1"):
            self.assertIn(ident, flipped, f"{ident} did not respond to the control")

    def test_the_negative_control_left_the_key_independent_checks_alone(self) -> None:
        """B3 and D1-D3 do not depend on the store being empty, so they must hold.

        A control that flipped *everything* would be evidence of a broken run,
        not of a working instrument.
        """
        document = json.loads(CONTROL.read_text(encoding="utf-8"))
        flipped = set(document["unexpectedChecks"])
        for ident in ("B3", "B4", "D1", "D2", "D3"):
            self.assertNotIn(ident, flipped, f"{ident} should not depend on the control")


if __name__ == "__main__":
    unittest.main()

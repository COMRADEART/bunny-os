# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The grader, replayed over real Phase 4 runs.

This is the check Phase 4 named and could not make. Its report says:

    "Before trusting a strengthened grader, replay it over a recorded run that
    should fail."

Phase 4 did that once, by hand, in a shell. Here it is a test, and the run
that should fail is ``g7`` — a granted Trust journey whose own record says
``final.state: "error"``, ``final.says: "the task failed"``, ``result.files:
[]``, and which was recorded at the time as ``findings: []``.

The fixtures point at the committed evidence in place rather than at a copy.
Evidence in this project is immutable, so the target is stable, and grading the
actual recorded bytes is stronger than grading a snapshot that could drift.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from qualification.grader import grade, load_evidence
from qualification.grader.models import Expectation, Outcome

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "recorded.json"


def fixtures() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]


def by_id(identifier: str) -> dict:
    for fixture in fixtures():
        if fixture["id"] == identifier:
            return fixture
    raise KeyError(identifier)


def grade_fixture(fixture: dict):
    run = ROOT / fixture["run"]
    expectation = (
        Expectation.from_json(fixture["expectation"])
        if fixture["expectation"]
        else Expectation.undeclared()
    )
    return grade(load_evidence(run, user=fixture["user"]), expectation)


class RecordedEvidenceTests(unittest.TestCase):
    def test_every_fixture_names_a_run_that_still_exists(self) -> None:
        """A fixture pointing at a deleted run is a test that quietly stops testing."""
        for fixture in fixtures():
            with self.subTest(fixture=fixture["id"]):
                run = ROOT / fixture["run"]
                self.assertTrue(run.is_dir(), f"{fixture['run']} is gone")
                self.assertTrue((run / "interaction.json").is_file() or fixture["expectation"])

    def test_each_recorded_run_grades_to_its_declared_outcome(self) -> None:
        for fixture in fixtures():
            with self.subTest(fixture=fixture["id"]):
                verdict = grade_fixture(fixture)
                want = fixture["expect"]
                self.assertEqual(
                    verdict.outcome.value,
                    want["outcome"],
                    f"{fixture['id']}: {verdict.explanation}",
                )
                dimensions = {d.name: d.outcome.value for d in verdict.dimensions}
                self.assertEqual(dimensions, want["dimensions"], fixture["id"])
                blocking = sorted({f.rule for f in verdict.blocking_findings})
                self.assertEqual(blocking, want["blockingRules"], fixture["id"])
                if "advisoryRules" in want:
                    advisory = sorted({f.rule for f in verdict.advisory_findings})
                    self.assertEqual(advisory, want["advisoryRules"], fixture["id"])


class TheHistoricalFalsePassTests(unittest.TestCase):
    """The regression that gives this package its reason to exist.

    Each assertion is written against the *record*, not against the grader, so
    that a future change to the grader cannot make these pass by changing what
    the fixture means.
    """

    def setUp(self) -> None:
        self.fixture = by_id("historical-false-pass")
        self.run = ROOT / self.fixture["run"]
        self.verdict = grade_fixture(self.fixture)

    def test_the_run_this_fixture_names_really_was_recorded_as_a_pass(self) -> None:
        recorded = json.loads((self.run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["findings"], [], "g7 was recorded with no findings")
        self.assertIsNone(
            recorded.get("journeyVerdict"),
            "g7 predates the journey verdict; that is why it passed",
        )

    def test_the_journey_record_says_the_task_failed(self) -> None:
        interaction = json.loads((self.run / "interaction.json").read_text(encoding="utf-8"))
        journey = interaction["journey"]
        self.assertEqual(journey["decision"], "granted")
        self.assertEqual(journey["final"]["state"], "error")
        self.assertEqual(journey["final"]["says"], "the task failed")
        self.assertEqual(journey["result"]["files"], [])

    def test_the_grader_now_fails_it(self) -> None:
        self.assertIs(self.verdict.outcome, Outcome.FAIL)

    def test_it_fails_on_the_outcome_and_not_on_the_machine(self) -> None:
        """The machine was healthy. Health was never the question.

        If this test ever fails because the *machine* dimension went red, the
        grader has started failing g7 for the wrong reason and the regression
        it guards has quietly stopped being guarded.
        """
        dimensions = {d.name: d.outcome for d in self.verdict.dimensions}
        self.assertIs(dimensions["machine"], Outcome.PASS)
        self.assertIs(dimensions["journey"], Outcome.FAIL)

    def test_the_explanation_says_what_went_wrong_in_words(self) -> None:
        self.assertIn("produced nothing", self.verdict.explanation)
        self.assertIn("error state", self.verdict.explanation)

    def test_the_two_good_runs_still_pass_under_the_same_grader(self) -> None:
        """A check that rejects everything is not a check.

        Phase 4's rule: a strengthened grader is only trustworthy once it has
        been shown to fail the bad run *and* pass the good ones.
        """
        for identifier in ("trust-granted", "trust-denied"):
            with self.subTest(fixture=identifier):
                self.assertIs(grade_fixture(by_id(identifier)).outcome, Outcome.PASS)


class TheDenialIsAMeasurementTests(unittest.TestCase):
    """`g13` proves denial prevents execution, and the proof needs `g12`.

    "No capsule started" is only evidence if the same line appears when one
    does. Both halves are asserted here so that an instrument change which
    stopped emitting the line entirely would fail rather than silently turn
    every denial into a pass.
    """

    def test_the_granted_run_shows_the_line_the_denied_run_lacks(self) -> None:
        granted = ROOT / by_id("trust-granted")["run"] / "journal-lastboot.log"
        denied = ROOT / by_id("trust-denied")["run"] / "journal-lastboot.log"
        granted_text = granted.read_text(encoding="utf-8", errors="replace")
        denied_text = denied.read_text(encoding="utf-8", errors="replace")
        self.assertIn("Started bunny-capsule", granted_text)
        self.assertNotIn("Started bunny-capsule", denied_text)

    def test_the_denied_fixture_cleared_the_file_the_granted_run_made(self) -> None:
        """Otherwise 'nothing was produced' cannot be told from 'it was already there'."""
        denied = json.loads(
            (ROOT / by_id("trust-denied")["run"] / "interaction.json").read_text(encoding="utf-8")
        )
        cleared = denied["journey"]["fixture"]["clearedExports"]
        self.assertTrue(cleared)
        self.assertTrue(any("holiday-resized.png" in path for path in cleared))


class UndeclaredRunsTests(unittest.TestCase):
    def test_a_run_that_declares_nothing_is_told_so(self) -> None:
        verdict = grade_fixture(by_id("trust-granted-undeclared"))
        self.assertIn("RI03", {finding.rule for finding in verdict.advisory_findings})
        self.assertIs(verdict.outcome, Outcome.PASS)

    def test_the_advisory_does_not_change_the_outcome(self) -> None:
        """Every run recorded before Phase 5 is undeclared.

        A rule that retroactively failed the evidence it was written to protect
        is a rule somebody would delete within a week.
        """
        declared = grade_fixture(by_id("trust-granted"))
        undeclared = grade_fixture(by_id("trust-granted-undeclared"))
        self.assertEqual(declared.outcome, undeclared.outcome)

    def test_a_photograph_only_run_fails_if_it_claimed_it_would_drive(self) -> None:
        """Defect 3, on real evidence.

        `g10` is a photograph-only run and passes as one. Declared as a run
        that would drive a session, the same bytes fail.
        """
        fixture = dict(by_id("photograph-only-run"))
        self.assertIs(grade_fixture(fixture).outcome, Outcome.PASS)
        fixture["expectation"] = {"journey": None, "interaction": True, "graphicalSession": True}
        self.assertIs(grade_fixture(fixture).outcome, Outcome.FAIL)


if __name__ == "__main__":
    unittest.main()

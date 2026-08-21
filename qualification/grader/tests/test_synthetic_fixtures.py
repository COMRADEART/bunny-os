# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One failing case per rule, written by hand.

A rule with no case that fires it is a rule nobody has seen work. Phase 4 shipped
five journal checks that had never been observed failing, and the one that
mattered — "did the journey do what it went there to do" — did not exist at all.

The cases are materialised into a temporary directory rather than committed as
run directories, because they are inputs to the loader as much as to the rules:
grading them exercises the real ``load_evidence`` path, including the parts that
decide what a missing file means.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qualification.grader import grade_run_directory
from qualification.grader.models import Outcome
from qualification.grader.rules import ALL_RULES, JOURNEY_RULES, MACHINE_RULES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic.json"


def document() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def materialise(case: dict, root: Path) -> Path:
    """Write one case out as a run directory the loader can read."""
    whole = document()
    run = root / case["id"]
    run.mkdir(parents=True)

    journal = case.get("journal")
    if journal == "healthy":
        text = "\n".join(whole["healthyJournal"]) + "\n"
    elif journal == "healthy+capsule":
        text = "\n".join([*whole["healthyJournal"], whole["capsuleLine"]]) + "\n"
    elif isinstance(journal, str):
        text = journal
    else:
        text = None
    if text is not None:
        (run / "journal-lastboot.log").write_text(text, encoding="utf-8")

    if case.get("interaction") is not None:
        (run / "interaction.json").write_text(
            json.dumps(case["interaction"], indent=1), encoding="utf-8"
        )
    if case.get("findings"):
        (run / "findings.txt").write_text("\n".join(case["findings"]), encoding="utf-8")
    if case.get("expectation") is not None:
        (run / "expectation.json").write_text(
            json.dumps(case["expectation"], indent=1), encoding="utf-8"
        )
    (run / "result.json").write_text(json.dumps({"user": "alex"}, indent=1), encoding="utf-8")
    return run


class SyntheticCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-grader-cases-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_every_case_grades_to_its_declared_outcome(self) -> None:
        for case in document()["cases"]:
            with self.subTest(case=case["id"]):
                verdict = grade_run_directory(materialise(case, self.root))
                want = case["expect"]
                self.assertEqual(
                    verdict.outcome.value, want["outcome"], f"{case['id']}: {verdict.explanation}"
                )
                dimensions = {d.name: d.outcome.value for d in verdict.dimensions}
                self.assertEqual(dimensions, want["dimensions"], case["id"])
                blocking = sorted({f.rule for f in verdict.blocking_findings})
                self.assertEqual(blocking, want["blockingRules"], case["id"])
                if "advisoryRules" in want:
                    advisory = sorted({f.rule for f in verdict.advisory_findings})
                    self.assertEqual(advisory, want["advisoryRules"], case["id"])

    def test_every_case_carries_a_reason_for_existing(self) -> None:
        for case in document()["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case.get("why"), "a fixture without a why is a fixture nobody can maintain")

    def test_every_rule_has_at_least_one_case_that_fires_it(self) -> None:
        """The coverage claim, checked rather than asserted.

        Counts rules by the identifiers that actually appear in a verdict over
        the *synthetic* set alone — deliberately not counting the recorded
        fixtures, so that a rule cannot be considered covered because one
        committed run happens to trip it. A rule added without a case fails
        here, which is the only way this stays true after today.

        It has already earned its place: written before the cases were
        complete, it found that RJ04 and RJ06 — the two rules that fail the
        historical false pass — fired on recorded evidence and on no
        hand-written case at all.
        """
        fired: set[str] = set()
        for case in document()["cases"]:
            verdict = grade_run_directory(materialise(case, self.root))
            fired.update(finding.rule for finding in verdict.findings)

        # RM05a fires only when the strict display-manager string is missing and
        # the loose one is present, which no synthetic case constructs; it is
        # covered directly in test_rules_in_isolation.
        expected = {
            "RM01", "RM02", "RM03", "RM04", "RM05", "RM06",
            "RI01", "RI02", "RI03",
            "RJ01", "RJ02", "RJ03", "RJ04", "RJ05", "RJ06",
            "RJ07", "RJ08", "RJ09", "RJ10", "RJ11", "RJ12", "RJ13",
        }
        self.assertEqual(expected - fired, set(), "these rules have no case that fires them")

    def test_a_clean_run_fires_no_rule_at_all(self) -> None:
        """The positive control.

        Without it, a grader that returned a finding for everything would pass
        every negative case above and look thorough.
        """
        clean = next(c for c in document()["cases"] if c["id"] == "a-clean-granted-journey")
        verdict = grade_run_directory(materialise(clean, self.root))
        self.assertEqual(list(verdict.findings), [])
        self.assertIs(verdict.outcome, Outcome.PASS)


class NotRunIsNotAPassTests(unittest.TestCase):
    """§4's third answer, and the reason it is a separate one.

    Phase 4's harness had two states, and "nothing was measured" shared the
    green one with "everything measured was fine".
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-grader-notrun-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_an_empty_run_is_not_run_rather_than_passed(self) -> None:
        run = self.root / "empty"
        run.mkdir()
        verdict = grade_run_directory(run)
        self.assertIs(verdict.outcome, Outcome.NOT_RUN)
        self.assertIsNot(verdict.outcome, Outcome.PASS)

    def test_a_missing_journal_does_not_count_as_a_healthy_machine(self) -> None:
        run = self.root / "no-journal"
        run.mkdir()
        (run / "interaction.json").write_text('{"status": "complete"}', encoding="utf-8")
        verdict = grade_run_directory(run)
        machine = next(d for d in verdict.dimensions if d.name == "machine")
        self.assertIs(machine.outcome, Outcome.NOT_RUN)
        self.assertIn("nothing about the machine was measured", machine.explanation)

    def test_a_pass_always_names_what_it_did_not_grade(self) -> None:
        """A pass that quietly measured two of three dimensions is a false pass.

        So the sentence a reader sees has to carry the gap, every time.
        """
        run = self.root / "partial"
        run.mkdir()
        (run / "interaction.json").write_text('{"status": "complete"}', encoding="utf-8")
        verdict = grade_run_directory(run)
        self.assertIs(verdict.outcome, Outcome.PASS)
        self.assertIn("not graded:", verdict.explanation)
        self.assertIn("machine", verdict.explanation.split("not graded:")[1])
        self.assertIn("journey", verdict.explanation.split("not graded:")[1])


class RuleRegistryTests(unittest.TestCase):
    def test_the_registry_holds_every_rule_family(self) -> None:
        self.assertEqual(len(ALL_RULES), len(set(ALL_RULES)))
        for rule in MACHINE_RULES + JOURNEY_RULES:
            self.assertIn(rule, ALL_RULES)

    def test_every_rule_documents_itself(self) -> None:
        for rule in ALL_RULES:
            with self.subTest(rule=rule.__name__):
                self.assertTrue(rule.__doc__, f"{rule.__name__} has no docstring")


if __name__ == "__main__":
    unittest.main()

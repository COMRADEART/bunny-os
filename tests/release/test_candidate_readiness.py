# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Candidate prerequisites, the dashboard, and the source gate.

The mandated adversarial cases exercised here:

* a stable candidate built with an unresolved ``Unknown`` (case 16)
* stale evidence accepted (case 18)
"""

from __future__ import annotations

import datetime as _datetime
import json
from pathlib import Path
import unittest

from release.candidate import (
    CANDIDATE_PREREQUISITES,
    DEFAULT_MAX_AGE_DAYS,
    OWNERS,
    PREREQUISITE_IDS,
    SATISFIED_STATES,
    STATES,
    CandidateError,
    build_row,
    evaluate_candidate,
    render_dashboard,
)
from release.gates import (
    SOURCE_GATE_REQUIREMENTS,
    GateError,
    evaluate_candidate_gate,
    evaluate_source_gate,
)

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "80df25b09f6578276d18c8a82f15c47dd8959740"
OTHER_COMMIT = "79bb99ddb39d8a5dbc279629f43b23346fb0e5e8"
NOW = _datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc)


def all_satisfied() -> dict[str, dict[str, object]]:
    return {
        name: {
            "satisfied": True,
            "evidence": f"{name} evidence",
            "commit": COMMIT,
            "generatedAt": "2026-07-29T00:00:00Z",
        }
        for name in PREREQUISITE_IDS
    }


class FourteenPrerequisites(unittest.TestCase):
    def test_there_are_fourteen(self) -> None:
        self.assertEqual(len(CANDIDATE_PREREQUISITES), 14)

    def test_every_prerequisite_names_an_owner_who_can_satisfy_it(self) -> None:
        for definition in CANDIDATE_PREREQUISITES:
            self.assertIn(definition["owner"], OWNERS, definition["id"])

    def test_no_absent_state_is_pass(self) -> None:
        # The fail-closed property: adding a prerequisite cannot make a candidate
        # pass by accident.
        for definition in CANDIDATE_PREREQUISITES:
            self.assertNotIn(definition["absentState"], SATISFIED_STATES, definition["id"])

    def test_an_absent_observation_takes_the_absent_state(self) -> None:
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        self.assertFalse(readiness.ready)
        self.assertEqual(len(readiness.unsatisfied), 14)

    def test_all_satisfied_is_ready(self) -> None:
        readiness = evaluate_candidate(all_satisfied(), sourceCommit=COMMIT, now=NOW)
        self.assertTrue(readiness.ready)
        self.assertTrue(readiness.as_dict()["candidateLabelPermitted"])

    def test_one_unsatisfied_prerequisite_blocks(self) -> None:
        observations = all_satisfied()
        observations["physical-hardware-evidence"] = {
            "satisfied": False,
            "state": "PENDING_HARDWARE",
            "evidence": "zero reports",
        }
        readiness = evaluate_candidate(observations, sourceCommit=COMMIT, now=NOW)
        self.assertFalse(readiness.ready)
        self.assertEqual([row.id for row in readiness.unsatisfied], ["physical-hardware-evidence"])

    def test_an_unknown_prerequisite_is_rejected(self) -> None:
        with self.assertRaises(CandidateError):
            evaluate_candidate({"vibes": {"satisfied": True}}, sourceCommit=COMMIT, now=NOW)

    def test_only_pass_satisfies(self) -> None:
        self.assertEqual(SATISFIED_STATES, frozenset({"PASS"}))
        for state in STATES:
            if state == "PASS":
                continue
            row = build_row(
                CANDIDATE_PREREQUISITES[0],
                {"satisfied": False, "state": state},
                sourceCommit=COMMIT,
                now=NOW,
            )
            self.assertFalse(row.satisfied, state)


class UnresolvedUnknownBlocksACandidate(unittest.TestCase):
    """Adversarial case 16."""

    def test_a_pending_vulnerability_review_blocks_the_candidate_gate(self) -> None:
        observations = all_satisfied()
        observations["vulnerability-gate"] = {
            "satisfied": False,
            "state": "PENDING_EXTERNAL_REVIEW",
            "evidence": "24 per-CVE analyses; 24 unresolved",
            "blocker": "24 Critical/High advisories remain Unknown",
        }
        readiness = evaluate_candidate(observations, sourceCommit=COMMIT, now=NOW)
        detail = readiness.as_dict()
        result = evaluate_candidate_gate(
            prerequisitesReady=readiness.ready,
            unsatisfied=tuple(detail["unsatisfied"]),
            detail=detail,
        )
        self.assertEqual(result.recommendation, "BLOCKED")
        self.assertFalse(result.passed)

    def test_the_committed_state_blocks_on_the_vulnerability_gate(self) -> None:
        payload = json.loads(
            (ROOT / "build/out/qualification/qualification-candidate.json").read_text(encoding="utf-8")
        ) if (ROOT / "build/out/qualification/qualification-candidate.json").is_file() else None
        if payload is None:
            self.skipTest("run scripts/release.py gate --kind qualification-candidate first")
        self.assertIn("vulnerability-gate", payload["unsatisfied"])
        self.assertFalse(payload["ready"])

    def test_a_blocking_candidate_gate_does_not_forbid_building(self) -> None:
        result = evaluate_candidate_gate(
            prerequisitesReady=False, unsatisfied=("vulnerability-gate",), detail={}
        )
        self.assertIn("does not forbid building an artifact", result.detail["meaning"])


class StaleEvidenceIsRefused(unittest.TestCase):
    """Adversarial case 18."""

    def test_a_pass_from_another_commit_becomes_stale(self) -> None:
        row = build_row(
            CANDIDATE_PREREQUISITES[0],
            {"satisfied": True, "commit": OTHER_COMMIT, "evidence": "licence gate"},
            sourceCommit=COMMIT,
            now=NOW,
        )
        self.assertEqual(row.state, "STALE")
        self.assertFalse(row.satisfied)
        self.assertIn("candidate is", row.evidence)

    def test_a_pass_older_than_the_freshness_limit_becomes_stale(self) -> None:
        generated = (NOW - _datetime.timedelta(days=DEFAULT_MAX_AGE_DAYS + 1)).isoformat()
        row = build_row(
            CANDIDATE_PREREQUISITES[0],
            {"satisfied": True, "commit": COMMIT, "generatedAt": generated},
            sourceCommit=COMMIT,
            now=NOW,
        )
        self.assertEqual(row.state, "STALE")
        self.assertIn("freshness limit", row.evidence)

    def test_a_pass_within_the_freshness_limit_stands(self) -> None:
        generated = (NOW - _datetime.timedelta(days=DEFAULT_MAX_AGE_DAYS - 1)).isoformat()
        row = build_row(
            CANDIDATE_PREREQUISITES[0],
            {"satisfied": True, "commit": COMMIT, "generatedAt": generated},
            sourceCommit=COMMIT,
            now=NOW,
        )
        self.assertEqual(row.state, "PASS")

    def test_stale_evidence_makes_the_candidate_unready(self) -> None:
        observations = all_satisfied()
        observations["licence-gate"]["commit"] = OTHER_COMMIT
        readiness = evaluate_candidate(observations, sourceCommit=COMMIT, now=NOW)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.unsatisfied[0].state, "STALE")

    def test_age_is_reported_even_for_a_passing_row(self) -> None:
        readiness = evaluate_candidate(all_satisfied(), sourceCommit=COMMIT, now=NOW)
        for row in readiness.rows:
            self.assertIsNotNone(row.ageDays)


class Dashboard(unittest.TestCase):
    def test_there_are_eight_states(self) -> None:
        self.assertEqual(len(STATES), 8)
        for name in (
            "PASS",
            "FAIL",
            "BLOCKED",
            "NOT_RUN",
            "STALE",
            "PENDING_EXTERNAL_REVIEW",
            "PENDING_OWNER",
            "PENDING_HARDWARE",
        ):
            self.assertIn(name, STATES)

    def test_the_dashboard_shows_every_required_column(self) -> None:
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        rendered = render_dashboard(readiness)
        for column in ("Owner", "Evidence", "Commit", "Age", "Blocker", "Next action", "Dependency"):
            self.assertIn(column, rendered)

    def test_the_dashboard_shows_no_aggregate_percentage(self) -> None:
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        rendered = render_dashboard(readiness)
        self.assertNotIn("%", rendered)
        self.assertIn("No aggregate percentage is shown", rendered)

    def test_every_unsatisfied_row_names_a_next_action(self) -> None:
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        for row in readiness.unsatisfied:
            self.assertNotEqual(row.nextAction, "none", row.id)
            self.assertNotEqual(row.nextAction, "unassigned", row.id)

    def test_a_third_party_row_never_says_run_the_check(self) -> None:
        # Misfiling a third-party requirement as an engineering task is how a
        # project talks itself into self-reviewing.
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        for row in readiness.rows:
            if row.owner in {"independent-reviewer", "physical-hardware", "second-authorised-signer", "owner-decision"}:
                self.assertNotIn("run the check", row.nextAction, row.id)

    def test_every_state_has_a_row_in_the_states_table(self) -> None:
        readiness = evaluate_candidate({}, sourceCommit=COMMIT, now=NOW)
        rendered = render_dashboard(readiness)
        for state in STATES:
            self.assertIn(f"`{state}`", rendered, state)


class SourceGate(unittest.TestCase):
    def test_a_complete_source_gate_passes(self) -> None:
        result = evaluate_source_gate({name: True for name in SOURCE_GATE_REQUIREMENTS})
        self.assertEqual(result.recommendation, "PASS")

    def test_one_unmet_requirement_fails(self) -> None:
        requirements = {name: True for name in SOURCE_GATE_REQUIREMENTS}
        requirements["licenceGatePassed"] = False
        result = evaluate_source_gate(requirements)
        self.assertEqual(result.recommendation, "FAIL")

    def test_the_source_gate_implies_nothing_about_a_release(self) -> None:
        result = evaluate_source_gate({name: True for name in SOURCE_GATE_REQUIREMENTS})
        self.assertFalse(result.detail["impliesRelease"])
        self.assertFalse(result.detail["impliesPilot"])
        self.assertIn("Nothing about a built image", result.detail["meaning"])

    def test_an_unknown_requirement_is_rejected(self) -> None:
        with self.assertRaises(GateError):
            evaluate_source_gate({"vibes": True})

    def test_the_baseline_is_a_source_gate_requirement(self) -> None:
        self.assertIn("baselineRecorded", SOURCE_GATE_REQUIREMENTS)


class BaselineDocument(unittest.TestCase):
    def test_the_baseline_classifies_all_eight_categories(self) -> None:
        text = (ROOT / "docs/QUALIFICATION_EVIDENCE_BASELINE.md").read_text(encoding="utf-8").casefold()
        for name in (
            "automatable in repository",
            "requires ci infrastructure",
            "requires second independent machine",
            "requires physical hardware",
            "requires independent reviewer",
            "requires second authorised signer",
            "requires owner decision",
            "requires operated release evidence",
        ):
            self.assertIn(name, text, name)

    def test_the_baseline_does_not_describe_the_workflow_as_executed(self) -> None:
        text = (ROOT / "docs/QUALIFICATION_EVIDENCE_BASELINE.md").read_text(encoding="utf-8")
        self.assertIn("Not executed", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

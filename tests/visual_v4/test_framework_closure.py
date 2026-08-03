# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the V4 framework-closure harness.

The harness exists to stop a framework being selected on the strength of
unmeasured work, so most of these are mutation tests: each takes the real
contract, breaks one guard, and asserts the harness notices. A guard that no
test can break is a guard nobody has checked.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "visual-v4" / "tools"))

import v4  # noqa: E402


def contract() -> dict:
    return v4.load(v4.CONTRACT)


def results() -> dict:
    return v4.load(v4.RESULTS)


def set_state(doc: dict, arm: str, gate_id: str, state: str, evidence=None) -> dict:
    for row in doc["arms"][arm]["results"]:
        if row["id"] == gate_id:
            row["state"] = state
            row["evidence"] = evidence
    return doc


class ContractShapeTests(unittest.TestCase):
    def test_the_committed_contract_and_results_validate(self):
        v4.validate(contract(), results())

    def test_the_scorecard_totals_one_hundred(self):
        self.assertEqual(sum(contract()["scorecard"].values()), 100)

    def test_every_c7_mandatory_blocker_is_marked_mandatory(self):
        # C7 names seven blockers. Lock and unlock are separate gates here
        # because a lock that cannot be unlocked is not half a success.
        required = {
            "secure-session-lock",
            "pam-unlock",
            "input-method-v2",
            "screen-sharing-portal-pipewire",
            "orca-session",
            "gpu-rendering",
            "application-launch",
            "two-output-presentation",
        }
        mandatory = {g["id"] for g in contract()["gates"] if g["mandatory"]}
        self.assertEqual(mandatory, required)

    def test_pass_is_the_only_satisfying_state(self):
        self.assertEqual(v4.SATISFYING, "PASS")
        self.assertIn("PASS", contract()["resultStates"])


class NoUnmeasuredVerdictTests(unittest.TestCase):
    """The central property: nothing unmeasured may become a selection."""

    def test_verdict_is_withheld_as_committed(self):
        decision, reasons = v4.verdict(contract(), results())
        self.assertEqual(decision, "WITHHELD")
        self.assertTrue(reasons)

    def test_report_exits_non_zero_while_withheld(self):
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(ROOT / "visual-v4" / "tools" / "v4.py"), "report"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_not_run_does_not_satisfy_a_mandatory_gate(self):
        doc = set_state(results(), "smithay", "orca-session", "NOT_RUN")
        outstanding = dict(v4.unsatisfied_mandatory(contract(), doc, "smithay"))
        self.assertEqual(outstanding.get("orca-session"), "NOT_RUN")

    def test_not_available_does_not_satisfy_a_mandatory_gate(self):
        doc = set_state(results(), "smithay", "gpu-rendering", "NOT_AVAILABLE")
        outstanding = dict(v4.unsatisfied_mandatory(contract(), doc, "smithay"))
        self.assertEqual(outstanding.get("gpu-rendering"), "NOT_AVAILABLE")

    def test_partial_does_not_satisfy_a_mandatory_gate(self):
        doc = set_state(results(), "smithay", "pam-unlock", "PARTIAL", evidence="e.log")
        outstanding = dict(v4.unsatisfied_mandatory(contract(), doc, "smithay"))
        self.assertEqual(outstanding.get("pam-unlock"), "PARTIAL")

    def test_one_arm_passing_everything_mandatory_selects_it(self):
        doc = results()
        for gate in contract()["gates"]:
            if gate["mandatory"]:
                set_state(doc, "smithay", gate["id"], "PASS", evidence="measured.json")
        decision, _ = v4.verdict(contract(), doc)
        self.assertEqual(decision, "SELECT_SMITHAY")

    def test_both_arms_qualifying_does_not_force_a_winner(self):
        doc = results()
        for arm in ("smithay", "libmutter"):
            for gate in contract()["gates"]:
                if gate["mandatory"]:
                    set_state(doc, arm, gate["id"], "PASS", evidence="measured.json")
        decision, _ = v4.verdict(contract(), doc)
        self.assertEqual(decision, "CONTINUE_DUAL_TRACK")

    def test_a_high_score_never_overrides_one_failed_mandatory_gate(self):
        """C8's rule, as a test rather than a sentence."""
        doc = results()
        for gate in contract()["gates"]:
            set_state(doc, "smithay", gate["id"], "PASS", evidence="measured.json")
        # Everything passes: the arm is selectable and scores full marks.
        self.assertEqual(v4.verdict(contract(), doc)[0], "SELECT_SMITHAY")
        high, _ = v4.score(contract(), doc, "smithay")

        # Now break exactly one mandatory gate and nothing else.
        set_state(doc, "smithay", "orca-session", "FAIL", evidence="measured.json")
        decision, _ = v4.verdict(contract(), doc)
        self.assertEqual(decision, "WITHHELD")
        still_high, _ = v4.score(contract(), doc, "smithay")

        # The score barely moves — it loses one gate's share of one category —
        # while the verdict flips from selectable to withheld. That gap is
        # exactly why C8 says a number cannot override a mandatory gate.
        self.assertGreater(still_high, 0.85 * high)
        self.assertLess(still_high, high)


class ForgeryGuardTests(unittest.TestCase):
    """A PASS must point at something, and a matrix must be complete."""

    def test_pass_without_evidence_is_refused(self):
        doc = set_state(results(), "smithay", "xwayland", "PASS", evidence=None)
        with self.assertRaises(v4.ContractError) as caught:
            v4.validate(contract(), doc)
        self.assertIn("no evidence", str(caught.exception))

    def test_pass_with_evidence_is_accepted(self):
        doc = set_state(results(), "smithay", "xwayland", "PASS", evidence="reports/xwayland.json")
        v4.validate(contract(), doc)

    def test_duplicate_records_are_refused(self):
        doc = results()
        doc["arms"]["smithay"]["results"].append(
            copy.deepcopy(doc["arms"]["smithay"]["results"][0])
        )
        with self.assertRaises(v4.ContractError) as caught:
            v4.validate(contract(), doc)
        self.assertIn("duplicate", str(caught.exception))

    def test_a_missing_gate_is_refused_rather_than_assumed(self):
        doc = results()
        removed = doc["arms"]["smithay"]["results"].pop()
        with self.assertRaises(v4.ContractError) as caught:
            v4.validate(contract(), doc)
        self.assertIn(removed["id"], str(caught.exception))

    def test_an_unknown_state_is_refused(self):
        doc = set_state(results(), "smithay", "xwayland", "PROBABLY_FINE")
        with self.assertRaises(v4.ContractError):
            v4.validate(contract(), doc)

    def test_a_dropped_arm_is_refused(self):
        doc = results()
        del doc["arms"]["libmutter"]
        with self.assertRaises(v4.ContractError) as caught:
            v4.validate(contract(), doc)
        self.assertIn("libmutter", str(caught.exception))

    def test_a_gate_outside_the_contract_is_refused(self):
        doc = results()
        doc["arms"]["smithay"]["results"].append(
            {"id": "invented-gate", "state": "PASS", "evidence": "x", "reason": ""}
        )
        with self.assertRaises(v4.ContractError):
            v4.validate(contract(), doc)


class ScoreTests(unittest.TestCase):
    def test_nothing_measured_scores_zero(self):
        for arm in contract()["arms"]:
            total, _ = v4.score(contract(), results(), arm)
            self.assertEqual(total, 0.0)

    def test_only_pass_contributes(self):
        doc = results()
        for gate in contract()["gates"]:
            if gate["group"] == "accessibility":
                set_state(doc, "smithay", gate["id"], "PARTIAL", evidence="e")
        total, _ = v4.score(contract(), doc, "smithay")
        self.assertEqual(total, 0.0, "PARTIAL must not earn points")

    def test_a_fully_passing_arm_scores_its_mapped_weight(self):
        doc = results()
        for gate in contract()["gates"]:
            set_state(doc, "smithay", gate["id"], "PASS", evidence="e")
        total, breakdown = v4.score(contract(), doc, "smithay")
        self.assertEqual(breakdown["accessibility"], 18)
        self.assertEqual(breakdown["input-methods"], 12)
        # Unmapped categories stay zero rather than being redistributed.
        self.assertEqual(breakdown["maintenance-burden"], 0.0)
        self.assertLess(total, 100)


class EnvironmentHonestyTests(unittest.TestCase):
    def test_environment_blocked_gates_are_marked_not_available_for_both_arms(self):
        doc = results()
        blocked = {
            "gpu-rendering",
            "linux-dmabuf",
            "frame-pacing",
            "two-output-presentation",
            "output-hotplug",
        }
        for arm in doc["arms"]:
            by_id = {r["id"]: r for r in doc["arms"][arm]["results"]}
            for gate_id in blocked:
                self.assertEqual(by_id[gate_id]["state"], "NOT_AVAILABLE", gate_id)
                self.assertTrue(by_id[gate_id]["reason"], f"{gate_id} needs a stated reason")

    def test_no_gate_claims_pass_anywhere(self):
        doc = results()
        for arm in doc["arms"]:
            for row in doc["arms"][arm]["results"]:
                self.assertNotEqual(
                    row["state"], "PASS", f"{arm}/{row['id']} claims PASS with nothing measured"
                )

    def test_every_non_pass_row_explains_itself(self):
        doc = results()
        for arm in doc["arms"]:
            for row in doc["arms"][arm]["results"]:
                self.assertTrue(row["reason"].strip(), f"{arm}/{row['id']} has no reason")


if __name__ == "__main__":
    unittest.main()

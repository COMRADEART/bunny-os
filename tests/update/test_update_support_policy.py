# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the unsupported-update policy admission path.

Every refusal in ``release.updatepolicy`` is exercised here against a record
constructed to trip it. A refusal that has never rejected anything is not a
control, and this module's whole purpose is to be the thing standing between a
document that says "updates are unsupported" and a release decision that relies
on it.

The committed policy is checked too, because a validator nothing validates is
the same problem one level up.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release import updatepolicy

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "operations" / "data" / "update-support-policy.json"

GOOD_DIGEST = "sha256:" + "c" * 64
LONG_ANSWER = "x" * (updatepolicy.MINIMUM_ANSWER_CHARACTERS + 10)


def as_intended_run(checks=18, **overrides):
    document = {
        "result": "AS_INTENDED",
        "checks": checks,
        "missingChecks": [],
        "duplicateChecks": [],
        "unexpectedChecks": [],
    }
    document.update(overrides)
    return document


def failing_control():
    return {
        "result": "UNEXPECTED",
        "checks": 18,
        "missingChecks": [],
        "duplicateChecks": [],
        "unexpectedChecks": ["A1"],
    }


class PolicyFixture:
    """A minimal admissible policy, plus the files it points at."""

    def __init__(self, stack):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "ev").mkdir()
        self.run_path = self.root / "ev" / "run.json"
        self.control_path = self.root / "ev" / "control.json"
        self.write_run(as_intended_run())
        self.write_control(failing_control())

    def write_run(self, document):
        self.run_path.write_text(json.dumps(document), encoding="utf-8")

    def write_control(self, document):
        self.control_path.write_text(json.dumps(document), encoding="utf-8")

    def policy(self, **overrides):
        document = {
            "schemaVersion": 1,
            "releaseClass": "alpha",
            "decision": "UNSUPPORTED",
            "approver": {"name": "A Real Person", "accountableFor": "the decision"},
            "boundTo": {"imageManifestDigest": GOOD_DIGEST},
            "questions": {name: LONG_ANSWER for name in updatepolicy.REQUIRED_QUESTIONS},
            "waivedScenarios": [],
            "reviewCondition": "void on a production key being created",
            "expires": "2027-02-18",
            "refusalQualification": {
                "evidence": "ev/run.json",
                "negativeControl": "ev/control.json",
                "requiredChecks": 18,
            },
        }
        document.update(overrides)
        return document

    def evaluate(self, **overrides):
        return updatepolicy.evaluate_policy(self.policy(**overrides), root=self.root)


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.fixture = PolicyFixture(self.stack)

    def assertRefusedBecause(self, verdict, fragment):
        self.assertFalse(verdict.admissible, "the policy was admitted when it should not be")
        joined = " | ".join(verdict.reasons)
        self.assertIn(fragment, joined)

    # -- the positive case, so every refusal below means something ----------

    def test_a_complete_policy_is_admissible(self) -> None:
        verdict = self.fixture.evaluate()
        self.assertTrue(verdict.admissible, verdict.reasons)
        self.assertTrue(verdict.refusalQualified)

    # -- accountability -----------------------------------------------------

    def test_a_role_is_not_an_approver(self) -> None:
        verdict = self.fixture.evaluate(
            approver={"name": "Security", "accountableFor": "the decision"}
        )
        self.assertRefusedBecause(verdict, "accountable approver")

    def test_a_placeholder_is_not_an_approver(self) -> None:
        verdict = self.fixture.evaluate(
            approver={"name": "TBD", "accountableFor": "the decision"}
        )
        self.assertRefusedBecause(verdict, "accountable approver")

    def test_an_approver_accountable_for_nothing_is_refused(self) -> None:
        verdict = self.fixture.evaluate(approver={"name": "A Real Person"})
        self.assertRefusedBecause(verdict, "accountable for anything specific")

    # -- artifact binding ---------------------------------------------------

    def test_a_policy_bound_to_no_digest_is_refused(self) -> None:
        verdict = self.fixture.evaluate(boundTo={})
        self.assertRefusedBecause(verdict, "sha256 image manifest digest")

    def test_a_policy_bound_to_a_branch_is_refused(self) -> None:
        verdict = self.fixture.evaluate(boundTo={"imageManifestDigest": "main"})
        self.assertRefusedBecause(verdict, "sha256 image manifest digest")

    def test_a_truncated_digest_is_refused(self) -> None:
        verdict = self.fixture.evaluate(boundTo={"imageManifestDigest": "sha256:c87a6616"})
        self.assertRefusedBecause(verdict, "sha256 image manifest digest")

    # -- the seven questions ------------------------------------------------

    def test_every_missing_question_is_named(self) -> None:
        for name in updatepolicy.REQUIRED_QUESTIONS:
            answers = {other: LONG_ANSWER for other in updatepolicy.REQUIRED_QUESTIONS}
            del answers[name]
            verdict = self.fixture.evaluate(questions=answers)
            self.assertRefusedBecause(verdict, f"question {name} is unanswered")

    def test_a_one_word_answer_is_refused(self) -> None:
        answers = {name: LONG_ANSWER for name in updatepolicy.REQUIRED_QUESTIONS}
        answers["whatRootOfTrustIsPresent"] = "none"
        verdict = self.fixture.evaluate(questions=answers)
        self.assertRefusedBecause(verdict, "answered too briefly to be checkable")

    def test_an_unrecognised_question_is_refused(self) -> None:
        answers = {name: LONG_ANSWER for name in updatepolicy.REQUIRED_QUESTIONS}
        answers["whatAboutThis"] = LONG_ANSWER
        verdict = self.fixture.evaluate(questions=answers)
        self.assertRefusedBecause(verdict, "unknown fields")

    # -- expiry -------------------------------------------------------------

    def test_a_policy_that_cannot_expire_is_refused(self) -> None:
        verdict = self.fixture.evaluate(reviewCondition="")
        self.assertRefusedBecause(verdict, "permanent by inattention")

    def test_a_policy_with_no_expiry_date_is_refused(self) -> None:
        verdict = self.fixture.evaluate(expires="")
        self.assertRefusedBecause(verdict, "no expiry date")

    # -- waivers ------------------------------------------------------------

    def test_an_implied_empty_waiver_list_is_refused(self) -> None:
        """An absent list and a stated empty list are different claims."""
        policy = self.fixture.policy()
        del policy["waivedScenarios"]
        verdict = updatepolicy.evaluate_policy(policy, root=self.fixture.root)
        self.assertRefusedBecause(verdict, "must be stated, not implied")

    def test_a_waiver_with_no_reason_is_refused(self) -> None:
        verdict = self.fixture.evaluate(
            waivedScenarios=[{"scenario": "interrupted-download"}]
        )
        self.assertRefusedBecause(verdict, "a blanket waiver is refused")

    # -- the refusal qualification, which is the point ----------------------

    def test_a_policy_with_no_refusal_qualification_is_refused(self) -> None:
        policy = self.fixture.policy()
        del policy["refusalQualification"]
        verdict = updatepolicy.evaluate_policy(policy, root=self.fixture.root)
        self.assertRefusedBecause(verdict, "asserted, not measured")

    def test_a_missing_evidence_file_is_refused(self) -> None:
        verdict = self.fixture.evaluate(refusalQualification={
            "evidence": "ev/absent.json",
            "negativeControl": "ev/control.json",
        })
        self.assertRefusedBecause(verdict, "does not exist")

    def test_evidence_outside_the_repository_is_refused(self) -> None:
        verdict = self.fixture.evaluate(refusalQualification={
            "evidence": "../../etc/passwd",
            "negativeControl": "ev/control.json",
        })
        self.assertRefusedBecause(verdict, "escapes the repository")

    def test_an_incomplete_run_is_refused(self) -> None:
        self.fixture.write_run(
            as_intended_run(result="INCOMPLETE", missingChecks=["B3"])
        )
        verdict = self.fixture.evaluate()
        self.assertRefusedBecause(verdict, "missing required checks: B3")

    def test_a_run_with_an_unexpected_check_is_refused(self) -> None:
        self.fixture.write_run(
            as_intended_run(result="UNEXPECTED", unexpectedChecks=["A1"])
        )
        verdict = self.fixture.evaluate()
        self.assertRefusedBecause(verdict, "is UNEXPECTED, not AS_INTENDED")

    def test_a_run_with_fewer_checks_than_declared_is_refused(self) -> None:
        """A probe narrowed after the policy was written must not pass on it."""
        self.fixture.write_run(as_intended_run(checks=12))
        verdict = self.fixture.evaluate()
        self.assertRefusedBecause(verdict, "declares 18 required checks")

    def test_a_negative_control_that_passed_is_refused(self) -> None:
        """The single most important refusal in the module."""
        self.fixture.write_control(as_intended_run())
        verdict = self.fixture.evaluate()
        self.assertRefusedBecause(verdict, "a control that cannot fail is not a control")

    def test_a_policy_with_no_negative_control_is_refused(self) -> None:
        verdict = self.fixture.evaluate(refusalQualification={"evidence": "ev/run.json"})
        self.assertRefusedBecause(verdict, "names no negative control")

    def test_a_supported_decision_does_not_need_a_refusal_qualification(self) -> None:
        """Only an UNSUPPORTED policy rests on the system refusing."""
        self.fixture.write_control(as_intended_run())
        verdict = self.fixture.evaluate(decision="SUPPORTED")
        self.assertTrue(verdict.admissible, verdict.reasons)
        self.assertFalse(verdict.refusalQualified)

    # -- schema -------------------------------------------------------------

    def test_a_wrong_schema_version_raises(self) -> None:
        with self.assertRaises(updatepolicy.UpdatePolicyError):
            updatepolicy.evaluate_policy(
                self.fixture.policy(schemaVersion=2), root=self.fixture.root
            )

    def test_an_unknown_decision_raises(self) -> None:
        with self.assertRaises(updatepolicy.UpdatePolicyError):
            updatepolicy.evaluate_policy(
                self.fixture.policy(decision="PROBABLY_FINE"), root=self.fixture.root
            )


class CommittedPolicyTests(unittest.TestCase):
    """The policy this repository actually ships."""

    def setUp(self) -> None:
        self.verdict = updatepolicy.load_and_evaluate(POLICY_PATH, root=ROOT)

    def test_the_committed_policy_is_admissible(self) -> None:
        self.assertTrue(self.verdict.admissible, self.verdict.reasons)

    def test_it_declares_updates_unsupported_for_the_alpha_class(self) -> None:
        self.assertEqual(self.verdict.decision, "UNSUPPORTED")
        self.assertEqual(self.verdict.releaseClass, "alpha")

    def test_it_binds_to_the_phase_six_subject_artifact(self) -> None:
        self.assertEqual(
            self.verdict.boundToDigest,
            "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d",
        )

    def test_its_refusal_is_qualified_by_a_run_with_a_failing_control(self) -> None:
        self.assertTrue(self.verdict.refusalQualified)
        detail = self.verdict.detail["refusalQualification"]
        self.assertEqual(detail["evidence"]["result"], "AS_INTENDED")
        self.assertEqual(detail["negativeControl"]["result"], "UNEXPECTED")

    def test_it_waives_no_matrix_scenario(self) -> None:
        """The policy must not be a route to a complete matrix."""
        document = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(document["waivedScenarios"], [])


if __name__ == "__main__":
    unittest.main()

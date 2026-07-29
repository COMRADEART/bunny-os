from __future__ import annotations

import unittest

from operations.qualification import REQUIRED_APPROVALS, REQUIRED_AUTOMATED, evaluate_release


class QualificationTests(unittest.TestCase):
    def test_unknown_evidence_is_no_go(self) -> None:
        result = evaluate_release({}, {}, [])
        self.assertEqual(result.recommendation, "NO-GO")

    def test_one_blocker_is_no_go(self) -> None:
        evidence = {key: "PASS" for key in REQUIRED_AUTOMATED}
        approvals = {key: "APPROVED" for key in REQUIRED_APPROVALS}
        self.assertFalse(evaluate_release(evidence, approvals, ["wrong-disk"]).passed)

    def test_all_evidence_and_approvals_can_go(self) -> None:
        evidence = {key: "PASS" for key in REQUIRED_AUTOMATED}
        approvals = {key: "APPROVED" for key in REQUIRED_APPROVALS}
        self.assertTrue(evaluate_release(evidence, approvals, []).passed)

    def test_accessibility_is_mandatory(self) -> None:
        evidence = {key: "PASS" for key in REQUIRED_AUTOMATED}
        evidence["accessibility"] = "NOT_RUN"
        approvals = {key: "APPROVED" for key in REQUIRED_APPROVALS}
        self.assertIn("accessibility", evaluate_release(evidence, approvals, []).missing)

    def test_unknown_blocker_code_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_release({}, {}, ["ignore-this-defect"])


if __name__ == "__main__":
    unittest.main()

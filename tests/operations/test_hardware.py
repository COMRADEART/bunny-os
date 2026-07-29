from __future__ import annotations

import unittest

from operations.hardware import RECOMMENDED_EVIDENCE, classify_hardware


class HardwareTests(unittest.TestCase):
    def test_no_execution_is_untested(self) -> None:
        self.assertEqual(classify_hardware({"executions": [], "explicitlyUnsupported": False}), "Untested")

    def test_unsupported_is_explicit(self) -> None:
        self.assertEqual(classify_hardware({"explicitlyUnsupported": True}), "Unsupported")

    def test_detection_alone_is_not_support(self) -> None:
        self.assertEqual(classify_hardware({"executions": ["lspci"], "evidence": {}, "openIssueSeverities": []}), "Experimental")

    def test_complete_evidence_can_be_recommended(self) -> None:
        report = {"executions": ["physical-run-1"], "evidence": {key: True for key in RECOMMENDED_EVIDENCE}, "openIssueSeverities": [], "explicitlyUnsupported": False}
        self.assertEqual(classify_hardware(report), "Stable recommended")

    def test_high_issue_prevents_recommended(self) -> None:
        report = {"executions": ["run"], "evidence": {key: True for key in RECOMMENDED_EVIDENCE}, "openIssueSeverities": ["High"], "explicitlyUnsupported": False}
        self.assertNotEqual(classify_hardware(report), "Stable recommended")

    def test_expected_unqualified_hardware_is_best_effort(self) -> None:
        report = {"executions": ["run"], "evidence": {}, "openIssueSeverities": [], "expectedToWork": True, "explicitlyUnsupported": False}
        self.assertEqual(classify_hardware(report), "Best effort")


if __name__ == "__main__":
    unittest.main()

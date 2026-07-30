"""Accessibility evidence: static tests are not sufficient.

The brief says so directly, and this is the gap where the cost of being wrong is
borne by a user rather than by the project: an inaccessible encryption prompt or
recovery tool locks someone out of their own machine.

``release/matrix.py`` therefore refuses a source-inspection pass in the
accessibility matrix, exactly as it does for recovery media.

Directory naming note: the brief names this suite
``tests/accessibility-evidence/``. A hyphen cannot be imported as a Python
package, so the underscore spelling keeps the tests running.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from release.matrix import (
    MATRICES,
    RUNTIME_ONLY_MATRICES,
    MatrixError,
    evaluate_matrix,
    parse_result,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = MATRICES["accessibility"]


def result(scenario, **overrides):
    base = {
        "scenario": scenario,
        "outcome": "PASS",
        "method": "manual-procedure",
        "evidenceReference": "evidence/build/beta-inspect.log",
        "recordedAt": "2026-07-29T00:00:00Z",
    }
    base.update(overrides)
    return base


class WorkflowCoverageTests(unittest.TestCase):
    def test_the_fourteen_essential_workflows(self):
        for name in (
            "installer-keyboard-navigation",
            "installer-screen-reader",
            "encryption-prompt",
            "first-run",
            "login",
            "bunny-launcher",
            "bunny-approvals",
            "update-ui",
            "rollback-ui",
            "recovery-ui",
            "diagnostics-export",
            "high-contrast",
            "text-scaling",
            "reduced-motion",
        ):
            self.assertIn(name, WORKFLOWS)
        self.assertEqual(len(WORKFLOWS), 14)

    def test_accessibility_is_a_runtime_only_matrix(self):
        self.assertIn("accessibility", RUNTIME_ONLY_MATRICES)


class StaticEvidenceTests(unittest.TestCase):
    def test_source_inspection_cannot_pass_any_workflow(self):
        for scenario in WORKFLOWS:
            with self.assertRaises(MatrixError) as caught:
                parse_result("accessibility", result(scenario, method="source-inspection"), root=ROOT)
            self.assertIn("must be observed at runtime", str(caught.exception))

    def test_unit_test_evidence_is_permitted_but_is_not_source_inspection(self):
        """A unit test runs code; it is weaker than a driven session but is not static."""
        parsed = parse_result("accessibility", result("high-contrast", method="unit-test"), root=ROOT)
        self.assertEqual(parsed.outcome, "PASS")

    def test_manual_procedure_is_the_expected_method_for_screen_reader_workflows(self):
        parsed = parse_result("accessibility", result("installer-screen-reader"), root=ROOT)
        self.assertEqual(parsed.method, "manual-procedure")

    def test_a_pass_must_cite_an_artifact_that_exists(self):
        with self.assertRaises(MatrixError):
            parse_result(
                "accessibility",
                result("first-run", evidenceReference="evidence/never-captured.log"),
                root=ROOT,
            )


class CompletenessTests(unittest.TestCase):
    def test_missing_workflow_blocks_the_matrix(self):
        verdict = evaluate_matrix("accessibility", [result(WORKFLOWS[0])], root=ROOT)
        self.assertFalse(verdict.complete)
        self.assertEqual(len(verdict.missing), len(WORKFLOWS) - 1)

    def test_full_matrix_completes(self):
        verdict = evaluate_matrix("accessibility", [result(name) for name in WORKFLOWS], root=ROOT)
        self.assertTrue(verdict.complete, verdict.missing + verdict.failing)

    def test_a_failed_workflow_blocks(self):
        rows = [result(name) for name in WORKFLOWS]
        rows[2]["outcome"] = "FAIL"
        verdict = evaluate_matrix("accessibility", rows, root=ROOT)
        self.assertFalse(verdict.complete)
        self.assertIn("encryption-prompt", verdict.failing)

    def test_essential_workflows_cannot_be_dismissed_without_a_reason(self):
        with self.assertRaises(MatrixError):
            parse_result(
                "accessibility",
                result("encryption-prompt", outcome="NOT_APPLICABLE", evidenceReference=None),
            )


class RecordedAccessibilityStateTests(unittest.TestCase):
    def test_recorded_accessibility_matrix_has_no_static_pass(self):
        path = ROOT / "operations/data/qualification-matrices.json"
        if not path.is_file():
            self.skipTest("no qualification matrix record yet")
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = document.get("matrices", {}).get("accessibility", [])
        for row in rows:
            if row.get("outcome") == "PASS":
                self.assertNotEqual(
                    row.get("method"),
                    "source-inspection",
                    f"{row.get('scenario')} claims a pass from source inspection",
                )

    def test_accessibility_is_not_yet_qualified(self):
        """Honesty check: no accessibility workflow has been driven at runtime."""
        path = ROOT / "operations/data/qualification-matrices.json"
        if not path.is_file():
            self.skipTest("no qualification matrix record yet")
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = document.get("matrices", {}).get("accessibility", [])
        verdict = evaluate_matrix("accessibility", rows, root=ROOT)
        self.assertFalse(
            verdict.complete,
            "accessibility is now complete; update ACCESSIBILITY_QUALIFICATION_REPORT.md and this test",
        )


if __name__ == "__main__":
    unittest.main()

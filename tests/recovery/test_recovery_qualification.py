"""Recovery media qualification.

One of the fourteen mandated adversarial cases lives here: a recovery report
without boot evidence. The brief is explicit that no recovery-media claim may
rest on source inspection, so ``release/matrix.py`` refuses a source-inspection
pass in this matrix and these tests hold it to that.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from release.matrix import (
    MATRICES,
    METHODS,
    RUNTIME_ONLY_MATRICES,
    MatrixError,
    evaluate_matrix,
    parse_result,
)

ROOT = Path(__file__).resolve().parents[2]

RECOVERY_SCENARIOS = MATRICES["recovery-media"]


def result(scenario, **overrides):
    base = {
        "scenario": scenario,
        "outcome": "PASS",
        "method": "virtual-machine",
        "evidenceReference": "evidence/build/beta-inspect.log",
        "recordedAt": "2026-07-29T00:00:00Z",
    }
    base.update(overrides)
    return base


class RecoveryMatrixShapeTests(unittest.TestCase):
    def test_the_eleven_recovery_capabilities(self):
        for name in (
            "boots-independently",
            "verifies-own-signature",
            "encrypted-access-requires-credentials",
            "mounts-user-data-read-only-by-default",
            "inspects-deployments",
            "selects-previous-deployment",
            "repairs-boot-entries",
            "disables-bunny",
            "disables-plugins",
            "enters-safe-graphics",
            "exports-redacted-diagnostics",
        ):
            self.assertIn(name, RECOVERY_SCENARIOS)

    def test_recovery_is_a_runtime_only_matrix(self):
        self.assertIn("recovery-media", RUNTIME_ONLY_MATRICES)

    def test_unknown_scenario_is_refused(self):
        with self.assertRaises(MatrixError):
            parse_result("recovery-media", result("makes-tea"))


class SourceInspectionTests(unittest.TestCase):
    """Adversarial: a recovery report without boot evidence."""

    def test_source_inspection_cannot_pass_a_recovery_scenario(self):
        for scenario in RECOVERY_SCENARIOS:
            with self.assertRaises(MatrixError) as caught:
                parse_result(
                    "recovery-media",
                    result(scenario, method="source-inspection"),
                    root=ROOT,
                )
            self.assertIn("must be observed at runtime", str(caught.exception))

    def test_source_inspection_may_record_a_failure(self):
        parsed = parse_result(
            "recovery-media",
            result("boots-independently", outcome="FAIL", method="source-inspection"),
            root=ROOT,
        )
        self.assertEqual(parsed.outcome, "FAIL")

    def test_a_pass_must_reference_evidence(self):
        with self.assertRaises(MatrixError) as caught:
            parse_result("recovery-media", result("boots-independently", evidenceReference=None))
        self.assertIn("must reference the evidence", str(caught.exception))

    def test_a_pass_referencing_a_missing_artifact_is_refused(self):
        with self.assertRaises(MatrixError) as caught:
            parse_result(
                "recovery-media",
                result("boots-independently", evidenceReference="evidence/nope.log"),
                root=ROOT,
            )
        self.assertIn("does not exist", str(caught.exception))

    def test_a_virtual_machine_pass_with_real_evidence_is_accepted(self):
        parsed = parse_result("recovery-media", result("boots-independently"), root=ROOT)
        self.assertEqual(parsed.outcome, "PASS")
        self.assertEqual(parsed.method, "virtual-machine")

    def test_evidence_path_escaping_the_repository_is_refused(self):
        with self.assertRaises(MatrixError) as caught:
            parse_result(
                "recovery-media",
                result("boots-independently", evidenceReference="../../../etc/passwd"),
                root=ROOT,
            )
        self.assertIn("escapes the repository", str(caught.exception))


class RecoveryCompletenessTests(unittest.TestCase):
    def test_partial_matrix_is_incomplete(self):
        verdict = evaluate_matrix(
            "recovery-media",
            [result(RECOVERY_SCENARIOS[0])],
            root=ROOT,
        )
        self.assertFalse(verdict.complete)
        self.assertIn(RECOVERY_SCENARIOS[1], verdict.missing)

    def test_full_matrix_is_complete(self):
        verdict = evaluate_matrix(
            "recovery-media",
            [result(name) for name in RECOVERY_SCENARIOS],
            root=ROOT,
        )
        self.assertTrue(verdict.complete, verdict.missing + verdict.failing)

    def test_one_failure_blocks_the_matrix(self):
        rows = [result(name) for name in RECOVERY_SCENARIOS]
        rows[3]["outcome"] = "FAIL"
        verdict = evaluate_matrix("recovery-media", rows, root=ROOT)
        self.assertFalse(verdict.complete)
        self.assertIn(RECOVERY_SCENARIOS[3], verdict.failing)

    def test_not_applicable_requires_a_reason(self):
        with self.assertRaises(MatrixError) as caught:
            parse_result(
                "recovery-media",
                result("enters-safe-graphics", outcome="NOT_APPLICABLE", evidenceReference=None),
            )
        self.assertIn("requires a reason", str(caught.exception))

    def test_not_applicable_with_a_reason_resolves_the_scenario(self):
        rows = [result(name) for name in RECOVERY_SCENARIOS]
        rows[-1] = result(
            RECOVERY_SCENARIOS[-1],
            outcome="NOT_APPLICABLE",
            evidenceReference=None,
            reason="the recovery profile ships no graphical session",
        )
        verdict = evaluate_matrix("recovery-media", rows, root=ROOT)
        self.assertTrue(verdict.complete)

    def test_duplicate_scenarios_are_refused(self):
        with self.assertRaises(MatrixError):
            evaluate_matrix(
                "recovery-media",
                [result("boots-independently"), result("boots-independently")],
                root=ROOT,
            )

    def test_method_counts_are_reported(self):
        rows = [result(name) for name in RECOVERY_SCENARIOS]
        rows[0]["method"] = "physical-hardware"
        verdict = evaluate_matrix("recovery-media", rows, root=ROOT)
        payload = verdict.as_dict()
        self.assertEqual(payload["methodCounts"]["physical-hardware"], 1)
        self.assertEqual(payload["methodCounts"]["virtual-machine"], len(RECOVERY_SCENARIOS) - 1)


class RecordedRecoveryStateTests(unittest.TestCase):
    def test_recorded_recovery_matrix_parses_and_is_honest(self):
        path = ROOT / "operations/data/qualification-matrices.json"
        if not path.is_file():
            self.skipTest("no qualification matrix record yet")
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = document.get("matrices", {}).get("recovery-media", [])
        verdict = evaluate_matrix("recovery-media", rows, root=ROOT)
        for row in verdict.results:
            if row.outcome == "PASS":
                self.assertNotEqual(
                    row.method,
                    "source-inspection",
                    f"{row.scenario} claims a pass from source inspection",
                )


class MethodVocabularyTests(unittest.TestCase):
    def test_methods_are_ordered_weakest_first(self):
        self.assertEqual(METHODS[0], "source-inspection")
        self.assertIn("physical-hardware", METHODS)

    def test_unknown_method_is_refused(self):
        with self.assertRaises(MatrixError):
            parse_result("recovery-media", result("boots-independently", method="vibes"))


if __name__ == "__main__":
    unittest.main()

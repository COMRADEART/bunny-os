from __future__ import annotations

import json
from pathlib import Path
import unittest

from operations.devqualification import (
    ENVIRONMENTS,
    KEY_CLASSES,
    PRODUCTION_REQUIREMENTS,
    DevQualificationError,
    evaluate_development,
    production_gap_analysis,
)
from operations.qualification import REQUIRED_APPROVALS, REQUIRED_AUTOMATED, evaluate_release

ROOT = Path(__file__).resolve().parents[2]


def row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "PASS",
        "environment": "virtual",
        "keyClass": "development",
        "method": "QEMU/KVM boot with serial marker capture",
        "command": "bash build/scripts/vm-smoke.sh developer",
        "recordedAt": "2026-07-29T20:00:00Z",
    }
    value.update(overrides)
    return value


def complete_evidence(**overrides: object) -> dict[str, object]:
    evidence = {name: row() for name in REQUIRED_AUTOMATED}
    evidence.update(overrides)
    return evidence


class DevelopmentGateTests(unittest.TestCase):
    def test_complete_virtual_evidence_reaches_go(self) -> None:
        decision = evaluate_development(complete_evidence(), root=ROOT)
        self.assertEqual(decision.recommendation, "GO")
        self.assertTrue(decision.passed)

    def test_a_development_go_is_never_a_production_approval(self) -> None:
        decision = evaluate_development(complete_evidence(), root=ROOT)
        payload = decision.as_dict()
        self.assertFalse(payload["isProductionApproval"])
        self.assertEqual(payload["track"], "development")
        self.assertIn("not a stable release approval", payload["note"])

    def test_missing_row_blocks(self) -> None:
        evidence = complete_evidence()
        del evidence["recovery"]
        decision = evaluate_development(evidence, root=ROOT)
        self.assertFalse(decision.passed)
        self.assertIn("recovery", decision.missing)

    def test_not_run_row_blocks(self) -> None:
        decision = evaluate_development(complete_evidence(installer=row(status="NOT_RUN")), root=ROOT)
        self.assertFalse(decision.passed)
        self.assertIn("installer", decision.missing)

    def test_failing_row_blocks(self) -> None:
        decision = evaluate_development(complete_evidence(security=row(status="FAIL")), root=ROOT)
        self.assertFalse(decision.passed)
        self.assertIn("security", decision.failing)

    def test_every_row_blocks_independently(self) -> None:
        for name in REQUIRED_AUTOMATED:
            with self.subTest(evidence=name):
                decision = evaluate_development(
                    complete_evidence(**{name: row(status="BLOCKED")}), root=ROOT
                )
                self.assertFalse(decision.passed)

    def test_unknown_row_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(invented_row=row()), root=ROOT)

    def test_row_without_provenance_is_refused(self) -> None:
        incomplete = dict(row())
        del incomplete["method"]
        with self.assertRaises(DevQualificationError) as error:
            evaluate_development(complete_evidence(hardware=incomplete), root=ROOT)
        self.assertIn("missing evidence fields", str(error.exception))

    def test_row_with_an_extra_field_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(hardware=row(waived=True)), root=ROOT)

    def test_blank_method_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(sbom=row(method="   ")), root=ROOT)

    def test_malformed_timestamp_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(sbom=row(recordedAt="yesterday")), root=ROOT)

    def test_invalid_environment_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(sbom=row(environment="imaginary")), root=ROOT)

    def test_invalid_key_class_is_refused(self) -> None:
        with self.assertRaises(DevQualificationError):
            evaluate_development(complete_evidence(sbom=row(keyClass="borrowed")), root=ROOT)


class OverclaimTests(unittest.TestCase):
    """The provenance rules are the point: a stronger claim needs stronger evidence."""

    def test_claiming_physical_hardware_without_a_report_is_refused(self) -> None:
        decision = evaluate_development(
            complete_evidence(hardware=row(environment="physical")), root=ROOT
        )
        self.assertFalse(decision.passed)
        self.assertTrue(any("claims physical hardware" in item for item in decision.overclaimed))

    def test_claiming_physical_with_an_unknown_report_id_is_refused(self) -> None:
        payload = row(environment="physical")
        payload["hardwareReportId"] = "HW-9999"
        decision = evaluate_development(complete_evidence(hardware=payload), root=ROOT)
        self.assertFalse(decision.passed)

    def test_claiming_a_production_key_without_a_ceremony_is_refused(self) -> None:
        decision = evaluate_development(
            complete_evidence(signature_verification=row(keyClass="production")), root=ROOT
        )
        self.assertFalse(decision.passed)
        self.assertTrue(any("production key" in item for item in decision.overclaimed))

    def test_claiming_a_production_key_with_a_fabricated_ceremony_is_refused(self) -> None:
        payload = row(keyClass="production")
        payload["keyCeremonyRef"] = "CEREMONY-001"
        decision = evaluate_development(
            complete_evidence(signature_verification=payload), root=ROOT
        )
        self.assertFalse(decision.passed)

    def test_hardware_evidence_file_is_still_empty(self) -> None:
        # If this ever fails, real hardware reports were added and the physical
        # overclaim tests above need revisiting rather than deleting.
        document = json.loads(
            (ROOT / "operations/data/hardware-evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["reports"], [])

    def test_virtual_and_development_rows_are_reported(self) -> None:
        decision = evaluate_development(complete_evidence(), root=ROOT)
        self.assertEqual(len(decision.virtualRows), len(REQUIRED_AUTOMATED))
        self.assertEqual(len(decision.developmentKeyRows), len(REQUIRED_AUTOMATED))


class ProductionSeparationTests(unittest.TestCase):
    def test_the_production_evaluator_is_untouched_and_still_no_go(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/stable-qualification.json").read_text(encoding="utf-8")
        )
        decision = evaluate_release(
            document["evidence"], document["approvals"], document["blockers"]
        )
        self.assertEqual(decision.recommendation, "NO-GO")

    def test_development_evidence_cannot_be_fed_to_the_production_gate(self) -> None:
        # The production evaluator expects bare status strings, not provenance
        # objects, so a development record cannot be substituted for one. It
        # raises rather than returning anything, which is fail-closed: a crash
        # is never a GO. The exception type is incidental, the refusal is not.
        with self.assertRaises((TypeError, ValueError)):
            evaluate_release(complete_evidence(), {}, [])

    def test_gap_analysis_covers_every_row(self) -> None:
        analysis = production_gap_analysis(complete_evidence())
        self.assertEqual(len(analysis["rows"]), len(REQUIRED_AUTOMATED))
        self.assertEqual(
            {item["evidence"] for item in analysis["rows"]}, set(REQUIRED_AUTOMATED)
        )

    def test_gap_analysis_lists_the_outstanding_human_approvals(self) -> None:
        analysis = production_gap_analysis(complete_evidence())
        self.assertEqual(analysis["productionApprovalsOutstanding"], list(REQUIRED_APPROVALS))
        self.assertEqual(analysis["summary"]["humanApprovalsOutstanding"], 9)

    def test_most_rows_still_require_more_for_production(self) -> None:
        analysis = production_gap_analysis(complete_evidence())
        self.assertGreater(analysis["summary"]["rowsRequiringMoreForProduction"], 15)

    def test_every_row_has_a_stated_production_requirement(self) -> None:
        self.assertEqual(set(PRODUCTION_REQUIREMENTS), set(REQUIRED_AUTOMATED))
        for name, requirement in PRODUCTION_REQUIREMENTS.items():
            with self.subTest(evidence=name):
                self.assertTrue(requirement.strip())


class RecordedEvidenceTests(unittest.TestCase):
    def record(self) -> dict[str, object]:
        return json.loads(
            (ROOT / "operations/data/dev-qualification.json").read_text(encoding="utf-8")
        )

    def test_recorded_evidence_is_structurally_valid(self) -> None:
        # Raises if any recorded row is malformed or overclaims.
        evaluate_development(self.record()["evidence"], root=ROOT)

    def test_recorded_evidence_never_claims_physical_hardware(self) -> None:
        for name, entry in self.record()["evidence"].items():
            with self.subTest(evidence=name):
                self.assertNotEqual(entry["environment"], "physical")

    def test_recorded_evidence_never_claims_a_production_key(self) -> None:
        for name, entry in self.record()["evidence"].items():
            with self.subTest(evidence=name):
                self.assertNotEqual(entry["keyClass"], "production")

    def test_every_recorded_row_names_the_command_that_produced_it(self) -> None:
        for name, entry in self.record()["evidence"].items():
            with self.subTest(evidence=name):
                self.assertTrue(entry["command"].strip())
                self.assertTrue(entry["method"].strip())

    def test_recorded_rows_are_a_subset_of_the_required_set(self) -> None:
        self.assertTrue(set(self.record()["evidence"]) <= set(REQUIRED_AUTOMATED))

    def test_environments_and_key_classes_are_from_the_closed_vocabularies(self) -> None:
        for name, entry in self.record()["evidence"].items():
            with self.subTest(evidence=name):
                self.assertIn(entry["environment"], ENVIRONMENTS)
                self.assertIn(entry["keyClass"], KEY_CLASSES)


if __name__ == "__main__":
    unittest.main()

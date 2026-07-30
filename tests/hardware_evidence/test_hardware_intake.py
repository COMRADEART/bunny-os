"""Physical hardware evidence intake: redaction and substantiation.

One of the fourteen mandated adversarial cases lives here: a fake physical
hardware report. A report is fake in the sense that matters when it claims
outcomes it cannot show artifacts for, so that is what is tested.

Directory naming note: the brief names this suite ``tests/hardware-evidence/``.
A hyphen is not a valid Python identifier, so ``unittest discover`` cannot
import such a package and the tests would silently never run. The underscore
spelling keeps them executing, which matters more than the spelling.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from release.hardware import (
    HARDWARE_CHARACTERISTICS,
    HARDWARE_TESTS,
    HardwareEvidenceError,
    evaluate_intake,
    parse_report,
    redaction_findings,
)

ROOT = Path(__file__).resolve().parents[2]


def report(**overrides):
    base = {
        "reportId": "hw-0001",
        "submittedBy": "submitter",
        "submittedAt": "2026-07-29T00:00:00Z",
        "architecture": "x86-64",
        "firmwareMode": "uefi-secure-boot",
        "formFactor": "ultraportable-laptop",
        "chipsetClass": "intel-tiger-lake",
        "firmwareVendor": "vendor",
        "firmwareVersion": "1.14.0",
        "characteristics": {name: True for name in HARDWARE_CHARACTERISTICS},
        "results": {name: "NOT_RUN" for name in HARDWARE_TESTS},
        "evidence": {},
        "imageDigest": "sha256:" + "0" * 64,
        "sourceCommit": "0" * 40,
    }
    base.update(overrides)
    return base


class RedactionTests(unittest.TestCase):
    def test_mac_address_is_detected(self):
        findings = redaction_findings({"notes": "adapter AA:BB:CC:DD:EE:FF came up"})
        self.assertTrue(any("MAC address" in item for item in findings))

    def test_hyphenated_mac_address_is_detected(self):
        findings = redaction_findings({"notes": "aa-bb-cc-dd-ee-ff"})
        self.assertTrue(any("MAC address" in item for item in findings))

    def test_labelled_serial_is_detected(self):
        findings = redaction_findings({"notes": "Serial: ABC12345"})
        self.assertTrue(findings)

    def test_labelled_hostname_is_detected(self):
        findings = redaction_findings({"notes": "hostname=alices-laptop"})
        self.assertTrue(findings)

    def test_labelled_username_is_detected(self):
        findings = redaction_findings({"notes": "username: alice"})
        self.assertTrue(findings)

    def test_serial_like_token_is_detected(self):
        findings = redaction_findings({"formFactor": "7X2K9M3Q"})
        self.assertTrue(findings)

    def test_digest_fields_are_exempt(self):
        findings = redaction_findings({"sourceCommit": "a1b2c3d4" * 5})
        self.assertEqual(findings, [])

    def test_clean_report_produces_no_findings(self):
        self.assertEqual(redaction_findings(report()), [])

    def test_report_with_a_mac_address_is_rejected(self):
        with self.assertRaises(HardwareEvidenceError) as caught:
            parse_report(report(notes="wifi mac AA:BB:CC:DD:EE:FF"))
        self.assertIn("personal or device identifiers", str(caught.exception))

    def test_identifier_in_a_nested_field_is_rejected(self):
        with self.assertRaises(HardwareEvidenceError):
            parse_report(report(evidence={"boot": "logs/serial: XYZ98765/boot.log"}))


class SubstantiationTests(unittest.TestCase):
    """Adversarial: a fake physical hardware report."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.evidence_root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def _artifact(self, name: str) -> str:
        target = self.evidence_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("captured output", encoding="utf-8")
        return name

    def test_all_pass_with_no_artifacts_is_rejected(self):
        payload = report(results={name: "PASS" for name in HARDWARE_TESTS})
        with self.assertRaises(HardwareEvidenceError) as caught:
            parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertIn("unsubstantiated", str(caught.exception))

    def test_pass_naming_a_missing_artifact_is_rejected(self):
        payload = report(
            results={**{name: "NOT_RUN" for name in HARDWARE_TESTS}, "boot": "PASS"},
            evidence={"boot": "hw-0001/boot.log"},
        )
        with self.assertRaises(HardwareEvidenceError) as caught:
            parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertIn("does not exist", str(caught.exception))

    def test_pass_naming_a_present_artifact_is_accepted(self):
        reference = self._artifact("hw-0001/boot.log")
        payload = report(
            results={**{name: "NOT_RUN" for name in HARDWARE_TESTS}, "boot": "PASS"},
            evidence={"boot": reference},
        )
        parsed = parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertIn("boot", parsed.passingTests)

    def test_fail_also_requires_an_artifact(self):
        payload = report(
            results={**{name: "NOT_RUN" for name in HARDWARE_TESTS}, "camera": "FAIL"},
            evidence={},
        )
        with self.assertRaises(HardwareEvidenceError):
            parse_report(payload, evidenceRoot=self.evidence_root)

    def test_evidence_path_escaping_the_directory_is_rejected(self):
        payload = report(
            results={**{name: "NOT_RUN" for name in HARDWARE_TESTS}, "boot": "PASS"},
            evidence={"boot": "../../etc/passwd"},
        )
        with self.assertRaises(HardwareEvidenceError) as caught:
            parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertIn("escapes", str(caught.exception))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.evidence_root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        for name in HARDWARE_TESTS:
            target = self.evidence_root / f"hw-0001/{name}.log"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("captured", encoding="utf-8")

    def _full(self, **overrides):
        payload = report(
            results={name: "PASS" for name in HARDWARE_TESTS},
            evidence={name: f"hw-0001/{name}.log" for name in HARDWARE_TESTS},
        )
        payload.update(overrides)
        return payload

    def test_fully_evidenced_machine_qualifies(self):
        parsed = parse_report(self._full(), evidenceRoot=self.evidence_root)
        self.assertTrue(parsed.qualified)

    def test_one_untested_item_disqualifies_the_machine(self):
        payload = self._full()
        payload["results"]["camera"] = "NOT_RUN"
        parsed = parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertFalse(parsed.qualified)
        self.assertIn("camera", parsed.untestedTests)

    def test_one_failure_disqualifies_the_machine(self):
        payload = self._full()
        payload["results"]["suspend"] = "FAIL"
        parsed = parse_report(payload, evidenceRoot=self.evidence_root)
        self.assertFalse(parsed.qualified)

    def test_unknown_test_name_is_refused(self):
        payload = self._full()
        payload["results"]["overclocking"] = "PASS"
        with self.assertRaises(HardwareEvidenceError):
            parse_report(payload, evidenceRoot=self.evidence_root)

    def test_non_x86_architecture_is_refused(self):
        with self.assertRaises(HardwareEvidenceError):
            parse_report(self._full(architecture="aarch64"), evidenceRoot=self.evidence_root)

    def test_intake_requires_an_x86_uefi_machine(self):
        document = {"schemaVersion": 1, "reports": [self._full()]}
        result = evaluate_intake(document, evidenceRoot=self.evidence_root)
        self.assertTrue(result["requirementMet"])
        self.assertEqual(result["result"], "PASS")

    def test_legacy_bios_machine_does_not_meet_the_requirement(self):
        document = {"schemaVersion": 1, "reports": [self._full(firmwareMode="legacy-bios")]}
        result = evaluate_intake(document, evidenceRoot=self.evidence_root)
        self.assertFalse(result["requirementMet"])

    def test_empty_intake_is_blocked(self):
        result = evaluate_intake({"schemaVersion": 1, "reports": []}, evidenceRoot=self.evidence_root)
        self.assertFalse(result["requirementMet"])
        self.assertEqual(result["result"], "BLOCKED")


class RepositoryStateTests(unittest.TestCase):
    def test_the_repository_currently_has_no_qualified_machine(self):
        """Honesty check: if this starts failing, real hardware evidence arrived."""
        document = json.loads((ROOT / "operations/data/hardware-evidence.json").read_text(encoding="utf-8"))
        result = evaluate_intake(document, evidenceRoot=ROOT / "hardware/evidence")
        self.assertFalse(
            result["requirementMet"],
            "hardware evidence now exists; update PHYSICAL_HARDWARE_QUALIFICATION_REPORT.md and this test",
        )

    def test_intake_template_is_shaped_correctly(self):
        payload = json.loads((ROOT / "hardware/evidence/template.json").read_text(encoding="utf-8"))
        payload.pop("_comment", None)
        parsed = parse_report(payload, evidenceRoot=None)
        self.assertFalse(parsed.qualified, "the template must not claim a qualified machine")
        self.assertEqual(len(parsed.results), len(HARDWARE_TESTS))


if __name__ == "__main__":
    unittest.main()

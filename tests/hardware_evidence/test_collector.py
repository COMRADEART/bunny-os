# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The on-device collector, the guided runner, and the signature model.

The mandated adversarial cases exercised here:

* a fake hardware report (case 10)
* a report containing a hardware serial number (case 11)
* a ``NOT_RUN`` hardware test marked ``PASS`` (case 12)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from release.hardware import (
    COLLECTOR_FIELDS,
    EXCLUDED_CATEGORIES,
    FORBIDDEN_TERMS,
    GUIDED_TESTS,
    HARDWARE_TESTS,
    PERMITTED_CLAIMS,
    SIGNER_ROLES,
    HardwareCollectionError,
    HardwareEvidenceError,
    assert_collector_scope,
    assert_no_certification_claim,
    evaluate_collection,
    parse_evidence_signature,
    parse_guided_test,
    parse_report,
    redaction_findings,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/bunny-os"))

from bunny_os import qualification as collector  # noqa: E402


def guided(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "test": "boot",
        "startedAt": "2026-08-01T10:00:00Z",
        "completedAt": "2026-08-01T10:05:00Z",
        "operator": "operator-1",
        "expectedResult": "the system reaches the login screen",
        "actualResult": "reached the login screen in 18 seconds",
        "outcome": "PASS",
        "evidenceReference": "template.json",
        "notes": "",
        "logs": [],
        "redactionState": "completed",
    }
    record.update(overrides)
    return record


class CollectorScope(unittest.TestCase):
    def test_the_collector_emits_exactly_the_allow_listed_fields(self) -> None:
        payload = collector.collect()
        self.assertEqual(set(payload["collected"]), set(COLLECTOR_FIELDS))

    def test_the_two_copies_of_the_field_list_agree(self) -> None:
        # The collector is installed onto a device and cannot import release/.
        # Duplication is deliberate; drift is a test failure.
        self.assertEqual(collector.COLLECTOR_FIELDS, COLLECTOR_FIELDS)
        self.assertEqual(collector.EXCLUDED_CATEGORIES, EXCLUDED_CATEGORIES)
        self.assertEqual(collector.GUIDED_TESTS, GUIDED_TESTS)

    def test_an_excluded_category_is_refused_by_name(self) -> None:
        for name in EXCLUDED_CATEGORIES:
            with self.assertRaises(HardwareCollectionError, msg=name) as raised:
                assert_collector_scope({name: "value"})
            self.assertIn("excluded categories", str(raised.exception))

    def test_a_field_outside_the_allow_list_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            assert_collector_scope({"cpuTemperature": "62C"})
        self.assertIn("outside the allow-list", str(raised.exception))

    def test_the_collector_has_no_function_reading_an_excluded_category(self) -> None:
        # A crude check on purpose. The per-interface hardware address file, the
        # hostname calls and the login-name calls are the four routes by which an
        # excluded category would enter, and none of their names appears here.
        source = (ROOT / "tools/bunny-os/bunny_os/qualification.py").read_text(encoding="utf-8")
        for token in ("/address", "gethostname", "getpass", "getlogin", "NetworkManager", "iwconfig"):
            self.assertNotIn(token, source, f"the collector references {token}")

    def test_ram_is_recorded_as_a_category(self) -> None:
        payload = collector.collect()
        self.assertIn(
            payload["collected"]["ramSizeCategory"],
            {"under-4GB", "4-8GB", "8-16GB", "16-32GB", "32GB-or-more", "unknown"},
        )

    def test_every_guided_test_defaults_to_not_run(self) -> None:
        payload = collector.collect()
        self.assertEqual(set(payload["collected"]["testResults"]), set(GUIDED_TESTS))
        self.assertEqual(set(payload["collected"]["testResults"].values()), {"NOT_RUN"})

    def test_the_fifteen_intake_tests_map_into_the_twenty_one_guided_tests(self) -> None:
        mapping = {
            "install": "installation",
            "encryption": "encrypted-installation",
            "network": "wifi",
            "bunny-disabled": "bunny-disabled-mode",
            "local-only": "local-only-mode",
        }
        for name in HARDWARE_TESTS:
            self.assertIn(mapping.get(name, name), GUIDED_TESTS, name)


class NotRunIsNeverPass(unittest.TestCase):
    """Adversarial case 12."""

    def test_a_not_run_record_carrying_a_result_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(guided(outcome="NOT_RUN"))
        self.assertIn("NOT_RUN must never be converted to PASS", str(raised.exception))

    def test_a_not_run_record_carrying_an_artifact_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError):
            parse_guided_test(guided(outcome="NOT_RUN", actualResult=""))

    def test_a_clean_not_run_is_accepted(self) -> None:
        parsed = parse_guided_test(
            guided(outcome="NOT_RUN", actualResult="", evidenceReference=None)
        )
        self.assertEqual(parsed.outcome, "NOT_RUN")

    def test_the_collector_refuses_to_record_a_pass_without_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with self.assertRaises(collector.QualificationError) as raised:
                collector.record_test(
                    test="wifi",
                    outcome="PASS",
                    operator="operator-1",
                    expected="associates with a WPA3 network",
                    actual="",
                    evidence="wifi.log",
                    notes="",
                    logs=[],
                    redaction="completed",
                    startedAt=None,
                    statePath=state,
                )
            self.assertIn("requires the observed result", str(raised.exception))

    def test_the_collector_refuses_a_not_run_carrying_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with self.assertRaises(collector.QualificationError) as raised:
                collector.record_test(
                    test="wifi",
                    outcome="NOT_RUN",
                    operator="",
                    expected="",
                    actual="it worked",
                    evidence=None,
                    notes="",
                    logs=[],
                    redaction="not-required",
                    startedAt=None,
                    statePath=state,
                )
            self.assertIn("A test that produced a result was run", str(raised.exception))

    def test_a_report_with_any_not_run_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            collector.record_test(
                test="boot",
                outcome="PASS",
                operator="operator-1",
                expected="reaches login",
                actual="reached login",
                evidence="boot.log",
                notes="",
                logs=[],
                redaction="completed",
                startedAt=None,
                statePath=state,
            )
            report = collector.build_report(operator="operator-1", statePath=state)
        self.assertFalse(report["complete"])
        self.assertEqual(len(report["notRunTests"]), len(GUIDED_TESTS) - 1)


class FakeReportIsRefused(unittest.TestCase):
    """Adversarial case 10."""

    def test_a_report_of_all_passes_with_no_artifacts_is_refused(self) -> None:
        with self.assertRaises(HardwareEvidenceError) as raised:
            parse_report(
                {
                    "reportId": "hw-0001",
                    "submittedBy": "test operator",
                    "submittedAt": "2026-08-01T10:00:00Z",
                    "architecture": "x86-64",
                    "firmwareMode": "uefi-secure-boot",
                    "formFactor": "laptop",
                    "chipsetClass": "consumer",
                    "firmwareVendor": "vendor",
                    "firmwareVersion": "1.0",
                    "characteristics": {},
                    "results": {name: "PASS" for name in HARDWARE_TESTS},
                    "evidence": {},
                    "imageDigest": "sha256:" + "0" * 64,
                    "sourceCommit": "0" * 40,
                },
                evidenceRoot=ROOT / "hardware/evidence",
            )
        self.assertIn("unsubstantiated", str(raised.exception))

    def test_a_guided_pass_with_no_artifact_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(guided(evidenceReference=None))
        self.assertIn("is an assertion", str(raised.exception))

    def test_a_guided_pass_naming_a_missing_artifact_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(
                guided(evidenceReference="absent.log"), evidenceRoot=ROOT / "hardware/evidence"
            )
        self.assertIn("does not exist", str(raised.exception))

    def test_an_evidence_path_escaping_the_evidence_root_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(
                guided(evidenceReference="../../LICENSE"), evidenceRoot=ROOT / "hardware/evidence"
            )
        self.assertIn("escapes", str(raised.exception))

    def test_a_signature_over_a_changed_report_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_evidence_signature(
                {
                    "role": "test-operator",
                    "signerName": "operator-1",
                    "signedAt": "2026-08-01T12:00:00Z",
                    "signature": "MEUCIQ...",
                    "publicKey": "ssh-ed25519 AAAA...",
                    "reportDigest": "a" * 64,
                },
                reportDigest="b" * 64,
            )
        self.assertIn("changed after it was signed", str(raised.exception))


class SerialNumbersAreRefused(unittest.TestCase):
    """Adversarial case 11."""

    def test_a_labelled_serial_number_is_found(self) -> None:
        findings = redaction_findings({"notes": "serial: 5CD1234ABC"})
        self.assertTrue(findings)
        self.assertIn("labelled identifier", findings[0])

    def test_a_mac_address_is_found(self) -> None:
        findings = redaction_findings({"notes": "adapter 00:1a:2b:3c:4d:5e"})
        self.assertTrue(any("MAC address" in item for item in findings))

    def test_a_bare_serial_like_token_is_found(self) -> None:
        findings = redaction_findings({"chipsetClass": "PF0X9K2Q1"})
        self.assertTrue(any("serial number or asset tag" in item for item in findings))

    def test_the_scan_walks_a_nested_field_nobody_thought_about(self) -> None:
        findings = redaction_findings(
            {"characteristics": {"detail": {"deep": {"note": "hostname: buildbox-01"}}}}
        )
        self.assertTrue(findings)

    def test_a_collection_carrying_an_identifier_is_rejected(self) -> None:
        result = evaluate_collection(
            {
                "schemaVersion": 1,
                "collections": [
                    {
                        "collectionId": "collection-1",
                        "submittedBy": "test operator",
                        "collected": {name: "unknown" for name in COLLECTOR_FIELDS},
                        "guidedTests": [],
                        "notes": "mac: 00:1a:2b:3c:4d:5e",
                    }
                ],
            }
        )
        self.assertTrue(result["rejected"])
        self.assertEqual(result["result"], "BLOCKED")

    def test_an_ordinary_report_is_not_flagged(self) -> None:
        self.assertEqual(redaction_findings({"formFactor": "laptop", "architecture": "x86-64"}), [])


class CertificationLanguageIsRefused(unittest.TestCase):
    def test_the_word_certified_is_refused(self) -> None:
        for term in FORBIDDEN_TERMS:
            with self.assertRaises(HardwareCollectionError, msg=term) as raised:
                assert_no_certification_claim(f"this machine is {term}")
            self.assertIn("not hardware certification", str(raised.exception))

    def test_the_permitted_claims_are_offered_in_the_refusal(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            assert_no_certification_claim("certified for use")
        for claim in PERMITTED_CLAIMS:
            self.assertIn(claim, str(raised.exception))

    def test_a_guided_test_note_claiming_certification_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError):
            parse_guided_test(guided(notes="this configuration is certified"))

    def test_a_signature_statement_claiming_certification_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError):
            parse_evidence_signature(
                {
                    "role": "approved-laboratory",
                    "signerName": "Laboratory",
                    "signedAt": "2026-08-01T12:00:00Z",
                    "signature": "MEUCIQ...",
                    "publicKey": "ssh-ed25519 AAAA...",
                    "reportDigest": "a" * 64,
                    "statement": "we certify this hardware",
                },
                reportDigest="a" * 64,
            )

    def test_the_collector_refuses_a_certification_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with self.assertRaises(collector.QualificationError):
                collector.record_test(
                    test="tpm",
                    outcome="PASS",
                    operator="operator-1",
                    expected="TPM 2.0 present",
                    actual="present and certified",
                    evidence="tpm.log",
                    notes="",
                    logs=[],
                    redaction="completed",
                    startedAt=None,
                    statePath=state,
                )

    def test_permitted_language_is_accepted(self) -> None:
        for claim in PERMITTED_CLAIMS:
            assert_no_certification_claim(f"this machine is {claim}")


class SignatureRoles(unittest.TestCase):
    def test_the_three_roles_are_available(self) -> None:
        self.assertEqual(
            set(SIGNER_ROLES),
            {"test-operator", "approved-laboratory", "project-maintainer-after-verification"},
        )

    def test_an_unknown_role_is_refused(self) -> None:
        with self.assertRaises(HardwareCollectionError):
            parse_evidence_signature(
                {
                    "role": "vendor",
                    "signerName": "x",
                    "signedAt": "2026-08-01T12:00:00Z",
                    "signature": "s",
                    "publicKey": "k",
                    "reportDigest": "a" * 64,
                },
                reportDigest="a" * 64,
            )

    def test_a_maintainer_signature_must_record_how_it_verified(self) -> None:
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_evidence_signature(
                {
                    "role": "project-maintainer-after-verification",
                    "signerName": "maintainer",
                    "signedAt": "2026-08-01T12:00:00Z",
                    "signature": "s",
                    "publicKey": "k",
                    "reportDigest": "a" * 64,
                },
                reportDigest="a" * 64,
            )
        self.assertIn("independently verified", str(raised.exception))

    def test_a_signature_states_what_it_does_not_prove(self) -> None:
        detail = parse_evidence_signature(
            {
                "role": "test-operator",
                "signerName": "operator-1",
                "signedAt": "2026-08-01T12:00:00Z",
                "signature": "s",
                "publicKey": "k",
                "reportDigest": "a" * 64,
            },
            reportDigest="a" * 64,
        )
        self.assertEqual(detail["proves"], "report integrity")
        self.assertIn("hardware certification", detail["doesNotProve"])


class CommittedState(unittest.TestCase):
    def test_no_hardware_collection_has_been_submitted(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/hardware-collections.json").read_text(encoding="utf-8")
        )
        result = evaluate_collection(document, evidenceRoot=ROOT / "hardware/evidence")
        self.assertEqual(result["submitted"], 0)
        self.assertFalse(result["requirementMet"])

    def test_the_committed_state_says_it_needs_a_device(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/hardware-collections.json").read_text(encoding="utf-8")
        )
        self.assertIn("needs a device", document["note"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

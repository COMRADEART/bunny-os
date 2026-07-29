from __future__ import annotations

from pathlib import Path
import unittest

from oem.validation.finalize import (
    CHECK_IDS,
    FACTORY_STATE_CHECKS,
    describe_checks,
    evaluate_finalisation,
)

ROOT = Path(__file__).resolve().parents[2]


def record(**overrides: str) -> dict[str, object]:
    checks = {check_id: "PASS" for check_id in CHECK_IDS}
    checks.update(overrides)
    return {"schemaVersion": 1, "deviceRecordId": "unit-000123", "checks": checks}


class FactoryFinalisationTests(unittest.TestCase):
    def test_all_checks_passing_permits_handoff(self) -> None:
        verdict = evaluate_finalisation(record())
        self.assertTrue(verdict.sealed)
        self.assertEqual(verdict.blockers, ())

    def test_remaining_factory_account_blocks_handoff(self) -> None:
        verdict = evaluate_finalisation(record(**{"factory-accounts-removed": "FAIL"}))
        self.assertFalse(verdict.sealed)
        self.assertIn("factory-accounts-removed", verdict.failures)

    def test_remaining_wifi_profile_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"factory-wifi-profiles-removed": "FAIL"})).sealed)

    def test_remaining_test_credential_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"test-credentials-removed": "FAIL"})).sealed)

    def test_remaining_shell_history_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"shell-history-cleared": "FAIL"})).sealed)

    def test_identifier_logs_block_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"identifier-logs-removed": "FAIL"})).sealed)

    def test_unregenerated_machine_id_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"machine-id-regenerated": "FAIL"})).sealed)

    def test_completed_first_user_setup_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"first-user-setup-incomplete": "FAIL"})).sealed)

    def test_unverified_recovery_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"recovery-verified": "FAIL"})).sealed)

    def test_unverified_image_signature_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"image-signatures-verified": "FAIL"})).sealed)

    def test_retained_diagnostic_serial_blocks_handoff(self) -> None:
        self.assertFalse(evaluate_finalisation(record(**{"diagnostic-serials-not-retained": "FAIL"})).sealed)

    def test_unknown_status_is_not_a_pass(self) -> None:
        verdict = evaluate_finalisation(record(**{"burn-in-completed": "UNKNOWN"}))
        self.assertFalse(verdict.sealed)
        self.assertIn("burn-in-completed", verdict.unknown)

    def test_not_run_status_is_not_a_pass(self) -> None:
        verdict = evaluate_finalisation(record(**{"tpm-state-recorded": "NOT_RUN"}))
        self.assertFalse(verdict.sealed)
        self.assertIn("tpm-state-recorded", verdict.unknown)

    def test_missing_check_blocks_handoff(self) -> None:
        value = record()
        del value["checks"]["host-keys-regenerated"]
        verdict = evaluate_finalisation(value)
        self.assertFalse(verdict.sealed)
        self.assertIn("host-keys-regenerated", verdict.missing)

    def test_unknown_check_id_is_rejected(self) -> None:
        value = record()
        value["checks"]["definitely-fine"] = "PASS"
        with self.assertRaises(ValueError):
            evaluate_finalisation(value)

    def test_invalid_status_is_rejected(self) -> None:
        value = record()
        value["checks"]["recovery-verified"] = "PROBABLY"
        with self.assertRaises(ValueError):
            evaluate_finalisation(value)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        value = record()
        value["schemaVersion"] = 2
        with self.assertRaises(ValueError):
            evaluate_finalisation(value)

    def test_enrolment_and_sync_state_must_be_absent(self) -> None:
        for check in ("enrolment-state-absent", "sync-state-absent", "device-identity-absent-or-fresh"):
            with self.subTest(check=check):
                self.assertFalse(evaluate_finalisation(record(**{check: "FAIL"})).sealed)

    def test_catalogue_covers_every_documented_cleanup_step(self) -> None:
        described = {item["checkId"] for item in describe_checks()}
        self.assertEqual(described, set(CHECK_IDS))
        self.assertEqual(len(FACTORY_STATE_CHECKS), len(CHECK_IDS))

    def test_cli_refuses_handoff_with_residual_state(self) -> None:
        source = (ROOT / "oem/cli.py").read_text(encoding="utf-8")
        self.assertIn("Customer handoff refused", source)
        self.assertIn("EXIT_UNAVAILABLE = 78", source)

    def test_provisioning_executor_is_not_silently_implemented(self) -> None:
        source = (ROOT / "oem/cli.py").read_text(encoding="utf-8")
        self.assertIn("writesPerformed", source)
        self.assertIn("source-only build", source)


if __name__ == "__main__":
    unittest.main()

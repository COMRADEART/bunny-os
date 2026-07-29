from __future__ import annotations

import unittest

from enterprise.decommission import (
    ORGANISATION_OWNED_ONLY_ACTIONS,
    REQUIRED_ACTIONS,
    SCENARIOS,
    DecommissionError,
    evaluate_decommission,
    lost_device_response,
    required_actions,
)

CORRELATION = "0f9c2a1b-4d3e-4f5a-8b6c-7d8e9f0a1b2c"


def record(scenario: str, *, organisation_owned: bool = True, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "scenario": scenario,
        "organisationOwned": organisation_owned,
        "completedActions": list(REQUIRED_ACTIONS[scenario]),
        "auditCorrelationId": CORRELATION,
        "recoveryPreserved": True,
    }
    value.update(overrides)
    return value


class DecommissionTests(unittest.TestCase):
    def test_six_scenarios_are_defined(self) -> None:
        self.assertEqual(len(SCENARIOS), 6)

    def test_every_scenario_completes_with_its_required_actions(self) -> None:
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                owned = scenario != "personally-owned-unenrolment"
                verdict = evaluate_decommission(record(scenario, organisation_owned=owned))
                self.assertTrue(verdict.complete, verdict.outstandingActions + verdict.refusals)

    def test_partial_decommission_is_incomplete(self) -> None:
        value = record("lost-device")
        value["completedActions"] = ["revoke-enrolment-certificate"]
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertIn("rotate-sync-keys", verdict.outstandingActions)

    def test_wiping_without_revoking_certificates_is_incomplete(self) -> None:
        value = record("device-retirement")
        value["completedActions"] = ["cryptographic-erase"]
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertIn("revoke-enrolment-certificate", verdict.outstandingActions)

    def test_revoking_without_rotating_sync_keys_is_incomplete(self) -> None:
        value = record("lost-device")
        value["completedActions"] = [
            action for action in REQUIRED_ACTIONS["lost-device"] if action != "rotate-sync-keys"
        ]
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertIn("rotate-sync-keys", verdict.outstandingActions)

    def test_personally_owned_unenrolment_does_not_require_a_wipe(self) -> None:
        actions = required_actions("personally-owned-unenrolment")
        self.assertNotIn("full-reset", actions)
        self.assertNotIn("cryptographic-erase", actions)

    def test_personally_owned_device_cannot_be_fully_reset(self) -> None:
        value = record("personally-owned-unenrolment", organisation_owned=False)
        value["completedActions"] = [*REQUIRED_ACTIONS["personally-owned-unenrolment"], "full-reset"]
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertTrue(any("organisation-owned device" in item for item in verdict.refusals))

    def test_personally_owned_device_cannot_be_cryptographically_erased(self) -> None:
        value = record("personally-owned-unenrolment", organisation_owned=False)
        value["completedActions"] = [*REQUIRED_ACTIONS["personally-owned-unenrolment"], "cryptographic-erase"]
        self.assertFalse(evaluate_decommission(value).complete)

    def test_reset_must_preserve_recovery(self) -> None:
        value = record("device-retirement", recoveryPreserved=False)
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertTrue(any("recovery environment" in item for item in verdict.refusals))

    def test_missing_audit_correlation_is_refused(self) -> None:
        value = record("device-retirement")
        del value["auditCorrelationId"]
        verdict = evaluate_decommission(value)
        self.assertFalse(verdict.complete)
        self.assertTrue(any("auditable" in item for item in verdict.refusals))

    def test_unknown_action_is_refused(self) -> None:
        value = record("lost-device")
        value["completedActions"] = ["sell-the-data"]
        with self.assertRaises(DecommissionError):
            evaluate_decommission(value)

    def test_unknown_scenario_is_refused(self) -> None:
        with self.assertRaises(DecommissionError):
            evaluate_decommission({
                "schemaVersion": 1, "scenario": "gave-it-away", "organisationOwned": True,
                "completedActions": [], "auditCorrelationId": CORRELATION,
            })

    def test_destructive_actions_are_organisation_only(self) -> None:
        self.assertEqual(ORGANISATION_OWNED_ONLY_ACTIONS, frozenset({"full-reset", "cryptographic-erase"}))

    def test_storage_replacement_rotates_keys_and_erases(self) -> None:
        actions = required_actions("storage-replacement")
        self.assertIn("rotate-sync-keys", actions)
        self.assertIn("cryptographic-erase", actions)


class LostDeviceTests(unittest.TestCase):
    def test_lost_device_response_revokes_and_rotates(self) -> None:
        response = lost_device_response()
        self.assertIn("revoke-enrolment-certificate", response["immediateActions"])
        self.assertIn("rotate-sync-keys", response["immediateActions"])
        self.assertIn("revoke-sync-device", response["immediateActions"])

    def test_stolen_device_requires_an_incident_report(self) -> None:
        response = lost_device_response(stolen=True)
        self.assertEqual(response["scenario"], "stolen-device")
        self.assertIn("record-incident-report", response["immediateActions"])
        self.assertTrue(response["auditReportRequired"])

    def test_remote_wipe_remains_ownership_constrained(self) -> None:
        self.assertIn("personally owned", lost_device_response()["remoteWipeConstraint"])

    def test_guidance_is_honest_about_already_downloaded_data(self) -> None:
        guidance = lost_device_response()["recoveryGuidance"]
        self.assertTrue(any("cannot be retracted" in item for item in guidance))

    def test_guidance_notes_luks_protection(self) -> None:
        self.assertTrue(any("LUKS" in item for item in lost_device_response()["recoveryGuidance"]))


if __name__ == "__main__":
    unittest.main()

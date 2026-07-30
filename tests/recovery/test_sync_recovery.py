from __future__ import annotations

import unittest

from sync.recovery import (
    ORGANISATION_RECOVERABLE_COLLECTIONS,
    RECOVERY_METHODS,
    RecoveryError,
    describe_methods,
    evaluate_recovery,
    key_loss_warning,
)

PHRASE = " ".join(["abandon"] * 24)


def request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "method": "recovery-phrase",
        "requestedCollections": ["col-memory"],
        "recoveryPhrasePresented": PHRASE,
    }
    value.update(overrides)
    return value


class SyncRecoveryTests(unittest.TestCase):
    def test_recovery_phrase_permits_recovery(self) -> None:
        decision = evaluate_recovery(request())
        self.assertTrue(decision.permitted, decision.refusals)

    def test_missing_phrase_is_refused(self) -> None:
        decision = evaluate_recovery(request(recoveryPhrasePresented=None))
        self.assertFalse(decision.permitted)

    def test_malformed_phrase_is_refused(self) -> None:
        decision = evaluate_recovery(request(recoveryPhrasePresented="too short"))
        self.assertFalse(decision.permitted)

    def test_recovery_file_requires_a_digest(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "recovery-file", "requestedCollections": ["col-memory"],
        })
        self.assertFalse(decision.permitted)

    def test_recovery_file_with_digest_is_permitted(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "recovery-file",
            "requestedCollections": ["col-memory"], "recoveryFileDigest": "a" * 64,
        })
        self.assertTrue(decision.permitted, decision.refusals)

    def test_trusted_device_recovery_requires_a_device(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "trusted-existing-device",
            "requestedCollections": ["col-memory"],
        })
        self.assertFalse(decision.permitted)

    def test_server_assisted_recovery_of_private_content_is_refused(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "organisation-recovery-policy",
            "requestedCollections": ["organisation-documents"],
            "organisationOwnedDevice": True,
            "organisationPolicyReference": "POL-0042",
            "serverAssisted": True,
        })
        self.assertFalse(decision.permitted)
        self.assertTrue(any("cannot decrypt" in item for item in decision.refusals))

    def test_organisation_recovery_requires_organisation_owned_device(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "organisation-recovery-policy",
            "requestedCollections": ["organisation-documents"],
            "organisationOwnedDevice": False,
            "organisationPolicyReference": "POL-0042",
        })
        self.assertFalse(decision.permitted)
        self.assertTrue(any("personally owned" in item for item in decision.refusals))

    def test_organisation_recovery_cannot_reach_personal_collections(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "organisation-recovery-policy",
            "requestedCollections": ["col-memory"],
            "organisationOwnedDevice": True,
            "organisationPolicyReference": "POL-0042",
        })
        self.assertFalse(decision.permitted)
        self.assertTrue(any("cannot reach" in item for item in decision.refusals))

    def test_organisation_recovery_of_organisation_data_is_permitted(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "organisation-recovery-policy",
            "requestedCollections": ["organisation-documents", "organisation-backup"],
            "organisationOwnedDevice": True,
            "organisationPolicyReference": "POL-0042",
        })
        self.assertTrue(decision.permitted, decision.refusals)
        self.assertTrue(decision.warnings)

    def test_organisation_recovery_requires_a_disclosed_policy(self) -> None:
        decision = evaluate_recovery({
            "schemaVersion": 1, "method": "organisation-recovery-policy",
            "requestedCollections": ["organisation-documents"],
            "organisationOwnedDevice": True,
        })
        self.assertFalse(decision.permitted)

    def test_organisation_recoverable_scope_is_narrow(self) -> None:
        self.assertEqual(len(ORGANISATION_RECOVERABLE_COLLECTIONS), 3)
        self.assertNotIn("col-memory", ORGANISATION_RECOVERABLE_COLLECTIONS)

    def test_key_loss_warning_is_explicit(self) -> None:
        warning = key_loss_warning()
        self.assertTrue(warning["acknowledgementRequired"])
        self.assertIn("cannot be recovered", warning["headline"])
        self.assertTrue(any("nobody at Bunny OS" in item for item in warning["detail"]))

    def test_no_method_lets_the_server_recover_alone(self) -> None:
        for row in describe_methods():
            with self.subTest(method=row["method"]):
                self.assertFalse(row["serverCanPerformAlone"])

    def test_all_four_recovery_methods_are_documented(self) -> None:
        self.assertEqual({row["method"] for row in describe_methods()}, set(RECOVERY_METHODS))

    def test_empty_requested_collections_is_refused(self) -> None:
        with self.assertRaises(RecoveryError):
            evaluate_recovery(request(requestedCollections=[]))

    def test_unknown_method_is_refused(self) -> None:
        with self.assertRaises(RecoveryError):
            evaluate_recovery(request(method="email-a-support-agent"))


if __name__ == "__main__":
    unittest.main()

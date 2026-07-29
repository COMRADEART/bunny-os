from __future__ import annotations

import unittest

from installer.encryption.plans import EncryptionPlan
from installer.encryption.recovery_key import confirm_recovery_key, confirmation_digest, generate_recovery_key


class EncryptionTests(unittest.TestCase):
    def test_luks2_password_plan(self) -> None:
        plan = EncryptionPlan(True, passwordSecretRef="fd:3")
        self.assertEqual(plan.validate(), ())
        self.assertEqual(plan.public_dict()["passwordSecretRef"], "[protected]")

    def test_rejects_plaintext_secret_reference(self) -> None:
        self.assertIn("protected", " ".join(EncryptionPlan(True, passwordSecretRef="hunter2").validate()))

    def test_tpm_requires_fallback_recovery_and_pcr(self) -> None:
        plan = EncryptionPlan(True, unlock="password+tpm2", passwordSecretRef="fd:4", recoveryKey=False, tpm2=True, fallbackPassword=False)
        self.assertGreaterEqual(len(plan.validate()), 3)

    def test_recovery_key_round_trip(self) -> None:
        key = generate_recovery_key()
        self.assertTrue(confirm_recovery_key(key, key.lower()))
        self.assertEqual(len(confirmation_digest(key)), 64)

    def test_wrong_recovery_key_fails(self) -> None:
        self.assertFalse(confirm_recovery_key(generate_recovery_key(), generate_recovery_key()))


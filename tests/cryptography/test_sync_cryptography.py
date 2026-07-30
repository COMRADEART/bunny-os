from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest import mock

from sync import crypto
from sync.backends import reference
from sync.crypto import (
    ACCEPTABLE_BACKENDS,
    EXIT_UNAVAILABLE,
    REQUIRED_OPERATIONS,
    CryptoBackendUnavailable,
    backend_available,
    backend_status,
    require_backend,
)
from sync.envelope import canonical_associated_data
from sync.keys import DERIVATION_LABELS
from sync.pairing import (
    PAIRING_METHODS,
    PairingError,
    compute_fingerprint,
    confirm_pairing,
    fingerprints_match,
    parse_session,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
SESSION_ID = "pair-" + "0" * 32
KEY_A = bytes(range(32))
KEY_B = bytes(range(1, 33))


def stamp(offset_seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def session(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "sessionId": SESSION_ID,
        "method": "existing-trusted-device",
        "newDeviceKeyId": "dev-bbbbbbbbbbbbbbbb",
        "newDeviceName": "New Laptop",
        "initiatingDeviceKeyId": "dev-aaaaaaaaaaaaaaaa",
        "createdAt": stamp(-30),
        "expiresAt": stamp(300),
        "state": "authenticator-displayed",
    }
    value.update(overrides)
    return value


class CryptoBoundaryTests(unittest.TestCase):
    def test_backend_status_reports_reality(self) -> None:
        status = backend_status()
        self.assertEqual(status["available"], backend_available())
        self.assertFalse(status["writesPerformed"])
        if status["available"]:
            self.assertEqual(status["exitCode"], 0)
            self.assertIn("AES-256-GCM", status["supportedAlgorithms"])
        else:
            self.assertEqual(status["exitCode"], EXIT_UNAVAILABLE)
            self.assertEqual(status["supportedAlgorithms"], [])

    def test_openssl_cannot_supply_object_sealing(self) -> None:
        # openssl enc refuses AEAD outright, so a CLI-only backend is not an
        # option for seal-object however convenient that would have been.
        self.assertIn("refuses AEAD", backend_status()["opensslNote"])

    def test_unknown_operation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            require_backend("invent-new-cipher")

    def test_absent_backend_refuses_rather_than_degrading(self) -> None:
        # The property that matters most. With no backend every operation
        # raises: it never returns plaintext and never substitutes a weaker
        # construction, because downstream tests would otherwise pass while
        # nothing was actually encrypted.
        with mock.patch.object(reference, "AVAILABLE", False), mock.patch.object(
            reference, "IMPORT_ERROR", "simulated absence"
        ):
            for operation in REQUIRED_OPERATIONS:
                with self.subTest(operation=operation):
                    with self.assertRaises(CryptoBackendUnavailable) as error:
                        require_backend(operation)
                    self.assertIn("No data was encrypted", str(error.exception))
            self.assertFalse(backend_status()["available"])
            self.assertEqual(backend_status()["exitCode"], EXIT_UNAVAILABLE)
            with self.assertRaises(CryptoBackendUnavailable):
                crypto.seal_object(b"k" * 32, b"n" * 12, b"plaintext", b"aad")

    def test_acceptable_backends_are_named_and_not_vendored(self) -> None:
        self.assertTrue(ACCEPTABLE_BACKENDS)
        self.assertFalse((ROOT / "sync/vendor").exists())

    def test_repository_does_not_implement_its_own_aead(self) -> None:
        sources = [path for path in (ROOT / "sync").rglob("*.py")]
        self.assertTrue(sources)
        for path in sources:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for forbidden in ("def _encrypt_block", "def _aes_", "def _chacha", "S_BOX", "def _feistel"):
                    self.assertNotIn(forbidden, text)

    def test_derivation_labels_are_distinct_per_purpose(self) -> None:
        labels = list(DERIVATION_LABELS.values())
        self.assertEqual(len(labels), len(set(labels)))

    def test_derivation_labels_are_versioned_and_namespaced(self) -> None:
        for purpose, label in DERIVATION_LABELS.items():
            with self.subTest(purpose=purpose):
                self.assertTrue(label.startswith(b"bunny-os/sync/v1/"))

    def test_no_private_key_material_is_committed_under_sync(self) -> None:
        for path in (ROOT / "sync").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("-----BEGIN PRIVATE KEY-----", text)
                self.assertNotIn("-----BEGIN OPENSSH PRIVATE KEY-----", text)

    def test_canonical_associated_data_is_order_independent(self) -> None:
        self.assertEqual(
            canonical_associated_data({"b": 2, "a": 1}),
            canonical_associated_data({"a": 1, "b": 2}),
        )
        self.assertEqual(canonical_associated_data({"a": 1, "b": 2}), b'{"a":1,"b":2}')


@unittest.skipUnless(backend_available(), "no reviewed cryptographic backend installed")
class RealCryptographyTests(unittest.TestCase):
    """Exercises the backend for real. Skipped when it is absent."""

    def setUp(self) -> None:
        self.key = b"K" * 32
        self.nonce = crypto.generate_nonce()
        self.aad = b'{"collectionId":"col-memory","objectId":"obj-1"}'

    def test_round_trip_recovers_the_plaintext(self) -> None:
        sealed = crypto.seal_object(self.key, self.nonce, b"a private memory", self.aad)
        self.assertNotIn(b"a private memory", sealed)
        self.assertEqual(crypto.open_object(self.key, self.nonce, sealed, self.aad), b"a private memory")

    def test_tampered_ciphertext_is_rejected(self) -> None:
        sealed = bytearray(crypto.seal_object(self.key, self.nonce, b"payload", self.aad))
        sealed[0] ^= 0x01
        with self.assertRaises(reference.BackendError):
            crypto.open_object(self.key, self.nonce, bytes(sealed), self.aad)

    def test_truncated_ciphertext_is_rejected(self) -> None:
        sealed = crypto.seal_object(self.key, self.nonce, b"payload", self.aad)
        with self.assertRaises(reference.BackendError):
            crypto.open_object(self.key, self.nonce, sealed[:-1], self.aad)

    def test_mismatched_associated_data_is_rejected(self) -> None:
        sealed = crypto.seal_object(self.key, self.nonce, b"payload", self.aad)
        other = b'{"collectionId":"col-memory","objectId":"obj-2"}'
        with self.assertRaises(reference.BackendError):
            crypto.open_object(self.key, self.nonce, sealed, other)

    def test_wrong_key_is_rejected(self) -> None:
        sealed = crypto.seal_object(self.key, self.nonce, b"payload", self.aad)
        with self.assertRaises(reference.BackendError):
            crypto.open_object(b"X" * 32, self.nonce, sealed, self.aad)

    def test_wrong_nonce_is_rejected(self) -> None:
        sealed = crypto.seal_object(self.key, self.nonce, b"payload", self.aad)
        with self.assertRaises(reference.BackendError):
            crypto.open_object(self.key, b"z" * 12, sealed, self.aad)

    def test_empty_associated_data_is_refused(self) -> None:
        # An unbound ciphertext could be relocated to another object.
        with self.assertRaises(reference.BackendError):
            crypto.seal_object(self.key, self.nonce, b"payload", b"")

    def test_derivation_is_deterministic_and_purpose_separated(self) -> None:
        parent = b"P" * 32
        first = crypto.derive_subkey(parent, "collection-key")
        again = crypto.derive_subkey(parent, "collection-key")
        other = crypto.derive_subkey(parent, "backup-key")
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 32)

    def test_root_key_derivation_works(self) -> None:
        self.assertEqual(len(crypto.derive_root_key(b"S" * 32)), 32)

    def test_unknown_derivation_purpose_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            crypto.derive_subkey(b"P" * 32, "exfiltrate")

    def test_key_wrap_round_trip(self) -> None:
        wrapped = crypto.wrap_key(b"W" * 32, b"T" * 32)
        self.assertNotEqual(wrapped, b"T" * 32)
        self.assertEqual(crypto.unwrap_key(b"W" * 32, wrapped), b"T" * 32)

    def test_wrapped_key_integrity_is_verified(self) -> None:
        wrapped = bytearray(crypto.wrap_key(b"W" * 32, b"T" * 32))
        wrapped[0] ^= 0x01
        with self.assertRaises(reference.BackendError):
            crypto.unwrap_key(b"W" * 32, bytes(wrapped))

    def test_unwrapping_with_the_wrong_key_fails(self) -> None:
        wrapped = crypto.wrap_key(b"W" * 32, b"T" * 32)
        with self.assertRaises(reference.BackendError):
            crypto.unwrap_key(b"X" * 32, wrapped)

    def test_xchacha_is_refused_rather_than_substituted(self) -> None:
        # The envelope format permits it; this backend cannot do it. Quietly
        # using a different construction would make the declared algorithm false.
        with self.assertRaises(reference.BackendError) as error:
            crypto.seal_object(self.key, self.nonce, b"x", self.aad, algorithm="XChaCha20-Poly1305")
        self.assertIn("libsodium", str(error.exception))

    def test_recovery_entropy_is_full_length_and_unique(self) -> None:
        first = crypto.generate_recovery_entropy()
        second = crypto.generate_recovery_entropy()
        self.assertEqual(len(first), 32)
        self.assertNotEqual(first, second)

    def test_nonces_do_not_repeat(self) -> None:
        self.assertEqual(len({crypto.generate_nonce() for _ in range(64)}), 64)

    def test_short_key_is_refused(self) -> None:
        with self.assertRaises(reference.BackendError):
            crypto.seal_object(b"short", self.nonce, b"x", self.aad)

    def test_recovery_phrase_encoding_requires_a_reviewed_wordlist(self) -> None:
        with self.assertRaises(reference.BackendError):
            reference.encode_recovery_phrase(b"E" * 32, ["word"] * 10)
        words = reference.encode_recovery_phrase(b"E" * 32, [f"w{index}" for index in range(2048)])
        self.assertEqual(len(words), 23)


class PairingTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_grouped(self) -> None:
        value = compute_fingerprint(KEY_A, session_id=SESSION_ID)
        self.assertEqual(value, compute_fingerprint(KEY_A, session_id=SESSION_ID))
        self.assertEqual(len(value.split("-")), 4)

    def test_different_key_yields_different_fingerprint(self) -> None:
        self.assertNotEqual(
            compute_fingerprint(KEY_A, session_id=SESSION_ID),
            compute_fingerprint(KEY_B, session_id=SESSION_ID),
        )

    def test_fingerprint_is_bound_to_the_session(self) -> None:
        other = "pair-" + "1" * 32
        self.assertNotEqual(
            compute_fingerprint(KEY_A, session_id=SESSION_ID),
            compute_fingerprint(KEY_A, session_id=other),
        )

    def test_short_key_material_is_refused(self) -> None:
        with self.assertRaises(PairingError):
            compute_fingerprint(b"short", session_id=SESSION_ID)

    def test_valid_session_parses_and_recomputes_locally(self) -> None:
        parsed = parse_session(session(), public_key=KEY_A, now=NOW)
        self.assertEqual(parsed.authenticator, compute_fingerprint(KEY_A, session_id=SESSION_ID))

    def test_display_shows_device_name_and_fingerprint(self) -> None:
        display = parse_session(session(), public_key=KEY_A, now=NOW).display()
        self.assertEqual(display["newDeviceName"], "New Laptop")
        self.assertTrue(display["keyFingerprint"])
        self.assertIn("substituted", display["instruction"])

    def test_server_side_key_substitution_is_detected(self) -> None:
        parsed = parse_session(session(), public_key=KEY_B, now=NOW)
        user_confirmed = compute_fingerprint(KEY_A, session_id=SESSION_ID)
        with self.assertRaises(PairingError) as error:
            confirm_pairing(parsed, userConfirmedAuthenticator=user_confirmed)
        self.assertIn("substituted the device key", str(error.exception))

    def test_matching_fingerprint_completes_pairing(self) -> None:
        parsed = parse_session(session(), public_key=KEY_A, now=NOW)
        result = confirm_pairing(parsed, userConfirmedAuthenticator=parsed.authenticator)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["collectionsGranted"], [])

    def test_new_device_receives_no_collections_by_default(self) -> None:
        parsed = parse_session(session(), public_key=KEY_A, now=NOW)
        result = confirm_pairing(parsed, userConfirmedAuthenticator=parsed.authenticator)
        self.assertIn("defaults to granting nothing", result["note"])

    def test_session_replay_is_refused(self) -> None:
        consumed: set[str] = set()
        parsed = parse_session(session(), public_key=KEY_A, now=NOW, consumed_session_ids=consumed)
        confirm_pairing(parsed, userConfirmedAuthenticator=parsed.authenticator, consumed_session_ids=consumed)
        with self.assertRaises(PairingError) as error:
            parse_session(session(), public_key=KEY_A, now=NOW, consumed_session_ids=consumed)
        self.assertIn("replay refused", str(error.exception))

    def test_expired_session_is_refused(self) -> None:
        with self.assertRaises(PairingError) as error:
            parse_session(session(createdAt=stamp(-900), expiresAt=stamp(-600)), public_key=KEY_A, now=NOW)
        self.assertIn("expired", str(error.exception))

    def test_overlong_session_lifetime_is_refused(self) -> None:
        with self.assertRaises(PairingError):
            parse_session(session(createdAt=stamp(0), expiresAt=stamp(7200)), public_key=KEY_A, now=NOW)

    def test_method_downgrade_is_refused(self) -> None:
        with self.assertRaises(PairingError) as error:
            parse_session(
                session(method="one-time-code"),
                public_key=KEY_A,
                now=NOW,
                initiating_method="existing-trusted-device",
            )
        self.assertIn("downgrade refused", str(error.exception))

    def test_equal_or_stronger_method_is_accepted(self) -> None:
        parse_session(
            session(method="existing-trusted-device"),
            public_key=KEY_A,
            now=NOW,
            initiating_method="one-time-code",
        )

    def test_self_pairing_is_refused(self) -> None:
        with self.assertRaises(PairingError):
            parse_session(session(newDeviceKeyId="dev-aaaaaaaaaaaaaaaa"), public_key=KEY_A, now=NOW)

    def test_empty_user_confirmation_is_refused(self) -> None:
        parsed = parse_session(session(), public_key=KEY_A, now=NOW)
        with self.assertRaises(PairingError):
            confirm_pairing(parsed, userConfirmedAuthenticator="   ")

    def test_fingerprint_comparison_is_case_and_space_insensitive(self) -> None:
        value = compute_fingerprint(KEY_A, session_id=SESSION_ID)
        self.assertTrue(fingerprints_match(value, f"  {value.lower()}  "))

    def test_all_five_pairing_methods_are_supported(self) -> None:
        self.assertEqual(len(PAIRING_METHODS), 5)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from sync.crypto import (
    ACCEPTABLE_BACKENDS,
    EXIT_UNAVAILABLE,
    REQUIRED_OPERATIONS,
    CryptoBackendUnavailable,
    backend_status,
    require_backend,
)
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
    def test_backend_reports_unavailable(self) -> None:
        status = backend_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["writesPerformed"])
        self.assertEqual(status["exitCode"], EXIT_UNAVAILABLE)

    def test_openssl_on_path_does_not_imply_a_reviewed_backend(self) -> None:
        status = backend_status()
        self.assertFalse(status["available"])
        self.assertIn("not sufficient", status["reason"])

    def test_every_operation_refuses_rather_than_degrading(self) -> None:
        for operation in REQUIRED_OPERATIONS:
            with self.subTest(operation=operation):
                with self.assertRaises(CryptoBackendUnavailable) as error:
                    require_backend(operation)
                self.assertIn("No data was encrypted", str(error.exception))

    def test_unknown_operation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            require_backend("invent-new-cipher")

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
                session(method="one-time-code"), public_key=KEY_A, now=NOW,
                initiating_method="existing-trusted-device",
            )
        self.assertIn("downgrade refused", str(error.exception))

    def test_equal_or_stronger_method_is_accepted(self) -> None:
        parse_session(
            session(method="existing-trusted-device"), public_key=KEY_A, now=NOW,
            initiating_method="one-time-code",
        )

    def test_self_pairing_is_refused(self) -> None:
        with self.assertRaises(PairingError):
            parse_session(
                session(newDeviceKeyId="dev-aaaaaaaaaaaaaaaa"), public_key=KEY_A, now=NOW
            )

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

from __future__ import annotations

import unittest

from enterprise.attestation import (
    APPROVED_FIELDS,
    AttestationError,
    parse_attestation,
)
from enterprise.identity import (
    FORBIDDEN_IDENTITY_SOURCES,
    IDENTITY_KINDS,
    IdentityError,
    assert_distinct_identity_kinds,
    parse_device_identity,
)
from operations.redaction import IDENTIFIER_KEYS


def identity() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "installationId": "0123456789abcdef0123456789abcdef",
        "deviceKeyId": "dev-0123456789abcdef",
        "keyStorage": "tpm-2.0",
        "locallyGenerated": True,
        "createdAt": "2026-07-29T12:00:00Z",
        "certificateSerial": None,
        "enrolmentIdentity": None,
        "rotationHistory": [],
    }


def attestation() -> dict[str, object]:
    return {
        "verifiedBootState": "verified",
        "secureBootState": "enabled",
        "osImageDigest": "sha256:" + "a" * 64,
        "updateChannel": "stable",
        "brokerVersion": "0.1.0",
        "recoveryAvailable": True,
        "encryptionState": "encrypted",
        "policyAgentState": "healthy",
    }


class DeviceIdentityTests(unittest.TestCase):
    def test_valid_identity_parses(self) -> None:
        parsed = parse_device_identity(identity())
        self.assertEqual(parsed.deviceKeyId, "dev-0123456789abcdef")
        self.assertTrue(parsed.locallyGenerated)

    def test_server_issued_identity_is_rejected(self) -> None:
        value = identity()
        value["locallyGenerated"] = False
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_mac_address_derivation_is_rejected(self) -> None:
        value = identity()
        value["derivedFrom"] = ["mac-address"]
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_every_prohibited_hardware_source_is_rejected(self) -> None:
        for source in ("motherboard-serial", "storage-serial", "cpu-serial", "advertising-id"):
            with self.subTest(source=source):
                value = identity()
                value["derivedFrom"] = [source]
                with self.assertRaises(IdentityError):
                    parse_device_identity(value)

    def test_short_installation_id_is_rejected(self) -> None:
        value = identity()
        value["installationId"] = "abc123"
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_software_key_storage_is_permitted(self) -> None:
        value = identity()
        value["keyStorage"] = "software-protected"
        self.assertEqual(parse_device_identity(value).keyStorage, "software-protected")

    def test_unknown_key_storage_is_rejected(self) -> None:
        value = identity()
        value["keyStorage"] = "vendor-cloud-escrow"
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_rotation_history_must_be_chronological(self) -> None:
        value = identity()
        value["rotationHistory"] = [
            {"rotatedAt": "2026-07-29T12:00:00Z", "reason": "scheduled", "previousKeyId": "dev-1111111111111111"},
            {"rotatedAt": "2026-01-01T12:00:00Z", "reason": "scheduled", "previousKeyId": "dev-2222222222222222"},
        ]
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_unknown_rotation_reason_is_rejected(self) -> None:
        value = identity()
        value["rotationHistory"] = [
            {"rotatedAt": "2026-07-29T12:00:00Z", "reason": "because", "previousKeyId": "dev-1111111111111111"}
        ]
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_unknown_field_is_rejected(self) -> None:
        value = identity()
        value["macAddress"] = "00:11:22:33:44:55"
        with self.assertRaises(IdentityError):
            parse_device_identity(value)

    def test_identity_kinds_stay_distinct(self) -> None:
        assert_distinct_identity_kinds({"device-identity": {"installationId": "x"}, "compliance-status": {}})

    def test_user_identity_inside_device_identity_is_rejected(self) -> None:
        with self.assertRaises(IdentityError):
            assert_distinct_identity_kinds({"device-identity": {"userId": "alice"}})

    def test_unknown_identity_kind_is_rejected(self) -> None:
        with self.assertRaises(IdentityError):
            assert_distinct_identity_kinds({"marketing-identity": {}})

    def test_four_identity_concepts_are_named(self) -> None:
        self.assertEqual(
            set(IDENTITY_KINDS),
            {"device-identity", "boot-attestation", "compliance-status", "user-identity"},
        )

    def test_existing_redactor_already_covers_device_identifiers(self) -> None:
        self.assertIn("deviceid", IDENTIFIER_KEYS)
        self.assertIn("serial", IDENTIFIER_KEYS)
        self.assertIn("macaddress", IDENTIFIER_KEYS)

    def test_forbidden_sources_include_every_named_prohibition(self) -> None:
        for source in ("macaddress", "motherboard-serial", "storage-serial", "cpu-serial", "advertising-id"):
            self.assertIn(source, FORBIDDEN_IDENTITY_SOURCES)


class AttestationTests(unittest.TestCase):
    def test_valid_attestation_parses(self) -> None:
        parsed = parse_attestation(attestation())
        self.assertEqual(parsed.updateChannel, "stable")

    def test_missing_field_is_rejected(self) -> None:
        value = attestation()
        del value["encryptionState"]
        with self.assertRaises(AttestationError):
            parse_attestation(value)

    def test_extra_field_is_rejected(self) -> None:
        value = attestation()
        value["installedApplications"] = ["org.example.App"]
        with self.assertRaises(AttestationError):
            parse_attestation(value)

    def test_prohibited_content_fields_are_rejected_by_name(self) -> None:
        for field in ("prompts", "memory", "browserHistory", "applicationUsage", "screenshot", "userId"):
            with self.subTest(field=field):
                value = attestation()
                value[field] = "anything"
                with self.assertRaises(AttestationError) as error:
                    parse_attestation(value)
                self.assertIn("prohibited attestation field", str(error.exception))

    def test_malformed_digest_is_rejected(self) -> None:
        value = attestation()
        value["osImageDigest"] = "sha256:short"
        with self.assertRaises(AttestationError):
            parse_attestation(value)

    def test_unprefixed_digest_is_rejected(self) -> None:
        value = attestation()
        value["osImageDigest"] = "a" * 64
        with self.assertRaises(AttestationError):
            parse_attestation(value)

    def test_disabled_secure_boot_is_reportable_honestly(self) -> None:
        value = attestation()
        value["secureBootState"] = "disabled"
        self.assertEqual(parse_attestation(value).secureBootState, "disabled")

    def test_unknown_states_are_reportable(self) -> None:
        value = attestation()
        value["verifiedBootState"] = "unknown"
        value["encryptionState"] = "unknown"
        self.assertEqual(parse_attestation(value).encryptionState, "unknown")

    def test_approved_field_set_is_exactly_eight_facts(self) -> None:
        self.assertEqual(len(APPROVED_FIELDS), 8)


if __name__ == "__main__":
    unittest.main()

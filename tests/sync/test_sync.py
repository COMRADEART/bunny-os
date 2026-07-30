from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import unittest

from sync.conflict import (
    DOMAIN_STRATEGIES,
    SENSITIVE_DOMAINS,
    ConflictError,
    compare_vectors,
    merge_vectors,
    resolve,
)
from sync.deletion import DELETION_SCOPES, DeletionError, assert_no_overclaim, describe_deletion
from sync.envelope import (
    SUPPORTED_ALGORITHMS,
    EnvelopeError,
    assert_no_version_rollback,
    parse_envelope,
)
from sync.keys import (
    KeyHierarchyError,
    parse_keyring,
    plan_collection_rotation,
    plan_device_addition,
    plan_device_revocation,
)
from sync.metadata import (
    MetadataClaimError,
    assert_no_zero_knowledge_claim,
    describe_visible_metadata,
    minimisation_report,
    visible_fields,
)
from sync.migration import MigrationError, apply_restore, preview_restore
from sync.selective import (
    SENSITIVE_DOMAINS as SELECTIVE_SENSITIVE,
    SelectiveSyncError,
    default_selection,
    parse_selection,
)

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
DEVICE_A = "dev-aaaaaaaaaaaaaaaa"
DEVICE_B = "dev-bbbbbbbbbbbbbbbb"


def nonce(size: int = 24) -> str:
    return base64.b64encode(bytes(range(size))).decode("ascii")


def envelope(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "envelopeVersion": 1,
        "algorithm": "XChaCha20-Poly1305",
        "collectionId": "col-memory",
        "objectId": "obj-" + "0" * 32,
        "objectVersion": 3,
        "keyReference": {"kind": "collection-key", "keyId": "ck-0123456789abcdef", "generation": 2},
        "nonce": nonce(),
        "ciphertextDigest": "a" * 64,
        "ciphertextBytes": 4096,
        "createdAt": "2026-07-29T12:00:00Z",
        "deviceKeyId": DEVICE_A,
    }
    value.update(overrides)
    return value


def keyring(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "rootKeyGeneration": 1,
        "devices": [
            {"deviceKeyId": DEVICE_A, "displayName": "Laptop", "state": "active",
             "addedAt": "2026-01-01T00:00:00Z", "revokedAt": None, "keyStorage": "tpm-2.0"},
            {"deviceKeyId": DEVICE_B, "displayName": "Desktop", "state": "active",
             "addedAt": "2026-02-01T00:00:00Z", "revokedAt": None, "keyStorage": "software-protected"},
        ],
        "collectionKeys": [
            {"collectionId": "col-memory", "kind": "memory", "keyId": "ck-0123456789abcdef",
             "generation": 2, "wrappedForDevices": [DEVICE_A, DEVICE_B]},
            {"collectionId": "col-workspace", "kind": "workspace", "keyId": "ck-fedcba9876543210",
             "generation": 1, "wrappedForDevices": [DEVICE_A]},
        ],
    }
    value.update(overrides)
    return value


class EnvelopeTests(unittest.TestCase):
    def test_valid_envelope_parses(self) -> None:
        parsed = parse_envelope(envelope())
        self.assertEqual(parsed.objectVersion, 3)

    def test_associated_data_binds_object_and_version(self) -> None:
        data = parse_envelope(envelope()).associated_data()
        self.assertEqual(
            set(data), {"envelopeVersion", "collectionId", "objectId", "objectVersion"}
        )

    def test_plaintext_description_is_refused(self) -> None:
        for field in ("title", "filename", "tags", "preview", "mimeType", "content"):
            with self.subTest(field=field):
                with self.assertRaises(EnvelopeError) as error:
                    parse_envelope(envelope(**{field: "notes.txt"}))
                self.assertIn("plaintext metadata", str(error.exception))

    def test_key_material_is_refused(self) -> None:
        for field in ("key", "wrappedKey", "passphrase", "rootKey", "recoveryPhrase"):
            with self.subTest(field=field):
                with self.assertRaises(EnvelopeError) as error:
                    parse_envelope(envelope(**{field: "AAAA"}))
                self.assertIn("never receives a plaintext decryption key", str(error.exception))

    def test_nested_key_material_is_refused(self) -> None:
        with self.assertRaises(EnvelopeError):
            parse_envelope(envelope(keyReference={
                "kind": "collection-key", "keyId": "ck-0123456789abcdef",
                "generation": 1, "keyMaterial": "AAAA",
            }))

    def test_unknown_algorithm_is_refused(self) -> None:
        with self.assertRaises(EnvelopeError) as error:
            parse_envelope(envelope(algorithm="rot13"))
        self.assertIn("reviewed AEAD", str(error.exception))

    def test_only_reviewed_aead_constructions_are_supported(self) -> None:
        self.assertEqual(set(SUPPORTED_ALGORITHMS), {"XChaCha20-Poly1305", "AES-256-GCM"})

    def test_nonce_length_must_match_algorithm(self) -> None:
        with self.assertRaises(EnvelopeError):
            parse_envelope(envelope(algorithm="AES-256-GCM", nonce=nonce(24)))
        parse_envelope(envelope(algorithm="AES-256-GCM", nonce=nonce(12)))

    def test_corrupted_digest_is_refused(self) -> None:
        with self.assertRaises(EnvelopeError):
            parse_envelope(envelope(ciphertextDigest="short"))

    def test_zero_length_ciphertext_is_refused(self) -> None:
        with self.assertRaises(EnvelopeError):
            parse_envelope(envelope(ciphertextBytes=0))

    def test_server_rollback_is_refused(self) -> None:
        stored = envelope(objectVersion=5)
        incoming = envelope(objectVersion=3)
        with self.assertRaises(EnvelopeError) as error:
            assert_no_version_rollback(stored, incoming)
        self.assertIn("server rollback refused", str(error.exception))

    def test_ciphertext_substitution_at_same_version_is_refused(self) -> None:
        stored = envelope(objectVersion=5, ciphertextDigest="a" * 64)
        incoming = envelope(objectVersion=5, ciphertextDigest="b" * 64)
        with self.assertRaises(EnvelopeError) as error:
            assert_no_version_rollback(stored, incoming)
        self.assertIn("substitution refused", str(error.exception))

    def test_forward_version_is_accepted(self) -> None:
        assert_no_version_rollback(envelope(objectVersion=3), envelope(objectVersion=4))

    def test_unsupported_envelope_version_is_refused(self) -> None:
        with self.assertRaises(EnvelopeError):
            parse_envelope(envelope(envelopeVersion=2))


class KeyHierarchyTests(unittest.TestCase):
    def test_valid_keyring_parses(self) -> None:
        parsed = parse_keyring(keyring())
        self.assertEqual(parsed["activeDeviceCount"], 2)

    def test_key_wrapped_for_revoked_device_is_refused(self) -> None:
        value = keyring()
        value["devices"][1]["state"] = "revoked"
        value["devices"][1]["revokedAt"] = "2026-03-01T00:00:00Z"
        with self.assertRaises(KeyHierarchyError) as error:
            parse_keyring(value)
        self.assertIn("revocation must rotate and rewrap", str(error.exception))

    def test_revocation_rotates_every_collection_the_device_could_read(self) -> None:
        plan = plan_device_revocation(keyring(), DEVICE_B)
        self.assertEqual(plan.rotateCollections, ("col-memory",))
        self.assertEqual(plan.rewrapForDevices, (DEVICE_A,))
        self.assertFalse(plan.rotateRootKey)

    def test_compromised_device_revocation_rotates_the_root_key(self) -> None:
        plan = plan_device_revocation(keyring(), DEVICE_B, suspected_compromise=True)
        self.assertTrue(plan.rotateRootKey)
        self.assertTrue(any("compromised device" in note for note in plan.notes))

    def test_revocation_states_that_downloaded_objects_cannot_be_retracted(self) -> None:
        plan = plan_device_revocation(keyring(), DEVICE_B)
        self.assertTrue(any("cannot be retracted" in note for note in plan.notes))

    def test_revoking_the_last_device_is_refused(self) -> None:
        value = keyring()
        value["devices"] = [value["devices"][0]]
        value["collectionKeys"] = [
            {"collectionId": "col-memory", "kind": "memory", "keyId": "ck-0123456789abcdef",
             "generation": 2, "wrappedForDevices": [DEVICE_A]}
        ]
        with self.assertRaises(KeyHierarchyError) as error:
            plan_device_revocation(value, DEVICE_A)
        self.assertIn("no active device", str(error.exception))

    def test_double_revocation_is_refused(self) -> None:
        value = keyring()
        value["devices"][1]["state"] = "revoked"
        value["devices"][1]["revokedAt"] = "2026-03-01T00:00:00Z"
        value["collectionKeys"][0]["wrappedForDevices"] = [DEVICE_A]
        with self.assertRaises(KeyHierarchyError):
            plan_device_revocation(value, DEVICE_B)

    def test_device_addition_rewraps_without_rotating(self) -> None:
        plan = plan_device_addition(keyring(), "dev-cccccccccccccccc", collections=["col-memory"])
        self.assertEqual(plan.rotateCollections, ())
        self.assertIn("dev-cccccccccccccccc", plan.rewrapForDevices)

    def test_device_addition_states_backfill_access_honestly(self) -> None:
        plan = plan_device_addition(keyring(), "dev-cccccccccccccccc", collections=["col-memory"])
        self.assertTrue(any("existing objects" in note for note in plan.notes))

    def test_device_addition_requires_a_collection(self) -> None:
        with self.assertRaises(KeyHierarchyError):
            plan_device_addition(keyring(), "dev-cccccccccccccccc", collections=[])

    def test_collection_rotation_advances_the_generation(self) -> None:
        plan = plan_collection_rotation(keyring(), "col-memory")
        self.assertTrue(any("Generation advances from 2 to 3" in note for note in plan.notes))

    def test_unknown_collection_rotation_is_refused(self) -> None:
        with self.assertRaises(KeyHierarchyError):
            plan_collection_rotation(keyring(), "col-nonexistent")

    def test_key_wrapped_for_unknown_device_is_refused(self) -> None:
        value = keyring()
        value["collectionKeys"][0]["wrappedForDevices"] = ["dev-9999999999999999"]
        with self.assertRaises(KeyHierarchyError):
            parse_keyring(value)


class ConflictTests(unittest.TestCase):
    def test_identical_vectors(self) -> None:
        self.assertEqual(compare_vectors({DEVICE_A: 1}, {DEVICE_A: 1}), "identical")

    def test_descendant_and_ancestor(self) -> None:
        self.assertEqual(compare_vectors({DEVICE_A: 2}, {DEVICE_A: 1}), "descendant")
        self.assertEqual(compare_vectors({DEVICE_A: 1}, {DEVICE_A: 2}), "ancestor")

    def test_concurrent_offline_edits(self) -> None:
        self.assertEqual(compare_vectors({DEVICE_A: 2, DEVICE_B: 1}, {DEVICE_A: 1, DEVICE_B: 2}), "concurrent")

    def test_merge_takes_element_wise_maximum(self) -> None:
        self.assertEqual(merge_vectors({DEVICE_A: 2, DEVICE_B: 1}, {DEVICE_A: 1, DEVICE_B: 3}),
                         {DEVICE_A: 2, DEVICE_B: 3})

    def test_deleted_memory_is_never_silently_resurrected(self) -> None:
        decision = resolve(
            {"domain": "memory", "vector": {DEVICE_A: 3, DEVICE_B: 1}, "deleted": False},
            {"domain": "memory", "vector": {DEVICE_A: 1, DEVICE_B: 3}, "deleted": True},
        )
        self.assertEqual(decision.outcome, "keep-deletion-and-queue-review")
        self.assertTrue(decision.requiresUserReview)
        self.assertTrue(decision.tombstonePreserved)

    def test_newer_edit_does_not_override_a_memory_deletion(self) -> None:
        decision = resolve(
            {"domain": "memory", "vector": {DEVICE_A: 5}, "deleted": False},
            {"domain": "memory", "vector": {DEVICE_A: 3}, "deleted": True},
        )
        self.assertTrue(decision.tombstonePreserved)
        self.assertTrue(decision.requiresUserReview)

    def test_file_conflict_creates_a_conflict_copy(self) -> None:
        decision = resolve(
            {"domain": "files", "vector": {DEVICE_A: 2, DEVICE_B: 1}},
            {"domain": "files", "vector": {DEVICE_A: 1, DEVICE_B: 2}},
        )
        self.assertTrue(decision.conflictCopyCreated)
        self.assertEqual(decision.outcome, "create-conflict-copy")

    def test_settings_merge_per_field(self) -> None:
        decision = resolve(
            {"domain": "settings", "vector": {DEVICE_A: 2, DEVICE_B: 1}},
            {"domain": "settings", "vector": {DEVICE_A: 1, DEVICE_B: 2}},
        )
        self.assertEqual(decision.outcome, "merge-per-field")

    def test_completed_task_stays_completed(self) -> None:
        decision = resolve(
            {"domain": "tasks", "vector": {DEVICE_A: 2, DEVICE_B: 1}, "completed": True},
            {"domain": "tasks", "vector": {DEVICE_A: 1, DEVICE_B: 2}, "completed": False},
        )
        self.assertEqual(decision.outcome, "mark-completed")

    def test_plan_conflict_requires_manual_review(self) -> None:
        decision = resolve(
            {"domain": "plans", "vector": {DEVICE_A: 2, DEVICE_B: 1}},
            {"domain": "plans", "vector": {DEVICE_A: 1, DEVICE_B: 2}},
        )
        self.assertTrue(decision.requiresUserReview)

    def test_non_sensitive_deletion_propagates_without_review(self) -> None:
        decision = resolve(
            {"domain": "bookmarks", "vector": {DEVICE_A: 2, DEVICE_B: 1}, "deleted": True},
            {"domain": "bookmarks", "vector": {DEVICE_A: 1, DEVICE_B: 2}, "deleted": False},
        )
        self.assertEqual(decision.outcome, "keep-deletion")
        self.assertFalse(decision.requiresUserReview)

    def test_older_change_is_discarded(self) -> None:
        decision = resolve(
            {"domain": "settings", "vector": {DEVICE_A: 1}},
            {"domain": "settings", "vector": {DEVICE_A: 3}},
        )
        self.assertEqual(decision.outcome, "keep-stored")

    def test_cross_domain_resolution_is_refused(self) -> None:
        with self.assertRaises(ConflictError):
            resolve({"domain": "files", "vector": {DEVICE_A: 1}}, {"domain": "settings", "vector": {DEVICE_A: 1}})

    def test_memory_domains_are_marked_sensitive(self) -> None:
        self.assertIn("memory", SENSITIVE_DOMAINS)
        self.assertIn("memory", DOMAIN_STRATEGIES)


class SelectiveSyncTests(unittest.TestCase):
    def test_nothing_syncs_by_default(self) -> None:
        self.assertEqual(default_selection()["enabledDomains"], [])

    def test_sensitive_domain_requires_acknowledgement(self) -> None:
        with self.assertRaises(SelectiveSyncError) as error:
            parse_selection({
                "schemaVersion": 1, "enabledDomains": ["approved-memories"],
                "devices": [DEVICE_A], "acknowledgedSensitiveDomains": [],
            })
        self.assertIn("explicit acknowledgement", str(error.exception))

    def test_acknowledged_sensitive_domain_is_accepted(self) -> None:
        parsed = parse_selection({
            "schemaVersion": 1, "enabledDomains": ["approved-memories"],
            "devices": [DEVICE_A], "acknowledgedSensitiveDomains": ["approved-memories"],
        })
        self.assertIn("approved-memories", parsed.enabledDomains)

    def test_non_sensitive_domain_needs_no_acknowledgement(self) -> None:
        parse_selection({
            "schemaVersion": 1, "enabledDomains": ["bookmarks"],
            "devices": [DEVICE_A], "acknowledgedSensitiveDomains": [],
        })

    def test_enabling_a_domain_requires_a_device(self) -> None:
        with self.assertRaises(SelectiveSyncError):
            parse_selection({
                "schemaVersion": 1, "enabledDomains": ["bookmarks"],
                "devices": [], "acknowledgedSensitiveDomains": [],
            })

    def test_unknown_domain_is_refused(self) -> None:
        with self.assertRaises(SelectiveSyncError):
            parse_selection({
                "schemaVersion": 1, "enabledDomains": ["everything"],
                "devices": [DEVICE_A], "acknowledgedSensitiveDomains": [],
            })

    def test_memory_and_files_are_sensitive(self) -> None:
        for domain in ("approved-memories", "approved-files", "encrypted-backups", "conversation-metadata"):
            self.assertIn(domain, SELECTIVE_SENSITIVE)


class MetadataTests(unittest.TestCase):
    def test_visible_metadata_is_documented(self) -> None:
        fields = visible_fields()
        for expected in ("accountIdentifier", "deviceKeyId", "encryptedObjectSize", "uploadTimestamp"):
            self.assertIn(expected, fields)

    def test_content_is_not_visible(self) -> None:
        rows = {item["field"]: item["visible"] for item in describe_visible_metadata()}
        self.assertEqual(rows["objectContent"], "no")
        self.assertEqual(rows["bunnyPromptsAndMemories"], "no")

    def test_zero_knowledge_claim_is_refused(self) -> None:
        for claim in ("zero knowledge", "zero-knowledge encryption", "we know nothing", "metadata-free"):
            with self.subTest(claim=claim):
                with self.assertRaises(MetadataClaimError):
                    assert_no_zero_knowledge_claim(f"Bunny sync offers {claim}.")

    def test_accurate_description_is_accepted(self) -> None:
        assert_no_zero_knowledge_claim(
            "Your content is end-to-end encrypted. Operational metadata such as object size and "
            "upload time remains visible to the service."
        )

    def test_excess_stored_field_breaks_minimisation(self) -> None:
        report = minimisation_report([*visible_fields(), "ipAddressHistory"])
        self.assertFalse(report["minimised"])
        self.assertIn("ipAddressHistory", report["excessFields"])

    def test_declared_set_is_minimised(self) -> None:
        self.assertTrue(minimisation_report(visible_fields())["minimised"])


class DeletionTests(unittest.TestCase):
    def test_six_scopes_are_defined(self) -> None:
        self.assertEqual(len(DELETION_SCOPES), 6)

    def test_local_deletion_does_not_remove_server_copy(self) -> None:
        effect = describe_deletion("local-deletion")
        self.assertFalse(effect.removesServerCiphertext)

    def test_server_deletion_discloses_backup_retention(self) -> None:
        effect = describe_deletion("server-encrypted-object-deletion")
        self.assertGreater(effect.maximumBackupPersistenceDays, 0)
        self.assertTrue(any("not claimed" in item for item in effect.caveats))

    def test_account_deletion_is_irreversible_and_bounded(self) -> None:
        effect = describe_deletion("account-deletion")
        self.assertTrue(effect.irreversible)
        self.assertGreater(effect.maximumBackupPersistenceDays, 0)

    def test_organisation_removal_does_not_touch_personal_data(self) -> None:
        effect = describe_deletion("organisation-data-removal")
        self.assertTrue(any("Personal accounts" in item for item in effect.caveats))

    def test_tombstone_propagation_is_recorded(self) -> None:
        self.assertTrue(describe_deletion("all-synced-devices").tombstonePropagated)

    def test_overclaiming_deletion_is_refused(self) -> None:
        with self.assertRaises(DeletionError):
            assert_no_overclaim("server-encrypted-object-deletion", "Your data is completely gone.")

    def test_claiming_server_deletion_for_local_scope_is_refused(self) -> None:
        with self.assertRaises(DeletionError):
            assert_no_overclaim("local-deletion", "This item is deleted from the server.")

    def test_accurate_statement_is_accepted(self) -> None:
        assert_no_overclaim("local-deletion", "Removed from this device. Other devices keep their copy.")

    def test_unknown_scope_is_refused(self) -> None:
        with self.assertRaises(DeletionError):
            describe_deletion("delete-everything-everywhere")


class MigrationTests(unittest.TestCase):
    def request(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "method": "encrypted-backup-file",
            "mode": "selective",
            "sourceOsVersion": "1.0.0",
            "destinationOsVersion": "1.0.0",
            "sourceCollections": ["col-memory", "col-workspace"],
            "destinationCollections": ["col-memory"],
            "backupSignatureVerified": True,
        }
        value.update(overrides)
        return value

    def test_preview_reports_what_would_change(self) -> None:
        preview = preview_restore(self.request())
        self.assertEqual(preview.wouldReplace, ("col-memory",))
        self.assertEqual(preview.wouldAdd, ("col-workspace",))
        self.assertTrue(preview.acknowledgementRequired)

    def test_unverified_backup_is_refused(self) -> None:
        preview = preview_restore(self.request(backupSignatureVerified=False))
        self.assertFalse(preview.compatible)
        self.assertTrue(any("not verified" in item for item in preview.blockers))

    def test_downgrade_restore_is_refused(self) -> None:
        preview = preview_restore(self.request(sourceOsVersion="1.2.0", destinationOsVersion="1.0.0"))
        self.assertFalse(preview.compatible)

    def test_major_version_change_needs_a_reviewed_route(self) -> None:
        preview = preview_restore(self.request(sourceOsVersion="1.0.0", destinationOsVersion="2.0.0"))
        self.assertFalse(preview.compatible)

    def test_restore_never_overwrites_silently(self) -> None:
        preview = preview_restore(self.request())
        with self.assertRaises(MigrationError) as error:
            apply_restore(preview, acknowledgedReplacements=[])
        self.assertIn("never overwrites the destination silently", str(error.exception))

    def test_acknowledged_restore_applies(self) -> None:
        preview = preview_restore(self.request())
        result = apply_restore(preview, acknowledgedReplacements=["col-memory"])
        self.assertTrue(result["applied"])
        self.assertEqual(result["replaced"], ["col-memory"])

    def test_preview_mode_cannot_be_applied(self) -> None:
        preview = preview_restore(self.request(mode="preview"))
        with self.assertRaises(MigrationError):
            apply_restore(preview, acknowledgedReplacements=["col-memory"])

    def test_direct_transfer_requires_authenticated_source(self) -> None:
        preview = preview_restore(self.request(method="direct-device-transfer"))
        self.assertFalse(preview.compatible)


if __name__ == "__main__":
    unittest.main()

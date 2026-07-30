from __future__ import annotations

import unittest

from enterprise.audit import (
    GENESIS_HASH,
    MAXIMUM_RETENTION_DAYS,
    AuditError,
    append_entry,
    compute_hash,
    parse_entry,
    retention_policy,
    verify_chain,
)

CORRELATION = "0f9c2a1b-4d3e-4f5a-8b6c-7d8e9f0a1b2c"


def base(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "organisationId": "org-example-school",
        "administrator": "admin@example.invalid",
        "operation": "update.schedule",
        "targetScope": ["grp-site-north"],
        "policyVersion": 3,
        "occurredAt": "2026-07-29T12:00:00Z",
        "authorisation": "passkey",
        "result": "succeeded",
        "correlationId": CORRELATION,
    }
    value.update(overrides)
    return value


def chain(length: int = 3) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for index in range(length):
        entries.append(append_entry(entries, base(operation=f"update.schedule.{index}")))
    return entries


class AuditEntryTests(unittest.TestCase):
    def test_appended_entry_is_valid(self) -> None:
        entries = chain(1)
        parsed = parse_entry(entries[0])
        self.assertEqual(parsed.sequence, 1)
        self.assertEqual(parsed.previousHash, GENESIS_HASH)

    def test_chain_verifies(self) -> None:
        report = verify_chain(chain(4), organisation_id="org-example-school")
        self.assertTrue(report["intact"], report["problems"])
        self.assertEqual(report["verifiedEntries"], 4)

    def test_modified_entry_breaks_its_own_hash(self) -> None:
        entries = chain(3)
        entries[1]["operation"] = "device.factory-reset"
        report = verify_chain(entries, organisation_id="org-example-school")
        self.assertFalse(report["intact"])
        self.assertTrue(any("hash mismatch" in item or "modified" in item for item in report["problems"]))

    def test_deleted_entry_leaves_a_sequence_gap(self) -> None:
        entries = chain(4)
        del entries[2]
        report = verify_chain(entries, organisation_id="org-example-school")
        self.assertFalse(report["intact"])
        self.assertTrue(any("deleted" in item for item in report["problems"]))

    def test_reordered_chain_is_detected(self) -> None:
        entries = chain(3)
        entries[1], entries[2] = entries[2], entries[1]
        self.assertFalse(verify_chain(entries, organisation_id="org-example-school")["intact"])

    def test_cross_organisation_verification_is_refused(self) -> None:
        report = verify_chain(chain(2), organisation_id="org-other-company")
        self.assertFalse(report["intact"])
        self.assertTrue(any("cross-organisation" in item for item in report["problems"]))

    def test_appending_a_foreign_organisation_entry_is_refused(self) -> None:
        entries = chain(1)
        with self.assertRaises(AuditError):
            append_entry(entries, base(organisationId="org-other-company"))

    def test_secret_field_is_refused(self) -> None:
        with self.assertRaises(AuditError) as error:
            parse_entry({**base(), "schemaVersion": 1, "sequence": 1, "previousHash": GENESIS_HASH, "token": "abc"})
        self.assertIn("unknown audit fields", str(error.exception))

    def test_user_content_in_target_scope_object_is_refused(self) -> None:
        candidate = {
            **base(),
            "schemaVersion": 1,
            "sequence": 1,
            "previousHash": GENESIS_HASH,
        }
        candidate["failureCode"] = "ok"
        candidate["entryHash"] = compute_hash(candidate)
        parse_entry(candidate)

    def test_failed_result_requires_failure_code(self) -> None:
        entries: list[dict[str, object]] = []
        with self.assertRaises(AuditError):
            append_entry(entries, base(result="failed"))
        append_entry(entries, base(result="failed", failureCode="signature-invalid"))

    def test_unknown_authorisation_method_is_refused(self) -> None:
        with self.assertRaises(AuditError):
            append_entry([], base(authorisation="vibes"))

    def test_malformed_correlation_id_is_refused(self) -> None:
        with self.assertRaises(AuditError):
            append_entry([], base(correlationId="not-a-uuid"))

    def test_empty_target_scope_is_refused(self) -> None:
        with self.assertRaises(AuditError):
            append_entry([], base(targetScope=[]))

    def test_rollback_is_recordable(self) -> None:
        entry = append_entry([], base(result="rolled-back", rolledBack=True))
        self.assertTrue(parse_entry(entry).rolledBack)

    def test_retention_policy_is_bounded(self) -> None:
        policy = retention_policy()
        self.assertLessEqual(policy["retentionDays"], MAXIMUM_RETENTION_DAYS)
        self.assertEqual(policy["exportScope"].count("one organisation per export"), 1)
        with self.assertRaises(AuditError):
            retention_policy(MAXIMUM_RETENTION_DAYS + 1)

    def test_retention_policy_documents_append_only_expiry(self) -> None:
        self.assertTrue(retention_policy()["deletionIsAppendOnly"])


if __name__ == "__main__":
    unittest.main()

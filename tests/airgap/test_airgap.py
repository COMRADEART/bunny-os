from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from enterprise.airgap import (
    BUNDLE_KINDS,
    WORKFLOW_STAGES,
    AirGapError,
    describe_workflow,
    next_stage,
    parse_bundle,
)

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def stamp(days: int = 0) -> str:
    return (NOW + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def bundle(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "bundleId": "bnd-0123456789abcdef",
        "kind": "policy-bundle",
        "organisationId": "org-example-lab",
        "sequence": 5,
        "createdAt": stamp(-1),
        "expiresAt": stamp(29),
        "contentDigest": "a" * 64,
        "signatureKeyId": "fleet-example-lab",
        "signatureVerified": True,
        "sizeBytes": 65536,
    }
    value.update(overrides)
    return value


class OfflineBundleTests(unittest.TestCase):
    def test_valid_bundle_parses(self) -> None:
        parsed = parse_bundle(bundle(), now=NOW, last_applied_sequence=4)
        self.assertEqual(parsed.sequence, 5)

    def test_unsigned_bundle_is_refused(self) -> None:
        with self.assertRaises(AirGapError) as error:
            parse_bundle(bundle(signatureVerified=False), now=NOW, last_applied_sequence=4)
        self.assertIn("no unsigned or 'trusted local' import path", str(error.exception))

    def test_every_bundle_kind_must_be_signed(self) -> None:
        for kind in BUNDLE_KINDS:
            with self.subTest(kind=kind):
                with self.assertRaises(AirGapError):
                    parse_bundle(
                        bundle(kind=kind, signatureVerified=False), now=NOW, last_applied_sequence=4
                    )

    def test_stale_policy_replay_is_refused(self) -> None:
        with self.assertRaises(AirGapError) as error:
            parse_bundle(bundle(sequence=3), now=NOW, last_applied_sequence=5)
        self.assertIn("stale policy replay refused", str(error.exception))

    def test_equal_sequence_replay_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            parse_bundle(bundle(sequence=5), now=NOW, last_applied_sequence=5)

    def test_expired_bundle_is_refused(self) -> None:
        with self.assertRaises(AirGapError) as error:
            parse_bundle(bundle(createdAt=stamp(-60), expiresAt=stamp(-30)), now=NOW, last_applied_sequence=4)
        self.assertIn("expired", str(error.exception))

    def test_overlong_bundle_lifetime_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            parse_bundle(bundle(createdAt=stamp(-1), expiresAt=stamp(200)), now=NOW, last_applied_sequence=4)

    def test_wrong_key_namespace_is_refused(self) -> None:
        for key_id in ("oem-example", "bunny-os-release", "sync-example"):
            with self.subTest(key_id=key_id):
                with self.assertRaises(AirGapError) as error:
                    parse_bundle(bundle(signatureKeyId=key_id), now=NOW, last_applied_sequence=4)
                self.assertIn("fleet-", str(error.exception))

    def test_revoked_key_is_refused(self) -> None:
        with self.assertRaises(AirGapError) as error:
            parse_bundle(
                bundle(), now=NOW, last_applied_sequence=4,
                revoked_key_ids=frozenset({"fleet-example-lab"}),
            )
        self.assertIn("revoked", str(error.exception))

    def test_malformed_digest_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            parse_bundle(bundle(contentDigest="nope"), now=NOW, last_applied_sequence=4)

    def test_missing_field_is_refused(self) -> None:
        value = bundle()
        del value["contentDigest"]
        with self.assertRaises(AirGapError):
            parse_bundle(value, now=NOW, last_applied_sequence=4)

    def test_extra_field_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            parse_bundle(bundle(trustedLocalOverride=True), now=NOW, last_applied_sequence=4)

    def test_zero_size_bundle_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            parse_bundle(bundle(sizeBytes=0), now=NOW, last_applied_sequence=4)


class WorkflowTests(unittest.TestCase):
    def test_workflow_proceeds_in_order(self) -> None:
        stage = WORKFLOW_STAGES[0]
        for requested in WORKFLOW_STAGES[1:]:
            stage = next_stage(stage, requested)
        self.assertEqual(stage, "status-imported")

    def test_skipping_verification_is_refused(self) -> None:
        with self.assertRaises(AirGapError) as error:
            next_stage("transported", "applied")
        self.assertIn("in order", str(error.exception))

    def test_applying_before_export_is_refused(self) -> None:
        with self.assertRaises(AirGapError):
            next_stage("exported", "applied")

    def test_six_stages_are_documented(self) -> None:
        described = [row["stage"] for row in describe_workflow()]
        self.assertEqual(described, list(WORKFLOW_STAGES))

    def test_workflow_requires_no_cloud_connection(self) -> None:
        text = " ".join(row["action"] for row in describe_workflow()).casefold()
        self.assertIn("removable media", text)
        self.assertNotIn("cloud", text)

    def test_verification_stage_names_every_check(self) -> None:
        verify = next(row for row in describe_workflow() if row["stage"] == "verified")
        for check in ("signature", "digest", "sequence", "expiry"):
            self.assertIn(check, verify["action"])


if __name__ == "__main__":
    unittest.main()

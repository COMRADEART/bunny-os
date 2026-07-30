"""Signing role separation and the development/production wall.

Two of the fourteen mandated adversarial cases live here: a development key
presented as a production key, and a key from one signing role presented for
another.
"""

from __future__ import annotations

import datetime as _datetime
import unittest

from release.signing import (
    DEVELOPMENT_PREFIX,
    DRILL_CHECKS,
    ROLE_AUTHORITY,
    SIGNING_ROLES,
    TWO_PERSON_ROLES,
    SigningError,
    evaluate_drill,
    parse_key_id,
    parse_key_record,
    require_production_key,
    rotation_overlap,
    usable_key,
    validate_namespaces,
)

NOW = _datetime.datetime(2026, 7, 29, tzinfo=_datetime.timezone.utc)


def key_record(**overrides):
    base = {
        "keyId": "bunny-os-release-001",
        "state": "active",
        "publishedAt": "2026-01-01T00:00:00Z",
        "expiresAt": "2027-01-01T00:00:00Z",
        "publicKeyReference": "build/keys/bunny-os-release-001.pub.pem",
        "storage": "hardware-token",
        "twoPersonApproval": True,
    }
    base.update(overrides)
    return base


class NamespaceTests(unittest.TestCase):
    def test_seven_roles_exist(self):
        self.assertEqual(len(SIGNING_ROLES), 7)
        for name in (
            "osRelease",
            "updateMetadata",
            "recoveryImage",
            "applicationCatalogue",
            "oemProfile",
            "fleetPolicy",
            "syncServiceIdentity",
        ):
            self.assertIn(name, SIGNING_ROLES)

    def test_every_role_declares_its_authority(self):
        self.assertEqual(set(ROLE_AUTHORITY), set(SIGNING_ROLES))

    def test_no_namespace_is_a_prefix_of_another(self):
        validate_namespaces()

    def test_overlapping_namespaces_are_refused(self):
        with self.assertRaises(SigningError) as caught:
            validate_namespaces({"a": "update-", "b": "update-meta-"})
        self.assertIn("would not be separable", str(caught.exception))

    def test_a_role_may_not_claim_the_development_prefix(self):
        with self.assertRaises(SigningError):
            validate_namespaces({"a": "dev-thing-"})

    def test_key_outside_every_namespace_is_refused(self):
        with self.assertRaises(SigningError) as caught:
            parse_key_id("random-key-1")
        self.assertIn("in no signing namespace", str(caught.exception))


class DevelopmentProductionWallTests(unittest.TestCase):
    """Adversarial: a development key used as a production key."""

    def test_development_prefix_is_detected_for_every_role(self):
        for role, prefix in SIGNING_ROLES.items():
            identity = parse_key_id(f"{DEVELOPMENT_PREFIX}{prefix}drill1")
            self.assertEqual(identity.role, role)
            self.assertEqual(identity.keyClass, "development")
            self.assertTrue(identity.isDevelopment)

    def test_production_path_refuses_a_development_key(self):
        for prefix in SIGNING_ROLES.values():
            identity = parse_key_id(f"{DEVELOPMENT_PREFIX}{prefix}drill1")
            with self.assertRaises(SigningError) as caught:
                require_production_key(identity)
            self.assertIn("can never satisfy a production release gate", str(caught.exception))

    def test_production_path_accepts_a_production_key(self):
        identity = parse_key_id("bunny-os-release-001")
        self.assertIs(require_production_key(identity), identity)

    def test_usable_key_refuses_a_development_key_on_a_production_path(self):
        record = parse_key_record(
            key_record(keyId="dev-bunny-os-release-001", storage="development-directory", twoPersonApproval=False)
        )
        usable, reason = usable_key(record, role="osRelease", now=NOW)
        self.assertFalse(usable)
        self.assertIn("development key", reason)

    def test_development_key_is_usable_when_production_is_not_required(self):
        record = parse_key_record(
            key_record(keyId="dev-bunny-os-release-001", storage="development-directory", twoPersonApproval=False)
        )
        usable, _ = usable_key(record, role="osRelease", now=NOW, requireProduction=False)
        self.assertTrue(usable)


class WrongRoleTests(unittest.TestCase):
    """Adversarial: a wrong signing-role key."""

    def test_presenting_a_recovery_key_for_the_release_role_is_refused(self):
        with self.assertRaises(SigningError) as caught:
            parse_key_id("recovery-001", expectedRole="osRelease")
        self.assertIn("not interchangeable", str(caught.exception))

    def test_presenting_a_fleet_key_for_the_update_role_is_refused(self):
        with self.assertRaises(SigningError):
            parse_key_id("fleet-001", expectedRole="updateMetadata")

    def test_usable_key_refuses_a_key_from_another_authority(self):
        record = parse_key_record(key_record())
        usable, reason = usable_key(record, role="fleetPolicy", now=NOW)
        self.assertFalse(usable)
        self.assertIn("not fleetPolicy", reason)

    def test_matching_role_is_accepted(self):
        identity = parse_key_id("oem-acme-001", expectedRole="oemProfile")
        self.assertEqual(identity.role, "oemProfile")


class KeyLifecycleTests(unittest.TestCase):
    def test_production_key_requires_protected_storage(self):
        with self.assertRaises(SigningError) as caught:
            parse_key_record(key_record(storage="development-directory"))
        self.assertIn("hardware token", str(caught.exception))

    def test_two_person_roles_require_two_person_approval(self):
        for role in sorted(TWO_PERSON_ROLES):
            prefix = SIGNING_ROLES[role]
            with self.assertRaises(SigningError) as caught:
                parse_key_record(key_record(keyId=f"{prefix}001", twoPersonApproval=False))
            self.assertIn("two-person approval", str(caught.exception))

    def test_expired_key_is_not_usable(self):
        record = parse_key_record(key_record(expiresAt="2026-01-02T00:00:00Z"))
        usable, reason = usable_key(record, role="osRelease", now=NOW)
        self.assertFalse(usable)
        self.assertIn("expired", reason)

    def test_unpublished_key_is_not_usable(self):
        record = parse_key_record(key_record(publishedAt="2026-12-01T00:00:00Z", expiresAt="2027-12-01T00:00:00Z"))
        usable, reason = usable_key(record, role="osRelease", now=NOW)
        self.assertFalse(usable)
        self.assertIn("not yet published", reason)

    def test_revoked_key_is_not_usable(self):
        record = parse_key_record(key_record())
        usable, reason = usable_key(record, role="osRelease", now=NOW, revokedKeyIds=[record.keyId])
        self.assertFalse(usable)
        self.assertIn("revoked", reason)

    def test_rotation_requires_an_overlapping_trust_period(self):
        previous = parse_key_record(key_record(keyId="bunny-os-release-001"))
        gapped = parse_key_record(
            key_record(
                keyId="bunny-os-release-002",
                publishedAt="2027-06-01T00:00:00Z",
                expiresAt="2028-06-01T00:00:00Z",
                supersedes="bunny-os-release-001",
            )
        )
        ok, reason = rotation_overlap(previous, gapped)
        self.assertFalse(ok)
        self.assertIn("no overlapping trust period", reason)

    def test_overlapping_rotation_is_accepted(self):
        previous = parse_key_record(key_record(keyId="bunny-os-release-001"))
        replacement = parse_key_record(
            key_record(
                keyId="bunny-os-release-002",
                publishedAt="2026-10-01T00:00:00Z",
                expiresAt="2028-01-01T00:00:00Z",
                supersedes="bunny-os-release-001",
            )
        )
        ok, _ = rotation_overlap(previous, replacement)
        self.assertTrue(ok)

    def test_rotation_across_authorities_is_refused(self):
        previous = parse_key_record(key_record(keyId="bunny-os-release-001"))
        other = parse_key_record(
            key_record(keyId="recovery-002", supersedes="bunny-os-release-001")
        )
        ok, reason = rotation_overlap(previous, other)
        self.assertFalse(ok)
        self.assertIn("within one signing authority", reason)

    def test_replacement_must_declare_what_it_supersedes(self):
        previous = parse_key_record(key_record(keyId="bunny-os-release-001"))
        replacement = parse_key_record(key_record(keyId="bunny-os-release-002"))
        ok, reason = rotation_overlap(previous, replacement)
        self.assertFalse(ok)
        self.assertIn("does not declare", reason)


class DrillEvaluationTests(unittest.TestCase):
    def test_nine_checks_are_required(self):
        self.assertEqual(len(DRILL_CHECKS), 9)

    def test_complete_passing_drill_passes(self):
        result = evaluate_drill(
            [{"check": name, "outcome": "PASS", "detail": "d", "command": "c"} for name in DRILL_CHECKS]
        )
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["keyClass"], "development")

    def test_missing_check_fails(self):
        result = evaluate_drill(
            [{"check": name, "outcome": "PASS"} for name in DRILL_CHECKS[:-1]]
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(DRILL_CHECKS[-1], result["missingChecks"])

    def test_a_rejection_check_that_did_not_reject_fails_the_drill(self):
        rows = [{"check": name, "outcome": "PASS"} for name in DRILL_CHECKS]
        rows[DRILL_CHECKS.index("corrupted-artifact-rejection")]["outcome"] = "FAIL"
        result = evaluate_drill(rows)
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("corrupted-artifact-rejection", result["failingChecks"])

    def test_unknown_check_is_refused(self):
        with self.assertRaises(SigningError):
            evaluate_drill([{"check": "not-a-check", "outcome": "PASS"}])


if __name__ == "__main__":
    unittest.main()

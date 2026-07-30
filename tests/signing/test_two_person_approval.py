# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Two-person approval, and the two ways one person defeats it.

The mandated adversarial cases exercised here:

* a development signer used for production (case 13)
* one person supplying two signer identities (case 14)
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from release.signing import (
    KEY_STATES,
    TWO_PERSON_DRILL_CHECKS,
    TWO_PERSON_ROLES,
    SigningError,
    evaluate_two_person_approval,
    evaluate_two_person_drill,
    parse_key_id,
    parse_key_record,
    parse_signer_approval,
    require_production_key,
)

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "a" * 64


def approval(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "signerId": "signer-a",
        "keyId": "dev-bunny-os-release-signer-a",
        "operatorFingerprint": "1" * 32,
        "operationLogReference": "/var/log/signer-a.log",
        "artifactDigest": DIGEST,
        "decision": "approve",
        "approvedAt": "2026-07-30T12:00:00Z",
    }
    record.update(overrides)
    return record


def other(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "signerId": "signer-b",
        "keyId": "dev-bunny-os-release-signer-b",
        "operatorFingerprint": "2" * 32,
        "operationLogReference": "/var/log/signer-b.log",
    }
    defaults.update(overrides)
    return approval(**defaults)


def parsed(record: dict[str, object]):
    return parse_signer_approval(record, expectedRole="osRelease")


class DevelopmentKeyNeverSatisfiesProduction(unittest.TestCase):
    """Adversarial case 13."""

    def test_a_development_key_is_refused_on_a_production_path(self) -> None:
        with self.assertRaises(SigningError) as raised:
            require_production_key(parse_key_id("dev-bunny-os-release-signer-a"))
        self.assertIn("can never satisfy a production release gate", str(raised.exception))

    def test_a_two_person_approval_with_development_keys_is_not_production_capable(self) -> None:
        verdict = evaluate_two_person_approval(parsed(approval()), parsed(other()), role="osRelease")
        self.assertTrue(verdict["authorised"])
        self.assertFalse(verdict["productionCapable"])
        self.assertEqual(verdict["keyClasses"], ["development"])

    def test_the_drill_refuses_a_production_key(self) -> None:
        with self.assertRaises(SigningError) as raised:
            evaluate_two_person_drill(
                {
                    "schemaVersion": 1,
                    "role": "osRelease",
                    "checks": [
                        {"check": name, "outcome": "PASS"} for name in TWO_PERSON_DRILL_CHECKS
                    ],
                    "signers": [
                        approval(keyId="bunny-os-release-real-a"),
                        other(keyId="bunny-os-release-real-b"),
                    ],
                }
            )
        self.assertIn("may not use a production key", str(raised.exception))

    def test_the_drill_never_claims_to_satisfy_the_production_requirement(self) -> None:
        result = evaluate_two_person_drill(
            {
                "schemaVersion": 1,
                "role": "osRelease",
                "checks": [{"check": name, "outcome": "PASS"} for name in TWO_PERSON_DRILL_CHECKS],
                "signers": [approval(), other()],
            }
        )
        self.assertFalse(result["satisfiesProductionRequirement"])
        self.assertIn("does not satisfy the production second-signer requirement", result["note"])

    def test_a_production_key_in_a_two_person_role_must_declare_two_person_approval(self) -> None:
        with self.assertRaises(SigningError) as raised:
            parse_key_record(
                {
                    "keyId": "bunny-os-release-001",
                    "state": "active",
                    "publishedAt": "2026-07-30T00:00:00Z",
                    "expiresAt": "2027-07-30T00:00:00Z",
                    "publicKeyReference": "keys/release.pem",
                    "storage": "hardware-token",
                    "twoPersonApproval": False,
                }
            )
        self.assertIn("requires two-person approval", str(raised.exception))

    def test_a_production_key_in_a_directory_is_refused(self) -> None:
        with self.assertRaises(SigningError) as raised:
            parse_key_record(
                {
                    "keyId": "bunny-os-release-001",
                    "state": "active",
                    "publishedAt": "2026-07-30T00:00:00Z",
                    "expiresAt": "2027-07-30T00:00:00Z",
                    "publicKeyReference": "keys/release.pem",
                    "storage": "development-directory",
                    "twoPersonApproval": True,
                }
            )
        self.assertIn("hardware token, offline HSM", str(raised.exception))


class OnePersonIsNotTwoSigners(unittest.TestCase):
    """Adversarial case 14."""

    def test_two_key_ids_with_one_operator_fingerprint_are_refused(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()),
            parsed(other(operatorFingerprint="1" * 32)),
            role="osRelease",
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(
            any("one person supplying two signer identities" in r for r in verdict["reasons"]),
            verdict["reasons"],
        )

    def test_one_key_used_twice_is_refused(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()),
            parsed(other(keyId="dev-bunny-os-release-signer-a")),
            role="osRelease",
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(any("one key is not two signers" in r for r in verdict["reasons"]))

    def test_one_operation_log_for_both_signers_is_refused(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()),
            parsed(other(operationLogReference="/var/log/signer-a.log")),
            role="osRelease",
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(any("same operation log" in r for r in verdict["reasons"]))

    def test_one_signer_id_used_twice_is_refused(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()), parsed(other(signerId="signer-a")), role="osRelease"
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(any("both approvals name signer" in r for r in verdict["reasons"]))

    def test_two_genuinely_distinct_signers_are_authorised(self) -> None:
        verdict = evaluate_two_person_approval(parsed(approval()), parsed(other()), role="osRelease")
        self.assertTrue(verdict["authorised"], verdict["reasons"])


class ApprovalSemantics(unittest.TestCase):
    def test_signers_must_approve_the_same_artifact(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()), parsed(other(artifactDigest="b" * 64)), role="osRelease"
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(any("different artifacts" in r for r in verdict["reasons"]))

    def test_a_refusal_blocks_the_authorisation(self) -> None:
        verdict = evaluate_two_person_approval(
            parsed(approval()), parsed(other(decision="refuse")), role="osRelease"
        )
        self.assertFalse(verdict["authorised"])
        self.assertTrue(any("a refusal is final" in r for r in verdict["reasons"]))

    def test_a_key_from_another_role_is_refused_at_parse_time(self) -> None:
        with self.assertRaises(SigningError) as raised:
            parse_signer_approval(approval(keyId="dev-recovery-signer-a"), expectedRole="osRelease")
        self.assertIn("not interchangeable", str(raised.exception))

    def test_a_role_that_needs_no_two_person_approval_is_refused(self) -> None:
        with self.assertRaises(SigningError) as raised:
            evaluate_two_person_approval(
                parsed(approval()), parsed(other()), role="syncServiceIdentity"
            )
        self.assertIn("does not require two-person approval", str(raised.exception))

    def test_four_roles_require_two_person_approval(self) -> None:
        self.assertEqual(
            TWO_PERSON_ROLES,
            frozenset({"osRelease", "updateMetadata", "recoveryImage", "oemProfile"}),
        )

    def test_a_bad_artifact_digest_is_refused(self) -> None:
        with self.assertRaises(SigningError):
            parse_signer_approval(approval(artifactDigest="short"), expectedRole="osRelease")

    def test_a_missing_operation_log_is_refused(self) -> None:
        with self.assertRaises(SigningError) as raised:
            parse_signer_approval(approval(operationLogReference=""), expectedRole="osRelease")
        self.assertIn("operationLogReference", str(raised.exception))


class DrillRecord(unittest.TestCase):
    def test_the_drill_has_nine_checks(self) -> None:
        self.assertEqual(len(TWO_PERSON_DRILL_CHECKS), 9)

    def test_a_missing_check_fails_the_drill(self) -> None:
        result = evaluate_two_person_drill(
            {
                "schemaVersion": 1,
                "role": "osRelease",
                "checks": [
                    {"check": name, "outcome": "PASS"} for name in TWO_PERSON_DRILL_CHECKS[:-1]
                ],
                "signers": [approval(), other()],
            }
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("disagreement-refusal", result["missingChecks"])

    def test_a_not_run_check_fails_the_drill(self) -> None:
        checks = [{"check": name, "outcome": "PASS"} for name in TWO_PERSON_DRILL_CHECKS]
        checks[0]["outcome"] = "NOT_RUN"
        result = evaluate_two_person_drill(
            {"schemaVersion": 1, "role": "osRelease", "checks": checks, "signers": [approval(), other()]}
        )
        self.assertEqual(result["result"], "FAIL")

    def test_an_unauthorised_signer_pair_fails_the_drill(self) -> None:
        result = evaluate_two_person_drill(
            {
                "schemaVersion": 1,
                "role": "osRelease",
                "checks": [{"check": name, "outcome": "PASS"} for name in TWO_PERSON_DRILL_CHECKS],
                "signers": [approval(), other(operatorFingerprint="1" * 32)],
            }
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("signer-a-approval", result["failingChecks"])

    def test_an_unknown_check_is_rejected(self) -> None:
        with self.assertRaises(SigningError):
            evaluate_two_person_drill(
                {"schemaVersion": 1, "checks": [{"check": "vibes", "outcome": "PASS"}]}
            )


class CommittedDrill(unittest.TestCase):
    def setUp(self) -> None:
        path = ROOT / "operations/data/two-person-signing-drill.json"
        if not path.is_file():
            self.skipTest("run scripts/two_person_drill.py first")
        self.document = json.loads(path.read_text(encoding="utf-8"))

    def test_the_committed_drill_passes(self) -> None:
        result = evaluate_two_person_drill(self.document)
        self.assertEqual(result["result"], "PASS", result["failingChecks"])

    def test_the_committed_drill_uses_development_keys_only(self) -> None:
        for signer in self.document["signers"]:
            identity = parse_key_id(signer["keyId"])
            self.assertTrue(identity.isDevelopment, signer["keyId"])

    def test_the_committed_drill_does_not_satisfy_the_production_requirement(self) -> None:
        result = evaluate_two_person_drill(self.document)
        self.assertFalse(result["satisfiesProductionRequirement"])

    def test_no_production_key_exists(self) -> None:
        keys = json.loads((ROOT / "operations/data/signing-keys.json").read_text(encoding="utf-8"))
        production = []
        for item in keys.get("keys", []):
            record = parse_key_record(item)
            if record.keyClass == "production" and record.state in {"active", "rotating"}:
                production.append(record.keyId)
        self.assertEqual(production, [], f"production keys claimed: {production}")

    def test_key_states_are_a_closed_vocabulary(self) -> None:
        self.assertEqual(
            set(KEY_STATES), {"active", "pending", "rotating", "revoked", "expired"}
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

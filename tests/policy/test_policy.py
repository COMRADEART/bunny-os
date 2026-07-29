from __future__ import annotations

from datetime import datetime, timezone
import unittest

from enterprise.conflict import (
    LAYER_OWNERS,
    PRECEDENCE_ORDER,
    assert_organisation_policy_permitted,
    assert_user_cannot_bypass,
    explain_for_display,
    resolve,
)
from enterprise.policy import (
    ENFORCEMENT_TYPES,
    MANAGED_DOMAINS,
    SAFETY_INVARIANTS,
    TYPED_OPERATIONS,
    PolicyError,
    describe_domains,
    is_active,
    parse_policy,
)

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def policy(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "policyId": "POL-0001",
        "version": 1,
        "domain": "encryption-requirement",
        "scope": "organisation",
        "owner": "security-administrator",
        "desiredState": "required",
        "enforcementType": "enforced",
        "effectiveFrom": "2026-01-01T00:00:00Z",
        "expiresAt": None,
        "priority": 100,
        "conflictRule": "most-restrictive-wins",
        "remediation": "block-until-compliant",
    }
    value.update(overrides)
    return value


class PolicyTests(unittest.TestCase):
    def test_valid_policy_parses_and_binds_a_typed_operation(self) -> None:
        parsed = parse_policy(policy())
        self.assertEqual(parsed.operation, "policy.encryption.requirement.set")
        self.assertIn(parsed.operation, TYPED_OPERATIONS)

    def test_every_domain_has_exactly_one_typed_operation(self) -> None:
        operations = [item.operation for item in MANAGED_DOMAINS]
        self.assertEqual(len(operations), len(set(operations)))
        self.assertEqual(len(MANAGED_DOMAINS), 15)

    def test_organisation_may_require_encryption(self) -> None:
        self.assertTrue(parse_policy(policy()).enforcementType == "enforced")

    def test_organisation_cannot_disable_update_signature_verification(self) -> None:
        with self.assertRaises(PolicyError) as error:
            parse_policy(policy(domain="os.update.signature-verification", desiredState=False))
        self.assertIn("safety invariant", str(error.exception))

    def test_fleet_policy_cannot_expose_bunny_memory(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="bunny.memory.expose-to-organisation", desiredState=True))

    def test_unknown_domain_is_rejected(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="run-arbitrary-command"))

    def test_execution_channel_in_desired_state_is_rejected(self) -> None:
        with self.assertRaises(PolicyError) as error:
            parse_policy(policy(domain="plugin-policy", desiredState={"command": "/bin/sh"}))
        self.assertIn("execution channel", str(error.exception))

    def test_nested_execution_channel_is_rejected(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="plugin-policy", desiredState={"versionPins": {"a": "1"}, "script": "x"}))

    def test_invalid_update_channel_is_rejected(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="update-channel", desiredState="nightly"))

    def test_valid_update_channel_is_accepted(self) -> None:
        self.assertEqual(parse_policy(policy(domain="update-channel", desiredState="stable")).desiredState, "stable")

    def test_update_deadline_bounds_are_enforced(self) -> None:
        parse_policy(policy(domain="update-deadline", desiredState=14))
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="update-deadline", desiredState=400))

    def test_screen_lock_requires_exact_fields(self) -> None:
        parse_policy(policy(domain="screen-lock", desiredState={"requireLock": True, "maxIdleSeconds": 300}))
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="screen-lock", desiredState={"requireLock": True}))

    def test_provider_policy_rejects_credential_values(self) -> None:
        with self.assertRaises(PolicyError) as error:
            parse_policy(policy(domain="bunny-provider-policy", desiredState={"apiKey": "sk-secret"}))
        self.assertIn("credential source", str(error.exception))

    def test_provider_policy_accepts_local_only(self) -> None:
        parsed = parse_policy(policy(domain="bunny-provider-policy", desiredState={"localOnly": True, "cloudFallback": "never"}))
        self.assertEqual(parsed.desiredState["localOnly"], True)

    def test_provider_policy_rejects_always_cloud_fallback(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="bunny-provider-policy", desiredState={"cloudFallback": "always"}))

    def test_plugin_full_capability_requires_explicit_allowlist(self) -> None:
        with self.assertRaises(PolicyError) as error:
            parse_policy(policy(domain="plugin-policy", desiredState={"maximumCapability": "full-requested"}))
        self.assertIn("never granted silently", str(error.exception))

    def test_plugin_full_capability_with_allowlist_is_accepted(self) -> None:
        parse_policy(policy(
            domain="plugin-policy",
            desiredState={"maximumCapability": "full-requested", "pluginAllowlist": ["org.example.Plugin"]},
        ))

    def test_local_only_ai_requirement_is_boolean(self) -> None:
        parse_policy(policy(domain="local-only-ai-requirement", desiredState=True))
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="local-only-ai-requirement", desiredState="yes"))

    def test_diagnostic_export_policy_cannot_enable_upload(self) -> None:
        parse_policy(policy(domain="diagnostic-export-policy", desiredState="local-only"))
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="diagnostic-export-policy", desiredState="upload-to-organisation"))

    def test_application_allowlist_rejects_malformed_package_id(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(domain="application-allowlist", desiredState=["../../etc/passwd"]))

    def test_blocked_enforcement_requires_remediation(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(enforcementType="blocked", remediation="none"))

    def test_expiry_must_follow_effective_time(self) -> None:
        with self.assertRaises(PolicyError):
            parse_policy(policy(effectiveFrom="2026-06-01T00:00:00Z", expiresAt="2026-01-01T00:00:00Z"))

    def test_all_four_enforcement_types_are_supported(self) -> None:
        self.assertEqual(set(ENFORCEMENT_TYPES), {"informational", "recommended", "enforced", "blocked"})

    def test_active_window_is_respected(self) -> None:
        future = parse_policy(policy(effectiveFrom="2030-01-01T00:00:00Z"))
        self.assertFalse(is_active(future, now=NOW))
        expired = parse_policy(policy(effectiveFrom="2020-01-01T00:00:00Z", expiresAt="2021-01-01T00:00:00Z"))
        self.assertFalse(is_active(expired, now=NOW))
        self.assertTrue(is_active(parse_policy(policy()), now=NOW))

    def test_domain_catalogue_is_complete(self) -> None:
        self.assertEqual({item["domain"] for item in describe_domains()}, {item.domain for item in MANAGED_DOMAINS})


class ConflictTests(unittest.TestCase):
    def test_precedence_order_is_fixed(self) -> None:
        self.assertEqual(
            PRECEDENCE_ORDER,
            (
                "safety-invariant",
                "operating-system-security-policy",
                "organisation-device-policy",
                "user-preference",
                "application-preference",
            ),
        )

    def test_safety_invariant_beats_everything(self) -> None:
        decision = resolve("os.update.signature-verification", [
            {"layer": "application-preference", "value": False},
            {"layer": "organisation-device-policy", "value": False},
            {"layer": "safety-invariant", "value": True},
        ])
        self.assertEqual(decision.winningLayer, "safety-invariant")
        self.assertTrue(decision.winningValue)
        self.assertFalse(decision.userChangeable)

    def test_organisation_beats_user_preference(self) -> None:
        decision = resolve("os.encryption.required", [
            {"layer": "user-preference", "value": False},
            {"layer": "organisation-device-policy", "value": True, "owner": "Example School"},
        ])
        self.assertEqual(decision.winningLayer, "organisation-device-policy")
        self.assertEqual(decision.winningOwner, "Example School")
        self.assertIn("Example School", decision.explanation)

    def test_user_preference_wins_when_unmanaged(self) -> None:
        decision = resolve("desktop.wallpaper", [{"layer": "user-preference", "value": "blue"}])
        self.assertTrue(decision.userChangeable)

    def test_os_security_policy_beats_organisation(self) -> None:
        decision = resolve("os.security.warnings-visible", [
            {"layer": "organisation-device-policy", "value": False},
            {"layer": "operating-system-security-policy", "value": True},
        ])
        self.assertEqual(decision.winningLayer, "operating-system-security-policy")

    def test_ambiguous_same_layer_conflict_is_refused(self) -> None:
        with self.assertRaises(PolicyError):
            resolve("update-channel", [
                {"layer": "organisation-device-policy", "value": "stable"},
                {"layer": "organisation-device-policy", "value": "beta"},
            ])

    def test_priority_breaks_same_layer_conflict(self) -> None:
        decision = resolve("update-channel", [
            {"layer": "organisation-device-policy", "value": "stable", "priority": 200},
            {"layer": "organisation-device-policy", "value": "beta", "priority": 100},
        ])
        self.assertEqual(decision.winningValue, "stable")

    def test_tied_priority_is_refused(self) -> None:
        with self.assertRaises(PolicyError):
            resolve("update-channel", [
                {"layer": "organisation-device-policy", "value": "stable", "priority": 100},
                {"layer": "organisation-device-policy", "value": "beta", "priority": 100},
            ])

    def test_unknown_layer_is_rejected(self) -> None:
        with self.assertRaises(PolicyError):
            resolve("thing", [{"layer": "vendor-override", "value": 1}])

    def test_empty_candidate_list_is_rejected(self) -> None:
        with self.assertRaises(PolicyError):
            resolve("thing", [])

    def test_organisation_cannot_target_safety_invariant(self) -> None:
        for setting in sorted(SAFETY_INVARIANTS):
            with self.subTest(setting=setting):
                with self.assertRaises(PolicyError):
                    assert_organisation_policy_permitted(setting)

    def test_organisation_may_target_ordinary_setting(self) -> None:
        assert_organisation_policy_permitted("os.encryption.required")

    def test_user_cannot_bypass_mandatory_baseline(self) -> None:
        with self.assertRaises(PolicyError):
            assert_user_cannot_bypass("os.update.signature-verification", "user-preference")

    def test_display_explains_ownership(self) -> None:
        decision = resolve("os.encryption.required", [
            {"layer": "user-preference", "value": False},
            {"layer": "organisation-device-policy", "value": True},
        ])
        rows = explain_for_display([decision])
        self.assertEqual(rows[0]["managedBy"], LAYER_OWNERS["organisation-device-policy"])
        self.assertFalse(rows[0]["changeable"])
        self.assertTrue(rows[0]["why"])


if __name__ == "__main__":
    unittest.main()

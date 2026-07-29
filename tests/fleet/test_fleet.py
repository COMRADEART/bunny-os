from __future__ import annotations

import unittest

from enterprise.catalogue import CatalogueError, parse_entry, resolve_deployment
from enterprise.fleet import (
    UPDATE_RINGS,
    UPDATE_STATES,
    FleetError,
    assert_promotion_permitted,
    eligible_device_count,
    parse_group,
    parse_ring,
    parse_update_state,
)
from enterprise.health import HealthError, describe_visible_fields, parse_health
from enterprise.remote import (
    REMOTE_OPERATIONS,
    RemoteOperationError,
    assert_within_boundary,
    authorize,
    describe_operations,
)
from enterprise.roles import ROLES, RoleError, authorize_operation, authorize_view, describe_roles

CORRELATION = "0f9c2a1b-4d3e-4f5a-8b6c-7d8e9f0a1b2c"


def group(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "groupId": "grp-site-north",
        "dimension": "site",
        "name": "North campus",
        "parentGroupId": None,
        "deviceCount": 40,
    }
    value.update(overrides)
    return value


def ring(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {"schemaVersion": 1, "ring": "general-deployment", "rolloutPercentage": 25}
    value.update(overrides)
    return value


def health(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "osVersion": "1.0.0",
        "updateState": "healthy",
        "recoveryReadiness": "ready",
        "encryptionState": "encrypted",
        "secureBootState": "enabled",
        "policyAgentHealth": "healthy",
        "requiredServiceStatus": "all-running",
        "storageHealthCategory": "healthy",
        "hardwareSupportCategory": "stable-supported",
        "criticalSecurityAdvisoryStatus": "none-open",
    }
    value.update(overrides)
    return value


def remote(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "operation": "update.check.request",
        "enrolmentMode": "organisation-owned",
        "authorisationStrength": "multi-factor",
        "administrator": "admin@example.invalid",
    }
    value.update(overrides)
    return value


def catalogue_entry(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "organisationId": "org-example-school",
        "packageId": "org.example.Editor",
        "source": "flathub-verified",
        "packageFormat": "flatpak",
        "publisher": "Example Publisher",
        "version": "2.1.0",
        "signatureVerified": True,
        "permissions": ["network", "documents-portal"],
        "deploymentState": "optional-approved",
        "updatePolicy": "manual",
        "removalPolicy": "user-removable",
        "supportOwner": "IT team",
    }
    value.update(overrides)
    return value


class FleetGroupTests(unittest.TestCase):
    def test_valid_group_parses(self) -> None:
        self.assertEqual(parse_group(group()).dimension, "site")

    def test_behavioural_attribute_is_rejected(self) -> None:
        with self.assertRaises(FleetError) as error:
            parse_group(group(attributes={"productivityScore": 8}))
        self.assertIn("personal behaviour", str(error.exception))

    def test_several_behavioural_attributes_are_rejected(self) -> None:
        for attribute in ("activityScore", "usageHours", "keystrokeCount", "attendance", "applicationUsage"):
            with self.subTest(attribute=attribute):
                with self.assertRaises(FleetError):
                    parse_group(group(attributes={attribute: 1}))

    def test_operational_attribute_is_permitted(self) -> None:
        parse_group(group(attributes={"buildingCode": "N1"}))

    def test_self_parent_is_rejected(self) -> None:
        with self.assertRaises(FleetError):
            parse_group(group(parentGroupId="grp-site-north"))

    def test_unknown_dimension_is_rejected(self) -> None:
        with self.assertRaises(FleetError):
            parse_group(group(dimension="employee-performance"))


class UpdateRingTests(unittest.TestCase):
    def test_valid_ring_parses(self) -> None:
        parsed = parse_ring(ring())
        self.assertEqual(parsed.rolloutPercentage, 25)
        self.assertTrue(parsed.signatureVerificationRequired)

    def test_signature_verification_cannot_be_disabled(self) -> None:
        with self.assertRaises(FleetError) as error:
            parse_ring(ring(signatureVerificationRequired=False))
        self.assertIn("mandatory", str(error.exception))

    def test_all_five_rings_exist(self) -> None:
        self.assertEqual(
            set(UPDATE_RINGS),
            {"internal-test", "early-validation", "general-deployment", "deferred", "emergency"},
        )

    def test_withdrawn_update_must_have_zero_rollout(self) -> None:
        with self.assertRaises(FleetError):
            parse_ring(ring(withdrawn=True, rolloutPercentage=50))
        parse_ring(ring(withdrawn=True, rolloutPercentage=0))

    def test_paused_ring_offers_nothing(self) -> None:
        self.assertEqual(eligible_device_count(100, parse_ring(ring(paused=True))), 0)

    def test_rollout_percentage_limits_eligibility(self) -> None:
        self.assertEqual(eligible_device_count(100, parse_ring(ring(rolloutPercentage=25))), 25)

    def test_forced_restart_requires_explicit_policy_reference(self) -> None:
        with self.assertRaises(FleetError) as error:
            parse_ring(ring(forcedRestart=True))
        self.assertIn("forcedRestartPolicyReference", str(error.exception))
        parse_ring(ring(forcedRestart=True, forcedRestartPolicyReference="POL-0009"))

    def test_deferred_ring_cannot_force_restart(self) -> None:
        with self.assertRaises(FleetError):
            parse_ring(ring(ring="deferred", forcedRestart=True, forcedRestartPolicyReference="POL-0009"))

    def test_maintenance_window_format_is_enforced(self) -> None:
        parse_ring(ring(maintenanceWindow={"start": "02:00", "end": "05:00"}))
        with self.assertRaises(FleetError):
            parse_ring(ring(maintenanceWindow={"start": "2am", "end": "5am"}))

    def test_promotion_cannot_skip_early_validation(self) -> None:
        with self.assertRaises(FleetError) as error:
            assert_promotion_permitted("internal-test", "general-deployment")
        self.assertIn("skips", str(error.exception))

    def test_ordered_promotion_is_permitted(self) -> None:
        assert_promotion_permitted("internal-test", "early-validation")
        assert_promotion_permitted("early-validation", "general-deployment")

    def test_emergency_ring_may_be_entered_directly(self) -> None:
        assert_promotion_permitted("internal-test", "emergency")


class UpdateStateTests(unittest.TestCase):
    def test_all_nine_states_are_reportable(self) -> None:
        self.assertEqual(len(UPDATE_STATES), 9)

    def test_valid_state_parses(self) -> None:
        parse_update_state({"schemaVersion": 1, "state": "staged", "targetVersion": "1.0.1"})

    def test_user_activity_context_is_rejected(self) -> None:
        for field in ("activeApplication", "openFiles", "currentTask", "windowTitle", "terminalCommand"):
            with self.subTest(field=field):
                with self.assertRaises(FleetError) as error:
                    parse_update_state({"schemaVersion": 1, "state": "staged", field: "x"})
                self.assertIn("user activity", str(error.exception))

    def test_failed_update_must_preserve_rollback(self) -> None:
        with self.assertRaises(FleetError) as error:
            parse_update_state({"schemaVersion": 1, "state": "failed", "rollbackAvailable": False})
        self.assertIn("preserve the previous deployment", str(error.exception))

    def test_failed_update_with_rollback_is_accepted(self) -> None:
        parse_update_state({
            "schemaVersion": 1, "state": "failed", "rollbackAvailable": True,
            "previousVersion": "1.0.0", "failureCode": "bootc-switch-failed",
        })

    def test_rolled_back_update_must_name_previous_version(self) -> None:
        with self.assertRaises(FleetError):
            parse_update_state({"schemaVersion": 1, "state": "rolled-back", "rollbackAvailable": True})

    def test_unknown_state_is_rejected(self) -> None:
        with self.assertRaises(FleetError):
            parse_update_state({"schemaVersion": 1, "state": "user-was-busy"})


class FleetHealthTests(unittest.TestCase):
    def test_valid_health_parses(self) -> None:
        self.assertEqual(parse_health(health()).osVersion, "1.0.0")

    def test_prohibited_behavioural_fields_are_rejected(self) -> None:
        for field in (
            "prompts", "memories", "fileNames", "browserHistory", "terminalHistory",
            "applicationUsageDuration", "keyboardActivity", "screenshot", "cameraContent",
        ):
            with self.subTest(field=field):
                value = health()
                value[field] = "x"
                with self.assertRaises(HealthError):
                    parse_health(value)

    def test_identifying_fields_are_rejected(self) -> None:
        for field in ("hostname", "username", "email", "macAddress", "serial"):
            with self.subTest(field=field):
                value = health()
                value[field] = "x"
                with self.assertRaises(HealthError) as error:
                    parse_health(value)
                self.assertIn("fleet health", str(error.exception))

    def test_missing_field_is_rejected(self) -> None:
        value = health()
        del value["encryptionState"]
        with self.assertRaises(HealthError):
            parse_health(value)

    def test_storage_is_a_category_not_a_serial(self) -> None:
        with self.assertRaises(HealthError):
            parse_health(health(storageHealthCategory="Samsung 990 PRO S6B0NJ0T"))

    def test_disclosure_covers_every_visible_field(self) -> None:
        described = {item["field"] for item in describe_visible_fields()}
        self.assertEqual(described, set(health()))


class RemoteBoundaryTests(unittest.TestCase):
    def test_remote_shell_is_refused_with_a_specific_message(self) -> None:
        with self.assertRaises(RemoteOperationError) as error:
            assert_within_boundary("device.shell")
        self.assertIn("no generic remote shell", str(error.exception))

    def test_command_execution_names_are_refused(self) -> None:
        for name in ("run.command", "exec.script", "device.bash", "remote.powershell", "device.ssh"):
            with self.subTest(name=name):
                with self.assertRaises(RemoteOperationError):
                    assert_within_boundary(name)

    def test_no_remote_operation_accepts_a_command(self) -> None:
        for operation in REMOTE_OPERATIONS:
            with self.subTest(operation=operation.name):
                self.assertNotIn("shell", operation.name)
                self.assertNotIn("exec", operation.name)
                self.assertNotIn("command", operation.name)

    def test_unknown_operation_is_refused(self) -> None:
        with self.assertRaises(RemoteOperationError):
            assert_within_boundary("device.enable-vendor-backdoor")

    def test_benign_operation_is_permitted(self) -> None:
        self.assertTrue(authorize(remote()).permitted)

    def test_personal_device_cannot_be_factory_reset(self) -> None:
        decision = authorize(remote(
            operation="device.factory-reset", enrolmentMode="personally-owned",
            priorPolicyDeclared=True, scope=["all"], auditCorrelationId=CORRELATION,
        ))
        self.assertFalse(decision.permitted)
        self.assertTrue(any("personally owned" in item for item in decision.refusals))

    def test_organisation_device_factory_reset_requires_prior_policy(self) -> None:
        decision = authorize(remote(
            operation="device.factory-reset", scope=["all"], auditCorrelationId=CORRELATION,
        ))
        self.assertFalse(decision.permitted)
        self.assertTrue(any("prior policy" in item for item in decision.refusals))

    def test_destructive_operation_requires_audit_correlation(self) -> None:
        decision = authorize(remote(
            operation="device.factory-reset", priorPolicyDeclared=True, scope=["all"],
        ))
        self.assertTrue(any("audit evidence" in item for item in decision.refusals))

    def test_destructive_operation_requires_strong_authorisation(self) -> None:
        decision = authorize(remote(
            operation="device.factory-reset", authorisationStrength="single-factor",
            priorPolicyDeclared=True, scope=["all"], auditCorrelationId=CORRELATION,
        ))
        self.assertTrue(any("multi-factor" in item for item in decision.refusals))

    def test_fully_authorised_organisation_reset_is_permitted(self) -> None:
        decision = authorize(remote(
            operation="device.factory-reset", priorPolicyDeclared=True,
            scope=["organisation-owned-laptop-42"], auditCorrelationId=CORRELATION,
        ))
        self.assertTrue(decision.permitted, decision.refusals)
        self.assertTrue(decision.recoveryPreserved)
        self.assertTrue(any("recovery environment" in item for item in decision.dataLossConsequences))

    def test_device_side_confirmation_is_enforced_when_policy_requires_it(self) -> None:
        decision = authorize(remote(
            operation="organisation.data.remove", priorPolicyDeclared=True, scope=["profiles"],
            auditCorrelationId=CORRELATION, policyRequiresDeviceConfirmation=True,
        ))
        self.assertFalse(decision.permitted)
        self.assertTrue(decision.requiresDeviceConfirmation)

    def test_organisation_data_removal_does_not_touch_personal_data(self) -> None:
        decision = authorize(remote(
            operation="organisation.data.remove", enrolmentMode="personally-owned",
            priorPolicyDeclared=True, scope=["profiles"], auditCorrelationId=CORRELATION,
        ))
        self.assertTrue(decision.permitted, decision.refusals)
        self.assertTrue(any("Personal files" in item for item in decision.dataLossConsequences))

    def test_five_distinct_wipe_operations_exist(self) -> None:
        names = {item["operation"] for item in describe_operations()}
        for expected in (
            "organisation.data.remove", "organisation.applications.remove",
            "organisation.credentials.revoke", "device.factory-reset", "device.cryptographic-erase",
        ):
            self.assertIn(expected, names)


class RoleTests(unittest.TestCase):
    def test_seven_roles_exist(self) -> None:
        self.assertEqual(len(ROLES), 7)

    def test_help_desk_cannot_erase_a_device(self) -> None:
        decision = authorize_operation({
            "role": "help-desk-operator", "operation": "device.cryptographic-erase",
            "authenticationMethod": "passkey", "stepUpSatisfied": True,
        })
        self.assertFalse(decision.permitted)

    def test_read_only_analyst_performs_no_operations(self) -> None:
        decision = authorize_operation({
            "role": "read-only-analyst", "operation": "update.check.request",
            "authenticationMethod": "oidc",
        })
        self.assertFalse(decision.permitted)

    def test_auditor_cannot_operate_devices(self) -> None:
        decision = authorize_operation({
            "role": "auditor", "operation": "device.restart.request", "authenticationMethod": "oidc",
        })
        self.assertFalse(decision.permitted)

    def test_security_administrator_may_erase_with_step_up(self) -> None:
        decision = authorize_operation({
            "role": "security-administrator", "operation": "device.cryptographic-erase",
            "authenticationMethod": "hardware-security-key", "stepUpSatisfied": True,
        })
        self.assertTrue(decision.permitted, decision.refusals)

    def test_destructive_action_refuses_weak_authentication(self) -> None:
        decision = authorize_operation({
            "role": "security-administrator", "operation": "device.factory-reset",
            "authenticationMethod": "oidc",
        })
        self.assertFalse(decision.permitted)
        self.assertTrue(decision.stepUpRequired)

    def test_break_glass_role_warns_on_routine_use(self) -> None:
        decision = authorize_operation({
            "role": "organisation-owner", "operation": "update.check.request",
            "authenticationMethod": "passkey", "stepUpSatisfied": True,
        })
        self.assertIsNotNone(decision.breakGlassWarning)

    def test_custom_password_authentication_is_refused(self) -> None:
        with self.assertRaises(RoleError) as error:
            authorize_operation({
                "role": "device-administrator", "operation": "update.check.request",
                "authenticationMethod": "custom-password",
            })
        self.assertIn("custom", str(error.exception))

    def test_console_cannot_expose_user_content(self) -> None:
        for view in ("user-files", "prompts", "memories", "remote-shell", "live-screen"):
            with self.subTest(view=view):
                with self.assertRaises(RoleError):
                    authorize_view("organisation-owner", view)

    def test_permitted_view_is_scoped_by_role(self) -> None:
        self.assertTrue(authorize_view("auditor", "audit").permitted)
        self.assertFalse(authorize_view("help-desk-operator", "audit").permitted)

    def test_role_catalogue_is_complete(self) -> None:
        self.assertEqual({item["role"] for item in describe_roles()}, set(ROLES))


class CatalogueTests(unittest.TestCase):
    def test_valid_entry_parses(self) -> None:
        self.assertEqual(parse_entry(catalogue_entry()).packageId, "org.example.Editor")

    def test_unsigned_package_is_refused(self) -> None:
        with self.assertRaises(CatalogueError) as error:
            parse_entry(catalogue_entry(signatureVerified=False))
        self.assertIn("unsigned packages are refused", str(error.exception))

    def test_native_package_is_labelled_broad_access(self) -> None:
        parsed = parse_entry(catalogue_entry(packageFormat="rpm", packageId="vendor-agent", permissions=[]))
        self.assertTrue(parsed.broadSystemAccess)
        self.assertIn("broad system access", parsed.label or "")

    def test_native_package_cannot_claim_bounded_permissions(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_entry(catalogue_entry(packageFormat="rpm", packageId="vendor-agent", permissions=["network"]))

    def test_unenforceable_flatpak_permission_is_rejected(self) -> None:
        with self.assertRaises(CatalogueError) as error:
            parse_entry(catalogue_entry(permissions=["full-system-access"]))
        self.assertIn("sandbox cannot express", str(error.exception))

    def test_managed_configuration_cannot_carry_credentials(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_entry(catalogue_entry(managedConfiguration={"apiKey": "sk-secret"}))

    def test_required_application_cannot_be_user_removable(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_entry(catalogue_entry(deploymentState="required", removalPolicy="user-removable"))

    def test_ring_managed_update_requires_a_ring(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_entry(catalogue_entry(updatePolicy="ring-managed"))
        parse_entry(catalogue_entry(updatePolicy="ring-managed", updateRing="early-validation"))

    def test_blocked_beats_required(self) -> None:
        resolved = resolve_deployment({"org.example.A": "required"})
        self.assertEqual(resolved["org.example.A"], "required")
        self.assertEqual(resolve_deployment({"org.example.A": "blocked"})["org.example.A"], "blocked")

    def test_flatpak_id_must_be_reverse_dns(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_entry(catalogue_entry(packageId="editor"))


if __name__ == "__main__":
    unittest.main()

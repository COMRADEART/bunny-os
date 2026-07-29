from __future__ import annotations

import unittest

from enterprise.audit import append_entry, verify_chain
from enterprise.tenancy import (
    ISOLATION_REQUIREMENTS,
    TENANT_SCOPED_RESOURCES,
    TenancyError,
    assert_organisation_id,
    assert_same_tenant,
    evaluate_isolation,
    filter_rows,
    scoped_filter,
)

ORG_A = "org-alpha-school"
ORG_B = "org-beta-company"
CORRELATION = "0f9c2a1b-4d3e-4f5a-8b6c-7d8e9f0a1b2c"


class CrossTenantAccessTests(unittest.TestCase):
    def test_organisation_a_cannot_read_organisation_b_devices(self) -> None:
        with self.assertRaises(TenancyError) as error:
            assert_same_tenant(
                actorOrganisationId=ORG_A,
                resourceOrganisationId=ORG_B,
                resourceKind="device",
                resourceId="dev-0123456789abcdef",
            )
        self.assertIn("cross-organisation access refused", str(error.exception))

    def test_every_scoped_resource_family_refuses_cross_tenant_access(self) -> None:
        for kind in TENANT_SCOPED_RESOURCES:
            with self.subTest(kind=kind):
                with self.assertRaises(TenancyError):
                    assert_same_tenant(
                        actorOrganisationId=ORG_A, resourceOrganisationId=ORG_B, resourceKind=kind
                    )

    def test_same_tenant_access_is_permitted(self) -> None:
        for kind in TENANT_SCOPED_RESOURCES:
            with self.subTest(kind=kind):
                assert_same_tenant(
                    actorOrganisationId=ORG_A, resourceOrganisationId=ORG_A, resourceKind=kind
                )

    def test_policy_cross_assignment_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_same_tenant(
                actorOrganisationId=ORG_A, resourceOrganisationId=ORG_B,
                resourceKind="policy", resourceId="POL-0001",
            )

    def test_update_ring_cross_access_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_same_tenant(
                actorOrganisationId=ORG_A, resourceOrganisationId=ORG_B, resourceKind="update-ring"
            )

    def test_catalogue_cross_access_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_same_tenant(
                actorOrganisationId=ORG_A, resourceOrganisationId=ORG_B,
                resourceKind="application-catalogue-entry",
            )

    def test_backup_restoration_into_wrong_tenant_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_same_tenant(
                actorOrganisationId=ORG_A, resourceOrganisationId=ORG_B, resourceKind="backup"
            )

    def test_unknown_resource_kind_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_same_tenant(
                actorOrganisationId=ORG_A, resourceOrganisationId=ORG_A, resourceKind="mystery-table"
            )


class UnscopedAccessTests(unittest.TestCase):
    def test_missing_tenant_scope_is_refused(self) -> None:
        with self.assertRaises(TenancyError) as error:
            assert_organisation_id(None)
        self.assertIn("unscoped access is refused", str(error.exception))

    def test_wildcard_tenant_scope_is_refused(self) -> None:
        for wildcard in ("*", "all", "any"):
            with self.subTest(wildcard=wildcard):
                with self.assertRaises(TenancyError):
                    assert_organisation_id(wildcard)

    def test_empty_tenant_scope_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            assert_organisation_id("")

    def test_scoped_filter_always_carries_the_tenant(self) -> None:
        self.assertEqual(scoped_filter(ORG_A, {"state": "active"})["organisationId"], ORG_A)

    def test_filter_cannot_override_the_tenant_scope(self) -> None:
        with self.assertRaises(TenancyError) as error:
            scoped_filter(ORG_A, {"organisationId": ORG_B})
        self.assertIn("may not override the tenant scope", str(error.exception))

    def test_rows_are_filtered_to_the_tenant(self) -> None:
        rows = [
            {"organisationId": ORG_A, "deviceKeyId": "dev-1111111111111111"},
            {"organisationId": ORG_B, "deviceKeyId": "dev-2222222222222222"},
        ]
        result = filter_rows(ORG_A, rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["organisationId"], ORG_A)

    def test_row_without_a_tenant_is_refused_not_dropped(self) -> None:
        with self.assertRaises(TenancyError) as error:
            filter_rows(ORG_A, [{"deviceKeyId": "dev-1111111111111111"}])
        self.assertIn("unscoped records are refused", str(error.exception))


class AuditIsolationTests(unittest.TestCase):
    def test_audit_chains_do_not_interleave_between_tenants(self) -> None:
        chain_a: list[dict[str, object]] = []
        chain_a.append(append_entry(chain_a, {
            "organisationId": ORG_A, "administrator": "a@example.invalid", "operation": "update.schedule",
            "targetScope": ["grp-a"], "policyVersion": 1, "occurredAt": "2026-07-29T12:00:00Z",
            "authorisation": "passkey", "result": "succeeded", "correlationId": CORRELATION,
        }))
        report = verify_chain(chain_a, organisation_id=ORG_B)
        self.assertFalse(report["intact"])

    def test_tenant_a_chain_verifies_under_its_own_scope(self) -> None:
        chain_a: list[dict[str, object]] = []
        chain_a.append(append_entry(chain_a, {
            "organisationId": ORG_A, "administrator": "a@example.invalid", "operation": "update.schedule",
            "targetScope": ["grp-a"], "policyVersion": 1, "occurredAt": "2026-07-29T12:00:00Z",
            "authorisation": "passkey", "result": "succeeded", "correlationId": CORRELATION,
        }))
        self.assertTrue(verify_chain(chain_a, organisation_id=ORG_A)["intact"])


class IsolationEvidenceTests(unittest.TestCase):
    def test_complete_evidence_isolates(self) -> None:
        evidence = {name: True for name in ISOLATION_REQUIREMENTS}
        verdict = evaluate_isolation(evidence, organisation_id=ORG_A)
        self.assertTrue(verdict.isolated)

    def test_missing_evidence_is_not_a_pass(self) -> None:
        evidence = {name: True for name in ISOLATION_REQUIREMENTS}
        del evidence["backupIsolation"]
        verdict = evaluate_isolation(evidence)
        self.assertFalse(verdict.isolated)
        self.assertIn("backupIsolation", verdict.missingEvidence)

    def test_failed_control_is_reported(self) -> None:
        evidence = {name: True for name in ISOLATION_REQUIREMENTS}
        evidence["auditIsolation"] = False
        verdict = evaluate_isolation(evidence)
        self.assertFalse(verdict.isolated)
        self.assertIn("auditIsolation", verdict.failedControls)

    def test_each_required_control_blocks_independently(self) -> None:
        for name in ISOLATION_REQUIREMENTS:
            with self.subTest(control=name):
                evidence = {item: True for item in ISOLATION_REQUIREMENTS}
                evidence[name] = False
                self.assertFalse(evaluate_isolation(evidence).isolated)

    def test_unknown_control_is_refused(self) -> None:
        with self.assertRaises(TenancyError):
            evaluate_isolation({"vibesBasedIsolation": True})

    def test_eight_controls_are_required(self) -> None:
        self.assertEqual(len(ISOLATION_REQUIREMENTS), 8)


if __name__ == "__main__":
    unittest.main()

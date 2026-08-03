# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply-time revalidation: everything that can change between deciding and acting."""

from __future__ import annotations

from dataclasses import replace
import unittest

from capability.apply import SUPPORTED_PLAN_SCHEMA_VERSION
from capability.apply.revalidate import revalidate_plan, revalidate_transition
from capability.apply.state import ActualState, DesiredService, ServiceObservation
from capability.budget import compute_budget
from capability.manifest import parse_manifest
from capability.policy import Policy, RemoteExecutionPolicy
from capability.registry import build_registry, load_registry
from capability.runtime import assess
from capability.scores import compute_scores
from capability.simulate import machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3
REGISTRY = load_registry()


def validate(assessment, *, now=0.0, in_force=None, **overrides):
    arguments = {
        "inventory": assessment.inventory,
        "budget": assessment.budget,
        "policy": assessment.policy,
        "registry": assessment.registry,
    }
    arguments.update(overrides)
    return revalidate_plan(
        assessment.plan.identity, now=now, in_force=in_force,
        supported_schema_version=SUPPORTED_PLAN_SCHEMA_VERSION, **arguments,
    )


def desired(**overrides) -> DesiredService:
    fields = {
        "service_id": "a.one", "should_run": True, "implementation_id": "only",
        "locality": "local", "memory_limit_bytes": 64 * MIB, "cpu_percent": 25.0,
        "essential": False, "priority": 50, "action": "start_local",
    }
    fields.update(overrides)
    return DesiredService(**fields)


class PlanValidationTests(unittest.TestCase):
    def test_an_unchanged_machine_validates(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        verdict = validate(assessment)
        self.assertTrue(verdict.ok, verdict.problems)
        self.assertTrue(verdict.checked)

    def test_a_plan_without_an_identity_is_refused(self) -> None:
        verdict = revalidate_plan(
            None,
            inventory=simulate("laptop"), budget=None, policy=Policy(), registry=REGISTRY,
            now=0.0, supported_schema_version=SUPPORTED_PLAN_SCHEMA_VERSION,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "invalid_plan")

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        plan = replace(
            assessment.plan,
            identity=replace(assessment.plan.identity, schema_version=99),
        )
        verdict = revalidate_plan(
            plan.identity,
            inventory=assessment.inventory, budget=assessment.budget,
            policy=assessment.policy, registry=assessment.registry, now=0.0,
            supported_schema_version=SUPPORTED_PLAN_SCHEMA_VERSION,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "invalid_plan")

    def test_memory_changing_after_generation_invalidates_the_plan(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        # The user opened forty browser tabs between the decision and the act.
        loaded = machine(
            physical_memory_bytes=16 * GIB, available_memory_bytes=1 * GIB, logical_threads=8,
        )
        verdict = validate(assessment, inventory=loaded)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "stale_plan")
        self.assertTrue(any("machine changed" in item for item in verdict.problems))
        self.assertEqual(verdict.reevaluation_reason, "apply_time_validation_failed")

    def test_policy_changing_after_generation_invalidates_the_plan(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        withdrawn = Policy(remote_execution=RemoteExecutionPolicy(enabled=True))
        verdict = validate(assessment, policy=withdrawn)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("policy changed" in item for item in verdict.problems))

    def test_a_manifest_changing_after_generation_invalidates_the_plan(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        altered = build_registry([parse_manifest({
            "schemaVersion": 1, "id": "test.service", "title": "T", "essential": False,
            "priority": "standard", "budgetCategory": "optional_services",
            "implementations": [{
                "id": "only", "title": "Only", "locality": "local", "rank": 1,
                "requirements": {"memory": {"minimumBytes": 8 * MIB}},
            }],
        })])
        verdict = validate(assessment, registry=altered)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("manifest changed" in item for item in verdict.problems))

    def test_the_budget_changing_after_generation_invalidates_the_plan(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        tighter = compute_budget(
            assessment.inventory, assessment.scores,
            Policy(maximum_service_memory_bytes=128 * MIB),
            essential_floor_bytes=REGISTRY.essential_floor_bytes(),
        )
        verdict = validate(assessment, budget=tighter)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("budget changed" in item for item in verdict.problems))

    def test_an_expired_plan_is_refused(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY, now=0.0)
        verdict = validate(assessment, now=10_000.0)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "stale_plan")
        self.assertTrue(any("old against" in item for item in verdict.problems))

    def test_a_superseded_plan_is_refused_before_its_fingerprints_are_checked(self) -> None:
        inventory = simulate("laptop")
        first = assess(inventory, registry=REGISTRY)
        second = assess(inventory, registry=REGISTRY, previous=first.plan, now=10.0)
        verdict = validate(first, in_force=second.plan.identity)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "superseded_plan")

    def test_reapplying_the_plan_already_in_force_is_permitted(self) -> None:
        # Reconciliation is meant to be run repeatedly against the same plan.
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        verdict = validate(assessment, in_force=assessment.plan.identity)
        self.assertTrue(verdict.ok, verdict.problems)

    def test_the_verdict_shows_the_checks_that_passed_as_well_as_the_failure(self) -> None:
        # A user told "validation failed" learns nothing; one told which five
        # things were checked and which one moved learns what happened.
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        verdict = validate(assessment, policy=Policy(prefer_low_energy=True))
        names = [item["check"] for item in verdict.checked]
        self.assertIn("plan.schemaVersion", names)
        self.assertIn("fingerprint.inventory", names)
        self.assertTrue(any(item["satisfied"] for item in verdict.checked))
        self.assertTrue(any(not item["satisfied"] for item in verdict.checked))

    def test_validation_never_alters_the_plan(self) -> None:
        assessment = assess(simulate("laptop"), registry=REGISTRY)
        before = assessment.plan.to_json()
        validate(assessment, inventory=simulate("cpu-server"))
        self.assertEqual(assessment.plan.to_json(), before)


class TransitionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assessment = assess(simulate("laptop"), registry=REGISTRY)

    def test_a_transition_that_fits_validates(self) -> None:
        verdict = revalidate_transition(
            desired(), budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=512 * MIB,
        )
        self.assertTrue(verdict.ok, verdict.problems)

    def test_a_transition_that_no_longer_fits_is_refused(self) -> None:
        verdict = revalidate_transition(
            desired(memory_limit_bytes=512 * MIB),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=64 * MIB,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "insufficient_resources")

    def test_a_transition_that_would_breach_the_protected_reserve_is_refused(self) -> None:
        # The reserve is checked independently of the budget even though the
        # budget already excludes it: two statements of one invariant.
        tight = replace(
            self.assessment.budget,
            currently_available_bytes=200 * MIB,
            protected_reserve_bytes=128 * MIB,
        )
        verdict = revalidate_transition(
            desired(memory_limit_bytes=150 * MIB),
            budget=tight, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=8 * GIB,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "protected_reserve_violation")
        self.assertTrue(any("protected reserve" in item for item in verdict.problems))

    def test_a_dependency_that_disappeared_is_refused(self) -> None:
        verdict = revalidate_transition(
            desired(requires=("b.dependency",)),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=8 * GIB,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "dependency_unavailable")

    def test_a_dependency_that_is_up_passes(self) -> None:
        up = ActualState({"b.dependency": ServiceObservation(
            "b.dependency", "running", observed_by="in-memory",
        )})
        verdict = revalidate_transition(
            desired(requires=("b.dependency",)),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=up, available_bytes=8 * GIB,
        )
        self.assertTrue(verdict.ok, verdict.problems)

    def test_a_missing_approval_is_refused(self) -> None:
        verdict = revalidate_transition(
            desired(requires_approval=True),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=8 * GIB, approvals=(),
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "approval_missing")

    def test_a_valid_approval_passes(self) -> None:
        verdict = revalidate_transition(
            desired(requires_approval=True),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=8 * GIB, approvals=("a.one",),
        )
        self.assertTrue(verdict.ok, verdict.problems)

    def test_remote_execution_withdrawn_after_generation_is_refused(self) -> None:
        verdict = revalidate_transition(
            desired(locality="remote", memory_limit_bytes=8 * MIB),
            budget=self.assessment.budget, policy=Policy(),
            actual=ActualState(), available_bytes=8 * GIB,
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.failure_class, "stale_plan")
        self.assertTrue(any("no longer permitted" in item for item in verdict.problems))

    def test_a_remote_transition_passes_while_remote_execution_is_permitted(self) -> None:
        permitted = Policy(remote_execution=RemoteExecutionPolicy(
            enabled=True, require_user_approval=False, permitted_providers=("test",),
        ))
        verdict = revalidate_transition(
            desired(locality="remote", memory_limit_bytes=8 * MIB),
            budget=self.assessment.budget, policy=permitted,
            actual=ActualState(), available_bytes=8 * GIB,
        )
        self.assertTrue(verdict.ok, verdict.problems)

    def test_the_first_failure_class_reported_is_the_most_decisive(self) -> None:
        # Insufficient resources and a missing dependency at once should report
        # the resource problem, because that is what a reevaluation can fix.
        verdict = revalidate_transition(
            desired(memory_limit_bytes=512 * MIB, requires=("b.gone",)),
            budget=self.assessment.budget, policy=self.assessment.policy,
            actual=ActualState(), available_bytes=8 * MIB,
        )
        self.assertEqual(verdict.failure_class, "insufficient_resources")
        self.assertEqual(len(verdict.problems), 2)


if __name__ == "__main__":
    unittest.main()

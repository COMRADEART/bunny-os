# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Task routing: local incapability is never an argument for remote execution."""

from __future__ import annotations

from dataclasses import dataclass
import unittest

from capability.budget import compute_budget
from capability.policy import Policy, RemoteExecutionPolicy
from capability.router import (
    NullProvider,
    ProviderDeclaration,
    TaskRequest,
    route,
)
from capability.scores import compute_scores
from capability.simulate import machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3


@dataclass(frozen=True)
class StubProvider:
    """A test double. No real provider integration exists in this repository."""

    declaration: ProviderDeclaration
    reachable: bool = True

    def available(self) -> bool:
        return self.reachable


def declared(identifier: str = "test-provider", **overrides) -> ProviderDeclaration:
    fields = {
        "id": identifier,
        "title": "Test provider",
        "locality": "hosted",
        "retention": "none",
        "trains_on_input": False,
        "costs_money": False,
        "capabilities": ("inference", "tts"),
        "jurisdiction": "unspecified",
    }
    fields.update(overrides)
    return ProviderDeclaration(**fields)


def context(name: str = "raspberry-pi-class", policy: Policy | None = None):
    inventory = simulate(name)
    scores = compute_scores(inventory)
    resolved = policy or Policy()
    budget = compute_budget(inventory, scores, resolved, essential_floor_bytes=28 * MIB)
    return inventory, scores, budget, resolved


def permissive(**overrides) -> Policy:
    fields = {
        "metered_network_allowed": True,
        "confirm_before_paid_api": False,
        "remote_execution": RemoteExecutionPolicy(
            enabled=True, require_user_approval=False, allow_sensitive_data=True,
            permitted_providers=("test-provider",),
        ),
    }
    fields.update(overrides)
    return Policy(**fields)


class LocalPreferenceTests(unittest.TestCase):
    def test_a_task_that_fits_locally_runs_locally(self) -> None:
        inventory, scores, budget, policy = context("gaming-desktop")
        task = TaskRequest(id="t1", capability="inference", local_memory_bytes=64 * MIB)
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "local")
        self.assertIsNone(decision.provider_id)

    def test_local_is_preferred_even_when_a_provider_is_available(self) -> None:
        inventory, scores, budget, _ = context("gaming-desktop")
        task = TaskRequest(id="t2", capability="inference", local_memory_bytes=32 * MIB)
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "local")

    def test_a_local_score_requirement_is_enforced(self) -> None:
        inventory, scores, budget, policy = context("embedded-64mb")
        task = TaskRequest(id="t3", capability="inference", local_requirements={"local_ai": 50.0})
        decision = route(task, inventory, scores, budget, policy)
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("local_ai" in reason for reason in decision.reasons))

    def test_an_unmeasured_dimension_does_not_satisfy_a_local_requirement(self) -> None:
        inventory, scores, budget, policy = context("unmeasurable")
        task = TaskRequest(id="t4", capability="inference", local_requirements={"local_ai": 1.0})
        decision = route(task, inventory, scores, budget, policy)
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("unmeasured" in reason for reason in decision.reasons))


class SensitivityTests(unittest.TestCase):
    """Sensitive work stays local, whatever the machine cannot do."""

    def test_a_secret_task_is_refused_rather_than_sent(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="t5", capability="inference", privacy="secret",
            local_memory_bytes=8 * GIB, maximum_cost_units=1000,
        )
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("secret" in reason for reason in decision.reasons))
        self.assertIsNone(decision.provider_id)

    def test_a_device_only_task_is_refused_rather_than_sent(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="t6", capability="inference", data_locality="device-only",
            local_memory_bytes=8 * GIB, maximum_cost_units=1000,
        )
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")

    def test_a_sensitive_task_needs_explicit_permission_even_with_remote_enabled(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        policy = permissive(remote_execution=RemoteExecutionPolicy(
            enabled=True, require_user_approval=False, allow_sensitive_data=False,
            permitted_providers=("test-provider",),
        ))
        task = TaskRequest(
            id="t7", capability="inference", privacy="sensitive",
            local_memory_bytes=8 * GIB, maximum_cost_units=1000,
        )
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("allowSensitiveData" in reason for reason in decision.reasons))

    def test_a_weak_machine_does_not_acquire_permission_by_being_weak(self) -> None:
        # The same task on the weakest and strongest machines: the weak one is
        # refused, and the reason is never "the machine is weak".
        strong_inventory, strong_scores, strong_budget, _ = context("gaming-desktop")
        weak_inventory, weak_scores, weak_budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="t8", capability="inference", privacy="secret", local_memory_bytes=64 * MIB,
        )
        strong = route(task, strong_inventory, strong_scores, strong_budget, permissive())
        weak = route(task, weak_inventory, weak_scores, weak_budget, permissive(), [StubProvider(declared())])
        self.assertEqual(strong.target, "local")
        self.assertEqual(weak.target, "refused")

    def test_an_offline_requirement_prevents_remote_execution(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="t9", capability="inference", requires_offline=True,
            local_memory_bytes=8 * GIB, maximum_cost_units=1000,
        )
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")

    def test_may_ever_leave_device_is_decided_before_any_hardware_is_read(self) -> None:
        self.assertFalse(TaskRequest(id="a", capability="x", privacy="secret").may_ever_leave_device)
        self.assertFalse(TaskRequest(id="b", capability="x", data_locality="device-only").may_ever_leave_device)
        self.assertFalse(TaskRequest(id="c", capability="x", requires_offline=True).may_ever_leave_device)
        self.assertFalse(TaskRequest(id="d", capability="x", remote_allowed=False).may_ever_leave_device)
        self.assertTrue(TaskRequest(id="e", capability="x").may_ever_leave_device)


class RemotePolicyTests(unittest.TestCase):
    def test_remote_is_refused_by_default(self) -> None:
        inventory, scores, budget, policy = context("embedded-64mb")
        task = TaskRequest(id="r1", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("disabled in policy" in reason for reason in decision.reasons))

    def test_a_permitted_provider_receives_the_task(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(id="r2", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "remote")
        self.assertEqual(decision.provider_id, "test-provider")

    def test_an_undeclared_provider_fails_closed(self) -> None:
        # A provider that will not say whether it trains on input cannot be the
        # destination for a decision the user is entitled to understand.
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(trains_on_input=None))
        task = TaskRequest(id="r3", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("undeclared provider fails closed" in reason for reason in decision.reasons))

    def test_an_unspecified_retention_fails_closed(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(retention="unspecified"))
        task = TaskRequest(id="r4", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "refused")

    def test_a_provider_that_does_not_serve_the_capability_is_skipped(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(capabilities=("stt",)))
        task = TaskRequest(id="r5", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("no permitted, fully declared provider" in reason for reason in decision.reasons))

    def test_a_paid_provider_is_refused_when_the_task_permits_no_spend(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(costs_money=True))
        task = TaskRequest(id="r6", capability="inference", local_memory_bytes=8 * GIB, maximum_cost_units=0)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("permits no spend" in reason for reason in decision.reasons))

    def test_a_paid_provider_is_used_when_the_task_permits_spend(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(costs_money=True))
        task = TaskRequest(id="r7", capability="inference", local_memory_bytes=8 * GIB, maximum_cost_units=500)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "remote")

    def test_user_approval_is_required_when_policy_says_so(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        policy = permissive(remote_execution=RemoteExecutionPolicy(
            enabled=True, require_user_approval=True, allow_sensitive_data=True,
            permitted_providers=("test-provider",),
        ))
        task = TaskRequest(id="r8", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(decision.requires_user_approval)
        self.assertEqual(decision.provider_id, "test-provider")

    def test_an_approved_task_is_dispatched(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        policy = permissive(remote_execution=RemoteExecutionPolicy(
            enabled=True, require_user_approval=True, allow_sensitive_data=True,
            permitted_providers=("test-provider",),
        ))
        task = TaskRequest(id="r9", capability="inference", local_memory_bytes=8 * GIB, user_approved=True)
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "remote")

    def test_an_unreachable_provider_is_reported_rather_than_used(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        provider = StubProvider(declared(), reachable=False)
        task = TaskRequest(id="r10", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [provider])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("not currently available" in reason for reason in decision.reasons))

    def test_an_offline_machine_dispatches_nothing(self) -> None:
        inventory, scores, budget, _ = context("offline-laptop")
        task = TaskRequest(id="r11", capability="inference", local_memory_bytes=64 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("no usable network route" in reason for reason in decision.reasons))

    def test_a_metered_connection_blocks_dispatch_by_default(self) -> None:
        inventory = machine(physical_memory_bytes=1 * GIB, metered=True)
        scores = compute_scores(inventory)
        policy = permissive(metered_network_allowed=False)
        budget = compute_budget(inventory, scores, policy, essential_floor_bytes=28 * MIB)
        task = TaskRequest(id="r12", capability="inference", local_memory_bytes=64 * GIB)
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "refused")
        self.assertTrue(any("metered" in reason for reason in decision.reasons))


class DisclosureTests(unittest.TestCase):
    def test_a_remote_decision_carries_a_complete_disclosure(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(id="d1", capability="inference", local_memory_bytes=8 * GIB)
        decision = route(task, inventory, scores, budget, permissive(), [StubProvider(declared())])
        self.assertEqual(decision.target, "remote")
        disclosure = decision.disclosure
        self.assertEqual(disclosure["provider"]["id"], "test-provider")
        self.assertEqual(disclosure["provider"]["retention"], "none")
        self.assertIs(disclosure["provider"]["trainsOnInput"], False)
        self.assertIn("whatLeavesTheDevice", disclosure)

    def test_every_decision_states_at_least_one_reason(self) -> None:
        inventory, scores, budget, policy = context("laptop")
        for privacy in ("public", "internal", "sensitive", "secret"):
            with self.subTest(privacy=privacy):
                task = TaskRequest(id=f"x-{privacy}", capability="inference", privacy=privacy,
                                   local_memory_bytes=8 * GIB)
                self.assertTrue(route(task, inventory, scores, budget, policy).reasons)


class ValidationTests(unittest.TestCase):
    def test_an_unknown_privacy_class_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            TaskRequest(id="v1", capability="x", privacy="top-secret")

    def test_an_unknown_data_locality_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            TaskRequest(id="v2", capability="x", data_locality="somewhere-nice")

    def test_the_null_provider_declares_and_accepts_nothing(self) -> None:
        provider = NullProvider()
        self.assertFalse(provider.available())
        self.assertFalse(provider.declaration.fully_declared)
        self.assertEqual(provider.declaration.capabilities, ())


if __name__ == "__main__":
    unittest.main()

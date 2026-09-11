# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""ADR 0012 escalation ladder: observables only, no confidence, no silent hop."""

from __future__ import annotations

from dataclasses import dataclass
import unittest

from capability.budget import compute_budget
from capability.escalation import (
    PLAN_STEPS_AT,
    EscalationObservables,
    assess_escalation,
    crosses_privacy_boundary,
    refuse_silent_failover,
)
from capability.policy import Policy, RemoteExecutionPolicy
from capability.router import (
    ProviderDeclaration,
    TaskRequest,
    route,
)
from capability.scores import compute_scores
from capability.simulate import simulate

MIB = 1024 ** 2
GIB = 1024 ** 3


@dataclass(frozen=True)
class StubProvider:
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


class ObservablesShape(unittest.TestCase):
    def test_there_is_no_confidence_field(self) -> None:
        self.assertNotIn("confidence", EscalationObservables.__dataclass_fields__)
        self.assertNotIn("self_reported_confidence", EscalationObservables.__dataclass_fields__)

    def test_unknown_n_ctx_does_not_fire_overflow(self) -> None:
        decision = assess_escalation(
            EscalationObservables(estimated_context_tokens=100_000, true_n_ctx=None),
            local_feasible=False,
        )
        self.assertNotIn("n_ctx-overflow", decision.fired)

    def test_known_n_ctx_overflow_fires(self) -> None:
        decision = assess_escalation(
            EscalationObservables(
                estimated_context_tokens=9000,
                true_n_ctx=4096,
                local_generation_failed=True,
            ),
            local_feasible=False,
        )
        self.assertIn("n_ctx-overflow", decision.fired)
        self.assertTrue(decision.consider_remote or decision.consent_required)


class Ladder(unittest.TestCase):
    def test_a_short_plan_that_still_fits_stays_local(self) -> None:
        decision = assess_escalation(
            EscalationObservables(plan_step_count=PLAN_STEPS_AT),
            local_feasible=True,
        )
        self.assertEqual(decision.action, "stay-local")
        self.assertFalse(decision.consider_remote)

    def test_schema_failures_plus_local_failure_consider_remote_with_consent(self) -> None:
        decision = assess_escalation(
            EscalationObservables(
                tool_schema_failures=2,
                local_generation_failed=True,
                current_locality="loopback",
                candidate_locality="hosted",
                user_consented=False,
            ),
            local_feasible=False,
        )
        self.assertTrue(decision.consent_required)
        self.assertTrue(decision.silent_failover_refused)
        self.assertEqual(decision.action, "consent-required")

    def test_missing_capability_is_an_observable(self) -> None:
        decision = assess_escalation(
            EscalationObservables(missing_capability="vision"),
            local_feasible=True,
        )
        self.assertIn("missing-capability", decision.fired)

    def test_unhealthy_provider_is_an_observable(self) -> None:
        decision = assess_escalation(
            EscalationObservables(provider_healthy=False),
            local_feasible=True,
        )
        self.assertIn("provider-health", decision.fired)


class LocalityBoundary(unittest.TestCase):
    def test_hosted_is_more_public_than_loopback(self) -> None:
        self.assertTrue(crosses_privacy_boundary("loopback", "hosted"))
        self.assertFalse(crosses_privacy_boundary("hosted", "loopback"))

    def test_silent_failover_is_refused_without_consent(self) -> None:
        refusal = refuse_silent_failover(
            current_locality="device-only",
            candidate_locality="hosted",
            user_consented=False,
        )
        self.assertIsNotNone(refusal)
        assert refusal is not None
        self.assertTrue(refusal.silent_failover_refused)
        self.assertIn("security boundary", refusal.reasons[0])

    def test_consent_clears_the_silent_failover_refusal(self) -> None:
        self.assertIsNone(refuse_silent_failover(
            current_locality="loopback",
            candidate_locality="hosted",
            user_consented=True,
        ))


class RouterEscalation(unittest.TestCase):
    def test_local_still_wins_when_observables_fire_but_the_machine_fits(self) -> None:
        inventory, scores, budget, policy = context("gaming-desktop")
        task = TaskRequest(
            id="e1",
            capability="inference",
            local_memory_bytes=64 * 1024 * 1024,
            escalation=EscalationObservables(plan_step_count=12),
        )
        decision = route(task, inventory, scores, budget, policy, [StubProvider(declared())])
        self.assertEqual(decision.target, "local")

    def test_device_only_plus_local_failure_does_not_hop_hosted(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="e2",
            capability="inference",
            data_locality="device-only",
            local_memory_bytes=8 * 1024 ** 3,
            escalation=EscalationObservables(
                local_generation_failed=True,
                tool_schema_failures=3,
                current_locality="device-only",
                candidate_locality="hosted",
            ),
        )
        decision = route(
            task, inventory, scores, budget, permissive(), [StubProvider(declared())],
        )
        self.assertEqual(decision.target, "refused")
        self.assertIsNone(decision.provider_id)
        self.assertTrue(any("device-only" in reason for reason in decision.reasons))

    def test_a_disclosed_hosted_hop_is_labelled_not_a_failover(self) -> None:
        inventory, scores, budget, _ = context("embedded-64mb")
        task = TaskRequest(
            id="e3", capability="inference", local_memory_bytes=8 * 1024 ** 3,
        )
        decision = route(
            task, inventory, scores, budget, permissive(), [StubProvider(declared())],
        )
        self.assertEqual(decision.target, "remote")
        self.assertTrue(any("not a silent failover" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()

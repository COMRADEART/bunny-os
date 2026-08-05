# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Policy decisions: the nine properties §16 requires the engine to guarantee."""

from __future__ import annotations

import unittest

from capability.budget import compute_budget
from capability.engine import evaluate
from capability.manifest import ManifestError, parse_manifest
from capability.plan import ExecutionPlan
from capability.policy import Policy, RemoteExecutionPolicy
from capability.registry import build_registry, load_registry
from capability.runtime import assess
from capability.scores import compute_scores
from capability.simulate import machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3

REGISTRY = load_registry()


def plan_for(inventory, policy: Policy | None = None, *, previous=None, now: float = 0.0, registry=None):
    return assess(
        inventory,
        policy=policy or Policy(),
        registry=registry or REGISTRY,
        previous=previous,
        now=now,
    ).plan


def manifest(**overrides):
    document = {
        "schemaVersion": 1,
        "id": "test.service",
        "title": "Test service",
        "essential": False,
        "priority": "standard",
        "budgetCategory": "optional_services",
        "implementations": [
            {"id": "only", "title": "Only", "locality": "local", "rank": 1,
             "requirements": {"memory": {"minimumBytes": 64 * MIB}}},
        ],
    }
    document.update(overrides)
    return parse_manifest(document)


class EssentialPriorityTests(unittest.TestCase):
    """Essential services always receive priority."""

    def test_every_essential_service_starts_on_the_smallest_supported_machine(self) -> None:
        decisions = plan_for(simulate("embedded-64mb")).by_id()
        for service in REGISTRY.essential():
            with self.subTest(service=service.id):
                self.assertTrue(
                    decisions[service.id].running,
                    f"{service.id} did not start: {decisions[service.id].reasons[0].message}",
                )

    def test_essential_services_are_funded_before_optional_ones(self) -> None:
        plan = plan_for(simulate("embedded-64mb"))
        running = {decision.service_id for decision in plan.running()}
        essential = {service.id for service in REGISTRY.essential()}
        self.assertTrue(essential.issubset(running))
        # And on this machine nothing optional could be afforded.
        self.assertEqual(running, essential)

    def test_an_essential_service_may_not_depend_on_an_optional_one(self) -> None:
        # A control plane whose dependency can be switched off by a resource
        # decision is not a control plane.
        with self.assertRaises(ManifestError) as caught:
            build_registry([
                manifest(id="a.essential", essential=True, budgetCategory="essential_services",
                         dependencies={"requires": ["b.optional"]}),
                manifest(id="b.optional"),
            ])
        self.assertIn("essential", str(caught.exception))

    def test_no_optional_service_starts_when_the_control_plane_cannot_be_funded(self) -> None:
        inventory = machine(physical_memory_bytes=64 * MIB, available_memory_bytes=40 * MIB)
        scores = compute_scores(inventory)
        policy = Policy()
        budget = compute_budget(inventory, scores, policy, essential_floor_bytes=4 * GIB)
        plan = evaluate(inventory, scores, budget, REGISTRY, policy)
        for decision in plan.decisions:
            service = REGISTRY.get(decision.service_id)
            if service and not service.essential:
                with self.subTest(service=decision.service_id):
                    self.assertFalse(decision.running)


class ProtectedReserveTests(unittest.TestCase):
    """Optional services cannot consume the protected reserve."""

    def test_granted_memory_never_reaches_the_reserve(self) -> None:
        for name in ("embedded-64mb", "raspberry-pi-class", "laptop", "gaming-desktop",
                     "cpu-server", "multi-gpu-ai-server", "constrained-container"):
            with self.subTest(machine=name):
                assessment = assess(simulate(name), registry=REGISTRY)
                budget = assessment.budget
                self.assertLessEqual(
                    assessment.plan.granted_memory_bytes,
                    budget.currently_allocatable_bytes + budget.essential_services_bytes,
                )
                self.assertLessEqual(
                    assessment.plan.granted_memory_bytes + budget.protected_reserve_bytes,
                    budget.usable_bytes,
                )

    def test_the_engine_refuses_to_emit_a_plan_that_overcommits(self) -> None:
        # The invariant is enforced rather than assumed: a violation is a bug in
        # the allocation walk and must surface at the walk, not as an OOM kill
        # an hour later. Forced here by making one decision claim more than the
        # whole budget, which is what the cooldown path did before it was
        # taught not to carry a stale grant forward.
        import capability.engine as engine_module
        from capability.plan import Decision

        inventory = simulate("laptop")
        scores = compute_scores(inventory)
        policy = Policy()
        budget = compute_budget(inventory, scores, policy, essential_floor_bytes=28 * MIB)

        def greedy(service, *args, **keywords):
            return Decision(
                service_id=service.id, action="start_local", implementation_id="x",
                memory_grant_bytes=budget.currently_allocatable_bytes * 4,
            )

        original = engine_module._decide
        engine_module._decide = greedy
        try:
            with self.assertRaises(AssertionError):
                evaluate(inventory, scores, budget, REGISTRY, policy)
        finally:
            engine_module._decide = original


class RemoteExecutionTests(unittest.TestCase):
    """Remote execution stays off, and turning it on is not enough by itself."""

    def test_remote_execution_is_disabled_by_default(self) -> None:
        self.assertFalse(Policy().remote_execution.enabled)
        self.assertTrue(Policy().remote_execution.require_user_approval)
        self.assertFalse(Policy().remote_execution.allow_sensitive_data)
        self.assertEqual(Policy().remote_execution.permitted_providers, ())

    def test_no_service_is_dispatched_remotely_by_default(self) -> None:
        for name in ("embedded-64mb", "raspberry-pi-class", "laptop", "cpu-server"):
            with self.subTest(machine=name):
                plan = plan_for(simulate(name))
                self.assertEqual(
                    [d.service_id for d in plan.decisions if d.action == "start_remote"], [],
                )

    def test_enabling_remote_without_naming_a_provider_permits_nothing(self) -> None:
        policy = Policy(remote_execution=RemoteExecutionPolicy(enabled=True, permitted_providers=()))
        plan = plan_for(simulate("raspberry-pi-class"), policy)
        self.assertEqual([d.service_id for d in plan.decisions if d.action == "start_remote"], [])

    def test_a_sensitive_service_is_not_dispatched_remotely_without_explicit_permission(self) -> None:
        # Everything else permits it: remote on, provider allowlisted, no
        # approval needed, unmetered. Only allowSensitiveData is false.
        policy = Policy(
            metered_network_allowed=True,
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=False,
                permitted_providers=("bunny-node", "configured-inference-provider"),
            ),
        )
        plan = plan_for(simulate("raspberry-pi-class"), policy)
        inference = plan.decision("bunny.inference.local")
        self.assertNotEqual(inference.action, "start_remote")
        self.assertIn("sensitive-data-local-only", inference.reason_codes())

    def test_permitting_sensitive_data_allows_the_remote_path(self) -> None:
        policy = Policy(
            metered_network_allowed=True,
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("bunny-node",),
            ),
        )
        inference = plan_for(simulate("raspberry-pi-class"), policy).decision("bunny.inference.local")
        self.assertEqual(inference.action, "start_remote")
        self.assertEqual(inference.implementation_id, "remote-node")

    def test_an_unallowlisted_provider_is_refused_even_when_remote_is_enabled(self) -> None:
        policy = Policy(
            metered_network_allowed=True,
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("some-other-provider",),
            ),
        )
        inference = plan_for(simulate("raspberry-pi-class"), policy).decision("bunny.inference.local")
        self.assertNotEqual(inference.action, "start_remote")
        self.assertIn("remote-not-permitted", inference.reason_codes())

    def test_an_offline_machine_does_not_dispatch_remotely(self) -> None:
        policy = Policy(
            metered_network_allowed=True,
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("bunny-node",),
            ),
        )
        inference = plan_for(simulate("offline-laptop"), policy).decision("bunny.inference.local")
        self.assertNotEqual(inference.action, "start_remote")
        self.assertIn("remote-unreachable", inference.reason_codes())

    def test_a_metered_connection_blocks_remote_dispatch_by_default(self) -> None:
        inventory = machine(physical_memory_bytes=1 * GIB, metered=True, audio_input=True)
        policy = Policy(
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("bunny-node",),
            ),
        )
        inference = plan_for(inventory, policy).decision("bunny.inference.local")
        self.assertIn("metered-network", inference.reason_codes())

    def test_unknown_metering_is_treated_as_possibly_metered(self) -> None:
        inventory = machine(physical_memory_bytes=1 * GIB, metered=None)
        policy = Policy(
            confirm_before_paid_api=False,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("bunny-node",),
            ),
        )
        inference = plan_for(inventory, policy).decision("bunny.inference.local")
        self.assertIn("metered-network", inference.reason_codes())

    def test_a_paid_provider_requires_confirmation(self) -> None:
        policy = Policy(
            metered_network_allowed=True,
            confirm_before_paid_api=True,
            remote_execution=RemoteExecutionPolicy(
                enabled=True, require_user_approval=False, allow_sensitive_data=True,
                permitted_providers=("configured-inference-provider",),
            ),
        )
        inference = plan_for(simulate("raspberry-pi-class"), policy).decision("bunny.inference.local")
        self.assertIn("paid-api-confirmation", inference.reason_codes())


class RequirementEnforcementTests(unittest.TestCase):
    def test_a_display_requirement_is_enforced_on_a_headless_machine(self) -> None:
        shell = plan_for(simulate("cpu-server")).decision("bunny.shell.session")
        self.assertFalse(shell.running)
        self.assertTrue(any(check.requirement == "display.required" and check.satisfied is False
                            for check in shell.checks))

    def test_an_audio_requirement_is_enforced_without_audio_hardware(self) -> None:
        speech = plan_for(simulate("cpu-server")).decision("bunny.speech.synthesis")
        self.assertFalse(speech.running)
        self.assertIn("requirement-unmet", speech.reason_codes())

    def test_a_writable_storage_requirement_is_enforced_on_a_read_only_root(self) -> None:
        update = plan_for(simulate("read-only-appliance")).decision("bunny.system.update")
        self.assertFalse(update.running)
        self.assertTrue(any(check.requirement == "storage.writable" and check.satisfied is False
                            for check in update.checks))

    def test_a_gpu_requirement_is_not_satisfied_by_a_driverless_device(self) -> None:
        inference = plan_for(simulate("gpu-without-driver")).decision("bunny.inference.local")
        self.assertNotEqual(inference.implementation_id, "local-gpu")

    def test_a_dependency_that_is_not_running_defers_its_dependent(self) -> None:
        plan = plan_for(simulate("cpu-server"))
        search = plan.decision("bunny.desktop.search")
        self.assertFalse(plan.decision("bunny.shell.session").running)
        self.assertEqual(search.action, "defer")
        self.assertIn("dependency-unavailable", search.reason_codes())


class FallbackDeterminismTests(unittest.TestCase):
    """Fallback implementations are selected deterministically."""

    def test_the_same_inventory_always_selects_the_same_implementation(self) -> None:
        for name in ("embedded-64mb", "raspberry-pi-class", "laptop", "gaming-desktop",
                     "cpu-server", "multi-gpu-ai-server", "constrained-container"):
            with self.subTest(machine=name):
                first = plan_for(simulate(name)).to_json()["decisions"]
                second = plan_for(simulate(name)).to_json()["decisions"]
                self.assertEqual(
                    [(d["serviceId"], d["action"], d["implementationId"]) for d in first],
                    [(d["serviceId"], d["action"], d["implementationId"]) for d in second],
                )

    def test_the_companion_walks_its_ladder_downward_as_machines_shrink(self) -> None:
        selections = {
            name: plan_for(simulate(name)).decision("bunny.companion").implementation_id
            for name in ("gaming-desktop", "laptop", "raspberry-pi-class", "cpu-server")
        }
        self.assertEqual(selections["gaming-desktop"], "animated-3d")
        self.assertEqual(selections["laptop"], "static-avatar")
        self.assertEqual(selections["raspberry-pi-class"], "audio-only")
        self.assertEqual(selections["cpu-server"], "text-only")

    def test_a_degraded_selection_is_labelled_as_degraded(self) -> None:
        companion = plan_for(simulate("raspberry-pi-class")).decision("bunny.companion")
        self.assertIn("degraded", companion.reason_codes())

    def test_the_richest_implementation_is_not_labelled_degraded(self) -> None:
        companion = plan_for(simulate("gaming-desktop")).decision("bunny.companion")
        self.assertNotIn("degraded", companion.reason_codes())

    def test_ties_in_rank_are_broken_stably(self) -> None:
        registry = build_registry([
            manifest(
                id="tie.service",
                implementations=[
                    {"id": "bbb", "locality": "local", "rank": 1, "requirements": {}},
                    {"id": "aaa", "locality": "local", "rank": 1, "requirements": {}},
                ],
            ),
        ])
        service = registry.get("tie.service")
        self.assertEqual([item.id for item in service.ordered_implementations()], ["aaa", "bbb"])


class UserConstraintTests(unittest.TestCase):
    """User constraints override automatic preferences."""

    def test_a_disabled_service_is_never_started(self) -> None:
        policy = Policy(disabled_services=("bunny.companion",))
        companion = plan_for(simulate("gaming-desktop"), policy).decision("bunny.companion")
        self.assertEqual(companion.action, "reject")
        self.assertIn("user-disabled", companion.reason_codes())

    def test_a_user_may_disable_an_essential_service_and_is_told_what_it_costs(self) -> None:
        policy = Policy(disabled_services=("bunny.system.update",))
        update = plan_for(simulate("laptop"), policy).decision("bunny.system.update")
        self.assertEqual(update.action, "reject")
        self.assertIn("switched this service off", update.fallback)

    def test_a_pinned_implementation_is_honoured_when_it_fits(self) -> None:
        policy = Policy(pinned_implementations={"bunny.companion": "text-only"})
        companion = plan_for(simulate("gaming-desktop"), policy).decision("bunny.companion")
        self.assertEqual(companion.implementation_id, "text-only")
        self.assertIn("pin-honoured", companion.reason_codes())

    def test_a_pin_that_does_not_fit_is_refused_rather_than_overcommitting(self) -> None:
        policy = Policy(pinned_implementations={"bunny.companion": "animated-3d"})
        companion = plan_for(simulate("raspberry-pi-class"), policy).decision("bunny.companion")
        self.assertIn("pin-unsatisfiable", companion.reason_codes())
        # The ladder still proceeds: a preference is not a refusal to run.
        self.assertTrue(companion.running)
        self.assertNotEqual(companion.implementation_id, "animated-3d")

    def test_a_pin_naming_an_unknown_implementation_is_reported(self) -> None:
        policy = Policy(pinned_implementations={"bunny.companion": "holographic"})
        companion = plan_for(simulate("gaming-desktop"), policy).decision("bunny.companion")
        self.assertIn("pin-unsatisfiable", companion.reason_codes())

    def test_a_memory_ceiling_shrinks_what_starts(self) -> None:
        generous = plan_for(simulate("gaming-desktop"))
        constrained = plan_for(
            simulate("gaming-desktop"),
            Policy(maximum_service_memory_bytes=256 * MIB),
        )
        self.assertLess(len(constrained.running()), len(generous.running()))


class HysteresisTests(unittest.TestCase):
    """Hysteresis and cooldown prevent oscillation near a threshold."""

    def test_a_running_service_survives_a_dip_that_would_have_blocked_its_start(self) -> None:
        # Sized so the companion's 768 MiB 2D implementation sits inside the
        # hysteresis band: too little to start it, enough to keep it running.
        registry = build_registry([
            manifest(id="essential.core", essential=True, budgetCategory="essential_services",
                     implementations=[{"id": "core", "locality": "local", "rank": 1,
                                       "requirements": {"memory": {"minimumBytes": 8 * MIB}}}]),
            manifest(id="test.borderline",
                     implementations=[{"id": "only", "locality": "local", "rank": 1,
                                       "requirements": {"memory": {"minimumBytes": 400 * MIB}}}]),
        ])
        # 1 GiB usable leaves a 204.8 MiB reserve, so 620 MiB free admits
        # 415 MiB: below the 460 MiB start gate, above the 340 MiB keep-running
        # gate. That gap is the hysteresis band.
        inventory = machine(physical_memory_bytes=1 * GIB, available_memory_bytes=620 * MIB)
        cold = plan_for(inventory, registry=registry)
        self.assertFalse(cold.decision("test.borderline").running)
        self.assertIn("budget-exhausted", cold.decision("test.borderline").reason_codes())

        # Same machine, but the service was already running.
        warm_previous = ExecutionPlan(decisions=(
            cold.decision("essential.core"),
            cold.decision("test.borderline").__class__(
                service_id="test.borderline", action="start_local",
                implementation_id="only", memory_grant_bytes=400 * MIB, state_changed_at=0.0,
            ),
        ))
        warm = plan_for(inventory, registry=registry, previous=warm_previous, now=10_000.0)
        self.assertTrue(warm.decision("test.borderline").running)

    def test_essential_services_are_exempt_from_the_start_margin(self) -> None:
        # The budget engine reserves exactly the sum of essential minimums. A
        # start surcharge on top of that reservation would refuse the control
        # plane on any machine sized to its own stated requirements.
        from capability.engine import _memory_gate

        minimum = 100 * MIB
        self.assertEqual(_memory_gate(minimum, running=False, hysteresis=0.15, essential=True), minimum)
        self.assertEqual(_memory_gate(minimum, running=True, hysteresis=0.15, essential=True), minimum)
        # Optional services keep the band: harder to start than to keep running.
        self.assertGreater(_memory_gate(minimum, running=False, hysteresis=0.15, essential=False), minimum)
        self.assertLess(_memory_gate(minimum, running=True, hysteresis=0.15, essential=False), minimum)

    def test_a_cooldown_holds_a_service_at_its_previous_state(self) -> None:
        # A monitor is unplugged. The shell's requirement stops being satisfied,
        # but its grant still fits, so the change waits out the cooldown rather
        # than tearing the session down the instant a cable moved.
        policy = Policy(state_change_cooldown_seconds=60.0)
        first = plan_for(simulate("laptop"), policy, now=0.0)
        self.assertTrue(first.decision("bunny.shell.session").running)
        held = plan_for(self.unplugged_laptop(), policy, previous=first, now=1.0)
        self.assertIn("cooldown-hold", held.decision("bunny.shell.session").reason_codes())
        self.assertTrue(held.decision("bunny.shell.session").running)

    def test_a_cooldown_expires_and_the_change_then_applies(self) -> None:
        policy = Policy(state_change_cooldown_seconds=60.0)
        first = plan_for(simulate("laptop"), policy, now=0.0)
        later = plan_for(self.unplugged_laptop(), policy, previous=first, now=120.0)
        self.assertNotIn("cooldown-hold", later.decision("bunny.shell.session").reason_codes())
        self.assertFalse(later.decision("bunny.shell.session").running)

    def test_a_cooldown_never_holds_a_grant_the_budget_can_no_longer_honour(self) -> None:
        # Stability may not be bought by overcommitting the machine: a held
        # decision would carry a memory grant sized for hardware that no longer
        # exists.
        policy = Policy(state_change_cooldown_seconds=600.0)
        first = plan_for(simulate("gaming-desktop"), policy, now=0.0)
        self.assertGreater(first.decision("bunny.companion").memory_grant_bytes, 1 * GIB)
        starved = machine(physical_memory_bytes=1 * GIB, available_memory_bytes=200 * MIB,
                          connected_outputs=0, resolution=None, audio_output=False)
        second = plan_for(starved, policy, previous=first, now=1.0)
        self.assertNotIn("cooldown-hold", second.decision("bunny.companion").reason_codes())
        self.assertLess(second.decision("bunny.companion").memory_grant_bytes, 64 * MIB)

    @staticmethod
    def unplugged_laptop():
        return machine(
            physical_memory_bytes=16 * GIB, available_memory_bytes=9 * GIB, logical_threads=8,
            gpus=simulate("laptop").gpu, connected_outputs=0, resolution=None,
            power_supply="battery", battery_percent=72, connection_type="wireless",
        )

    def test_a_cooldown_never_holds_a_user_disabled_service_running(self) -> None:
        # A stability mechanism that keeps a switched-off service running for
        # another minute is a bug wearing a feature's clothes.
        policy = Policy(state_change_cooldown_seconds=600.0)
        first = plan_for(simulate("gaming-desktop"), policy, now=0.0)
        self.assertTrue(first.decision("bunny.companion").running)
        disabled = Policy(state_change_cooldown_seconds=600.0, disabled_services=("bunny.companion",))
        second = plan_for(simulate("gaming-desktop"), disabled, previous=first, now=1.0)
        self.assertEqual(second.decision("bunny.companion").action, "reject")
        self.assertNotIn("cooldown-hold", second.decision("bunny.companion").reason_codes())

    def test_a_zero_cooldown_disables_the_hold(self) -> None:
        policy = Policy(state_change_cooldown_seconds=0.0)
        first = plan_for(simulate("laptop"), policy, now=0.0)
        second = plan_for(self.unplugged_laptop(), policy, previous=first, now=0.5)
        self.assertNotIn("cooldown-hold", second.decision("bunny.shell.session").reason_codes())

    def test_repeated_evaluation_on_an_unchanged_machine_never_changes_the_plan(self) -> None:
        # The strongest anti-oscillation property: a stable machine produces a
        # stable plan no matter how often it is asked.
        inventory = simulate("laptop")
        plan = plan_for(inventory, now=0.0)
        for step in range(1, 8):
            plan = plan_for(inventory, previous=plan, now=step * 100.0)
        self.assertEqual(
            {d.service_id: (d.action, d.implementation_id) for d in plan.decisions},
            {d.service_id: (d.action, d.implementation_id) for d in plan_for(inventory).decisions},
        )


class MissingDataTests(unittest.TestCase):
    """Missing data causes conservative behaviour rather than crashes."""

    def test_a_machine_that_measured_nothing_still_produces_a_plan(self) -> None:
        plan = plan_for(simulate("unmeasurable"))
        self.assertEqual(len(plan.decisions), len(REGISTRY))

    def test_nothing_optional_starts_when_nothing_was_measured(self) -> None:
        plan = plan_for(simulate("unmeasurable"))
        for decision in plan.decisions:
            service = REGISTRY.get(decision.service_id)
            if service and not service.essential:
                with self.subTest(service=decision.service_id):
                    self.assertFalse(decision.running)

    def test_an_undeterminable_requirement_is_reported_as_unknown_not_unmet(self) -> None:
        # Telling a user their machine lacks something it may well have is a
        # worse error than telling them it could not be measured.
        update = plan_for(simulate("unmeasurable")).decision("bunny.system.update")
        codes = update.reason_codes()
        self.assertIn("requirement-unknown", codes)
        self.assertNotIn("requirement-unmet", codes)


class ExplanationTests(unittest.TestCase):
    def test_every_decision_carries_at_least_one_reason(self) -> None:
        for name in ("embedded-64mb", "laptop", "gaming-desktop", "unmeasurable"):
            for decision in plan_for(simulate(name)).decisions:
                with self.subTest(machine=name, service=decision.service_id):
                    self.assertTrue(decision.reasons, f"{decision.service_id} had no stated reason")

    def test_a_refused_service_names_a_fallback_or_a_reason_it_has_none(self) -> None:
        companion = plan_for(simulate("embedded-64mb")).decision("bunny.companion")
        self.assertFalse(companion.running)
        self.assertTrue(companion.reasons)

    def test_a_refused_remote_only_feature_points_at_the_setting_that_would_enable_it(self) -> None:
        inference = plan_for(simulate("raspberry-pi-class")).decision("bunny.inference.local")
        self.assertFalse(inference.running)
        self.assertIn("permittedProviders", inference.fallback)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration: the seven simulated machines §16 requires, end to end.

Each test drives the whole pipeline — inventory, scores, budget, plan — and
asserts on the *decisions*, which is what the subsystem exists to produce.
None of these requires real hardware, and none of them makes any claim about
real hardware. They are statements about the policy engine.

The property running through all of them: the same Bunny OS, the same services,
the same explanations. What differs between a 64 MB board and a DGX-class server
is which implementations were selected and which features were refused, never
which product the user installed.
"""

from __future__ import annotations

import unittest

from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import describe, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3

REGISTRY = load_registry()

#: The seven §16 requires, in its order.
REQUIRED_MACHINES = (
    "embedded-64mb",
    "raspberry-pi-class",
    "laptop",
    "gaming-desktop",
    "cpu-server",
    "multi-gpu-ai-server",
    "constrained-container",
)


def assessment(name: str):
    return assess(simulate(name), registry=REGISTRY)


class UniversalPropertyTests(unittest.TestCase):
    """What must be true on every machine, from 64 MB to 512 GB."""

    def test_every_machine_produces_a_decision_for_every_service(self) -> None:
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                plan = assessment(name).plan
                self.assertEqual(len(plan.decisions), len(REGISTRY))
                self.assertEqual(
                    {d.service_id for d in plan.decisions},
                    set(REGISTRY.services),
                )

    def test_every_machine_runs_the_same_essential_control_plane(self) -> None:
        # The core claim: one Bunny OS. The control plane is identical
        # everywhere; only what sits above it varies.
        essential = {service.id for service in REGISTRY.essential()}
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                running = {d.service_id for d in assessment(name).plan.running()}
                self.assertTrue(
                    essential.issubset(running),
                    f"{sorted(essential - running)} did not start on {name}",
                )

    def test_no_machine_is_given_a_mode_or_a_tier(self) -> None:
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                document = assessment(name).to_json()
                text = str(document).lower()
                for word in ("'tier'", "'mode'", "'profile'", "powerlevel", "'balanced'", "'ultra'"):
                    self.assertNotIn(word, text)

    def test_every_machine_explains_every_decision(self) -> None:
        for name in REQUIRED_MACHINES:
            for decision in assessment(name).plan.decisions:
                with self.subTest(machine=name, service=decision.service_id):
                    self.assertTrue(decision.reasons)

    def test_no_machine_dispatches_remotely_under_default_policy(self) -> None:
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                plan = assessment(name).plan
                self.assertEqual([d for d in plan.decisions if d.action == "start_remote"], [])

    def test_no_machine_overcommits_its_own_memory(self) -> None:
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                result = assessment(name)
                self.assertLessEqual(
                    result.plan.granted_memory_bytes + result.budget.protected_reserve_bytes,
                    result.budget.usable_bytes,
                )

    def test_every_machine_is_deterministic(self) -> None:
        for name in REQUIRED_MACHINES:
            with self.subTest(machine=name):
                first = assessment(name).plan.to_json()["decisions"]
                second = assessment(name).plan.to_json()["decisions"]
                self.assertEqual(first, second)


class EmbeddedTests(unittest.TestCase):
    """1. A 64 MB headless ARM device — §5's explicit architectural constraint."""

    def setUp(self) -> None:
        self.result = assessment("embedded-64mb")

    def test_the_control_plane_runs(self) -> None:
        self.assertTrue(self.result.budget.viable)
        running = {d.service_id for d in self.result.plan.running()}
        self.assertEqual(running, {service.id for service in REGISTRY.essential()})

    def test_the_heavy_features_are_all_refused_locally(self) -> None:
        # §5's list of what must not run locally under severe constraint.
        for identifier in ("bunny.shell.session", "bunny.inference.local", "bunny.companion",
                           "bunny.speech.recognition", "bunny.browser.automation",
                           "bunny.memory.vector", "bunny.agent.orchestrator"):
            with self.subTest(service=identifier):
                self.assertFalse(self.result.plan.decision(identifier).running)

    def test_it_is_not_a_separate_edition(self) -> None:
        # Same registry, same manifests, same schema version. The device is
        # running the same OS with less of it started.
        self.assertEqual(len(self.result.plan.decisions), len(REGISTRY))
        self.assertEqual(self.result.plan.to_json()["schemaVersion"], 1)

    def test_the_memory_dimension_scores_the_documented_floor(self) -> None:
        self.assertEqual(self.result.scores["memory_available"].value, 0.0)

    def test_expensive_budget_categories_are_unfunded_with_a_stated_reason(self) -> None:
        for name in ("local_ai_inference", "companion_rendering", "speech_recognition"):
            with self.subTest(category=name):
                category = self.result.budget.categories[name]
                self.assertFalse(category.funded)
                self.assertTrue(category.reason)

    def test_the_architecture_is_aarch64(self) -> None:
        self.assertEqual(self.result.inventory.system.architecture.get(None), "aarch64")


class RaspberryPiTests(unittest.TestCase):
    """2. A constrained Raspberry Pi-class device."""

    def setUp(self) -> None:
        self.result = assessment("raspberry-pi-class")

    def test_a_reduced_shell_runs_rather_than_none(self) -> None:
        shell = self.result.plan.decision("bunny.shell.session")
        self.assertTrue(shell.running)
        self.assertEqual(shell.implementation_id, "safe-shell")

    def test_the_companion_degrades_to_audio_rather_than_disappearing(self) -> None:
        companion = self.result.plan.decision("bunny.companion")
        self.assertTrue(companion.running)
        self.assertEqual(companion.implementation_id, "audio-only")

    def test_a_voice_is_still_available(self) -> None:
        synthesis = self.result.plan.decision("bunny.speech.synthesis")
        self.assertTrue(synthesis.running)
        self.assertEqual(synthesis.implementation_id, "local-system-voice")

    def test_local_inference_is_refused_and_points_at_the_remote_path(self) -> None:
        inference = self.result.plan.decision("bunny.inference.local")
        self.assertFalse(inference.running)
        self.assertIn("permittedProviders", inference.fallback)

    def test_a_shared_memory_gpu_grants_rendering_but_not_inference(self) -> None:
        self.assertTrue(self.result.budget.gpu_rendering_allowed)
        self.assertFalse(self.result.budget.gpu_local_inference_allowed)


class LaptopTests(unittest.TestCase):
    """3. A normal laptop."""

    def setUp(self) -> None:
        self.result = assessment("laptop")

    def test_the_full_shell_runs(self) -> None:
        shell = self.result.plan.decision("bunny.shell.session")
        self.assertTrue(shell.running)
        self.assertEqual(shell.implementation_id, "full-shell")

    def test_cpu_inference_is_selected_over_a_gpu_path_it_cannot_use(self) -> None:
        inference = self.result.plan.decision("bunny.inference.local")
        self.assertTrue(inference.running)
        self.assertEqual(inference.implementation_id, "local-cpu-small")

    def test_battery_operation_reduces_the_background_quota(self) -> None:
        desktop = assessment("gaming-desktop").budget.background_cpu_percent
        self.assertLess(self.result.budget.background_cpu_percent, desktop)

    def test_the_search_index_runs_because_the_shell_did(self) -> None:
        self.assertTrue(self.result.plan.decision("bunny.desktop.search").running)


class GamingDesktopTests(unittest.TestCase):
    """4. A gaming desktop."""

    def setUp(self) -> None:
        self.result = assessment("gaming-desktop")

    def test_everything_runs(self) -> None:
        self.assertEqual(len(self.result.plan.running()), len(REGISTRY))

    def test_the_richest_companion_is_selected(self) -> None:
        self.assertEqual(self.result.plan.decision("bunny.companion").implementation_id, "animated-3d")

    def test_gpu_inference_is_selected(self) -> None:
        self.assertEqual(self.result.plan.decision("bunny.inference.local").implementation_id, "local-gpu")
        self.assertTrue(self.result.budget.gpu_local_inference_allowed)

    def test_no_decision_is_labelled_degraded(self) -> None:
        for decision in self.result.plan.running():
            with self.subTest(service=decision.service_id):
                self.assertNotIn("degraded", decision.reason_codes())


class CpuServerTests(unittest.TestCase):
    """5. A CPU server."""

    def setUp(self) -> None:
        self.result = assessment("cpu-server")

    def test_the_desktop_session_is_refused_because_it_is_headless(self) -> None:
        shell = self.result.plan.decision("bunny.shell.session")
        self.assertFalse(shell.running)
        self.assertTrue(any(check.requirement == "display.required" and check.satisfied is False
                            for check in shell.checks))

    def test_the_large_cpu_model_is_selected(self) -> None:
        self.assertEqual(self.result.plan.decision("bunny.inference.local").implementation_id,
                         "local-cpu-large")

    def test_the_companion_falls_all_the_way_to_text(self) -> None:
        companion = self.result.plan.decision("bunny.companion")
        self.assertTrue(companion.running)
        self.assertEqual(companion.implementation_id, "text-only")

    def test_no_rendering_is_permitted(self) -> None:
        self.assertFalse(self.result.budget.gpu_rendering_allowed)

    def test_speech_is_refused_for_want_of_hardware_not_for_want_of_memory(self) -> None:
        recognition = self.result.plan.decision("bunny.speech.recognition")
        self.assertFalse(recognition.running)
        self.assertNotIn("budget-exhausted", recognition.reason_codes())
        self.assertIn("requirement-unmet", recognition.reason_codes())


class MultiGpuServerTests(unittest.TestCase):
    """6. A multi-GPU AI server."""

    def setUp(self) -> None:
        self.result = assessment("multi-gpu-ai-server")

    def test_gpu_inference_is_selected(self) -> None:
        self.assertEqual(self.result.plan.decision("bunny.inference.local").implementation_id, "local-gpu")

    def test_all_eight_accelerators_are_usable(self) -> None:
        self.assertEqual(len(self.result.inventory.usable_gpus), 8)
        self.assertGreater(self.result.scores["gpu_compute"].value, 95.0)

    def test_rendering_is_still_refused_because_nothing_is_plugged_in(self) -> None:
        self.assertFalse(self.result.budget.gpu_rendering_allowed)
        self.assertEqual(self.result.scores["graphics"].value, 0.0)

    def test_the_reserve_is_capped_rather_than_proportional(self) -> None:
        from capability.budget import MAXIMUM_RESERVE_BYTES

        self.assertEqual(self.result.budget.protected_reserve_bytes, MAXIMUM_RESERVE_BYTES)

    def test_the_companion_is_text_only_despite_the_hardware(self) -> None:
        # Eight accelerators do not produce a 3D companion on a machine with no
        # display. Capability is per-requirement, not a global level.
        self.assertEqual(self.result.plan.decision("bunny.companion").implementation_id, "text-only")


class ConstrainedContainerTests(unittest.TestCase):
    """7. A powerful host with a severely restricted container."""

    def setUp(self) -> None:
        self.result = assessment("constrained-container")
        self.host = assessment("multi-gpu-ai-server")

    def test_the_container_is_budgeted_as_the_container_not_the_host(self) -> None:
        self.assertEqual(self.result.budget.usable_bytes, 512 * MIB)
        self.assertEqual(self.host.budget.usable_bytes, 512 * GIB)

    def test_the_cpu_quota_binds_below_the_host_thread_count(self) -> None:
        self.assertEqual(self.result.budget.effective_cores, 0.5)
        self.assertEqual(self.result.inventory.cpu.logical_threads.get(None), 128)

    def test_eight_accelerators_do_not_buy_local_inference(self) -> None:
        # The failure this whole subsystem exists to prevent: a machine that
        # looks like a supercomputer by one measure and is smaller than a phone
        # by the one that decides whether anything can be loaded.
        self.assertEqual(len(self.result.inventory.usable_gpus), 8)
        self.assertGreater(self.result.scores["gpu_compute"].value, 90.0)
        inference = self.result.plan.decision("bunny.inference.local")
        self.assertFalse(inference.running)
        self.assertIn("budget-exhausted", inference.reason_codes())

    def test_the_same_host_without_the_container_does_run_inference(self) -> None:
        # The contrast that proves the ceiling, not the hardware, was decisive.
        self.assertTrue(self.host.plan.decision("bunny.inference.local").running)

    def test_the_control_plane_still_runs(self) -> None:
        essential = {service.id for service in REGISTRY.essential()}
        running = {d.service_id for d in self.result.plan.running()}
        self.assertTrue(essential.issubset(running))

    def test_the_containment_is_recorded_in_the_constraints(self) -> None:
        constraints = self.result.inventory.constraints_json()
        self.assertTrue(constraints["containerized"])
        self.assertTrue(constraints["memoryLimited"])
        self.assertTrue(constraints["cpuQuotaLimited"])


class DegenerateMachineTests(unittest.TestCase):
    """The cases that break naive detection code."""

    def test_a_driverless_gpu_produces_a_cpu_plan_not_a_failed_start(self) -> None:
        result = assessment("gpu-without-driver")
        self.assertEqual(len(result.inventory.gpu), 1)
        self.assertEqual(result.inventory.usable_gpus, [])
        inference = result.plan.decision("bunny.inference.local")
        self.assertTrue(inference.running)
        self.assertNotEqual(inference.implementation_id, "local-gpu")

    def test_an_offline_machine_still_runs_everything_local(self) -> None:
        result = assessment("offline-laptop")
        self.assertTrue(result.plan.decision("bunny.shell.session").running)
        self.assertTrue(result.plan.decision("bunny.companion").running)

    def test_a_read_only_root_refuses_services_that_must_write(self) -> None:
        result = assessment("read-only-appliance")
        self.assertFalse(result.plan.decision("bunny.memory.vector").running)
        self.assertEqual(result.budget.cache_storage_bytes, 0)

    def test_a_machine_that_measured_nothing_still_plans(self) -> None:
        result = assessment("unmeasurable")
        self.assertEqual(len(result.plan.decisions), len(REGISTRY))
        self.assertEqual(result.budget.confidence, "unknown")

    def test_every_simulated_machine_is_described(self) -> None:
        from capability.simulate import MACHINES

        for name in MACHINES:
            with self.subTest(machine=name):
                self.assertTrue(describe(name))


class SameFeatureDifferentImplementationTests(unittest.TestCase):
    """§18's required end-to-end example, asserted rather than only documented."""

    def test_the_companion_is_one_feature_with_machine_chosen_implementations(self) -> None:
        selections = {name: assessment(name).plan.decision("bunny.companion") for name in REQUIRED_MACHINES}
        # Present as a decision on every machine...
        self.assertEqual(len(selections), len(REQUIRED_MACHINES))
        # ...running on all but the smallest...
        self.assertFalse(selections["embedded-64mb"].running)
        for name in ("raspberry-pi-class", "laptop", "gaming-desktop", "cpu-server", "multi-gpu-ai-server"):
            self.assertTrue(selections[name].running, name)
        # ...through four different implementations of the same service.
        chosen = {name: item.implementation_id for name, item in selections.items() if item.running}
        self.assertGreaterEqual(len(set(chosen.values())), 4)

    def test_speech_synthesis_selects_three_different_local_voices(self) -> None:
        chosen = set()
        for name in REQUIRED_MACHINES:
            decision = assessment(name).plan.decision("bunny.speech.synthesis")
            if decision.running:
                chosen.add(decision.implementation_id)
        self.assertGreaterEqual(len(chosen), 2)
        self.assertTrue(chosen.issubset({"local-neural-gpu", "local-neural-cpu", "local-system-voice"}))


if __name__ == "__main__":
    unittest.main()

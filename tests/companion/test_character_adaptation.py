# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import replace
import unittest

from companion.presentation import PresentationRecommendation
from companion.character.adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.defaults import default_character_path
from companion.character.package import validate_package_directory


class AdaptiveRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(default_character_path())

    def plan(self, ceiling: Presentation = Presentation.ANIMATED_2D) -> CapabilityPresentationPlan:
        return CapabilityPresentationPlan("plan-1", ceiling, ceiling)

    def evaluate(self, signals: RendererSignals, *, selector=None, now=0, plan=None):
        return (selector or AdaptiveRendererSelector()).evaluate(
            plan or self.plan(), self.package, signals, now=now
        )

    def test_memory_pressure_disables_animation(self) -> None:
        decision = self.evaluate(RendererSignals(memory_pressure=True))
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_insufficient_static_memory_degrades_to_text(self) -> None:
        decision = self.evaluate(RendererSignals(available_memory_bytes=100))
        self.assertEqual(decision.effective, Presentation.TEXT_ONLY)

    def test_package_memory_declaration_is_respected(self) -> None:
        decision = self.evaluate(RendererSignals(
            available_memory_bytes=self.package.manifest.memory_estimate_bytes
        ))
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_thermal_pressure_caps_frame_rate_without_false_hardware_claim(self) -> None:
        decision = self.evaluate(RendererSignals(thermal_pressure=True))
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)
        self.assertEqual(decision.frame_rate_cap, 8)  # package declaration is stricter than thermal cap

    def test_cpu_and_foreground_pressure_cap_frame_rate(self) -> None:
        faster = replace(self.package, manifest=replace(self.package.manifest, frame_rate=60))
        selector = AdaptiveRendererSelector()
        decision = selector.evaluate(self.plan(), faster, RendererSignals(cpu_pressure=True), now=0)
        self.assertEqual(decision.frame_rate_cap, 20)
        decision = AdaptiveRendererSelector().evaluate(
            self.plan(), faster, RendererSignals(foreground_workload_high=True), now=0
        )
        self.assertEqual(decision.frame_rate_cap, 12)

    def test_missing_gpu_keeps_cpu_safe_frame_sequence_ceiling(self) -> None:
        decision = self.evaluate(
            RendererSignals(gpu_available=False, graphics_ready=True)
        )
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)
        self.assertLessEqual(decision.frame_rate_cap, 30)
        self.assertTrue(any("CPU-safe" in reason for reason in decision.reasons))

    def test_frame_rate_degradation_emits_one_typed_event(self) -> None:
        faster = replace(self.package, manifest=replace(self.package.manifest, frame_rate=60))
        selector = AdaptiveRendererSelector()
        first = selector.evaluate(
            self.plan(), faster,
            RendererSignals(gpu_available=True, thermal_pressure=True), now=0,
        )
        selector.evaluate(
            self.plan(), faster,
            RendererSignals(gpu_available=True, thermal_pressure=True), now=1,
        )
        self.assertEqual(first.frame_rate_cap, 15)
        throttles = [event for event in selector.events if event.event_type == "renderer.throttled"]
        self.assertEqual(len(throttles), 1)
        self.assertEqual(throttles[0].code, "thermal-pressure")
        self.assertEqual(throttles[0].frame_rate_cap, 15)
        self.assertTrue(throttles[0].task_continues)

    def test_battery_critical_switches_to_static(self) -> None:
        decision = self.evaluate(RendererSignals(on_battery=True, battery_percent=5))
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_display_removed_switches_to_text(self) -> None:
        decision = self.evaluate(RendererSignals(display_available=False))
        self.assertEqual(decision.effective, Presentation.TEXT_ONLY)

    def test_reduced_motion_and_no_animation_are_immediate(self) -> None:
        for signals in (RendererSignals(reduced_motion=True), RendererSignals(no_animation=True)):
            with self.subTest(signals=signals):
                self.assertEqual(self.evaluate(signals).effective, Presentation.STATIC_IMAGE)

    def test_user_preference_is_a_ceiling(self) -> None:
        decision = self.evaluate(RendererSignals(user_preference=Presentation.STATIC_IMAGE))
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_capability_plan_is_never_upgraded(self) -> None:
        decision = self.evaluate(RendererSignals(), plan=self.plan(Presentation.STATIC_IMAGE))
        self.assertEqual(decision.requested, Presentation.STATIC_IMAGE)
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_renderer_failure_uses_static_and_static_failure_uses_text(self) -> None:
        self.assertEqual(self.evaluate(RendererSignals(renderer_healthy=False)).effective, Presentation.STATIC_IMAGE)
        self.assertEqual(self.evaluate(RendererSignals(static_renderer_healthy=False)).effective, Presentation.TEXT_ONLY)

    def test_recovery_requires_stable_hysteresis_samples(self) -> None:
        selector = AdaptiveRendererSelector(recovery_samples=3, recovery_delay_seconds=2)
        first = self.evaluate(RendererSignals(memory_pressure=True), selector=selector, now=0)
        self.assertEqual(first.effective, Presentation.STATIC_IMAGE)
        for now in (1, 2):
            held = self.evaluate(RendererSignals(), selector=selector, now=now)
            self.assertEqual(held.effective, Presentation.STATIC_IMAGE)
            self.assertTrue(held.held_by_hysteresis)
        recovered = self.evaluate(RendererSignals(), selector=selector, now=3)
        self.assertEqual(recovered.effective, Presentation.ANIMATED_2D)

    def test_no_rapid_presentation_oscillation(self) -> None:
        selector = AdaptiveRendererSelector(recovery_samples=3, recovery_delay_seconds=0)
        observed = []
        for index, pressure in enumerate((True, False, True, False, False, False)):
            observed.append(self.evaluate(
                RendererSignals(memory_pressure=pressure), selector=selector, now=index
            ).effective)
        self.assertEqual(observed[:5], [Presentation.STATIC_IMAGE] * 5)
        self.assertEqual(observed[-1], Presentation.ANIMATED_2D)

    def test_degradation_event_is_typed_and_task_continues(self) -> None:
        selector = AdaptiveRendererSelector()
        self.evaluate(RendererSignals(), selector=selector, now=0)
        self.evaluate(RendererSignals(memory_pressure=True), selector=selector, now=1)
        event = selector.events[-1]
        self.assertEqual(event.event_type, "renderer.degraded")
        self.assertEqual(event.code, "memory-pressure")
        self.assertTrue(event.task_continues)

    def test_the_plan_comes_from_the_canonical_recommendation(self) -> None:
        """§14: consume the allowance; never re-derive it."""
        plan = CapabilityPresentationPlan.from_recommendation(PresentationRecommendation(
            implementation="animated-2d", eligible="animated-2d", plan_id="cap-plan",
            reasons=("the machine can animate",),
        ))
        self.assertEqual(plan.plan_id, "cap-plan")
        self.assertEqual(plan.ceiling, Presentation.ANIMATED_2D)
        self.assertIn("the machine can animate", plan.reasons)

    def test_a_text_only_allowance_stays_text_only(self) -> None:
        plan = CapabilityPresentationPlan.from_recommendation(PresentationRecommendation(
            implementation="text-only", eligible="text-only", plan_id="headless",
        ))
        self.assertEqual(plan.ceiling, Presentation.TEXT_ONLY)

    def test_an_audio_only_allowance_draws_nothing(self) -> None:
        """Audio is the voice adapter's business; the character stays text."""
        plan = CapabilityPresentationPlan.from_recommendation(PresentationRecommendation(
            implementation="audio-only", eligible="audio-only", plan_id="audio",
        ))
        self.assertEqual(plan.ceiling, Presentation.TEXT_ONLY)

    def test_a_3d_eligible_machine_is_capped_at_implemented_2d(self) -> None:
        """The canonical projection never selects 3D, and neither does this."""
        recommendation = PresentationRecommendation(
            implementation="animated-2d", eligible="full-3d",
            limited_by_implementation=True, plan_id="future",
        )
        plan = CapabilityPresentationPlan.from_recommendation(recommendation)
        self.assertEqual(plan.ceiling, Presentation.ANIMATED_2D)
        self.assertTrue(any("full-3d" in reason for reason in plan.reasons))
        self.assertTrue(any("claims nothing above it" in reason for reason in plan.reasons))

    def test_no_constructor_reads_a_capability_execution_plan(self) -> None:
        """The second interpretation this layer was rewired to remove."""
        self.assertFalse(hasattr(CapabilityPresentationPlan, "from_execution_plan"))


if __name__ == "__main__":
    unittest.main()

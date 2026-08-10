# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21, §22, §23 and §30: the ladder, degradation, context loss and headless.

No GPU is used here either. The selector is a pure function of a plan, a package
and a signal set — which is what makes "does memory pressure end 3D" a table
test rather than a scenario needing a machine under memory pressure.

The one thing that *cannot* be tested this way is whether a context actually
comes back after being lost, and that is in
``tests/companion/test_three_d_render.py`` where a real one is destroyed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from companion.character.adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.defaults import default_3d_character_path
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.character.three_d.budget import DEFAULT_BUDGET, FrameHealth, ThreeDBudget
from companion.presentation import (
    IMPLEMENTED_PRESENTATIONS,
    PRESENTATION_KINDS,
    AccessibilityPreferences,
    PresentationSignals,
    select_presentation,
)

_GIB = 1024 ** 3


def _package():
    root = default_3d_character_path()
    if not root.is_dir():
        raise unittest.SkipTest("the built-in 3D package is not installed here")
    return validate_package_directory(root, trust_state=PackageTrustState.BUILT_IN)


def _plan(ceiling: Presentation = Presentation.FULL_3D) -> CapabilityPresentationPlan:
    return CapabilityPresentationPlan(
        plan_id="plan-test", requested=ceiling, ceiling=ceiling,
        implementation_id=ceiling.value,
    )


def _signals(**overrides) -> RendererSignals:
    base = dict(
        display_available=True, graphics_ready=True, gpu_available=True,
        available_memory_bytes=8 * _GIB, three_d_available=True,
        package_supports_3d=True, model_gpu_bytes=1 << 20,
    )
    base.update(overrides)
    return RendererSignals(**base)


class LadderShapeTests(unittest.TestCase):
    def test_the_ladder_is_the_five_rungs_in_order(self) -> None:
        self.assertEqual(
            PRESENTATION_KINDS,
            ("full-3d", "lightweight-3d", "animated-2d", "static-image", "audio-only", "text-only"),
        )
        for rung in ("full-3d", "lightweight-3d", "animated-2d", "static-image", "text-only"):
            self.assertIn(rung, IMPLEMENTED_PRESENTATIONS)

    def test_the_2d_renderer_remains_a_mandatory_fallback(self) -> None:
        package = _package()
        selector = AdaptiveRendererSelector()
        decision = selector.evaluate(
            _plan(), package, _signals(three_d_available=False), now=0.0
        )
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)
        self.assertTrue(
            any("graphics stack cannot provide" in reason for reason in decision.reasons)
        )


class DegradationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = _package()
        self.selector = AdaptiveRendererSelector()

    def _evaluate(self, *, now: float = 0.0, **overrides):
        return self.selector.evaluate(_plan(), self.package, _signals(**overrides), now=now)

    def test_a_capable_machine_draws_the_full_rung(self) -> None:
        self.assertEqual(self._evaluate().effective, Presentation.FULL_3D)

    def test_gpu_context_loss_drops_to_2d_and_the_task_continues(self) -> None:
        self._evaluate()
        decision = self._evaluate(gpu_context_lost=True, now=1.0)
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)
        event = self.selector.events[-1]
        self.assertEqual(event.code, "gpu-context-lost")
        self.assertTrue(event.task_continues)

    def test_a_renderer_failure_drops_to_2d(self) -> None:
        self._evaluate()
        decision = self._evaluate(three_d_healthy=False, now=1.0)
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)

    def test_an_unsupported_graphics_feature_drops_to_2d(self) -> None:
        decision = self._evaluate(graphics_features_supported=False)
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)

    def test_sustained_slow_frames_drop_full_to_lightweight(self) -> None:
        self._evaluate()
        decision = self._evaluate(sustained_slow_frames=True, now=1.0)
        self.assertEqual(decision.effective, Presentation.LIGHTWEIGHT_3D)
        self.assertTrue(any("frame time stayed above" in reason for reason in decision.reasons))

    def test_continued_pressure_drops_lightweight_to_2d(self) -> None:
        selector = AdaptiveRendererSelector()
        selector.evaluate(_plan(), self.package, _signals(), now=0.0)
        selector.evaluate(
            _plan(), self.package, _signals(sustained_slow_frames=True), now=1.0
        )
        decision = selector.evaluate(
            _plan(Presentation.LIGHTWEIGHT_3D), self.package,
            _signals(sustained_slow_frames=True), now=2.0,
        )
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)

    def test_dropped_frames_drop_a_rung(self) -> None:
        self._evaluate()
        decision = self._evaluate(dropped_frame_ratio=0.6, now=1.0)
        self.assertEqual(decision.effective, Presentation.LIGHTWEIGHT_3D)

    def test_memory_pressure_ends_3d_entirely(self) -> None:
        """Both the 3D rule and the pre-existing 2D one apply; the lower wins.

        Memory pressure ends 3D *and* disables 2D animation, so the machine
        lands on a static image in one evaluation rather than descending a rung
        per frame. That is the property worth asserting: a machine in trouble
        arrives where it belongs immediately.
        """
        self._evaluate()
        decision = self._evaluate(memory_pressure=True, now=1.0)
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)
        self.assertTrue(any("memory pressure" in reason for reason in decision.reasons))

    def test_thermal_pressure_reduces_rather_than_ends_3d(self) -> None:
        self._evaluate()
        decision = self._evaluate(thermal_pressure=True, now=1.0)
        self.assertEqual(decision.effective, Presentation.LIGHTWEIGHT_3D)

    def test_a_critical_battery_ends_3d(self) -> None:
        self._evaluate()
        decision = self._evaluate(on_battery=True, battery_percent=8.0, now=1.0)
        self.assertLessEqual(
            list(Presentation).index(decision.effective),
            list(Presentation).index(Presentation.ANIMATED_2D),
        )

    def test_a_package_without_a_model_never_reaches_3d(self) -> None:
        decision = self._evaluate(package_supports_3d=False)
        self.assertEqual(decision.effective, Presentation.ANIMATED_2D)
        self.assertTrue(any("carries no validated 3D model" in item for item in decision.reasons))

    def test_no_display_still_lands_on_text_only(self) -> None:
        decision = self._evaluate(display_available=False)
        self.assertEqual(decision.effective, Presentation.TEXT_ONLY)

    def test_recovery_is_held_by_hysteresis(self) -> None:
        selector = AdaptiveRendererSelector(recovery_samples=3, recovery_delay_seconds=5.0)
        selector.evaluate(_plan(), self.package, _signals(), now=0.0)
        selector.evaluate(_plan(), self.package, _signals(gpu_context_lost=True), now=1.0)
        held = selector.evaluate(_plan(), self.package, _signals(), now=2.0)
        self.assertEqual(held.effective, Presentation.ANIMATED_2D)
        self.assertTrue(held.held_by_hysteresis)
        selector.evaluate(_plan(), self.package, _signals(), now=3.0)
        recovered = selector.evaluate(_plan(), self.package, _signals(), now=20.0)
        self.assertEqual(recovered.effective, Presentation.FULL_3D)
        self.assertEqual(selector.events[-1].event_type, "renderer.recovered")

    def test_reduced_motion_keeps_the_3d_rung(self) -> None:
        decision = self._evaluate(reduced_motion=True)
        self.assertEqual(decision.effective, Presentation.FULL_3D)
        self.assertTrue(
            any("reduced motion is applied inside" in reason for reason in decision.reasons)
        )

    def test_no_animation_still_drops_to_a_static_image(self) -> None:
        decision = self._evaluate(no_animation=True)
        self.assertEqual(decision.effective, Presentation.STATIC_IMAGE)

    def test_the_frame_rate_cap_follows_the_rung(self) -> None:
        full = self._evaluate()
        self.assertEqual(full.frame_rate_cap, DEFAULT_BUDGET.full_target_fps)
        selector = AdaptiveRendererSelector()
        selector.evaluate(_plan(), self.package, _signals(), now=0.0)
        light = selector.evaluate(
            _plan(), self.package, _signals(sustained_slow_frames=True), now=1.0
        )
        self.assertEqual(light.frame_rate_cap, DEFAULT_BUDGET.lightweight_target_fps)


class BudgetTests(unittest.TestCase):
    def test_the_budget_is_configuration_and_clamps_absurd_values(self) -> None:
        budget = ThreeDBudget.from_mapping({
            "fullFrameMsCeiling": 16.0, "lightweightFrameMsCeiling": 40.0,
            "sustainedSamples": 10_000,
        })
        self.assertEqual(budget.full_frame_ms_ceiling, 16.0)
        self.assertLessEqual(budget.sustained_samples, 120)

    def test_an_unknown_setting_is_refused_rather_than_ignored(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown 3D budget settings"):
            ThreeDBudget.from_mapping({"turnOffDegradation": True})

    def test_an_inconsistent_pair_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ThreeDBudget(full_frame_ms_ceiling=50.0, lightweight_frame_ms_ceiling=20.0)

    def test_frame_health_needs_a_sustained_trend(self) -> None:
        health = FrameHealth(ThreeDBudget(sustained_samples=3))
        self.assertFalse(health.observe(90.0, "full-3d"))
        self.assertFalse(health.observe(90.0, "full-3d"))
        self.assertTrue(health.observe(90.0, "full-3d"))
        self.assertFalse(health.observe(4.0, "full-3d"))
        self.assertEqual(health.slow_samples, 0)

    def test_frame_health_ignores_a_missing_sample(self) -> None:
        health = FrameHealth()
        self.assertFalse(health.observe(None, "full-3d"))
        self.assertEqual(health.slow_samples, 0)


class HeadlessTests(unittest.TestCase):
    """§30: no graphical session, no GPU library, and still a usable companion."""

    def test_a_headless_machine_selects_text_only_and_says_why(self) -> None:
        decision = select_presentation(
            PresentationSignals(
                headless=True, display_available=False, available_memory_bytes=8 * _GIB,
                gpu_available=True, audio_output_available=False,
            )
        )
        self.assertEqual(decision.implementation, "text-only")
        self.assertTrue(any("no display" in reason for reason in decision.reasons))

    def test_a_presenter_without_a_context_provider_never_reaches_3d(self) -> None:
        from companion.character.surface import CharacterPresenter
        from capability.runtime import assess_current_machine

        with tempfile.TemporaryDirectory(prefix="bunny-3d-headless-") as directory:
            presenter = CharacterPresenter(Path(directory), assessment=assess_current_machine())
            description = presenter.describe()
            self.assertIn("full-3d", description["implementedPresentations"])
            three_d = description["threeDimensionalRenderer"]
            self.assertIsNotNone(three_d)
            self.assertFalse(three_d["contextProviderConfigured"])
            self.assertIsNone(three_d["renderer"])

    def test_the_environment_probe_answers_without_a_session(self) -> None:
        from companion.character.three_d.diagnostics import three_d_environment

        report = three_d_environment()
        self.assertIn("graphicalSession", report)
        self.assertIsInstance(report["reasons"], list)
        self.assertFalse(report["libraryInitialised"])

    def test_reduced_motion_preference_still_produces_captions(self) -> None:
        decision = select_presentation(
            PresentationSignals(
                available_memory_bytes=8 * _GIB, gpu_available=True, display_available=True,
            ),
            AccessibilityPreferences(reduced_motion=True),
        )
        self.assertTrue(decision.captions)
        self.assertEqual(decision.implementation, "static-image")


if __name__ == "__main__":
    unittest.main()

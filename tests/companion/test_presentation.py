# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from companion.model import CompanionPhase, PresentationKind
from companion.presentation import (
    AdaptivePresentationController,
    CapabilityPresentationPlan,
    DesktopContext,
    MonitorGeometry,
    PresentationSignals,
    WindowPreferences,
    select_presentation,
    window_directive,
)

MIB = 1024 * 1024
GIB = 1024 * MIB


def plan(kind: PresentationKind = PresentationKind.FULL_3D) -> CapabilityPresentationPlan:
    implementation = {
        PresentationKind.FULL_3D: "animated-3d",
        PresentationKind.ANIMATED_2D: "animated-2d",
        PresentationKind.STATIC_IMAGE: "static-avatar",
        PresentationKind.AUDIO_ONLY: "audio-only",
        PresentationKind.TEXT_ONLY: "text-only",
        PresentationKind.LIGHTWEIGHT_3D: "lightweight-3d",
    }[kind]
    return CapabilityPresentationPlan("plan-test", "bunny.companion", "start_local", implementation, kind)


class AdaptivePresentationTests(unittest.TestCase):
    def test_64_mib_node_is_text_only(self) -> None:
        result = select_presentation(plan(), PresentationSignals(available_memory_bytes=64 * MIB))
        self.assertEqual(result.implementation, PresentationKind.TEXT_ONLY)

    def test_headless_system_uses_audio_when_permitted_by_plan(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=2 * GIB, display_available=False, headless=True, audio_output_available=True),
        )
        self.assertEqual(result.implementation, PresentationKind.AUDIO_ONLY)

    def test_headless_without_audio_is_text(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=2 * GIB, display_available=False, headless=True, audio_output_available=False),
        )
        self.assertEqual(result.implementation, PresentationKind.TEXT_ONLY)

    def test_laptop_is_animated_2d(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=GIB, display_available=True, gpu_ready=False),
        )
        self.assertEqual(result.implementation, PresentationKind.ANIMATED_2D)

    def test_gpu_workstation_is_full_3d_eligible(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, vram_available_bytes=8 * GIB),
        )
        self.assertEqual(result.implementation, PresentationKind.FULL_3D)

    def test_memory_pressure_degrades_without_stopping_task(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, memory_pressure=True),
            phase=CompanionPhase.WORKING,
        )
        self.assertEqual(result.implementation, PresentationKind.STATIC_IMAGE)
        self.assertEqual(result.placement.value, "docked")

    def test_gpu_pressure_removes_3d(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, gpu_pressure=True),
        )
        self.assertEqual(result.implementation, PresentationKind.ANIMATED_2D)

    def test_display_removed_falls_back_to_audio(self) -> None:
        result = select_presentation(
            plan(PresentationKind.STATIC_IMAGE),
            PresentationSignals(available_memory_bytes=GIB, display_available=False, headless=True, audio_output_available=True),
        )
        self.assertEqual(result.implementation, PresentationKind.AUDIO_ONLY)

    def test_audio_removed_keeps_captions(self) -> None:
        result = select_presentation(
            plan(PresentationKind.AUDIO_ONLY),
            PresentationSignals(available_memory_bytes=GIB, display_available=False, headless=True, audio_output_available=False),
        )
        self.assertEqual(result.implementation, PresentationKind.TEXT_ONLY)
        self.assertTrue(result.captions)

    def test_reduced_motion_overrides_animation(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, reduced_motion=True),
        )
        self.assertEqual(result.implementation, PresentationKind.STATIC_IMAGE)

    def test_audio_only_keeps_captions_in_the_typed_stream(self) -> None:
        result = select_presentation(
            plan(PresentationKind.AUDIO_ONLY),
            PresentationSignals(display_available=False, headless=True, audio_output_available=True),
        )
        self.assertEqual(result.implementation, PresentationKind.AUDIO_ONLY)
        self.assertTrue(result.captions)

    def test_accessibility_text_scale_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            PresentationSignals(text_scale=4.0)

    def test_capability_plan_is_a_ceiling(self) -> None:
        result = select_presentation(
            plan(PresentationKind.TEXT_ONLY),
            PresentationSignals(available_memory_bytes=64 * GIB, gpu_ready=True, vram_available_bytes=32 * GIB),
        )
        self.assertEqual(result.implementation, PresentationKind.TEXT_ONLY)

    def test_remote_rendering_needs_permission(self) -> None:
        result = select_presentation(
            plan(),
            PresentationSignals(
                available_memory_bytes=8 * GIB,
                gpu_ready=True,
                remote_rendering_requested=True,
                remote_rendering_permitted=False,
            ),
        )
        self.assertEqual(result.implementation, PresentationKind.STATIC_IMAGE)

    def test_recovery_uses_hysteresis(self) -> None:
        controller = AdaptivePresentationController(recovery_samples=3)
        pressured = PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, memory_pressure=True)
        healthy = PresentationSignals(available_memory_bytes=8 * GIB, gpu_ready=True, vram_available_bytes=8 * GIB)
        self.assertEqual(controller.update(plan(), pressured).implementation, PresentationKind.STATIC_IMAGE)
        self.assertEqual(controller.update(plan(), healthy).implementation, PresentationKind.STATIC_IMAGE)
        self.assertEqual(controller.update(plan(), healthy).implementation, PresentationKind.STATIC_IMAGE)
        self.assertEqual(controller.update(plan(), healthy).implementation, PresentationKind.FULL_3D)


class WindowPolicyTests(unittest.TestCase):
    def context(self, fullscreen: bool = False) -> DesktopContext:
        return DesktopContext(
            monitors=(
                MonitorGeometry("left", 0, 0, 1920, 1080),
                MonitorGeometry("right", 1920, 0, 2560, 1440),
            ),
            active_monitor_id="right",
            fullscreen_application=fullscreen,
        )

    def test_working_companion_is_docked_and_does_not_accept_focus(self) -> None:
        result = window_directive(CompanionPhase.WORKING, WindowPreferences(), self.context())
        self.assertEqual(result.placement.value, "docked")
        self.assertFalse(result.accept_focus)
        self.assertEqual(result.monitor_id, "right")

    def test_approval_panel_accepts_focus(self) -> None:
        result = window_directive(CompanionPhase.WAITING_FOR_APPROVAL, WindowPreferences(), self.context())
        self.assertEqual(result.placement.value, "task-panel")
        self.assertTrue(result.accept_focus)
        self.assertFalse(result.click_through)

    def test_fullscreen_compacts_and_suppresses_notification(self) -> None:
        result = window_directive(CompanionPhase.WORKING, WindowPreferences(), self.context(fullscreen=True))
        self.assertEqual(result.placement.value, "compact")
        self.assertTrue(result.suppress_notification)

    def test_fullscreen_can_hide_passive_window(self) -> None:
        result = window_directive(
            CompanionPhase.WORKING,
            WindowPreferences(hide_during_fullscreen=True),
            self.context(fullscreen=True),
        )
        self.assertFalse(result.visible)


if __name__ == "__main__":
    unittest.main()

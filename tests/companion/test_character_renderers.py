# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import replace
import unittest

from companion.character.adaptation import (
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.animated_renderer import Animated2DRenderer
from companion.character.bubble import BubbleKind, SpeechBubbleController, layout_bubble
from companion.character.controller import CharacterRendererController
from companion.character.defaults import default_character_path
from companion.character.errors import RendererError
from companion.character.mapper import StateMapperInput, map_character_state
from companion.character.package import validate_package_directory
from companion.character.positioning import Display, PixelRect, Placement, place_character
from companion.character.static_renderer import StaticImageRenderer


class RendererFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(default_character_path())
        cls.idle = map_character_state(cls.package.manifest, StateMapperInput(presentation_phase="idle"))
        cls.working = map_character_state(cls.package.manifest, StateMapperInput(presentation_phase="working"))
        cls.success = map_character_state(cls.package.manifest, StateMapperInput(presentation_phase="success"))
        cls.error = map_character_state(cls.package.manifest, StateMapperInput(presentation_phase="error", error_summary="failure"))


class StaticRendererTests(RendererFixture):
    def test_package_load_state_change_and_unload(self) -> None:
        renderer = StaticImageRenderer(); renderer.load_package(self.package)
        frame = renderer.display_state(self.working)
        self.assertEqual(frame.state, "working")
        self.assertTrue(frame.asset_path.is_file())
        renderer.unload_package()
        self.assertIsNone(renderer.frame)
        self.assertEqual(renderer.report_memory_use(), 0)

    def test_static_renderer_preserves_aspect_ratio_metadata(self) -> None:
        renderer = StaticImageRenderer(); renderer.load_package(self.package)
        frame = renderer.display_state(self.idle)
        self.assertEqual((frame.width, frame.height), (96, 96))

    def test_headless_display_is_safe_and_text_description_remains(self) -> None:
        renderer = StaticImageRenderer(display_available=False); renderer.load_package(self.package)
        self.assertIsNone(renderer.display_state(self.error))
        self.assertIn("error", renderer.accessibility_description().lower())

    def test_scale_opacity_visibility_and_position(self) -> None:
        renderer = StaticImageRenderer(); renderer.load_package(self.package)
        renderer.set_scale(2); renderer.set_opacity(0.5); renderer.set_visibility(False)
        display = Display("one", PixelRect(0, 0, 800, 600), True)
        renderer.set_position(place_character([display], size=(100, 100), placement=Placement.BOTTOM_RIGHT))
        frame = renderer.display_state(self.idle)
        self.assertEqual(frame.scale, 2)
        self.assertEqual(frame.opacity, 0.5)
        self.assertFalse(renderer.status().visible)

    def test_repositioning_refuses_keyboard_focus(self) -> None:
        renderer = StaticImageRenderer(); renderer.load_package(self.package)
        from companion.character.positioning import PositionDecision
        unsafe = PositionDecision("one", PixelRect(0, 0, 10, 10), Placement.USER_DRAGGED,
                                  None, False, False, False, True)
        with self.assertRaisesRegex(RendererError, "keyboard focus"):
            renderer.set_position(unsafe)

    def test_diagnostic_capture_is_development_only(self) -> None:
        renderer = StaticImageRenderer(); renderer.load_package(self.package); renderer.display_state(self.idle)
        with self.assertRaises(RendererError):
            renderer.capture_diagnostic_frame()
        self.assertIsNotNone(renderer.capture_diagnostic_frame(development_mode=True)["frame"])


class AnimatedRendererTests(RendererFixture):
    def renderer(self) -> Animated2DRenderer:
        renderer = Animated2DRenderer(); renderer.load_package(self.package); return renderer

    def test_loop_playback_and_frame_timing(self) -> None:
        renderer = self.renderer(); first = renderer.display_state(self.idle, now_ms=0)
        second = renderer.tick(now_ms=700)
        looped = renderer.tick(now_ms=1300)
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(looped.asset_id, first.asset_id)
        self.assertEqual(renderer.report_frame_timing()["lastFrameMs"], 1300.0)

    def test_one_shot_returns_to_idle(self) -> None:
        renderer = self.renderer(); renderer.display_state(self.success, now_ms=0)
        frame = renderer.tick(now_ms=1000)
        self.assertEqual(frame.animation, "idle")

    def test_static_state_holds_until_runtime_state_changes(self) -> None:
        listening = map_character_state(
            self.package.manifest, StateMapperInput(presentation_phase="idle", listening=True)
        )
        renderer = self.renderer(); first = renderer.display_state(listening, now_ms=0)
        held = renderer.tick(now_ms=2000)
        self.assertEqual(held.asset_id, first.asset_id)
        self.assertEqual(held.state, "listening")

    def test_frame_rate_cap_limits_visual_updates(self) -> None:
        renderer = self.renderer(); renderer.set_frame_rate_cap(1)
        first = renderer.display_state(self.idle, now_ms=0)
        early = renderer.tick(now_ms=700)
        late = renderer.tick(now_ms=1000)
        self.assertEqual(early.asset_id, first.asset_id)
        self.assertNotEqual(late.asset_id, first.asset_id)

    def test_pause_and_resume(self) -> None:
        renderer = self.renderer(); first = renderer.display_state(self.idle, now_ms=0)
        renderer.pause(now_ms=100)
        self.assertEqual(renderer.tick(now_ms=800).asset_id, first.asset_id)
        renderer.resume(now_ms=800)
        self.assertNotEqual(renderer.tick(now_ms=1400).asset_id, first.asset_id)

    def test_playback_speed_is_bounded(self) -> None:
        renderer = self.renderer()
        renderer.set_playback_speed(2)
        with self.assertRaises(ValueError):
            renderer.set_playback_speed(5)

    def test_large_timing_gap_counts_dropped_frames(self) -> None:
        renderer = self.renderer(); renderer.display_state(self.idle, now_ms=0)
        renderer.tick(now_ms=5000)
        self.assertGreater(renderer.dropped_frames, 0)

    def test_safety_state_interrupts_a_complete_current_animation(self) -> None:
        """§10: an error interrupts a decorative animation that blocks others.

        The blocking animation is started directly rather than reached through a
        character state. Its transition policy is what is under test, and no
        canonical presentation phase maps to the package's ``complete-current``
        animation — so going through the mapper would have tested the mapper.
        """
        renderer = self.renderer()
        renderer.play_animation("sleeping", now_ms=0)
        self.assertEqual(renderer.playback.animation.transition, "complete-current")
        renderer.display_state(self.working, now_ms=10)
        self.assertEqual(renderer.queued_animation, self.working.animation)
        frame = renderer.display_state(self.error, now_ms=20)
        self.assertEqual(frame.state, "error")
        self.assertIsNone(renderer.queued_animation)

    def test_state_interruption_queue_is_bounded_to_one(self) -> None:
        """§10: only one queued transition is retained."""
        renderer = self.renderer()
        renderer.play_animation("sleeping", now_ms=0)
        renderer.display_state(self.working, now_ms=10)
        renderer.display_state(self.success, now_ms=20)
        self.assertEqual(renderer.queued_animation, self.success.animation)

    def test_an_approval_interrupts_a_blocking_animation(self) -> None:
        """§10: approval requests interrupt idle or celebration."""
        from companion.character.mapper import StateMapperInput as _Input

        renderer = self.renderer()
        renderer.play_animation("sleeping", now_ms=0)
        approval = map_character_state(
            self.package.manifest,
            _Input(presentation_phase="waiting_for_approval", approval_pending=True),
        )
        frame = renderer.display_state(approval, now_ms=10)
        self.assertEqual(frame.state, "waiting_for_approval")
        self.assertIsNone(renderer.queued_animation)

    def test_listening_interrupts_a_blocking_animation(self) -> None:
        """§10: listening interrupts decorative movement."""
        from companion.character.mapper import StateMapperInput as _Input

        renderer = self.renderer()
        renderer.play_animation("sleeping", now_ms=0)
        listening = map_character_state(
            self.package.manifest, _Input(presentation_phase="idle", listening=True)
        )
        frame = renderer.display_state(listening, now_ms=10)
        self.assertEqual(frame.state, "listening")

    def test_mouth_shape_updates_diagnostic_frame(self) -> None:
        renderer = self.renderer(); renderer.display_state(self.working)
        renderer.set_mouth_shape("open-wide")
        self.assertEqual(renderer.frame.mouth_shape, "open-wide")

    def test_speaking_mouth_shape_uses_package_mapped_frame(self) -> None:
        renderer = self.renderer()
        speaking = map_character_state(
            self.package.manifest, StateMapperInput(presentation_phase="presenting_result", speaking=True)
        )
        renderer.display_state(speaking)
        renderer.set_mouth_shape("open-wide")
        self.assertEqual(renderer.frame.asset_id, "speaking-open")
        renderer.set_mouth_shape("closed")
        self.assertEqual(renderer.frame.asset_id, "speaking-closed")

    def test_resource_release_clears_playback(self) -> None:
        renderer = self.renderer(); renderer.display_state(self.idle)
        renderer.unload_package()
        self.assertIsNone(renderer.playback)
        self.assertIsNone(renderer.package)


class ControllerRecoveryTests(RendererFixture):
    def plan(self) -> CapabilityPresentationPlan:
        return CapabilityPresentationPlan("plan", Presentation.ANIMATED_2D, Presentation.ANIMATED_2D)

    def test_renderer_crash_degrades_without_touching_task(self) -> None:
        controller = CharacterRendererController(); controller.load_package(self.package)
        controller.apply(self.working, self.plan(), RendererSignals(), now=0, now_ms=0)
        failure = controller.report_renderer_failure("simulated-crash", "renderer process stopped")
        snapshot = controller.apply(
            self.working, self.plan(), RendererSignals(renderer_healthy=False), now=1, now_ms=1000
        )
        self.assertTrue(failure.task_continues)
        self.assertEqual(snapshot.presentation.effective, Presentation.STATIC_IMAGE)
        self.assertEqual(snapshot.renderer_status["renderer"], "static-image")

    def test_package_change_unloads_old_renderer_before_new_load(self) -> None:
        controller = CharacterRendererController(); controller.load_package(self.package)
        controller.apply(self.idle, self.plan(), RendererSignals(), now=0, now_ms=0)
        replacement = replace(self.package, package_digest="a" * 64)
        controller.load_package(replacement)
        snapshot = controller.apply(self.idle, self.plan(), RendererSignals(), now=1, now_ms=1)
        self.assertEqual(snapshot.renderer_status["loadedPackageDigest"], "a" * 64)
        self.assertTrue(any(
            event["eventType"] == "renderer.package-changed" for event in snapshot.events
        ))

    def test_restart_restores_package_state_and_position(self) -> None:
        controller = CharacterRendererController(); controller.load_package(self.package)
        display = Display("one", PixelRect(0, 0, 800, 600), True)
        position = place_character([display], size=(100, 100), placement=Placement.BOTTOM_RIGHT)
        controller.set_position(position)
        controller.apply(self.success, self.plan(), RendererSignals(), now=0, now_ms=0)
        controller.renderer.set_scale(1.5)
        controller.renderer.set_opacity(0.75)
        controller.renderer.set_visibility(False)
        controller.renderer.set_reduced_motion(True)
        controller.renderer.set_frame_rate_cap(8)
        bubble = SpeechBubbleController().update("Finished", kind=BubbleKind.CAPTION, now=0)
        layout = layout_bubble(
            bubble, self.package.manifest.bubble_anchor, position.character, [display]
        )
        controller.attach_bubble(bubble, layout)
        snapshot = controller.restart_renderer(now_ms=100)
        self.assertEqual(snapshot.renderer_status["loadedPackageId"], self.package.manifest.package_id)
        self.assertEqual(snapshot.mapped_state.character_state.value, "success")
        self.assertEqual(snapshot.position["displayId"], "one")
        self.assertEqual(snapshot.renderer_status["frameRateCap"], 8)
        self.assertTrue(snapshot.renderer_status["reducedMotion"])
        self.assertFalse(snapshot.renderer_status["visible"])
        self.assertEqual(snapshot.frame.scale, 1.5)
        self.assertEqual(snapshot.frame.opacity, 0.75)
        self.assertEqual(snapshot.bubble["text"], "Finished")
        self.assertIsNotNone(controller.renderer.bubble_layout)
        self.assertTrue(any(event["eventType"] == "renderer.restarted" for event in snapshot.events))

    def test_text_only_has_no_image_renderer(self) -> None:
        controller = CharacterRendererController(); controller.load_package(self.package)
        plan = CapabilityPresentationPlan("text", Presentation.TEXT_ONLY, Presentation.TEXT_ONLY)
        snapshot = controller.apply(self.idle, plan, RendererSignals(), now=0, now_ms=0)
        self.assertIsNone(snapshot.frame)
        self.assertIsNone(snapshot.renderer_status)

    def test_accessibility_frame_rate_cap_reaches_renderer(self) -> None:
        from companion.character.mapper import AccessibilityPreferences
        mapped = map_character_state(
            self.package.manifest,
            StateMapperInput(
                presentation_phase="working",
                accessibility=AccessibilityPreferences(frame_rate_cap=5),
            ),
        )
        controller = CharacterRendererController(); controller.load_package(self.package)
        snapshot = controller.apply(mapped, self.plan(), RendererSignals(), now=0, now_ms=0)
        self.assertEqual(snapshot.presentation.frame_rate_cap, 5)
        self.assertEqual(snapshot.renderer_status["frameRateCap"], 5)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.character.bubble import (
    BubbleKind,
    SpeechBubbleController,
    layout_bubble,
    sanitize_bubble_text,
)
from companion.character.defaults import default_character_path
from companion.character.lipsync import (
    LipSyncController,
    LipSyncEvent,
    MouthShape,
    amplitude_to_shape,
    validate_lip_sync_events,
)
from companion.character.package import validate_package_directory
from companion.character.positioning import (
    Display,
    PixelRect,
    Placement,
    PositionStore,
    SavedPosition,
    place_character,
    saved_from_decision,
)


class SpeechBubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(default_character_path())
        cls.anchor = cls.package.manifest.bubble_anchor
        cls.display = Display("primary", PixelRect(0, 0, 1280, 720), True)

    def test_anchor_is_relative_to_character(self) -> None:
        state = SpeechBubbleController().update("Hello", now=0)
        character = PixelRect(100, 200, 200, 300)
        layout = layout_bubble(state, self.anchor, character, [self.display])
        self.assertEqual(layout.anchor_x, 100 + round(self.anchor.x * 200))
        self.assertEqual(layout.anchor_y, 200 + round(self.anchor.y * 300))

    def test_automatic_side_selection_avoids_screen_edge(self) -> None:
        state = SpeechBubbleController().update("Edge avoidance " * 20, now=0)
        character = PixelRect(1100, 250, 160, 240)
        layout = layout_bubble(state, self.anchor, character, [self.display])
        self.assertLessEqual(layout.bounds.right, self.display.work_area.right - 12)
        self.assertTrue(layout.edge_avoided)

    def test_bubble_width_wrap_and_scale_are_bounded(self) -> None:
        state = SpeechBubbleController().update("word " * 500, now=0)
        layout = layout_bubble(state, self.anchor, PixelRect(400, 250, 200, 200), [self.display], scale=2)
        self.assertLessEqual(layout.bounds.width, 840)
        self.assertGreater(len(layout.wrapped_lines), 1)

    def test_streaming_caption_replaces_previous_partial_text(self) -> None:
        controller = SpeechBubbleController()
        first = controller.update("Hel", partial=True, now=0)
        second = controller.update("Hello", partial=True, now=0.1)
        final = controller.update("Hello.", final=True, now=0.2)
        self.assertEqual((first.text, second.text, final.text), ("Hel", "Hello", "Hello."))
        self.assertTrue(final.final)

    def test_approval_is_persistent_until_detached(self) -> None:
        controller = SpeechBubbleController()
        state = controller.update("Approve?", kind=BubbleKind.APPROVAL, now=0, timeout_seconds=1)
        self.assertTrue(state.persistent)
        self.assertTrue(controller.tick(now=100).visible)
        self.assertFalse(controller.detach(now=101).visible)

    def test_caption_timeout(self) -> None:
        controller = SpeechBubbleController()
        controller.update("Temporary", now=0, timeout_seconds=2)
        self.assertTrue(controller.tick(now=1).visible)
        self.assertFalse(controller.tick(now=2).visible)

    def test_warning_error_and_high_contrast_are_typed(self) -> None:
        controller = SpeechBubbleController()
        warning = controller.update("Warning", kind=BubbleKind.WARNING, high_contrast=True, now=0)
        error = controller.update("Error", kind=BubbleKind.ERROR, high_contrast=True, now=1)
        self.assertEqual(warning.kind, BubbleKind.WARNING)
        self.assertEqual(error.kind, BubbleKind.ERROR)
        self.assertTrue(error.high_contrast)

    def test_control_characters_are_removed_and_length_bounded(self) -> None:
        value = sanitize_bubble_text("safe\x00\x01" + "x" * 5000)
        self.assertNotIn("\x00", value)
        self.assertLessEqual(len(value), 4096)

    def test_content_is_keyboard_and_screen_reader_accessible(self) -> None:
        state = SpeechBubbleController().update("Accessible", now=0)
        self.assertTrue(state.keyboard_accessible)
        self.assertTrue(state.announce_to_screen_reader)

    def test_character_on_second_display_anchors_bubble_there(self) -> None:
        second = Display("second", PixelRect(1280, 0, 1280, 720), False)
        state = SpeechBubbleController().update("Second display", now=0)
        layout = layout_bubble(state, self.anchor, PixelRect(1500, 200, 200, 200), [self.display, second])
        self.assertEqual(layout.display_id, "second")


class LipSyncTests(unittest.TestCase):
    def controller(self, shapes=None) -> LipSyncController:
        return LipSyncController(shapes or [shape.value for shape in MouthShape])

    def test_sequence_advances_monotonically(self) -> None:
        controller = self.controller()
        controller.start([
            LipSyncEvent(0, MouthShape.CLOSED),
            LipSyncEvent(100, MouthShape.OPEN_SMALL),
            LipSyncEvent(200, MouthShape.OPEN_WIDE),
        ])
        self.assertEqual(controller.advance(100).shape, MouthShape.OPEN_SMALL)
        self.assertEqual(controller.advance(199).shape, MouthShape.OPEN_SMALL)

    def test_non_monotonic_timestamps_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "monotonic"):
            validate_lip_sync_events([
                LipSyncEvent(10, MouthShape.OPEN_SMALL), LipSyncEvent(5, MouthShape.CLOSED)
            ])

    def test_cancellation_and_audio_interruption_return_neutral(self) -> None:
        controller = self.controller(); controller.start([LipSyncEvent(0, MouthShape.OPEN_WIDE)])
        status = controller.cancel("audio interrupted")
        self.assertTrue(status.cancelled)
        self.assertEqual(status.shape, MouthShape.NEUTRAL)
        self.assertIn("interrupted", status.explanation)

    def test_missing_mouth_shape_falls_back_to_neutral(self) -> None:
        controller = self.controller(["neutral"])
        controller.start([LipSyncEvent(0, MouthShape.OPEN_WIDE), LipSyncEvent(100, MouthShape.CLOSED)])
        self.assertEqual(controller.advance(0).shape, MouthShape.NEUTRAL)

    def test_audio_drift_is_reported_not_claimed_accurate(self) -> None:
        controller = self.controller(); controller.start([
            LipSyncEvent(0, MouthShape.CLOSED), LipSyncEvent(1000, MouthShape.NEUTRAL)
        ])
        status = controller.advance(100, audio_clock_ms=500)
        self.assertTrue(status.drift_detected)
        self.assertEqual(status.drift_ms, 400)

    def test_completion_returns_neutral(self) -> None:
        controller = self.controller(); controller.start([LipSyncEvent(0, MouthShape.OPEN_WIDE)])
        status = controller.advance(0)
        self.assertFalse(status.active)
        self.assertEqual(status.shape, MouthShape.NEUTRAL)

    def test_reduced_motion_keeps_mouth_neutral(self) -> None:
        controller = self.controller(); controller.start(
            [LipSyncEvent(0, MouthShape.OPEN_WIDE), LipSyncEvent(100, MouthShape.NEUTRAL)],
            reduced_motion=True,
        )
        self.assertEqual(controller.advance(0).shape, MouthShape.NEUTRAL)

    def test_amplitude_fallback_uses_generic_shapes(self) -> None:
        self.assertEqual(amplitude_to_shape(0), MouthShape.CLOSED)
        self.assertEqual(amplitude_to_shape(0.2), MouthShape.OPEN_SMALL)
        self.assertEqual(amplitude_to_shape(0.5), MouthShape.OPEN_MEDIUM)
        self.assertEqual(amplitude_to_shape(0.9), MouthShape.OPEN_WIDE)

    def test_phoneme_viseme_amplitude_and_speaking_sources_are_provider_neutral(self) -> None:
        events = [LipSyncEvent(index * 10, MouthShape.NEUTRAL, source) for index, source in enumerate(
            ("phoneme", "viseme", "amplitude", "speaking-state")
        )]
        self.assertEqual(len(validate_lip_sync_events(events)), 4)


class PositioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.primary = Display("primary", PixelRect(0, 0, 1000, 800), True)
        self.second = Display("second", PixelRect(1000, 0, 1000, 800), False)

    def place(self, placement: Placement, **kwargs):
        return place_character([self.primary], size=(100, 120), placement=placement, **kwargs)

    def test_center_and_four_docking_positions(self) -> None:
        expected_x = {
            Placement.CENTER_SCREEN: 450,
            Placement.DOCK_LEFT: 16,
            Placement.DOCK_RIGHT: 884,
            Placement.BOTTOM_LEFT: 16,
            Placement.BOTTOM_RIGHT: 884,
        }
        for placement, x in expected_x.items():
            with self.subTest(placement=placement):
                self.assertEqual(self.place(placement).character.x, x)

    def test_compact_floating_is_edge_constrained(self) -> None:
        decision = self.place(Placement.COMPACT_FLOATING)
        self.assertGreaterEqual(decision.character.x, 0)
        self.assertLessEqual(decision.character.right, 1000)

    def test_user_dragged_position_snaps_to_targets_without_focus(self) -> None:
        decision = self.place(Placement.USER_DRAGGED, dragged_origin=(20, 20))
        self.assertIn("left", decision.snap_target)
        self.assertFalse(decision.accepts_keyboard_focus)

    def test_screen_edge_constraints(self) -> None:
        decision = self.place(Placement.USER_DRAGGED, dragged_origin=(-500, 5000))
        self.assertGreaterEqual(decision.character.x, 16)
        self.assertLessEqual(decision.character.bottom, 784)

    def test_oversized_scaled_character_is_constrained_to_work_area(self) -> None:
        decision = place_character(
            [self.primary], size=(5000, 4000), placement=Placement.CENTER_SCREEN
        )
        self.assertGreaterEqual(decision.character.x, 16)
        self.assertGreaterEqual(decision.character.y, 16)
        self.assertLessEqual(decision.character.right, 984)
        self.assertLessEqual(decision.character.bottom, 784)
        self.assertTrue(any("constrained" in reason for reason in decision.reasons))

    def test_fullscreen_application_uses_compact_avoidance(self) -> None:
        decision = self.place(Placement.CENTER_SCREEN, fullscreen_application=True)
        self.assertTrue(decision.avoids_fullscreen)
        self.assertGreater(decision.character.x, 500)

    def test_task_panel_is_avoided(self) -> None:
        panel = PixelRect(850, 500, 150, 300)
        decision = self.place(Placement.BOTTOM_RIGHT, task_panel=panel)
        self.assertFalse(decision.character.intersects(panel))
        self.assertTrue(decision.avoids_task_panel)

    def test_saved_position_uses_its_display(self) -> None:
        saved = SavedPosition("second", 0.5, 0.5)
        decision = place_character([self.primary, self.second], size=(100, 100),
                                   placement=Placement.USER_DRAGGED, saved=saved)
        self.assertEqual(decision.display_id, "second")

    def test_display_removal_recovers_to_primary(self) -> None:
        saved = SavedPosition("removed", 0.5, 0.5)
        decision = place_character([self.primary], size=(100, 100),
                                   placement=Placement.USER_DRAGGED, saved=saved)
        self.assertEqual(decision.display_id, "primary")
        self.assertTrue(decision.recovered_from_removed_display)

    def test_saved_position_round_trip(self) -> None:
        decision = self.place(Placement.USER_DRAGGED, dragged_origin=(300, 400))
        saved = saved_from_decision(decision, self.primary)
        with tempfile.TemporaryDirectory() as temporary:
            store = PositionStore(Path(temporary) / "position.json")
            store.save(saved)
            self.assertEqual(store.load(), saved)

    def test_bubble_safe_area_is_preserved(self) -> None:
        decision = self.place(Placement.DOCK_LEFT, bubble_safe_area=200)
        self.assertGreaterEqual(decision.character.y, 200)


if __name__ == "__main__":
    unittest.main()

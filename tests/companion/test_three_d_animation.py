# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§8-§14 and §17-§18, with no GPU anywhere in them.

Everything below the driver is pure: the state machine, the mixer, the face rig,
the procedural behaviour and the camera all take numbers and return numbers. So
these tests run on a build machine with no graphics stack, which is the only way
they get run on every commit — and it is why those five modules were written
without a GL call in them in the first place.
"""

from __future__ import annotations

import math
import unittest

from companion.character.lipsync import MouthShape
from companion.character.mapper import CharacterState, priority_rank
from companion.character.three_d.animation import (
    ANIMATION_STATES,
    CANDIDATES,
    DEFAULT_CROSSFADE,
    LOOPING_STATES,
    MAXIMUM_LAYERS,
    AnimationStateMachine,
    Pose,
    blend_poses,
    nlerp,
)
from companion.character.three_d.face import (
    EXPRESSIONS,
    MOUTH_OPENNESS,
    STATE_EXPRESSIONS,
    FaceController,
    FaceRig,
)
from companion.character.three_d.glb import validate_glb
from companion.character.three_d.procedural import (
    ATTENTION_TARGETS,
    MINIMUM_INTERVAL,
    ProceduralBehaviour,
)
from companion.character.three_d.scene import (
    CAMERA_FRAMINGS,
    DISTANCE_RANGE,
    FOV_RANGE,
    PLACEMENT_CAMERAS,
    DEFAULT_LIGHTING,
    LIGHTWEIGHT_LIGHTING,
    PresentationCamera,
)
from tests.companion.three_d_support import valid_glb

_CLIPS = (
    "idle", "working", "speaking", "error", "listening", "success",
    "waiting-for-approval", "blocked",
)


def _model():
    return validate_glb(valid_glb(animations=_CLIPS))


def _machine(motion: str = "full"):
    model = _model()
    return AnimationStateMachine(model, {name: name for name in _CLIPS}, motion=motion), model


class StateSelectionTests(unittest.TestCase):
    def test_every_animation_state_is_reachable_from_a_character_state(self) -> None:
        reachable = {name for chain in CANDIDATES.values() for name in chain}
        self.assertEqual(reachable, set(ANIMATION_STATES) - {"greeting"} | {"greeting"})

    def test_every_candidate_chain_ends_in_idle(self) -> None:
        for state, chain in CANDIDATES.items():
            self.assertEqual(chain[-1], "idle", f"{state} does not fall back to idle")

    def test_a_missing_animation_falls_through_its_chain(self) -> None:
        model = _model()
        machine = AnimationStateMachine(model, {"idle": "idle", "working": "working"})
        state, clip, chain = machine.resolve(CharacterState.RESEARCHING)
        self.assertEqual(state, "working")
        self.assertEqual(chain, ("researching", "working", "idle"))

    def test_an_unmapped_state_lands_on_idle_rather_than_failing(self) -> None:
        model = _model()
        machine = AnimationStateMachine(model, {"idle": "idle"})
        state, _clip, _chain = machine.resolve(CharacterState.SLEEPING)
        self.assertEqual(state, "idle")

    def test_a_state_map_without_idle_is_refused(self) -> None:
        from companion.character.three_d.errors import ModelSchemaError

        with self.assertRaisesRegex(ModelSchemaError, "must resolve idle"):
            AnimationStateMachine(_model(), {"working": "working"})

    def test_a_map_naming_a_clip_the_model_lacks_is_refused(self) -> None:
        from companion.character.three_d.errors import ModelSchemaError

        with self.assertRaisesRegex(ModelSchemaError, "does not carry"):
            AnimationStateMachine(_model(), {"idle": "idle", "working": "nonexistent"})


class PriorityTests(unittest.TestCase):
    def test_an_error_interrupts_a_working_animation_immediately(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.WORKING, now=0.0)
        decision = machine.request(CharacterState.ERROR, now=0.5)
        self.assertEqual(decision.animation_state, "error")
        self.assertFalse(decision.held)
        self.assertIn("outranks", decision.reason)

    def test_an_approval_interrupts_work(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.WORKING, now=0.0)
        decision = machine.request(CharacterState.WAITING_FOR_APPROVAL, now=0.2)
        self.assertEqual(decision.animation_state, "waiting-for-approval")
        self.assertFalse(decision.held)

    def test_a_cosmetic_animation_never_displaces_an_error(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.ERROR, now=0.0)
        decision = machine.request(CharacterState.IDLE, now=0.1)
        self.assertTrue(decision.held)
        self.assertEqual(decision.animation_state, "error")

    def test_a_finished_one_shot_releases_the_hold(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.ERROR, now=0.0)
        # The test clip is one second long; after it, idle is permitted.
        decision = machine.request(CharacterState.IDLE, now=4.0)
        self.assertFalse(decision.held)
        self.assertEqual(decision.animation_state, "idle")

    def test_urgent_states_use_the_shorter_crossfade(self) -> None:
        urgent_machine, _model = _machine()
        urgent_machine.request(CharacterState.IDLE, now=0.0)
        urgent = urgent_machine.request(CharacterState.WAITING_FOR_APPROVAL, now=1.0)
        ordinary_machine, _model = _machine()
        ordinary_machine.request(CharacterState.IDLE, now=0.0)
        ordinary = ordinary_machine.request(CharacterState.WORKING, now=1.0)
        self.assertLess(urgent.crossfade_seconds, ordinary.crossfade_seconds)
        self.assertEqual(ordinary.crossfade_seconds, DEFAULT_CROSSFADE)

    def test_the_section_nine_order_matches_the_canonical_ranking(self) -> None:
        self.assertLess(priority_rank(CharacterState.ERROR), priority_rank(CharacterState.BLOCKED))
        self.assertLess(
            priority_rank(CharacterState.WAITING_FOR_APPROVAL),
            priority_rank(CharacterState.LISTENING),
        )
        self.assertLess(priority_rank(CharacterState.SPEAKING), priority_rank(CharacterState.WORKING))
        self.assertLess(priority_rank(CharacterState.SUCCESS), priority_rank(CharacterState.IDLE))

    def test_looping_and_one_shot_states_are_distinguished(self) -> None:
        self.assertIn("idle", LOOPING_STATES)
        self.assertIn("working", LOOPING_STATES)
        self.assertNotIn("success", LOOPING_STATES)
        self.assertNotIn("error", LOOPING_STATES)


class BlendingTests(unittest.TestCase):
    def test_a_crossfade_runs_from_zero_to_one_and_then_ends(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.IDLE, now=0.0)
        machine.request(CharacterState.WORKING, now=1.0)
        self.assertAlmostEqual(machine.blend_weight(1.0), 0.0, places=5)
        self.assertGreater(machine.blend_weight(1.0 + DEFAULT_CROSSFADE / 2), 0.3)
        self.assertEqual(machine.blend_weight(2.0), 1.0)
        machine.evaluate(2.0)
        self.assertIsNone(machine.previous)

    def test_the_layer_count_never_exceeds_the_bound(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.IDLE, now=0.0)
        machine.request(CharacterState.WORKING, now=0.5)
        machine.set_upper_body_overlay("listening", now=0.5)
        status = machine.status(0.55)
        self.assertLessEqual(status["layers"], MAXIMUM_LAYERS)
        self.assertEqual(status["maximumLayers"], MAXIMUM_LAYERS)
        self.assertEqual(status["overlay"], "listening")

    def test_an_overlay_the_package_lacks_is_simply_absent(self) -> None:
        machine, _model = _machine()
        self.assertFalse(machine.set_upper_body_overlay("nonexistent", now=0.0))
        self.assertIsNone(machine.overlay)

    def test_blending_keeps_keys_present_in_only_one_pose(self) -> None:
        base = Pose(translations={1: (0.0, 0.0, 0.0)})
        overlay = Pose(translations={2: (1.0, 1.0, 1.0)})
        result = blend_poses(base, overlay, 0.5)
        self.assertEqual(result.translations[1], (0.0, 0.0, 0.0))
        self.assertEqual(result.translations[2], (1.0, 1.0, 1.0))

    def test_quaternion_blending_takes_the_short_arc_and_stays_unit_length(self) -> None:
        start = (0.0, 0.0, 0.0, 1.0)
        end = (0.0, 0.0, -0.7071, -0.7071)
        blended = nlerp(start, end, 0.5)
        self.assertAlmostEqual(sum(component ** 2 for component in blended), 1.0, places=5)
        self.assertGreaterEqual(blended[3], 0.0)

    def test_reduced_motion_removes_the_crossfade_and_holds_the_first_frame(self) -> None:
        machine, _model = _machine(motion="reduced")
        machine.request(CharacterState.IDLE, now=0.0)
        decision = machine.request(CharacterState.WORKING, now=1.0)
        self.assertEqual(decision.crossfade_seconds, 0.0)
        self.assertIsNone(machine.previous)
        first = machine.evaluate(1.0)
        later = machine.evaluate(9.0)
        self.assertEqual(first.rotations, later.rotations)

    def test_no_animation_mode_produces_an_empty_pose(self) -> None:
        machine, _model = _machine(motion="none")
        machine.request(CharacterState.WORKING, now=0.0)
        pose = machine.evaluate(1.0)
        self.assertEqual(pose.rotations, {})
        self.assertEqual(pose.translations, {})

    def test_a_looping_clip_wraps_rather_than_stopping(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.IDLE, now=0.0)
        early = machine.evaluate(0.25)
        wrapped = machine.evaluate(1.25)
        self.assertEqual(set(early.rotations), set(wrapped.rotations))
        self.assertFalse(machine.finished(50.0))

    def test_return_to_idle_only_fires_after_a_one_shot_finishes(self) -> None:
        machine, _model = _machine()
        machine.request(CharacterState.SUCCESS, now=0.0)
        self.assertIsNone(machine.return_to_idle(now=0.2))
        decision = machine.return_to_idle(now=5.0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.animation_state, "idle")


class WeightAnimationTests(unittest.TestCase):
    """A morph-weight clip: the shape the validator refused for one commit."""

    def test_a_weight_animation_validates(self) -> None:
        from tests.companion.three_d_support import glb_with_weight_animation

        model = validate_glb(glb_with_weight_animation())
        clip = model.clips[0]
        channel = clip.channels[0]
        self.assertEqual(channel.path, "weights")
        sampler = clip.samplers[channel.sampler]
        # The stride is the morph-target count, not the accessor's element size.
        self.assertEqual(sampler.stride, len(model.morph_target_names))
        self.assertEqual(len(sampler.output), len(sampler.input_times) * sampler.stride)

    def test_a_weight_animation_samples_one_value_per_target(self) -> None:
        from companion.character.three_d.animation import ClipSampler
        from tests.companion.three_d_support import glb_with_weight_animation

        model = validate_glb(glb_with_weight_animation())
        sampler = ClipSampler(model.clips[0], morph_target_count=len(model.morph_target_names))
        pose = sampler.sample(0.0)
        self.assertEqual(sorted(pose.weights), list(range(len(model.morph_target_names))))
        for index in pose.weights:
            self.assertLess(index, len(model.morph_target_names))

    def test_a_weight_sampler_with_the_wrong_length_is_refused(self) -> None:
        from companion.character.three_d.errors import ModelSchemaError
        from tests.companion.three_d_support import build_document

        document, builder = build_document(morph_targets=("a", "b"))
        mesh_node = len(document["nodes"]) - 1
        times = builder.floats([0.0, 0.5, 1.0], "SCALAR", bounds=True)
        # Three values for three keyframes over *two* targets: six are needed.
        output = builder.floats([0.0, 0.5, 1.0], "SCALAR")
        document["animations"][0] = {
            "name": "idle",
            "samplers": [{"input": times, "output": output, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": mesh_node, "path": "weights"}}],
        }
        with self.assertRaisesRegex(ModelSchemaError, "needs 6"):
            validate_glb(builder.pack(document))


class FaceTests(unittest.TestCase):
    def test_expressions_resolve_to_morph_targets_where_they_exist(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("smile", "brow_lower")))
        rig = FaceRig(model, expression_map={"happy": {"smile": 0.9}})
        self.assertEqual(rig.expressions["happy"].mechanism, "morph-targets")
        self.assertEqual(rig.expressions["happy"].targets, ((0, 0.9),))

    def test_an_expression_with_no_morphs_falls_back_to_neutral_without_failing(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("smile",)))
        rig = FaceRig(model, expression_map={})
        self.assertEqual(rig.expressions["surprised"].mechanism, "neutral-fallback")
        self.assertEqual(rig.expressions["neutral"].mechanism, "neutral")
        controller = FaceController(rig)
        self.assertEqual(controller.set_expression("surprised"), "surprised")

    def test_every_section_eleven_expression_resolves_to_something(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("smile",)))
        rig = FaceRig(model, expression_map={"happy": {"smile": 1.0}})
        for expression in EXPRESSIONS:
            self.assertIn(expression, rig.expressions)

    def test_a_missing_mouth_morph_uses_the_jaw_bone(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("smile",)))
        rig = FaceRig(model, viseme_map={})
        self.assertEqual(rig.visemes["open-wide"].mechanism, "jaw-bone")
        self.assertIsNotNone(rig.visemes["open-wide"].bone)
        controller = FaceController(rig)
        controller.set_mouth_shape("open-wide")
        controller.advance(0.0)
        controller.advance(1.0)
        pose = controller.pose()
        self.assertIn(rig.jaw, pose.rotations)

    def test_a_mouth_morph_wins_over_the_jaw_when_the_package_has_one(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("mouth_open_wide", "smile")))
        rig = FaceRig(model, viseme_map={"open-wide": {"mouth_open_wide": 1.0}})
        self.assertEqual(rig.visemes["open-wide"].mechanism, "morph-targets")
        controller = FaceController(rig)
        controller.set_mouth_shape("open-wide")
        controller.advance(0.0)
        controller.advance(1.0)
        self.assertGreater(controller.pose().weights[0], 0.5)

    def test_an_unknown_mouth_shape_closes_rather_than_holding(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("mouth_open_wide",)))
        rig = FaceRig(model, viseme_map={"open-wide": {"mouth_open_wide": 1.0}})
        controller = FaceController(rig)
        controller.set_mouth_shape("open-wide")
        self.assertEqual(controller.set_mouth_shape("klingon"), MouthShape.NEUTRAL.value)

    def test_speech_completion_returns_the_mouth_to_neutral(self) -> None:
        model = validate_glb(valid_glb(morph_targets=("mouth_open_wide",)))
        rig = FaceRig(model, viseme_map={"open-wide": {"mouth_open_wide": 1.0}})
        controller = FaceController(rig)
        controller.set_mouth_shape("open-wide")
        controller.reset_mouth()
        self.assertEqual(controller.mouth_shape, MouthShape.NEUTRAL.value)

    def test_every_generic_mouth_shape_has_an_openness(self) -> None:
        for shape in MouthShape:
            self.assertIn(shape.value, MOUTH_OPENNESS)

    def test_every_character_state_maps_to_a_known_expression(self) -> None:
        for state, expression in STATE_EXPRESSIONS.items():
            self.assertIn(expression, EXPRESSIONS, f"{state} maps to {expression}")

    def test_the_mouth_moves_faster_than_the_expression(self) -> None:
        from companion.character.three_d.face import (
            EXPRESSION_RESPONSE_PER_SECOND,
            MOUTH_RESPONSE_PER_SECOND,
        )

        self.assertGreater(MOUTH_RESPONSE_PER_SECOND, EXPRESSION_RESPONSE_PER_SECOND)


class ProceduralTests(unittest.TestCase):
    def _behaviour(self, **arguments) -> ProceduralBehaviour:
        model = _model()
        return ProceduralBehaviour(model.skeleton, **arguments)

    def test_a_seed_makes_the_behaviour_reproducible(self) -> None:
        first = self._behaviour(seed=11)
        second = self._behaviour(seed=11)
        for behaviour in (first, second):
            behaviour.reset(now=0.0)
            for step in range(400):
                behaviour.advance(step * 0.05)
        self.assertEqual(first.blinks, second.blinks)
        self.assertEqual(first.saccades, second.saccades)
        self.assertEqual(first.head_turns, second.head_turns)
        self.assertTrue(first.deterministic)

    def test_behaviours_respect_the_minimum_interval(self) -> None:
        behaviour = self._behaviour(seed=3)
        behaviour.reset(now=0.0)
        blinks: list[float] = []
        previous = behaviour.blinks
        for step in range(2000):
            now = step * 0.02
            behaviour.advance(now)
            if behaviour.blinks != previous:
                blinks.append(now)
                previous = behaviour.blinks
        gaps = [second - first for first, second in zip(blinks, blinks[1:])]
        self.assertTrue(gaps)
        self.assertGreaterEqual(min(gaps), MINIMUM_INTERVAL)

    def test_suspension_stops_everything_and_leaves_no_queue(self) -> None:
        behaviour = self._behaviour(seed=5)
        behaviour.reset(now=0.0)
        behaviour.advance(4.0)
        behaviour.suspend("battery")
        before = behaviour.blinks
        for step in range(500):
            behaviour.advance(10.0 + step * 0.1)
        self.assertEqual(behaviour.blinks, before)
        self.assertEqual(behaviour.pose(20.0).rotations, {})
        status = behaviour.status(20.0)
        self.assertTrue(status["suspended"])
        self.assertEqual(status["pendingBehaviours"], 0)

    def test_resuming_re_arms_rather_than_catching_up(self) -> None:
        behaviour = self._behaviour(seed=5)
        behaviour.reset(now=0.0)
        behaviour.suspend("thermal")
        behaviour.resume(now=600.0)
        before = behaviour.blinks
        behaviour.advance(600.1)
        self.assertEqual(behaviour.blinks, before, "a resumed behaviour owes nothing")

    def test_reduced_motion_keeps_the_blink_and_drops_the_movement(self) -> None:
        behaviour = self._behaviour(seed=9, motion="reduced")
        behaviour.reset(now=0.0)
        for step in range(600):
            behaviour.advance(step * 0.05)
        self.assertGreater(behaviour.blinks, 0)
        self.assertEqual(behaviour.saccades, 0)
        self.assertEqual(behaviour.head_turns, 0)

    def test_attention_targets_come_from_the_layout_and_nothing_else(self) -> None:
        behaviour = self._behaviour(seed=1)
        self.assertEqual(
            behaviour.attention_for_state("waiting_for_approval", bubble_visible=False),
            "task-panel",
        )
        self.assertEqual(behaviour.attention_for_state("speaking", bubble_visible=True), "bubble")
        self.assertEqual(behaviour.attention_for_state("listening", bubble_visible=False), "listening")
        self.assertEqual(behaviour.look_at("the user's face"), "forward")
        for name in ATTENTION_TARGETS:
            self.assertEqual(behaviour.look_at(name), name)

    def test_the_head_rotation_stays_small(self) -> None:
        behaviour = self._behaviour(seed=2)
        behaviour.reset(now=0.0)
        model = _model()
        head = model.skeleton.index("head")
        largest = 0.0
        for step in range(1200):
            now = step * 0.05
            behaviour.advance(now)
            rotation = behaviour.pose(now).rotations.get(head)
            if rotation is not None:
                angle = 2 * math.acos(min(1.0, abs(rotation[3])))
                largest = max(largest, angle)
        self.assertLess(largest, 0.6, "a companion looks around, it does not swivel")


class CameraTests(unittest.TestCase):
    def _camera(self) -> PresentationCamera:
        return PresentationCamera(_model().bounds, aspect=0.8)

    def test_every_placement_maps_to_a_camera_mode(self) -> None:
        from companion.presentation import PLACEMENTS

        for placement in PLACEMENTS:
            self.assertIn(placement, PLACEMENTS)
            self.assertIn(PLACEMENT_CAMERAS[placement], CAMERA_FRAMINGS)

    def test_the_camera_is_deterministic(self) -> None:
        camera = self._camera()
        camera.set_mode("waist-up")
        first = camera.state()
        second = camera.state()
        self.assertEqual(first.to_json(), second.to_json())

    def test_every_mode_stays_inside_its_bounds(self) -> None:
        camera = self._camera()
        for mode in CAMERA_FRAMINGS:
            camera.set_mode(mode)
            state = camera.state()
            self.assertGreaterEqual(state.fov_degrees, FOV_RANGE[0])
            self.assertLessEqual(state.fov_degrees, FOV_RANGE[1])
            distance = math.dist(state.position, state.target)
            self.assertGreaterEqual(distance, DISTANCE_RANGE[0] - 1e-6)
            self.assertLessEqual(distance, DISTANCE_RANGE[1] + 1e-6)
            self.assertGreater(state.far, state.near)
            projection = state.projection()
            self.assertEqual(len(projection), 16)

    def test_a_closer_mode_frames_less_of_the_character(self) -> None:
        camera = self._camera()
        camera.set_mode("full-body")
        full = math.dist(camera.state().position, camera.state().target)
        camera.set_mode("close-speaking")
        close = math.dist(camera.state().position, camera.state().target)
        self.assertLess(close, full)

    def test_an_unknown_mode_falls_back_rather_than_failing(self) -> None:
        camera = self._camera()
        self.assertEqual(camera.set_mode("cinematic-drone"), "full-body")

    def test_an_absurd_aspect_is_clamped(self) -> None:
        camera = self._camera()
        camera.set_aspect(10_000.0)
        self.assertLessEqual(camera.aspect, 8.0)
        camera.set_aspect(0.0001)
        self.assertGreaterEqual(camera.aspect, 0.2)


class LightingTests(unittest.TestCase):
    def test_the_lighting_is_a_constant_with_no_environment_map(self) -> None:
        payload = DEFAULT_LIGHTING.to_json()
        self.assertIsNone(payload["environmentMap"])
        self.assertFalse(payload["packageSuppliedLights"])
        self.assertEqual(payload["key"]["intensity"], DEFAULT_LIGHTING.key.intensity)

    def test_the_lightweight_rig_evaluates_one_light(self) -> None:
        self.assertEqual(LIGHTWEIGHT_LIGHTING.fill.intensity, 0.0)
        self.assertGreater(LIGHTWEIGHT_LIGHTING.key.intensity, DEFAULT_LIGHTING.key.intensity)
        self.assertGreater(
            sum(LIGHTWEIGHT_LIGHTING.ambient), sum(DEFAULT_LIGHTING.ambient)
        )


if __name__ == "__main__":
    unittest.main()

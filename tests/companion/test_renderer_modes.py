# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three renderer modes, the idle policy, and the switching between them.

The properties asserted here are the ones the polished-alpha brief states as
requirements rather than as implementation: pre-rendered is what a machine gets
when nobody has chosen, a mode is a ceiling and never a floor, a renderer that
will not start is replaced within the same frame, an idle companion stops
drawing, and none of that can happen while the user is being asked a question.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from companion.character.adaptation import (
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.animated_renderer import Animated2DRenderer
from companion.character.controller import CharacterRendererController
from companion.character.defaults import default_character_path, default_character_paths
from companion.character.importer import PackageRegistry
from companion.character.lipsync import MouthShape
from companion.character.mapper import (
    CharacterState,
    StateMapperInput,
    map_character_state,
    priority_rank,
)
from companion.character.modes import (
    DEFAULT_MODE,
    MODE_CEILINGS,
    RenderMode,
    mode_from_settings,
    performance_cap,
    renderer_chain,
)
from companion.character.package import PackageTrustState, validate_package_directory
from companion.character.policy import default_character_decision
from companion.character.procedural_renderer import (
    POSE_CHANNELS,
    Procedural2DRenderer,
    _VISEME_OPENING,
)
from companion.character.quiescence import (
    DEFAULT_POLICY,
    NEVER_QUIESCENT,
    QuiescenceLevel,
    QuiescencePolicy,
)
from companion.settings import CharacterSettings, Settings


def _plan(ceiling: Presentation) -> CapabilityPresentationPlan:
    return CapabilityPresentationPlan(
        plan_id="test-plan", requested=ceiling, ceiling=ceiling,
        implementation_id=ceiling.value,
    )


class ModeFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(
            default_character_path(), trust_state=PackageTrustState.BUILT_IN
        )

    def mapped(self, phase: str, **kwargs):
        return map_character_state(
            self.package.manifest, StateMapperInput(presentation_phase=phase, **kwargs)
        )


class ModeVocabularyTests(ModeFixture):
    def test_pre_rendered_is_the_default_mode(self) -> None:
        self.assertIs(DEFAULT_MODE, RenderMode.PRERENDERED)
        self.assertEqual(CharacterSettings().render_mode, "prerendered")
        self.assertIs(CharacterSettings().mode(), RenderMode.PRERENDERED)

    def test_every_mode_has_a_ceiling_and_a_chain_ending_in_the_frame_player(self) -> None:
        for mode in RenderMode:
            self.assertIn(mode, MODE_CEILINGS)
            chain = renderer_chain(mode, Presentation.ANIMATED_2D)
            self.assertTrue(chain, f"{mode} has no 2D chain")
            self.assertEqual(
                chain[-1], "animated-2d",
                "every fallback chain must end at the frame player, which has the "
                "fewest ways to fail",
            )

    def test_a_mode_is_a_ceiling_not_a_floor(self) -> None:
        # Choosing 3D on a machine whose plan permits only a static image must
        # not produce 3D. The plan wins wherever it is lower.
        controller = CharacterRendererController(mode=RenderMode.THREE_D)
        controller.load_package(self.package)
        bounded = controller._bounded_by_mode(_plan(Presentation.STATIC_IMAGE))
        self.assertIs(bounded.ceiling, Presentation.STATIC_IMAGE)

    def test_no_mode_applies_no_ceiling_at_all(self) -> None:
        """A caller that never heard of modes must be left exactly as it was.

        Caught on Linux and not on Windows, which skips the GL tests: making
        pre-rendered the *controller's* default silently capped the 3D presenter
        path at animated-2d, so the slice whose entire job is to draw 3D drew
        2D and asserted 'animated-2d' != 'full-3d'. The product default belongs
        in settings and in the character policy, not in the mechanism.
        """
        controller = CharacterRendererController()
        self.assertIsNone(controller.mode)
        for ceiling in (Presentation.FULL_3D, Presentation.LIGHTWEIGHT_3D, Presentation.ANIMATED_2D):
            self.assertIs(controller._bounded_by_mode(_plan(ceiling)).ceiling, ceiling)

    def test_no_mode_still_serves_the_2d_rung_with_the_frame_player(self) -> None:
        # The rung that existed before modes was always drawn by the frame
        # player, so defaulting the renderer choice must reproduce that.
        controller = CharacterRendererController()
        self.assertEqual(
            renderer_chain(controller.effective_mode, Presentation.ANIMATED_2D),
            ("animated-2d",),
        )

    def test_a_mode_lowers_a_plan_it_is_below_and_says_why(self) -> None:
        controller = CharacterRendererController(mode=RenderMode.PRERENDERED)
        bounded = controller._bounded_by_mode(_plan(Presentation.FULL_3D))
        self.assertIs(bounded.ceiling, Presentation.ANIMATED_2D)
        self.assertTrue(
            any("renderer mode in settings" in reason for reason in bounded.reasons),
            bounded.reasons,
        )

    def test_the_legacy_three_d_setting_can_only_veto(self) -> None:
        # It could only ever restrict, so it restricts; it must never promote.
        self.assertIs(mode_from_settings("3d", three_d="off"), RenderMode.INTERACTIVE_2D)
        self.assertIs(mode_from_settings("3d", three_d="auto"), RenderMode.THREE_D)
        self.assertIs(mode_from_settings("prerendered", three_d="auto"), RenderMode.PRERENDERED)

    def test_an_unreadable_mode_costs_the_preference_not_the_companion(self) -> None:
        self.assertIs(mode_from_settings("holographic"), DEFAULT_MODE)
        self.assertIs(mode_from_settings(None), DEFAULT_MODE)
        self.assertIs(mode_from_settings(""), DEFAULT_MODE)

    def test_settings_round_trip_carries_every_new_field(self) -> None:
        settings = Settings(character=CharacterSettings(
            render_mode="3d", performance="low", idle_animation=False,
            contextual_reactions=False, animation_intensity=0.25,
        ))
        restored = Settings.from_json(settings.to_json()).character
        self.assertEqual(restored.render_mode, "3d")
        self.assertEqual(restored.performance, "low")
        self.assertFalse(restored.idle_animation)
        self.assertFalse(restored.contextual_reactions)
        self.assertAlmostEqual(restored.animation_intensity, 0.25)

    def test_a_settings_file_written_before_this_phase_asks_for_pre_rendered(self) -> None:
        # An upgrade must never silently promote a machine to a heavier renderer.
        legacy = {
            "schemaVersion": Settings().to_json()["schemaVersion"],
            "character": {"threeD": "auto", "scale": 1.0, "dock": "bottom-right"},
        }
        self.assertIs(Settings.from_json(legacy).character.mode(), RenderMode.PRERENDERED)


class DefaultCharacterPolicyTests(ModeFixture):
    def _decision(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            registry = PackageRegistry(
                Path(tmp) / "characters", built_in_paths=default_character_paths()
            )
            return default_character_decision(
                eligible="full-3d", registry=registry, mode=mode
            )

    def test_a_full_3d_machine_defaults_to_the_2d_package(self) -> None:
        """The flip. This machine can run 3D and still gets the light companion."""
        decision = self._decision(RenderMode.PRERENDERED)
        self.assertEqual(decision.rung, "animated-2d")
        self.assertNotEqual(decision.package_id, "bunny-default-3d")

    def test_choosing_3d_still_selects_the_3d_package(self) -> None:
        decision = self._decision(RenderMode.THREE_D)
        self.assertEqual(decision.rung, "full-3d")
        self.assertEqual(decision.package_id, "bunny-default-3d")

    def test_the_reason_distinguishes_choice_from_incapability(self) -> None:
        decision = self._decision(RenderMode.PRERENDERED)
        self.assertTrue(
            any("renderer mode in settings" in reason for reason in decision.reasons),
            "a user asking why they are not seeing 3D must be told it was a setting, "
            f"not their hardware: {decision.reasons}",
        )


class ProceduralRendererTests(ModeFixture):
    def renderer(self, **kwargs) -> Procedural2DRenderer:
        renderer = Procedural2DRenderer(seed=7, **kwargs)
        renderer.load_package(self.package)
        return renderer

    def drive(self, renderer, mapped, *, start_ms=0, frames=40, step=33):
        renderer.display_state(mapped, now_ms=start_ms)
        now = start_ms
        frame = renderer.frame
        for _ in range(frames):
            now += step
            frame = renderer.tick(now_ms=now)
        return frame, now

    def test_states_the_user_must_tell_apart_have_different_poses(self) -> None:
        """§7: the user should never have to guess which state Bunny is in.

        Asserted on the pose alone — no colour, no caption. Two states that
        render to the same numbers are two states a person cannot distinguish.
        """
        renderer = self.renderer()
        poses = {}
        now = 0
        for phase in ("idle", "working", "waiting_for_approval", "success", "error", "listening"):
            frame, now = self.drive(renderer, self.mapped(phase), start_ms=now)
            poses[phase] = tuple(round(v, 2) for _, v in frame.pose)
        for left in poses:
            for right in poses:
                if left < right:
                    self.assertNotEqual(
                        poses[left], poses[right],
                        f"{left} and {right} render to the same pose",
                    )

    def test_waiting_for_approval_is_upright_attentive_and_still(self) -> None:
        renderer = self.renderer()
        frame, _ = self.drive(renderer, self.mapped("waiting_for_approval"))
        pose = dict(frame.pose)
        self.assertLess(abs(pose["lean"]), 0.1, "the approval pose faces the user square-on")
        self.assertGreater(pose["brow"], 0.2, "the approval pose is visibly attentive")
        self.assertGreater(pose["eye_open"], 0.8)

    def test_success_rises_and_error_slumps(self) -> None:
        renderer = self.renderer()
        success, now = self.drive(renderer, self.mapped("success"))
        self.assertGreater(dict(success.pose)["rise"], 0.2)
        error, _ = self.drive(renderer, self.mapped("error"), start_ms=now)
        self.assertLess(dict(error.pose)["rise"], -0.1)

    def test_the_idle_character_keeps_moving_but_only_slightly(self) -> None:
        """§8: present, not distracting. Motion must exist and must stay small."""
        renderer = self.renderer()
        _, now = self.drive(renderer, self.mapped("idle"), frames=90)
        values = []
        for _ in range(180):
            now += 33
            values.append(dict(renderer.tick(now_ms=now).pose)["rise"])
        span = max(values) - min(values)
        self.assertGreater(span, 0.01, "an idle character that never moves looks frozen")
        self.assertLess(span, 0.15, "idle motion large enough to notice is a distraction")

    def test_the_breath_does_not_accumulate(self) -> None:
        """The oscillator must not integrate into the pose it displaces.

        Written because it did: the sine was added into the stored channel each
        tick, so every tick eased from an already-displaced value and displaced
        it again, and an idle character drifted to eight times its intended
        amplitude and stayed there.
        """
        renderer = self.renderer()
        _, now = self.drive(renderer, self.mapped("idle"), frames=120)
        for _ in range(600):
            now += 33
            renderer.tick(now_ms=now)
        self.assertLess(
            abs(dict(renderer.frame.pose)["rise"]), 0.1,
            "the idle pose drifted away from neutral over time",
        )

    def test_reduced_motion_stops_movement_without_losing_the_state(self) -> None:
        """§9: reduced motion removes movement, never state information."""
        renderer = self.renderer()
        renderer.set_reduced_motion(True)
        frame, now = self.drive(renderer, self.mapped("waiting_for_approval"))
        pose = dict(frame.pose)
        self.assertGreater(pose["brow"], 0.2, "the state must still be readable")
        values = []
        for _ in range(90):
            now += 33
            values.append(dict(renderer.tick(now_ms=now).pose)["rise"])
        self.assertEqual(max(values), min(values), "reduced motion must not oscillate")

    def test_the_first_frame_shows_the_state_rather_than_neutral(self) -> None:
        """A companion appearing in an error state appears in the error pose."""
        renderer = self.renderer()
        frame = renderer.display_state(self.mapped("error"), now_ms=0)
        self.assertLess(dict(frame.pose)["brow"], -0.2)

    def test_a_clock_jump_is_not_integrated_as_one_step(self) -> None:
        renderer = self.renderer()
        self.drive(renderer, self.mapped("idle"), frames=60)
        before = dict(renderer.frame.pose)
        renderer.display_state(self.mapped("working"), now_ms=10_000_000)
        after = dict(renderer.tick(now_ms=10_000_000).pose)
        self.assertNotEqual(before["lean"], after["lean"])
        self.assertLessEqual(abs(after["lean"]), 1.5)

    def test_every_mouth_shape_the_lipsync_controller_emits_is_mapped(self) -> None:
        for shape in MouthShape:
            self.assertIn(
                shape.value, _VISEME_OPENING,
                f"{shape.value} would render as a closed mouth",
            )

    def test_lip_sync_opens_the_mouth_without_swapping_an_asset(self) -> None:
        renderer = self.renderer()
        self.drive(renderer, self.mapped("speaking"))
        renderer.set_mouth_shape(MouthShape.OPEN_WIDE.value)
        wide = dict(renderer.frame.pose)["mouth_open"]
        renderer.set_mouth_shape(MouthShape.CLOSED.value)
        closed = dict(renderer.frame.pose)["mouth_open"]
        self.assertGreater(wide, closed)

    def test_the_pose_is_deterministic_for_a_seed(self) -> None:
        first, _ = self.drive(self.renderer(), self.mapped("idle"), frames=200)
        second, _ = self.drive(self.renderer(), self.mapped("idle"), frames=200)
        self.assertEqual(first.pose, second.pose)

    def test_intensity_zero_keeps_expression_but_removes_departure(self) -> None:
        quiet = self.renderer(intensity=0.0)
        frame, _ = self.drive(quiet, self.mapped("working"))
        pose = dict(frame.pose)
        self.assertAlmostEqual(pose["lean"], 0.0, places=2)
        # Eyes are exempt: closed eyes are a state's meaning, not its decoration.
        sleeping, _ = self.drive(
            self.renderer(intensity=0.0), self.mapped("idle", dormant=True)
        )
        self.assertLess(dict(sleeping.pose)["eye_open"], 0.2)

    def test_it_holds_one_decoded_image_not_every_frame(self) -> None:
        procedural = self.renderer()
        player = Animated2DRenderer()
        player.load_package(self.package)
        self.assertLessEqual(procedural.report_memory_use(), player.report_memory_use())

    def test_every_declared_channel_reaches_the_frame(self) -> None:
        renderer = self.renderer()
        frame, _ = self.drive(renderer, self.mapped("idle"))
        names = {name for name, _ in frame.pose}
        for channel in POSE_CHANNELS:
            self.assertIn(channel, names)

    def test_look_at_is_clamped_rather_than_validated(self) -> None:
        renderer = self.renderer()
        renderer.look_at(50.0, -50.0)
        frame, _ = self.drive(renderer, self.mapped("idle"))
        pose = dict(frame.pose)
        self.assertLessEqual(abs(pose["look_x"]), 1.6)
        self.assertLessEqual(abs(pose["look_y"]), 1.6)

    def test_a_frame_without_a_pose_serialises_exactly_as_before(self) -> None:
        player = Animated2DRenderer()
        player.load_package(self.package)
        frame = player.display_state(self.mapped("idle"))
        self.assertNotIn("pose", frame.to_json())


class QuiescenceTests(ModeFixture):
    def test_an_idle_companion_eventually_stops_drawing(self) -> None:
        decision = DEFAULT_POLICY.evaluate(
            CharacterState.IDLE, seconds_in_state=60.0, active_cap=30
        )
        self.assertIs(decision.level, QuiescenceLevel.QUIESCENT)
        self.assertEqual(decision.frame_rate_cap, 0)
        self.assertFalse(decision.draws)

    def test_it_passes_through_a_drowsy_window_first(self) -> None:
        drowsy = DEFAULT_POLICY.evaluate(
            CharacterState.IDLE, seconds_in_state=10.0, active_cap=30
        )
        self.assertIs(drowsy.level, QuiescenceLevel.DROWSY)
        self.assertGreater(drowsy.frame_rate_cap, 0)
        self.assertLess(drowsy.frame_rate_cap, 30)

    def test_it_never_quiesces_while_the_user_is_owed_something(self) -> None:
        """§15: never leave the user looking at a frozen companion."""
        for state in NEVER_QUIESCENT:
            decision = DEFAULT_POLICY.evaluate(
                state, seconds_in_state=3600.0, active_cap=30
            )
            self.assertTrue(
                decision.draws,
                f"{state.value} stopped drawing after an hour; that is a frozen companion",
            )

    def test_active_work_never_reaches_the_idle_timer(self) -> None:
        for state in (CharacterState.WORKING, CharacterState.PLANNING, CharacterState.TYPING):
            decision = DEFAULT_POLICY.evaluate(
                state, seconds_in_state=3600.0, active_cap=30
            )
            self.assertIs(decision.level, QuiescenceLevel.ACTIVE)

    def test_a_one_shot_animation_is_allowed_to_finish(self) -> None:
        decision = DEFAULT_POLICY.evaluate(
            CharacterState.SUCCESS, seconds_in_state=30.0, active_cap=30, loops=False
        )
        self.assertTrue(decision.draws)

    def test_sleeping_quiesces_soonest(self) -> None:
        decision = DEFAULT_POLICY.evaluate(
            CharacterState.SLEEPING, seconds_in_state=8.0, active_cap=30
        )
        self.assertIs(decision.level, QuiescenceLevel.QUIESCENT)

    def test_turning_idle_animation_off_holds_the_frame(self) -> None:
        decision = DEFAULT_POLICY.evaluate(
            CharacterState.IDLE, seconds_in_state=0.0, active_cap=30, idle_animation=False
        )
        self.assertFalse(decision.draws)

    def test_a_compositor_that_needs_a_timer_can_keep_one(self) -> None:
        policy = QuiescencePolicy(may_stop=False)
        decision = policy.evaluate(CharacterState.IDLE, seconds_in_state=600.0, active_cap=30)
        self.assertTrue(decision.draws)
        self.assertEqual(decision.frame_rate_cap, 1)


class SleepingAndGreetingTests(ModeFixture):
    def test_dormant_reaches_the_sleeping_state(self) -> None:
        self.assertIs(
            self.mapped("idle", dormant=True).character_state, CharacterState.SLEEPING
        )

    def test_greeting_reaches_the_greeting_state(self) -> None:
        self.assertIs(
            self.mapped("idle", greeting=True).character_state, CharacterState.GREETING
        )

    def test_neither_can_mask_something_the_user_must_see(self) -> None:
        for phase in ("waiting_for_approval", "error", "blocked"):
            for flag in ({"dormant": True}, {"greeting": True}):
                mapped = self.mapped(phase, **flag)
                self.assertLess(
                    priority_rank(mapped.character_state),
                    priority_rank(CharacterState.GREETING),
                    f"{flag} hid {phase}",
                )

    def test_a_live_microphone_outranks_sleeping(self) -> None:
        mapped = self.mapped("listening", dormant=True, listening=True)
        self.assertIs(mapped.character_state, CharacterState.LISTENING)


class ControllerSwitchingTests(ModeFixture):
    def controller(self, mode=RenderMode.PRERENDERED) -> CharacterRendererController:
        controller = CharacterRendererController(mode=mode)
        controller.load_package(self.package)
        return controller

    def apply(self, controller, phase="idle", *, now=0.0, now_ms=0, ceiling=Presentation.ANIMATED_2D):
        return controller.apply(
            self.mapped(phase), _plan(ceiling),
            RendererSignals(display_available=True, graphics_ready=True),
            now=now, now_ms=now_ms,
        )

    def test_pre_rendered_mode_uses_the_frame_player(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller)
        self.assertEqual(controller.renderer.renderer_name, "animated-2d")

    def test_2d_mode_uses_the_interactive_renderer(self) -> None:
        controller = self.controller(RenderMode.INTERACTIVE_2D)
        self.apply(controller)
        self.assertEqual(controller.renderer.renderer_name, "interactive-2d")

    def test_switching_mode_preserves_the_visible_state(self) -> None:
        """§16: only the presentation layer changes."""
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller, "working")
        before = controller.mapped_state
        controller.set_mode(RenderMode.INTERACTIVE_2D, now_ms=1000)
        snapshot = self.apply(controller, "working", now=1.0, now_ms=1000)
        self.assertEqual(controller.renderer.renderer_name, "interactive-2d")
        self.assertIs(controller.mapped_state.character_state, before.character_state)
        self.assertEqual(snapshot.mode, "2d")

    def test_switching_mode_preserves_placement_and_scale(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller)
        controller.renderer.set_scale(1.75)
        controller.set_mode(RenderMode.INTERACTIVE_2D, now_ms=500)
        self.apply(controller, now=0.5, now_ms=500)
        self.assertAlmostEqual(controller.renderer.scale, 1.75)

    def test_a_mode_change_is_recorded_as_an_event_the_task_survives(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller)
        controller.set_mode(RenderMode.INTERACTIVE_2D)
        event = next(
            item for item in controller.events if item["eventType"] == "renderer.mode-changed"
        )
        self.assertTrue(event["taskContinues"])
        self.assertEqual(event["mode"], "2d")

    def test_a_renderer_that_will_not_start_falls_back_within_the_same_frame(self) -> None:
        """§15: 2D unavailable → pre-rendered, without a blank frame in between."""
        controller = self.controller(RenderMode.INTERACTIVE_2D)
        original = controller._construct

        def refuse(name, signals, package):
            if name == "interactive-2d":
                raise RuntimeError("no interactive renderer on this machine")
            return original(name, signals, package)

        controller._construct = refuse
        snapshot = self.apply(controller)
        self.assertEqual(controller.renderer.renderer_name, "animated-2d")
        self.assertIsNotNone(snapshot.frame, "the fallback drew a frame immediately")
        self.assertTrue(
            any(item["eventType"] == "renderer.fallback" for item in controller.events)
        )

    def test_the_fallback_does_not_rebuild_the_renderer_every_evaluation(self) -> None:
        controller = self.controller(RenderMode.INTERACTIVE_2D)
        original = controller._construct
        controller._construct = lambda name, s, p: (
            original(name, s, p) if name != "interactive-2d"
            else (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
        self.apply(controller)
        first = controller.renderer
        self.apply(controller, now=1.0, now_ms=1000)
        self.assertIs(controller.renderer, first, "the renderer was rebuilt on every frame")

    def test_a_quiescent_controller_stops_ticking_the_renderer(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller, "idle")
        controller.tick(now_ms=60_000)
        self.assertFalse(controller.last_quiescence.draws)
        self.assertIsNotNone(controller.tick(now_ms=61_000), "the held frame is still returned")

    def test_a_controller_showing_an_approval_never_quiesces(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller, "waiting_for_approval")
        controller.tick(now_ms=3_600_000)
        self.assertTrue(controller.last_quiescence.draws)

    def test_a_state_change_wakes_a_quiescent_controller(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller, "idle")
        controller.tick(now_ms=60_000)
        self.assertFalse(controller.last_quiescence.draws)
        self.apply(controller, "working", now=60.0, now_ms=60_000)
        controller.tick(now_ms=60_033)
        self.assertTrue(controller.last_quiescence.draws)

    def test_the_performance_setting_caps_the_frame_rate(self) -> None:
        for performance, ceiling in (("low", 15), ("balanced", 30), ("high", 60)):
            controller = CharacterRendererController(
                mode=RenderMode.PRERENDERED, performance=performance
            )
            controller.load_package(self.package)
            snapshot = self.apply(controller)
            self.assertLessEqual(snapshot.presentation.frame_rate_cap, ceiling)

    def test_performance_is_a_ceiling_and_never_a_target(self) -> None:
        """'high' must not raise a rate the package or the machine already set.

        The bundled package declares 8 fps, so every performance value should
        leave it at 8. A setting that pushed it to 60 would be inventing frames
        the animation does not have.
        """
        rates = {}
        for performance in ("automatic", "low", "balanced", "high"):
            controller = CharacterRendererController(
                mode=RenderMode.PRERENDERED, performance=performance
            )
            controller.load_package(self.package)
            rates[performance] = self.apply(controller).presentation.frame_rate_cap
        self.assertLessEqual(rates["high"], rates["automatic"])
        self.assertEqual(
            rates["high"], int(self.package.manifest.frame_rate),
            f"'high' changed the package's declared rate: {rates}",
        )

    def test_the_ceiling_is_recorded_as_a_reason_when_it_binds(self) -> None:
        """A user must be able to read why their frame rate is what it is.

        Driven through a stub selector rather than the bundled package, whose
        8 fps is already below every performance ceiling — so on that package the
        setting correctly never binds and there is nothing to explain.
        """
        controller = CharacterRendererController(
            mode=RenderMode.PRERENDERED, performance="low"
        )
        controller.load_package(self.package)
        real = controller.selector

        class Generous:
            events: list = []

            def evaluate(self, plan, package, signals, *, now):
                decision = real.evaluate(plan, package, signals, now=now)
                return replace(decision, frame_rate_cap=60)

        controller.selector = Generous()
        snapshot = self.apply(controller)
        self.assertEqual(snapshot.presentation.frame_rate_cap, 15)
        self.assertTrue(
            any("performance setting" in reason for reason in snapshot.presentation.reasons),
            snapshot.presentation.reasons,
        )

    def test_the_performance_setting_never_changes_which_renderer_runs(self) -> None:
        """§10: 'low' means 3D at a lower frame rate, not a silent demotion."""
        for performance in ("automatic", "low", "balanced", "high"):
            controller = CharacterRendererController(
                mode=RenderMode.INTERACTIVE_2D, performance=performance
            )
            controller.load_package(self.package)
            self.apply(controller)
            self.assertEqual(
                controller.renderer.renderer_name, "interactive-2d",
                f"performance={performance} changed the renderer",
            )

    def test_automatic_performance_adds_no_ceiling_of_its_own(self) -> None:
        self.assertIsNone(performance_cap("automatic"))

    def test_contextual_reactions_gate_the_pointer_response(self) -> None:
        """§10's toggle is enforced in one place, not at every call site."""
        on = CharacterRendererController(mode=RenderMode.INTERACTIVE_2D)
        on.load_package(self.package)
        self.apply(on)
        self.assertTrue(on.look_at(0.5, 0.5))

        off = CharacterRendererController(
            mode=RenderMode.INTERACTIVE_2D, contextual_reactions=False
        )
        off.load_package(self.package)
        self.apply(off)
        self.assertFalse(off.look_at(0.5, 0.5))
        self.assertEqual(dict(off.renderer.frame.pose)["look_x"], 0.0)

    def test_the_frame_player_cannot_react_and_says_so(self) -> None:
        controller = self.controller(RenderMode.PRERENDERED)
        self.apply(controller)
        self.assertFalse(controller.look_at(0.5, 0.5))

    def test_restarting_the_interactive_renderer_does_not_demote_it(self) -> None:
        controller = self.controller(RenderMode.INTERACTIVE_2D)
        self.apply(controller, "working")
        controller.restart_renderer(now_ms=1000)
        self.assertEqual(controller.renderer.renderer_name, "interactive-2d")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

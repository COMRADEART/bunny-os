# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement, persistence, the attention model and the renderer boundary.

§7 asks that four settings "must not unexpectedly reset". Three of them already
round-tripped through the settings document and one — the position — was
persisted by a module nothing called. The tests here are written against the
*observable* property rather than against the storage: a presenter is built, a
thing is changed, a **second presenter** is built over the same root, and the
change is expected to still be there. That is the shape of the failure a user
reports ("it forgets where I put it"), and it is the only shape that would have
caught a store nobody invoked.
"""

from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

from capability.runtime import assess_current_machine

from companion.character.attention import (
    AttentionInput,
    AttentionLevel,
    attention_for,
)
from companion.character.mapper import CharacterState
from companion.character.modes import RenderMode
from companion.character.positioning import (
    Display,
    PixelRect,
    Placement,
    place_character,
)
from companion.character.surface import (
    DEFAULT_CHARACTER_PIXELS,
    POSITION_FILE_NAME,
    CharacterPresenter,
)
from companion.settings import (
    CharacterSettings,
    Settings,
    SettingsError,
    load_settings,
    normalise_dock,
    update_settings,
)

_WIDE = Display("HDMI-1", PixelRect(0, 0, 1920, 1080), True)
_SMALL = Display("HDMI-1", PixelRect(0, 0, 1280, 720), True)


class PresenterFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assessment = assess_current_machine()

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="bunny-experience-")
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def presenter(self, *, display: Display = _WIDE, **kwargs) -> CharacterPresenter:
        return CharacterPresenter(
            self.root, assessment=self.assessment, display=display, **kwargs
        )


class PlacementVocabularyTests(unittest.TestCase):
    """§6 and §7: one vocabulary, not two that disagree."""

    def test_every_settings_dock_value_is_a_real_placement(self) -> None:
        for placement in Placement:
            settings = CharacterSettings(dock=placement.value)
            self.assertIs(settings.placement(), placement)

    def test_the_legacy_names_still_resolve(self) -> None:
        # These were the only values the settings field used to accept. A file
        # on disk still contains one of them.
        self.assertEqual(normalise_dock("center"), "center-screen")
        self.assertEqual(normalise_dock("top-left"), "top-left")
        self.assertEqual(normalise_dock("top-right"), "top-right")
        self.assertEqual(normalise_dock("bottom-right"), "bottom-right")

    def test_the_top_corners_place_at_the_top(self) -> None:
        """They were accepted by settings and unreachable by the engine."""
        for placement, expect_left in (
            (Placement.TOP_LEFT, True), (Placement.TOP_RIGHT, False)
        ):
            decision = place_character(
                [_WIDE], size=(288, 288), placement=placement
            )
            self.assertLess(decision.character.y, _WIDE.work_area.height // 2, placement)
            if expect_left:
                self.assertLess(decision.character.x, _WIDE.work_area.width // 2)
            else:
                self.assertGreater(decision.character.x, _WIDE.work_area.width // 2)

    def test_an_unreadable_dock_costs_the_corner_not_the_companion(self) -> None:
        self.assertEqual(normalise_dock("nowhere"), "bottom-right")
        self.assertEqual(normalise_dock(""), "bottom-right")

    def test_a_bad_dock_is_still_refused_on_the_way_in(self) -> None:
        with self.assertRaises(SettingsError):
            CharacterSettings(dock="somewhere-else")


class SettingsPersistenceTests(PresenterFixture):
    """§7: the four settings that must not unexpectedly reset."""

    def test_mode_scale_and_intensity_survive_a_write_and_reload(self) -> None:
        update_settings(self.root, "character", {
            "render_mode": "2d", "scale": 1.6,
            "animation_intensity": 0.3, "dock": "top-left",
        })
        character = load_settings(self.root).character
        self.assertEqual(character.render_mode, "2d")
        self.assertAlmostEqual(character.scale, 1.6)
        self.assertAlmostEqual(character.animation_intensity, 0.3)
        self.assertIs(character.placement(), Placement.TOP_LEFT)

    def test_a_dragged_position_survives_a_new_presenter(self) -> None:
        """The logout-and-back-in case, which is what a user actually notices."""
        first = self.presenter()
        self.assertIsNone(first.saved_position, "nothing should be saved yet")
        first.reposition((300, 200))
        self.assertTrue((self.root / POSITION_FILE_NAME).is_file())

        second = self.presenter()
        self.assertIsNotNone(second.saved_position, "the dragged position was forgotten")
        self.assertEqual(second.saved_position.display_id, "HDMI-1")

    def test_a_dragged_position_is_proportional_across_a_resolution_change(self) -> None:
        first = self.presenter()
        first.reposition((960, 540))
        saved = first.saved_position

        smaller = place_character(
            [_SMALL], size=(288, 288), placement=Placement.USER_DRAGGED, saved=saved
        )
        self.assertLessEqual(smaller.character.right, _SMALL.work_area.width)
        self.assertLessEqual(smaller.character.bottom, _SMALL.work_area.height)

    def test_a_removed_display_recovers_rather_than_stranding_the_companion(self) -> None:
        first = self.presenter()
        first.reposition((300, 200))
        elsewhere = Display("DP-9", PixelRect(0, 0, 1920, 1080), True)
        decision = place_character(
            [elsewhere], size=(288, 288), placement=Placement.USER_DRAGGED,
            saved=first.saved_position,
        )
        self.assertTrue(decision.recovered_from_removed_display)
        self.assertLessEqual(decision.character.right, elsewhere.work_area.width)

    def test_forgetting_a_position_returns_to_the_named_placement(self) -> None:
        presenter = self.presenter()
        presenter.reposition((300, 200))
        presenter.forget_position()
        self.assertIsNone(presenter.saved_position)
        self.assertFalse((self.root / POSITION_FILE_NAME).is_file())

    def test_scale_opens_at_the_chosen_size_rather_than_jumping_to_it(self) -> None:
        presenter = self.presenter(scale=1.75)
        self.assertAlmostEqual(presenter.scale, 1.75)

    def test_an_out_of_range_scale_is_clamped_not_refused(self) -> None:
        self.assertAlmostEqual(self.presenter(scale=99.0).scale, 3.0)
        self.assertAlmostEqual(self.presenter(scale=0.01).scale, 0.5)

    def test_the_window_passes_every_persisted_preference_to_the_presenter(self) -> None:
        """§7's "single authoritative settings source", asserted at the seam.

        The window used to build the presenter with no arguments at all, so
        every one of these was stored, validated and ignored.
        """
        from companion.gtk_shell import _companion_settings_arguments

        update_settings(self.root, "character", {
            "render_mode": "2d", "scale": 1.4, "dock": "dock-left",
            "performance": "low", "idle_animation": False,
            "animation_intensity": 0.25, "contextual_reactions": False,
        })
        arguments = _companion_settings_arguments(self.root)
        self.assertIs(arguments["mode"], RenderMode.INTERACTIVE_2D)
        self.assertAlmostEqual(arguments["scale"], 1.4)
        self.assertIs(arguments["placement"], Placement.DOCK_LEFT)
        self.assertEqual(arguments["performance"], "low")
        self.assertFalse(arguments["idle_animation"])
        self.assertAlmostEqual(arguments["animation_intensity"], 0.25)
        self.assertFalse(arguments["contextual_reactions"])

    def test_damaged_settings_cost_preferences_and_not_the_companion(self) -> None:
        """A damaged file yields usable defaults, not an exception and not nothing.

        ``load_settings`` already degrades to defaults rather than raising, so
        the presenter still receives a complete, valid argument set — which is
        the property that matters. Asserting an empty dict here would have been
        asserting that the degradation happened at *this* layer, which is a
        detail of where the recovery lives rather than of what the user gets.
        """
        from companion.gtk_shell import _companion_settings_arguments

        (self.root / "settings.json").write_text("{ not json", encoding="utf-8")
        arguments = _companion_settings_arguments(self.root)
        self.assertIs(arguments["mode"], RenderMode.PRERENDERED)
        self.assertIs(arguments["placement"], Placement.BOTTOM_RIGHT)
        self.assertAlmostEqual(arguments["scale"], 1.0)
        # And the presenter accepts them.
        self.presenter(**arguments)

    def test_the_accessibility_translator_was_not_shadowed(self) -> None:
        """Two functions in one module both named for character preferences.

        The settings reader was briefly called ``_character_preferences`` too,
        which shadowed the accessibility translator of the same name. Because
        the reader catches every exception, the accessibility preferences would
        have silently become ``{}`` and taken reduced motion and high contrast
        with them.
        """
        from companion.gtk_shell import _character_preferences
        from companion.presentation import AccessibilityPreferences

        translated = _character_preferences(
            AccessibilityPreferences(reduced_motion=True, high_contrast=True)
        )
        self.assertTrue(translated.reduced_motion)
        self.assertTrue(translated.high_contrast)


class HiddenCompanionTests(PresenterFixture):
    """§6's "Hidden", and the states in which hiding does not apply."""

    def test_hidden_is_a_preference_about_the_resting_companion(self) -> None:
        decision = attention_for(
            AttentionInput(state=CharacterState.IDLE, hidden_by_preference=True)
        )
        self.assertFalse(decision.visible)
        self.assertFalse(decision.animate)

    def test_hiding_is_never_a_way_to_dismiss_a_question(self) -> None:
        for state in (
            CharacterState.WAITING_FOR_APPROVAL,
            CharacterState.ERROR,
            CharacterState.LISTENING,
        ):
            decision = attention_for(
                AttentionInput(state=state, hidden_by_preference=True)
            )
            self.assertTrue(
                decision.visible,
                f"{state.value} was hidden by a preference",
            )
            self.assertIn("hide preference", decision.reason)

    def test_visibility_round_trips_through_settings(self) -> None:
        update_settings(self.root, "character", {"visible": False})
        self.assertFalse(load_settings(self.root).character.visible)


class FirstRunGreetingTests(PresenterFixture):
    """§5: once, short, and never in front of something that matters."""

    def state(self, phase: str, **kwargs):
        from companion.presentation import PresentationState

        return PresentationState(phase=phase, **kwargs)

    def greeter(self, **kwargs):
        return self.presenter(first_run_greeting=True, **kwargs)

    def test_the_greeting_is_off_unless_a_session_asks_for_it(self) -> None:
        """A slice or a diagnostic over a fresh directory is not a first boot.

        The presenter constructed one unconditionally at first, so every
        temporary root looked like a first login and the vertical slice
        opened on ``greeting`` instead of the static idle state its step 4
        asserts.
        """
        plain = self.presenter()
        self.assertIsNone(plain.greeting)
        update = plain.update(self.state('idle'), now=0.0)
        self.assertIs(
            update.snapshot.mapped_state.character_state, CharacterState.IDLE
        )

    def test_the_session_launcher_is_what_turns_it_on(self) -> None:
        from companion.gtk_shell import _companion_settings_arguments

        self.assertTrue(_companion_settings_arguments(self.root)['first_run_greeting'])

    def test_the_companion_greets_on_the_first_update_and_then_settles(self) -> None:
        presenter = self.greeter()
        self.assertTrue(presenter.greeting.should_greet())
        first = presenter.update(self.state("idle"), now=0.0)
        self.assertIs(
            first.snapshot.mapped_state.character_state, CharacterState.GREETING
        )
        later = presenter.update(self.state("idle"), now=99.0)
        self.assertIs(later.snapshot.mapped_state.character_state, CharacterState.IDLE)

    def test_it_greets_exactly_once_per_machine(self) -> None:
        first = self.greeter()
        first.update(self.state("idle"), now=0.0)
        second = self.greeter()
        update = second.update(self.state("idle"), now=0.0)
        self.assertIs(
            update.snapshot.mapped_state.character_state, CharacterState.IDLE,
            "the companion introduced itself again on the second login",
        )

    def test_the_marker_is_written_when_the_greeting_starts(self) -> None:
        """A crash mid-greeting must not produce a companion that greets forever."""
        presenter = self.greeter()
        presenter.update(self.state("idle"), now=0.0)
        self.assertTrue(presenter.greeting.already_greeted())

    def test_a_first_boot_that_opens_on_a_question_shows_the_question(self) -> None:
        presenter = self.greeter()
        update = presenter.update(
            self.state("waiting_for_approval", approval_state="pending"), now=0.0
        )
        self.assertIs(
            update.snapshot.mapped_state.character_state,
            CharacterState.WAITING_FOR_APPROVAL,
        )

    def test_an_unreadable_marker_counts_as_greeted(self) -> None:
        from companion.character.first_run import GREETING_FILE_NAME, FirstRunGreeting

        (self.root / GREETING_FILE_NAME).write_text("{ not json", encoding="utf-8")
        self.assertFalse(FirstRunGreeting(self.root).should_greet())

    def test_a_greeting_can_be_ended_early(self) -> None:
        from companion.character.first_run import FirstRunGreeting

        greeting = FirstRunGreeting(self.root)
        greeting.begin(now=0.0)
        self.assertTrue(greeting.active(now=1.0))
        greeting.finish()
        self.assertFalse(greeting.active(now=1.0))

    def test_the_greeting_is_short(self) -> None:
        from companion.character.first_run import GREETING_SECONDS

        self.assertLessEqual(
            GREETING_SECONDS, 10.0,
            "§5 asks for a short first run, not a tutorial maze",
        )


class AttentionModelTests(unittest.TestCase):
    """§2: one model, derived from the existing states."""

    def test_engagement_raises_available_to_attention(self) -> None:
        resting = attention_for(AttentionInput(state=CharacterState.IDLE))
        engaged = attention_for(AttentionInput(state=CharacterState.IDLE, engaged=True))
        self.assertIs(resting.level, AttentionLevel.AVAILABLE)
        self.assertIs(engaged.level, AttentionLevel.ATTENTION)

    def test_engagement_cannot_reach_listening(self) -> None:
        """§13: clicking the companion does not open a microphone."""
        for state in (CharacterState.IDLE, CharacterState.SLEEPING, CharacterState.PAUSED):
            decision = attention_for(AttentionInput(state=state, engaged=True))
            self.assertIsNot(decision.level, AttentionLevel.LISTENING)

    def test_an_unreachable_runtime_is_idle_rather_than_available(self) -> None:
        decision = attention_for(AttentionInput(state=CharacterState.IDLE, reachable=False))
        self.assertIs(decision.level, AttentionLevel.IDLE)

    def test_engagement_cannot_override_an_unreachable_runtime(self) -> None:
        decision = attention_for(
            AttentionInput(state=CharacterState.IDLE, reachable=False, engaged=True)
        )
        self.assertIs(decision.level, AttentionLevel.IDLE)

    def test_the_model_is_total_over_the_character_states(self) -> None:
        for state in CharacterState:
            decision = attention_for(AttentionInput(state=state))
            self.assertIsInstance(decision.level, AttentionLevel)

    def test_it_is_pure(self) -> None:
        value = AttentionInput(state=CharacterState.WORKING, engaged=True)
        self.assertEqual(attention_for(value), attention_for(value))


class RendererBoundaryTests(unittest.TestCase):
    """§8: the application layer never names a renderer.

    Asserted by reading the source rather than by convention. A rule about who
    may import what is only a rule if something checks it, and this is the
    check that stops the first ``if renderer_name == "full-3d"`` outside the
    character package.
    """

    #: The concrete renderers. Naming one outside the character package means
    #: the caller has stopped talking in semantic states.
    _RENDERER_NAMES = (
        "Animated2DRenderer", "Procedural2DRenderer", "ThreeDRenderer",
        "StaticImageRenderer",
    )

    def _companion_modules(self):
        root = Path(__file__).resolve().parents[2] / "companion"
        for path in sorted(root.rglob("*.py")):
            # The character package is where renderers live; it is allowed to
            # know their names. Everything else is the application layer.
            if "character" in path.relative_to(root).parts:
                continue
            yield path

    def test_no_application_module_imports_a_concrete_renderer(self) -> None:
        offenders = []
        for path in self._companion_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in self._RENDERER_NAMES:
                            offenders.append(f"{path.name} imports {alias.name}")
        self.assertEqual(offenders, [], "the application layer named a renderer")

    def test_no_application_module_branches_on_a_renderer_name(self) -> None:
        """Only names that identify a *renderer* count as a leak.

        Deliberately not ``full-3d``. That is a rung in the canonical capability
        vocabulary — :data:`companion.presentation.PRESENTATION_KINDS` — and the
        projection that owns that vocabulary is entitled to say it. The name
        that must never appear outside the character package is
        ``interactive-2d``, which is not a rung at all: it identifies one of the
        two renderers that serve the 2D rung, so anything naming it has stopped
        talking about capability and started talking about implementation.
        """
        from companion.character.modes import MODE_RENDERERS
        from companion.presentation import PRESENTATION_KINDS

        # Derived rather than listed. Written out by hand this test named
        # ``full-3d`` and then ``animated-2d``, and both are rungs — so it
        # failed on the projection that legitimately owns the rung vocabulary,
        # twice. The set that matters is exactly "renderer names that are not
        # also rung names", and computing it keeps the test honest if either
        # vocabulary gains a member.
        renderer_only = {
            name for name in MODE_RENDERERS.values() if name not in PRESENTATION_KINDS
        }
        self.assertIn("interactive-2d", renderer_only, "the test found nothing to check")

        offenders = []
        for path in self._companion_modules():
            source = path.read_text(encoding="utf-8")
            for name in renderer_only:
                if f'"{name}"' in source or f"'{name}'" in source:
                    offenders.append(f"{path.name} mentions {name}")
        self.assertEqual(
            offenders, [],
            "the application layer branched on which renderer is running",
        )

    def test_the_semantic_state_is_what_crosses_the_boundary(self) -> None:
        """What the app layer *does* hand over is a projection, not a command."""
        from companion.character.integration import mapper_input_for
        from companion.presentation import PresentationState

        value = mapper_input_for(PresentationState(phase="working"))
        self.assertEqual(value.presentation_phase, "working")
        self.assertFalse(hasattr(value, "renderer"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

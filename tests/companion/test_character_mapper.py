# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The state mapper: pure, canonical-phase-led, and unable to hide anything.

§6 and §19's state list. The mapper takes the canonical presentation phase —
already resolved by the projection's own §12 priority — and refines it into a
character state using the package's capabilities and a handful of facts the
projection does not hold. These tests are about the one property that makes
that safe: **refinement never produces a less urgent state than the canonical
phase implies**, so a decorative animation cannot hide an approval, a warning or
an error.

Everything here runs without a compositor, because the mapper is a pure function
over a manifest and a value.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from companion.character.defaults import default_character_path
from companion.character.integration import bubble_request_for, mapper_input_for
from companion.character.mapper import (
    CANONICAL_PHASE_STATES,
    FALLBACK_CHAINS,
    STATE_PRIORITY,
    AccessibilityPreferences,
    CharacterState,
    MappedCharacterState,
    StateMapperInput,
    map_character_state,
    priority_rank,
    resolve_state,
)
from companion.character.package import validate_package_directory
from companion.character.schema import (
    GENERIC_MOUTH_SHAPES,
    REQUIRED_CHARACTER_STATES,
    PackageTrustState,
)
from companion.presentation import (
    PRESENTATION_PHASES,
    PresentationRecommendation,
    PresentationState,
    ReviewerPresentation,
)

#: §6's order, verbatim, so reordering STATE_PRIORITY has to break this rather
#: than quietly agree with itself.
SPECIFIED_ORDER = (
    CharacterState.ERROR,
    CharacterState.BLOCKED,
    CharacterState.WAITING_FOR_APPROVAL,
    CharacterState.LISTENING,
    CharacterState.SPEAKING,
    CharacterState.WORKING,
    CharacterState.REVIEWING,
    CharacterState.PRESENTING_RESULT,
    CharacterState.SUCCESS,
    CharacterState.IDLE,
)


class MapperTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(
            default_character_path(), trust_state=PackageTrustState.BUILT_IN
        )
        cls.manifest = cls.package.manifest

    def mapped(self, **values) -> MappedCharacterState:
        values.setdefault("presentation_phase", "idle")
        return map_character_state(self.manifest, StateMapperInput(**values))


class VocabularyTests(MapperTestCase):
    def test_every_canonical_presentation_phase_is_mapped(self) -> None:
        self.assertEqual(set(PRESENTATION_PHASES), set(CANONICAL_PHASE_STATES))

    def test_every_character_state_is_ranked_exactly_once(self) -> None:
        self.assertEqual(sorted(STATE_PRIORITY), sorted(CharacterState))

    def test_the_specified_priority_order_survives(self) -> None:
        ranks = [priority_rank(state) for state in SPECIFIED_ORDER]
        self.assertEqual(ranks, sorted(ranks))

    def test_every_required_state_has_a_fallback_chain_ending_in_static(self) -> None:
        for state in REQUIRED_CHARACTER_STATES:
            with self.subTest(state=state):
                chain = FALLBACK_CHAINS[state]
                self.assertEqual(chain[0], state)
                self.assertEqual(chain[-1], "static_fallback")

    def test_every_canonical_phase_resolves_to_a_real_animation(self) -> None:
        """§5: deterministic fallbacks, and never a dead end."""
        for phase in PRESENTATION_PHASES:
            with self.subTest(phase=phase):
                mapped = self.mapped(presentation_phase=phase)
                self.assertIn(mapped.character_state, set(CharacterState))
                self.assertTrue(mapped.animation)
                self.assertTrue(mapped.fallback_chain)
                if mapped.animation != "__static_fallback__":
                    self.assertIn(mapped.animation, self.manifest.animations)
                self.assertTrue(mapped.accessibility_description)

    def test_the_default_package_declares_every_required_state(self) -> None:
        """§16: the built-in character covers the whole vocabulary."""
        self.assertEqual(
            sorted(set(REQUIRED_CHARACTER_STATES) - set(self.manifest.state_map)), []
        )

    def test_a_fallback_chain_walks_and_is_reported(self) -> None:
        """§5: deterministic fallbacks, with the path used exposed.

        Against a manifest with the state *removed*, because the shipped package
        declares every state and so never walks — testing the chain on it would
        assert that a one-element list has one element.
        """
        from dataclasses import replace as _replace

        reduced = _replace(
            self.manifest,
            state_map={
                key: value for key, value in self.manifest.state_map.items()
                if key not in {"researching", "working"}
            },
        )
        resolved, animation, chain = resolve_state(reduced, CharacterState.RESEARCHING)
        self.assertEqual(chain[0], "researching")
        self.assertGreater(len(chain), 1)
        self.assertEqual(chain[1], "working")
        self.assertIn(resolved, chain)
        self.assertTrue(animation)

    def test_a_chain_with_nothing_left_ends_at_the_static_fallback(self) -> None:
        from dataclasses import replace as _replace

        empty = _replace(self.manifest, state_map={})
        resolved, animation, chain = resolve_state(empty, CharacterState.RESEARCHING)
        self.assertEqual(resolved, "static_fallback")
        self.assertEqual(animation, "__static_fallback__")
        self.assertEqual(chain[-1], "static_fallback")

    def test_the_mouth_shape_map_uses_only_generic_shapes(self) -> None:
        self.assertTrue(set(self.manifest.mouth_shape_map).issubset(set(GENERIC_MOUTH_SHAPES)))


class PriorityTests(MapperTestCase):
    """§6: refinement may raise urgency and may never lower it."""

    def test_refinement_never_lowers_urgency_below_the_canonical_phase(self) -> None:
        combinations = (
            {}, {"listening": True}, {"speaking": True}, {"transcribing": True},
            {"repositioning": True}, {"approval_pending": True},
            {"reviewer_warning": True}, {"renderer_healthy": False},
            {"tool_activity": "typing"}, {"tool_activity": "research"},
            {"listening": True, "speaking": True, "repositioning": True},
        )
        from companion.character.mapper import _NARROWINGS

        for phase, canonical in CANONICAL_PHASE_STATES.items():
            for extra in combinations:
                with self.subTest(phase=phase, extra=tuple(sorted(extra))):
                    mapped = self.mapped(presentation_phase=phase, **extra)
                    # Either at least as urgent, or a declared narrowing — a
                    # more specific drawing of the same urgency class, which §6
                    # groups together as "active work".
                    narrowing = mapped.character_state in _NARROWINGS.get(canonical, ())
                    self.assertTrue(
                        narrowing
                        or priority_rank(mapped.character_state) <= priority_rank(canonical),
                        f"{extra} made {phase} less urgent than {canonical.value} "
                        f"(became {mapped.character_state.value})",
                    )

    def test_a_narrowing_is_only_ever_a_more_specific_kind_of_the_same_thing(self) -> None:
        """The exception to the rank rule, kept narrow enough to be safe."""
        from companion.character.mapper import _NARROWINGS

        self.assertEqual(set(_NARROWINGS), {CharacterState.WORKING})
        self.assertEqual(
            _NARROWINGS[CharacterState.WORKING],
            frozenset({CharacterState.RESEARCHING, CharacterState.TYPING}),
        )

    def test_a_decorative_flag_cannot_hide_an_error_block_or_approval(self) -> None:
        for phase, expected in (
            ("error", CharacterState.ERROR),
            ("blocked", CharacterState.BLOCKED),
            ("waiting_for_approval", CharacterState.WAITING_FOR_APPROVAL),
            ("cancelled", CharacterState.CANCELLED),
        ):
            with self.subTest(phase=phase):
                mapped = self.mapped(
                    presentation_phase=phase, listening=True, speaking=True,
                    transcribing=True, repositioning=True, tool_activity="typing",
                )
                self.assertEqual(mapped.character_state, expected)

    def test_an_outstanding_approval_outranks_ordinary_work(self) -> None:
        mapped = self.mapped(presentation_phase="working", approval_pending=True)
        self.assertEqual(mapped.character_state, CharacterState.WAITING_FOR_APPROVAL)

    def test_a_current_reviewer_disagreement_outranks_success(self) -> None:
        """§10: success must not override a later warning."""
        mapped = self.mapped(presentation_phase="success", reviewer_warning=True)
        self.assertEqual(mapped.character_state, CharacterState.WARNING)

    def test_listening_and_speaking_refine_only_where_permitted(self) -> None:
        self.assertEqual(
            self.mapped(presentation_phase="working", listening=True).character_state,
            CharacterState.LISTENING,
        )
        self.assertEqual(
            self.mapped(presentation_phase="working", speaking=True).character_state,
            CharacterState.SPEAKING,
        )
        # Not where a question is waiting.
        self.assertEqual(
            self.mapped(presentation_phase="waiting_for_approval", listening=True).character_state,
            CharacterState.WAITING_FOR_APPROVAL,
        )

    def test_work_narrows_to_a_kind_of_work_and_never_to_something_else(self) -> None:
        self.assertEqual(
            self.mapped(presentation_phase="working", tool_activity="typing").character_state,
            CharacterState.TYPING,
        )
        self.assertEqual(
            self.mapped(presentation_phase="working", tool_activity="research").character_state,
            CharacterState.RESEARCHING,
        )
        # An unknown activity stays plain working rather than being guessed at.
        self.assertEqual(
            self.mapped(presentation_phase="working", tool_activity="haruspicy").character_state,
            CharacterState.WORKING,
        )

    def test_an_unknown_phase_renders_as_idle_and_says_so(self) -> None:
        mapped = self.mapped(presentation_phase="interpretive-dance")
        self.assertEqual(mapped.character_state, CharacterState.IDLE)
        self.assertIn("unknown presentation phase", mapped.priority_reason)

    def test_a_degraded_renderer_never_outranks_the_task(self) -> None:
        mapped = self.mapped(presentation_phase="error", renderer_healthy=False)
        self.assertEqual(mapped.character_state, CharacterState.ERROR)
        mapped = self.mapped(presentation_phase="idle", renderer_healthy=False)
        self.assertEqual(mapped.character_state, CharacterState.DEGRADED)
        self.assertIn("task is unaffected", mapped.degradation_explanation)


class AccessibilityTests(MapperTestCase):
    """§17: no required information may exist only in animation."""

    def test_reduced_motion_holds_a_single_frame(self) -> None:
        mapped = self.mapped(accessibility=AccessibilityPreferences(reduced_motion=True))
        self.assertEqual(mapped.playback_policy, "static-first-frame")
        self.assertFalse(mapped.loop)
        self.assertEqual(mapped.transition_type, "immediate")

    def test_no_animation_and_disable_flashing_do_the_same(self) -> None:
        for preference in ("no_animation", "disable_flashing"):
            with self.subTest(preference=preference):
                mapped = self.mapped(
                    accessibility=AccessibilityPreferences(**{preference: True})
                )
                self.assertFalse(mapped.loop)

    def test_an_approval_or_error_never_loops(self) -> None:
        """A blinking approval is a flashing hazard and a distraction."""
        for phase in ("waiting_for_approval", "error", "blocked"):
            with self.subTest(phase=phase):
                mapped = self.mapped(presentation_phase=phase)
                self.assertFalse(mapped.loop)

    def test_every_state_carries_a_description_independent_of_colour(self) -> None:
        """§17: state meaning must not depend on colour.

        Matched on whole words, not substrings — "encountered" contains "red",
        and a check that flagged it would push the descriptions towards worse
        English rather than towards better accessibility.
        """
        import re

        pattern = re.compile(r"\b(red|green|amber|yellow|colour|color|flashing)\b")
        for phase in PRESENTATION_PHASES:
            with self.subTest(phase=phase):
                description = self.mapped(presentation_phase=phase).accessibility_description
                self.assertTrue(description.endswith("."))
                self.assertIsNone(pattern.search(description.casefold()), description)

    def test_the_frame_rate_cap_reaches_the_mapped_state(self) -> None:
        mapped = self.mapped(accessibility=AccessibilityPreferences(frame_rate_cap=12))
        self.assertEqual(mapped.frame_rate_cap, 12)

    def test_an_out_of_range_scale_is_refused(self) -> None:
        for values in ({"character_scale": 9.0}, {"bubble_scale": 0.1}, {"frame_rate_cap": 0}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    AccessibilityPreferences(**values)


class CanonicalInputTests(MapperTestCase):
    """§2 and §11: the mapper is fed the projection and nothing else."""

    def _state(self, **values) -> PresentationState:
        values.setdefault("phase", "idle")
        values.setdefault(
            "recommendation", PresentationRecommendation(implementation="animated-2d")
        )
        return PresentationState(**values)

    def test_the_input_is_built_only_from_the_projection(self) -> None:
        state = self._state(
            phase="working", current_tool="text.count_words", status_text="Working.",
        )
        value = mapper_input_for(state)
        self.assertEqual(value.presentation_phase, "working")
        self.assertEqual(value.current_tool, "text.count_words")
        self.assertEqual(value.tool_activity, "typing")
        self.assertEqual(value.status_text, "Working.")
        self.assertEqual(value.effective_presentation, "animated-2d")

    def test_an_unknown_tool_is_not_guessed_at(self) -> None:
        value = mapper_input_for(self._state(phase="working", current_tool="some.new.tool"))
        self.assertEqual(value.tool_activity, "")

    def test_only_the_latest_review_round_counts_as_a_current_warning(self) -> None:
        """A disagreement the executor already answered is history, not now."""
        historical = ReviewerPresentation(
            reviewer_id="r", severity="high", summary="missing validation",
            disagreement=True, round_number=1,
        )
        current = ReviewerPresentation(
            reviewer_id="r", severity="info", summary="the plan validates",
            disagreement=False, round_number=2,
        )
        answered = mapper_input_for(
            self._state(phase="success", observations=(historical, current))
        )
        self.assertFalse(answered.reviewer_warning)
        outstanding = mapper_input_for(self._state(phase="success", observations=(historical,)))
        self.assertTrue(outstanding.reviewer_warning)

    def test_the_projection_supplies_every_bubble_sentence(self) -> None:
        """§11: the renderer never composes task status itself."""
        result = bubble_request_for(self._state(phase="success", result_summary="words=6"))
        self.assertEqual(result.text, "words=6")
        self.assertFalse(result.persistent)

        error = bubble_request_for(self._state(phase="error", error_summary="it failed"))
        self.assertEqual(error.text, "it failed")
        self.assertTrue(error.persistent)

        approval = bubble_request_for(self._state(
            phase="waiting_for_approval", status_text="May I interrupt user work?"
        ))
        self.assertEqual(approval.kind.value, "approval")
        self.assertTrue(approval.persistent)

    def test_bubble_text_is_stripped_of_control_characters(self) -> None:
        request = bubble_request_for(self._state(
            phase="idle", status_text="hello\x00\x07 there\r\nagain"
        ))
        self.assertNotIn("\x00", request.text)
        self.assertNotIn("\x07", request.text)
        self.assertNotIn("\r", request.text)

    def test_the_integration_module_cannot_read_the_record(self) -> None:
        """The structural version of §11, checked from the import graph."""
        import ast

        source = (
            Path(__file__).resolve().parents[2] / "companion" / "character" / "integration.py"
        ).read_text(encoding="utf-8")
        reached = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                reached.add(node.module)
        for forbidden in (
            "companion.events", "companion.task", "companion.store",
            "companion.runtime", "companion.session",
        ):
            self.assertNotIn(forbidden, reached)
        self.assertIn("companion.presentation", reached)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

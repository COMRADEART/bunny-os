# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The interaction loop's invariants, asserted exhaustively rather than by example.

§4 lists six things a transition must never do. Five of them are properties of
the whole pipeline — task lifecycle, canonical projection, character mapper,
attention model — and the only honest way to assert a property of a pipeline is
to enumerate its inputs rather than to pick a few and hope. So these tests loop
over every state, every phase and every combination of the client flags, and
the assertion is inside the loop.

That matters because the failures §4 is describing are not ones anybody writes
deliberately. They are what happens when a flag added for one purpose turns out
to outrank something it should not, and the only way that is caught is by a
check that tried every flag against every phase.
"""

from __future__ import annotations

from itertools import product
import unittest

from companion.character.attention import (
    ATTENTION_LEVELS,
    AttentionInput,
    AttentionLevel,
    attention_for,
)
from companion.character.defaults import default_character_path
from companion.character.mapper import (
    CANONICAL_PHASE_STATES,
    FALLBACK_CHAINS,
    CharacterState,
    StateMapperInput,
    map_character_state,
    priority_rank,
)
from companion.character.package import PackageTrustState, validate_package_directory
from companion.character.quiescence import DEFAULT_POLICY, NEVER_QUIESCENT
from companion.presentation import PRESENTATION_PHASES
from companion.states import (
    STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    transition_allowed,
)

#: Every client-supplied flag the mapper will accept, and both of its values.
#: These are the inputs that could, in principle, overrule a phase — so these
#: are the inputs the masking tests enumerate.
_CLIENT_FLAGS = (
    "listening", "speaking", "transcribing", "repositioning",
    "dormant", "greeting", "approval_pending", "reviewer_warning",
)

#: Phases in which the user is either being asked something or being told
#: something went wrong. Nothing decorative may take the surface from these.
_SECURITY_CRITICAL = ("waiting_for_approval", "error", "blocked")


class InvariantFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = validate_package_directory(
            default_character_path(), trust_state=PackageTrustState.BUILT_IN
        )

    def mapped(self, phase: str, **flags):
        return map_character_state(
            self.package.manifest, StateMapperInput(presentation_phase=phase, **flags)
        )

    def flag_combinations(self, names=_CLIENT_FLAGS):
        """Every on/off combination of the named flags, as kwargs."""
        for values in product((False, True), repeat=len(names)):
            yield dict(zip(names, values))


class PermissionCannotBeSkipped(InvariantFixture):
    """§4: a transition must not skip permission."""

    def test_waiting_for_approval_never_leads_straight_to_a_result(self) -> None:
        for target in ("presenting", "completed", "reviewing"):
            self.assertFalse(
                transition_allowed("waiting_for_approval", target),
                f"a task awaiting permission could move straight to {target!r}",
            )

    def test_leaving_an_approval_means_planning_executing_or_stopping(self) -> None:
        reachable = {to for source, to in TRANSITIONS if source == "waiting_for_approval"}
        self.assertTrue(reachable)
        permitted = {"planning", "executing", "blocked", "failed", "cancelling", "paused", "recovering"}
        self.assertEqual(
            reachable - permitted, set(),
            f"an approval may end in an unexpected state: {sorted(reachable - permitted)}",
        )

    def test_a_pending_approval_is_never_masked_by_any_client_flag(self) -> None:
        """No combination of decorative flags may hide an outstanding approval."""
        for flags in self.flag_combinations():
            flags["approval_pending"] = True
            mapped = self.mapped("waiting_for_approval", **flags)
            self.assertLessEqual(
                priority_rank(mapped.character_state),
                priority_rank(CharacterState.WAITING_FOR_APPROVAL),
                f"{flags} reduced an approval to {mapped.character_state.value}",
            )

    def test_an_approval_never_loops_its_own_question_away(self) -> None:
        """A prompt animation plays once and settles; it must not repeat.

        The property is ``loop`` and not the playback policy. A one-shot is a
        perfectly good prompt animation — it plays and holds — so asserting the
        policy string was asserting the package's authoring choice rather than
        the invariant. What must never happen is a *loop*, because a question
        that re-animates every two seconds pulls the eye forever.
        """
        for phase in ("waiting_for_approval", "error", "blocked"):
            mapped = self.mapped(phase, approval_pending=(phase == "waiting_for_approval"))
            self.assertFalse(mapped.loop, f"{phase} loops its animation")
            self.assertNotEqual(mapped.playback_policy, "loop")


class SuccessCannotPrecedeCompletion(InvariantFixture):
    """§4: a transition must not report success before completion."""

    def test_completed_is_reachable_only_by_presenting_a_result(self) -> None:
        sources = {source for source, to in TRANSITIONS if to == "completed"}
        self.assertEqual(
            sources, {"presenting"},
            f"completed is reachable from {sorted(sources)}; a result must be presented first",
        )

    def test_only_the_success_phase_produces_the_success_character_state(self) -> None:
        for phase in PRESENTATION_PHASES:
            for flags in self.flag_combinations(("listening", "speaking", "greeting", "dormant")):
                mapped = self.mapped(phase, **flags)
                if mapped.character_state is CharacterState.SUCCESS:
                    self.assertEqual(
                        phase, "success",
                        f"phase {phase!r} with {flags} rendered as success",
                    )

    def test_working_never_renders_as_completed_attention(self) -> None:
        for state in (CharacterState.WORKING, CharacterState.TYPING, CharacterState.PLANNING):
            decision = attention_for(AttentionInput(state=state))
            self.assertIsNot(
                decision.level, AttentionLevel.COMPLETED,
                f"{state.value} presented as completed",
            )


class MicrophoneCannotBeHidden(InvariantFixture):
    """§4 and §13: an active microphone must never be visually lost."""

    def test_a_live_microphone_always_outranks_a_decorative_flag(self) -> None:
        decorative = ("repositioning", "dormant", "greeting", "speaking")
        for phase in PRESENTATION_PHASES:
            for flags in self.flag_combinations(decorative):
                flags["listening"] = True
                mapped = self.mapped(phase, **flags)
                base = CANONICAL_PHASE_STATES.get(phase)
                if base is None or priority_rank(base) > priority_rank(CharacterState.LISTENING):
                    # The phase is less urgent than a live microphone, so the
                    # microphone must win.
                    self.assertLessEqual(
                        priority_rank(mapped.character_state),
                        priority_rank(CharacterState.LISTENING),
                        f"phase {phase!r} with {flags} hid a live microphone as "
                        f"{mapped.character_state.value}",
                    )

    def test_listening_is_never_shown_without_a_microphone(self) -> None:
        """§13: no fake states. Clicking the companion is not listening."""
        for phase in PRESENTATION_PHASES:
            for flags in self.flag_combinations(
                ("speaking", "repositioning", "dormant", "greeting")
            ):
                flags["listening"] = False
                flags["transcribing"] = False
                mapped = self.mapped(phase, **flags)
                if mapped.character_state is CharacterState.LISTENING:
                    self.assertEqual(
                        phase, "listening",
                        f"phase {phase!r} with {flags} claimed a microphone that was not open",
                    )

    def test_engagement_reaches_attention_and_never_listening(self) -> None:
        decision = attention_for(AttentionInput(state=CharacterState.IDLE, engaged=True))
        self.assertIs(decision.level, AttentionLevel.ATTENTION)
        self.assertIsNot(decision.level, AttentionLevel.LISTENING)

    def test_a_listening_companion_is_never_hidden_by_preference(self) -> None:
        decision = attention_for(
            AttentionInput(state=CharacterState.LISTENING, hidden_by_preference=True)
        )
        self.assertTrue(decision.visible, "a hidden companion with an open microphone")


class SecurityCriticalStatesAreNeverMasked(InvariantFixture):
    """§4: a transition must not mask a security-critical state."""

    def test_no_flag_combination_lowers_urgency_below_the_phase(self) -> None:
        for phase in _SECURITY_CRITICAL:
            base = CANONICAL_PHASE_STATES[phase]
            for flags in self.flag_combinations():
                mapped = self.mapped(phase, **flags)
                self.assertLessEqual(
                    priority_rank(mapped.character_state), priority_rank(base),
                    f"phase {phase!r} with {flags} became the less urgent "
                    f"{mapped.character_state.value}",
                )

    def test_a_critical_state_is_always_visible_and_never_quiesces(self) -> None:
        for phase in _SECURITY_CRITICAL:
            mapped = self.mapped(phase)
            decision = attention_for(
                AttentionInput(state=mapped.character_state, hidden_by_preference=True)
            )
            self.assertTrue(decision.visible, f"{phase} could be hidden")
            self.assertFalse(decision.may_quiesce, f"{phase} could freeze")
            quiescence = DEFAULT_POLICY.evaluate(
                mapped.character_state, seconds_in_state=3600.0, active_cap=30
            )
            self.assertTrue(quiescence.draws, f"{phase} stopped drawing after an hour")


class NothingBecomesStuck(InvariantFixture):
    """§4: a transition must not leave the companion stuck indefinitely."""

    def test_every_non_terminal_task_state_can_leave(self) -> None:
        for state in STATES:
            if state in TERMINAL_STATES:
                continue
            outgoing = {to for source, to in TRANSITIONS if source == state}
            self.assertTrue(outgoing, f"{state!r} has no outgoing transition")

    def test_every_non_terminal_task_state_can_reach_a_terminal_one(self) -> None:
        # Breadth-first over the transition table. A state from which no ending
        # is reachable is a task that can never finish, however many moves it
        # has available.
        for start in STATES:
            if start in TERMINAL_STATES:
                continue
            seen, frontier = {start}, [start]
            reached = False
            while frontier and not reached:
                current = frontier.pop()
                for source, to in TRANSITIONS:
                    if source != current or to in seen:
                        continue
                    if to in TERMINAL_STATES:
                        reached = True
                        break
                    seen.add(to)
                    frontier.append(to)
            self.assertTrue(reached, f"no terminal state is reachable from {start!r}")

    def test_every_character_state_resolves_to_something_drawable(self) -> None:
        for state in CharacterState:
            chain = FALLBACK_CHAINS[state.value]
            self.assertEqual(
                chain[-1], "static_fallback",
                f"{state.value}'s fallback chain does not end in the guaranteed frame",
            )
            resolved = self.mapped("idle")
            del resolved
            self.assertTrue(chain, f"{state.value} has an empty fallback chain")

    def test_every_attention_level_is_produced_by_some_character_state(self) -> None:
        produced = {
            attention_for(AttentionInput(state=state)).level for state in CharacterState
        }
        produced.add(attention_for(AttentionInput(state=CharacterState.IDLE, engaged=True)).level)
        produced.add(
            attention_for(AttentionInput(state=CharacterState.IDLE, reachable=False)).level
        )
        for level in ATTENTION_LEVELS:
            self.assertIn(level, produced, f"nothing can produce {level.value}")


class NoContradictoryVisualStates(InvariantFixture):
    """§4: a transition must not cause contradictory visual states."""

    def test_a_hidden_companion_is_never_told_to_animate(self) -> None:
        for state in CharacterState:
            for engaged, reachable, hidden in product((False, True), repeat=3):
                decision = attention_for(AttentionInput(
                    state=state, engaged=engaged, reachable=reachable,
                    hidden_by_preference=hidden,
                ))
                if not decision.visible:
                    self.assertFalse(
                        decision.animate,
                        f"{state.value} is invisible and animating",
                    )

    def test_nothing_may_quiesce_and_be_urgent_at_once(self) -> None:
        urgent = {
            AttentionLevel.WAITING_FOR_PERMISSION,
            AttentionLevel.LISTENING,
            AttentionLevel.ERROR,
            AttentionLevel.WORKING,
            AttentionLevel.THINKING,
        }
        for state in CharacterState:
            decision = attention_for(AttentionInput(state=state))
            if decision.level in urgent:
                self.assertFalse(
                    decision.may_quiesce,
                    f"{state.value} is {decision.level.value} and may freeze",
                )

    def test_the_two_freeze_lists_agree(self) -> None:
        """``NEVER_QUIESCENT`` and the attention model must not drift apart.

        Two independently maintained answers to "when may the companion stop
        drawing" is exactly how a companion comes to freeze while asking a
        question. Cross-checked here rather than kept in step by hand.
        """
        for state in NEVER_QUIESCENT:
            decision = attention_for(AttentionInput(state=state))
            self.assertFalse(
                decision.may_quiesce,
                f"{state.value} is never-quiescent for the idle policy but "
                f"quiescible for the attention model",
            )

    def test_voice_is_never_appropriate_while_listening(self) -> None:
        for state in (CharacterState.LISTENING, CharacterState.TRANSCRIBING):
            decision = attention_for(AttentionInput(state=state))
            self.assertFalse(
                decision.voice_appropriate,
                f"{state.value} would speak over the person talking",
            )

    def test_an_error_never_renders_with_a_success_animation(self) -> None:
        error = self.mapped("error", error_summary="it failed")
        success = self.mapped("success")
        self.assertNotEqual(
            error.animation, success.animation,
            "the error state draws the success animation",
        )


class PermissionUiAndCompanionAgree(InvariantFixture):
    """§12: the companion state and the permission surface are one decision."""

    def bubble_and_state(self, phase: str, **kwargs):
        from companion.character.integration import bubble_request_for, mapper_input_for
        from companion.presentation import PresentationState

        state = PresentationState(phase=phase, status_text="Allow Bunny to open a file?", **kwargs)
        request = bubble_request_for(state)
        mapped = map_character_state(self.package.manifest, mapper_input_for(state))
        return request, mapped

    def test_an_approval_bubble_implies_the_waiting_for_permission_state(self) -> None:
        from companion.character.bubble import BubbleKind

        request, mapped = self.bubble_and_state(
            "waiting_for_approval", approval_state="pending"
        )
        self.assertIs(request.kind, BubbleKind.APPROVAL)
        self.assertIs(mapped.character_state, CharacterState.WAITING_FOR_APPROVAL)

    def test_the_waiting_state_implies_an_approval_bubble(self) -> None:
        """Neither can appear without the other; both derive from one phase."""
        from companion.character.bubble import BubbleKind

        request, mapped = self.bubble_and_state(
            "waiting_for_approval", approval_state="pending"
        )
        self.assertIs(mapped.character_state, CharacterState.WAITING_FOR_APPROVAL)
        self.assertIs(request.kind, BubbleKind.APPROVAL)

    def test_an_approval_bubble_never_times_out(self) -> None:
        """A question that faded away would lapse into a denial nobody saw."""
        request, _ = self.bubble_and_state("waiting_for_approval", approval_state="pending")
        self.assertTrue(request.persistent)

    def test_the_permission_vocabulary_is_not_duplicated(self) -> None:
        """§12: do not introduce a second permission vocabulary."""
        from trust.explain import DENY_LABEL, SCOPE_LABELS

        self.assertEqual(set(SCOPE_LABELS), {"once", "session", "always"})
        self.assertEqual(SCOPE_LABELS["once"], "Allow once")
        self.assertEqual(SCOPE_LABELS["session"], "Allow while using")
        self.assertEqual(SCOPE_LABELS["always"], "Always allow")
        self.assertEqual(DENY_LABEL, "Don't allow")

    def test_the_attention_model_agrees_with_the_permission_phase(self) -> None:
        _, mapped = self.bubble_and_state("waiting_for_approval", approval_state="pending")
        decision = attention_for(AttentionInput(state=mapped.character_state))
        self.assertIs(decision.level, AttentionLevel.WAITING_FOR_PERMISSION)
        self.assertTrue(decision.visible)
        self.assertFalse(decision.may_quiesce)


class VoiceStateIsHonest(InvariantFixture):
    """§13: the visual state reflects the actual system state."""

    def test_speaking_is_shown_only_when_the_client_is_speaking(self) -> None:
        for phase in PRESENTATION_PHASES:
            mapped = self.mapped(phase, speaking=False, listening=False)
            if mapped.character_state is CharacterState.SPEAKING:
                self.assertEqual(
                    phase, "speaking",
                    f"phase {phase!r} claimed to be speaking with no audio",
                )

    def test_a_microphone_flag_produces_a_microphone_state(self) -> None:
        mapped = self.mapped("idle", listening=True)
        self.assertIs(mapped.character_state, CharacterState.LISTENING)

    def test_a_live_microphone_is_the_most_urgent_of_the_audio_states(self) -> None:
        """``listening`` outranks ``transcribing``, and both outrank idle.

        That ordering is the right way round and this test originally asserted
        the opposite. ``listening`` means the microphone is *open now*;
        ``transcribing`` means audio already captured is being processed. The
        live device is the privacy-critical fact, so it is the one that wins.
        """
        self.assertLess(
            priority_rank(CharacterState.LISTENING),
            priority_rank(CharacterState.TRANSCRIBING),
        )
        for state in (CharacterState.LISTENING, CharacterState.TRANSCRIBING):
            self.assertLess(priority_rank(state), priority_rank(CharacterState.IDLE))

    def test_the_companion_does_not_speak_over_the_user(self) -> None:
        for state in (CharacterState.LISTENING, CharacterState.TRANSCRIBING):
            self.assertFalse(attention_for(AttentionInput(state=state)).voice_appropriate)


class AccessibilityInvariants(InvariantFixture):
    """§15: reduced motion simplifies; it never removes meaning."""

    def test_reduced_motion_keeps_every_state_distinguishable(self) -> None:
        from companion.character.mapper import AccessibilityPreferences

        quiet = AccessibilityPreferences(reduced_motion=True)
        descriptions = set()
        for phase in PRESENTATION_PHASES:
            mapped = self.mapped(phase, accessibility=quiet)
            self.assertEqual(mapped.transition_type, "immediate")
            self.assertFalse(mapped.loop)
            descriptions.add(mapped.accessibility_description)
        self.assertGreater(
            len(descriptions), 5,
            "reduced motion collapsed the states into indistinguishable descriptions",
        )

    def test_every_state_has_a_non_visual_description(self) -> None:
        """§15: no critical information communicated exclusively through animation."""
        for phase in PRESENTATION_PHASES:
            mapped = self.mapped(phase)
            self.assertTrue(
                mapped.accessibility_description.strip(),
                f"phase {phase!r} has no spoken description",
            )

    def test_the_companion_never_takes_keyboard_focus(self) -> None:
        """A passive character that stole focus would trap a keyboard user."""
        from companion.character.positioning import (
            Display,
            PixelRect,
            Placement,
            place_character,
        )

        display = Display("one", PixelRect(0, 0, 1920, 1080), True)
        for placement in Placement:
            decision = place_character(
                [display], size=(288, 288), placement=placement
            )
            self.assertFalse(
                decision.accepts_keyboard_focus,
                f"{placement.value} took keyboard focus",
            )

    def test_animation_intensity_never_removes_expression(self) -> None:
        """Turning motion down must not make an error look like a success."""
        from companion.character.defaults import default_character_path
        from companion.character.procedural_renderer import Procedural2DRenderer

        renderer = Procedural2DRenderer(seed=3, intensity=0.0)
        renderer.load_package(self.package)
        poses = {}
        now = 0
        for phase in ("success", "error", "waiting_for_approval"):
            renderer.display_state(self.mapped(phase), now_ms=now)
            for _ in range(30):
                now += 33
                frame = renderer.tick(now_ms=now)
            poses[phase] = dict(frame.pose)["brow"]
        self.assertNotEqual(
            round(poses["success"], 3), round(poses["error"], 3),
            "at zero intensity a success and an error look identical",
        )


class LoopTransitionsAreLegal(InvariantFixture):
    """§1's loop, walked through the real lifecycle table."""

    def test_the_documented_interaction_loop_is_a_legal_path(self) -> None:
        path = [
            "created", "classifying", "waiting_for_capability", "waiting_for_executor",
            "planning", "waiting_for_approval", "executing", "reviewing",
            "presenting", "completed",
        ]
        for source, target in zip(path, path[1:]):
            self.assertTrue(
                transition_allowed(source, target),
                f"the interaction loop needs {source!r} -> {target!r} and the table refuses it",
            )

    def test_a_denied_approval_returns_to_a_resting_state(self) -> None:
        self.assertTrue(transition_allowed("waiting_for_approval", "blocked"))
        self.assertTrue(transition_allowed("blocked", "cancelling"))
        self.assertTrue(transition_allowed("cancelling", "cancelled"))

    def test_each_loop_step_maps_to_the_expected_attention_level(self) -> None:
        expected = {
            "listening": AttentionLevel.LISTENING,
            "planning": AttentionLevel.THINKING,
            "working": AttentionLevel.WORKING,
            "waiting_for_approval": AttentionLevel.WAITING_FOR_PERMISSION,
            "success": AttentionLevel.COMPLETED,
            "error": AttentionLevel.ERROR,
        }
        for phase, level in expected.items():
            mapped = self.mapped(phase)
            decision = attention_for(AttentionInput(state=mapped.character_state))
            self.assertIs(
                decision.level, level,
                f"phase {phase!r} presented as {decision.level.value}, expected {level.value}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

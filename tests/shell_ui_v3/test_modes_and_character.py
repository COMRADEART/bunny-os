"""Regular Mode, Character Mode and the guide character policy.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Covers rejections 4 (character surfaces receiving keyboard focus), 5 (two
character assets displayed simultaneously), 6 (a completed pose before backend
completion), 7 (approval accepted without explicit input) and 8 (a critical
approval with a default affirmative button).
"""

from __future__ import annotations

import json
import sys
import unittest

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "apps/common"))

from bunny_shell_v3.assistant import (
    ApprovalCard,
    ApprovalInput,
    ApprovalOutcome,
    Assistant,
    AssistantState,
    GUIDE_FOR_ASSISTANT,
    Privilege,
    Reversibility,
    Severity,
    resolve_approval,
)
from bunny_shell_v3.character import (
    APPROVED_CONTAINERS,
    CharacterLayer,
    CharacterRefusal,
    FORBIDDEN_CONTAINERS,
    GuideState,
    POSE_FOR_STATE,
    SUCCESS_STATES,
    scaled_size,
)
from bunny_shell_v3.model import ShellState, VisualMode
from bunny_shell_v3.modes import (
    CHARACTER_LAYOUT,
    ModeController,
    REGULAR_LAYOUT,
    character_fits,
    responsive_layout,
)


def layer(character_mode: bool = True) -> CharacterLayer:
    return CharacterLayer(ROOT, character_mode=character_mode)


class CharacterMappingTests(unittest.TestCase):
    def test_the_approved_mapping_is_complete_and_exact(self) -> None:
        expected = {
            "Ready": "idle-neutral",
            "Welcome": "welcome-wave",
            "Composing": "typing",
            "Planning": "thinking",
            "Teaching": "explaining",
            "Approval required": "requesting-approval",
            "Running": "task-running",
            "Completed": "task-completed",
            "Warning": "warning",
            "Failed": "error",
            "Offline": "offline",
            "Local Only": "privacy-mode",
            "Milestone": "celebrating",
        }
        actual = {state.value: pose for state, pose in POSE_FOR_STATE.items()}
        self.assertEqual(actual, expected)

    def test_every_mapped_pose_exists_in_the_canonical_family(self) -> None:
        available = layer().available_poses()
        for state, pose in POSE_FOR_STATE.items():
            self.assertIn(pose, available, f"{state.value} maps to a missing pose {pose}")

    def test_v3_creates_no_new_character_artwork(self) -> None:
        manifest = json.loads(
            (ROOT / "shell-ui/character-layer/component.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["newArtworkCreated"])
        self.assertEqual(manifest["assetFamily"], "visual-v2/assets/character/bunny-guide/v1")
        # And no V3 character directory was created alongside it.
        self.assertFalse((ROOT / "visual-v3/assets/character").exists())


class CharacterPlacementTests(unittest.TestCase):
    def test_regular_mode_shows_no_character_anywhere(self) -> None:
        component = layer(character_mode=False)
        for container in APPROVED_CONTAINERS:
            self.assertEqual(
                component.show(container, GuideState.READY),
                CharacterRefusal.NOT_CHARACTER_MODE,
            )
        self.assertEqual(component.displayed_count, 0)

    def test_the_character_is_refused_on_every_forbidden_surface(self) -> None:
        component = layer()
        for container in FORBIDDEN_CONTAINERS:
            self.assertEqual(
                component.show(container, GuideState.READY),
                CharacterRefusal.FORBIDDEN_CONTAINER,
                f"{container} must never host the character",
            )

    def test_an_unknown_container_is_refused_rather_than_permitted(self) -> None:
        self.assertEqual(
            layer().show("some-new-panel", GuideState.READY),
            CharacterRefusal.UNKNOWN_CONTAINER,
        )

    def test_only_one_character_can_be_displayed(self) -> None:
        """Rejection 5: two character assets displayed simultaneously."""
        component = layer()
        first = component.show("assistant", GuideState.READY)
        self.assertNotIsInstance(first, CharacterRefusal)
        second = component.show("welcome", GuideState.WELCOME)
        self.assertEqual(second, CharacterRefusal.ALREADY_DISPLAYED)
        self.assertEqual(component.displayed_count, 1)

    def test_a_success_pose_requires_an_observed_success(self) -> None:
        """Rejection 6: a completed pose shown before backend completion."""
        for state in SUCCESS_STATES:
            component = layer()
            self.assertEqual(
                component.show("task-summary", state),
                CharacterRefusal.SUCCESS_NOT_OBSERVED,
            )
            component = layer()
            placement = component.show("task-summary", state, success_observed=True)
            self.assertNotIsInstance(placement, CharacterRefusal)

    def test_focus_mode_refuses_a_continuous_character(self) -> None:
        component = layer()
        component.focus_mode = True
        self.assertEqual(
            component.show("assistant", GuideState.READY, continuous=True),
            CharacterRefusal.FOCUS_MODE_CONTINUOUS,
        )
        # A momentary appearance is still allowed.
        self.assertNotIsInstance(
            component.show("assistant", GuideState.READY, continuous=False), CharacterRefusal
        )

    def test_only_the_active_pose_is_held_in_memory(self) -> None:
        component = layer()
        component.show("assistant", GuideState.READY)
        self.assertEqual(component.loaded_poses(), {"idle-neutral"})
        component.hide()
        self.assertEqual(component.loaded_poses(), set())
        component.show("assistant", GuideState.PLANNING)
        self.assertEqual(component.loaded_poses(), {"thinking"})

    def test_the_character_is_never_focusable_and_never_blocks_input(self) -> None:
        """Rejection 4: character surfaces receiving keyboard focus."""
        self.assertFalse(CharacterLayer.focusable())
        self.assertFalse(CharacterLayer.accepts_input())

    def test_the_character_exposes_semantic_state_not_decoration(self) -> None:
        component = layer()
        component.show("assistant", GuideState.PLANNING)
        self.assertEqual(component.accessible_text(), "Bunny is planning the next step.")

    def test_aspect_ratio_is_preserved(self) -> None:
        # The canonical assets are 1024x1536.
        self.assertEqual(scaled_size((1024, 1536), (512, 768)), (512, 768))
        self.assertEqual(scaled_size((1024, 1536), (512, 2000)), (512, 768))
        self.assertEqual(scaled_size((1024, 1536), (2000, 768)), (512, 768))
        self.assertEqual(scaled_size((1024, 1536), (0, 0)), (0, 0))


class ModeControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ShellState()
        self.character = CharacterLayer(ROOT)
        self.controller = ModeController(self.state, self.character)

    def test_regular_mode_reserves_no_illustration_area(self) -> None:
        self.assertEqual(REGULAR_LAYOUT.illustration_fraction, 0.0)
        self.assertFalse(REGULAR_LAYOUT.reserved_empty_space)
        self.assertEqual(self.controller.illustration_box((460, 700)), (0, 700))
        self.assertEqual(self.controller.content_box((460, 700)), (460, 700))

    def test_character_mode_gives_the_illustration_a_bounded_share(self) -> None:
        self.controller.set_visual_mode(VisualMode.CHARACTER)
        width, _ = self.controller.illustration_box((1000, 700))
        self.assertEqual(width, 320)
        self.assertFalse(CHARACTER_LAYOUT.reserved_empty_space)

    def test_every_layout_accounts_for_all_available_space(self) -> None:
        for layout in (REGULAR_LAYOUT, CHARACTER_LAYOUT):
            layout.validate()

    def test_switching_mode_is_live_and_hides_the_character_immediately(self) -> None:
        self.controller.set_visual_mode(VisualMode.CHARACTER)
        self.character.show("assistant", GuideState.READY)
        self.assertEqual(self.character.displayed_count, 1)
        self.controller.set_visual_mode(VisualMode.REGULAR)
        self.assertEqual(self.character.displayed_count, 0)

    def test_toggling_returns_the_new_mode(self) -> None:
        self.assertIs(self.controller.toggle(), VisualMode.CHARACTER)
        self.assertIs(self.controller.toggle(), VisualMode.REGULAR)

    def test_focus_mode_removes_an_existing_character(self) -> None:
        self.controller.set_visual_mode(VisualMode.CHARACTER)
        self.character.show("assistant", GuideState.READY)
        self.controller.set_focus_mode(True)
        self.assertEqual(self.character.displayed_count, 0)

    def test_reduced_motion_means_no_animation(self) -> None:
        self.state.reduced_motion = True
        self.assertEqual(self.controller.animation_duration_ms(250), 0)

    def test_responsive_layout_has_one_stated_threshold(self) -> None:
        self.assertEqual(responsive_layout(1279).value, "compact")
        self.assertEqual(responsive_layout(1280).value, "comfortable")

    def test_a_narrow_panel_falls_back_rather_than_shrinking_the_character(self) -> None:
        self.assertFalse(character_fits(600))
        self.assertTrue(character_fits(720))


class AssistantAndApprovalTests(unittest.TestCase):
    def card(self, severity: Severity = Severity.ORDINARY) -> ApprovalCard:
        return ApprovalCard(
            requester="Bunny",
            operation="Install system updates",
            affected_resources=("/usr", "package database"),
            privilege=Privilege.ADMINISTRATOR,
            network_impact="downloads from the Bunny package mirror",
            data_impact="no user data is read or written",
            reversibility=Reversibility.REVERSIBLE_WITH_EFFORT,
            reason="14 security updates are available",
            expiration_seconds=120,
            severity=severity,
        )

    def test_every_assistant_state_maps_to_a_guide_state_or_to_none(self) -> None:
        self.assertEqual(set(GUIDE_FOR_ASSISTANT), set(AssistantState))
        self.assertIsNone(GUIDE_FOR_ASSISTANT[AssistantState.DISABLED])

    def test_a_disabled_assistant_shows_no_character(self) -> None:
        assistant = Assistant(bunny_enabled=False)
        self.assertIs(assistant.state, AssistantState.DISABLED)
        self.assertIsNone(assistant.guide_state())
        self.assertIsNone(assistant.character_container())

    def test_the_assistant_cannot_declare_completion_itself(self) -> None:
        assistant = Assistant()
        self.assertFalse(assistant.set_state(AssistantState.COMPLETED))
        self.assertIs(assistant.state, AssistantState.READY)
        self.assertTrue(assistant.set_state(AssistantState.COMPLETED, backend_confirmed=True))

    def test_a_disabled_assistant_does_not_come_back_on_its_own(self) -> None:
        assistant = Assistant(bunny_enabled=False)
        self.assertFalse(assistant.set_state(AssistantState.READY))

    def test_an_approval_card_states_its_whole_blast_radius(self) -> None:
        self.assertEqual(self.card().validate(), [])
        self.assertTrue(self.card().renderable)

    def test_an_incomplete_card_is_not_renderable(self) -> None:
        import dataclasses

        for field in ("requester", "operation", "network_impact", "data_impact", "reason"):
            broken = dataclasses.replace(self.card(), **{field: ""})
            self.assertFalse(broken.renderable, f"a card without {field} must not render")
        self.assertFalse(dataclasses.replace(self.card(), affected_resources=()).renderable)
        self.assertFalse(dataclasses.replace(self.card(), expiration_seconds=0).renderable)

    def test_approval_requires_explicit_input(self) -> None:
        """Rejection 7: approval accepted without explicit input."""
        card = self.card()
        for user_input in (
            ApprovalInput.DISMISSED,
            ApprovalInput.EXPIRED,
            ApprovalInput.NO_INPUT,
            ApprovalInput.EXPLICIT_DENY,
        ):
            self.assertIs(resolve_approval(card, user_input), ApprovalOutcome.DENIED)
        self.assertIs(
            resolve_approval(card, ApprovalInput.EXPLICIT_APPROVE), ApprovalOutcome.APPROVED
        )

    def test_an_unrenderable_card_cannot_be_approved(self) -> None:
        import dataclasses

        broken = dataclasses.replace(self.card(), reason="")
        self.assertIs(
            resolve_approval(broken, ApprovalInput.EXPLICIT_APPROVE), ApprovalOutcome.DENIED
        )

    def test_no_card_has_a_default_affirmative_action(self) -> None:
        """Rejection 8: a critical approval with a default affirmative button."""
        self.assertIsNone(self.card(Severity.CRITICAL).default_action())
        self.assertIsNone(self.card(Severity.ORDINARY).default_action())

    def test_every_card_offers_approve_deny_and_inspect(self) -> None:
        self.assertEqual(set(self.card().actions), {"approve", "deny", "inspect"})


if __name__ == "__main__":
    unittest.main()

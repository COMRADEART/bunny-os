# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python mirror of the Phase 1 companion vocabulary."""

from __future__ import annotations

import unittest

from companion.os_companion import (
    OS_STATES,
    PRESENTATION_MODES,
    RENDERING_TIERS,
    SCREEN_QUESTIONS,
    fidelity_for_tier,
    limit_bubble_text,
    os_state_from_phase,
    pose_for_os_state,
    screen_answers,
)
from companion.presentation import PRESENTATION_PHASES
from companion.user_copy import SCREEN_QUESTIONS as COPY_QUESTIONS


class OsCompanionTests(unittest.TestCase):
    def test_the_seventeen_states(self) -> None:
        self.assertEqual(len(OS_STATES), 17)
        self.assertEqual(OS_STATES[0], "idle")
        self.assertEqual(OS_STATES[-1], "offline")

    def test_every_runtime_phase_has_an_os_state(self) -> None:
        for phase in PRESENTATION_PHASES:
            with self.subTest(phase=phase):
                self.assertIn(os_state_from_phase(phase), OS_STATES)

    def test_activity_and_sleep_win_in_the_documented_order(self) -> None:
        self.assertEqual(os_state_from_phase("working", tool_activity="search files"), "searching")
        self.assertEqual(os_state_from_phase("idle", sleeping=True), "sleep")
        self.assertEqual(os_state_from_phase("success", celebrating=True), "celebrating")
        self.assertEqual(pose_for_os_state("asking"), "warning")

    def test_named_tiers_are_implemented_and_only_full_is_featured(self) -> None:
        from companion.os_companion import tier_is_fully_featured, tier_is_implemented

        self.assertEqual(RENDERING_TIERS, ("FULL", "BALANCED", "LIGHT", "MINIMAL"))
        self.assertEqual(fidelity_for_tier("LIGHT"), "static-image")
        self.assertEqual(fidelity_for_tier("MINIMAL"), "text-only")
        self.assertTrue(tier_is_implemented("FULL"))
        self.assertTrue(tier_is_implemented("BALANCED"))
        self.assertTrue(tier_is_implemented("LIGHT"))
        self.assertTrue(tier_is_implemented("MINIMAL"))
        self.assertTrue(tier_is_fully_featured("FULL"))
        self.assertFalse(tier_is_fully_featured("BALANCED"))
        self.assertFalse(tier_is_fully_featured("LIGHT"))
        self.assertFalse(tier_is_fully_featured("MINIMAL"))
        self.assertEqual(os_state_from_phase("waiting_for_approval"), "asking")
        self.assertEqual(os_state_from_phase("waiting_for_permission"), "asking")
        self.assertEqual(pose_for_os_state("asking"), "warning")

    def test_bubbles_are_short(self) -> None:
        self.assertEqual(
            limit_bubble_text("Hello. More. Again. Too much."),
            "Hello. More. Again.",
        )

    def test_the_three_screen_questions_are_the_brief(self) -> None:
        self.assertEqual(PRESENTATION_MODES, ("full", "compact", "ambient"))
        self.assertEqual(
            SCREEN_QUESTIONS,
            (
                "What am I doing?",
                "What is Bunny doing?",
                "What can I do next?",
            ),
        )
        self.assertEqual(COPY_QUESTIONS, SCREEN_QUESTIONS)
        answers = screen_answers(doing="Editing a photo", bunny="Working", nxt="Pause or cancel.")
        self.assertEqual(answers[SCREEN_QUESTIONS[1]], "Working")


if __name__ == "__main__":
    unittest.main()

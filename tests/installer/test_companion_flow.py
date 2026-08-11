# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup conversation, and the one thing the Companion may not decide.

§3's safety rule is short and absolute: the visual Companion must never become
the authority for destructive disk actions, and explicit confirmation is required
before destructive operations. These tests are what makes that a property of the
code rather than an intention in a document — a stage whose authority is ``user``
does not proceed without its own named confirmation, and no Companion state, no
preference and no Next button substitutes for it.
"""

from __future__ import annotations

import unittest

from installer.companion_flow import (
    AUTHORITIES,
    FIRST_RUN_STAGES,
    INSTALL_STAGES,
    PROGRESS_STAGES,
    Stage,
    may_proceed,
    stage,
    stages_for,
)
from companion.presentation import PRESENTATION_PHASES


class AuthorityTests(unittest.TestCase):
    def test_every_destructive_stage_requires_a_person(self) -> None:
        for key in ("confirm_erase", "encryption"):
            self.assertEqual(stage(key).authority, "user")

    def test_a_user_authority_stage_does_not_proceed_without_its_confirmation(self) -> None:
        erase = stage("confirm_erase")
        self.assertFalse(may_proceed(erase, confirmations=[]))
        self.assertFalse(may_proceed(erase, confirmations=["something-else"]))
        self.assertTrue(may_proceed(erase, confirmations=[erase.confirmation]))

    def test_one_confirmation_does_not_unlock_another_stage(self) -> None:
        erase = stage("confirm_erase")
        encryption = stage("encryption")
        self.assertFalse(may_proceed(encryption, confirmations=[erase.confirmation]))

    def test_a_companion_stage_needs_no_confirmation(self) -> None:
        self.assertTrue(may_proceed(stage("welcome"), confirmations=[]))

    def test_the_companion_never_has_authority_over_the_disk(self) -> None:
        for key in ("storage", "install"):
            self.assertEqual(stage(key).authority, "installer")

    def test_a_stage_that_needs_a_person_cannot_be_skipped(self) -> None:
        for entry in INSTALL_STAGES:
            if entry.authority == "user":
                self.assertFalse(entry.skippable, entry.key)

    def test_a_confirmation_always_says_what_it_authorises(self) -> None:
        for entry in INSTALL_STAGES:
            if entry.confirmation is not None:
                self.assertTrue(entry.confirmation_consequence.strip(), entry.key)

    def test_a_stage_cannot_half_require_a_confirmation(self) -> None:
        with self.assertRaises(ValueError):
            Stage(
                key="sneaky",
                says="...",
                heading="...",
                authority="companion",
                companion="idle",
                confirmation="type-the-disk-name",
                confirmation_consequence="erases things",
            )
        with self.assertRaises(ValueError):
            Stage(key="sneaky", says="...", heading="...", authority="user", companion="idle", skippable=False)


class ConversationTests(unittest.TestCase):
    def test_the_installer_opens_with_the_companion_and_not_a_partition_table(self) -> None:
        first = INSTALL_STAGES[0]
        self.assertEqual(first.key, "welcome")
        self.assertIn("I'm Bunny", first.says)
        self.assertEqual(first.authority, "companion")

    def test_every_stage_names_a_real_companion_phase(self) -> None:
        for entry in INSTALL_STAGES + FIRST_RUN_STAGES:
            self.assertIn(entry.companion, PRESENTATION_PHASES, entry.key)

    def test_every_stage_declares_one_of_the_three_authorities(self) -> None:
        for entry in INSTALL_STAGES + FIRST_RUN_STAGES:
            self.assertIn(entry.authority, AUTHORITIES, entry.key)

    def test_technical_detail_is_present_rather_than_removed(self) -> None:
        """§3 asks for plain language by default and the technical detail still
        available. A stage with neither would be an installer nobody can debug."""
        storage = stage("storage")
        self.assertTrue(storage.advanced)
        self.assertTrue(any("partition" in line.lower() for line in storage.advanced))

    def test_the_keyboard_stage_cannot_be_skipped_and_says_why(self) -> None:
        keyboard = stage("keyboard")
        self.assertFalse(keyboard.skippable)
        self.assertIn("password", keyboard.skip_note)

    def test_progress_rows_are_real_phases_not_decoration(self) -> None:
        keys = [key for key, _label in PROGRESS_STAGES]
        self.assertIn("capsules", keys)
        self.assertIn("security", keys)
        self.assertEqual(len(set(keys)), len(keys))

    def test_first_run_explains_capsules_and_permissions(self) -> None:
        keys = [entry.key for entry in FIRST_RUN_STAGES]
        self.assertIn("capsules_explained", keys)
        self.assertIn("trust_explained", keys)

    def test_first_run_is_never_destructive(self) -> None:
        for entry in FIRST_RUN_STAGES:
            self.assertEqual(entry.authority, "companion", entry.key)
            self.assertIsNone(entry.confirmation)

    def test_the_flows_are_addressable_by_name(self) -> None:
        self.assertEqual(stages_for("install"), INSTALL_STAGES)
        self.assertEqual(stages_for("first-run"), FIRST_RUN_STAGES)
        with self.assertRaises(KeyError):
            stages_for("nonsense")

    def test_the_companion_can_be_turned_off_entirely(self) -> None:
        """A person who does not want a character still gets a desktop."""
        behaviour = stage("companion_behaviour")
        self.assertIn("turn me off", behaviour.skip_note)


if __name__ == "__main__":
    unittest.main()

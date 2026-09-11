# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The host-visible Trust surface: same names, deny-by-default, no silent allow."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.support import ROOT
from companion.trust_surface import ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME
from companion.visible_trust import (
    FORBIDDEN_LABELS,
    JOURNEY_REQUEST,
    decide_journey,
    demo_prompt,
    drive_by_accessible_name,
    forbidden_labels_present,
    frames_for,
    render_html,
)


class AccessibleNameContractTests(unittest.TestCase):
    def test_the_names_match_the_guest_harness(self) -> None:
        self.assertEqual(ALLOW_ACCESSIBLE_NAME, "Allow this Bunny action")
        self.assertEqual(DENY_ACCESSIBLE_NAME, "Deny this Bunny action")

    def test_the_shell_trust_component_still_uses_those_names(self) -> None:
        source = (ROOT / "shell/components/gnome-shell-extension/lib/components/trust.js").read_text(
            encoding="utf-8",
        )
        self.assertIn(ALLOW_ACCESSIBLE_NAME, source)
        self.assertIn(DENY_ACCESSIBLE_NAME, source)

    def test_the_gtk_window_uses_the_same_names(self) -> None:
        source = (ROOT / "companion/gtk_shell.py").read_text(encoding="utf-8")
        self.assertIn("ALLOW_ACCESSIBLE_NAME", source)
        self.assertIn("DENY_ACCESSIBLE_NAME", source)

    def test_allow_and_deny_are_the_only_successful_presses(self) -> None:
        self.assertEqual(drive_by_accessible_name(ALLOW_ACCESSIBLE_NAME), "allow")
        self.assertEqual(drive_by_accessible_name(DENY_ACCESSIBLE_NAME), "deny")
        self.assertEqual(drive_by_accessible_name("Always allow everything"), "deny")
        self.assertEqual(drive_by_accessible_name(""), "deny")


class PromptHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = demo_prompt()
        self.html = render_html(self.prompt, state="waiting_for_approval")

    def test_the_production_explainer_wrote_the_headline(self) -> None:
        self.assertIn("Bunny Image Tool wants to open", self.prompt.headline)
        self.assertIn("holiday.png", self.prompt.headline)
        self.assertIn(JOURNEY_REQUEST, self.prompt.reason or "")

    def test_both_harness_names_are_present_once(self) -> None:
        self.assertEqual(self.html.count(f'aria-label="{ALLOW_ACCESSIBLE_NAME}"'), 1)
        self.assertEqual(self.html.count(f'aria-label="{DENY_ACCESSIBLE_NAME}"'), 1)

    def test_deny_is_focused(self) -> None:
        deny_at = self.html.index(DENY_ACCESSIBLE_NAME)
        allow_at = self.html.index(ALLOW_ACCESSIBLE_NAME)
        self.assertLess(deny_at, allow_at)
        self.assertIn("autofocus", self.html)
        self.assertIn('data-safe-default="denied"', self.html)

    def test_there_is_no_always_allow_everything(self) -> None:
        self.assertEqual(forbidden_labels_present(self.html), [])
        for label in FORBIDDEN_LABELS:
            self.assertNotIn(label, self.html)

    def test_every_photographed_state_is_bound(self) -> None:
        frames = frames_for(self.prompt)
        self.assertEqual(
            set(frames),
            {"idle", "thinking", "waiting_for_approval", "granted", "denied", "failed"},
        )
        self.assertTrue(frames["waiting_for_approval"].prompt_visible)
        self.assertFalse(frames["idle"].prompt_visible)
        self.assertEqual(frames["waiting_for_approval"].focused, DENY_ACCESSIBLE_NAME)
        self.assertIn("the request was declined", frames["denied"].status)
        self.assertIn("the task failed", frames["failed"].status)


class GateDriveTests(unittest.TestCase):
    def test_pressing_allow_once_grants_and_deny_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed, _ = decide_journey(ALLOW_ACCESSIBLE_NAME, root / "granted")
            denied, _ = decide_journey(DENY_ACCESSIBLE_NAME, root / "denied")
            leaked, _ = decide_journey("Always allow everything", root / "leaked")
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.reason_code, "user-allowed")
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason_code, "user-denied")
        self.assertFalse(leaked.allowed)


if __name__ == "__main__":
    unittest.main()

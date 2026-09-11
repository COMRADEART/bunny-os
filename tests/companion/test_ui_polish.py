# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""UI polish: tokens, copy, settings catalog, Trust labels, a11y names."""

from __future__ import annotations

import unittest

from tests.support import ROOT
from companion.design_tokens import (
    MOTION_COMPANION_MS,
    MOTION_UI_MS,
    bunny_silhouette_svg,
    css_custom_properties,
    visual_key_spec,
)
from companion.settings import settings_nav
from companion.trust_surface import ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME
from companion.user_copy import (
    disconnected_message,
    error_message,
    offline_message,
    voice_listening_message,
)
from companion.visual_keys import CORE_VISUAL_KEYS, VISUAL_KEYS


class TokenTests(unittest.TestCase):
    def test_motion_bands_are_the_product_budget(self) -> None:
        self.assertEqual(MOTION_UI_MS, (80, 420))
        self.assertEqual(MOTION_COMPANION_MS, (300, 420))

    def test_css_custom_properties_honour_reduced_motion(self) -> None:
        css = css_custom_properties()
        self.assertIn("--motion-fast:", css)
        self.assertIn("--motion-companion:", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("--motion-companion: 0ms", css)

    def test_listening_is_readable_without_the_caption(self) -> None:
        spec = visual_key_spec("listening")
        self.assertTrue(spec["mic"])
        self.assertEqual(spec["ears"], "up")
        permission = visual_key_spec("waiting_for_permission")
        self.assertEqual(permission["ears"], "up")
        offline = visual_key_spec("offline")
        self.assertTrue(offline["dim"])

    def test_the_silhouette_stays_bunny(self) -> None:
        mark = bunny_silhouette_svg(ears="up", mic=True)
        self.assertIn("bunny-face", mark)
        self.assertIn("mic-badge", mark)
        self.assertNotIn("🤔", mark)


class CopyTests(unittest.TestCase):
    def test_errors_answer_three_questions(self) -> None:
        message = error_message(kind="failed")
        self.assertTrue(message.happened)
        self.assertTrue(message.next_step)
        self.assertIn("changed", message.changed.casefold())
        self.assertIn("Nothing else", message.changed)

    def test_offline_is_intentional_not_an_outage_costume(self) -> None:
        copy = offline_message(intentional=True)
        self.assertIn("on purpose", copy.headline.casefold())
        self.assertIn("this computer", copy.happened.casefold())
        lost = offline_message(intentional=False)
        self.assertIn("network", lost.headline.casefold())

    def test_voice_listening_names_the_microphone(self) -> None:
        copy = voice_listening_message()
        self.assertIn("microphone", copy.happened.casefold())
        self.assertEqual(copy.headline, "Listening.")

    def test_disconnect_does_not_blame_the_task(self) -> None:
        copy = disconnected_message()
        self.assertIn("cannot reach the companion runtime", copy.sentence())
        self.assertIn("unaffected", copy.sentence())


class SettingsCatalogTests(unittest.TestCase):
    def test_nav_is_user_concepts_not_subsystems(self) -> None:
        titles = [item["title"] for item in settings_nav()]
        self.assertEqual(
            titles,
            [
                "Appearance", "Bunny", "Voice", "AI", "Privacy", "Memory",
                "Apps", "Permissions", "Accessibility", "System", "Updates",
            ],
        )


class AccessibleNameRegressionTests(unittest.TestCase):
    def test_the_harness_names_are_unchanged_in_production_surfaces(self) -> None:
        self.assertEqual(ALLOW_ACCESSIBLE_NAME, "Allow this Bunny action")
        self.assertEqual(DENY_ACCESSIBLE_NAME, "Deny this Bunny action")
        trust = (ROOT / "shell/components/gnome-shell-extension/lib/components/trust.js").read_text(
            encoding="utf-8",
        )
        self.assertIn(ALLOW_ACCESSIBLE_NAME, trust)
        self.assertIn(DENY_ACCESSIBLE_NAME, trust)
        self.assertIn("spec?.accessibleName ?? fallback", trust)
        gtk = (ROOT / "companion/gtk_shell.py").read_text(encoding="utf-8")
        self.assertIn("Allow once", gtk)
        self.assertIn("Don't allow", gtk)
        self.assertIn("ALLOW_ACCESSIBLE_NAME", gtk)

    def test_visual_keys_remain_a_projection(self) -> None:
        self.assertEqual(len(CORE_VISUAL_KEYS), 11)
        self.assertEqual(len(VISUAL_KEYS), 15)
        self.assertTrue(set(CORE_VISUAL_KEYS).issubset(VISUAL_KEYS))


if __name__ == "__main__":
    unittest.main()

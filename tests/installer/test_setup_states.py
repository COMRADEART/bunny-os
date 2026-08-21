# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup screens, the generated fixtures, and the invariants that hold them.

Three separate things are checked here and they fail for different reasons:

**Freshness.** ``qualification/installer/setup-states.json`` is what the story
harness draws. It is generated, so it can go stale, and a stale fixture is still
a *valid* fixture — the harness would render last week's installer and report no
findings. Regenerating and comparing is the only thing that catches that.

**Invariants.** Every screen carries an announcement, every destructive
consequence is inside it, no secret carries a value, every action has a name.
These are enforced in `Screen.__post_init__`, and they are checked again here
against every screen the generator actually produces — because a constructor
invariant only fires on the paths that construct.

**The negative control.** Each invariant is also asserted to *fail* when it
should. `qualification/design/story-manifest.json` records that the checks pass;
this records that they can fail, which is the part a green suite cannot show.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.setup_view import Action, Field, Screen, Warning  # noqa: E402
from installer.storage.models import DiskInfo                    # noqa: E402
from installer.storage.safety import confirmation_phrase, disk_identity  # noqa: E402

STATES = ROOT / "qualification" / "installer" / "setup-states.json"


def _document() -> dict:
    return json.loads(STATES.read_text(encoding="utf-8"))


class SetupStateFreshness(unittest.TestCase):
    def test_committed_states_match_the_generator(self) -> None:
        """Regenerate in memory and compare. A stale story is a failing test."""
        sys.path.insert(0, str(ROOT / "build" / "scripts"))
        try:
            import render_setup_states
        finally:
            sys.path.pop(0)
        rebuilt = render_setup_states.build()
        committed = _document()
        self.assertEqual(
            json.dumps(rebuilt, sort_keys=True, ensure_ascii=False),
            json.dumps(committed, sort_keys=True, ensure_ascii=False),
            "qualification/installer/setup-states.json is stale; "
            "run `python build/scripts/render_setup_states.py`",
        )

    def test_every_story_theme_has_a_stylesheet(self) -> None:
        document = _document()
        self.assertEqual(len(document["stylesheets"]), 7)
        for name, sheet in document["stylesheets"].items():
            self.assertTrue(sheet["css"].strip(), f"{name} rendered an empty stylesheet")
            self.assertIn(".bunny-setup", sheet["css"])

    def test_reduced_motion_zeroes_every_transition(self) -> None:
        """§41: no setup state may depend on animation.

        The reduced-motion sheet keeps its transitions and sets them to zero
        rather than dropping them, so this asserts the durations rather than
        their absence.
        """
        import re

        sheets = _document()["stylesheets"]
        moving = set(re.findall(r"transition:[^;]*?(\d+)ms", sheets["dark"]["css"]))
        still = set(re.findall(r"transition:[^;]*?(\d+)ms", sheets["dark, reduced motion"]["css"]))
        self.assertNotEqual(moving, {"0"}, "the ordinary sheet has no motion to reduce")
        self.assertEqual(still, {"0"}, f"reduced motion left durations behind: {sorted(still)}")


class SetupScreenInvariants(unittest.TestCase):
    def setUp(self) -> None:
        self.screens = _document()["screens"]

    def test_every_screen_is_announced(self) -> None:
        for screen in self.screens:
            with self.subTest(screen["title"]):
                self.assertTrue(screen["announcement"].strip())

    def test_every_destructive_consequence_is_announced(self) -> None:
        """§38: Orca must clearly announce destructive consequences."""
        seen = 0
        for screen in self.screens:
            for warning in screen["warnings"]:
                if warning["level"] != "danger":
                    continue
                seen += 1
                with self.subTest(screen["title"]):
                    self.assertIn(warning["text"], screen["announcement"])
        self.assertGreater(seen, 0, "no danger warning in any fixture; the check proves nothing")

    def test_no_secret_carries_a_value(self) -> None:
        seen = 0
        for screen in self.screens:
            for field in screen["fields"]:
                if field["kind"] == "secret":
                    seen += 1
                    with self.subTest(f"{screen['title']}:{field['key']}"):
                        self.assertIsNone(field["value"])
        self.assertGreater(seen, 0, "no secret field in any fixture; the check proves nothing")

    def test_every_action_has_an_accessible_name(self) -> None:
        for screen in self.screens:
            for action in screen["actions"]:
                with self.subTest(f"{screen['title']}:{action['id']}"):
                    self.assertTrue(action["accessibleName"].strip())

    def test_no_screen_invents_a_percentage(self) -> None:
        """§23: real installer states, never a made-up number."""
        for screen in self.screens:
            blob = json.dumps(screen["fields"]) + json.dumps(screen["progress"])
            with self.subTest(screen["title"]):
                self.assertNotIn('"percent"', blob)

    def test_the_confirmation_screen_names_the_disk_the_plan_targets(self) -> None:
        """§12: the confirmation surface shows the exact disk and action.

        Rebuilt from the same `DiskInfo` the generator used, so this compares the
        rendered sentence against `storage.safety`'s own derivation rather than
        against a copy of the string.
        """
        sys.path.insert(0, str(ROOT / "build" / "scripts"))
        try:
            import render_setup_states
        finally:
            sys.path.pop(0)

        for disk, title in ((render_setup_states.TARGET, "confirm_erase"),
                            (render_setup_states.LONG_TARGET, "confirm_erase — existing Windows")):
            screen = next(item for item in self.screens if item["title"] == title)
            identity = disk_identity(disk)
            phrase = confirmation_phrase(disk)
            with self.subTest(title):
                danger = [item["text"] for item in screen["warnings"] if item["level"] == "danger"]
                self.assertTrue(danger, "the confirmation screen has no danger warning")
                self.assertIn(identity, danger[0])
                self.assertIn(identity, screen["announcement"])
                # The phrase the backend will independently re-derive and compare.
                self.assertIn(phrase, screen["announcement"])
                self.assertEqual(screen["confirmation"], "type-the-disk-name")

    def test_installation_media_is_shown_and_refused(self) -> None:
        """§11: a disk that vanishes from the list is a consequence hidden."""
        screen = next(item for item in self.screens if item["key"] == "storage")
        field = next(item for item in screen["fields"] if item["key"] == "targetDisk")
        media = [item for item in field["options"] if "SanDisk" in item["label"]]
        self.assertTrue(media, "the installation media is missing from the disk list")
        self.assertFalse(media[0]["available"])
        self.assertIn("installation media", media[0]["note"].lower())

    def test_the_companion_can_be_turned_off(self) -> None:
        """§16: Off is one of the five modes, and says what still happens."""
        screen = next(item for item in self.screens if item["key"] == "companion_behaviour")
        field = next(item for item in screen["fields"] if item["key"] == "mode")
        values = [option["value"] for option in field["options"]]
        self.assertEqual(values, ["full", "compact", "minimal", "text-only", "off"])
        off = next(option for option in field["options"] if option["value"] == "off")
        self.assertIn("permission", off["note"].lower())

    def test_commercial_applications_are_labelled_honestly(self) -> None:
        """§19: no implied feature equivalence, and no pretending it runs here."""
        screen = next(item for item in self.screens if item["key"] == "applications")
        field = next(item for item in screen["fields"] if item["key"] == "applications")
        photoshop = next(
            (option for option in field["options"] if "Photoshop" in option["label"]), None)
        self.assertIsNotNone(photoshop, "the commercial option is absent from the fixture")
        self.assertFalse(photoshop["available"])
        self.assertIn("linux", photoshop["note"].lower())


class InvariantsCanFail(unittest.TestCase):
    """The negative control.

    Every assertion above passes today. These prove the assertions are capable of
    failing, which is the difference between a check and a decoration.
    """

    def test_a_danger_warning_outside_the_announcement_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            Screen(
                key="x", heading="h", says="s", companion="idle", authority="installer",
                warnings=(Warning("danger", "Everything on /dev/vda will be erased."),),
                actions=(Action("go", "Continue"),),
                announcement="Are you sure?",
            )
        self.assertIn("screen reader", str(caught.exception))

    def test_a_screen_without_an_announcement_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Screen(key="x", heading="h", says="s", companion="idle",
                   authority="installer", actions=(Action("go", "Continue"),))

    def test_a_screen_with_no_action_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Screen(key="x", heading="h", says="s", companion="idle",
                   authority="installer", announcement="something")

    def test_a_secret_field_may_not_carry_a_value(self) -> None:
        with self.assertRaises(ValueError):
            Field("passphrase", "secret", "Passphrase", value="hunter2")

    def test_an_action_without_a_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Action("go", "   ")

    def test_an_unknown_warning_level_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Warning("scary", "boo")


if __name__ == "__main__":
    unittest.main()

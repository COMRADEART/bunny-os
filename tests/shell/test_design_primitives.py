# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 1 primitives: models, not pixels.

The St actors cannot be constructed under node. The models they consume can,
and that is what this file measures: every named primitive exists, a bubble
is not a transcript, a timeline never types, and a companion is optional.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

DESIGN = ROOT / "shell/components/gnome-shell-extension/lib/design"


def run_node(script: str) -> object:
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, encoding="utf-8",
            check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def call(function: str, argument: object | None = None) -> object:
    arg = "undefined" if argument is None else json.dumps(argument)
    return run_node(
        f"import {{{function}, PRIMITIVE_KINDS}} from '{(DESIGN / 'primitives.js').as_uri()}';\n"
        f"console.log(JSON.stringify({function}({arg})));\n"
    )


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class PrimitiveCatalogueTests(NodeBackedTestCase):
    def test_every_phase_1_primitive_is_named(self) -> None:
        kinds = run_node(
            f"import {{PRIMITIVE_KINDS}} from '{(DESIGN / 'primitives.js').as_uri()}';\n"
            "console.log(JSON.stringify(PRIMITIVE_KINDS));\n"
        )
        self.assertEqual(
            set(kinds),
            {
                "Button", "IconButton", "Card", "Panel", "Sheet", "Dialog",
                "Popover", "Tooltip", "TextField", "SearchField", "Toggle",
                "Slider", "Menu", "List", "Sidebar", "TaskCard", "TaskTimeline",
                "PermissionCard", "Bubble", "CompanionAnchor", "Notification",
                "DockItem",
            },
        )

    def test_every_kind_has_a_builder(self) -> None:
        measured = run_node(
            f"import {{PRIMITIVE_KINDS, BUILDERS}} from '{(DESIGN / 'primitives.js').as_uri()}';\n"
            "console.log(JSON.stringify(PRIMITIVE_KINDS.filter(k => typeof BUILDERS[k] !== 'function')));\n"
        )
        self.assertEqual(measured, [])


class FocusAndNameTests(NodeBackedTestCase):
    def test_a_button_is_focusable_when_it_can_be_pressed(self) -> None:
        self.assertTrue(call("buildButton", {"label": "Open"})["canFocus"])
        self.assertFalse(call("buildButton", {"label": "Open", "disabled": True})["canFocus"])

    def test_an_icon_button_without_a_name_is_invalid(self) -> None:
        self.assertFalse(call("buildIconButton", {"icon": "search"})["valid"])
        self.assertTrue(call("buildIconButton", {"icon": "search", "accessibleName": "Search"})["valid"])

    def test_a_dock_item_carries_an_accessible_name(self) -> None:
        item = call("buildDockItem", {"id": "files", "label": "Files"})
        self.assertEqual(item["accessibleName"], "Files")
        self.assertTrue(item["canFocus"])


class BubbleTests(NodeBackedTestCase):
    def test_a_bubble_keeps_three_sentences_and_drops_the_fourth(self) -> None:
        copy = "One. Two. Three. Four is a panel."
        bubble = call("buildBubble", {"text": copy})
        self.assertEqual(bubble["text"], "One. Two. Three.")
        self.assertTrue(bubble["truncated"])
        self.assertFalse(bubble["transcript"])

    def test_actions_sit_on_the_model_not_inside_the_caption(self) -> None:
        bubble = call("buildBubble", {
            "text": "May I resize this photo?",
            "actions": [{"id": "allow", "label": "Allow once"}],
        })
        self.assertEqual(bubble["actions"][0]["label"], "Allow once")
        self.assertNotIn("Allow once", bubble["text"])


class TaskTimelineTests(NodeBackedTestCase):
    def test_stages_are_marks_not_a_percentage(self) -> None:
        model = call("buildTaskTimeline", {
            "stages": ["Plan", "Run", "Save"], "stageIndex": 1,
        })
        self.assertEqual(
            [s["glyph"] for s in model["stages"]],
            ["done", "current", "pending"],
        )
        self.assertFalse(model["typingIndicator"])
        self.assertIsNone(model.get("percent"))

    def test_pause_and_cancel_are_the_next_steps(self) -> None:
        model = call("buildTaskTimeline", {"stages": ["Run"], "stageIndex": 0})
        self.assertEqual([a["id"] for a in model["actions"]], ["pause", "cancel"])

    def test_details_expand_plan_tools_files_permissions(self) -> None:
        model = call("buildTaskTimeline", {
            "details": {
                "plan": "Resize holiday.png",
                "tools": ["image"],
                "files": ["holiday.png"],
                "permissions": ["read holiday.png"],
            },
            "expanded": True,
        })
        self.assertEqual(model["details"]["plan"], "Resize holiday.png")
        self.assertTrue(model["expanded"])


class CompanionAnchorTests(NodeBackedTestCase):
    def test_the_default_corner_is_bottom_right(self) -> None:
        anchor = call("buildCompanionAnchor", {})
        self.assertEqual(anchor["corner"], "bottom-right")
        self.assertTrue(anchor["draggable"])
        self.assertTrue(anchor["scalable"])
        self.assertTrue(anchor["hideable"])
        self.assertFalse(anchor["requiredToUseOs"])
        self.assertFalse(anchor["absolutePlacementAvailable"])

    def test_scale_is_clamped_to_the_accessibility_range(self) -> None:
        self.assertEqual(call("buildCompanionAnchor", {"scale": 9})["scale"], 2)
        self.assertEqual(call("buildCompanionAnchor", {"scale": 0.1})["scale"], 0.75)


class PermissionCardTests(NodeBackedTestCase):
    def test_unenforced_does_not_claim_a_kernel_boundary(self) -> None:
        card = call("buildPermissionCard", {
            "application": "GIMP",
            "action": "open holiday.png",
            "network": "Off",
            "enforced": False,
        })
        self.assertFalse(card["enforced"])
        self.assertEqual(card["standing"], "unenforced")
        self.assertEqual(card["enforcementNote"], "Declared, not enforced")
        blob = json.dumps(card).casefold()
        self.assertNotIn("allowlist", blob)
        self.assertNotIn("allow-listed", blob)
        self.assertNotIn("allow listed", blob)

    def test_enforced_is_honest_when_true(self) -> None:
        card = call("buildPermissionCard", {"enforced": True, "network": "Off"})
        self.assertTrue(card["enforced"])
        self.assertEqual(card["standing"], "granted")
        self.assertEqual(card["enforcementNote"], "Enforced")
        self.assertEqual(card["network"], "Off")


if __name__ == "__main__":
    unittest.main()

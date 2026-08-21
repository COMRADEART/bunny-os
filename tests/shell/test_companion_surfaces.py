# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three new shell modules, evaluated for real under node.

Same approach as ``test_desktop_shell.py``: the modules import nothing, so their
logic can be run outside GJS and the result is measured rather than asserted from
a reading of the source. What cannot be measured here is whether the result looks
right on a screen — that is VM and screenshot work, and neither this file nor the
reports claim otherwise.

Two of these cross the language boundary on purpose. The fidelity ladder and the
companion phases are each defined once in Python and consumed in JavaScript, and
there is no compiler that would notice the drift.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"


def run_node(script: str) -> dict:
    """Evaluate an ES module and return the JSON it prints on its last line."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "probe.mjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(ROOT),
        )
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class CompanionPresenceTests(NodeBackedTestCase):
    def resolve(self, **options) -> dict:  # type: ignore[no-untyped-def]
        script = (
            f"import {{resolve, FIDELITY, PRESENCE}} from '{(LIB / 'companionPresence.js').as_uri()}';\n"
            f"console.log(JSON.stringify(resolve({json.dumps(options)})));\n"
        )
        return run_node(script)

    def test_reduced_motion_stops_movement_without_lowering_the_picture(self) -> None:
        """A person who asked for less movement did not ask for a worse picture."""
        result = self.resolve(preference="full", selected="animated-2d", accessibility={"reducedMotion": True})
        self.assertEqual(result["motionMs"], 0)
        self.assertEqual(result["fidelity"], "animated-2d")

    def test_a_missed_frame_budget_lowers_the_tier_by_one(self) -> None:
        result = self.resolve(selected="full-3d", machine={"frameRate": 12})
        self.assertEqual(result["fidelity"], "lightweight-3d")

    def test_two_problems_lower_it_twice(self) -> None:
        result = self.resolve(selected="full-3d", machine={"frameRate": 12, "thermalThrottled": True})
        self.assertEqual(result["fidelity"], "animated-2d")

    def test_a_low_battery_drops_two_tiers(self) -> None:
        result = self.resolve(selected="full-3d", machine={"onBattery": True, "batteryPercent": 5})
        self.assertEqual(result["fidelity"], "animated-2d")

    def test_degradation_never_goes_past_text_only(self) -> None:
        result = self.resolve(
            selected="static-image",
            machine={"frameRate": 1, "thermalThrottled": True, "memoryPressure": True, "onBattery": True, "batteryPercent": 1},
        )
        self.assertEqual(result["fidelity"], "text-only")

    def test_text_only_is_honoured_over_everything(self) -> None:
        result = self.resolve(preference="full", selected="full-3d", accessibility={"textOnly": True})
        self.assertEqual(result["fidelity"], "text-only")

    def test_an_attention_phase_is_shown_even_at_the_indicator(self) -> None:
        result = self.resolve(preference="indicator", phase="waiting_for_approval")
        self.assertTrue(result["attention"])
        self.assertTrue(result["mustShowAttention"])

    def test_a_disabled_companion_routes_the_question_to_a_notification(self) -> None:
        """§5 says the Companion must never block ordinary desktop use, and §22
        says a question must still reach somebody. Both, at once."""
        result = self.resolve(preference="off", phase="waiting_for_approval")
        self.assertFalse(result["mustShowAttention"])
        self.assertTrue(result["routeToNotification"])

    def test_a_screen_reader_gets_every_state_announced(self) -> None:
        result = self.resolve(accessibility={"screenReader": True})
        self.assertTrue(result["announce"])

    def test_the_fidelity_ladder_matches_the_python_one(self) -> None:
        from companion.presentation import IMPLEMENTED_PRESENTATIONS

        script = (
            f"import {{FIDELITY}} from '{(LIB / 'companionPresence.js').as_uri()}';\n"
            "console.log(JSON.stringify({fidelity: FIDELITY}));\n"
        )
        js_ladder = set(run_node(script)["fidelity"])
        self.assertTrue(
            js_ladder <= set(IMPLEMENTED_PRESENTATIONS),
            f"the shell offers tiers the runtime does not implement: {js_ladder - set(IMPLEMENTED_PRESENTATIONS)}",
        )


class TrustPromptTests(NodeBackedTestCase):
    def build(self, record: dict, options: dict | None = None) -> dict:
        script = (
            f"import {{buildPrompt, focusOrder}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            f"const model = buildPrompt({json.dumps(record)}, {json.dumps(options or {})});\n"
            "console.log(JSON.stringify({model, focus: focusOrder(model)}));\n"
        )
        return run_node(script)

    def record(self, **overrides) -> dict:  # type: ignore[no-untyped-def]
        base = {
            "requestId": "r-1",
            "applicationId": "org.example.PhotoEditor",
            "applicationName": "Photo Editor",
            "category": "camera",
            "categoryTitle": "Camera",
            "risk": "high",
            "purpose": "use",
            "headline": "Photo Editor wants to use your camera.",
            "capabilityNote": "See whatever the camera sees, while it is running.",
            "resource": "",
            "reason": None,
            "reasonNote": "It didn't say why.",
            "enforcementNote": None,
            "revocation": "immediate",
            "options": [{"scope": "once", "label": "Allow once"}, {"scope": "session", "label": "Allow while using"}],
            "denyOption": {"verdict": "deny", "label": "Don't allow"},
            "spoken": "Photo Editor wants to use your camera. It didn't say why.",
        }
        base.update(overrides)
        return base

    def test_the_keyboard_starts_on_the_safe_option(self) -> None:
        result = self.build(self.record())
        self.assertEqual(result["model"]["initialFocus"], "deny")
        self.assertEqual(result["focus"][0], "deny")

    def test_return_and_escape_and_closing_all_deny(self) -> None:
        model = self.build(self.record())["model"]
        self.assertEqual(model["defaultAction"], "deny")
        self.assertEqual(model["escapeAction"], "deny")
        self.assertEqual(model["closeAction"], "deny")

    def test_deny_is_last_in_reading_order(self) -> None:
        buttons = self.build(self.record())["model"]["buttons"]
        self.assertEqual(buttons[-1]["verdict"], "deny")

    def test_a_high_risk_category_is_marked_by_shape_not_only_by_colour(self) -> None:
        model = self.build(self.record(risk="high"))["model"]
        self.assertTrue(model["marked"])
        self.assertEqual(model["riskToken"], "warning")
        low = self.build(self.record(risk="low"))["model"]
        self.assertFalse(low["marked"])

    def test_the_reason_never_leads(self) -> None:
        model = self.build(self.record(reason="The app says: \"for filters\""))["model"]
        keys = [entry["key"] for entry in model["body"]]
        self.assertLess(keys.index("capability"), keys.index("reason"))

    def test_an_absent_reason_still_says_something(self) -> None:
        model = self.build(self.record())["model"]
        texts = [entry["text"] for entry in model["body"]]
        self.assertIn("It didn't say why.", texts)

    def test_an_unenforced_permission_is_marked_in_the_dialog(self) -> None:
        model = self.build(self.record(enforcementNote="Bunny cannot yet stop it."))["model"]
        self.assertFalse(model["enforced"])
        self.assertTrue(any(entry["emphasis"] == "warning" for entry in model["body"]))

    def test_the_scrim_gets_heavier_at_high_contrast_not_lighter(self) -> None:
        model = self.build(self.record(), {"highContrast": True})["model"]
        self.assertEqual(model["style"]["scrim"], "solid")

    def test_the_announcement_is_the_layers_own_spoken_string(self) -> None:
        record = self.record()
        model = self.build(record)["model"]
        self.assertEqual(model["announcement"], record["spoken"])


class TaskWorkspaceTests(NodeBackedTestCase):
    def build(self, record: dict, options: dict | None = None) -> dict:
        script = (
            f"import {{buildWorkspace}} from '{(LIB / 'taskWorkspace.js').as_uri()}';\n"
            f"console.log(JSON.stringify(buildWorkspace({json.dumps(record)}, {json.dumps(options or {})})));\n"
        )
        return run_node(script)

    def record(self, **overrides) -> dict:  # type: ignore[no-untyped-def]
        base = {
            "taskId": "task-1",
            "title": "remove the background",
            "state": "working",
            "applicationName": "GIMP",
            "steps": [
                {"key": "choose", "label": "Finding an app that can do this", "state": "done", "detail": "GIMP"},
                {"key": "install", "label": "Setting up its protected space", "state": "done", "detail": ""},
                {"key": "permission", "label": "Asking you about the file", "state": "running", "detail": ""},
            ],
            "authorisedFiles": ["Pictures/cat.png"],
            "permissions": [{"category": "files", "resource": "Pictures/cat.png", "verdict": "allow", "scope": "once", "reasonCode": "user-allowed"}],
            "warnings": [],
            "outputs": [],
            "actions": ["watch", "minimise", "cancel", "inspect_permissions"],
            "summary": "",
            "startedAt": "2026-08-10T10:00:00Z",
            "finishedAt": None,
        }
        base.update(overrides)
        return base

    def test_all_seven_steps_are_present_including_the_future_ones(self) -> None:
        model = self.build(self.record())
        self.assertEqual(len(model["steps"]), 7)
        self.assertEqual(model["progress"]["total"], 7)
        self.assertEqual(model["progress"]["completed"], 2)

    def test_a_step_that_has_not_happened_is_drawn_dim(self) -> None:
        model = self.build(self.record())
        future = [step for step in model["steps"] if step["key"] == "export"][0]
        self.assertEqual(future["state"], "pending")
        self.assertEqual(future["token"], "muted")

    def test_a_waiting_task_leads_with_the_question(self) -> None:
        model = self.build(self.record(state="waiting_for_you"))
        self.assertTrue(model["leadWithQuestion"])
        self.assertTrue(model["sticky"])

    def test_warnings_are_a_region_of_their_own(self) -> None:
        model = self.build(self.record(warnings=["Some permissions are not enforced."]))
        self.assertEqual(model["warnings"], ["Some permissions are not enforced."])
        for step in model["steps"]:
            self.assertNotIn("not enforced", step["detail"])

    def test_the_output_note_is_read_from_the_export_result(self) -> None:
        model = self.build(
            self.record(
                state="completed",
                outputs=[{"display": "Pictures/cat-bunny.png", "renamed": False, "originalPreserved": True, "originalCopy": None}],
            )
        )
        self.assertEqual(model["outputs"][0]["originalNote"], "Your original was not changed.")

    def test_an_overwritten_original_is_not_described_as_preserved(self) -> None:
        model = self.build(
            self.record(
                state="completed",
                outputs=[{"display": "Pictures/cat.png", "renamed": False, "originalPreserved": False, "originalCopy": "/x"}],
            )
        )
        self.assertIn("replaced", model["outputs"][0]["originalNote"])

    def test_reduced_motion_removes_the_transition_and_not_the_rows(self) -> None:
        model = self.build(self.record(), {"reducedMotion": True})
        self.assertEqual(model["motionMs"], 0)
        self.assertEqual(len(model["steps"]), 7)

    def test_the_announcement_says_where_the_task_is_now(self) -> None:
        model = self.build(self.record())
        self.assertIn("Step 3 of 7", model["announcement"])

    def test_a_cancel_button_is_marked_destructive(self) -> None:
        model = self.build(self.record())
        cancel = [action for action in model["actions"] if action["id"] == "cancel"][0]
        self.assertTrue(cancel["destructive"])

    def test_the_step_keys_match_the_python_vocabulary(self) -> None:
        from companion.capsule_bridge import STEP_LABELS

        script = (
            f"import {{STEP_KEYS}} from '{(LIB / 'taskWorkspace.js').as_uri()}';\n"
            "console.log(JSON.stringify({keys: STEP_KEYS}));\n"
        )
        self.assertEqual(run_node(script)["keys"], list(STEP_LABELS))


class TokenTests(unittest.TestCase):
    """The design tokens, checked for the properties surfaces depend on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = json.loads((ROOT / "shell/themes/tokens.json").read_text(encoding="utf-8"))

    def test_every_companion_phase_has_something_to_draw(self) -> None:
        from companion.presentation import PRESENTATION_PHASES

        self.assertEqual(set(self.tokens["companion"]["phase"]), set(PRESENTATION_PHASES))

    def test_every_risk_level_has_a_token_and_the_dangerous_ones_have_a_marker(self) -> None:
        from trust.categories import RISK_LEVELS

        risk = self.tokens["risk"]
        for level in RISK_LEVELS:
            self.assertIn(level, risk)
        self.assertTrue(risk["high"]["marker"])
        self.assertTrue(risk["critical"]["marker"])
        self.assertFalse(risk["low"]["marker"])

    def test_reduced_transparency_is_fully_opaque(self) -> None:
        self.assertEqual(self.tokens["opacity"]["surfaceReducedTransparency"], 1.0)

    def test_reduced_motion_is_zero_and_not_merely_shorter(self) -> None:
        self.assertEqual(self.tokens["motion"]["reducedMs"], 0)

    def test_the_focus_ring_is_never_zero_width(self) -> None:
        self.assertGreaterEqual(self.tokens["focus"]["widthPx"], 2)

    def test_there_is_one_bunny_accent_and_both_stacks_use_it(self) -> None:
        """The property that replaced "version one is unchanged", and why.

        Schema version 2 promised the version-one values would not move, and
        they did not — but there were *two* sets of them. This file described an
        evergreen and mint palette (`light.accent` `#087F5B`, `dark.accent`
        `#88E7C4`) that no display server ever loaded, because nothing read this
        file at runtime; the desktop shell had its own violet palette in
        JavaScript, and that is the one in every screenshot the project has.
        docs/DESIGN_SYSTEM.md recorded the split and said resolving it "is worth
        doing and is not done yet".

        Version 3 resolves it in favour of the rendered palette. The check that
        matters now is not that a value has not changed but that there is only
        one of it, so the two stacks cannot drift apart again.
        """
        self.assertGreaterEqual(self.tokens["schemaVersion"], 3)
        self.assertEqual(
            self.tokens["generatedFrom"],
            "shell/components/gnome-shell-extension/lib/design/tokens.js")

        violet = {"#7C3AED", "#6D28D9", "#5B21B6", "#A78BFA", "#8B5CF6"}
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                self.assertIn(self.tokens[theme]["accent"], violet)

    def test_every_theme_defines_every_semantic_role(self) -> None:
        """A missing role is a surface that falls back to whatever St had."""
        roles = set(self.tokens["colourRoles"])
        self.assertIn("textOnSelection", roles)
        for name, theme in self.tokens["themes"].items():
            with self.subTest(theme=name):
                self.assertEqual(set(theme["colour"]), roles)

    def test_high_contrast_exists_as_a_theme_rather_than_a_wish(self) -> None:
        """The measured failure was that no second palette existed to switch to."""
        self.assertIn("highContrastDark", self.tokens["themes"])
        self.assertIn("highContrastLight", self.tokens["themes"])
        for name in ("highContrastDark", "highContrastLight"):
            with self.subTest(theme=name):
                theme = self.tokens["themes"][name]
                self.assertTrue(theme["highContrast"])
                # No shadows: a shadow is the separation cue a person using
                # high contrast cannot see. A visible border replaces it.
                self.assertEqual(set(theme["shadow"].values()), {"none"})


if __name__ == "__main__":
    unittest.main()

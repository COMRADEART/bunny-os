# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Task status, result, error and protected space: §20 to §23.

The phase vocabulary crosses the language boundary — defined once in
`companion.presentation`, consumed in JavaScript — and there is no compiler that
would notice drift. A phase the runtime can produce and the desktop cannot draw
is a task that appears to stop.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"


def run_node(script: str) -> object:
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def call(function: str, argument: object) -> object:
    return run_node(
        f"import {{{function}}} from '{(LIB / 'taskState.js').as_uri()}';\n"
        f"console.log(JSON.stringify({function}({json.dumps(argument)})));\n"
    )


def constant(name: str) -> object:
    return run_node(
        f"import {{{name}}} from '{(LIB / 'taskState.js').as_uri()}';\n"
        f"console.log(JSON.stringify({name}));\n"
    )


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class TaskStatusTests(NodeBackedTestCase):
    """§21."""

    def test_every_runtime_phase_maps_to_a_drawable_state(self) -> None:
        """The cross-language table, checked against the side that defines it."""
        from companion.presentation import PRESENTATION_PHASES

        mapping = constant("PHASE_TO_STATE")
        self.assertEqual(set(mapping), set(PRESENTATION_PHASES))

    def test_every_mapped_state_is_one_the_brief_names(self) -> None:
        states = set(constant("TASK_STATES"))
        self.assertEqual(
            states,
            {"waiting", "approval", "working", "completed", "blocked", "failed", "cancelled"})
        self.assertEqual(set(constant("PHASE_TO_STATE").values()) - states, set())

    def test_every_state_has_a_label_a_glyph_and_a_colour(self) -> None:
        """§19 again: three cues, so removing any one still leaves the state readable."""
        presentation = constant("STATE_PRESENTATION")
        for state in constant("TASK_STATES"):
            with self.subTest(state=state):
                entry = presentation[state]
                self.assertTrue(entry["label"])
                self.assertTrue(entry["glyph"])
                self.assertTrue(entry["token"])

    def test_no_percentage_is_invented(self) -> None:
        """§21: a percentage nobody measured is a claim about how long this will take."""
        self.assertIsNone(call("buildTaskStatus", {"phase": "working"})["percent"])
        self.assertIsNone(
            call("buildTaskStatus", {"phase": "working", "percent": "80%"})["percent"])
        self.assertEqual(
            call("buildTaskStatus", {"phase": "working", "percent": 40})["percent"], 40)

    def test_a_measured_percentage_is_bounded(self) -> None:
        for supplied, expected in ((-5, 0), (140, 100)):
            with self.subTest(supplied=supplied):
                self.assertEqual(
                    call("buildTaskStatus", {"phase": "working", "percent": supplied})["percent"],
                    expected)

    def test_stages_carry_position_rather_than_a_fraction(self) -> None:
        model = call("buildTaskStatus", {
            "phase": "working", "stages": ["Prepare", "Launch", "Export"], "stageIndex": 1})
        self.assertEqual(
            [(s["name"], s["done"], s["current"]) for s in model["stages"]],
            [("Prepare", True, False), ("Launch", False, True), ("Export", False, False)])

    def test_the_caption_is_the_runtimes_own_sentence(self) -> None:
        """The desktop must not describe a task differently from the runtime.

        `VISUAL_QA_REPORT.md` §3.5: the desktop showed "Assistant offline" and
        "Thinking…" at once, because availability and activity came from
        different state and nothing reconciled them.
        """
        model = call("buildTaskStatus", {"phase": "working", "caption": "Resizing the image"})
        self.assertEqual(model["detail"], "Resizing the image")
        self.assertIn("Resizing the image", model["announcement"])

    def test_an_unknown_phase_is_waiting_rather_than_a_crash(self) -> None:
        self.assertEqual(call("buildTaskStatus", {"phase": "invented"})["state"], "waiting")


class ErrorTaxonomyTests(NodeBackedTestCase):
    """§23. "Something went wrong" is the failure this component exists to prevent."""

    def test_the_six_kinds_the_brief_names_all_exist(self) -> None:
        kinds = constant("ERROR_KINDS")
        self.assertEqual(
            set(kinds),
            {"denied", "blocked", "application-failed", "internal", "missing", "offline"})

    def test_every_kind_says_what_to_do_next(self) -> None:
        for name, entry in constant("ERROR_KINDS").items():
            with self.subTest(kind=name):
                self.assertTrue(entry["next"], f"{name} has no next step")
                self.assertNotIn("went wrong", entry["headline"].lower().replace("something inside bunny went wrong", ""))

    def test_a_named_kind_wins_over_the_words_in_the_reason(self) -> None:
        model = call("buildError", {"kind": "blocked", "reason": "no such file"})
        self.assertEqual(model["kind"], "blocked")

    def test_reasons_are_classified_when_the_runtime_did_not(self) -> None:
        for reason, expected in [
            ("the request was declined", "denied"),
            ("network is unreachable", "offline"),
            ("no such file or directory", "missing"),
            ("the application exited with code 1", "application-failed"),
            ("blocked by policy", "blocked"),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(call("buildError", {"reason": reason})["kind"], expected)

    def test_an_unclassifiable_failure_is_bunnys_own(self) -> None:
        """Telling a person their application misbehaved when the truth is "we do not know"
        moves the blame to the wrong place."""
        self.assertEqual(call("buildError", {"reason": "qqq zzz"})["kind"], "internal")
        self.assertEqual(call("buildError", {})["kind"], "internal")

    def test_the_runtimes_reason_survives_beside_the_taxonomy(self) -> None:
        model = call("buildError", {"reason": "the request was declined"})
        self.assertEqual(model["explanation"], "the request was declined")
        self.assertTrue(model["headline"])
        self.assertNotEqual(model["headline"], model["explanation"])

    def test_a_denial_and_a_block_do_not_read_the_same(self) -> None:
        """One is reversible by asking again; the other is not."""
        denied = call("buildError", {"kind": "denied"})
        blocked = call("buildError", {"kind": "blocked"})
        self.assertNotEqual(denied["headline"], blocked["headline"])
        self.assertNotEqual(denied["next"], blocked["next"])
        self.assertNotEqual(denied["token"], blocked["token"])


class ResultTests(NodeBackedTestCase):
    """§22."""

    def test_the_result_offers_open_and_show_in_files(self) -> None:
        model = call("buildResult", {"files": ["holiday-resized.png"]})
        self.assertEqual([a["id"] for a in model["actions"]], ["open", "reveal"])

    def test_actions_name_the_file_they_act_on(self) -> None:
        """"Open" in a list of buttons is not a sentence a screen reader user can act on."""
        model = call("buildResult", {"files": ["holiday-resized.png"]})
        for action in model["actions"]:
            with self.subTest(action=action["id"]):
                self.assertIn("holiday-resized.png", action["accessibleName"])

    def test_a_result_with_no_file_offers_nothing_to_open(self) -> None:
        self.assertEqual(call("buildResult", {})["actions"], [])

    def test_provenance_is_a_sentence_and_not_an_audit_trail(self) -> None:
        """§22: do not overwhelm the normal result view with audit details."""
        model = call("buildResult", {
            "files": ["a.png"], "provenance": "Made in a protected space with no network."})
        self.assertLess(len(model["provenance"]), 120)


class ProtectedSpaceTests(NodeBackedTestCase):
    """§20."""

    PLAN = {"fileAccess": "holiday.png only", "network": "Off", "privateAppData": "Isolated"}

    def test_the_simple_view_is_the_brief_s_four_lines(self) -> None:
        model = call("buildProtectedSpace", self.PLAN)
        self.assertEqual(model["heading"], "Protected space: On")
        self.assertEqual(
            [(row["label"], row["value"]) for row in model["rows"]],
            [("Files", "holiday.png only"), ("Network", "Off"), ("App data", "Isolated")])

    def test_the_technical_view_comes_from_the_same_plan(self) -> None:
        """§20: the simple view must use the same underlying effective plan."""
        model = call("buildProtectedSpace", self.PLAN)
        details = {row["label"]: row["value"] for row in model["details"]}
        for row in model["rows"]:
            with self.subTest(row=row["label"]):
                self.assertIn(row["value"], details.values())

    def test_network_off_is_distinguishable_from_network_on(self) -> None:
        off = call("buildProtectedSpace", {**self.PLAN, "network": "Off"})
        on = call("buildProtectedSpace", {**self.PLAN, "network": "On"})
        standing = lambda m: next(r["standing"] for r in m["rows"] if r["label"] == "Network")
        self.assertEqual(standing(off), "blocked")
        self.assertEqual(standing(on), "granted")

    def test_an_unenforced_plan_says_so_in_words(self) -> None:
        """§19's central case: "off, enforced" versus "declared, not enforced"."""
        enforced = call("buildProtectedSpace", self.PLAN)
        declared = call("buildProtectedSpace", {**self.PLAN, "enforced": False})
        self.assertEqual(enforced["standing"], "granted")
        self.assertEqual(declared["standing"], "unenforced")
        self.assertIn("Enforced", enforced["announcement"])
        self.assertIn("not enforced", declared["announcement"])

    def test_a_task_with_no_protected_space_says_that_rather_than_showing_an_empty_card(self) -> None:
        model = call("buildProtectedSpace", {})
        self.assertFalse(model["on"])
        self.assertIn("not in use", model["heading"])


if __name__ == "__main__":
    unittest.main()

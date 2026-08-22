# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§16 and §17: four Companion modes that cannot disagree about the task.

The rule the tests exist for is the one sentence in §16 that is not about
layout: *no presentation mode may invent a different task truth.* Four surfaces
showing the same task is four times the opportunity for the defect
`VISUAL_QA_REPORT.md` §3.5 photographed — "Assistant offline" and "Thinking…" on
screen together, because availability and activity came from different state and
nothing reconciled them.
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
#: §16's four presentation modes, plus Off — a mode, not an absence
#: (28f62a24): a switched-off companion still may not invent a different task
#: truth, which is exactly why it belongs in the agreement tests below.
MODES = ("full", "compact", "minimal", "text-only", "off")

#: The ten states §16 names, in its own words.
REQUIRED_STATES = {
    "idle", "understanding", "waiting-for-approval", "launching", "working",
    "exporting", "completed", "blocked", "failed", "offline",
}


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


def call(function: str, argument: object) -> object:
    return run_node(
        f"import {{{function}}} from '{(LIB / 'companionModes.js').as_uri()}';\n"
        f"console.log(JSON.stringify({function}({json.dumps(argument)})));\n"
    )


def constant(name: str) -> object:
    return run_node(
        f"import {{{name}}} from '{(LIB / 'companionModes.js').as_uri()}';\n"
        f"console.log(JSON.stringify({name}));\n"
    )


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class ModeTests(NodeBackedTestCase):
    def test_every_mode_the_product_ships_is_named_off_included(self) -> None:
        self.assertEqual(constant("MODES"), list(MODES))

    def test_every_runtime_phase_maps_to_a_companion_state(self) -> None:
        """Superset for the same reason as taskState's: the bridge's voice-only
        `transcribing` phase must map instead of falling back to idle."""
        from companion.presentation import PRESENTATION_PHASES

        mapping = constant("PHASE_TO_COMPANION")
        unmapped = set(PRESENTATION_PHASES) - set(mapping)
        self.assertEqual(unmapped, set(), f"presentation phases with no companion state: {sorted(unmapped)}")
        self.assertIn("transcribing", mapping)

    def test_every_state_the_brief_requires_is_reachable_from_a_phase(self) -> None:
        reachable = set(constant("PHASE_TO_COMPANION").values())
        missing = REQUIRED_STATES - reachable
        self.assertEqual(missing, set(), f"no phase produces {sorted(missing)}")

    def test_every_reachable_state_has_something_to_draw(self) -> None:
        states = constant("COMPANION_STATES")
        for name in set(constant("PHASE_TO_COMPANION").values()):
            with self.subTest(state=name):
                entry = states[name]
                self.assertTrue(entry["label"])
                self.assertTrue(entry["behaviour"])
                self.assertTrue(entry["token"])

    def test_the_behaviours_seventeen_names_all_exist(self) -> None:
        """§17: resting, attention, working, success, blocked, error, offline."""
        behaviours = {entry["behaviour"] for entry in constant("COMPANION_STATES").values()}
        self.assertEqual(
            behaviours,
            {"resting", "attention", "working", "success", "blocked", "error", "offline"})


class OneTruthTests(NodeBackedTestCase):
    """The property §16 exists for."""

    PHASES = ("idle", "understanding", "waiting_for_approval", "starting", "working",
              "presenting_result", "success", "blocked", "error", "disconnected")

    def test_every_mode_agrees_about_every_phase(self) -> None:
        for phase in self.PHASES:
            with self.subTest(phase=phase):
                built = call("everyMode", {"phase": phase, "caption": "a sentence"})
                self.assertEqual(set(built), set(MODES))
                for field in ("state", "label", "announcement", "needsAnswer", "terminal"):
                    values = {json.dumps(built[mode][field]) for mode in MODES}
                    self.assertEqual(
                        len(values), 1,
                        f"{phase}: modes disagree about {field}: {sorted(values)}")

    def test_every_mode_shares_one_task_projection(self) -> None:
        """Not merely equal — built from one call, so they cannot drift."""
        built = call("everyMode", {"phase": "working", "caption": "Resizing the image"})
        tasks = {json.dumps(built[mode]["task"], sort_keys=True) for mode in MODES}
        self.assertEqual(len(tasks), 1)

    def test_what_differs_between_modes_is_only_which_parts_are_shown(self) -> None:
        built = call("everyMode", {"phase": "working", "caption": "x"})
        self.assertNotEqual(built["full"]["parts"], built["minimal"]["parts"])
        self.assertTrue(built["full"]["parts"]["transcript"])
        self.assertFalse(built["minimal"]["parts"]["transcript"])

    def test_a_mode_without_a_character_still_has_a_word_for_the_state(self) -> None:
        """§17: the OS must remain usable if character rendering fails."""
        for phase in self.PHASES:
            with self.subTest(phase=phase):
                built = call("buildCompanion", {"phase": phase, "mode": "text-only"})
                self.assertFalse(built["parts"]["character"])
                self.assertTrue(built["indicatorText"])


class FidelityTests(NodeBackedTestCase):
    """Mode and fidelity are different axes, and collapsing them makes one a lie."""

    def test_a_weak_machine_still_honours_a_request_for_the_full_companion(self) -> None:
        built = call("buildCompanion", {"mode": "full", "fidelity": "static-image"})
        self.assertEqual(built["mode"], "full")
        self.assertTrue(built["parts"]["character"])

    def test_a_text_only_fidelity_forces_the_text_only_mode(self) -> None:
        """There is no full size for a picture that is not drawn."""
        built = call("buildCompanion", {"mode": "full", "fidelity": "text-only"})
        self.assertEqual(built["mode"], "text-only")
        self.assertFalse(built["parts"]["character"])

    def test_the_accessibility_preference_wins_over_the_requested_mode(self) -> None:
        built = call("buildCompanion", {"mode": "full", "preferTextOnly": True})
        self.assertEqual(built["mode"], "text-only")

    def test_the_requested_mode_survives_being_overridden(self) -> None:
        """A setting that silently forgets what it was set to is not a setting."""
        built = call("buildCompanion", {"mode": "full", "preferTextOnly": True})
        self.assertEqual(built["requestedMode"], "full")

    def test_an_unknown_mode_falls_back_to_full_rather_than_to_nothing(self) -> None:
        built = call("buildCompanion", {"mode": "enormous"})
        self.assertEqual(built["mode"], "full")


class MotionTests(NodeBackedTestCase):
    """§15 and §17."""

    def test_only_the_state_waiting_for_a_person_may_ask_for_attention(self) -> None:
        """A character that pulsed while working would ask for attention every time."""
        states = constant("COMPANION_STATES")
        attention = {name for name, entry in states.items() if entry["motion"] == "attention"}
        self.assertEqual(attention, {"waiting-for-approval", "blocked", "failed"})

    def test_reduced_motion_stills_every_state(self) -> None:
        for phase in ("waiting_for_approval", "working", "success", "error"):
            with self.subTest(phase=phase):
                built = call("buildCompanion", {"phase": phase, "reducedMotion": True})
                self.assertEqual(built["motion"], "still")

    def test_reduced_motion_does_not_lower_the_fidelity(self) -> None:
        """A person who asked for less movement did not ask for a worse picture."""
        built = call("buildCompanion", {
            "phase": "working", "mode": "full", "fidelity": "full-3d", "reducedMotion": True})
        self.assertEqual(built["fidelity"], "full-3d")
        self.assertEqual(built["mode"], "full")
        self.assertTrue(built["parts"]["character"])

    def test_reduced_motion_keeps_the_behaviour_so_the_state_is_still_shown(self) -> None:
        """§15: no information disappears; motion is replaced, not removed."""
        moving = call("buildCompanion", {"phase": "waiting_for_approval"})
        still = call("buildCompanion", {"phase": "waiting_for_approval", "reducedMotion": True})
        self.assertEqual(moving["behaviour"], still["behaviour"])
        self.assertEqual(moving["label"], still["label"])


if __name__ == "__main__":
    unittest.main()

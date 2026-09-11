# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seventeen companion states, three modes, four rendering tiers."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"

OS_STATES = (
    "idle", "listening", "understanding", "thinking", "planning",
    "working", "coding", "reading", "searching", "waiting", "asking",
    "warning", "error", "success", "celebrating", "sleep", "offline",
)


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


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class VocabularyTests(NodeBackedTestCase):
    def test_the_seventeen_states_are_the_brief(self) -> None:
        states = run_node(
            f"import {{OS_STATES}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(OS_STATES));\n"
        )
        self.assertEqual(tuple(states), OS_STATES)

    def test_python_and_javascript_name_the_same_states(self) -> None:
        from companion.os_companion import OS_STATES as py_states
        self.assertEqual(tuple(py_states), OS_STATES)

    def test_every_presentation_phase_maps(self) -> None:
        from companion.presentation import PRESENTATION_PHASES

        mapping = run_node(
            f"import {{PHASE_TO_OS_STATE}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(PHASE_TO_OS_STATE));\n"
        )
        unmapped = set(PRESENTATION_PHASES) - set(mapping)
        self.assertEqual(unmapped, set(), f"unmapped phases: {sorted(unmapped)}")

    def test_tool_activity_narrows_working(self) -> None:
        built = run_node(
            f"import {{buildOsCompanion}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildOsCompanion("
            "{phase: 'working', toolActivity: 'coding holiday.png'})));\n"
        )
        self.assertEqual(built["state"], "coding")
        self.assertEqual(built["pose"], "working")

    def test_modes_share_one_task_truth(self) -> None:
        built = run_node(
            f"import {{buildOsCompanion, PRESENTATION_MODES}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "const caption = 'Resizing the image';\n"
            "const modes = {};\n"
            "for (const mode of PRESENTATION_MODES)\n"
            "  modes[mode] = buildOsCompanion({phase: 'working', caption, mode});\n"
            "console.log(JSON.stringify(modes));\n"
        )
        captions = {json.dumps(built[mode]["task"]) for mode in built}
        self.assertEqual(len(captions), 1)
        self.assertEqual(set(built), {"full", "compact", "ambient"})

    def test_the_companion_is_not_required_to_use_the_os(self) -> None:
        built = run_node(
            f"import {{buildOsCompanion}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildOsCompanion({hidden: true})));\n"
        )
        self.assertFalse(built["requiredToUseOs"])
        self.assertTrue(built["hidden"])

    def test_every_state_answers_the_three_questions(self) -> None:
        built = run_node(
            f"import {{buildOsCompanion}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildOsCompanion({phase: 'waiting_for_approval', caption: 'May I?'})));\n"
        )
        self.assertEqual(built["questions"]["bunny"], "Waiting for you")
        self.assertIn("Answer", built["questions"]["next"])

    def test_waiting_aliases_project_to_one_trust_wait(self) -> None:
        projected = run_node(
            f"import {{projectTrustWait}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "approval: projectTrustWait('waiting_for_approval'),"
            "permission: projectTrustWait('waiting_for_permission'),"
            "asking: projectTrustWait('asking')}));\n"
        )
        self.assertEqual(projected["approval"], projected["permission"])
        self.assertEqual(projected["approval"], projected["asking"])
        self.assertEqual(projected["approval"]["osState"], "asking")
        self.assertEqual(projected["approval"]["pose"], "warning")
        self.assertEqual(projected["approval"]["visualKey"], "waiting_for_permission")
        self.assertEqual(projected["approval"]["taskState"], "approval")
        self.assertEqual(projected["approval"]["label"], "Waiting for you")
        self.assertTrue(projected["approval"]["needsAnswer"])

    def test_os_companion_asking_matches_the_trust_wait_label(self) -> None:
        built = run_node(
            f"import {{buildOsCompanion, projectTrustWait}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "const wait = projectTrustWait('waiting_for_approval');\n"
            "const companion = buildOsCompanion({phase: 'waiting_for_approval'});\n"
            "console.log(JSON.stringify({wait, companion}));\n"
        )
        self.assertEqual(built["companion"]["state"], built["wait"]["osState"])
        self.assertEqual(built["companion"]["pose"], built["wait"]["pose"])
        self.assertEqual(built["companion"]["label"], built["wait"]["label"])


class RenderingTierTests(NodeBackedTestCase):
    def test_unimplemented_tiers_still_resolve_to_a_fidelity(self) -> None:
        mapping = run_node(
            f"import {{fidelityForTier}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "FULL: fidelityForTier('FULL'),"
            "BALANCED: fidelityForTier('BALANCED'),"
            "LIGHT: fidelityForTier('LIGHT'),"
            "MINIMAL: fidelityForTier('MINIMAL')}));\n"
        )
        self.assertEqual(mapping["FULL"], "full-3d")
        self.assertEqual(mapping["BALANCED"], "lightweight-3d")
        self.assertEqual(mapping["LIGHT"], "static-image")
        self.assertEqual(mapping["MINIMAL"], "text-only")

    def test_only_full_is_implemented(self) -> None:
        measured = run_node(
            f"import {{tierIsImplemented, RENDERING_TIER_NAMES}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "const out = {};\n"
            "for (const name of RENDERING_TIER_NAMES)\n"
            "  out[name] = tierIsImplemented(name);\n"
            "console.log(JSON.stringify(out));\n"
        )
        self.assertEqual(measured, {
            "FULL": True,
            "BALANCED": False,
            "LIGHT": False,
            "MINIMAL": False,
        })


class SkeletonLayoutTests(NodeBackedTestCase):
    def test_skeleton_is_bar_dock_and_companion(self) -> None:
        solution = run_node(
            f"import {{solve, overlappingPairs}} from '{(LIB / 'layout.js').as_uri()}';\n"
            "const s = solve({width: 1920, height: 1080}, {profile: 'skeleton'});\n"
            "console.log(JSON.stringify({profile: s.profile, keys: Object.keys(s.rects),"
            " overlaps: overlappingPairs(s), dropped: s.dropped, corner: s.companionCorner,"
            " character: s.rects.character, dock: s.rects.dock, topBar: s.rects.topBar}));\n"
        )
        self.assertEqual(solution["profile"], "skeleton")
        self.assertEqual(solution["corner"], "bottom-right")
        self.assertEqual(solution["overlaps"], [])
        self.assertIn("topBar", solution["keys"])
        self.assertIn("dock", solution["keys"])
        self.assertIn("character", solution["keys"])
        self.assertNotIn("sidebar", solution["keys"])
        self.assertNotIn("systemOverview", solution["keys"])
        self.assertGreater(solution["character"]["x"], 1920 / 2)
        self.assertGreater(solution["character"]["y"], 1080 / 2)
        self.assertLess(solution["topBar"]["height"], 44)

    def test_full_profile_still_places_cards(self) -> None:
        solution = run_node(
            f"import {{solve}} from '{(LIB / 'layout.js').as_uri()}';\n"
            "const s = solve({width: 1920, height: 1080});\n"
            "console.log(JSON.stringify({profile: s.profile || 'full', hasOverview: Boolean(s.rects.systemOverview)}));\n"
        )
        self.assertEqual(solution["profile"], "full")
        self.assertTrue(solution["hasOverview"])


class TrustConsentSurfaceTests(NodeBackedTestCase):
    def test_skeleton_routes_trust_to_a_focusable_dialog(self) -> None:
        measured = run_node(
            f"import {{solve}} from '{(LIB / 'layout.js').as_uri()}';\n"
            f"import {{consentSurfaceForLayout}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "const s = solve({width: 1920, height: 1080}, {profile: 'skeleton'});\n"
            "const surface = consentSurfaceForLayout({profile: s.profile, dropped: s.dropped});\n"
            "console.log(JSON.stringify({dropped: s.dropped, surface}));\n"
        )
        self.assertIn("assistant", measured["dropped"])
        self.assertFalse(measured["surface"]["card"])
        self.assertTrue(measured["surface"]["dialog"])
        self.assertTrue(measured["surface"]["bubble"])
        self.assertTrue(measured["surface"]["focusable"])
        self.assertEqual(measured["surface"]["kind"], "dialog")

    def test_full_profile_keeps_the_card_when_it_is_live(self) -> None:
        measured = run_node(
            f"import {{solve}} from '{(LIB / 'layout.js').as_uri()}';\n"
            f"import {{consentSurfaceForLayout}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "const s = solve({width: 1920, height: 1080});\n"
            "const surface = consentSurfaceForLayout("
            "{profile: s.profile, dropped: s.dropped, cardLive: true});\n"
            "console.log(JSON.stringify({dropped: s.dropped, surface}));\n"
        )
        self.assertNotIn("assistant", measured["dropped"])
        self.assertTrue(measured["surface"]["card"])
        self.assertFalse(measured["surface"]["dialog"])
        self.assertEqual(measured["surface"]["kind"], "card")

    def test_a_dropped_assistant_card_does_not_keep_trust(self) -> None:
        surface = run_node(
            f"import {{consentSurfaceForLayout}} from '{(LIB / 'companionVocabulary.js').as_uri()}';\n"
            "console.log(JSON.stringify(consentSurfaceForLayout("
            "{profile: 'full', dropped: ['assistant'], cardLive: false})));\n"
        )
        self.assertEqual(surface["kind"], "dialog")
        self.assertTrue(surface["focusable"])

    def test_the_live_shell_presents_approval_off_the_hidden_card(self) -> None:
        shell = (ROOT / "shell/components/gnome-shell-extension/lib/desktopShell.js").read_text(
            encoding="utf-8")
        overlay = (ROOT / "shell/components/gnome-shell-extension/lib/assistant/trustOverlay.js").read_text(
            encoding="utf-8")
        self.assertIn("_layoutProfile() {\n        return 'skeleton';", shell)
        self.assertIn("_presentApproval(", shell)
        self.assertIn("TrustOverlay", shell)
        self.assertIn("consentSurfaceForLayout", shell)
        self.assertIn("TrustComponent", overlay)
        self.assertIn("focusSafeAnswer", overlay)
        self.assertIn("bunny-trust-scrim", overlay)


if __name__ == "__main__":
    unittest.main()

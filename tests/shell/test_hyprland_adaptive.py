# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptive Hybrid layouts on the Hyprland Bunny session (M1)."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import ROOT


class AdaptiveLayoutGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        services = str(ROOT / "shell/services")
        if services not in sys.path:
            sys.path.insert(0, services)
        from bunny_shell.adaptive_layout import (  # noqa: WPS433
            LAYOUTS,
            hyprland_dispatch_plan,
            next_layout,
            normalise_layout,
            overlapping_pairs,
            retain_task_cursor,
            solve,
            AdaptiveLayoutState,
            ScreenRect,
        )

        self.LAYOUTS = LAYOUTS
        self.solve = solve
        self.ScreenRect = ScreenRect
        self.overlapping_pairs = overlapping_pairs
        self.normalise_layout = normalise_layout
        self.next_layout = next_layout
        self.retain_task_cursor = retain_task_cursor
        self.AdaptiveLayoutState = AdaptiveLayoutState
        self.hyprland_dispatch_plan = hyprland_dispatch_plan

    def test_layout_names_and_legacy_aliases(self) -> None:
        self.assertEqual(self.LAYOUTS, ("desktop", "focus", "studio"))
        self.assertEqual(self.normalise_layout("skeleton"), "desktop")
        self.assertEqual(self.normalise_layout("full"), "studio")
        self.assertEqual(self.next_layout("desktop"), "focus")
        self.assertEqual(self.next_layout("studio"), "desktop")

    def test_resolutions_and_scales_have_no_chrome_collisions(self) -> None:
        screens = ((1280, 800), (1366, 768), (1920, 1080))
        scales = (1.0, 1.5, 2.0)
        for width, height in screens:
            for scale in scales:
                for layout in self.LAYOUTS:
                    with self.subTest(width=width, height=height, scale=scale, layout=layout):
                        solution = self.solve(
                            self.ScreenRect(width, height),
                            layout=layout,
                            scale=scale,
                        )
                        self.assertEqual(solution.layout, layout)
                        self.assertFalse(
                            self.overlapping_pairs(solution),
                            msg=self.overlapping_pairs(solution),
                        )
                        self.assertFalse(solution.to_json()["absolutePlacementAvailable"])

    def test_narrow_focus_uses_drawer_rail(self) -> None:
        solution = self.solve(self.ScreenRect(1366, 768), layout="focus")
        self.assertEqual(solution.task_rail_mode, "drawer")
        self.assertIsNotNone(solution.task_rail)

    def test_wide_focus_uses_side_rail(self) -> None:
        solution = self.solve(self.ScreenRect(1920, 1080), layout="focus")
        self.assertEqual(solution.task_rail_mode, "side")

    def test_desktop_hides_rail(self) -> None:
        solution = self.solve(self.ScreenRect(1920, 1080), layout="desktop")
        self.assertEqual(solution.task_rail_mode, "hidden")
        self.assertIsNone(solution.task_rail)

    def test_layout_switch_retains_task_cursor(self) -> None:
        state = self.AdaptiveLayoutState(
            layout="desktop",
            task_id="task-1",
            event_sequence=7,
            approval_id="apr-9",
            artifact_refs=["file://a"],
        )
        moved = self.retain_task_cursor(state, layout="studio")
        self.assertEqual(moved.layout, "studio")
        self.assertEqual(moved.task_id, "task-1")
        self.assertEqual(moved.event_sequence, 7)
        self.assertEqual(moved.approval_id, "apr-9")
        self.assertEqual(moved.artifact_refs, ["file://a"])

    def test_dispatch_plan_does_not_claim_absolute_placement(self) -> None:
        plan = self.hyprland_dispatch_plan(
            self.solve(self.ScreenRect(1920, 1080), layout="focus")
        )
        self.assertEqual(plan["compositor"], "hyprland")
        self.assertFalse(plan["absolutePlacementAvailable"])
        self.assertTrue(any("absolute" in item for item in plan["unsupported"]))


class TaskRailProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        services = str(ROOT / "shell/services")
        if services not in sys.path:
            sys.path.insert(0, services)
        from bunny_shell.task_rail import build_task_rail, rail_outranks_work  # noqa: WPS433

        self.build_task_rail = build_task_rail
        self.rail_outranks_work = rail_outranks_work

    def test_no_invented_percent(self) -> None:
        rail = self.build_task_rail(
            {
                "phase": "working",
                "caption": "Generating files",
                "stages": ["plan", "build", "test"],
                "stageIndex": 1,
                "taskId": "t1",
            }
        )
        self.assertIsNone(rail["percent"])
        self.assertEqual(rail["stages"][1]["glyph"], "current")
        self.assertFalse(self.rail_outranks_work(rail))

    def test_approval_and_error_outrank_work(self) -> None:
        approval = self.build_task_rail({"phase": "waiting_for_approval", "caption": "Open file?"})
        self.assertTrue(approval["attention"])
        self.assertTrue(approval["approval"]["persistent"])
        self.assertTrue(self.rail_outranks_work(approval))

        failed = self.build_task_rail({"phase": "error", "caption": "Tool failed"})
        self.assertTrue(self.rail_outranks_work(failed))

    def test_disconnect_is_honest(self) -> None:
        rail = self.build_task_rail({"phase": "disconnected"})
        self.assertTrue(rail["disconnected"])
        self.assertIn("Disconnected", rail["announcement"])

    def test_measured_percent_is_kept(self) -> None:
        rail = self.build_task_rail({"phase": "working", "percent": 64})
        self.assertEqual(rail["percent"], 64.0)


class AdaptiveCliAndConfigTests(unittest.TestCase):
    def test_bin_and_hyprland_wiring_exist(self) -> None:
        self.assertTrue((ROOT / "shell/services/bin/bunny-adaptive-layout").is_file())
        keybinds = (ROOT / "shell/components/hyprland/keybinds.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("bunny-adaptive-layout set desktop", keybinds)
        self.assertIn("bunny-adaptive-layout set focus", keybinds)
        self.assertIn("bunny-adaptive-layout set studio", keybinds)
        waybar = (ROOT / "shell/components/hyprland/waybar/config.jsonc").read_text(
            encoding="utf-8"
        )
        self.assertIn("custom/bunny-layout", waybar)
        self.assertIn("bunny-adaptive-layout waybar", waybar)

    def test_cli_set_retains_cursor_without_hyprctl(self) -> None:
        import sys

        services = str(ROOT / "shell/services")
        if services not in sys.path:
            sys.path.insert(0, services)
        from bunny_shell import adaptive_cli

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "XDG_STATE_HOME": tmp,
                "HOME": tmp,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    code = adaptive_cli.run(
                        [
                            "set",
                            "focus",
                            "--task-id",
                            "task-42",
                            "--event-sequence",
                            "3",
                            "--dry-run",
                        ]
                    )
                self.assertEqual(code, 0)
                printed = stdout.getvalue()
                self.assertIn('"layout": "focus"', printed)
                state_file = Path(tmp) / "bunny-shell" / "adaptive-layout.json"
                self.assertTrue(state_file.is_file())
                payload = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(payload["layout"], "focus")
                self.assertEqual(payload["taskId"], "task-42")
                self.assertEqual(payload["eventSequence"], 3)

    def test_docs_name_hyprland_primary(self) -> None:
        contract = (ROOT / "docs/ADAPTIVE_HYBRID_INTERACTION_CONTRACT.md").read_text(
            encoding="utf-8"
        )
        plan = (ROOT / "docs/M1_ADAPTIVE_SHELL_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("Hyprland", contract)
        self.assertIn("Hyprland", plan)
        self.assertIn("NOT_RUN", plan)


if __name__ == "__main__":
    unittest.main()

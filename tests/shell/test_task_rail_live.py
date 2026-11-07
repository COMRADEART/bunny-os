# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""M1R: live task-rail runtime over Companion presentation (host-honest)."""

from __future__ import annotations

import unittest
from typing import Any

from tests.support import ROOT


class _FakeClient:
    def __init__(self, *, fail: bool = False, states: list[dict[str, Any]] | None = None) -> None:
        self.fail = fail
        self.states = list(states or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._index = 0

    def health(self) -> dict[str, Any]:
        self.calls.append(("health", {}))
        if self.fail:
            raise OSError("socket missing")
        return {"ok": True}

    def list_sessions(self) -> dict[str, Any]:
        self.calls.append(("list_sessions", {}))
        return {"sessions": [{"sessionId": "sess-1"}]}

    def list_tasks(self) -> dict[str, Any]:
        self.calls.append(("list_tasks", {}))
        return {
            "tasks": [
                {"taskId": "task-1", "sessionId": "sess-1", "state": "executing"},
            ]
        }

    def get_presentation_state(
        self,
        task_id: str | None = None,
        *,
        session_id: str | None = None,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_presentation_state",
                {
                    "taskId": task_id,
                    "sessionId": session_id,
                    "afterSequence": after_sequence,
                },
            )
        )
        if self.fail:
            raise OSError("disconnected")
        if self._index < len(self.states):
            state = self.states[self._index]
            self._index += 1
        else:
            state = self.states[-1] if self.states else {
                "taskId": "task-1",
                "sessionId": "sess-1",
                "phase": "working",
                "statusText": "Building",
                "revision": after_sequence + 1,
                "approvals": [],
                "progress": 0.0,
            }
        events = [
            {
                "eventType": "task_state_changed",
                "sequence": int(state.get("revision") or 1),
                "taskId": state.get("taskId"),
            }
        ]
        return {
            "state": state,
            "events": events if after_sequence < int(state.get("revision") or 0) else [],
            "revision": state.get("revision"),
        }


class TaskRailRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        import sys

        services = str(ROOT / "shell/services")
        if services not in sys.path:
            sys.path.insert(0, services)
        from bunny_shell.task_rail_runtime import (  # noqa: WPS433
            RAIL_ACCESSIBLE_NAME,
            RAIL_CANCEL_NAME,
            RAIL_OPEN_TRUST_NAME,
            TaskRailRuntime,
            presentation_to_rail_input,
        )
        from bunny_shell.task_rail_gtk import build_accessible_tree  # noqa: WPS433

        self.TaskRailRuntime = TaskRailRuntime
        self.presentation_to_rail_input = presentation_to_rail_input
        self.build_accessible_tree = build_accessible_tree
        self.RAIL_ACCESSIBLE_NAME = RAIL_ACCESSIBLE_NAME
        self.RAIL_OPEN_TRUST_NAME = RAIL_OPEN_TRUST_NAME
        self.RAIL_CANCEL_NAME = RAIL_CANCEL_NAME

    def test_desktop_hides_rail_focus_studio_show(self) -> None:
        runtime = self.TaskRailRuntime(client=_FakeClient())
        runtime.connect()
        runtime.set_layout("desktop")
        self.assertFalse(runtime.visible_for_layout())
        self.assertFalse(runtime.surface_model()["visible"])
        runtime.set_layout("focus")
        self.assertTrue(runtime.surface_model()["visible"])
        runtime.set_layout("studio")
        self.assertTrue(runtime.surface_model()["visible"])

    def test_connect_replays_events_and_retains_task_ids(self) -> None:
        client = _FakeClient(
            states=[
                {
                    "taskId": "task-9",
                    "sessionId": "sess-9",
                    "phase": "waiting_for_approval",
                    "statusText": "Open a file?",
                    "revision": 4,
                    "progress": 0.0,
                    "approvals": [
                        {"requestId": "apr-1", "reason": "Open Documents/a.txt", "action": "open"}
                    ],
                    "observations": [],
                }
            ]
        )
        runtime = self.TaskRailRuntime(client=client)
        self.assertTrue(runtime.connect())
        model = runtime.surface_model()
        self.assertEqual(model["taskId"], "task-9")
        self.assertEqual(model["revision"], 4)
        self.assertEqual(runtime.layout_state.task_id, "task-9")
        self.assertEqual(runtime.layout_state.event_sequence, 4)
        self.assertEqual(runtime.layout_state.approval_id, "apr-1")
        self.assertTrue(model["outranksWork"])
        self.assertTrue(model["acceptFocus"])
        # Replay path used afterSequence=0 on full refresh.
        presentation_calls = [c for c in client.calls if c[0] == "get_presentation_state"]
        self.assertTrue(presentation_calls)
        self.assertEqual(presentation_calls[0][1]["afterSequence"], 0)

    def test_disconnect_is_honest_and_does_not_invent_percent(self) -> None:
        runtime = self.TaskRailRuntime(client=_FakeClient(fail=True))
        self.assertFalse(runtime.connect())
        model = runtime.surface_model()
        self.assertTrue(model["disconnected"])
        self.assertEqual(model["rail"]["phase"], "disconnected")
        self.assertIsNone(model["rail"]["percent"])

    def test_no_invented_progress_from_zero_placeholder(self) -> None:
        mapped = self.presentation_to_rail_input(
            {"phase": "working", "statusText": "Working", "progress": 0.0, "revision": 1}
        )
        self.assertIsNone(mapped["percent"])

    def test_layout_switch_preserves_approval_state(self) -> None:
        runtime = self.TaskRailRuntime(
            client=_FakeClient(
                states=[
                    {
                        "taskId": "task-2",
                        "sessionId": "sess-2",
                        "phase": "working",
                        "statusText": "Coding",
                        "revision": 2,
                        "progress": 0.0,
                        "approvals": [{"requestId": "apr-keep", "reason": "still open"}],
                    }
                ]
            )
        )
        runtime.connect()
        runtime.set_layout("studio")
        self.assertEqual(runtime.layout_state.layout, "studio")
        self.assertEqual(runtime.layout_state.task_id, "task-2")
        self.assertEqual(runtime.layout_state.approval_id, "apr-keep")

    def test_accessible_names_and_keyboard_contract(self) -> None:
        runtime = self.TaskRailRuntime(client=_FakeClient())
        runtime.connect()
        runtime.set_layout("focus")
        model = runtime.surface_model()
        tree = self.build_accessible_tree(model)
        names = {node["name"] for node in tree}
        self.assertIn(self.RAIL_ACCESSIBLE_NAME, names)
        self.assertIn(self.RAIL_CANCEL_NAME, names)
        self.assertEqual(model["keyboard"]["escapeCollapses"], True)
        self.assertEqual(model["keyboard"]["hHidesToDesktop"], True)
        self.assertFalse(model["absolutePlacementAvailable"])

    def test_scaling_and_multimonitor_geometry(self) -> None:
        runtime = self.TaskRailRuntime(client=_FakeClient())
        runtime.set_layout("focus")
        for width, height, scale in (
            (1280, 800, 1.0),
            (1366, 768, 1.5),
            (1920, 1080, 2.0),
        ):
            geo = runtime.geometry(width=width, height=height, scale=scale, monitor_id="m1")
            self.assertEqual(geo["monitorId"], "m1")
            self.assertTrue(geo["visible"])
            self.assertFalse(geo["absolutePlacementAvailable"])
            self.assertIn(geo["solution"]["taskRailMode"], {"side", "drawer"})

    def test_focus_protection_only_for_approval(self) -> None:
        working = self.TaskRailRuntime(
            client=_FakeClient(
                states=[
                    {
                        "taskId": "t",
                        "sessionId": "s",
                        "phase": "working",
                        "statusText": "Working",
                        "revision": 1,
                        "progress": 0.0,
                        "approvals": [],
                    }
                ]
            )
        )
        working.connect()
        working.set_layout("focus")
        self.assertFalse(working.surface_model()["acceptFocus"])

        waiting = self.TaskRailRuntime(
            client=_FakeClient(
                states=[
                    {
                        "taskId": "t",
                        "sessionId": "s",
                        "phase": "waiting_for_approval",
                        "statusText": "Need permission",
                        "revision": 2,
                        "progress": 0.0,
                        "approvals": [{"requestId": "a1", "reason": "write"}],
                    }
                ]
            )
        )
        waiting.connect()
        waiting.set_layout("focus")
        model = waiting.surface_model()
        self.assertTrue(model["acceptFocus"])
        tree_names = {node["name"] for node in self.build_accessible_tree(model)}
        self.assertIn(self.RAIL_OPEN_TRUST_NAME, tree_names)

    def test_compositor_restart_preserves_cursor(self) -> None:
        client = _FakeClient(
            states=[
                {
                    "taskId": "task-r",
                    "sessionId": "sess-r",
                    "phase": "planning",
                    "statusText": "Planning",
                    "revision": 5,
                    "progress": 0.0,
                    "approvals": [],
                },
                {
                    "taskId": "task-r",
                    "sessionId": "sess-r",
                    "phase": "planning",
                    "statusText": "Planning",
                    "revision": 5,
                    "progress": 0.0,
                    "approvals": [],
                },
            ]
        )
        runtime = self.TaskRailRuntime(client=client)
        runtime.connect()
        runtime.set_layout("focus")
        result = runtime.simulate_compositor_restart()
        self.assertEqual(result["preservedLayout"], "focus")
        self.assertEqual(result["preservedTaskId"], "task-r")
        self.assertEqual(result["preservedEventSequence"], 5)
        self.assertTrue(result["reconnected"])
        self.assertFalse(result["absolutePlacementAvailable"])


class TaskRailPackagingTests(unittest.TestCase):
    def test_bin_and_reconciliation_docs_exist(self) -> None:
        self.assertTrue((ROOT / "shell/services/bin/bunny-task-rail").is_file())
        recon = (
            ROOT / "docs/ADAPTIVE_HYBRID_HYPRLAND_RECONCILIATION.md"
        ).read_text(encoding="utf-8")
        self.assertIn("ADR-031", recon)
        self.assertIn("Hyprland", recon)
        keybinds = (ROOT / "shell/components/hyprland/keybinds.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("bunny-task-rail", keybinds)


if __name__ == "__main__":
    unittest.main()

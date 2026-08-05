# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``bunny-os companion`` command group.

The UX shell will consume this output, so the tests assert on the *structure*.
A test that matched a sentence would pass while the shell broke.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest

from companion import cli as companion_cli
from companion.errors import CompanionError


def parse(*argv: str, root: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bunny-os")
    sub = parser.add_subparsers(dest="command", required=True)
    companion_cli.add_arguments(sub)
    return parser.parse_args(["companion", "--root", str(root), "--simulate", "laptop", *argv])


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def run_command(self, *argv: str) -> dict:
        return companion_cli.dispatch(parse(*argv, root=self.root))

    def test_every_command_returns_json_serialisable_structure(self) -> None:
        document = self.run_command("sessions")
        json.dumps(document)  # would raise if anything were not serialisable
        self.assertEqual(document["effect"], "read-only")
        self.assertEqual(document["sessions"], [])

    def test_a_simulated_run_is_labelled_as_simulated(self) -> None:
        document = self.run_command("sessions")
        self.assertIn("SIMULATED HARDWARE", document["simulationBanner"])
        self.assertIn("not a measurement of any physical machine", document["simulationBanner"])

    def test_mutating_commands_name_their_effect(self) -> None:
        created = self.run_command("session", "create", "--title", "CLI")
        self.assertTrue(created["effect"].startswith("CREATED session "))
        session_id = created["session"]["sessionId"]

        submitted = self.run_command(
            "task", "submit", "--session", session_id, "--request", "Count the words and validate.",
        )
        self.assertTrue(submitted["effect"].startswith("CREATED task "))
        task_id = submitted["task"]["taskId"]

        ran = self.run_command("task", "run", task_id)
        self.assertIn("RAN task", ran["effect"])
        self.assertEqual(ran["task"]["state"], "completed")

        paused = self.run_command("session", "pause", session_id)
        self.assertTrue(paused["effect"].startswith("PAUSED session "))
        closed = self.run_command("session", "close", session_id)
        self.assertTrue(closed["effect"].startswith("CLOSED session "))

    def test_read_only_commands_say_they_are_read_only(self) -> None:
        session_id = self.run_command("session", "create", "--title", "CLI")["session"]["sessionId"]
        task_id = self.run_command(
            "task", "submit", "--session", session_id, "--request", "Count the words.", "--run",
        )["task"]["taskId"]

        for argv in (
            ("sessions",),
            ("session", "inspect", session_id),
            ("task", "inspect", task_id),
            ("task", "events", task_id),
            ("recover", "--dry-run"),
            ("approvals",),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_command(*argv)["effect"], "read-only")

    def test_events_are_rendered_for_the_audience_asked_for(self) -> None:
        session_id = self.run_command("session", "create", "--title", "CLI")["session"]["sessionId"]
        task_id = self.run_command(
            "task", "submit", "--session", session_id, "--request", "Count the words and validate.", "--run",
        )["task"]["taskId"]

        reviewer = self.run_command("task", "events", task_id, "--audience", "reviewer")
        text = json.dumps(reviewer)
        self.assertIn("[withheld: personal]", text)
        self.assertNotIn("Count the words and validate.", text)

        ui = self.run_command("task", "events", task_id, "--audience", "ui")
        self.assertIn("Count the words and validate.", json.dumps(ui))

    def test_cancel_names_what_it_stopped(self) -> None:
        session_id = self.run_command("session", "create", "--title", "CLI")["session"]["sessionId"]
        task_id = self.run_command(
            "task", "submit", "--session", session_id,
            "--request", "Count the words, validate, and notify me.", "--run",
        )["task"]["taskId"]
        cancelled = self.run_command("task", "cancel", task_id, "--cause", "user")
        self.assertIn("CANCELLED task", cancelled["effect"])
        self.assertIn("approval(s) withdrawn", cancelled["effect"])
        self.assertEqual(cancelled["task"]["state"], "cancelled")

    def test_recover_reports_what_it_decided(self) -> None:
        session_id = self.run_command("session", "create", "--title", "CLI")["session"]["sessionId"]
        self.run_command(
            "task", "submit", "--session", session_id, "--request", "Count the words.", "--run",
        )
        document = self.run_command("recover")
        self.assertIn("RECOVERED", document["effect"])
        self.assertTrue(document["healthy"])
        self.assertEqual([item["decision"] for item in document["decisions"]], ["intact"])

    def test_approvals_lists_the_questions_and_records_an_answer(self) -> None:
        session_id = self.run_command("session", "create", "--title", "CLI")["session"]["sessionId"]
        self.run_command(
            "task", "submit", "--session", session_id,
            "--request", "Count the words and notify me.", "--run",
        )
        listing = self.run_command("approvals")
        self.assertTrue(listing["answered"], "the question should be on the record")
        request_id = listing["answered"][0]["request"]["requestId"]
        self.assertTrue(listing["answered"][0]["request"]["alternatives"])

        granted = self.run_command("approvals", "--grant", request_id)
        self.assertIn("RECORDED a grant", granted["effect"])

    def test_granting_an_unknown_request_is_refused(self) -> None:
        with self.assertRaisesRegex(CompanionError, "no approval request"):
            self.run_command("approvals", "--grant", "approval:nothing")

    def test_inspecting_a_missing_task_is_refused(self) -> None:
        with self.assertRaisesRegex(CompanionError, "no task"):
            self.run_command("task", "inspect", "task-nowhere")

    def test_run_demo_produces_the_whole_slice(self) -> None:
        demo_root = self.root / "demo"
        document = companion_cli.dispatch(parse("run-demo", "--demo-root", str(demo_root), root=self.root))
        self.assertTrue(document["passed"], document["failures"])
        self.assertEqual(len(document["steps"]), 21)
        self.assertIn("No network, provider or credential was used", document["effect"])
        self.assertEqual(document["provider"], "none")

    def test_the_default_root_is_under_the_user(self) -> None:
        import os

        previous = os.environ.pop("BUNNY_COMPANION_ROOT", None)
        try:
            self.assertIn("bunny-os", str(companion_cli.default_root()))
            os.environ["BUNNY_COMPANION_ROOT"] = str(self.root)
            self.assertEqual(companion_cli.default_root(), self.root)
        finally:
            os.environ.pop("BUNNY_COMPANION_ROOT", None)
            if previous is not None:
                os.environ["BUNNY_COMPANION_ROOT"] = previous


class CommandTreeTests(unittest.TestCase):
    def test_the_brief_s_commands_all_exist(self) -> None:
        parser = argparse.ArgumentParser(prog="bunny-os")
        sub = parser.add_subparsers(dest="command", required=True)
        companion_cli.add_arguments(sub)
        root = Path(tempfile.gettempdir())
        for argv in (
            ["companion", "sessions"],
            ["companion", "session", "create"],
            ["companion", "session", "inspect", "ses-1"],
            ["companion", "task", "submit", "--session", "ses-1", "--request", "x"],
            ["companion", "task", "inspect", "task-1"],
            ["companion", "task", "events", "task-1"],
            ["companion", "task", "cancel", "task-1"],
            ["companion", "approvals"],
            ["companion", "run-demo"],
        ):
            with self.subTest(argv=argv):
                parsed = parser.parse_args([*argv[:1], "--root", str(root), *argv[1:]])
                self.assertEqual(parsed.command, "companion")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

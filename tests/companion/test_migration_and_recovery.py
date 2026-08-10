# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§20's migration policy, and §22's persistence-and-recovery list.

The migration tests build a real donor SQLite file with the schema that branch
wrote, because a migration tested against a fixture somebody wrote to match the
importer is a migration tested against itself.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from companion.migration import (
    DONOR_TABLES,
    import_donor_store,
    inspect_donor_store,
    rollback_donor_import,
)
from companion.presentation import project_presentation
from companion.recovery import recover
from companion.store import CompanionStore

from .support import FULL_REQUEST, SIMPLE_REQUEST, CompanionTestCase


def _donor_store(path: Path, *, tasks: list[dict]) -> None:
    """Write a database in the shape the UX prototype actually used."""
    connection = sqlite3.connect(path)
    with connection:
        connection.executescript(
            """
            CREATE TABLE companion_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE companion_tasks (
                task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, terminal INTEGER NOT NULL,
                updated_at TEXT NOT NULL, record_json TEXT NOT NULL
            );
            CREATE TABLE companion_events (
                event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL, record_json TEXT NOT NULL
            );
            INSERT INTO companion_meta(key, value) VALUES('schemaVersion', '1');
            """
        )
        for index, task in enumerate(tasks, start=1):
            connection.execute(
                "INSERT INTO companion_tasks VALUES(?,?,?,?,?)",
                (
                    task["taskId"], task["sessionId"], int(task.get("terminal", 0)),
                    "2026-01-01T00:00:00Z", json.dumps(task),
                ),
            )
            connection.execute(
                "INSERT INTO companion_events VALUES(?,?,?,?,?,?,?)",
                (
                    f"ev-{index}", task["taskId"], task["sessionId"], 1,
                    "2026-01-01T00:00:00Z", "tool_started", json.dumps({"toolId": "x"}),
                ),
            )
    connection.close()


class DonorMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name) / "canonical"
        self.donor = Path(self._directory.name) / "companion.sqlite3"
        _donor_store(self.donor, tasks=[
            {
                "taskId": "task-completed", "sessionId": "ses-1", "terminal": 1,
                "currentPhase": "completed",
                "approvals": [{
                    "requestId": "approval:1", "planId": "plan-1", "transitionId": "t-1",
                    "action": "remote_dispatch", "destination": "remote", "decision": "approved",
                }],
            },
            {
                # Marked finished with no phase saying how. §20: this may not
                # become a completed task.
                "taskId": "task-terminal-but-silent", "sessionId": "ses-1", "terminal": 1,
                "approvals": [{"requestId": "approval:2", "decision": "approved"}],
            },
            {"taskId": "task-running", "sessionId": "ses-2", "terminal": 0, "currentPhase": "working"},
        ])

    def test_inspection_reads_without_writing(self) -> None:
        before = self.donor.stat().st_mtime_ns
        document = inspect_donor_store(self.donor)
        self.assertTrue(document["isDonorStore"])
        self.assertEqual(document["tasks"], 3)
        self.assertEqual(document["sessions"], 2)
        self.assertEqual(document["events"], 3)
        self.assertFalse(document["supported"])
        self.assertIn("never merged into the canonical", document["disposition"])
        self.assertEqual(self.donor.stat().st_mtime_ns, before)
        self.assertFalse((self.donor.parent / "companion.sqlite3-journal").exists())
        self.assertFalse((self.donor.parent / "companion.sqlite3-wal").exists())

    def test_something_that_is_not_a_donor_store_is_refused(self) -> None:
        other = Path(self._directory.name) / "notes.sqlite3"
        connection = sqlite3.connect(other)
        with connection:
            connection.execute("CREATE TABLE shopping (item TEXT)")
        connection.close()
        document = inspect_donor_store(other)
        self.assertFalse(document["isDonorStore"])
        self.assertTrue(document["problems"])
        report = import_donor_store(other, self.root, dry_run=False)
        self.assertFalse(report.performed)
        self.assertTrue(report.problems)
        self.assertEqual(sorted(DONOR_TABLES), sorted(DONOR_TABLES))

    def test_a_dry_run_reports_everything_and_writes_nothing(self) -> None:
        report = import_donor_store(self.donor, self.root)
        self.assertTrue(report.dry_run)
        self.assertFalse(report.performed)
        self.assertTrue(report.ok)
        self.assertEqual(report.tasks, 3)
        self.assertFalse(self.root.exists())
        self.assertIn("task-terminal-but-silent", report.uncertain_tasks)
        self.assertIn("task-running", report.uncertain_tasks)
        self.assertNotIn("task-completed", report.uncertain_tasks)

    def test_the_import_archives_and_never_touches_the_canonical_store(self) -> None:
        # A canonical store with real content, so "untouched" means something.
        store = CompanionStore(self.root / "store")
        store.initialise()
        before = sorted(
            (path.relative_to(self.root).as_posix(), path.read_bytes())
            for path in (self.root / "store").rglob("*") if path.is_file()
        )
        report = import_donor_store(self.donor, self.root, dry_run=False)
        self.assertTrue(report.performed, report.problems)
        self.assertTrue(report.ok)
        after = sorted(
            (path.relative_to(self.root).as_posix(), path.read_bytes())
            for path in (self.root / "store").rglob("*") if path.is_file()
        )
        self.assertEqual(before, after)
        self.assertEqual(store.session_ids(), ())
        archive = self.root / "imported" / "ux-shell-sqlite"
        self.assertTrue((archive / "manifest.json").is_file())
        self.assertTrue((archive / "tasks.json").is_file())
        self.assertTrue((archive / "events.json").is_file())

    def test_the_backup_is_verified_by_digest(self) -> None:
        report = import_donor_store(self.donor, self.root, dry_run=False)
        self.assertEqual(report.source_digest, report.copy_digest)
        self.assertTrue(report.source_digest)
        copy = self.root / "imported" / "ux-shell-sqlite" / "source" / "companion.sqlite3"
        self.assertTrue(copy.is_file())
        self.assertEqual(copy.read_bytes(), self.donor.read_bytes())
        # And the original is still where it was.
        self.assertTrue(self.donor.is_file())

    def test_an_unfinished_task_is_recorded_as_uncertain_and_never_completed(self) -> None:
        import_donor_store(self.donor, self.root, dry_run=False)
        tasks = json.loads(
            (self.root / "imported" / "ux-shell-sqlite" / "tasks.json").read_text(encoding="utf-8")
        )["tasks"]
        outcomes = {item["taskId"]: item["outcome"] for item in tasks}
        self.assertEqual(outcomes["task-completed"], "completed")
        self.assertEqual(outcomes["task-terminal-but-silent"], "uncertain")
        self.assertEqual(outcomes["task-running"], "uncertain")

    def test_an_approval_with_an_incomplete_binding_is_not_copied(self) -> None:
        report = import_donor_store(self.donor, self.root, dry_run=False)
        withheld = dict(report.withheld_approvals)
        self.assertIn("approval:2", withheld)
        self.assertIn("missing", withheld["approval:2"])
        tasks = json.loads(
            (self.root / "imported" / "ux-shell-sqlite" / "tasks.json").read_text(encoding="utf-8")
        )["tasks"]
        kept = {item["taskId"]: item["approvals"] for item in tasks}
        self.assertEqual(kept["task-terminal-but-silent"], [])
        self.assertEqual(len(kept["task-completed"]), 1)
        # And even a complete one authorises nothing.
        self.assertIn("authorises nothing", kept["task-completed"][0]["authority"])

    def test_importing_twice_is_refused_rather_than_merged(self) -> None:
        self.assertTrue(import_donor_store(self.donor, self.root, dry_run=False).performed)
        second = import_donor_store(self.donor, self.root, dry_run=False)
        self.assertFalse(second.performed)
        self.assertTrue(any("already exists" in item for item in second.problems))

    def test_rollback_removes_the_archive_and_nothing_else(self) -> None:
        import_donor_store(self.donor, self.root, dry_run=False)
        outcome = rollback_donor_import(self.root)
        self.assertTrue(outcome["removed"])
        self.assertFalse((self.root / "imported" / "ux-shell-sqlite").exists())
        self.assertTrue(self.donor.is_file())
        # Idempotent, and honest about it.
        again = rollback_donor_import(self.root)
        self.assertFalse(again["removed"])

    def test_rollback_refuses_a_directory_it_did_not_write(self) -> None:
        stranger = self.root / "imported" / "ux-shell-sqlite"
        stranger.mkdir(parents=True)
        (stranger / "somebodys-notes.txt").write_text("important", encoding="utf-8")
        outcome = rollback_donor_import(self.root)
        self.assertFalse(outcome["removed"])
        self.assertIn("not a donor archive", outcome["detail"])
        self.assertTrue((stranger / "somebodys-notes.txt").is_file())


class RecoveryTests(CompanionTestCase):
    """§22: what survives a restart, and what is honestly left undecided."""

    def test_a_completed_task_is_intact_after_a_runtime_restart(self) -> None:
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Recovery")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "completed")
        before = project_presentation(runtime.events(session.session_id, task_id=task.task_id))
        runtime.stop()

        restarted = self.started()
        report = recover(restarted)
        self.assertTrue(report.healthy)
        decisions = {item.task_id: item.decision for item in report.decisions}
        self.assertEqual(decisions[task.task_id], "intact")
        after = project_presentation(restarted.events(session.session_id, task_id=task.task_id))
        self.assertEqual(after.phase, "success")
        self.assertEqual(after.result_summary, before.result_summary)
        self.assertEqual(after.to_json(), before.to_json())

    def test_a_cancelled_task_stays_cancelled_across_a_restart(self) -> None:
        from companion.cancellation import cancel_task

        runtime = self.started()
        session = runtime.create_session("Cancelled")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        cancel_task(runtime, session.session_id, task.task_id, cause="user")
        runtime.stop()

        restarted = self.started()
        recover(restarted)
        self.assertEqual(restarted.task(session.session_id, task.task_id).state, "cancelled")
        state = project_presentation(restarted.events(session.session_id, task_id=task.task_id))
        self.assertEqual(state.phase, "cancelled")

    def test_a_pending_approval_does_not_survive_as_consent(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Approval")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        runtime.stop()

        from companion.approvals import CompanionApprovalStore

        reloaded = CompanionApprovalStore.load(self.root / "approvals.json")
        self.assertTrue(reloaded.warnings)
        self.assertEqual(reloaded.pending(), ())
        for response in reloaded.responses.values():
            self.assertNotEqual(response.decision, "granted")

    def test_a_corrupted_stream_is_reported_and_does_not_take_the_store_down(self) -> None:
        runtime = self.started()
        first = runtime.create_session("Healthy")
        runtime.submit_task(first.session_id, SIMPLE_REQUEST)
        second = runtime.create_session("Damaged")
        runtime.submit_task(second.session_id, SIMPLE_REQUEST)
        runtime.stop()

        events = self.root / "store" / "sessions" / second.session_id / "events.jsonl"
        lines = events.read_text(encoding="utf-8").splitlines(keepends=True)
        document = json.loads(lines[0])
        document["payload"]["title"] = "edited by somebody"
        lines[0] = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        events.write_text("".join(lines), encoding="utf-8")

        restarted = self.started()
        report = recover(restarted)
        self.assertFalse(report.healthy)
        damaged = dict(report.unreadable_sessions)
        self.assertIn(second.session_id, damaged)
        # The other session is still recovered. One damaged file must not cost
        # a user the rest of their history.
        self.assertIn(first.session_id, report.sessions)
        self.assertTrue(any(item.session_id == first.session_id for item in report.decisions))

    def test_an_interrupted_final_append_is_dropped_and_reported(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Truncated")
        runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        runtime.stop()

        events = self.root / "store" / "sessions" / session.session_id / "events.jsonl"
        with events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write('{"schemaVersion": 2, "eventId": "ev-999", "sequ')

        restarted = self.started()
        read = restarted.store.read_stream(session.session_id)
        self.assertEqual(read.incomplete_tail, 1)
        self.assertTrue(read.warnings)
        self.assertIn("nothing was reconstructed", read.warnings[0])
        # And the surface built from what remains is still coherent.
        state = project_presentation(read.events)
        self.assertIn(state.phase, ("starting", "idle"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

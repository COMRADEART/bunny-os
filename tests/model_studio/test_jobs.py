# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The state machine, and the promise that a crash cannot become a success."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from model_studio.errors import JobStateError, ModelStudioError
from model_studio.jobs import state as machine
from model_studio.jobs.store import JobStore


class Machine(unittest.TestCase):
    def test_the_happy_path_exists(self) -> None:
        path = [
            machine.CREATED, machine.PREFLIGHTING, machine.READY, machine.PREPARING,
            machine.TRAINING, machine.EVALUATING, machine.COMPLETED,
        ]
        for current, target in zip(path, path[1:]):
            machine.check_transition(current, target)

    def test_completed_has_exactly_one_predecessor(self) -> None:
        """The property the whole store exists to hold."""
        predecessors = [
            state for state, targets in machine.TRANSITIONS.items()
            if machine.COMPLETED in targets
        ]
        self.assertEqual(predecessors, [machine.EVALUATING])

    def test_training_cannot_jump_to_completed(self) -> None:
        with self.assertRaises(JobStateError):
            machine.check_transition(machine.TRAINING, machine.COMPLETED)

    def test_terminal_states_are_terminal(self) -> None:
        for state in (machine.COMPLETED, machine.FAILED, machine.CANCELLED):
            self.assertEqual(machine.TRANSITIONS[state], frozenset())
            with self.assertRaises(JobStateError):
                machine.check_transition(state, machine.TRAINING)

    def test_blocked_can_be_retried(self) -> None:
        machine.check_transition(machine.BLOCKED, machine.PREFLIGHTING)

    def test_an_unknown_state_is_refused(self) -> None:
        with self.assertRaises(JobStateError):
            machine.check_transition("finished", machine.COMPLETED)

    def test_every_state_can_reach_a_terminal_one(self) -> None:
        for state in machine.STATES:
            with self.subTest(state=state):
                seen, frontier = set(), [state]
                while frontier:
                    current = frontier.pop()
                    if current in seen:
                        continue
                    seen.add(current)
                    frontier.extend(machine.TRANSITIONS[current])
                self.assertTrue(seen & machine.TERMINAL)


class Store(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "jobs"
        self.store = JobStore(self.root, boot_id="boot-a")

    def test_a_new_job_is_created_and_persisted(self) -> None:
        record = self.store.create(detail="from a test")
        self.assertEqual(record.state, machine.CREATED)
        self.assertTrue((self.root / f"{record.job_id}.json").is_file())
        self.assertEqual(self.store.load(record.job_id).job_id, record.job_id)

    def test_transitions_are_recorded_in_order(self) -> None:
        record = self.store.create()
        record = self.store.transition(record, machine.PREFLIGHTING, detail="checking")
        record = self.store.transition(record, machine.BLOCKED, detail="no GPU")
        self.assertEqual(
            [change.became for change in record.history],
            [machine.CREATED, machine.PREFLIGHTING, machine.BLOCKED],
        )
        self.assertEqual(self.store.load(record.job_id).state, machine.BLOCKED)

    def test_an_illegal_transition_is_refused_and_nothing_is_written(self) -> None:
        record = self.store.create()
        with self.assertRaises(JobStateError):
            self.store.transition(record, machine.COMPLETED)
        self.assertEqual(self.store.load(record.job_id).state, machine.CREATED)

    def test_attached_fields_land_in_the_same_write_as_the_state(self) -> None:
        record = self.store.create()
        record = self.store.transition(record, machine.PREFLIGHTING)
        record = self.store.transition(
            record, machine.READY, preflight={"status": "READY"}
        )
        reloaded = self.store.load(record.job_id)
        self.assertEqual(reloaded.state, machine.READY)
        self.assertEqual(reloaded.preflight, {"status": "READY"})

    def test_listing_is_chronological(self) -> None:
        identifiers = [self.store.create(job_id=f"job-{index}").job_id for index in range(3)]
        self.assertEqual([record.job_id for record in self.store.list()], sorted(identifiers))

    def test_an_unknown_job_is_an_error_not_an_empty_record(self) -> None:
        with self.assertRaises(ModelStudioError):
            self.store.load("nothing")

    def test_a_traversing_identifier_is_refused(self) -> None:
        for bad in ("../escape", "a/b", ".hidden", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ModelStudioError):
                    self.store.path_for(bad)


class CrashRecovery(unittest.TestCase):
    """A record that says ``training`` is a claim, and it is checked."""

    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "jobs"

    def _job_in_training(self, store: JobStore) -> str:
        record = store.create()
        record = store.transition(record, machine.PREFLIGHTING)
        record = store.transition(record, machine.READY)
        record = store.transition(record, machine.PREPARING)
        record = store.transition(record, machine.TRAINING)
        return record.job_id

    def test_a_reboot_fails_an_active_job(self) -> None:
        before = JobStore(self.root, boot_id="boot-a")
        job_id = self._job_in_training(before)

        after = JobStore(self.root, boot_id="boot-b")
        recovered = after.load(job_id)
        self.assertEqual(recovered.state, machine.FAILED)
        self.assertIn("before a restart", recovered.detail)
        self.assertIn("interrupted in training", recovered.detail)

    def test_a_dead_process_fails_an_active_job(self) -> None:
        store = JobStore(self.root, boot_id="boot-a")
        job_id = self._job_in_training(store)
        record = store.load(job_id, recover=False)
        # A pid that is not this process and is not plausibly running.
        store._write(replace(record, owner_pid=2 ** 22))  # noqa: SLF001 - a stale file
        recovered = JobStore(self.root, boot_id="boot-a").load(job_id)
        self.assertEqual(recovered.state, machine.FAILED)
        self.assertIn("no longer present", recovered.detail)

    def test_recovery_is_persisted_not_just_reported(self) -> None:
        before = JobStore(self.root, boot_id="boot-a")
        job_id = self._job_in_training(before)
        JobStore(self.root, boot_id="boot-b").load(job_id)
        again = JobStore(self.root, boot_id="boot-b").load(job_id, recover=False)
        self.assertEqual(again.state, machine.FAILED)

    def test_a_completed_job_is_never_touched(self) -> None:
        store = JobStore(self.root, boot_id="boot-a")
        record = store.create()
        for target in (machine.PREFLIGHTING, machine.READY, machine.PREPARING,
                       machine.TRAINING, machine.EVALUATING, machine.COMPLETED):
            record = store.transition(record, target)
        later = JobStore(self.root, boot_id="boot-b").load(record.job_id)
        self.assertEqual(later.state, machine.COMPLETED)

    def test_an_interrupted_job_never_reads_as_completed(self) -> None:
        """The guarantee, stated as the test that would catch its loss."""
        before = JobStore(self.root, boot_id="boot-a")
        job_id = self._job_in_training(before)
        after = JobStore(self.root, boot_id="boot-b")
        self.assertNotEqual(after.load(job_id).state, machine.COMPLETED)
        self.assertIn(after.load(job_id).state, machine.TERMINAL)

    def test_recover_all_reports_what_it_changed(self) -> None:
        before = JobStore(self.root, boot_id="boot-a")
        first = self._job_in_training(before)
        idle = before.create()
        changed = JobStore(self.root, boot_id="boot-b").recover_all()
        self.assertEqual([record.job_id for record in changed], [first])
        self.assertEqual(
            JobStore(self.root, boot_id="boot-b").load(idle.job_id).state, machine.CREATED
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

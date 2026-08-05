# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sessions, tasks, and the state machine that connects them."""

from __future__ import annotations

from dataclasses import replace
import unittest

from companion.errors import CompanionError, InvalidTransition, SchemaError
from companion.session import CompanionSession, CostPolicy, PrivacyPolicy
from companion.states import (
    STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    event_for,
    may_start_operation,
    require_transition,
    transition_allowed,
)
from companion.task import CompanionTask

from .support import SIMPLE_REQUEST, CompanionTestCase


class SessionModelTests(unittest.TestCase):
    def test_a_new_session_is_strict_by_default(self) -> None:
        session = CompanionSession.create(session_id="ses-1", title="Work", now=0.0)
        self.assertEqual(session.privacy_policy.default_classification, "personal")
        self.assertFalse(session.privacy_policy.allow_remote)
        self.assertEqual(session.locality_preference, "device-only")
        self.assertEqual(session.cost_policy.task_limit_units, 0)

    def test_the_document_round_trips(self) -> None:
        session = CompanionSession.create(
            session_id="ses-1", title="Work", now=0.0,
            privacy_policy=PrivacyPolicy(allow_remote=True),
            cost_policy=CostPolicy(task_limit_units=10, session_limit_units=100),
            locality_preference="any",
        )
        self.assertEqual(CompanionSession.from_json(session.to_json()), session)

    def test_secret_cannot_be_the_remote_ceiling(self) -> None:
        with self.assertRaisesRegex(SchemaError, "secret data never leaves"):
            PrivacyPolicy(maximum_remote_classification="secret")

    def test_a_task_may_not_outspend_its_session(self) -> None:
        with self.assertRaisesRegex(SchemaError, "more than its whole session"):
            CostPolicy(task_limit_units=200, session_limit_units=100)

    def test_a_task_cannot_be_active_and_completed_at_once(self) -> None:
        with self.assertRaisesRegex(SchemaError, "both active and completed"):
            CompanionSession(
                session_id="ses-1", title="t", created_at="", last_activity_at="",
                active_task_ids=("task-1",), completed_task_ids=("task-1",),
            )

    def test_a_closed_session_cannot_be_resumed(self) -> None:
        session = CompanionSession.create(session_id="ses-1", title="Work", now=0.0).closed(1.0)
        with self.assertRaisesRegex(SchemaError, "closed session cannot be resumed"):
            session.resumed(2.0)

    def test_finishing_a_task_is_idempotent(self) -> None:
        session = CompanionSession.create(session_id="ses-1", title="Work", now=0.0)
        session = session.with_task("task-1", 1.0).task_finished("task-1", 2.0)
        again = session.task_finished("task-1", 3.0)
        self.assertEqual(again.completed_task_ids, ("task-1",))
        self.assertEqual(again.active_task_ids, ())


class TaskModelTests(unittest.TestCase):
    def base(self, **kwargs: object) -> CompanionTask:
        task = CompanionTask.create(
            task_id="task-1", session_id="ses-1", request="Count the words", now=0.0
        )
        return replace(task, **kwargs) if kwargs else task

    def test_the_document_round_trips(self) -> None:
        task = self.base()
        self.assertEqual(CompanionTask.from_json(task.to_json()), task)

    def test_a_credential_in_the_request_never_reaches_the_summary(self) -> None:
        task = CompanionTask.create(
            task_id="task-1", session_id="ses-1", now=0.0,
            request="Post this with Bearer abcdefghijklmnop please",
        )
        self.assertNotIn("abcdefghijklmnop", task.display_summary)
        self.assertIn("[redacted]", task.display_summary)

    def test_offline_and_remote_locality_is_a_contradiction(self) -> None:
        with self.assertRaisesRegex(SchemaError, "must also be device-only"):
            self.base(requires_offline=True, data_locality="any")

    def test_progress_never_goes_backwards(self) -> None:
        task = self.base().with_progress(0.6).with_progress(0.2)
        self.assertEqual(task.progress, 0.6)

    def test_no_deadline_is_not_an_exhausted_deadline(self) -> None:
        self.assertEqual(self.base().deadline_remaining_seconds, float("inf"))
        spent = self.base(execution_deadline_seconds=10.0, deadline_consumed_seconds=10.0)
        self.assertEqual(spent.deadline_remaining_seconds, 0.0)

    def test_a_reviewer_cannot_read_a_personal_request(self) -> None:
        task = self.base(classification="personal")
        self.assertEqual(task.view("reviewer")["originalRequest"], "[withheld: personal]")
        self.assertEqual(task.view("executor")["originalRequest"], task.original_request)


class StateMachineTests(unittest.TestCase):
    def test_every_transition_names_known_states_and_an_event(self) -> None:
        for (source, target), event_type in TRANSITIONS.items():
            self.assertIn(source, STATES)
            self.assertIn(target, STATES)
            self.assertTrue(event_type, f"{source}->{target} has no event type")

    def test_terminal_states_have_no_exit(self) -> None:
        for state in TERMINAL_STATES:
            self.assertEqual([t for s, t in TRANSITIONS if s == state], [])

    def test_a_valid_transition_returns_its_event(self) -> None:
        self.assertEqual(event_for("presenting", "completed"), "task_completed")
        self.assertEqual(event_for("classifying", "waiting_for_capability"), "task_classified")

    def test_an_invalid_transition_is_refused_and_says_what_is_possible(self) -> None:
        with self.assertRaises(InvalidTransition) as caught:
            require_transition("executing", "completed")
        self.assertIn("presenting", str(caught.exception))

    def test_a_finished_task_cannot_move(self) -> None:
        with self.assertRaisesRegex(InvalidTransition, "final"):
            require_transition("completed", "executing")

    def test_recovery_never_resumes_straight_into_execution(self) -> None:
        # The load-bearing rule of companion.recovery, asserted on the table
        # rather than on the code that reads it.
        self.assertFalse(transition_allowed("recovering", "executing"))
        self.assertTrue(transition_allowed("recovering", "planning"))

    def test_only_executing_may_start_an_operation(self) -> None:
        for state in STATES:
            self.assertEqual(may_start_operation(state), state == "executing", state)

    def test_unknown_states_are_refused(self) -> None:
        with self.assertRaisesRegex(InvalidTransition, "unknown current state"):
            require_transition("daydreaming", "executing")
        with self.assertRaisesRegex(InvalidTransition, "unknown target state"):
            require_transition("executing", "daydreaming")


class RuntimeLifecycleTests(CompanionTestCase):
    def test_a_session_and_task_are_created_and_persisted(self) -> None:
        runtime = self.started()
        session = runtime.create_session("First")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        self.assertEqual(task.state, "created")
        self.assertIn(task.task_id, runtime.session(session.session_id).active_task_ids)
        self.assertEqual(runtime.store.load_task(session.session_id, task.task_id), task)

    def test_a_task_runs_to_completion(self) -> None:
        runtime = self.started()
        _, task = self.completed_task(runtime)
        self.assertEqual(task.state, "completed")
        self.assertEqual(task.progress, 1.0)
        self.assertTrue(task.outputs)
        self.assertTrue(task.completed_at)

    def test_concurrent_tasks_keep_separate_records(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Two tasks")
        first = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        second = runtime.submit_task(session.session_id, "Count the words in the other note.")
        self.assertNotEqual(first.task_id, second.task_id)

        finished_first = runtime.run_task(session.session_id, first.task_id)
        finished_second = runtime.run_task(session.session_id, second.task_id)
        self.assertEqual(finished_first.state, "completed")
        self.assertEqual(finished_second.state, "completed")

        first_events = runtime.events(session.session_id, task_id=first.task_id)
        second_events = runtime.events(session.session_id, task_id=second.task_id)
        self.assertTrue(first_events and second_events)
        self.assertEqual({event.task_id for event in first_events}, {first.task_id})
        self.assertEqual({event.task_id for event in second_events}, {second.task_id})
        # One stream, so the sequences interleave without ever colliding.
        everything = runtime.events(session.session_id)
        self.assertEqual(
            [event.sequence for event in everything],
            list(range(1, len(everything) + 1)),
        )

    def test_pause_records_the_phase_it_interrupted_and_resume_restores_it(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Pausing")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        moved = runtime._transition(task, "classifying")
        runtime.store.save_task(moved)

        paused = runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(paused.state, "paused")
        self.assertEqual(paused.paused_from, "classifying")

        resumed = runtime.resume_task(session.session_id, task.task_id)
        self.assertEqual(resumed.state, "classifying")
        self.assertEqual(resumed.paused_from, "")

    def test_resuming_a_task_that_is_not_paused_is_refused(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Not paused")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        with self.assertRaisesRegex(CompanionError, "is not paused"):
            runtime.resume_task(session.session_id, task.task_id)

    def test_a_closed_session_takes_no_new_tasks(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Closing")
        runtime.close_session(session.session_id)
        with self.assertRaisesRegex(CompanionError, "closed"):
            runtime.submit_task(session.session_id, SIMPLE_REQUEST)

    def test_sessions_and_tasks_survive_a_restart(self) -> None:
        first = self.started()
        session, task = self.completed_task(first)
        summary = [item.summary for item in task.outputs]
        first.stop()

        second = self.started()
        reloaded_session = second.session(session.session_id)
        reloaded_task = second.task(session.session_id, task.task_id)
        self.assertEqual(reloaded_session.session_id, session.session_id)
        self.assertEqual(reloaded_task.state, "completed")
        self.assertEqual([item.summary for item in reloaded_task.outputs], summary)

    def test_every_transition_produced_an_event(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime)
        events = runtime.events(session.session_id, task_id=task.task_id)
        # The lifecycle moved from created to completed; each move is in the
        # stream, so the terminal events must be present and last.
        self.assertEqual(events[-1].event_type, "task_completed")
        self.assertIn("task_classified", {event.event_type for event in events})
        self.assertIn("capability_checked", {event.event_type for event in events})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

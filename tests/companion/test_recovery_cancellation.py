# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Crashing, stopping, and coming back without inventing anything.

The centrepiece is :meth:`RecoveryTests.test_a_crash_between_start_and_completion_does_not_repeat_the_operation`.
Everything else in this module supports it: the operation whose outcome nobody
knows must not be performed again, and the record must say that it is unknown
rather than quietly rounding it to "failed" or "done".
"""

from __future__ import annotations

from dataclasses import replace
import json
import unittest

from companion.cancellation import cancel_task
from companion.errors import CompanionError
from companion.executor import ProducedOutput
from companion.recovery import recover
from companion.task import OperationReference

from companion.executor import DeterministicLocalExecutor

from .support import (
    FULL_REQUEST,
    SIMPLE_REQUEST,
    CompanionTestCase,
    UnavailableExecutor,
)


class CrashHarness(CompanionTestCase):
    """Drives a task partway through the pipeline and abandons it."""

    def partway(self, runtime, *, through: str, request: str = SIMPLE_REQUEST):
        """Advance a task to a phase and stop, as a killed process would.

        The phases are driven directly rather than by interrupting
        :meth:`run_task`, because a test that raced a real interrupt would be a
        test whose failures were about timing.
        """
        session = runtime.create_session("Crashing")
        task = runtime.submit_task(session.session_id, request)
        if through == "created":
            return session, runtime.task(session.session_id, task.task_id)

        task = runtime._transition(task, "classifying")
        task = runtime._classify(runtime.session(session.session_id), task)
        if through == "classified":
            runtime.store.save_task(task)
            return session, task

        decision, task = runtime._check_capability(runtime.session(session.session_id), task)
        task = runtime._select_executor(runtime.session(session.session_id), task, decision)
        task = runtime._transition(task, "planning", {"planRevision": 1})
        task = replace(task, plan_revision=1)
        if through == "planned":
            runtime.store.save_task(task)
            return session, task

        task = runtime._transition(task, "executing", {"planRevision": 1})
        if through == "before_operation":
            runtime.store.save_task(task)
            return session, task

        # The *derived* key the executor's own plan would produce. A made-up key
        # would never match anything and would make the non-repetition
        # assertions pass for the wrong reason.
        from companion.executor import context_for

        planned = runtime.executor(task.executor_id).plan(context_for(task, plan_revision=1))
        key = planned.keys_for(task.task_id)[0]
        runtime._emit(
            session.session_id, task.task_id, "operation_started",
            {"operationKey": key, "name": "count-words", "tool": "text.count_words"},
            classification=task.classification,
        )
        task = task.with_operation(OperationReference(
            key=key, name="count-words", status="started",
            started_sequence=runtime.store.tip(session.session_id)[0],
        ))
        runtime.store.save_task(task)
        if through == "during_operation":
            return session, task

        runtime._emit(
            session.session_id, task.task_id, "operation_completed",
            {"operationKey": key, "name": "count-words", "value": 9},
            classification=task.classification,
        )
        task = task.with_operation(OperationReference(
            key=key, name="count-words", status="completed",
            started_sequence=task.operation(key).started_sequence,
            settled_sequence=runtime.store.tip(session.session_id)[0],
        ))
        runtime.store.save_task(task)
        return session, task


class RecoveryTests(CrashHarness):
    def test_a_crash_before_any_operation_restarts_from_classification(self) -> None:
        first = self.started()
        session, _ = self.partway(first, through="before_operation")
        first.stop()

        second = self.started()
        report = recover(second)
        decision = report.decisions[0]
        self.assertEqual(decision.decision, "resumed")
        self.assertEqual(decision.unknown_operations, ())
        self.assertEqual(second.store.load_task(session.session_id, decision.task_id).state, "planning")

    def test_a_crash_between_start_and_completion_does_not_repeat_the_operation(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="during_operation")
        first.stop()

        second = self.started()
        report = recover(second)
        decision = report.decisions[0]
        self.assertEqual(decision.decision, "resumed")
        self.assertEqual(len(decision.unknown_operations), 1)

        recovered = second.store.load_task(session.session_id, task.task_id)
        self.assertEqual(recovered.state, "planning")
        uncertain = [item for item in recovered.operations if item.status == "unknown"]
        self.assertEqual(len(uncertain), 1)
        self.assertIn("not known", uncertain[0].recovery_note)
        self.assertNotIn("failed", [item.status for item in recovered.operations])

        # Resuming must not perform the uncertain act again — not under its own
        # key and not under a new one. This is the guarantee three module
        # docstrings claim, and it was false until the idempotency key was
        # changed to identify the act rather than its position in a plan.
        before = list(second.broker.invocations)
        final = second.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "completed")

        performed = [item["toolId"] for item in second.broker.invocations[len(before):]]
        self.assertNotIn(
            "text.count_words", performed,
            "the operation whose outcome is unknown was performed again",
        )

        still_unknown = [item for item in final.operations if item.key == uncertain[0].key]
        self.assertEqual([item.status for item in still_unknown], ["unknown"])

        # And the refusal is in the stream, with its reason, rather than being a
        # silent gap between two operations.
        skipped = [
            event.payload for event in second.events(session.session_id, task_id=task.task_id)
            if event.event_type == "operation_progress" and event.payload.get("skipped")
        ]
        self.assertTrue(skipped)
        self.assertIn("not known", skipped[0]["reason"])
        self.assertEqual(skipped[0]["operationKey"], uncertain[0].key)

    def test_an_operation_the_record_proves_completed_is_not_done_twice(self) -> None:
        # The milder half of the same defect: a replan that still contains an
        # operation already recorded as completed must skip it and carry its
        # value forward, not perform it again.
        first = self.started()
        session, task = self.partway(first, through="after_operation")
        completed_key = [item.key for item in
                         first.task(session.session_id, task.task_id).operations][0]
        first.stop()

        second = self.started()
        recover(second)
        before = list(second.broker.invocations)
        final = second.run_task(session.session_id, task.task_id)

        performed = [item["toolId"] for item in second.broker.invocations[len(before):]]
        self.assertNotIn("text.count_words", performed)
        self.assertEqual(final.state, "completed")
        self.assertEqual(
            [item.status for item in final.operations if item.key == completed_key],
            ["completed"],
        )

    def test_a_crash_after_an_operation_but_before_completion_keeps_the_completed_key(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="after_operation")
        first.stop()

        second = self.started()
        recover(second)
        recovered = second.store.load_task(session.session_id, task.task_id)
        self.assertEqual(
            [item.status for item in recovered.operations], ["completed"],
            "an operation with a completion event is known, not unknown",
        )
        self.assertEqual(recovered.state, "planning")

    def test_recovery_invalidates_approvals_from_before_the_restart(self) -> None:
        # A task that ran, asked for consent and was refused: the question is on
        # the record and the task is blocked. Recovery must not carry any of
        # that consent state forward into the new run.
        first = self.started()
        session = first.create_session("Approved")
        task = first.submit_task(session.session_id, FULL_REQUEST)
        blocked = first.run_task(session.session_id, task.task_id)
        self.assertEqual(blocked.state, "blocked")
        request_id = blocked.approvals[0].request_id
        first.approvals.save()
        first.stop()

        from companion.approvals import CompanionApprovalStore

        reloaded = CompanionApprovalStore.load(self.root / "approvals.json")
        self.assertEqual(reloaded.decision_for(request_id).decision, "expired")
        self.assertTrue(reloaded.warnings)
        self.harness.approvals = reloaded

        second = self.started()
        report = recover(second)
        self.assertTrue(any("does not survive a restart" in item for item in report.warnings))

    def test_a_missing_executor_blocks_rather_than_guessing(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="during_operation")
        first.stop()

        # The runtime that comes back has a different executor configured.
        second = self.started(executors=(UnavailableExecutor(),))
        report = recover(second)
        decision = report.decisions[0]
        self.assertEqual(decision.decision, "blocked")
        self.assertFalse(decision.executor_present)
        self.assertIn("not configured in this runtime", " ".join(decision.reasons))

    def test_a_finished_task_is_left_alone(self) -> None:
        first = self.started()
        session, task = self.completed_task(first)
        first.stop()

        second = self.started()
        report = recover(second)
        self.assertEqual([item.decision for item in report.decisions], ["intact"])
        self.assertEqual(second.task(session.session_id, task.task_id).state, "completed")

    def test_recovery_is_safe_to_run_twice(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="during_operation")
        first.stop()

        second = self.started()
        recover(second)
        state_once = second.store.load_task(session.session_id, task.task_id).state
        again = recover(second)
        state_twice = second.store.load_task(session.session_id, task.task_id).state
        self.assertEqual(state_once, state_twice)
        self.assertEqual([item.decision for item in again.decisions], ["intact"])

    def test_a_corrupt_session_is_reported_without_losing_the_others(self) -> None:
        first = self.started()
        healthy_session, healthy_task = self.completed_task(first)
        broken_session = first.create_session("Broken")
        first.submit_task(broken_session.session_id, SIMPLE_REQUEST)
        first.stop()

        # Corrupt one event in the broken session's chain.
        path = self.root / "store" / "sessions" / broken_session.session_id / "events.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[0])
        document["payload"]["title"] = "tampered"
        lines[0] = json.dumps(document, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

        second = self.started()
        report = second and recover(second)
        self.assertFalse(report.healthy)
        self.assertEqual([name for name, _ in report.unreadable_sessions], [broken_session.session_id])
        # The healthy session was still recovered.
        self.assertIn(healthy_session.session_id, report.sessions)
        self.assertEqual(second.task(healthy_session.session_id, healthy_task.task_id).state, "completed")

    def test_recovery_reconciles_a_projection_that_lags_the_stream(self) -> None:
        first = self.started()
        session, task = self.completed_task(first)
        # Roll the session projection back, as a crash between the append and
        # the projection write would.
        stale = replace(first.store.load_session(session.session_id), event_stream_revision=1)
        first.store.save_session(stale)
        first.stop()

        second = self.started()
        report = recover(second)
        self.assertTrue(any("stream is authoritative" in item for item in report.warnings))
        healed = second.store.load_session(session.session_id)
        self.assertEqual(healed.event_stream_revision, second.store.tip(session.session_id)[0])


class CancellationTests(CrashHarness):
    def test_cancelling_stops_new_operations_and_records_the_unknown_one(self) -> None:
        runtime = self.started()
        session, task = self.partway(runtime, through="during_operation")
        calls_before = len(runtime.broker.invocations)

        outcome = cancel_task(runtime, session.session_id, task.task_id, cause="user")
        self.assertEqual(outcome.task.state, "cancelled")
        self.assertEqual(outcome.task.cancellation_state, "complete")
        self.assertEqual(outcome.task.cancellation_cause, "user")
        self.assertEqual(len(outcome.unknown_operations), 1)
        self.assertEqual(len(runtime.broker.invocations), calls_before)

        events = runtime.events(session.session_id, task_id=task.task_id)
        self.assertEqual(events[-1].event_type, "task_cancelled")

    def test_cancelling_withdraws_a_pending_approval(self) -> None:
        runtime = self.started()  # nobody answers
        session = runtime.create_session("Cancel with approval")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        blocked = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(blocked.state, "blocked")

        outcome = cancel_task(runtime, session.session_id, task.task_id, cause="user")
        self.assertEqual(len(outcome.withdrawn_approvals), 1)
        answer = runtime.approvals.decision_for(outcome.withdrawn_approvals[0])
        self.assertEqual(answer.decision, "expired")

    def test_partial_output_is_kept(self) -> None:
        runtime = self.started()
        session, task = self.partway(runtime, through="during_operation")
        outcome = cancel_task(
            runtime, session.session_id, task.task_id, cause="user",
            partial_outputs=(ProducedOutput(output_id="partial-1", content="words=9"),),
        )
        self.assertEqual(outcome.retained_outputs, ("partial-1",))
        self.assertEqual([item.output_id for item in outcome.task.outputs], ["partial-1"])

    def test_every_cause_is_recorded_distinctly(self) -> None:
        # One runtime for all six, so the identifier source keeps counting.
        # Building a fresh runtime per cause over the same store would restart
        # the sequential ids and collide, which is a property of the test
        # harness rather than of cancellation.
        runtime = self.started()
        for cause in ("user", "policy", "timeout", "capability_loss", "provider_loss", "supervisor_shutdown"):
            with self.subTest(cause=cause):
                session, task = self.partway(runtime, through="before_operation")
                outcome = cancel_task(runtime, session.session_id, task.task_id, cause=cause)
                self.assertEqual(outcome.task.cancellation_cause, cause)
                final = runtime.events(session.session_id, task_id=task.task_id)[-1]
                self.assertEqual(final.event_type, "task_cancelled")
                self.assertEqual(final.payload["reason"], cause)

    def test_an_unknown_cause_is_refused(self) -> None:
        runtime = self.started()
        session, task = self.partway(runtime, through="before_operation")
        with self.assertRaisesRegex(CompanionError, "cancellation cause must be"):
            cancel_task(runtime, session.session_id, task.task_id, cause="boredom")

    def test_cancelling_twice_is_harmless(self) -> None:
        runtime = self.started()
        session, task = self.partway(runtime, through="before_operation")
        cancel_task(runtime, session.session_id, task.task_id, cause="user")
        again = cancel_task(runtime, session.session_id, task.task_id, cause="user")
        self.assertIn("already cancelled", again.detail)

    def test_a_cancellation_written_by_another_process_stops_the_next_operation(self) -> None:
        # `bunny-os companion task cancel` runs in its own process and writes to
        # the same store. The executor lease is in memory, so it does not stop
        # that; what stops it is the runtime re-reading the persisted
        # cancellation state between operations.
        # FULL_REQUEST with consent granted gives a two-operation first plan —
        # count-words then publish-notice — so there is a genuine second
        # operation for the cancellation to stop.
        runtime = self.started(reviewers=(), consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Out of band")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)

        original = runtime.broker.invoke
        marked: list[str] = []

        def cancel_after_the_first_call(tool_id, arguments, *, caller, classification="internal"):
            outcome = original(tool_id, arguments, caller=caller, classification=classification)
            if not marked:
                marked.append(tool_id)
                # Another process marks the task cancelled, mid-plan.
                stored = runtime.store.load_task(session.session_id, task.task_id)
                runtime.store.save_task(replace(
                    stored, cancellation_state="requested", cancellation_cause="user",
                ))
            return outcome

        runtime.broker.invoke = cancel_after_the_first_call  # type: ignore[method-assign]
        final = runtime.run_task(session.session_id, task.task_id)

        performed = [item["toolId"] for item in runtime.broker.invocations]
        self.assertEqual(performed, ["text.count_words"], "the second operation must not have run")
        self.assertEqual(final.cancellation_state, "requested")

    def test_a_cancellation_landing_between_operations_stops_the_next_one(self) -> None:
        # The other window: the cancel arrives after the previous operation's
        # write rather than during an operation. This is the check at the top of
        # the loop; the test above covers the merge on write. Both windows exist,
        # so both are tested — removing either guard fails exactly one of them.
        runtime = self.started(reviewers=(), consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Between operations")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)

        original = runtime.store.save_task
        marked: list[str] = []

        def cancel_after_the_first_write(written):
            original(written)
            if written.operations and not marked and all(
                item.settled for item in written.operations
            ):
                marked.append(written.task_id)
                original(replace(
                    written, cancellation_state="requested", cancellation_cause="policy",
                ))

        runtime.store.save_task = cancel_after_the_first_write  # type: ignore[method-assign]
        final = runtime.run_task(session.session_id, task.task_id)

        performed = [item["toolId"] for item in runtime.broker.invocations]
        self.assertEqual(performed, ["text.count_words"])
        self.assertNotIn("notice.publish", performed)
        self.assertEqual(final.cancellation_cause, "policy")

    def test_cancelling_a_running_task_stops_it_reaching_completion(self) -> None:
        # A security review found that cancellation stopped the *operations* and
        # then let the pipeline carry the task on through review, result and
        # completion — so the stream said `task_cancelled` and then
        # `task_completed`, and the persisted state was `completed` with the
        # cancellation erased. The record asserted that a task the user stopped
        # had finished normally.
        runtime = self.started(reviewers=(), consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Cancel mid-run")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)

        original = runtime.broker.invoke
        fired: list[str] = []

        def cancel_during_the_first_operation(tool_id, arguments, *, caller, classification="internal"):
            outcome = original(tool_id, arguments, caller=caller, classification=classification)
            if not fired:
                fired.append(tool_id)
                cancel_task(runtime, session.session_id, task.task_id, cause="user")
            return outcome

        runtime.broker.invoke = cancel_during_the_first_operation  # type: ignore[method-assign]
        returned = runtime.run_task(session.session_id, task.task_id)

        persisted = runtime.task(session.session_id, task.task_id)
        self.assertEqual(returned.state, "cancelled")
        self.assertEqual(persisted.state, "cancelled")
        self.assertEqual(persisted.cancellation_state, "complete")
        self.assertEqual(persisted.cancellation_cause, "user")
        self.assertNotIn("notice.publish", [item["toolId"] for item in runtime.broker.invocations])

        events = runtime.events(session.session_id, task_id=task.task_id)
        cancelled_at = max(item.sequence for item in events if item.event_type == "task_cancelled")
        after = [item.event_type for item in events if item.sequence > cancelled_at]
        self.assertNotIn("task_completed", after)
        self.assertNotIn("result_created", after)

    def test_cancelling_during_review_stops_the_task(self) -> None:
        # The second round of security review found this window still open: the
        # first fix checked the operation loop only, so a cancel arriving during
        # review — up to `maximum_reviewers × reviewer_timeout_seconds`, twenty
        # seconds by default — went on to a result and a completion.
        from companion.reviewer import ReviewObservation

        holder: dict[str, object] = {}
        produced: list[str] = []

        class CancelsWhileReviewing:
            reviewer_id = "local.canceller"

            def observe(self, context):
                cancel_task(holder["runtime"], holder["session"], holder["task"], cause="policy")
                return (ReviewObservation(reviewer_id=self.reviewer_id, summary="looked"),)

        class RecordsWhetherItWasAsked(DeterministicLocalExecutor):
            def result(self, context):
                produced.append("asked")
                return super().result(context)

        runtime = self.started(
            executors=(RecordsWhetherItWasAsked(),), reviewers=(CancelsWhileReviewing(),),
        )
        session = runtime.create_session("Cancel in review")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        holder.update(runtime=runtime, session=session.session_id, task=task.task_id)

        returned = runtime.run_task(session.session_id, task.task_id)
        persisted = runtime.task(session.session_id, task.task_id)
        self.assertEqual(returned.state, "cancelled")
        self.assertEqual(persisted.state, "cancelled")
        self.assertEqual(persisted.cancellation_cause, "policy")

        # And the executor was never asked for a result. `executor.result()` is
        # third-party code with no bound on how long it may take; a cancelled
        # task should not be handing it more work. This is what the check
        # between review and result buys — the one after the result would catch
        # the state, but only once the work had already been done.
        self.assertEqual(produced, [], "the executor was asked for a result after the cancel")

        events = runtime.events(session.session_id, task_id=task.task_id)
        cancelled_at = max(item.sequence for item in events if item.event_type == "task_cancelled")
        after = [item.event_type for item in events if item.sequence > cancelled_at]
        self.assertNotIn("task_completed", after)
        self.assertNotIn("result_created", after)

    def test_cancelling_while_the_executor_builds_the_result_stops_the_task(self) -> None:
        # The same window one phase later, and with no reviewers at all — so
        # this is not a property of review. `executor.result()` is third-party
        # code and may take arbitrarily long.
        holder: dict[str, object] = {}

        class CancelsWhileProducingResult(DeterministicLocalExecutor):
            def result(self, context):
                cancel_task(holder["runtime"], holder["session"], holder["task"], cause="user")
                return super().result(context)

        runtime = self.started(executors=(CancelsWhileProducingResult(),), reviewers=())
        session = runtime.create_session("Cancel in result")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        holder.update(runtime=runtime, session=session.session_id, task=task.task_id)

        returned = runtime.run_task(session.session_id, task.task_id)
        persisted = runtime.task(session.session_id, task.task_id)
        self.assertEqual(returned.state, "cancelled")
        self.assertEqual(persisted.state, "cancelled")

        events = runtime.events(session.session_id, task_id=task.task_id)
        cancelled_at = max(item.sequence for item in events if item.event_type == "task_cancelled")
        after = [item.event_type for item in events if item.sequence > cancelled_at]
        self.assertNotIn("task_completed", after)

    def test_cancelling_while_consent_is_pending_stops_the_task(self) -> None:
        # The window that matters most in practice, and the last one found. A
        # real Approval Centre *blocks* here, so this is where a task spends most
        # of its wall-clock time and exactly the moment a user is looking at a
        # dialog and most likely to press stop — and the operations that would
        # then run are the ones that needed consent in the first place.
        holder: dict[str, object] = {}

        class CancelsAtTheDialog:
            """Models a person pressing stop instead of answering."""

            def answer(self, request, *, now):
                cancel_task(holder["runtime"], holder["session"], holder["task"], cause="user")
                return "granted"

        runtime = self.started(reviewers=(), consent=CancelsAtTheDialog())
        session = runtime.create_session("Cancel at the dialog")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        holder.update(runtime=runtime, session=session.session_id, task=task.task_id)

        returned = runtime.run_task(session.session_id, task.task_id)
        persisted = runtime.task(session.session_id, task.task_id)
        self.assertEqual(returned.state, "cancelled")
        self.assertEqual(persisted.state, "cancelled")
        # Nothing ran at all — not even the harmless count, because the whole
        # plan was gated behind the consent that was never given.
        self.assertEqual(runtime.broker.invocations, [])

        events = runtime.events(session.session_id, task_id=task.task_id)
        cancelled_at = max(item.sequence for item in events if item.event_type == "task_cancelled")
        after = [item.event_type for item in events if item.sequence > cancelled_at]
        self.assertNotIn("task_completed", after)
        self.assertNotIn("operation_started", after)

    def test_a_cancel_racing_the_runner_does_not_raise(self) -> None:
        # `_emit` reads the stream tip and appends; the session lock is taken
        # inside the append, so a second writer can land in between and the
        # append is correctly refused. From the caller that is a lost race, not
        # an error, and it used to surface as an IntegrityError traceback out of
        # `cancel_task` — so the cancellation simply did not happen.
        import threading

        from companion.clock import SystemClock
        from companion.ids import RandomIds

        for trial in range(6):
            with self.subTest(trial=trial):
                runtime = self.started(reviewers=(), clock=SystemClock())
                runtime.ids = RandomIds()
                session = runtime.create_session(f"Race {trial}")
                task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
                failures: list[str] = []

                def run() -> None:
                    try:
                        runtime.run_task(session.session_id, task.task_id)
                    except Exception as exc:  # noqa: BLE001 - the failure is the finding
                        failures.append(f"runner {type(exc).__name__}: {exc}")

                def cancel() -> None:
                    try:
                        cancel_task(runtime, session.session_id, task.task_id, cause="user")
                    except CompanionError:
                        pass  # "already finished" is a legitimate outcome of the race
                    except Exception as exc:  # noqa: BLE001
                        failures.append(f"canceller {type(exc).__name__}: {exc}")

                runner = threading.Thread(target=run)
                canceller = threading.Thread(target=cancel)
                runner.start()
                canceller.start()
                runner.join()
                canceller.join()
                self.assertEqual(failures, [])

    def test_a_task_taken_terminal_mid_failure_keeps_its_own_diagnostic(self) -> None:
        # `_block`/`_fail` re-read the persisted task, so a cancel landing while
        # the run path was raising handed them a terminal task. Transitioning it
        # raised InvalidTransition out of `run_task`, replacing the real reason
        # (the approval refusal, the capability refusal) with a confusing one
        # about the state machine.
        runtime = self.started(reviewers=())
        session = runtime.create_session("Terminal mid-failure")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        moved = runtime._transition(runtime.task(session.session_id, task.task_id), "classifying")
        runtime.store.save_task(moved)
        cancel_task(runtime, session.session_id, task.task_id, cause="user")

        cancelled = runtime.task(session.session_id, task.task_id)
        self.assertTrue(cancelled.terminal)
        # Neither parking path raises, and neither changes the terminal state.
        self.assertEqual(runtime._block(session, cancelled, "blocked", ("because",)).state, "cancelled")
        self.assertEqual(runtime._fail(session, cancelled, "code", "summary").state, "cancelled")
        self.assertEqual(runtime.task(session.session_id, task.task_id).state, "cancelled")

    def test_a_completed_task_cannot_be_cancelled(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime)
        with self.assertRaisesRegex(CompanionError, "already finished"):
            cancel_task(runtime, session.session_id, task.task_id, cause="user")

    def test_the_executor_is_signalled_once(self) -> None:
        runtime = self.started()
        session, task = self.partway(runtime, through="during_operation")
        executor = runtime.executor("local.deterministic")
        outcome = cancel_task(runtime, session.session_id, task.task_id, cause="timeout")
        self.assertTrue(outcome.executor_signalled)
        self.assertEqual(executor.cancelled_with, "timeout")

    def test_a_cancelled_task_survives_a_restart(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="during_operation")
        cancel_task(first, session.session_id, task.task_id, cause="user")
        first.stop()

        second = self.started()
        reloaded = second.task(session.session_id, task.task_id)
        self.assertEqual(reloaded.state, "cancelled")
        report = recover(second)
        self.assertEqual([item.decision for item in report.decisions], ["intact"])

    def test_a_crash_during_cancellation_completes_the_cancellation(self) -> None:
        first = self.started()
        session, task = self.partway(first, through="during_operation")
        # Enter `cancelling` and stop, as a process killed mid-cancel would.
        entering = first._transition(task, "cancelling", {"cause": "user"})
        entering = replace(entering, cancellation_state="in_progress", cancellation_cause="user")
        first.store.save_task(entering)
        first.stop()

        second = self.started()
        report = recover(second)
        decision = report.decisions[0]
        self.assertEqual(decision.decision, "cancelled")
        self.assertEqual(second.task(session.session_id, task.task_id).state, "cancelled")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

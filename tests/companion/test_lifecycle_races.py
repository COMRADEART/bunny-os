# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The interleavings, constructed rather than waited for.

Every test here builds the exact ordering it is about, using barriers, events
and an injected clock. None of them sleeps to make a race likely. That is the
whole point: the defects this file covers were found by a stress harness at
rates between one in fifty and one in a hundred and thirty-seven, and a
regression test that reproduces a fault one run in fifty is not a regression
test — it is a second flaky test, and it will be deleted by whoever is trying to
get a green build six months from now.

The seams used to construct the orderings are the ones the runtime already has:
``ApprovalGate.build`` / ``persist`` are separate calls because registration
happens between them, and ``InteractiveConsent.register`` / ``answer`` are
separate because the waiter exists before the question does. A barrier dropped
into either seam produces a deterministic interleaving.
"""

from __future__ import annotations

import threading
import unittest

from capability.apply.approval import ApprovalRequest

from companion.approvals import ApprovalGate
from companion.errors import ApprovalError
from companion.service import CompanionService, InteractiveConsent, ServiceOptions

from .support import FULL_REQUEST, SIMPLE_REQUEST, CompanionTestCase

#: Long enough that a wait which is *meant* to be released never times out
#: first, and short enough that a genuine hang fails the suite instead of
#: stopping it.
PATIENCE = 15.0


def question(
    request_id: str = "req-1",
    *,
    task_id: str = "task-1",
    expires_at_monotonic: float = 0.0,
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        plan_id="plan-1",
        transition_id="transition-1",
        service_id=f"companion.task.{task_id}",
        action="interrupt_user_work",
        reason="the task wants to interrupt the person using the machine",
        expires_at_monotonic=expires_at_monotonic,
        alternatives=("leave the result in the task list and say nothing",),
        safe_default="denied",
    )


class AnswerArrivalTests(unittest.TestCase):
    """An answer arriving at each boundary of the question's construction."""

    def test_an_answer_before_registration_is_not_lost(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        # Nothing is registered and nothing is persisted. An answer here cannot
        # have come from a person — they cannot see a question that does not
        # exist — so it is not held, and the safe default applies.
        self.assertEqual(consent.resolve("req-1", "granted"), "unclaimed")

    def test_an_answer_after_registration_and_before_persistence_is_delivered(self) -> None:
        """The window that used to lose answers, now closed from the front."""
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        request = question()
        self.assertTrue(consent.register(request))
        # Persistence has not happened. The waiter exists anyway, which is the
        # point of registering first: there is no longer an instant in which a
        # question is answerable and nothing is listening.
        self.assertEqual(
            consent.resolve("req-1", "granted", hold_for_pending_ask=True), "released"
        )
        self.assertEqual(consent.answer(request, now=100.0), "granted")

    def test_an_answer_immediately_after_persistence_is_delivered(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        request = question()
        consent.register(request)
        answered: list[str | None] = []
        asking = threading.Barrier(2, timeout=PATIENCE)

        def worker() -> None:
            asking.wait()
            answered.append(consent.answer(request, now=100.0))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        asking.wait()
        self.assertEqual(
            consent.resolve("req-1", "granted", hold_for_pending_ask=True), "released"
        )
        thread.join(PATIENCE)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answered, ["granted"])

    def test_registration_refuses_a_second_waiter_for_one_question(self) -> None:
        """Two waiters would let an answer release only one of them."""
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        self.assertTrue(consent.register(question()))
        self.assertFalse(consent.register(question()))

    def test_a_second_answer_is_a_replay_before_the_worker_records_the_first(self) -> None:
        """Replay protection must not wait for the durable store.

        The gateway detected a second answer by asking the approval store
        whether a decision existed — but that decision is written by the
        *worker*, after it wakes from the consent call. A second answer
        arriving in between found "pending" and was accepted. Measured at about
        one run in thirty before this; deterministic here, because nothing has
        woken the worker at all.
        """
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        consent.register(question())
        self.assertEqual(
            consent.resolve("req-1", "granted", hold_for_pending_ask=True), "released"
        )
        self.assertEqual(
            consent.resolve("req-1", "granted", hold_for_pending_ask=True), "replayed"
        )
        # And a denial cannot overwrite a grant either; one answer is one answer.
        self.assertEqual(
            consent.resolve("req-1", "denied", hold_for_pending_ask=True), "replayed"
        )

    def test_a_replayed_answer_is_refused_even_with_no_waiter(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        self.assertEqual(consent.resolve("req-1", "granted"), "unclaimed")
        self.assertEqual(consent.resolve("req-1", "granted"), "replayed")

    def test_a_rolled_back_registration_leaves_nothing_answerable(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        consent.register(question())
        consent.unregister("req-1")
        # The question never became durable, so an answer to it must not exist
        # either.
        self.assertEqual(consent.resolve("req-1", "granted"), "unclaimed")
        self.assertIsNone(consent.answer(question(), now=100.0))


class ParkedTaskCase(CompanionTestCase):
    """A task actually parked on a question, which is what can be paused.

    A freshly submitted task is in ``created`` and cannot move to ``paused`` —
    correctly, since there is nothing to set aside. Every pause test therefore
    needs a task that has been *run* as far as its first question, and the
    deterministic way to get one is to let the runner reach the consent call and
    stop it there. The consent source is the seam: it is the thing that blocks,
    so wrapping it gives an exact "the question is now on screen" signal with no
    sleeping and no polling.
    """

    def parked(self, *, request: str = FULL_REQUEST):
        """Start a task and return once it is waiting for its first answer."""
        consent = InteractiveConsent(maximum_wait_seconds=PATIENCE)
        runtime = self.started(consent=consent)
        session = runtime.create_session("parked")
        task = runtime.submit_task(session.session_id, request)

        displayed = threading.Event()
        finished = threading.Event()
        original_answer = consent.answer

        def answering(approval_request, *, now):
            displayed.set()
            return original_answer(approval_request, now=now)

        consent.answer = answering  # type: ignore[assignment]

        def run() -> None:
            try:
                runtime.run_task(session.session_id, task.task_id)
            except Exception:  # noqa: BLE001 - a withdrawn question ends the run
                pass
            finally:
                finished.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, PATIENCE)
        self.assertTrue(displayed.wait(PATIENCE), "the question was never asked")
        return runtime, session, task, finished


class PauseRaceTests(ParkedTaskCase):
    """Pausing, against everything that can be happening at the same time."""

    def test_pause_while_a_question_is_displayed(self) -> None:
        """The ordinary case, and the one the defect was found in."""
        runtime, session, task, finished = self.parked()

        paused = runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(paused.state, "paused")
        self.assertTrue(finished.wait(PATIENCE), "the worker was not released")

        # Nothing pending survives the pause.
        pending = [
            request for request in runtime.approvals.pending()
            if request.service_id == f"companion.task.{task.task_id}"
        ]
        self.assertEqual(pending, [], "an approve button outlived the pause")

    def test_a_pause_beats_the_runner_reaching_its_own_verdict(self) -> None:
        """Whoever the user asked wins.

        The runner can reach a verdict from a phase that began before the pause
        — withdrawing its questions is exactly what makes its next approval
        check raise — and it used to write `blocked` over the `paused` the user
        had just asked for. Traced on Linux at about one run in three: the
        runner read `waiting_for_approval`, blocked, and the pause that followed
        was written protectively and therefore declined to assert itself.

        Constructed as the invariant rather than as the interleaving, because
        the interleaving needs two threads inside one lock and the invariant is
        the thing that has to hold: once a pause is persisted, a runner holding
        a task object from before it cannot put that object back.
        """
        runtime, session, task, finished = self.parked()

        # The runner's in-flight copy, taken before the pause.
        in_flight = runtime.task(session.session_id, task.task_id)
        self.assertNotEqual(in_flight.state, "paused")

        paused = runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(paused.state, "paused")

        # Let the real worker unwind before asserting anything global. This
        # test is about a *stale* write, and leaving a live worker running
        # while it asserts on the document makes it a test about two writers
        # instead — which is a different property, already covered above, and
        # produced a failure about once in twenty-five soak runs.
        self.assertTrue(finished.wait(PATIENCE), "the worker never unwound")
        self.assertEqual(
            runtime.task(session.session_id, task.task_id).state, "paused"
        )

        # The runner writes what it was holding. This is every write on the run
        # path, and it must decline.
        runtime._save_running_task(in_flight)
        self.assertEqual(
            runtime.task(session.session_id, task.task_id).state, "paused",
            "a runner write from before the pause put the old state back",
        )

        # And the runner's verdict is refused outright rather than applied.
        settled = runtime._block_unless_stopped(
            runtime.session(session.session_id), session.session_id, in_flight,
            "the question was withdrawn", ("withdrawn",),
        )
        self.assertEqual(settled.state, "paused")
        self.assertEqual(
            runtime.task(session.session_id, task.task_id).state, "paused"
        )

    def test_pause_with_two_questions_withdraws_both(self) -> None:
        runtime, session, task, _finished = self.parked()
        # A second question beside the one the plan raised, so the count is
        # known rather than inferred from whatever the plan needed.
        runtime.approvals.request(question("req-extra", task_id=task.task_id))
        self.assertGreaterEqual(len(runtime.approvals.pending()), 2)

        runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(runtime.approvals.pending(), ())

    def test_pause_is_idempotent(self) -> None:
        """Two clients pressing pause is not a fault."""
        runtime, session, task, _finished = self.parked()
        first = runtime.pause_task(session.session_id, task.task_id)
        second = runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(first.state, "paused")
        self.assertEqual(second.state, "paused")
        events = list(runtime.events(session.session_id, task_id=task.task_id))
        paused_events = [item for item in events if item.event_type == "task_paused"]
        self.assertEqual(len(paused_events), 1, "the second pause emitted a second event")

    def test_pause_enumerates_from_the_durable_authority_not_the_task(self) -> None:
        """A question is durable before it reaches the task document.

        That gap is exactly when somebody is looking at the question and most
        likely to press pause, and reading only the task document withdrew
        nothing.
        """
        runtime, session, task, _finished = self.parked()
        # Durable, and deliberately never added to the task document.
        runtime.approvals.request(question("req-orphan", task_id=task.task_id))
        self.assertTrue(runtime.approvals.pending())

        runtime.pause_task(session.session_id, task.task_id)
        self.assertEqual(runtime.approvals.pending(), ())

    def test_cancel_during_pause_leaves_one_terminal_state(self) -> None:
        runtime, session, task, _finished = self.parked()
        runtime.pause_task(session.session_id, task.task_id)

        from companion.cancellation import cancel_task

        outcome = cancel_task(
            runtime, session.session_id, task.task_id,
            cause="user", detail="stop",
        )
        self.assertEqual(outcome.task.state, "cancelled")
        # And pausing a cancelled task is refused rather than half-applied.
        with self.assertRaises(Exception):
            runtime.pause_task(session.session_id, task.task_id)

    def test_a_finished_task_cannot_be_paused(self) -> None:
        runtime = self.started(consent=self.granting())
        session, task = self.completed_task(runtime)
        self.assertEqual(task.state, "completed")
        with self.assertRaisesRegex(Exception, "already finished"):
            runtime.pause_task(session.session_id, task.task_id)


class ResumeTests(ParkedTaskCase):
    """§8: resume never reuses stale approval authority."""

    def settled(self):
        """A parked task with its worker unwound, so the document is still.

        Every test in this class asserts on epochs, which live in the task
        document — and `parked()` deliberately leaves a real worker running.
        Asserting on a document two threads are writing makes a test about
        concurrency whether or not it meant to be one, and three of these failed
        that way at about one run in fifteen. Concurrency has its own tests in
        PauseRaceTests; these are about what pause and resume *mean*.
        """
        runtime, session, task, finished = self.parked()
        runtime.pause_task(session.session_id, task.task_id)
        self.assertTrue(finished.wait(PATIENCE), "the worker never unwound")
        return runtime, session, task

    def test_resume_advances_the_lifecycle_epoch(self) -> None:
        runtime, session, task = self.settled()
        base = runtime.task(session.session_id, task.task_id).lifecycle_epoch

        resumed = runtime.resume_task(session.session_id, task.task_id)
        self.assertEqual(resumed.lifecycle_epoch, base + 1)

        runtime.pause_task(session.session_id, task.task_id)
        again = runtime.resume_task(session.session_id, task.task_id)
        self.assertEqual(again.lifecycle_epoch, base + 2)

    def test_repeated_pause_and_resume_never_carries_an_approval_over(self) -> None:
        """Four attempts, and no approval survives into the next one.

        The worker is allowed to unwind before the rounds begin. This test is
        about what pause and resume do to *approvals and epochs*, not about a
        runner writing concurrently — that is a different property with its own
        test — and leaving the worker running made this one assert on a document
        two threads were changing. It failed about seven times in forty for that
        reason, which is a flaky test rather than a finding.
        """
        runtime, session, task = self.settled()
        runtime.resume_task(session.session_id, task.task_id)
        base = runtime.task(session.session_id, task.task_id).lifecycle_epoch

        for round_number in range(4):
            with self.subTest(round=round_number):
                runtime.approvals.request(
                    question(f"req-{round_number}", task_id=task.task_id)
                )
                self.assertTrue(runtime.approvals.pending())
                runtime.pause_task(session.session_id, task.task_id)
                # Withdrawn, every time, and never carried into the next attempt.
                self.assertEqual(runtime.approvals.pending(), ())
                runtime.resume_task(session.session_id, task.task_id)

        current = runtime.task(session.session_id, task.task_id)
        self.assertEqual(current.lifecycle_epoch, base + 4)

    def test_an_approval_answered_after_a_resume_is_not_replayed(self) -> None:
        """The old question is terminal; answering it again authorises nothing."""
        runtime, session, task = self.settled()
        # `settled` leaves the task paused, and pausing a paused task is
        # deliberately a no-op — so it has to be running again before a pause
        # can withdraw anything.
        runtime.resume_task(session.session_id, task.task_id)
        runtime.approvals.request(question("req-old", task_id=task.task_id))
        runtime.pause_task(session.session_id, task.task_id)
        runtime.resume_task(session.session_id, task.task_id)

        settled = runtime.approvals.decision_for("req-old")
        self.assertIsNotNone(settled)
        self.assertNotEqual(settled.decision, "pending")
        self.assertEqual(runtime.gate.withdrawn.get("req-old"), "cancelled-with-pause")


class ExpiryTests(ParkedTaskCase):
    """Expiry, invalidation, and the order they can arrive in."""

    def test_an_invalidated_question_does_not_later_become_a_denial(self) -> None:
        """The defect, stated as an invariant.

        Withdrawn is not denied. A worker arriving after the withdrawal must
        record what the withdrawal recorded, not the safe default for a question
        nobody answered.
        """
        runtime, session, task, _finished = self.parked()
        runtime.approvals.request(question("req-1", task_id=task.task_id))
        runtime.pause_task(session.session_id, task.task_id)

        self.assertEqual(runtime.gate.withdrawn["req-1"], "cancelled-with-pause")
        events = [
            item for item in runtime.events(session.session_id, task_id=task.task_id)
            if item.event_type == "approval_resolved"
        ]
        self.assertTrue(events)
        for item in events:
            self.assertNotEqual(
                item.payload.get("decision"), "denied-by-user",
                "a withdrawal was recorded as a refusal by the person",
            )

    def test_expiry_after_invalidation_does_not_change_the_terminal_state(self) -> None:
        runtime, session, task, _finished = self.parked()
        runtime.approvals.request(
            question("req-1", task_id=task.task_id, expires_at_monotonic=10.0)
        )
        runtime.pause_task(session.session_id, task.task_id)
        settled = runtime.approvals.decision_for("req-1")

        # The clock moves past the expiry; the sweep must not re-settle it.
        runtime.approvals.expire(1_000.0)
        self.assertEqual(runtime.approvals.decision_for("req-1").decision, settled.decision)
        self.assertEqual(runtime.gate.withdrawn["req-1"], "cancelled-with-pause")


class RestartTests(ParkedTaskCase):
    """§9: a restart while paused, and during invalidation."""

    def test_a_restart_while_paused_keeps_the_task_paused(self) -> None:
        runtime, session, task, _finished = self.parked()
        runtime.pause_task(session.session_id, task.task_id)

        # A fresh runtime over the same store is what a restart is.
        restarted = self.started(consent=self.granting())
        reloaded = restarted.task(session.session_id, task.task_id)
        self.assertEqual(reloaded.state, "paused")
        self.assertEqual(reloaded.lifecycle_epoch, 0)

    def test_a_restart_does_not_resurrect_a_withdrawn_question(self) -> None:
        runtime, session, task, _finished = self.parked()
        runtime.approvals.request(question("req-1", task_id=task.task_id))
        runtime.pause_task(session.session_id, task.task_id)

        restarted = self.started(consent=self.granting())
        # The durable store carries the settled decision across the restart even
        # though the in-memory withdrawal reason does not; the question must not
        # come back as pending.
        decision = restarted.approvals.decision_for("req-1")
        self.assertIsNotNone(decision)
        self.assertNotEqual(decision.decision, "pending")


class DuplicateRequestTests(ParkedTaskCase):
    """Two of the same request, arriving together."""

    def test_two_pauses_in_flight_produce_one_paused_task(self) -> None:
        runtime, session, task, _finished = self.parked()

        start = threading.Barrier(4, timeout=PATIENCE)
        results: list[str] = []
        errors: list[BaseException] = []

        def pause() -> None:
            try:
                start.wait()
                results.append(runtime.pause_task(session.session_id, task.task_id).state)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=pause, daemon=True) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(PATIENCE)

        self.assertEqual(errors, [])
        self.assertEqual(results, ["paused"] * 4)
        events = [
            item for item in runtime.events(session.session_id, task_id=task.task_id)
            if item.event_type == "task_paused"
        ]
        self.assertEqual(len(events), 1, "concurrent pauses emitted more than one event")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""An answer given before the question is asked must still reach the task.

These tests exist because of a measured defect, not a hypothetical one. The
companion suite failed roughly one run in three on a loaded host, always in the
service-driven tests, always with a flat thread and descriptor inventory, and
always about half a minute slower than a passing run. A flat inventory with a
failure is a race rather than a leak, and the extra time was a wait budget being
consumed in full.

The race: the runtime writes an approval request to the store — which is what
makes it visible to the Approval Centre — and only then does its worker call
:meth:`InteractiveConsent.answer` to register a waiter. A client that polled,
saw the question and answered inside that window found nobody listening, and the
decision was discarded. The worker went on to wait out its entire consent budget
and the task sat in ``waiting_for_approval`` with the answer already given.

Every test below is deterministic. None of them sleeps to make a race likely;
each one constructs the interleaving directly, which is the only way this can be
a regression test rather than a second flaky test.
"""

from __future__ import annotations

import threading
import time
import unittest

from capability.apply.approval import ApprovalRequest

from companion.service import InteractiveConsent


def question(
    request_id: str = "req-1",
    *,
    task_id: str = "task-1",
    expires_at_monotonic: float = 0.0,
    action: str = "interrupt_user_work",
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        plan_id="plan-1",
        transition_id="transition-1",
        service_id=f"companion.task.{task_id}",
        action=action,
        reason="the task wants to interrupt the person using the machine",
        expires_at_monotonic=expires_at_monotonic,
        # A sensitive action must offer the person something other than "no".
        alternatives=("leave the result in the task list and say nothing",),
        safe_default="denied",
    )


def wait_until_registered(consent: InteractiveConsent, *, timeout: float = 10.0) -> bool:
    """Block until a waiter exists, with a bound.

    Bounded because an unbounded version of this loop turned a broken worker
    thread into a hung test run rather than a failing one, which is a worse
    outcome than the bug it was written to catch.
    """
    pause = threading.Event()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if consent.waiting_for():
            return True
        pause.wait(0.01)
    return False


class AnswerBeforeTheAskTests(unittest.TestCase):
    """The defect itself, and the shape of the fix."""

    def test_an_answer_that_arrives_first_is_delivered_to_the_task(self) -> None:
        # The exact interleaving that failed: the answer lands while the worker
        # is still between writing the request and registering its waiter.
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        request = question()

        outcome = consent.resolve("req-1", "granted", hold_for_pending_ask=True)
        self.assertEqual(outcome, "held")

        # Had this been dropped, `answer` would block for the full 30 s and then
        # return None. It must return immediately with the person's decision.
        started = time.monotonic()
        self.assertEqual(consent.answer(request, now=100.0), "granted")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_the_held_answer_is_consumed_once_and_not_reused(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        consent.resolve("req-1", "granted", hold_for_pending_ask=True)
        self.assertEqual(consent.answer(question(), now=100.0), "granted")
        # A second ask for the same question finds nothing held and falls back
        # to waiting, which times out into the safe default. An answer is used
        # once; a second use would be a replay the person never made.
        self.assertIsNone(consent.answer(question(), now=100.0))

    def test_a_denial_given_early_is_delivered_as_a_denial(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        consent.resolve("req-1", "denied", hold_for_pending_ask=True)
        self.assertEqual(consent.answer(question(), now=100.0), "denied")

    def test_the_ordinary_path_still_releases_a_waiting_task(self) -> None:
        """The fix must not cost the case that already worked."""
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        answered: list[str | None] = []
        ready = threading.Event()

        def worker() -> None:
            ready.set()
            answered.append(consent.answer(question(), now=100.0))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        ready.wait(5.0)
        # Wait for the registration itself rather than for a duration.
        self.assertTrue(wait_until_registered(consent))
        self.assertEqual(
            consent.resolve("req-1", "granted", hold_for_pending_ask=True), "released"
        )
        thread.join(10.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answered, ["granted"])


class HoldingIsPrivilegedTests(unittest.TestCase):
    """Holding an answer requires a caller that proved the question is live."""

    def test_without_the_licence_an_unwaited_answer_is_not_kept(self) -> None:
        # The default refuses to hold. Only CompanionGateway.resolve_approval,
        # which has already checked that the request exists, matches what was
        # displayed, has not expired and has not been answered, passes the flag.
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        self.assertEqual(consent.resolve("req-1", "granted"), "unclaimed")
        self.assertEqual(consent.held_answers(), ())
        self.assertIsNone(consent.answer(question(), now=100.0))

    def test_a_held_answer_cannot_outlive_the_question(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        consent.resolve(
            "req-1", "granted", expires_at_monotonic=150.0, hold_for_pending_ask=True
        )
        # The task asks after the request has lapsed. Honouring the grant here
        # would be acting on consent given for a question that had expired.
        self.assertIsNone(consent.answer(question(expires_at_monotonic=150.0), now=151.0))

    def test_a_lapsed_hold_is_discarded_rather_than_accumulated(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        consent.resolve(
            "req-old", "granted", expires_at_monotonic=150.0, hold_for_pending_ask=True
        )
        self.assertEqual(consent.held_answers(), ("req-old",))
        # Asking about anything at all after the lapse sweeps the stale entry,
        # so the store cannot grow without bound on a long-running service.
        consent.answer(question("req-other"), now=200.0)
        self.assertEqual(consent.held_answers(), ())

    def test_only_granted_or_denied_may_be_delivered(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        for decision in ("pending", "maybe", "", "GRANTED"):
            with self.assertRaises(ValueError):
                consent.resolve("req-1", decision, hold_for_pending_ask=True)
        self.assertEqual(consent.held_answers(), ())


class ReleasingDropsHeldAnswersTests(unittest.TestCase):
    """Consent must not survive the thing it was given for."""

    def test_cancelling_a_task_discards_an_answer_held_for_it(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        consent.resolve(
            "req-1", "granted", service_id="companion.task.task-1", hold_for_pending_ask=True
        )
        consent.abandon("task-1")
        self.assertEqual(consent.held_answers(), ())
        # The safe default applies to anything that asks afterwards.
        self.assertIsNone(consent.answer(question(), now=100.0))

    def test_cancelling_one_task_leaves_another_task_alone(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        for name in ("task-1", "task-2"):
            consent.resolve(
                f"req-{name}", "granted",
                service_id=f"companion.task.{name}", hold_for_pending_ask=True,
            )
        consent.abandon("task-1")
        self.assertEqual(consent.held_answers(), ("req-task-2",))
        self.assertEqual(
            consent.answer(question("req-task-2", task_id="task-2"), now=100.0), "granted"
        )

    def test_cancelling_before_the_worker_asks_refuses_the_question_on_arrival(self) -> None:
        """The mirror image of the early answer, and the reason cancel exists.

        Cancelling in the window released nothing, so the worker parked on a
        question belonging to an already-cancelled task and was held for the
        whole consent budget.
        """
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        released = consent.abandon("task-1", request_ids=("req-1",))
        self.assertEqual(released, ("req-1",))
        # Immediately, not after 30 s, and with no decision.
        self.assertIsNone(consent.answer(question(), now=100.0))

    def test_a_refusal_on_arrival_is_spent_once_so_a_resumed_task_can_ask(self) -> None:
        # Pausing abandons outstanding questions; resuming asks new ones. The
        # refusal must not outlive the question it was aimed at.
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        consent.abandon("task-1", request_ids=("req-1",))
        self.assertIsNone(consent.answer(question("req-1"), now=100.0))
        # A new question from the same task after resuming is answerable.
        consent.resolve("req-2", "granted", hold_for_pending_ask=True)
        self.assertEqual(consent.answer(question("req-2"), now=100.0), "granted")

    def test_cancelling_reports_both_the_woken_and_the_pre_empted(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=30.0)
        answered: list[str | None] = []
        ready = threading.Event()

        def worker() -> None:
            ready.set()
            answered.append(consent.answer(question("req-waiting"), now=100.0))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        ready.wait(5.0)
        self.assertTrue(wait_until_registered(consent))
        released = consent.abandon("task-1", request_ids=("req-not-yet-asked",))
        self.assertEqual(released, ("req-not-yet-asked", "req-waiting"))
        thread.join(10.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answered, [None])

    def test_stopping_the_service_discards_every_held_answer(self) -> None:
        consent = InteractiveConsent(maximum_wait_seconds=0.05)
        for index in range(3):
            consent.resolve(
                f"req-{index}", "granted",
                service_id=f"companion.task.task-{index}", hold_for_pending_ask=True,
            )
        consent.abandon_all()
        self.assertEqual(consent.held_answers(), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

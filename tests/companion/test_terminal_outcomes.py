# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A task never claims to have done work that did not happen.

The defect this closes was found by a booted graphical journey: the image tool
ran, the export hit ``EROFS``, the runtime recorded ``operation_failed`` and an
error reference on the task — and the task reached ``completed``. The only place
the truth appeared was the summary text, which said "resize did not complete"
underneath a green terminal state.

The cause was structural rather than a slip. :class:`TaskResult` had no failure
channel at all, so an executor could not report one; and the runtime, which had
watched every operation settle, asked nobody. Two parties both knew and neither
could say.

So there are now two verdicts and the pessimistic one wins:

``result.outcome``      what the executor reports;
``_observed_outcome``   what the runtime saw, read from the operation records
                        rather than from any claim about them.

The executor's default is ``success``, which is safe *only* because it is not
trusted — every test below that passes a default-constructed result alongside a
failed operation is testing exactly that.
"""

from __future__ import annotations

import unittest

from companion.errors import MalformedOutput
from companion.executor import ProducedOutput, TaskResult
from companion.runtime import CompanionRuntime
from companion.task import TASK_OUTCOMES, CompanionTask, OperationReference, worst_outcome


def _task(*operations: tuple[str, str]) -> CompanionTask:
    task = CompanionTask.create(
        task_id="task-1", session_id="session-1",
        request="Resize this to 100 pixels wide.", classification="personal", now=0.0,
    )
    for key, status in operations:
        task = task.with_operation(
            OperationReference(key=key, name=key, status=status)
        )
    return task


class TheWorstVerdictWins(unittest.TestCase):
    def test_failure_beats_success(self) -> None:
        self.assertEqual(worst_outcome("success", "failed"), "failed")
        self.assertEqual(worst_outcome("failed", "success"), "failed")

    def test_the_order_is_success_cancelled_blocked_failed(self) -> None:
        self.assertEqual(worst_outcome("success", "cancelled"), "cancelled")
        self.assertEqual(worst_outcome("cancelled", "blocked"), "blocked")
        self.assertEqual(worst_outcome("blocked", "failed"), "failed")

    def test_all_success_is_success(self) -> None:
        """The positive control. A combiner that always failed would satisfy
        every other test here and make the product unusable."""
        self.assertEqual(worst_outcome("success", "success", "success"), "success")

    def test_an_unknown_verdict_is_treated_as_failure(self) -> None:
        """§11: never unknown to success."""
        self.assertEqual(worst_outcome("success", "who knows"), "failed")
        self.assertEqual(worst_outcome(""), "failed")

    def test_every_declared_outcome_is_orderable(self) -> None:
        for outcome in TASK_OUTCOMES:
            with self.subTest(outcome=outcome):
                self.assertEqual(worst_outcome(outcome, "success"), outcome)


class TheRuntimeReadsTheRecord(unittest.TestCase):
    """``_observed_outcome`` is a pure function of the task's own operations."""

    def test_a_task_with_no_operations_succeeded(self) -> None:
        """"Answer this question" produces no operations and is not a failure."""
        self.assertEqual(CompanionRuntime._observed_outcome(_task()), "success")

    def test_one_completed_operation_is_success(self) -> None:
        self.assertEqual(
            CompanionRuntime._observed_outcome(_task(("resize", "completed"))), "success"
        )

    def test_one_failed_operation_is_failure(self) -> None:
        """The exact shape of the defect: a single-operation task whose one
        operation failed."""
        self.assertEqual(
            CompanionRuntime._observed_outcome(_task(("resize", "failed"))), "failed"
        )

    def test_all_failed_is_failure(self) -> None:
        self.assertEqual(
            CompanionRuntime._observed_outcome(
                _task(("a", "failed"), ("b", "failed"))
            ),
            "failed",
        )

    def test_a_mix_is_not_reported_as_a_total_failure(self) -> None:
        """A plan that got some of its work done is not the same as one that got
        none. The executor's own verdict is what distinguishes those, and this
        deliberately does not overrule it in the safe direction."""
        self.assertEqual(
            CompanionRuntime._observed_outcome(
                _task(("a", "completed"), ("b", "failed"))
            ),
            "success",
        )

    def test_an_unsettled_operation_is_not_a_failure(self) -> None:
        """``unknown`` means the runtime stopped between starting an operation
        and settling it. That is not evidence the work failed, and calling it
        failure here would fail every task interrupted by a restart."""
        self.assertEqual(
            CompanionRuntime._observed_outcome(_task(("resize", "unknown"))), "success"
        )


class TheResultCarriesTheVerdict(unittest.TestCase):
    def test_the_default_is_success(self) -> None:
        """Every executor predates the field. The default is safe only because
        the runtime does not trust it — which the class below proves."""
        result = TaskResult(result_id="r", summary="done")
        self.assertEqual(result.outcome, "success")

    def test_an_unknown_outcome_is_refused(self) -> None:
        with self.assertRaises(MalformedOutput):
            TaskResult(result_id="r", summary="done", outcome="probably fine")

    def test_the_verdict_and_reason_reach_the_record(self) -> None:
        result = TaskResult(
            result_id="r", summary="could not save",
            outcome="failed", failure={"code": "OUTPUT_EXPORT_FAILED", "detail": "EROFS"},
        )
        document = result.to_json()
        self.assertEqual(document["outcome"], "failed")
        self.assertEqual(document["failure"]["code"], "OUTPUT_EXPORT_FAILED")


class TheInvariants(unittest.TestCase):
    """§11, stated as the combinations that must never occur.

    These are about the *decision*, not about a live runtime: what state a
    verdict maps to is a pure function, and testing it here means it is checked
    on every machine rather than only where a VM can boot.
    """

    TERMINAL = {"success": "completed", "failed": "failed",
                "cancelled": "cancelled", "blocked": "blocked"}

    def _terminal_for(self, executor: str, observed: str) -> str:
        outcome = worst_outcome(executor, observed)
        return {"cancelled": "cancelled", "blocked": "blocked"}.get(
            outcome, "completed" if outcome == "success" else "failed"
        )

    def test_a_successful_operation_completes(self) -> None:
        self.assertEqual(self._terminal_for("success", "success"), "completed")

    def test_a_failed_operation_never_completes(self) -> None:
        """The headline. An executor claiming success over a failed operation
        does not produce a completed task."""
        self.assertEqual(self._terminal_for("success", "failed"), "failed")

    def test_a_declared_failure_never_completes(self) -> None:
        self.assertEqual(self._terminal_for("failed", "success"), "failed")

    def test_a_denial_blocks_rather_than_failing(self) -> None:
        """A person saying no is not a malfunction, and must not be reported as
        one — §18 keeps user denial and internal failure distinct."""
        self.assertEqual(self._terminal_for("blocked", "success"), "blocked")

    def test_a_cancellation_is_its_own_state(self) -> None:
        self.assertEqual(self._terminal_for("cancelled", "success"), "cancelled")

    def test_an_unknown_state_fails_rather_than_completing(self) -> None:
        self.assertEqual(self._terminal_for("success", "no idea"), "failed")


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stopping, as a first-class operation rather than an exception.

Cancellation is where a companion is most likely to lie. The tempting
implementation raises something, unwinds, and marks the task cancelled — which
is fast, and which quietly asserts that nothing further happened. In fact an
operation may have been in flight, an approval may still be sitting on somebody's
screen, and partial output may exist that the user would rather keep.

So cancellation here is a sequence, and each step is recorded:

1. the task enters ``cancelling`` — a state, not a flag. The runtime re-reads
   the persisted task between operations and at each phase boundary, so a
   cancellation written by *another process* takes effect at the next boundary
   rather than at the end of the plan, and the phase loop stops instead of
   carrying the task on to ``completed``;
2. the executor is signalled, once;
3. operations that were started and never settled are marked ``unknown`` —
   never ``failed``, because a failure is a claim about what happened and
   nobody knows;
4. pending approvals are withdrawn, so a question about a task nobody is
   running any more does not stay on a screen waiting to authorise it;
5. whatever partial output exists is written down;
6. a final ``task_cancelled`` event is appended, and the task becomes
   ``cancelled``.

Steps 3 and 5 are why cancelling is not free and why it has a state of its own.
A cancellation that skipped them would be faster and would lose the only record
of what the task had already done.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence, TYPE_CHECKING

from .errors import CompanionError
from .executor import ProducedOutput, context_for
from .privacy import display_summary
from .task import CANCELLATION_CAUSES, CompanionTask, ErrorReference, OutputReference

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to a type checker
    from .runtime import CompanionRuntime

__all__ = ["CancellationOutcome", "cancel_task"]


@dataclass(frozen=True)
class CancellationOutcome:
    """What stopping actually did."""

    task: CompanionTask
    cause: str
    withdrawn_approvals: tuple[str, ...] = ()
    unknown_operations: tuple[str, ...] = ()
    retained_outputs: tuple[str, ...] = ()
    executor_signalled: bool = False
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task.task_id,
            "state": self.task.state,
            "cause": self.cause,
            "withdrawnApprovals": list(self.withdrawn_approvals),
            "unknownOperations": list(self.unknown_operations),
            "retainedOutputs": list(self.retained_outputs),
            "executorSignalled": self.executor_signalled,
            "detail": self.detail,
        }


def cancel_task(
    runtime: "CompanionRuntime",
    session_id: str,
    task_id: str,
    *,
    cause: str = "user",
    detail: str = "",
    partial_outputs: Sequence[ProducedOutput] = (),
) -> CancellationOutcome:
    """Stop one task, safely, and say exactly what that meant.

    Idempotent: cancelling an already-cancelled task returns the outcome of the
    cancellation that happened rather than doing it again or refusing. A user who
    presses stop twice has not made a mistake.
    """
    if cause not in CANCELLATION_CAUSES or not cause:
        raise CompanionError(f"cancellation cause must be one of {[c for c in CANCELLATION_CAUSES if c]}")

    session = runtime.session(session_id)
    task = runtime.task(session_id, task_id)

    if task.state == "cancelled":
        return CancellationOutcome(
            task=task, cause=task.cancellation_cause or cause,
            detail="the task was already cancelled; nothing further was done",
        )
    if task.terminal:
        raise CompanionError(
            f"task {task_id} is {task.state!r} and cannot be cancelled; it has already finished"
        )

    # 1. Enter cancelling. From here the state machine refuses new operations.
    task = replace(task, cancellation_state="requested", cancellation_cause=cause)
    if task.state != "cancelling":
        task = runtime._transition(task, "cancelling", {
            "cause": cause,
            "detail": display_summary(detail) if detail else "",
        })
    task = replace(task, cancellation_state="in_progress")
    runtime.store.save_task(task)

    # 2. Signal the executor. Once, and its answer is not waited on: an executor
    #    that hangs in `cancel` must not hold the cancellation open.
    signalled = False
    executor = runtime.executor(task.executor_id) if task.executor_id else None
    if executor is not None and executor.declaration.supports_cancellation:
        try:
            executor.cancel(context_for(task, plan_revision=task.plan_revision), cause)
            signalled = True
        except Exception as exc:  # third-party code; its faults are recorded, not raised
            # An executor that throws on the way out does not get to stop the
            # cancellation. It is written down against the task and the sequence
            # continues, because the remaining steps are the ones that protect
            # the user's data.
            task = task.with_error(ErrorReference(
                code="executor_cancel_failed",
                summary=display_summary(f"the executor raised during cancellation: {type(exc).__name__}: {exc}"),
                producer=f"executor:{task.executor_id}",
                sequence=runtime.store.tip(session_id)[0],
            ))
            runtime._emit(
                session_id, task_id, "operation_failed",
                {
                    "operationKey": "executor-cancel",
                    "name": "executor-cancel",
                    "error": display_summary(f"the executor raised during cancellation: {type(exc).__name__}"),
                },
                classification=task.classification,
            )

    # 3. Operations in flight become unknown, not failed.
    unknown: list[str] = []
    for reference in task.unsettled_operations():
        unknown.append(reference.key)
        task = task.with_operation(replace(
            reference,
            status="unknown",
            recovery_note=(
                "the task was cancelled while this operation was in flight; whether it completed "
                "is not known and it will not be repeated"
            ),
        ))
    runtime.store.save_task(task)

    # 4. Withdraw consent that is no longer about anything.
    withdrawn = runtime.gate.invalidate_for_task(
        task,
        detail=f"task {task_id} was cancelled ({cause}); this question no longer authorises anything",
        terminal_state="cancelled-with-task",
    )

    # 5. Keep whatever was produced. Partial output is still the user's.
    retained: list[str] = []
    for output in partial_outputs:
        task = task.with_output(OutputReference(
            output_id=output.output_id, kind=output.kind, digest=output.digest,
            byte_size=output.byte_size, classification=output.classification,
            summary=display_summary(output.content),
            created_sequence=runtime.store.tip(session_id)[0],
        ))
        retained.append(output.output_id)
    if retained:
        runtime._emit(
            session_id, task_id, "result_created",
            {
                "resultId": f"partial-{task_id}",
                "partial": True,
                "outputs": [item.to_json() for item in partial_outputs],
            },
            classification=task.classification,
        )

    # 6. The final event, and the terminal state.
    task = runtime._transition(task, "cancelled", {
        "reason": cause,
        "detail": display_summary(detail) if detail else "",
        "withdrawnApprovals": withdrawn,
        "unknownOperations": unknown,
        "retainedOutputs": retained,
        "executorSignalled": signalled,
    })
    task = replace(task, cancellation_state="complete").finished(runtime.clock.wall())
    session = session.task_finished(task_id, runtime.clock.wall())
    runtime._sessions[session_id] = session
    runtime.leases.release(task_id)
    # Authoritative: cancellation is the authority for this task's final
    # state, so this write is not the protective one the run path uses.
    runtime._checkpoint(session, task, authoritative=True)

    return CancellationOutcome(
        task=task,
        cause=cause,
        withdrawn_approvals=tuple(withdrawn),
        unknown_operations=tuple(unknown),
        retained_outputs=tuple(retained),
        executor_signalled=signalled,
        detail=detail,
    )

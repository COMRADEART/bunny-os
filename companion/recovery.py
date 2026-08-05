# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What to do about a task the machine was in the middle of when it stopped.

The hard case is one operation wide. A task has an ``operation_started`` event
with the key ``op-1f3c…`` and no ``operation_completed`` for it. Did the work
happen? The record cannot say. The process died somewhere between writing the
first event and writing the second, and the operation itself sits in that gap.

The wrong answer is to retry, and it is wrong in a way that is easy to miss
because it is right for idempotent work and catastrophic for the rest. The
rule this module implements is the brief's:

    Do not repeat an operation merely because its completion event was missing.

An operation in that state becomes ``unknown``. Recovery does not perform it,
does not mark it failed, and does not hide it. It goes back to the executor at
the next planning round as a fact — "this may or may not have happened" — in
:attr:`companion.executor.TaskContext.unknown_operation_keys`, and the runtime
*refuses* to perform any operation whose key is in that set, recording the
refusal and its reason in the stream. So the guarantee does not rest on the
executor cooperating.

That is only possible because :func:`companion.ids.operation_key` identifies the
**act** — task, name, tool, arguments, destination — rather than its position in
a plan. An earlier version keyed the position, which meant every replan minted
fresh keys, nothing ever matched, and the skip was unreachable: the runtime
re-ran uncertain work while the ledger beside it said it would not. Keying the
act is what makes this paragraph true rather than aspirational.

The rest of the sequence follows §15 in order: load, verify integrity, find
incomplete tasks, check the executor still exists, inspect pending operations,
invalidate stale approvals, resume only when it is supported and safe, otherwise
park, and record the decision as an event either way. There is no path through
this module that reaches a terminal state without writing down why.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence, TYPE_CHECKING

from .errors import IntegrityError, SchemaError, StoreError
from .events import TaskEvent
from .session import CompanionSession
from .states import TERMINAL_STATES
from .store import StoreReport
from .task import CompanionTask, OperationReference

if TYPE_CHECKING:  # pragma: no cover
    from .runtime import CompanionRuntime

__all__ = ["RecoveryDecision", "RecoveryReport", "recover", "rebuild_task_from_events"]

#: Decisions recovery may reach about one task. ``resumed`` never means "carried
#: on from where it was": it means the task was returned to planning with what is
#: known, which is the only resumption that is safe without executor support.
RECOVERY_DECISIONS = ("intact", "resumed", "paused", "blocked", "failed", "cancelled")


@dataclass(frozen=True)
class RecoveryDecision:
    """What recovery concluded about one task, and why."""

    task_id: str
    session_id: str
    detected_state: str
    decision: str
    reasons: tuple[str, ...] = ()
    unknown_operations: tuple[str, ...] = ()
    invalidated_approvals: tuple[str, ...] = ()
    executor_present: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "detectedState": self.detected_state,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "unknownOperations": list(self.unknown_operations),
            "invalidatedApprovals": list(self.invalidated_approvals),
            "executorPresent": self.executor_present,
        }


@dataclass(frozen=True)
class RecoveryReport:
    """Everything one recovery pass found and did."""

    sessions: tuple[str, ...] = ()
    decisions: tuple[RecoveryDecision, ...] = ()
    store_reports: tuple[StoreReport, ...] = ()
    warnings: tuple[str, ...] = ()
    unreadable_sessions: tuple[tuple[str, str], ...] = ()

    @property
    def healthy(self) -> bool:
        return not self.unreadable_sessions

    def to_json(self) -> dict[str, Any]:
        return {
            "sessions": list(self.sessions),
            "decisions": [item.to_json() for item in self.decisions],
            "storeReports": [item.to_json() for item in self.store_reports],
            "warnings": list(self.warnings),
            "unreadableSessions": [
                {"sessionId": name, "problem": problem} for name, problem in self.unreadable_sessions
            ],
            "healthy": self.healthy,
        }


def rebuild_task_from_events(
    task_id: str,
    session_id: str,
    events: Sequence[TaskEvent],
    *,
    fallback: CompanionTask | None = None,
) -> CompanionTask | None:
    """Reconstruct what the stream says about a task's operations.

    Only the operation ledger and the terminal facts are rebuilt, not the whole
    document. The stream is authoritative about *what happened*; the projection
    is the more convenient place to read the request text and the policy, and
    those do not change after submission. Rebuilding everything would mean
    reimplementing the whole runtime as a fold, and a second implementation of
    the lifecycle is a second thing that can disagree with the first.
    """
    if fallback is None:
        return None
    task = fallback
    started: dict[str, str] = {}
    settled: dict[str, str] = {}
    for event in events:
        if event.task_id != task_id:
            continue
        key = str(event.payload.get("operationKey", ""))
        if not key:
            continue
        if event.event_type == "operation_started":
            started[key] = str(event.payload.get("name", ""))
        elif event.event_type == "operation_completed":
            settled[key] = "completed"
        elif event.event_type == "operation_failed":
            settled[key] = "failed"

    for key, name in started.items():
        status = settled.get(key, "unknown")
        existing = task.operation(key)
        note = ""
        if status == "unknown":
            note = (
                "the runtime stopped after this operation began and before anything settled it; "
                "whether it happened is not known, so it was not repeated"
            )
        task = task.with_operation(OperationReference(
            key=key,
            name=name or (existing.name if existing is not None else ""),
            status=status,
            started_sequence=existing.started_sequence if existing is not None else 0,
            settled_sequence=existing.settled_sequence if existing is not None else 0,
            recovery_note=note or (existing.recovery_note if existing is not None else ""),
        ))
    return task


def _session_state(runtime: "CompanionRuntime", session_id: str) -> tuple[CompanionSession | None, StoreReport]:
    report = runtime.store.validate(session_id)
    session = runtime.store.load_session(session_id)
    return session, report


def recover(runtime: "CompanionRuntime") -> RecoveryReport:
    """Run one recovery pass over every session in the store.

    Called at start-up, and safe to call again: a task already parked by a
    previous pass is reported ``intact`` rather than re-decided, so recovery
    running twice does not walk a task further down the lifecycle than the
    evidence supports.
    """
    decisions: list[RecoveryDecision] = []
    reports: list[StoreReport] = []
    warnings: list[str] = list(runtime.approvals.warnings)
    unreadable: list[tuple[str, str]] = []
    session_ids: list[str] = []

    for session_id in runtime.store.session_ids():
        session_ids.append(session_id)
        try:
            session, report = _session_state(runtime, session_id)
            if session is None:
                unreadable.append((session_id, "the session projection is missing and was not invented"))
                continue
            # Read inside the guard. `validate` turns an unreadable chain into a
            # report rather than an exception, so a session that failed to
            # verify would otherwise reach this line and raise here instead —
            # taking every session after it down with it.
            events = runtime.store.read_events(session_id)
        except (IntegrityError, SchemaError, StoreError) as exc:
            # A session whose chain will not verify is not opened, not repaired
            # and not partially replayed. It is reported, and every other
            # session is still recovered — one damaged file must not cost a user
            # the rest of their history.
            unreadable.append((session_id, str(exc)))
            continue

        reports.append(report)
        warnings.extend(report.warnings)
        if not report.consistent:
            warnings.extend(f"{session_id}: {problem}" for problem in report.problems)

        runtime._sessions[session_id] = session

        for task in runtime.store.tasks(session_id):
            decisions.append(_recover_task(runtime, session, task, events))

        # Bring the projection back in line with the stream. The stream is
        # authoritative; this is the write that makes the cheap read agree
        # with it again.
        runtime._checkpoint(runtime._sessions[session_id])

    return RecoveryReport(
        sessions=tuple(session_ids),
        decisions=tuple(decisions),
        store_reports=tuple(reports),
        warnings=tuple(dict.fromkeys(warnings)),
        unreadable_sessions=tuple(unreadable),
    )


def _recover_task(
    runtime: "CompanionRuntime",
    session: CompanionSession,
    stored: CompanionTask,
    events: Sequence[TaskEvent],
) -> RecoveryDecision:
    detected = stored.state
    if detected in TERMINAL_STATES:
        return RecoveryDecision(
            task_id=stored.task_id, session_id=session.session_id,
            detected_state=detected, decision="intact",
            reasons=(f"the task is {detected} and needs no recovery",),
        )
    if detected in ("blocked", "paused"):
        return RecoveryDecision(
            task_id=stored.task_id, session_id=session.session_id,
            detected_state=detected, decision="intact",
            reasons=(f"the task was already parked in {detected} and was left there",),
        )

    own = [event for event in events if event.task_id == stored.task_id]
    if own and own[-1].event_type == "recovery_completed":
        # A previous pass already decided about this task and nothing has
        # happened since. Deciding again would append a second recovery to the
        # record for the same crash, and a history that says a task was
        # recovered four times because somebody ran the command four times is a
        # history that misleads.
        return RecoveryDecision(
            task_id=stored.task_id, session_id=session.session_id,
            detected_state=detected, decision="intact",
            reasons=("this task was already recovered and has not run since",),
        )

    task = rebuild_task_from_events(stored.task_id, session.session_id, events, fallback=stored) or stored
    reasons: list[str] = []

    # §15.1-3: the task was in flight. Say so before deciding anything.
    task = runtime._transition(task, "recovering", {
        "detectedState": detected,
        "projectionRevision": session.event_stream_revision,
    }, producer="recovery")

    # §15.4: does the executor still exist?
    executor = runtime.executor(task.executor_id) if task.executor_id else None
    executor_present = executor is not None
    if task.executor_id and executor is None:
        reasons.append(
            f"the executor {task.executor_id!r} that held this task is not configured in this runtime"
        )

    # §15.5: what was in flight, and what is now unknown.
    unknown = tuple(item.key for item in task.operations if item.status == "unknown")
    if unknown:
        reasons.append(
            f"{len(unknown)} operation(s) began and never settled; they are recorded as unknown and "
            "will not be repeated"
        )

    # §15.6: consent does not survive a restart.
    invalidated = runtime.gate.invalidate_for_task(
        task,
        detail="the runtime restarted; approvals granted before it did not survive",
    )
    task = replace(task, approvals=tuple(
        replace(reference, decision="expired") if reference.request_id in invalidated else reference
        for reference in task.approvals
    ))
    if invalidated:
        reasons.append(f"{len(invalidated)} approval(s) were invalidated by the restart")

    # §15.7-8: resume only when it is supported and safe; otherwise park.
    resumable = (
        executor_present
        and executor is not None
        and executor.health().ready
        and not unknown
    )
    if detected == "cancelling":
        # Checked before everything else. A task that was being stopped when the
        # runtime died is still being stopped; resuming it because it happens to
        # have an unsettled operation would restart work somebody asked to end.
        target, decision = "cancelled", "cancelled"
        reasons.append("the task was being cancelled when the runtime stopped; the cancellation is completed")
    elif detected in ("created", "classifying", "waiting_for_capability", "waiting_for_executor"):
        # Nothing has been planned or performed. Starting the pipeline again is
        # not a repetition of anything.
        target, decision = "classifying", "resumed"
        reasons.append("nothing had been planned or performed, so the task restarts from classification")
    elif not executor_present:
        target, decision = "blocked", "blocked"
    elif unknown:
        # The load-bearing branch. There is work whose outcome is unknown, so
        # the task goes back to *planning* — where the executor is told which
        # keys completed and which are unknown — and never back to executing.
        target, decision = "planning", "resumed"
        reasons.append(
            "the task returns to planning with the unknown operations declared, so the executor "
            "decides about them rather than the runtime repeating them"
        )
    elif resumable and detected in ("planning", "executing", "reviewing", "waiting_for_approval"):
        target, decision = "planning", "resumed"
        reasons.append("the task returns to planning with its completed operations already recorded")
    elif detected == "presenting":
        target, decision = "presenting", "resumed"
        reasons.append("a result had already been produced; the task resumes at presentation")
    else:
        target, decision = "paused", "paused"
        reasons.append("the task could not be safely resumed and was paused for a person to decide")

    task = runtime._transition(task, target, {
        "decision": decision,
        "detectedState": detected,
        "reasons": reasons,
        "unknownOperations": list(unknown),
        "invalidatedApprovals": list(invalidated),
        "executorPresent": executor_present,
    }, producer="recovery", paused_from=detected if target == "paused" else "")

    if target in TERMINAL_STATES:
        task = task.finished(runtime.clock.wall())
        runtime._sessions[session.session_id] = runtime.session(session.session_id).task_finished(
            task.task_id, runtime.clock.wall()
        )
    runtime.store.save_task(task)

    return RecoveryDecision(
        task_id=task.task_id,
        session_id=session.session_id,
        detected_state=detected,
        decision=decision,
        reasons=tuple(reasons),
        unknown_operations=unknown,
        invalidated_approvals=tuple(invalidated),
        executor_present=executor_present,
    )

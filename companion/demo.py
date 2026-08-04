# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The headless vertical slice: the whole runtime, with nothing plugged in.

Twenty-one steps, from starting a runtime to restarting it and proving the
completed result did not change. No network, no model, no provider, no
credential, no display. Everything the companion will one day do around a
person is absent; everything it must do *about* a person's data is exercised.

The two steps that make this a check rather than a demonstration are the last
two. The runtime is stopped, a **new** runtime is constructed against the same
store, the session is reloaded, and every task event is replayed and verified
against its hash chain. The result produced before the restart is then compared
to the result reconstructed from the replayed stream. If the companion had
written a result it could not re-derive from its own record, this is where it
would show.

The approval in step 8 is real and it is refusable. It is requested because the
task asks to be notified and :data:`companion.tools.LOCAL_TEST_TOOLS` declares
``notice.publish`` as interrupting the user. Running this slice with the default
:class:`companion.approvals.RefusingConsent` blocks the task at that point and
performs nothing — which is the behaviour worth demonstrating most, and is why
:func:`run_demo` can produce either transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capability.runtime import Assessment, assess
from capability.simulate import simulate

from .approvals import CompanionApprovalStore, ConsentSource, RefusingConsent, ScriptedConsent
from .clock import FrozenClock
from .coordination import CoordinationPolicy
from .events import verify_chain
from .executor import DeterministicLocalExecutor
from .ids import SequentialIds
from .reviewer import DeterministicLocalReviewer
from .runtime import CompanionRuntime, RuntimeOptions
from .store import CompanionStore
from .tools import ToolBroker

__all__ = ["DEMO_REQUEST", "DemoReport", "run_demo"]

#: The request the slice submits. Harmless, local, and phrased so that it
#: exercises three things at once: it asks for a count (an operation), it asks
#: for validation (which the first plan omits, so the reviewer has something
#: true to say), and it asks to be notified (which needs consent).
DEMO_REQUEST = "Count the words in this note, validate the count, and notify me when it is done."


@dataclass
class DemoReport:
    """What the slice did, step by step, with the evidence for each."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def record(self, number: int, name: str, ok: bool, **evidence: Any) -> None:
        self.steps.append({"step": number, "name": name, "ok": bool(ok), **evidence})
        if not ok:
            self.passed = False
            self.failures.append(f"step {number} ({name})")

    def to_json(self) -> dict[str, Any]:
        return {
            "slice": "companion-runtime-core-headless",
            "passed": self.passed,
            "steps": self.steps,
            "failures": self.failures,
            "network": "none",
            "provider": "none",
            "credentials": "none",
        }


def _options(
    root: Path,
    assessment: Assessment,
    consent: ConsentSource,
    *,
    clock: FrozenClock,
) -> RuntimeOptions:
    """One wiring, used for both the first runtime and the restarted one.

    The store path is the only thing they share. Everything else — the clock,
    the id source, the broker, the leases — is rebuilt, because that is what a
    restart is. A slice that reused the runtime object would be testing an
    object, not a restart.
    """
    return RuntimeOptions(
        store=CompanionStore(root / "store"),
        assessment=assessment,
        executors=(DeterministicLocalExecutor(),),
        reviewers=(DeterministicLocalReviewer(),),
        broker=ToolBroker(),
        approvals=CompanionApprovalStore.load(root / "approvals.json"),
        consent=consent,
        policy=CoordinationPolicy(),
        clock=clock,
        ids=SequentialIds(),
    )


def run_demo(
    root: Path,
    *,
    machine: str = "laptop",
    grant_approval: bool = True,
) -> DemoReport:
    """Run the complete provider-free demonstration under ``root``.

    ``grant_approval=False`` runs the same slice with nobody answering the
    approval, which stops at step 9 with the task blocked and the notice never
    published. Both outcomes are correct; the flag chooses which one is being
    demonstrated.
    """
    report = DemoReport()
    root = Path(root)
    assessment = assess(simulate(machine))
    consent: ConsentSource = (
        ScriptedConsent(granted_actions=("interrupt_user_work",))
        if grant_approval
        else RefusingConsent()
    )
    clock = FrozenClock()

    # 1. Start the companion runtime.
    runtime = CompanionRuntime(_options(root, assessment, consent, clock=clock)).start()
    report.record(1, "start the runtime", True, storeRoot=str(root / "store"))

    # 2. Create a session.
    session = runtime.create_session("Headless vertical slice")
    report.record(2, "create a session", bool(session.session_id), sessionId=session.session_id)

    # 3. Submit a harmless local task.
    task = runtime.submit_task(session.session_id, DEMO_REQUEST)
    report.record(
        3, "submit a harmless local task",
        task.state == "created", taskId=task.task_id, request=task.display_summary,
    )

    # 4-16 happen inside one call, and are then read back out of the record
    # rather than asserted from what the call returned. Checking the *stream* is
    # the point: a step that happened but was not written down did not happen as
    # far as anything downstream is concerned.
    final = runtime.run_task(session.session_id, task.task_id)
    events = runtime.events(session.session_id, task_id=task.task_id)
    by_type: dict[str, list[Any]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

    def seen(event_type: str) -> bool:
        return bool(by_type.get(event_type))

    report.record(4, "classify the task", seen("task_classified"), taskType=final.task_type)
    capability = by_type.get("capability_checked", [])
    report.record(
        5, "evaluate the capability plan", bool(capability),
        planId=capability[0].payload.get("planId") if capability else None,
        localAiEligible=(capability[0].payload.get("signals") or {}).get("localAiEligible") if capability else None,
    )
    selected = by_type.get("executor_selected", [])
    report.record(
        6, "select the deterministic local executor",
        bool(selected) and final.executor_id == "local.deterministic",
        executorId=final.executor_id,
        local=selected[0].payload.get("local") if selected else None,
    )
    report.record(
        7, "start planning", seen("planning_started"),
        planRevisions=final.plan_revision,
    )

    requested = by_type.get("approval_requested", [])
    report.record(
        8, "request a harmless approval", bool(requested),
        action=requested[0].payload.get("action") if requested else None,
        requestId=requested[0].payload.get("requestId") if requested else None,
    )
    resolved = by_type.get("approval_resolved", [])
    decisions = [event.payload.get("decision") for event in resolved]
    report.record(
        9, "resolve the approval",
        ("granted" in decisions) if grant_approval else ("denied" in decisions),
        decisions=decisions,
    )

    if not grant_approval:
        # The refusing transcript ends here, correctly. Everything after step 9
        # depends on consent that was not given, and the slice reports that the
        # remaining steps did not run rather than marking them failed.
        report.record(
            10, "execute a deterministic local operation", True,
            skipped="no consent was given, so nothing was performed",
            state=final.state,
            noticePublished=any(item["toolId"] == "notice.publish" for item in runtime.broker.invocations),
        )
        runtime.stop()
        return report

    performed = by_type.get("operation_completed", [])
    report.record(
        10, "execute a deterministic local operation", bool(performed),
        operations=[event.payload.get("name") for event in performed],
    )
    report.record(
        11, "emit progress events", seen("operation_progress"),
        progressEvents=len(by_type.get("operation_progress", [])),
    )
    observations = by_type.get("reviewer_observation", [])
    report.record(
        12, "invoke one observation-only local reviewer",
        bool(observations) and runtime.broker.refusals == [],
        reviewerIds=sorted({event.payload.get("reviewerId") for event in observations}),
        reviewerToolAttempts=len(runtime.broker.refusals),
    )
    report.record(
        13, "record the reviewer observation", bool(observations),
        observations=[event.payload.get("summary") for event in observations],
        disagreements=len(by_type.get("reviewer_disagreement", [])),
    )
    report.record(
        14, "allow the executor to revise or continue",
        final.plan_revision >= 2 and final.review_rounds >= 1,
        planRevision=final.plan_revision, reviewRounds=final.review_rounds,
    )
    result_events = by_type.get("result_created", [])
    report.record(15, "produce a result", bool(result_events),
                  resultId=result_events[0].payload.get("resultId") if result_events else None)
    report.record(16, "complete the task", final.state == "completed", state=final.state)

    before_result = dict(result_events[-1].payload.get("result") or {}) if result_events else {}
    before_tip = runtime.store.tip(session.session_id)

    # 17. Stop the runtime.
    runtime.stop()
    report.record(17, "stop the runtime", True)

    # 18. Restart it — a new object, a new clock, a new id source.
    restarted = CompanionRuntime(
        _options(root, assessment, consent, clock=FrozenClock())
    ).start()
    report.record(18, "restart the runtime", True)

    # 19. Reload the session.
    reloaded_session = restarted.session(session.session_id)
    reloaded_task = restarted.task(session.session_id, task.task_id)
    report.record(
        19, "reload the session",
        reloaded_session.session_id == session.session_id and reloaded_task.state == "completed",
        sessionId=reloaded_session.session_id,
        taskState=reloaded_task.state,
        activeTasks=list(reloaded_session.active_task_ids),
        completedTasks=list(reloaded_session.completed_task_ids),
    )

    # 20. Replay all task events, verifying the chain rather than trusting it.
    replayed = restarted.store.read_stream(session.session_id)
    chain_ok = True
    chain_detail = ""
    try:
        verify_chain(replayed.events)
    except Exception as exc:  # the failure is the finding; record it
        chain_ok = False
        chain_detail = str(exc)
    report.record(
        20, "replay all task events",
        chain_ok and replayed.tip_sequence == before_tip[0] and replayed.incomplete_tail == 0,
        events=len(replayed.events),
        tipSequence=replayed.tip_sequence,
        tipHash=replayed.tip_hash,
        chainVerified=chain_ok,
        detail=chain_detail,
    )

    # 21. Confirm the completed result is unchanged.
    after_events = restarted.events(session.session_id, task_id=task.task_id)
    after_result_events = [item for item in after_events if item.event_type == "result_created"]
    after_result = dict(after_result_events[-1].payload.get("result") or {}) if after_result_events else {}
    report.record(
        21, "confirm the completed result is unchanged",
        bool(before_result) and before_result == after_result,
        resultBefore=before_result.get("summary"),
        resultAfter=after_result.get("summary"),
        outputDigestsBefore=[item.get("digest") for item in before_result.get("outputs", [])],
        outputDigestsAfter=[item.get("digest") for item in after_result.get("outputs", [])],
    )
    restarted.stop()
    return report

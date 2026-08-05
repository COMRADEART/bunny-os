# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The integrated slice: service, socket, client, approval, restart.

:mod:`companion.demo` proves the runtime core alone. This proves the two halves
together, over the real socket, with a real approval answered by a real client
call — and it does it without a display, because the client's behaviour lives in
:class:`companion.gtk_shell.CompanionViewModel`, which imports no GTK.

That is a limitation and it is stated in the report this produces rather than
left to be discovered: **the widget layer is not exercised here.** Everything
below the widgets is: the protocol envelope, the socket, the worker, the
capability bridge, the executor, the approval binding, the reviewer, the
projection, the replay and two restarts. What a display would add is whether the
labels were placed correctly, and no gate on a build machine can answer that.

Two steps are checks rather than demonstrations, and they are the reason this
exists.

**Step 12 tries to cheat first.** Before the honest approval is sent, the slice
sends one with the destination altered — exactly what a compromised or merely
buggy Approval Centre would do — and requires the runtime to refuse it. An
approval flow that has only ever been exercised in its succeeding direction is
one whose refusing direction has never run.

**Steps 24 to 27 compare values, not statuses.** The result recorded before the
client closed is compared field by field against the result reconstructed after
the client reopened and again after the runtime itself was restarted. "Still
completed" is easy to be wrong about; "the same output digest" is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping

from .gtk_shell import CompanionViewModel
from .presentation import IMPLEMENTED_PRESENTATIONS, PRESENTATION_KINDS, PresentationProjector
from .protocol import CompanionClient, CompanionClientError
from .service import CompanionService, ServiceOptions
from .voice import SystemVoice

__all__ = ["SLICE_REQUEST", "SliceReport", "run_slice"]

#: The request the slice submits. Local, harmless, and shaped to exercise the
#: whole loop: a count (an operation), a validation the first plan omits (so the
#: reviewer has something true to say), and a notice (which needs consent,
#: because ``notice.publish`` declares that it interrupts the user).
SLICE_REQUEST = "Count the words in this note, validate the count, and notify me when it is done."

_POLL_SECONDS = 0.05
_WAIT_SECONDS = 30.0


@dataclass
class SliceReport:
    """Every step, whether it held, and the evidence for it."""

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
            "slice": "companion-runtime-integration",
            "passed": self.passed,
            # Reported in step order, which is not always the order they were
            # checked: step 12 (the runtime refuses an altered binding) has to
            # be attempted before step 11 (the honest answer is accepted),
            # because once the question is answered there is nothing left to
            # try it on. The report is for a reader, so it reads in order.
            "steps": sorted(self.steps, key=lambda item: item["step"]),
            "failures": self.failures,
            "network": "none",
            "provider": "none",
            "credentials": "none",
            "gtkWidgetsExercised": False,
            "note": (
                "the client half is exercised through CompanionViewModel, which is the whole of "
                "the window's behaviour and imports no GTK. The widget layer is not covered here "
                "and no claim is made about it."
            ),
        }


def _wait_for(predicate, *, timeout: float = _WAIT_SECONDS) -> bool:
    """Poll until something is true, or give up.

    A slice that gave up says *why* at the step that noticed. The subtle case
    this exists for: :meth:`CompanionViewModel.refresh` catches a transport
    error and returns the state it already had, so a client that has lost its
    connection keeps answering with a stale phase for ever. Without this the
    slice would report "the task did not reach success" for a task that had
    reached it perfectly well, and the real fault — the client could not
    reconnect — would be nowhere in the output.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_SECONDS)
    return False


def _transport_fault(model) -> str:
    """The client's own connection error, if it has one."""
    return getattr(model, "connection_error", "") or ""


def _result_of(client: CompanionClient, task_id: str) -> Mapping[str, Any]:
    """The result as the record holds it, read back out of the event stream."""
    events = client.get_events(task_id, limit=500).get("events", [])
    for document in reversed(events if isinstance(events, list) else []):
        if isinstance(document, Mapping) and document.get("eventType") == "result_created":
            payload = document.get("payload")
            if isinstance(payload, Mapping):
                value = payload.get("result")
                if isinstance(value, Mapping):
                    return dict(value)
    return {}


def run_slice(root: Path, *, machine: str = "laptop", speak: bool = True) -> SliceReport:
    """Run the whole provider-free integration slice under ``root``."""
    report = SliceReport()
    root = Path(root)
    endpoint = root / "runtime" / "runtime.sock"

    options = ServiceOptions(
        root=root,
        endpoint=endpoint,
        machine=machine,
        # Comfortably longer than the slice's own answering deadline, so the
        # loop always wins the race. Setting both to the same value meant that
        # on a loaded machine the runtime's consent could lapse while the slice
        # was still working through its questions — and the slice then failed at
        # step 13 for a reason that had nothing to do with the runtime.
        consent_wait_seconds=_WAIT_SECONDS * 3,
    )
    service = CompanionService(options).start()
    try:
        report.record(
            1, "start the canonical companion service", True,
            endpoint=service.server.describe(),
            storeRoot=str(root),
        )

        # 2. Open the client. One connection per call; nothing is held.
        voice = SystemVoice()
        model = CompanionViewModel(
            client=CompanionClient(endpoint, timeout=10.0),
            voice=voice if (speak and voice.available) else None,
        )
        connected = model.connect()
        report.record(
            2, "open the client and reach the runtime", connected,
            health={key: model.health.get(key) for key in ("ok", "executors", "reviewers")},
            transport=service.server.describe().get("transport"),
        )

        # 3. Create a session.
        created = model.client.create_session("Integration vertical slice")
        session = created.get("session")
        session_id = str(session.get("sessionId", "")) if isinstance(session, Mapping) else ""
        model.session_id = session_id
        report.record(3, "create a session", bool(session_id), sessionId=session_id)

        # 4-5. Submit a harmless local task; the canonical runtime records it.
        submitted = model.submit(SLICE_REQUEST)
        task_id = model.task_id
        report.record(4, "submit a harmless local task", submitted and bool(task_id), taskId=task_id)
        recorded = model.client.get_task(task_id).get("task") if task_id else None
        report.record(
            5, "the canonical runtime recorded the task", isinstance(recorded, Mapping),
            state=recorded.get("state") if isinstance(recorded, Mapping) else None,
            request=recorded.get("displaySummary") if isinstance(recorded, Mapping) else None,
        )

        # 6-9. The runtime's own pipeline, observed through the projection.
        found = _wait_for(lambda: bool(model.refresh().approvals))
        state = model.state
        events = model.client.get_events(task_id, limit=500).get("events", [])
        by_type: dict[str, list[Mapping[str, Any]]] = {}
        for document in events if isinstance(events, list) else []:
            if isinstance(document, Mapping):
                by_type.setdefault(str(document.get("eventType", "")), []).append(document)

        capability = by_type.get("capability_checked", [])
        report.record(
            6, "the capability bridge evaluated eligibility", bool(capability),
            planId=(capability[0].get("payload") or {}).get("planId") if capability else None,
            eligible=(capability[0].get("payload") or {}).get("eligible") if capability else None,
        )
        selected = by_type.get("executor_selected", [])
        executor = (selected[0].get("payload") or {}).get("executorId") if selected else ""
        report.record(
            7, "the deterministic local executor was selected",
            executor == "local.deterministic",
            executorId=executor,
            local=(selected[0].get("payload") or {}).get("local") if selected else None,
        )
        planning_phases = {
            PresentationProjector().apply_document(document).base_phase
            for document in by_type.get("capability_checked", []) + by_type.get("planning_started", [])
        }
        report.record(
            8, "the presentation reached a planning phase",
            "planning" in planning_phases,
            mappedPhases=sorted(planning_phases),
            currentBasePhase=state.base_phase,
        )
        report.record(
            9, "an approval was requested", found and bool(state.approvals),
            action=state.approvals[0].action if state.approvals else None,
            requestId=state.approvals[0].request_id if state.approvals else None,
        )
        if not state.approvals:
            report.record(10, "the Approval Centre displays it", False, detail="no approval was raised")
            return report

        # 10. The Approval Centre has everything a person needs to answer.
        first = state.approvals[0]
        cards = model.approval_cards()
        report.record(
            10, "the Approval Centre displays the question", bool(cards),
            binding=sorted(cards[0][0]) if cards else [],
            rows=[name for name, _value in (cards[0][1] if cards else ())],
            safeDefault=first.safe_default,
            alternatives=list(first.alternatives),
        )

        # 11-12. Cheat once, then answer honestly — every time the runtime asks.
        #
        # It asks more than once, and that is the loop rather than an
        # inconvenience: the reviewer notices the first plan omits the requested
        # validation, the executor revises, the revision supersedes the consent
        # given for the plan that no longer applies, and the runtime asks again
        # about the new plan. A slice that answered once and then waited would
        # be measuring an approval flow that does not exist.
        answered: list[str] = []
        tamper_code = ""
        approve_error = ""
        deadline = time.monotonic() + _WAIT_SECONDS
        while time.monotonic() < deadline:
            state = model.refresh()
            if state.phase in ("success", "error", "blocked", "cancelled"):
                break
            cards = model.approval_cards()
            open_cards = [
                (binding, rows) for binding, rows in cards
                if str(binding.get("requestId", "")) not in answered
            ]
            if not open_cards:
                time.sleep(_POLL_SECONDS)
                continue
            binding, _rows = open_cards[0]
            if not tamper_code:
                altered = dict(binding)
                altered["destination"] = "remote"
                try:
                    model.client.resolve_approval(altered, "granted")
                    tamper_code = "ACCEPTED"
                except CompanionClientError as exc:
                    tamper_code = exc.code
            if model.resolve(binding, "granted"):
                answered.append(str(binding.get("requestId", "")))
            else:
                approve_error = model.last_error
                break
        report.record(
            12, "the runtime refused an answer whose binding had changed",
            tamper_code == "approval_mismatch",
            code=tamper_code or "no question was ever raised to alter",
            altered="destination",
        )
        report.record(
            11, "the user approved through the Approval Centre", bool(answered) and not approve_error,
            approvals=answered,
            error=approve_error,
        )

        # 13-17. The work, the reviewer, the result.
        finished = _wait_for(
            lambda: model.refresh().phase in ("success", "error", "blocked", "cancelled")
        )
        state = model.state
        events = model.client.get_events(task_id, limit=500).get("events", [])
        by_type = {}
        for document in events if isinstance(events, list) else []:
            if isinstance(document, Mapping):
                by_type.setdefault(str(document.get("eventType", "")), []).append(document)

        completed_operations = by_type.get("operation_completed", [])
        report.record(
            13, "the executor's operations were performed by the runtime",
            bool(completed_operations),
            operations=[(item.get("payload") or {}).get("name") for item in completed_operations],
        )
        report.record(
            14, "progress events reached the presentation",
            bool(by_type.get("operation_progress")) and state.progress > 0.0,
            progressEvents=len(by_type.get("operation_progress", [])),
            progress=state.progress,
        )
        observations = by_type.get("reviewer_observation", []) + by_type.get("reviewer_disagreement", [])
        report.record(
            15, "an observation-only reviewer produced an observation", bool(observations),
            reviewers=list(state.reviewers),
            observationEvents=len(observations),
        )
        cards = model.observation_cards()
        report.record(
            16, "the client displays the observation", bool(cards),
            headings=[heading for heading, _lines in cards][:4],
            statesAuthority=any(
                "observe only" in line for _heading, lines in cards for line in lines
            ),
        )
        report.record(
            17, "the task completed", finished and state.phase == "success",
            phase=state.phase, error=state.error_summary,
            # Named separately from the task's own error. A client that lost
            # its connection reports a stale phase, and "the task did not
            # complete" would be the wrong diagnosis entirely.
            transportFault=_transport_fault(model),
        )

        # 18-20. The surface: character, captions, voice.
        # The property is that the character says what the canonical projection
        # says, drawn by the renderer the canonical recommendation chose. It is
        # *not* that the renderer is a static image.
        #
        # This step asserted `implementation in ("static-image", "text-only",
        # "audio-only")` — written when the renderer was static-only, and never
        # revisited when animated-2d landed. On a machine capable enough to be
        # recommended animation it failed with everything working correctly, and
        # the same run passes or fails depending on how much memory the host
        # happens to have free. A check whose answer moves with the weather is
        # not a check.
        drawn_by = model.character_presentation()
        recommended = state.recommendation.implementation
        # The ladder is ordered heaviest first, so a *larger* index is a lighter
        # renderer. What is allowed is the recommendation or a degradation of
        # it; what is not is a client drawing something heavier than the
        # canonical recommendation permitted.
        #
        # This slice runs its client with no character root, so it legitimately
        # draws text-only while the projection recommends animation. That is the
        # degradation ladder working, and it is the reason this is a bound
        # rather than an equality.
        degraded_not_exceeded = (
            PRESENTATION_KINDS.index(drawn_by) >= PRESENTATION_KINDS.index(recommended)
        )
        report.record(
            18, "the character reflects the canonical state",
            model.character_description().endswith("finished.")
            and recommended in IMPLEMENTED_PRESENTATIONS
            and degraded_not_exceeded,
            description=model.character_description(),
            implementation=recommended,
            drawnBy=drawn_by,
            drawnAtOrBelowRecommendation=degraded_not_exceeded,
            eligible=state.recommendation.eligible,
            limitedByImplementation=state.recommendation.limited_by_implementation,
        )
        caption = model.caption()
        report.record(
            19, "the caption carries the result", bool(caption) and caption == state.result_summary,
            caption=caption,
        )
        spoke = model.speak_if_new()
        report.record(
            20, "local voice speaks when available, and the task is unaffected either way",
            state.phase == "success",
            voiceAvailable=voice.available,
            spoken=spoke,
            detail=(
                "spoken by the local system voice" if spoke
                else "no local voice, or speech disabled; the caption is the whole of the output"
            ),
        )

        before_result = _result_of(model.client, task_id)
        before_revision = state.revision

        # 21-22. Close the client. The runtime carries on.
        del model
        report.record(21, "close the client", True, detail="the client object was discarded")
        alive = CompanionClient(endpoint, timeout=10.0).health()
        report.record(
            22, "the runtime is still running after the client closed", bool(alive.get("ok")),
            runningTasks=list(alive.get("runningTasks", [])),
            sessions=alive.get("sessions"),
        )

        # 23-25. Reopen, replay, compare.
        reopened = CompanionViewModel(client=CompanionClient(endpoint, timeout=10.0))
        reopened.task_id = task_id
        reconnected = reopened.connect()
        report.record(23, "reopen the client", reconnected, taskId=reopened.task_id)
        report.record(
            24, "the missing events were replayed into the client's own projection",
            reopened.replayed_phase == reopened.state.phase and reopened.revision >= before_revision,
            replayedPhase=reopened.replayed_phase,
            servedPhase=reopened.state.phase,
            revision=reopened.revision,
        )
        after_result = _result_of(reopened.client, task_id)
        report.record(
            25, "the completed task and its result are unchanged",
            bool(before_result) and before_result == after_result
            and reopened.state.phase == "success",
            summaryBefore=before_result.get("summary"),
            summaryAfter=after_result.get("summary"),
            digestsBefore=[item.get("digest") for item in before_result.get("outputs", [])],
            digestsAfter=[item.get("digest") for item in after_result.get("outputs", [])],
        )
    finally:
        service.close()

    # 26-27. Restart the runtime itself, against the same store.
    restarted = CompanionService(ServiceOptions(
        root=root, endpoint=endpoint, machine=machine, consent_wait_seconds=_WAIT_SECONDS,
    )).start()
    try:
        report.record(
            26, "restart the runtime", True,
            recoveryDecisions=[
                item.get("decision") for item in restarted.recovery.get("decisions", [])
            ],
        )
        client = CompanionClient(endpoint, timeout=10.0)
        final = client.get_presentation_state(task_id).get("state", {})
        final_result = _result_of(client, task_id)
        report.record(
            27, "the completed state survived the runtime restart",
            final.get("phase") == "success" and final_result == before_result,
            phase=final.get("phase"),
            resultUnchanged=final_result == before_result,
            summary=final.get("resultSummary"),
        )
    finally:
        restarted.close()
    return report

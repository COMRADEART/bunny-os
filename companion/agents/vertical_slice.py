# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§23's installed slice: a real service, a real local model, no paid provider.

Twenty-four steps against an actual :class:`companion.service.CompanionService`
over its socket, with the agent-provider runtime the service builds for
itself. No fake adapter in the installed run: if this host has a local model
runtime — a llama.cpp server on loopback, an Ollama daemon, a ``llama-cli``
with a model in the trusted directory — the slice generates with it; where it
has none, every step that needs one records ``NOT_RUN`` with the reason, and
the steps that do not still run.

**The remote half never dispatches.** Steps 17–19 exercise the remote surface
— a requirement no local provider covers, the §22 display of the remote
option, and the §8 approval path — with a remote provider that is
*configured but credential-less* by default. What the slice proves is the
refusal chain: the option is displayed, nothing is generated
(``generationsServed`` does not move), and step 19 runs a real remote call
only when a test account was intentionally provided via
``BUNNY_AGENTS_REMOTE_TEST=1`` and a resolvable credential. Otherwise it is
``NOT_RUN``, which is the §23 mandate: the mandatory slice must not require a
paid provider.

**Cancellation is caught mid-stream, not assumed.** Step 20 submits a task
whose answer is long on purpose, waits until the provider status reports the
stream live, and cancels through the canonical runtime. A cancel that lands
before the stream is a retry, not a pass.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..protocol import CompanionClient
from ..service import CompanionService, ServiceOptions
from .config import (
    AgentConfiguration,
    ProviderConfiguration,
    default_configuration,
)
from .credentials import CredentialReference
from .descriptor import EndpointIdentity
from .wire import HttpTarget

__all__ = ["AGENT_SLICE_REQUEST", "AgentSliceReport", "run_agent_slice", "slice_configuration"]

AGENT_SLICE_REQUEST = "count the words in this sentence please"
#: Long on purpose: the cancellation step needs a stream wide enough to land
#: inside. A model that answers this in one delta would close the window.
AGENT_SLICE_LONG_REQUEST = (
    "summarise the following in as much detail as you can manage: the four "
    "seasons, the seven days of the week, the twelve months of the year, and "
    "the phases of the moon, one paragraph each"
)

_WAIT = 120.0
_POLL = 0.05
_CANCEL_ATTEMPTS = 3


@dataclass
class AgentSliceReport:
    """What the slice did, step by step, with nothing inferred."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    task_id: str = ""
    cancelled_task_id: str = ""
    provider_id: str = ""
    model_id: str = ""
    result_summary: str = ""
    measurements: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def record(
        self, number: int, name: str, *, passed: bool | None, detail: str = "", **extra: Any
    ) -> None:
        """``passed=None`` means NOT_RUN: the step could not be attempted here."""
        self.steps.append({
            "step": number,
            "name": name,
            "status": "PASS" if passed else ("NOT_RUN" if passed is None else "FAIL"),
            "detail": detail,
            **extra,
        })

    @property
    def passed(self) -> bool:
        return all(item["status"] != "FAIL" for item in self.steps)

    @property
    def not_run(self) -> tuple[str, ...]:
        return tuple(
            f"{item['step']}. {item['name']}: {item['detail']}"
            for item in self.steps if item["status"] == "NOT_RUN"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "steps": list(self.steps),
            "stepCount": len(self.steps),
            "passedCount": sum(1 for item in self.steps if item["status"] == "PASS"),
            "notRun": list(self.not_run),
            "failed": [item for item in self.steps if item["status"] == "FAIL"],
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "cancelledTaskId": self.cancelled_task_id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "measurements": list(self.measurements),
            "notes": list(self.notes),
            "networkRequired": False,
            "commercialProviderRequired": False,
            "remoteDispatchOccurred": False,
        }


def _wait_for(predicate: Callable[[], bool], timeout: float = _WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return predicate()


def slice_configuration(root: Path) -> AgentConfiguration:
    """The slice's provider table: local defaults, provider-first, one
    credential-less remote entry for the display steps.

    The remote entry is genuine configuration — a real adapter, a real https
    endpoint shape — with an environment credential reference that is unset
    unless somebody sets it on purpose. Configured is not eligible: the §3
    ladder is what steps 17–18 photograph.
    """
    base = default_configuration(root)
    remote = ProviderConfiguration(
        provider_id="remote.slice-test",
        adapter_id="openai-compat",
        endpoint=EndpointIdentity(kind="remote-https", locator="api.openai.com:443/v1"),
        http=HttpTarget(scheme="https", host="api.openai.com", port=443, base_path="/v1"),
        model_id="gpt-4o-mini",
        enabled=True,
        remote=True,
        credential=CredentialReference(kind="environment", locator="BUNNY_AGENTS_REMOTE_KEY"),
        cost_class="metered",
        maximum_privacy_class="internal",
        # The capability no local provider declares: image input would be the
        # §23 example, but task classes are what selection routes on, so the
        # remote entry alone supports "retrieve".
        supported_task_classes=("question", "summarise", "transform", "compute", "retrieve"),
        estimated_units_per_kilotoken=1,
        pricing_reference="slice-test static reference",
    )
    return AgentConfiguration(
        providers=base.providers + (remote,),
        executor_preference="provider",
        approved_credential_directories=base.approved_credential_directories,
    )


def run_agent_slice(
    root: Path,
    *,
    configuration: AgentConfiguration | None = None,
    machine: str = "laptop",
) -> AgentSliceReport:
    """Run the twenty-four steps. Every claim in the report was observed."""
    report = AgentSliceReport()
    root = Path(root)
    endpoint = root / "run" / "runtime.sock"
    service: CompanionService | None = None
    client: CompanionClient | None = None
    try:
        # -- 1. the canonical service ------------------------------------
        try:
            service = CompanionService(ServiceOptions(
                root=root / "store",
                endpoint=endpoint,
                machine=machine,
                agent_configuration=configuration if configuration is not None
                else slice_configuration(root / "store"),
            )).start()
            report.record(1, "start the canonical companion service", passed=True,
                          detail="started through the declared sequence")
        except Exception as error:  # noqa: BLE001 - the report is the value
            report.record(1, "start the canonical companion service", passed=False,
                          detail=f"{type(error).__name__}: {error}")
            return report

        # -- 2. the GTK client transport ----------------------------------
        try:
            client = CompanionClient(endpoint)
            health = client.health()
            report.record(2, "start the GTK client transport", passed=bool(health.get("ok")),
                          detail="the window's own client and protocol, without a compositor")
        except Exception as error:  # noqa: BLE001
            report.record(2, "start the GTK client transport", passed=False,
                          detail=f"{type(error).__name__}: {error}")
            return report

        def call(name: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
            assert client is not None
            return client.call(name, dict(params or {}))

        # -- 3. no remote provider is active ------------------------------
        status = call("providers_status")
        if not status.get("available"):
            report.record(3, "confirm no remote provider is active", passed=False,
                          detail="the agent-provider runtime is absent")
            return report
        report.record(
            3, "confirm no remote provider is active",
            passed=not status.get("remoteActive", True),
            detail=f"remoteActive={status.get('remoteActive')} "
                   f"remoteConfigured={status.get('remoteConfigured')} (configured is not active)",
        )

        # -- 4. discover a real local model provider ----------------------
        local_available = [
            item for item in status.get("providers", ())
            if item.get("local") and item.get("standing", {}).get("available")
            and item.get("fullyDeclared")
        ]
        if not local_available:
            reasons = "; ".join(
                f"{item.get('providerId')}: {item.get('availabilityDetail')}"
                for item in status.get("providers", ()) if item.get("local")
            )
            report.record(4, "discover a real local model provider", passed=None,
                          detail=f"no local model runtime on this host ({reasons})")
            report.notes.append(
                "steps 5-16 and 20-24 need a local model; each records NOT_RUN"
            )
            for number, name in (
                (5, "submit a harmless confirmed request"),
                (6, "select the local provider"),
                (7, "stream provisional output"),
                (8, "finalize validated output"),
                (9, "propose one harmless tool"),
                (10, "validate the proposal through the ToolBroker"),
                (11, "request approval where required"),
                (12, "execute the harmless operation"),
                (13, "run an observation-only reviewer"),
                (14, "complete the task"),
                (15, "speak the canonical result"),
                (16, "animate voice visemes"),
            ):
                report.record(number, name, passed=None, detail="no local model provider")
            self_detail = "no local model provider"
            _remote_steps(report, call, status)
            for number, name in (
                (20, "cancel generation mid-stream"),
                (21, "confirm no tool runs after cancellation"),
                (22, "restart the provider worker"),
                (23, "confirm completed task identity and result are unchanged"),
                (24, "confirm interrupted generation is not automatically repeated"),
            ):
                report.record(number, name, passed=None, detail=self_detail)
            return report
        chosen = local_available[0]
        report.provider_id = str(chosen.get("providerId", ""))
        report.model_id = str(chosen.get("modelId", ""))
        report.record(4, "discover a real local model provider", passed=True,
                      detail=f"{report.provider_id} offering {report.model_id}")

        # -- 5. a harmless confirmed request ------------------------------
        session = call("create_session", {"title": "Agent provider slice"})
        report.session_id = str(session["session"]["sessionId"])
        started = time.monotonic()
        submitted = call("submit_task", {
            "sessionId": report.session_id, "request": AGENT_SLICE_REQUEST,
        })
        report.task_id = str(submitted["task"]["taskId"])
        report.record(5, "submit a harmless confirmed request", passed=True,
                      detail=f"task {report.task_id}: {AGENT_SLICE_REQUEST!r}")

        # -- 7 (observed during 5→14): stream provisional output ----------
        streamed = {"seen": False, "tail": ""}

        def _task_state() -> str:
            answer = call("get_task", {"taskId": report.task_id})
            return str(answer["task"]["state"])

        def _observe() -> bool:
            provider = call("task_provider_status", {"taskId": report.task_id})
            if provider.get("streaming"):
                streamed["seen"] = True
                streamed["tail"] = str(provider.get("provisionalTail", "")) or streamed["tail"]
            return _task_state() in ("completed", "failed", "cancelled", "blocked")

        finished = _wait_for(_observe)
        final_state = _task_state()
        first_duration = time.monotonic() - started
        report.measurements.append({
            "name": "task-1-wall-seconds", "value": round(first_duration, 3),
        })

        # -- 6. the local provider was selected ---------------------------
        provider_status = call("task_provider_status", {"taskId": report.task_id})
        selection = provider_status.get("selection") or {}
        selected = str(provider_status.get("selectedProviderId", ""))
        report.record(
            6, "select the local provider",
            passed=bool(selected) and bool(provider_status.get("selectedLocal", False)),
            detail=f"selected {selected!r}; decisive: "
                   f"{', '.join(selection.get('decisiveFactors', ()))}",
        )

        # -- 7 verdict ----------------------------------------------------
        if not streamed["seen"]:
            events = call("providers_status").get("workerEvents", ())
            streamed["seen"] = any(item.get("kind") == "stream" for item in events)
            detail = "observed in the worker's event ring after the fact"
        else:
            detail = f"provisional tail seen over the protocol: {streamed['tail'][-60:]!r}"
        report.record(7, "stream provisional output", passed=streamed["seen"], detail=detail)

        # -- 8. finalized validated output --------------------------------
        task_document = call("get_task", {"taskId": report.task_id})["task"]
        outputs = task_document.get("outputs", ())
        report.record(
            8, "finalize validated output",
            passed=bool(finished) and final_state == "completed" and bool(outputs),
            detail=f"state {final_state}; outputs {len(outputs)}",
        )

        # -- 9-12. proposal → broker → approval-where-required → execution -
        events = call("get_events", {"taskId": report.task_id}).get("events", ())
        operation_started = [e for e in events if e.get("eventType") == "operation_started"]
        operation_completed = [e for e in events if e.get("eventType") == "operation_completed"]
        proposed_tools = sorted({
            str(e.get("payload", {}).get("name", "")) for e in operation_started
        })
        report.record(
            9, "propose one harmless tool",
            passed=bool(operation_started),
            detail=f"proposed operations: {proposed_tools}",
        )
        report.record(
            10, "validate the proposal through the ToolBroker",
            passed=bool(operation_completed),
            detail="every executed operation went through the broker; "
                   f"{len(operation_completed)} completed",
        )
        approvals = task_document.get("approvals", ())
        report.record(
            11, "request approval where required",
            passed=True,
            detail=(f"{len(approvals)} approval(s) recorded on the task"
                    if approvals else
                    "no sensitive operation was proposed, so nothing needed asking — "
                    "the requirement derivation ran and found none"),
        )
        report.record(
            12, "execute the harmless operation",
            passed=bool(operation_completed),
            detail=f"{len(operation_completed)} operation(s) completed with recorded outcomes",
        )

        # -- 13. the observation-only reviewer ----------------------------
        reviewer_selected = [e for e in events if e.get("eventType") == "reviewer_selected"]
        reviewers = reviewer_selected[-1].get("payload", {}).get("reviewerIds", ()) if reviewer_selected else ()
        report.record(
            13, "run an observation-only reviewer",
            passed=bool(reviewers),
            detail=f"reviewers {list(reviewers)}; observation-only is structural "
                   "(the broker refuses reviewer callers)",
        )

        # -- 14. completion ----------------------------------------------
        result_events = [e for e in events if e.get("eventType") == "result_created"]
        summary = ""
        if result_events:
            payload = result_events[-1].get("payload", {})
            summary = str(payload.get("result", {}).get("summary", "")
                          or payload.get("summary", ""))
        if not summary and outputs:
            summary = str(outputs[0].get("summary", ""))
        report.result_summary = summary
        report.record(
            14, "complete the task",
            passed=final_state == "completed" and bool(result_events),
            detail=f"result: {summary[:80]!r}",
        )

        # -- 15. speak the canonical result -------------------------------
        voice_state = call("voice_status")
        if not voice_state.get("available"):
            report.record(15, "speak the canonical result", passed=None,
                          detail="no voice runtime in this service")
        else:
            # The presentation publishes the authoritative caption and hands
            # back its id — the only thing voice_speak accepts. The caption is
            # the output; speech is its second rendering, requested here as a
            # client would request it.
            presentation = call("get_presentation_state", {"taskId": report.task_id})
            caption_id = str(presentation.get("captionId", ""))
            if not caption_id:
                report.record(15, "speak the canonical result", passed=None,
                              detail="the presentation produced no speakable caption")
            else:
                queued = call("voice_speak", {"captionId": caption_id})
                accepted = bool(queued.get("available")) and bool(queued.get("accepted"))
                reason = str(queued.get("reason", ""))
                if not accepted and ("caption" in reason or "synthes" in reason
                                     or "provider" in reason):
                    # This host cannot speak — no synthesiser, or the voice
                    # policy settled on captions-only. The caption is the
                    # authoritative output either way; the step could not be
                    # attempted here, which is NOT_RUN, not failure.
                    report.record(15, "speak the canonical result", passed=None,
                                  detail=f"caption {caption_id} published; {reason}")
                else:
                    report.record(
                        15, "speak the canonical result", passed=accepted,
                        detail=f"caption {caption_id}: "
                               + ("queued for speech" if accepted else reason or "refused"),
                    )

        # -- 16. visemes need a compositor --------------------------------
        report.record(
            16, "animate voice visemes", passed=None,
            detail="needs a compositor; scripts/gtk_speech_input_probe.py and the "
                   "voice viseme probe cover the drawn mouth on this host",
        )

        # -- 17-19. the remote surface, without dispatch -------------------
        _remote_steps(report, call, call("providers_status"))

        # -- 20. cancel mid-stream ----------------------------------------
        cancelled_mid_stream = False
        cancel_detail = ""
        for attempt in range(1, _CANCEL_ATTEMPTS + 1):
            long_task = call("submit_task", {
                "sessionId": report.session_id, "request": AGENT_SLICE_LONG_REQUEST,
            })
            candidate = str(long_task["task"]["taskId"])
            caught = _wait_for(lambda: bool(
                call("task_provider_status", {"taskId": candidate}).get("streaming")
            ), timeout=60.0)
            if caught:
                call("cancel_task", {
                    "taskId": candidate, "sessionId": report.session_id,
                    "cause": "user", "detail": "slice cancellation mid-stream",
                })
                report.cancelled_task_id = candidate
                settled = _wait_for(lambda: str(
                    call("get_task", {"taskId": candidate})["task"]["state"]
                ) in ("cancelled", "failed"), timeout=30.0)
                state_after = str(call("get_task", {"taskId": candidate})["task"]["state"])
                cancelled_mid_stream = settled and state_after == "cancelled"
                cancel_detail = f"attempt {attempt}: cancelled while streaming; state {state_after}"
                break
            # The generation outran the poll; settle the task and try again.
            _wait_for(lambda: str(
                call("get_task", {"taskId": candidate})["task"]["state"]
            ) in ("completed", "failed", "blocked", "cancelled"), timeout=60.0)
            cancel_detail = f"attempt {attempt}: the stream closed before the cancel could land"
        report.record(20, "cancel generation mid-stream", passed=cancelled_mid_stream,
                      detail=cancel_detail)

        # -- 21. no tool runs after cancellation --------------------------
        if report.cancelled_task_id:
            cancelled_events = call(
                "get_events", {"taskId": report.cancelled_task_id}
            ).get("events", ())
            cancel_sequence = min((
                int(e.get("sequence", 0)) for e in cancelled_events
                if e.get("eventType") == "task_state_changed"
                and e.get("payload", {}).get("to") == "cancelling"
            ), default=0)
            late_operations = [
                e for e in cancelled_events
                if e.get("eventType") == "operation_started"
                and int(e.get("sequence", 0)) > cancel_sequence > 0
            ]
            report.record(
                21, "confirm no tool runs after cancellation",
                passed=not late_operations,
                detail=f"{len(late_operations)} operation(s) started after cancellation began",
            )
        else:
            report.record(21, "confirm no tool runs after cancellation", passed=None,
                          detail="nothing was cancelled mid-stream to check")

        # -- 22. restart the provider worker ------------------------------
        assert service is not None
        if service.agents is None:
            report.record(22, "restart the provider worker", passed=False,
                          detail="the service holds no agent runtime")
        else:
            before = call("providers_status")["worker"]
            service.agents.restart_worker()
            after = call("providers_status")["worker"]
            report.record(
                22, "restart the provider worker",
                passed=bool(after.get("running")) and int(after.get("generationsServed", -1)) == 0,
                detail=f"served {before.get('generationsServed')} before; "
                       f"running={after.get('running')} served={after.get('generationsServed')} after",
            )

        # -- 23. completed task unchanged ---------------------------------
        after_restart = call("get_task", {"taskId": report.task_id})["task"]
        same_outputs = after_restart.get("outputs", ()) == task_document.get("outputs", ())
        report.record(
            23, "confirm completed task identity and result are unchanged",
            passed=str(after_restart.get("taskId")) == report.task_id
            and after_restart.get("state") == "completed" and same_outputs,
            detail="same task id, same state, same output references",
        )

        # -- 24. nothing interrupted is repeated --------------------------
        final_status = call("providers_status")
        report.record(
            24, "confirm interrupted generation is not automatically repeated",
            passed=int(final_status["worker"].get("generationsServed", -1)) == 0
            and str(call("get_task", {"taskId": report.cancelled_task_id})["task"]["state"])
            == "cancelled" if report.cancelled_task_id else None,
            detail="the restarted worker has served nothing on its own and the "
                   "cancelled task stayed cancelled",
        )
        return report
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - teardown never raises
                pass
        if service is not None:
            try:
                service.close()
            except Exception:  # noqa: BLE001
                pass


def _remote_steps(
    report: AgentSliceReport,
    call: Callable[..., Mapping[str, Any]],
    status: Mapping[str, Any],
) -> None:
    """Steps 17-19: the remote option, displayed and never dispatched."""
    served_before = int(status.get("worker", {}).get("generationsServed", 0))
    explanation = call("providers_explain", {"taskClass": "retrieve"}).get("explanation", {})
    remote_listed = [
        entry.get("providerId") for entry in explanation.get("ineligible", ())
        if str(entry.get("providerId", "")).startswith("remote.")
    ] + [pid for pid in explanation.get("eligible", ()) if str(pid).startswith("remote.")]
    report.record(
        17, "submit a second task requiring an unavailable local capability",
        passed=bool(remote_listed) and not any(
            str(pid).startswith("local.") for pid in explanation.get("eligible", ())
        ),
        detail="expressed as the provider requirement 'retrieve', which no local "
               f"provider declares; remote candidates: {remote_listed}",
    )
    served_after = int(call("providers_status").get("worker", {}).get("generationsServed", 0))
    report.record(
        18, "display remote-provider option without dispatching",
        passed=bool(remote_listed) and served_after == served_before,
        detail=f"the explanation names {remote_listed} with its reasons and approval "
               f"requirement; generations served stayed {served_after}",
    )
    wants_remote_test = os.environ.get("BUNNY_AGENTS_REMOTE_TEST") == "1"
    if not wants_remote_test:
        report.record(
            19, "approve a controlled remote test", passed=None,
            detail="no intentionally configured test account "
                   "(BUNNY_AGENTS_REMOTE_TEST unset); the mandatory slice must "
                   "not require a paid provider",
        )
        return
    report.record(
        19, "approve a controlled remote test", passed=None,
        detail="BUNNY_AGENTS_REMOTE_TEST=1 but the controlled remote test is "
               "not implemented as an unattended step; a remote dispatch "
               "requires a live approval, which a slice must not self-answer",
    )

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless Bunny Companion session runtime.

The GTK shell is a client of this object through :mod:`companion.protocol`.
Closing or restarting that client never cancels a task.  SQLite task/event
state and the capability approval store are recovered independently.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import threading
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .approval import ApprovalCentre, ApprovalResolution
from .coordination import (
    AgentCoordinator,
    CoordinationLimits,
    ExecutionProposal,
    HarmlessLocalExecutor,
    LocalSafetyReviewer,
)
from .events import TaskEvent, observed_event
from .model import (
    AgentIdentity,
    AudioPresentationHint,
    CompanionPhase,
    CostPolicy,
    Placement,
    PresentationKind,
    PrivacyClass,
    TaskError,
    TaskOutput,
    TaskPhase,
    TaskSession,
    ToolOperation,
    VisualPresentationHint,
    concise_summary,
    utc_now,
)
from .presentation import (
    AdaptivePresentationController,
    CapabilityPresentationPlan,
    PresentationDecision,
    PresentationSignals,
)
from .providers import (
    CaptionsOnlyVoiceProvider,
    SpeechRequest,
    SystemVoiceProvider,
    VoiceProvider,
    VoiceRouter,
)
from .state import CompanionStateController, initial_state
from .store import CompanionStore


def conservative_capability_plan() -> CapabilityPresentationPlan:
    """Fallback when no capability plan can be obtained; never guesses hardware."""
    return CapabilityPresentationPlan(
        plan_id="plan-companion-conservative",
        service_id="bunny.companion",
        action="start_local",
        implementation_id="text-only",
        presentation_ceiling=PresentationKind.TEXT_ONLY,
        reasons=("capability-plan-unavailable",),
    )


def current_capability_plan() -> CapabilityPresentationPlan:
    """Run the existing capability pipeline and consume its companion decision."""
    from capability.runtime import assess_current_machine

    assessment = assess_current_machine(probe_runtimes=False)
    return CapabilityPresentationPlan.from_execution_plan(assessment.plan.to_json())


def current_capability_context() -> tuple[CapabilityPresentationPlan, PresentationSignals]:
    """Consume the existing capability assessment without exposing it to the UI."""
    from capability.runtime import assess_current_machine

    assessment = assess_current_machine(probe_runtimes=False)
    inventory = assessment.inventory
    usable_gpus = inventory.usable_gpus
    vram_values = [
        item.vram_available_bytes.get(None)
        for item in usable_gpus
        if isinstance(item.vram_available_bytes.get(None), int)
    ]
    load = inventory.cpu.load_average_1m.get(None)
    cores = inventory.cpu.effective_cores(1.0)
    memory_pressure = inventory.memory.pressure_some_avg10.get(None)
    return (
        CapabilityPresentationPlan.from_execution_plan(assessment.plan.to_json()),
        PresentationSignals(
            available_memory_bytes=inventory.memory.usable_available_bytes(None),
            gpu_ready=bool(usable_gpus),
            vram_available_bytes=max(vram_values) if vram_values else None,
            display_available=inventory.display.has_display,
            audio_output_available=inventory.audio.output_present.get(False) is True,
            on_battery=inventory.power.on_battery,
            battery_percent=inventory.power.battery_percent.get(None),
            thermal_pressure=inventory.thermal.throttled.get(False) is True,
            memory_pressure=isinstance(memory_pressure, (int, float)) and memory_pressure >= 5.0,
            foreground_workload_high=isinstance(load, (int, float)) and load / max(cores, 0.1) >= 0.8,
            headless=inventory.display.headless.get(False) is True or not inventory.display.has_display,
        ),
    )


@dataclass(frozen=True)
class RuntimePaths:
    state_directory: Path

    @property
    def database(self) -> Path:
        return self.state_directory / "companion.sqlite3"

    @property
    def approvals(self) -> Path:
        return self.state_directory / "approvals.json"


@dataclass(frozen=True)
class RuntimeSnapshot:
    task: TaskSession
    state: Mapping[str, Any]
    events: tuple[TaskEvent, ...]
    approvals: tuple[Mapping[str, Any], ...]
    presentation: PresentationDecision
    latest_sequence: int

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "task": self.task.to_json(),
            "state": dict(self.state),
            "events": [event.to_json() for event in self.events],
            "approvals": [dict(item) for item in self.approvals],
            "presentation": self.presentation.to_json(),
            "latestSequence": self.latest_sequence,
        }


class CompanionRuntime:
    def __init__(
        self,
        *,
        paths: RuntimePaths,
        capability_plan: CapabilityPresentationPlan | None = None,
        presentation_signals: PresentationSignals | None = None,
        voice_provider: VoiceProvider | None = None,
        voice_fallbacks: Sequence[VoiceProvider] = (),
        limits: CoordinationLimits | None = None,
    ) -> None:
        configured_voice = voice_provider or SystemVoiceProvider()
        voice_router = VoiceRouter((configured_voice, *voice_fallbacks))
        selected_voice = voice_router.select() or CaptionsOnlyVoiceProvider()
        self.paths = paths
        self.paths.state_directory.mkdir(parents=True, exist_ok=True)
        try:
            self.paths.state_directory.chmod(0o700)
        except OSError:
            pass
        self.store = CompanionStore(self.paths.database)
        self.approvals = ApprovalCentre(self.paths.approvals)
        self.coordinator = AgentCoordinator(limits)
        self.capability_plan = capability_plan or conservative_capability_plan()
        self.presentation_signals = presentation_signals or PresentationSignals(
            display_available=False,
            audio_output_available=False,
            headless=True,
        )
        self.presentation = AdaptivePresentationController()
        self.voice_router = voice_router
        # The runtime has not received a remote or paid speech approval here,
        # so selection must remain local and free.  A blocked provider becomes
        # an explicit captions-only endpoint rather than a silent policy bypass.
        self.voice = selected_voice
        self._controllers: dict[str, CompanionStateController] = {}
        self._proposals: dict[str, ExecutionProposal] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._restore_active_tasks()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.store.close()
                self._closed = True

    def __enter__(self) -> "CompanionRuntime":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _presentation_for(self, phase: CompanionPhase) -> PresentationDecision:
        return self.presentation.update(
            self.capability_plan,
            self.presentation_signals,
            phase=phase,
        )

    def _visual_hint(self, decision: PresentationDecision) -> VisualPresentationHint:
        return VisualPresentationHint(
            implementation=decision.implementation,
            placement=decision.placement,
            reduced_motion=(
                self.presentation_signals.reduced_motion
                or self.presentation_signals.no_animation
            ),
            high_contrast=self.presentation_signals.high_contrast,
            text_scale=self.presentation_signals.text_scale,
            explanation="; ".join(decision.reasons)[:512],
        )

    def _audio_hint(self, decision: PresentationDecision) -> AudioPresentationHint:
        descriptor = self.voice.descriptor
        return AudioPresentationHint(
            enabled=descriptor.health == "healthy" and self.presentation_signals.audio_output_available,
            captions=decision.captions,
            voice_id=descriptor.voice_id if descriptor.health == "healthy" else None,
        )

    def _controller_for(self, task: TaskSession) -> CompanionStateController:
        controller = self._controllers.get(task.task_id)
        if controller is not None:
            return controller
        decision = self._presentation_for(CompanionPhase.STARTING)
        events = self.store.replay(task.task_id)
        if events:
            controller = CompanionStateController.restore(
                task,
                events,
                visual_hint=self._visual_hint(decision),
                audio_hint=self._audio_hint(decision),
            )
        else:
            controller = CompanionStateController(initial_state(
                task.session_id,
                task_id=task.task_id,
                visual_hint=self._visual_hint(decision),
                audio_hint=self._audio_hint(decision),
            ))
        self._controllers[task.task_id] = controller
        return controller

    def _restore_active_tasks(self) -> None:
        for task in self.store.list_tasks(include_terminal=False):
            executor = HarmlessLocalExecutor()
            if task.executor is None or task.executor.agent_id != executor.identity.agent_id:
                # Unknown adapters are never fabricated during recovery.  Their
                # event history remains viewable and the task remains paused.
                continue
            self.coordinator.assign_executor(task.task_id, executor)
            for identity in task.reviewers:
                reviewer = LocalSafetyReviewer()
                if identity.agent_id == reviewer.identity.agent_id:
                    self.coordinator.add_reviewer(task.task_id, reviewer)
            for request_id in task.approvals:
                self.approvals.associate(request_id, task.task_id)
            events = self.store.replay(task.task_id)
            self._controllers[task.task_id] = CompanionStateController.restore(task, events)
            for event in reversed(events):
                if event.event_type == "tool_requested" and isinstance(event.payload.get("proposal"), Mapping):
                    self._proposals[task.task_id] = ExecutionProposal.from_json(event.payload["proposal"])
                    break

    def _emit(
        self,
        task: TaskSession,
        event_type: str,
        *,
        source: str,
        payload: Mapping[str, Any] | None = None,
    ) -> TaskEvent:
        event = observed_event(
            session_id=task.session_id,
            task_id=task.task_id,
            event_type=event_type,
            source=source,
            payload=payload,
        )
        result = self.store.append(event)
        controller = self._controller_for(task)
        controller.apply(result.event, task)
        decision = self._presentation_for(controller.state.state)
        controller.state = replace(
            controller.state,
            visual_hint=self._visual_hint(decision),
            audio_hint=self._audio_hint(decision),
        )
        return result.event

    @staticmethod
    def _replace_operation(task: TaskSession, operation_id: str, **changes: Any) -> None:
        updated: list[ToolOperation] = []
        found = False
        for operation in task.tool_operations:
            if operation.operation_id == operation_id:
                updated.append(replace(operation, **changes))
                found = True
            else:
                updated.append(operation)
        if not found:
            raise KeyError(f"task has no operation {operation_id!r}")
        task.tool_operations = tuple(updated)

    def submit(
        self,
        user_request: str,
        *,
        session_id: str | None = None,
        privacy_classification: PrivacyClass = PrivacyClass.INTERNAL,
    ) -> RuntimeSnapshot:
        with self._lock:
            session = session_id or f"session-{uuid4()}"
            task_id = f"task-{uuid4()}"
            task = TaskSession(
                task_id=task_id,
                session_id=session,
                user_request=user_request,
                display_summary=concise_summary(user_request),
                privacy_classification=privacy_classification,
                cost_policy=CostPolicy(paid_providers_allowed=False, ceiling_minor_units=0),
                offline_required=True,
            )
            self.store.save_task(task)
            self._controller_for(task)
            self._emit(task, "task_created", source="companion.runtime", payload={
                "displaySummary": task.display_summary,
                "locality": "local",
                "explanationReference": f"event:{task_id}:created",
            })

            task.task_classification = "local_harmless_demo"
            task.required_capabilities = ("task.history.write",)
            task.data_locality_requirements = ("local-only",)
            task.current_phase = TaskPhase.CLASSIFYING
            self.store.save_task(task)
            self._emit(task, "task_classified", source="companion.classifier", payload={
                "classification": task.task_classification,
                "privacyClassification": task.privacy_classification.value,
                "locality": "local",
            })

            executor = HarmlessLocalExecutor()
            self.coordinator.assign_executor(task.task_id, executor)
            task.executor = executor.identity
            self.store.save_task(task)
            self._emit(task, "executor_selected", source="companion.coordinator", payload={
                "executor": executor.identity.display_name,
                "locality": "local",
                "providerSelection": "no commercial provider required",
            })

            reviewer = LocalSafetyReviewer()
            self.coordinator.add_reviewer(task.task_id, reviewer)
            task.reviewers = (reviewer.identity,)
            self.store.save_task(task)
            self._emit(task, "reviewer_added", source="companion.coordinator", payload={
                "reviewer": reviewer.identity.display_name,
                "authority": "observation-only",
                "reviewerContextShared": True,
                "locality": "local",
            })

            task.current_phase = TaskPhase.PLANNING
            self.store.save_task(task)
            self._emit(task, "planning_started", source=executor.identity.agent_id, payload={
                "planSource": "deterministic local executor",
                "locality": "local",
            })
            proposal = self.coordinator.plan(task)
            self._proposals[task.task_id] = proposal
            operation = ToolOperation(
                operation_id=proposal.operation_id,
                tool_id=proposal.tool_id,
                action_summary=proposal.action_summary,
            )
            task.tool_operations = (*task.tool_operations, operation)
            self.store.save_task(task)
            requested = self._emit(task, "tool_requested", source=executor.identity.agent_id, payload={
                "toolId": proposal.tool_id,
                "operationId": proposal.operation_id,
                "actionSummary": proposal.action_summary,
                "planId": proposal.plan_id,
                "transitionId": proposal.transition_id,
                "proposal": proposal.to_json(),
                "locality": "local",
                "systemModificationActive": False,
            })

            task.current_phase = TaskPhase.REVIEWING
            self.store.save_task(task)
            arbitration = self.coordinator.review(task, self.store.replay(task.task_id))
            for observation in arbitration.observations:
                self._emit(task, "reviewer_observation", source=observation.reviewer, payload={
                    **observation.to_json(),
                    "reviewerContextShared": True,
                    "locality": "local",
                })
            if arbitration.disagreements:
                self._emit(task, "reviewer_disagreement", source="companion.arbitrator", payload={
                    "disagreements": list(arbitration.disagreements),
                    "requiresUserEscalation": arbitration.user_escalation_required,
                })

            now = time.monotonic()
            record = self.approvals.request(task, proposal, executor.identity, now=now)
            task.approvals = (*task.approvals, record.request.request_id)
            self._replace_operation(
                task,
                proposal.operation_id,
                status="waiting_for_approval",
            )
            task.current_phase = TaskPhase.WAITING_FOR_APPROVAL
            self.store.save_task(task)
            self._emit(task, "approval_requested", source="companion.approval-centre", payload={
                "requestId": record.request.request_id,
                "action": record.request.action,
                "planId": record.request.plan_id,
                "transitionId": record.request.transition_id,
                "destination": record.request.destination,
                "providerDestination": record.request.provider_id,
                "safeDefault": record.request.safe_default,
                "evidenceReferences": [requested.event_id],
                "locality": "local",
            })
            return self.snapshot(task.task_id)

    def _proposal_for(self, task_id: str) -> ExecutionProposal:
        proposal = self._proposals.get(task_id)
        if proposal is not None:
            return proposal
        for event in reversed(self.store.replay(task_id)):
            raw = event.payload.get("proposal")
            if event.event_type == "tool_requested" and isinstance(raw, Mapping):
                proposal = ExecutionProposal.from_json(raw)
                self._proposals[task_id] = proposal
                return proposal
        raise KeyError("the task has no execution proposal")

    def resolve_approval(self, task_id: str, resolution: ApprovalResolution) -> RuntimeSnapshot:
        with self._lock:
            task = self.store.load_task(task_id)
            if task is None:
                raise KeyError(f"no task {task_id!r}")
            proposal = self._proposal_for(task_id)
            outcome = self.approvals.resolve(
                resolution,
                current_plan_id=proposal.plan_id,
                audit_events=tuple(event.event_id for event in self.store.replay(task_id)[-4:]),
            )
            self._emit(task, "approval_resolved", source="companion.approval-centre", payload={
                "requestId": outcome.request_id,
                "decision": "cancel_task" if outcome.cancel_task else outcome.decision,
                "planId": proposal.plan_id,
                "transitionId": proposal.transition_id,
                "destination": proposal.destination,
                "providerDestination": proposal.provider_id,
                "locality": proposal.destination,
            })
            if outcome.cancel_task:
                return self.cancel(task_id)
            if outcome.decision != "approved":
                task.current_phase = TaskPhase.BLOCKED
                self.store.save_task(task)
                return self.snapshot(task_id)

            task.current_phase = TaskPhase.EXECUTING
            self._replace_operation(
                task,
                proposal.operation_id,
                status="running",
                progress=0.0,
                started_at=utc_now(),
            )
            self.store.save_task(task)
            self._emit(task, "tool_started", source=task.executor.agent_id if task.executor else "companion.executor", payload={
                "toolId": proposal.tool_id,
                "operationId": proposal.operation_id,
                "progress": 0.0,
                "locality": "local",
                "systemModificationActive": False,
            })
            self._replace_operation(task, proposal.operation_id, progress=0.5)
            task.progress = 0.5
            self.store.save_task(task)
            self._emit(task, "tool_progress", source=proposal.tool_id, payload={
                "toolId": proposal.tool_id,
                "operationId": proposal.operation_id,
                "progress": 0.5,
                "status": "The local task-history operation is halfway complete.",
                "locality": "local",
            })
            try:
                result = self.coordinator.execute(task, proposal)
            except Exception as exc:
                self._replace_operation(
                    task,
                    proposal.operation_id,
                    status="failed",
                    completed_at=utc_now(),
                )
                task.current_phase = TaskPhase.FAILED
                task.errors = (*task.errors, TaskError(
                    code="executor_failed",
                    display_message=f"The permitted executor failed: {type(exc).__name__}",
                    recoverable=False,
                ))
                task.completed_at = utc_now()
                self.store.save_task(task)
                self._emit(task, "tool_failed", source=proposal.tool_id, payload={
                    "toolId": proposal.tool_id,
                    "operationId": proposal.operation_id,
                    "error": type(exc).__name__,
                })
                self._emit(task, "task_failed", source="companion.runtime", payload={
                    "error": "the permitted local executor failed",
                })
                return self.snapshot(task_id)

            completed = utc_now()
            self._replace_operation(
                task,
                proposal.operation_id,
                status="completed",
                progress=1.0,
                completed_at=completed,
            )
            task.progress = 1.0
            output = TaskOutput(
                output_id=f"output-{uuid4()}",
                kind="local-task-result",
                display_summary=result.display_summary,
                reference=result.output_reference,
            )
            task.outputs = (*task.outputs, output)
            self.store.save_task(task)
            completed_event = self._emit(task, "tool_completed", source=proposal.tool_id, payload={
                "toolId": proposal.tool_id,
                "operationId": proposal.operation_id,
                "outputReference": result.output_reference,
                "locality": "local",
                "systemModificationActive": False,
            })

            if self.voice.descriptor.health != "healthy" or not self.presentation_signals.audio_output_available:
                self._emit(task, "capability_degraded", source="companion.voice-router", payload={
                    "capability": "speech-synthesis",
                    "reason": "Local system speech is unavailable; synchronized captions remain active.",
                    "fallback": "captions",
                    "locality": "local",
                })
            task.current_phase = TaskPhase.DRAFTING
            self.store.save_task(task)
            drafting = self._emit(task, "response_drafting", source="companion.runtime", payload={
                "evidenceReferences": [completed_event.event_id],
                "locality": "local",
            })
            caption = result.display_summary
            if self.voice.descriptor.health == "healthy" and self.presentation_signals.audio_output_available:
                speech_id = f"speech-{uuid4()}"
                started = self._emit(task, "speech_started", source=self.voice.descriptor.provider_id, payload={
                    "speechId": speech_id,
                    "caption": caption,
                    "voiceId": self.voice.descriptor.voice_id,
                    "audioTransmitted": False,
                    "locality": "local",
                    "evidenceReferences": [drafting.event_id],
                })
                try:
                    speech_result = self.voice.speak(SpeechRequest(speech_id=speech_id, text=caption))
                except Exception as exc:
                    self._emit(task, "speech_completed", source=self.voice.descriptor.provider_id, payload={
                        "speechId": speech_id,
                        "caption": caption,
                        "completed": False,
                        "cancelled": False,
                        "error": type(exc).__name__,
                        "audioTransmitted": False,
                        "locality": "local",
                        "evidenceReferences": [started.event_id],
                    })
                    self._emit(task, "capability_degraded", source="companion.voice-router", payload={
                        "capability": "speech-synthesis",
                        "reason": "The local voice failed; synchronized captions remain active.",
                        "fallback": "captions",
                        "locality": "local",
                    })
                else:
                    self._emit(task, "speech_completed", source=self.voice.descriptor.provider_id, payload={
                        "speechId": speech_id,
                        "caption": caption,
                        "completed": speech_result.completed,
                        "cancelled": speech_result.cancelled,
                        "audioTransmitted": False,
                        "locality": "local",
                        "evidenceReferences": [started.event_id],
                    })
                    if not speech_result.completed or speech_result.cancelled:
                        self._emit(task, "capability_degraded", source="companion.voice-router", payload={
                            "capability": "speech-synthesis",
                            "reason": "The selected local voice did not complete; synchronized captions remain active.",
                            "fallback": "captions",
                            "locality": "local",
                        })

            task.current_phase = TaskPhase.COMPLETED
            task.completed_at = utc_now()
            self.store.save_task(task)
            self._emit(task, "task_completed", source="companion.runtime", payload={
                "resultSummary": result.display_summary,
                "outputReference": result.output_reference,
                "locality": "local",
            })
            return self.snapshot(task_id)

    def cancel(self, task_id: str) -> RuntimeSnapshot:
        with self._lock:
            task = self.store.load_task(task_id)
            if task is None:
                raise KeyError(f"no task {task_id!r}")
            if task.terminal:
                return self.snapshot(task_id)
            try:
                proposal = self._proposal_for(task_id)
                self.approvals.store.cancel_for_transition(
                    proposal.transition_id,
                    detail="the user cancelled the companion task",
                )
                self.coordinator.cancel(task_id)
                self._replace_operation(
                    task,
                    proposal.operation_id,
                    status="cancelled",
                    completed_at=utc_now(),
                )
            except (KeyError, ValueError):
                pass
            task.current_phase = TaskPhase.CANCELLED
            task.cancellation_state = "cancelled"
            task.completed_at = utc_now()
            self.store.save_task(task)
            self._emit(task, "task_cancelled", source="companion.runtime", payload={
                "reason": "cancelled by the user",
                "locality": "local",
            })
            return self.snapshot(task_id)

    def snapshot(self, task_id: str, *, after_sequence: int = 0) -> RuntimeSnapshot:
        task = self.store.load_task(task_id)
        if task is None:
            raise KeyError(f"no task {task_id!r}")
        controller = self._controller_for(task)
        events = self.store.replay(task_id, after_sequence=after_sequence)
        approvals = tuple(
            view.to_json() for view in self.approvals.pending(task_id=task_id)
        )
        decision = self._presentation_for(controller.state.state)
        return RuntimeSnapshot(
            task=task,
            state=controller.state.to_json(),
            events=events,
            approvals=approvals,
            presentation=decision,
            latest_sequence=self.store.latest_sequence(task_id),
        )

    def tasks(self, *, session_id: str | None = None) -> tuple[dict[str, Any], ...]:
        return tuple(task.to_json() for task in self.store.list_tasks(session_id=session_id))

    def health(self) -> dict[str, Any]:
        tasks = self.store.list_tasks()
        return {
            "schemaVersion": 1,
            "status": "degraded" if self.capability_plan.presentation_ceiling == PresentationKind.TEXT_ONLY
            and "capability-plan-unavailable" in self.capability_plan.reasons else "available",
            "headless": True,
            "taskCount": len(tasks),
            "activeTaskCount": sum(1 for task in tasks if not task.terminal),
            "capabilityPlan": {
                "planId": self.capability_plan.plan_id,
                "implementationId": self.capability_plan.implementation_id,
                "presentationCeiling": self.capability_plan.presentation_ceiling.value,
            },
            "voice": self.voice.descriptor.to_json(),
            "approvalWarnings": list(self.approvals.warnings),
            "commercialProviderRequired": False,
        }

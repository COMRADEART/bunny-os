# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic projection from task events into companion presentation state."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .events import TaskEvent
from .model import (
    ApprovalState,
    AudioPresentationHint,
    CompanionPhase,
    CompanionState,
    Locality,
    PrivacyIndicator,
    TaskSession,
    VisualPresentationHint,
    bounded_text,
    redact_text,
    utc_now,
)


class InvalidStateTransition(ValueError):
    pass


# A transition that is not named here is refused.  Self-transitions are state
# updates (for example two tool_progress events) and are always permitted.
ALLOWED_TRANSITIONS: Mapping[CompanionPhase, frozenset[CompanionPhase]] = {
    CompanionPhase.UNAVAILABLE: frozenset({CompanionPhase.STARTING, CompanionPhase.DISCONNECTED}),
    CompanionPhase.STARTING: frozenset({
        CompanionPhase.IDLE, CompanionPhase.UNDERSTANDING, CompanionPhase.DEGRADED,
        CompanionPhase.ERROR, CompanionPhase.UNAVAILABLE, CompanionPhase.DISCONNECTED,
    }),
    CompanionPhase.IDLE: frozenset({
        CompanionPhase.GREETING, CompanionPhase.LISTENING, CompanionPhase.UNDERSTANDING,
        CompanionPhase.PLANNING, CompanionPhase.SLEEPING, CompanionPhase.DEGRADED,
        CompanionPhase.DISCONNECTED, CompanionPhase.ERROR,
    }),
    CompanionPhase.GREETING: frozenset({
        CompanionPhase.IDLE, CompanionPhase.LISTENING, CompanionPhase.UNDERSTANDING,
        CompanionPhase.SPEAKING, CompanionPhase.SLEEPING,
    }),
    CompanionPhase.LISTENING: frozenset({
        CompanionPhase.TRANSCRIBING, CompanionPhase.WAITING_FOR_USER,
        CompanionPhase.CANCELLED, CompanionPhase.ERROR, CompanionPhase.IDLE,
    }),
    CompanionPhase.TRANSCRIBING: frozenset({
        CompanionPhase.UNDERSTANDING, CompanionPhase.WAITING_FOR_USER,
        CompanionPhase.CANCELLED, CompanionPhase.ERROR,
    }),
    CompanionPhase.UNDERSTANDING: frozenset({
        CompanionPhase.PLANNING, CompanionPhase.WAITING_FOR_USER,
        CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.WORKING,
        CompanionPhase.BLOCKED, CompanionPhase.CANCELLED, CompanionPhase.ERROR,
        CompanionPhase.DEGRADED, CompanionPhase.DISCONNECTED,
    }),
    CompanionPhase.WAITING_FOR_USER: frozenset({
        CompanionPhase.LISTENING, CompanionPhase.UNDERSTANDING, CompanionPhase.PLANNING,
        CompanionPhase.CANCELLED, CompanionPhase.SLEEPING, CompanionPhase.IDLE,
    }),
    CompanionPhase.WAITING_FOR_APPROVAL: frozenset({
        CompanionPhase.WORKING, CompanionPhase.BLOCKED, CompanionPhase.CANCELLED,
        CompanionPhase.ERROR, CompanionPhase.DISCONNECTED, CompanionPhase.DEGRADED,
    }),
    CompanionPhase.PLANNING: frozenset({
        CompanionPhase.WORKING, CompanionPhase.REVIEWING,
        CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.WAITING_FOR_USER,
        CompanionPhase.BLOCKED, CompanionPhase.CANCELLED, CompanionPhase.ERROR,
        CompanionPhase.DEGRADED, CompanionPhase.DISCONNECTED,
    }),
    CompanionPhase.WORKING: frozenset({
        CompanionPhase.REVIEWING, CompanionPhase.WAITING_FOR_APPROVAL,
        CompanionPhase.PRESENTING_RESULT, CompanionPhase.SPEAKING,
        CompanionPhase.SUCCESS, CompanionPhase.WARNING, CompanionPhase.BLOCKED,
        CompanionPhase.PAUSED, CompanionPhase.CANCELLED, CompanionPhase.ERROR,
        CompanionPhase.DEGRADED, CompanionPhase.DISCONNECTED,
    }),
    CompanionPhase.REVIEWING: frozenset({
        CompanionPhase.PLANNING, CompanionPhase.WORKING,
        CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.PRESENTING_RESULT,
        CompanionPhase.WARNING, CompanionPhase.BLOCKED, CompanionPhase.SUCCESS,
        CompanionPhase.CANCELLED, CompanionPhase.ERROR, CompanionPhase.DEGRADED,
        CompanionPhase.DISCONNECTED,
    }),
    CompanionPhase.SPEAKING: frozenset({
        CompanionPhase.PRESENTING_RESULT, CompanionPhase.SUCCESS,
        CompanionPhase.WORKING, CompanionPhase.CANCELLED,
        CompanionPhase.ERROR, CompanionPhase.DEGRADED,
    }),
    CompanionPhase.PRESENTING_RESULT: frozenset({
        CompanionPhase.SPEAKING, CompanionPhase.SUCCESS, CompanionPhase.WARNING,
        CompanionPhase.WORKING, CompanionPhase.CANCELLED, CompanionPhase.ERROR,
        CompanionPhase.DEGRADED,
    }),
    CompanionPhase.SUCCESS: frozenset({
        CompanionPhase.IDLE, CompanionPhase.PRESENTING_RESULT, CompanionPhase.SPEAKING,
        CompanionPhase.SLEEPING, CompanionPhase.UNDERSTANDING,
    }),
    CompanionPhase.WARNING: frozenset({
        CompanionPhase.PLANNING, CompanionPhase.WORKING, CompanionPhase.REVIEWING,
        CompanionPhase.WAITING_FOR_USER, CompanionPhase.WAITING_FOR_APPROVAL,
        CompanionPhase.PRESENTING_RESULT, CompanionPhase.SUCCESS,
        CompanionPhase.BLOCKED, CompanionPhase.CANCELLED, CompanionPhase.ERROR,
    }),
    CompanionPhase.BLOCKED: frozenset({
        CompanionPhase.WAITING_FOR_USER, CompanionPhase.WAITING_FOR_APPROVAL,
        CompanionPhase.PLANNING, CompanionPhase.WORKING, CompanionPhase.CANCELLED,
        CompanionPhase.ERROR, CompanionPhase.IDLE,
    }),
    CompanionPhase.DEGRADED: frozenset({
        CompanionPhase.IDLE, CompanionPhase.PLANNING, CompanionPhase.WORKING,
        CompanionPhase.REVIEWING, CompanionPhase.PRESENTING_RESULT,
        CompanionPhase.SUCCESS, CompanionPhase.BLOCKED, CompanionPhase.ERROR,
        CompanionPhase.DISCONNECTED, CompanionPhase.CANCELLED,
    }),
    CompanionPhase.ERROR: frozenset({
        CompanionPhase.STARTING, CompanionPhase.IDLE, CompanionPhase.PLANNING,
        CompanionPhase.WORKING, CompanionPhase.BLOCKED, CompanionPhase.CANCELLED,
    }),
    CompanionPhase.PAUSED: frozenset({
        CompanionPhase.PLANNING, CompanionPhase.WORKING, CompanionPhase.CANCELLED,
        CompanionPhase.ERROR, CompanionPhase.SLEEPING,
    }),
    CompanionPhase.CANCELLED: frozenset({
        CompanionPhase.IDLE, CompanionPhase.UNDERSTANDING, CompanionPhase.SLEEPING,
    }),
    CompanionPhase.DISCONNECTED: frozenset({
        CompanionPhase.STARTING, CompanionPhase.IDLE, CompanionPhase.UNDERSTANDING,
        CompanionPhase.PLANNING, CompanionPhase.WORKING, CompanionPhase.REVIEWING,
        CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.DEGRADED,
        CompanionPhase.ERROR, CompanionPhase.CANCELLED,
    }),
    CompanionPhase.SLEEPING: frozenset({
        CompanionPhase.STARTING, CompanionPhase.IDLE, CompanionPhase.GREETING,
        CompanionPhase.LISTENING, CompanionPhase.UNDERSTANDING,
    }),
}


EVENT_STATES: Mapping[str, CompanionPhase] = {
    "task_created": CompanionPhase.UNDERSTANDING,
    "task_classified": CompanionPhase.UNDERSTANDING,
    "executor_selected": CompanionPhase.PLANNING,
    "reviewer_added": CompanionPhase.PLANNING,
    "planning_started": CompanionPhase.PLANNING,
    "tool_requested": CompanionPhase.WORKING,
    "approval_requested": CompanionPhase.WAITING_FOR_APPROVAL,
    "tool_started": CompanionPhase.WORKING,
    "tool_progress": CompanionPhase.WORKING,
    "tool_completed": CompanionPhase.WORKING,
    "tool_failed": CompanionPhase.ERROR,
    "reviewer_observation": CompanionPhase.REVIEWING,
    "reviewer_disagreement": CompanionPhase.WARNING,
    "response_drafting": CompanionPhase.PRESENTING_RESULT,
    "speech_started": CompanionPhase.SPEAKING,
    "speech_completed": CompanionPhase.PRESENTING_RESULT,
    "task_completed": CompanionPhase.SUCCESS,
    "task_cancelled": CompanionPhase.CANCELLED,
    "task_failed": CompanionPhase.ERROR,
    "capability_degraded": CompanionPhase.DEGRADED,
    "connection_lost": CompanionPhase.DISCONNECTED,
}


def initial_state(
    session_id: str,
    *,
    task_id: str | None = None,
    visual_hint: VisualPresentationHint | None = None,
    audio_hint: AudioPresentationHint | None = None,
) -> CompanionState:
    return CompanionState(
        session_id=session_id,
        task_id=task_id,
        state=CompanionPhase.STARTING,
        state_revision=0,
        started_at=utc_now(),
        status_text="Starting the Bunny companion runtime.",
        visual_hint=visual_hint or VisualPresentationHint(),
        audio_hint=audio_hint or AudioPresentationHint(),
    )


def _payload_text(payload: Mapping[str, Any], key: str, fallback: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return fallback
    return redact_text(value, 240)


def status_for_event(event: TaskEvent) -> str:
    payload = event.payload
    if event.record_kind == "generated_description" and event.description:
        return redact_text(event.description, 512)
    messages = {
        "task_created": "Received the task and created a private session record.",
        "task_classified": f"Classified the task as {_payload_text(payload, 'classification', 'local work')}.",
        "executor_selected": f"Selected {_payload_text(payload, 'executor', 'the permitted executor')}.",
        "reviewer_added": f"Added {_payload_text(payload, 'reviewer', 'an observation-only reviewer')}.",
        "planning_started": "Preparing the permitted execution plan.",
        "tool_requested": f"Prepared {_payload_text(payload, 'actionSummary', 'a tool operation')}.",
        "approval_requested": f"Waiting for approval: {_payload_text(payload, 'action', 'requested action')}.",
        "tool_started": f"Using {_payload_text(payload, 'toolId', 'the selected tool')}.",
        "tool_progress": _payload_text(payload, "status", "The tool reported progress."),
        "tool_completed": f"Completed {_payload_text(payload, 'toolId', 'the tool operation')}.",
        "tool_failed": f"The tool failed: {_payload_text(payload, 'error', 'no additional detail')}.",
        "reviewer_observation": f"Reviewer observation: {_payload_text(payload, 'summary', 'review completed')}.",
        "reviewer_disagreement": "Reviewers materially disagree; their observations are preserved for review.",
        "response_drafting": "Preparing the result from recorded task events.",
        "speech_started": _payload_text(payload, "caption", "Speaking the result."),
        "speech_completed": _payload_text(payload, "caption", "Finished speaking the result."),
        "task_completed": _payload_text(payload, "resultSummary", "The task completed successfully."),
        "task_cancelled": "The task was cancelled; no further action will be taken.",
        "task_failed": f"The task failed: {_payload_text(payload, 'error', 'no additional detail')}.",
        "capability_degraded": _payload_text(payload, "reason", "Presentation capability was reduced."),
        "connection_lost": "The runtime connection was lost; the task may continue headlessly.",
        "connection_restored": "The runtime connection was restored and task events were replayed.",
        "approval_resolved": f"Approval was {_payload_text(payload, 'decision', 'resolved')}.",
    }
    return messages[event.event_type]


class CompanionStateController:
    def __init__(self, state: CompanionState) -> None:
        self.state = state
        self._before_disconnect: CompanionPhase | None = None

    def transition(
        self,
        target: CompanionPhase,
        *,
        status_text: str,
        started_at: str | None = None,
        **changes: Any,
    ) -> CompanionState:
        bounded_text(status_text, "status text", 512)
        current = self.state.state
        if target != current and target not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransition(f"companion cannot transition from {current.value} to {target.value}")
        self.state = replace(
            self.state,
            state=target,
            state_revision=self.state.state_revision + 1,
            started_at=started_at or utc_now(),
            status_text=status_text,
            **changes,
        )
        return self.state

    def apply(self, event: TaskEvent, task: TaskSession) -> CompanionState:
        if event.task_id != task.task_id or event.session_id != task.session_id:
            raise ValueError("event does not belong to the projected task")
        target = EVENT_STATES.get(event.event_type)
        payload = event.payload
        approval = self.state.approval_state
        active_tool = self.state.active_tool
        progress = self.state.progress
        privacy = self.state.privacy_indicator

        if event.event_type == "approval_requested":
            approval = ApprovalState.PENDING
        elif event.event_type == "approval_resolved":
            decision = str(payload.get("decision", "denied"))
            if decision in {"approved", "granted"}:
                approval = ApprovalState.APPROVED
                target = CompanionPhase.WORKING
            elif decision == "expired":
                approval = ApprovalState.EXPIRED
                target = CompanionPhase.BLOCKED
            elif decision in {"cancelled", "cancel_task"}:
                approval = ApprovalState.CANCELLED
                target = CompanionPhase.CANCELLED
            else:
                approval = ApprovalState.DENIED
                target = CompanionPhase.BLOCKED
        elif event.event_type in {"tool_started", "tool_progress"}:
            tool = payload.get("toolId")
            active_tool = str(tool) if isinstance(tool, str) and tool else active_tool
            if payload.get("progress") is not None:
                progress = max(0.0, min(1.0, float(payload["progress"])))
        elif event.event_type in {"tool_completed", "tool_failed"}:
            active_tool = None
            if event.event_type == "tool_completed":
                progress = 1.0

        if event.event_type == "connection_lost":
            self._before_disconnect = self.state.state
        elif event.event_type == "connection_restored":
            requested = payload.get("resumeState")
            if isinstance(requested, str):
                try:
                    target = CompanionPhase(requested)
                except ValueError:
                    target = None
            if target is None:
                target = self._before_disconnect or CompanionPhase.IDLE

        locality_text = payload.get("locality")
        locality = self.state.execution_indicator
        if isinstance(locality_text, str) and locality_text in {item.value for item in Locality}:
            locality = Locality(locality_text)
        privacy = replace(
            privacy,
            remote_provider_active=bool(payload.get("remoteProviderActive", privacy.remote_provider_active)),
            screen_context_shared=bool(payload.get("screenContextShared", privacy.screen_context_shared)),
            audio_transmitted=bool(payload.get("audioTransmitted", privacy.audio_transmitted)),
            paid_service_active=bool(payload.get("paidServiceActive", privacy.paid_service_active)),
            reviewer_context_shared=bool(payload.get("reviewerContextShared", privacy.reviewer_context_shared)),
            system_modification_active=bool(payload.get("systemModificationActive", privacy.system_modification_active)),
            microphone_active=bool(payload.get("microphoneActive", privacy.microphone_active)),
        )

        if target is None:
            target = self.state.state
        return self.transition(
            target,
            status_text=status_for_event(event),
            started_at=event.occurred_at,
            task_id=task.task_id,
            progress=progress,
            active_tool=active_tool,
            active_executor=task.executor,
            active_reviewers=task.reviewers,
            approval_state=approval,
            privacy_indicator=privacy,
            execution_indicator=locality,
            explanation_reference=str(payload["explanationReference"])
            if payload.get("explanationReference") else self.state.explanation_reference,
        )

    @classmethod
    def restore(
        cls,
        task: TaskSession,
        events: Iterable[TaskEvent],
        *,
        visual_hint: VisualPresentationHint | None = None,
        audio_hint: AudioPresentationHint | None = None,
    ) -> "CompanionStateController":
        controller = cls(initial_state(
            task.session_id,
            task_id=task.task_id,
            visual_hint=visual_hint,
            audio_hint=audio_hint,
        ))
        last_sequence = 0
        for event in events:
            if event.sequence != last_sequence + 1:
                raise ValueError(
                    f"cannot restore task {task.task_id}: expected event {last_sequence + 1}, got {event.sequence}"
                )
            controller.apply(event, task)
            last_sequence = event.sequence
        return controller

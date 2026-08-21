# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned, typed records shared by the companion runtime and its UIs.

These records contain displayable facts and deterministic explanations only.
They have no field for model chain-of-thought, provider credentials, or raw
tool payloads.  The presentation layer consumes these values; it does not
recalculate routing, approval, security, or execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Mapping, Sequence

from . import COMPANION_STATE_SCHEMA_VERSION, TASK_SCHEMA_VERSION

MAX_USER_REQUEST_CHARS = 4096
MAX_STATUS_CHARS = 512
MAX_DISPLAY_SUMMARY_CHARS = 280
MAX_COLLECTION_ITEMS = 256

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization)"
        r"\s*([:=])\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be a UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a timestamp") from exc
    return value


def safe_identifier(value: str, field_name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid {field_name}")
    return value


def bounded_text(value: Any, field_name: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def redact_text(value: str, maximum: int = MAX_USER_REQUEST_CHARS) -> str:
    """Remove common credential shapes and bound a persisted/display value."""
    bounded = str(value)[:maximum]
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)\\b(api"):
            bounded = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", bounded)
        else:
            bounded = pattern.sub("[REDACTED]", bounded)
    return bounded


def request_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


class CompanionPhase(str, Enum):
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    IDLE = "idle"
    GREETING = "greeting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PLANNING = "planning"
    WORKING = "working"
    REVIEWING = "reviewing"
    SPEAKING = "speaking"
    PRESENTING_RESULT = "presenting_result"
    SUCCESS = "success"
    WARNING = "warning"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"
    SLEEPING = "sleeping"


class TaskPhase(str, Enum):
    CREATED = "created"
    CLASSIFYING = "classifying"
    PLANNING = "planning"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    DRAFTING = "drafting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class ApprovalState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Locality(str, Enum):
    NONE = "none"
    LOCAL = "local"
    REMOTE = "remote"
    HYBRID = "hybrid"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class PresentationKind(str, Enum):
    TEXT_ONLY = "text-only"
    AUDIO_ONLY = "audio-only"
    STATIC_IMAGE = "static-image"
    ANIMATED_2D = "animated-2d"
    LIGHTWEIGHT_3D = "lightweight-3d"
    FULL_3D = "full-3d"


class Placement(str, Enum):
    CENTER = "center"
    DOCKED = "docked"
    COMPACT = "compact"
    TASK_PANEL = "task-panel"
    SPEECH_BUBBLE = "speech-bubble"


@dataclass(frozen=True)
class CostPolicy:
    paid_providers_allowed: bool = False
    ceiling_minor_units: int = 0
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.ceiling_minor_units < 0:
            raise ValueError("cost ceiling cannot be negative")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter code")

    def to_json(self) -> dict[str, Any]:
        return {
            "paidProvidersAllowed": self.paid_providers_allowed,
            "ceilingMinorUnits": self.ceiling_minor_units,
            "currency": self.currency,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CostPolicy":
        return cls(
            paid_providers_allowed=bool(value.get("paidProvidersAllowed", False)),
            ceiling_minor_units=int(value.get("ceilingMinorUnits", 0)),
            currency=str(value.get("currency", "USD")),
        )


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    provider_id: str | None = None
    model_id: str | None = None
    locality: Locality = Locality.LOCAL

    def __post_init__(self) -> None:
        safe_identifier(self.agent_id, "agent id")
        if self.provider_id is not None:
            safe_identifier(self.provider_id, "provider id")
        if self.model_id is not None:
            safe_identifier(self.model_id, "model id")

    @property
    def display_name(self) -> str:
        if self.provider_id and self.model_id:
            return f"{self.provider_id}/{self.model_id}"
        return self.agent_id

    def to_json(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "locality": self.locality.value,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "AgentIdentity":
        return cls(
            agent_id=str(value.get("agentId", "")),
            provider_id=str(value["providerId"]) if value.get("providerId") else None,
            model_id=str(value["modelId"]) if value.get("modelId") else None,
            locality=Locality(str(value.get("locality", "local"))),
        )


@dataclass(frozen=True)
class ReviewerObservation:
    reviewer: str
    severity: str
    category: str
    summary: str
    suggested_action: str
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        safe_identifier(self.reviewer, "reviewer")
        if self.severity not in {"info", "warning", "critical"}:
            raise ValueError("reviewer severity is invalid")
        if self.category not in {"correctness", "security", "quality", "performance", "privacy"}:
            raise ValueError("reviewer category is invalid")
        bounded_text(self.summary, "reviewer summary", 1000)
        bounded_text(self.suggested_action, "suggested action", 1000)
        if len(self.evidence_references) > 64:
            raise ValueError("too many evidence references")
        for reference in self.evidence_references:
            safe_identifier(reference, "evidence reference")

    def to_json(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "severity": self.severity,
            "category": self.category,
            "summary": redact_text(self.summary, 1000),
            "suggestedAction": redact_text(self.suggested_action, 1000),
            "evidenceReferences": list(self.evidence_references),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReviewerObservation":
        return cls(
            reviewer=str(value.get("reviewer", "")),
            severity=str(value.get("severity", "")),
            category=str(value.get("category", "")),
            summary=str(value.get("summary", "")),
            suggested_action=str(value.get("suggestedAction", "")),
            evidence_references=tuple(str(item) for item in value.get("evidenceReferences", ())),
        )


@dataclass(frozen=True)
class ToolOperation:
    operation_id: str
    tool_id: str
    action_summary: str
    status: str = "requested"
    progress: float | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.operation_id, "operation id")
        safe_identifier(self.tool_id, "tool id")
        bounded_text(self.action_summary, "tool action summary", 512)
        if self.status not in {"requested", "waiting_for_approval", "running", "completed", "failed", "cancelled"}:
            raise ValueError("tool operation status is invalid")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("tool progress must be between zero and one")

    def to_json(self) -> dict[str, Any]:
        return {
            "operationId": self.operation_id,
            "toolId": self.tool_id,
            "actionSummary": redact_text(self.action_summary, 512),
            "status": self.status,
            "progress": self.progress,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ToolOperation":
        return cls(
            operation_id=str(value.get("operationId", "")),
            tool_id=str(value.get("toolId", "")),
            action_summary=str(value.get("actionSummary", "")),
            status=str(value.get("status", "requested")),
            progress=float(value["progress"]) if value.get("progress") is not None else None,
            started_at=str(value["startedAt"]) if value.get("startedAt") else None,
            completed_at=str(value["completedAt"]) if value.get("completedAt") else None,
        )


@dataclass(frozen=True)
class TaskOutput:
    output_id: str
    kind: str
    display_summary: str
    reference: str | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.output_id, "output id")
        safe_identifier(self.kind, "output kind")
        bounded_text(self.display_summary, "output summary", 2000)
        if self.reference is not None:
            safe_identifier(self.reference, "output reference")

    def to_json(self) -> dict[str, Any]:
        return {
            "outputId": self.output_id,
            "kind": self.kind,
            "displaySummary": redact_text(self.display_summary, 2000),
            "reference": self.reference,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TaskOutput":
        return cls(
            output_id=str(value.get("outputId", "")),
            kind=str(value.get("kind", "")),
            display_summary=str(value.get("displaySummary", "")),
            reference=str(value["reference"]) if value.get("reference") else None,
        )


@dataclass(frozen=True)
class TaskError:
    code: str
    display_message: str
    recoverable: bool = False
    explanation_reference: str | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.code, "error code")
        bounded_text(self.display_message, "error message", 1000)
        if self.explanation_reference is not None:
            safe_identifier(self.explanation_reference, "explanation reference")

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "displayMessage": redact_text(self.display_message, 1000),
            "recoverable": self.recoverable,
            "explanationReference": self.explanation_reference,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TaskError":
        return cls(
            code=str(value.get("code", "")),
            display_message=str(value.get("displayMessage", "")),
            recoverable=bool(value.get("recoverable", False)),
            explanation_reference=str(value["explanationReference"]) if value.get("explanationReference") else None,
        )


@dataclass
class TaskSession:
    task_id: str
    session_id: str
    user_request: str
    display_summary: str
    task_classification: str = "unclassified"
    required_capabilities: tuple[str, ...] = ()
    privacy_classification: PrivacyClass = PrivacyClass.INTERNAL
    data_locality_requirements: tuple[str, ...] = ("local",)
    cost_policy: CostPolicy = field(default_factory=CostPolicy)
    latency_preference: str = "balanced"
    offline_required: bool = False
    executor: AgentIdentity | None = None
    reviewers: tuple[AgentIdentity, ...] = ()
    current_phase: TaskPhase = TaskPhase.CREATED
    progress: float | None = None
    approvals: tuple[str, ...] = ()
    tool_operations: tuple[ToolOperation, ...] = ()
    outputs: tuple[TaskOutput, ...] = ()
    errors: tuple[TaskError, ...] = ()
    cancellation_state: str = "active"
    created_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    audit_references: tuple[str, ...] = ()
    request_sha256: str = ""

    def __post_init__(self) -> None:
        safe_identifier(self.task_id, "task id")
        safe_identifier(self.session_id, "session id")
        self.user_request = redact_text(
            bounded_text(self.user_request, "user request", MAX_USER_REQUEST_CHARS),
            MAX_USER_REQUEST_CHARS,
        )
        self.display_summary = redact_text(
            bounded_text(self.display_summary, "display summary", MAX_DISPLAY_SUMMARY_CHARS),
            MAX_DISPLAY_SUMMARY_CHARS,
        )
        safe_identifier(self.task_classification, "task classification")
        if self.latency_preference not in {"interactive", "balanced", "throughput"}:
            raise ValueError("latency preference is invalid")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("task progress must be between zero and one")
        if self.cancellation_state not in {"active", "requested", "cancelled"}:
            raise ValueError("cancellation state is invalid")
        validate_timestamp(self.created_at, "createdAt")
        if self.completed_at is not None:
            validate_timestamp(self.completed_at, "completedAt")
        for collection_name, collection in (
            ("required capabilities", self.required_capabilities),
            ("data locality requirements", self.data_locality_requirements),
            ("reviewers", self.reviewers),
            ("approvals", self.approvals),
            ("tool operations", self.tool_operations),
            ("outputs", self.outputs),
            ("errors", self.errors),
            ("audit references", self.audit_references),
        ):
            if len(collection) > MAX_COLLECTION_ITEMS:
                raise ValueError(f"too many {collection_name}")
        if not self.request_sha256:
            self.request_sha256 = request_digest(self.user_request)

    @property
    def terminal(self) -> bool:
        return self.current_phase in {TaskPhase.COMPLETED, TaskPhase.FAILED, TaskPhase.CANCELLED}

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": TASK_SCHEMA_VERSION,
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "userRequest": self.user_request,
            "userRequestSha256": self.request_sha256,
            "displaySummary": self.display_summary,
            "taskClassification": self.task_classification,
            "requiredCapabilities": list(self.required_capabilities),
            "privacyClassification": self.privacy_classification.value,
            "dataLocalityRequirements": list(self.data_locality_requirements),
            "costPolicy": self.cost_policy.to_json(),
            "latencyPreference": self.latency_preference,
            "offlineRequired": self.offline_required,
            "executor": self.executor.to_json() if self.executor else None,
            "reviewers": [item.to_json() for item in self.reviewers],
            "currentPhase": self.current_phase.value,
            "progress": self.progress,
            "approvals": list(self.approvals),
            "toolOperations": [item.to_json() for item in self.tool_operations],
            "outputs": [item.to_json() for item in self.outputs],
            "errors": [item.to_json() for item in self.errors],
            "cancellationState": self.cancellation_state,
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
            "auditReferences": list(self.audit_references),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TaskSession":
        if value.get("schemaVersion") != TASK_SCHEMA_VERSION:
            raise ValueError("unsupported task schemaVersion")
        executor = value.get("executor")
        return cls(
            task_id=str(value.get("taskId", "")),
            session_id=str(value.get("sessionId", "")),
            user_request=str(value.get("userRequest", "")),
            request_sha256=str(value.get("userRequestSha256", "")),
            display_summary=str(value.get("displaySummary", "")),
            task_classification=str(value.get("taskClassification", "unclassified")),
            required_capabilities=tuple(str(item) for item in value.get("requiredCapabilities", ())),
            privacy_classification=PrivacyClass(str(value.get("privacyClassification", "internal"))),
            data_locality_requirements=tuple(str(item) for item in value.get("dataLocalityRequirements", ())),
            cost_policy=CostPolicy.from_json(value.get("costPolicy") or {}),
            latency_preference=str(value.get("latencyPreference", "balanced")),
            offline_required=bool(value.get("offlineRequired", False)),
            executor=AgentIdentity.from_json(executor) if isinstance(executor, Mapping) else None,
            reviewers=tuple(AgentIdentity.from_json(item) for item in value.get("reviewers", ()) if isinstance(item, Mapping)),
            current_phase=TaskPhase(str(value.get("currentPhase", "created"))),
            progress=float(value["progress"]) if value.get("progress") is not None else None,
            approvals=tuple(str(item) for item in value.get("approvals", ())),
            tool_operations=tuple(ToolOperation.from_json(item) for item in value.get("toolOperations", ()) if isinstance(item, Mapping)),
            outputs=tuple(TaskOutput.from_json(item) for item in value.get("outputs", ()) if isinstance(item, Mapping)),
            errors=tuple(TaskError.from_json(item) for item in value.get("errors", ()) if isinstance(item, Mapping)),
            cancellation_state=str(value.get("cancellationState", "active")),
            created_at=str(value.get("createdAt", "")),
            completed_at=str(value["completedAt"]) if value.get("completedAt") else None,
            audit_references=tuple(str(item) for item in value.get("auditReferences", ())),
        )


@dataclass(frozen=True)
class VisualPresentationHint:
    implementation: PresentationKind = PresentationKind.TEXT_ONLY
    placement: Placement = Placement.CENTER
    reduced_motion: bool = False
    high_contrast: bool = False
    text_scale: float = 1.0
    explanation: str = ""

    def __post_init__(self) -> None:
        if not 0.75 <= self.text_scale <= 3.0:
            raise ValueError("text scale is outside the supported range")
        bounded_text(self.explanation, "visual explanation", 512, allow_empty=True)

    def to_json(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation.value,
            "placement": self.placement.value,
            "reducedMotion": self.reduced_motion,
            "highContrast": self.high_contrast,
            "textScale": self.text_scale,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class AudioPresentationHint:
    enabled: bool = False
    captions: bool = True
    voice_id: str | None = None
    speech_rate: float = 1.0
    transmitting: bool = False

    def __post_init__(self) -> None:
        if not 0.5 <= self.speech_rate <= 2.0:
            raise ValueError("speech rate is outside the supported range")
        if self.voice_id is not None:
            safe_identifier(self.voice_id, "voice id")

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "captions": self.captions,
            "voiceId": self.voice_id,
            "speechRate": self.speech_rate,
            "transmitting": self.transmitting,
        }


@dataclass(frozen=True)
class PrivacyIndicator:
    classification: PrivacyClass = PrivacyClass.INTERNAL
    remote_provider_active: bool = False
    screen_context_shared: bool = False
    audio_transmitted: bool = False
    paid_service_active: bool = False
    reviewer_context_shared: bool = False
    system_modification_active: bool = False
    microphone_active: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "remoteProviderActive": self.remote_provider_active,
            "screenContextShared": self.screen_context_shared,
            "audioTransmitted": self.audio_transmitted,
            "paidServiceActive": self.paid_service_active,
            "reviewerContextShared": self.reviewer_context_shared,
            "systemModificationActive": self.system_modification_active,
            "microphoneActive": self.microphone_active,
        }


@dataclass(frozen=True)
class CompanionState:
    session_id: str
    task_id: str | None
    state: CompanionPhase
    state_revision: int
    started_at: str
    status_text: str
    progress: float | None = None
    active_tool: str | None = None
    active_executor: AgentIdentity | None = None
    active_reviewers: tuple[AgentIdentity, ...] = ()
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    visual_hint: VisualPresentationHint = field(default_factory=VisualPresentationHint)
    audio_hint: AudioPresentationHint = field(default_factory=AudioPresentationHint)
    privacy_indicator: PrivacyIndicator = field(default_factory=PrivacyIndicator)
    execution_indicator: Locality = Locality.NONE
    explanation_reference: str | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.session_id, "session id")
        if self.task_id is not None:
            safe_identifier(self.task_id, "task id")
        if self.state_revision < 0:
            raise ValueError("state revision cannot be negative")
        validate_timestamp(self.started_at, "state start timestamp")
        bounded_text(self.status_text, "status text", MAX_STATUS_CHARS)
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("state progress must be between zero and one")
        if self.active_tool is not None:
            safe_identifier(self.active_tool, "active tool")
        if self.explanation_reference is not None:
            safe_identifier(self.explanation_reference, "explanation reference")

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": COMPANION_STATE_SCHEMA_VERSION,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "state": self.state.value,
            "stateRevision": self.state_revision,
            "startedAt": self.started_at,
            "statusText": redact_text(self.status_text, MAX_STATUS_CHARS),
            "progress": self.progress,
            "activeTool": self.active_tool,
            "activeExecutor": self.active_executor.to_json() if self.active_executor else None,
            "activeReviewers": [item.to_json() for item in self.active_reviewers],
            "approvalState": self.approval_state.value,
            "visualPresentationHint": self.visual_hint.to_json(),
            "audioPresentationHint": self.audio_hint.to_json(),
            "privacyIndicator": self.privacy_indicator.to_json(),
            "executionIndicator": self.execution_indicator.value,
            "explanationReference": self.explanation_reference,
        }


def concise_summary(request: str) -> str:
    redacted = " ".join(redact_text(request).split())
    return redacted[:MAX_DISPLAY_SUMMARY_CHARS] or "Local companion task"


def string_tuple(values: Sequence[Any], field_name: str) -> tuple[str, ...]:
    result = tuple(str(item) for item in values)
    if len(result) > MAX_COLLECTION_ITEMS:
        raise ValueError(f"too many {field_name}")
    return result

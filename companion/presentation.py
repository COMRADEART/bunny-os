# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-plan-bounded adaptive presentation and desktop window policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .model import CompanionPhase, Placement, PresentationKind

MIB = 1024 * 1024
GIB = 1024 * MIB

_LADDER = (
    PresentationKind.FULL_3D,
    PresentationKind.LIGHTWEIGHT_3D,
    PresentationKind.ANIMATED_2D,
    PresentationKind.STATIC_IMAGE,
    PresentationKind.AUDIO_ONLY,
    PresentationKind.TEXT_ONLY,
)
_RANK = {item: index for index, item in enumerate(_LADDER)}
_CAPABILITY_IMPLEMENTATIONS = {
    "animated-3d": PresentationKind.FULL_3D,
    "full-3d": PresentationKind.FULL_3D,
    "lightweight-3d": PresentationKind.LIGHTWEIGHT_3D,
    "animated-2d": PresentationKind.ANIMATED_2D,
    "static-avatar": PresentationKind.STATIC_IMAGE,
    "static-image": PresentationKind.STATIC_IMAGE,
    "audio-only": PresentationKind.AUDIO_ONLY,
    "text-only": PresentationKind.TEXT_ONLY,
}


@dataclass(frozen=True)
class CapabilityPresentationPlan:
    plan_id: str
    service_id: str
    action: str
    implementation_id: str | None
    presentation_ceiling: PresentationKind
    requires_approval: bool = False
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_execution_plan(cls, document: Mapping[str, Any]) -> "CapabilityPresentationPlan":
        identity = document.get("identity") if isinstance(document.get("identity"), Mapping) else {}
        plan_id = str(identity.get("planId") or document.get("planId") or "plan-unidentified")
        decisions = document.get("decisions")
        if not isinstance(decisions, Sequence):
            raise ValueError("capability plan has no decisions")
        selected: Mapping[str, Any] | None = None
        for decision in decisions:
            if isinstance(decision, Mapping) and decision.get("serviceId") == "bunny.companion":
                selected = decision
                break
        if selected is None:
            raise ValueError("capability plan has no bunny.companion decision")
        implementation = selected.get("implementationId")
        ceiling = _CAPABILITY_IMPLEMENTATIONS.get(str(implementation), PresentationKind.TEXT_ONLY)
        reasons = tuple(
            str(item.get("code"))
            for item in selected.get("reasons", ())
            if isinstance(item, Mapping) and item.get("code")
        )
        return cls(
            plan_id=plan_id,
            service_id="bunny.companion",
            action=str(selected.get("action", "reject")),
            implementation_id=str(implementation) if implementation else None,
            presentation_ceiling=ceiling,
            requires_approval=bool(selected.get("requiresApproval", False)),
            reasons=reasons,
        )


@dataclass(frozen=True)
class PresentationSignals:
    available_memory_bytes: int | None = None
    gpu_ready: bool = False
    vram_available_bytes: int | None = None
    display_available: bool = True
    audio_output_available: bool = True
    on_battery: bool = False
    battery_percent: float | None = None
    thermal_pressure: bool = False
    memory_pressure: bool = False
    gpu_pressure: bool = False
    foreground_workload_high: bool = False
    headless: bool = False
    user_preference: PresentationKind | None = None
"""What the user's screen is allowed to know, derived from the record alone.

This is the one place where the canonical event stream becomes something a
window can draw. It is a *projection*: it reads events and produces a value. It
decides nothing, stores nothing and can start no work. A defect here shows the
user the wrong sentence; it cannot make the companion do the wrong thing. That
property is the reason this module exists at all rather than the GTK client
reading tasks and events for itself — a client that interpreted the record would
be a second interpretation of it, and the two would eventually disagree about
whether a task had finished.

Three rules shape it.

**The projection is a fold over events, and only over events.** §7 requires the
client to rebuild its whole visible state by asking for the events it missed and
replaying them. That is only true if nothing in the visible state comes from
somewhere else, so the fold takes events and nothing else. The runtime holds the
task document and does not pass it in; a test compares the folded phase against
the canonical task state and fails if they part company.

**Priority resolves what is true at once, not what happened last.** A task can be
executing *and* have an unanswered approval on somebody's screen; the last event
might be an ``operation_progress`` while the thing the user must act on is the
question. So the fold produces a *base* phase from the stream and
:func:`resolve_phase` picks the highest-priority phase among everything that is
simultaneously true — see :data:`PHASE_PRIORITY`. Without this the UI would show
"working" over a blocking question, which is how a person misses a consent
dialog.

**Nothing above the ``ui`` ceiling reaches the projection, and no payload reaches
it verbatim.** Every read goes through :meth:`companion.events.TaskEvent.view`
at the ``ui`` audience, and every string that ends up on screen goes through
:func:`companion.privacy.display_summary`. The projection therefore cannot carry
a credential, a model's reasoning, a raw tool value or a microphone sample —
there is no field for any of them and no path that would fill one.

What this module is *not*: it is not the presentation policy for whether the
companion may be drawn at all. That comes from the capability runtime, is read
out of the ``capability_checked`` event's own signals, and is applied by
:func:`select_presentation`, which can only ever choose something this build
actually implements. Declaring an implementation eligible and selecting it are
two different statements and are kept apart on purpose; see
:data:`IMPLEMENTED_PRESENTATIONS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from .events import TaskEvent
from .privacy import display_summary, visible_to, withheld_marker

__all__ = [
    "AccessibilityPreferences",
    "ApprovalPresentation",
    "DesktopContext",
    "IMPLEMENTED_PRESENTATIONS",
    "MonitorGeometry",
    "PHASE_PRIORITY",
    "PRESENTATION_KINDS",
    "PRESENTATION_PHASES",
    "PLACEMENTS",
    "PresentationRecommendation",
    "PresentationSignals",
    "PresentationState",
    "PresentationProjector",
    "ReviewerPresentation",
    "WindowDirective",
    "WindowPreferences",
    "escape_markup",
    "placement_for_phase",
    "project_presentation",
    "resolve_phase",
    "select_presentation",
    "signals_from_capability_event",
    "window_directive",
]

#: Version of the presentation state document
#: (``schemas/companion-presentation-state.schema.json``).
PRESENTATION_SCHEMA_VERSION = 1

#: Every phase the companion surface may be in.
#:
#: ``disconnected`` is the one phase the runtime never produces: it is what a
#: client shows when it cannot reach the runtime, and it is deliberately part of
#: this vocabulary so a client does not invent a phase of its own.
PRESENTATION_PHASES = (
    "idle",
    "starting",
    "recovering",
    "understanding",
    "planning",
    "waiting_for_approval",
    "listening",
    "speaking",
    "working",
    "reviewing",
    "presenting_result",
    "success",
    "cancelling",
    "cancelled",
    "paused",
    "blocked",
    "error",
    "disconnected",
)

#: Highest priority first. §12 fixes the order of nine of these:
#:
#:     error > blocked > waiting_for_approval > listening > speaking
#:           > working > reviewing > success > idle
#:
#: and that sequence appears here unbroken, with the remaining phases placed
#: around it. A test asserts the §12 order is a subsequence of this tuple, so a
#: phase added later cannot quietly reorder the part that was specified.
PHASE_PRIORITY = (
    "error",
    "blocked",
    "waiting_for_approval",
    "cancelling",
    "cancelled",
    "listening",
    "speaking",
    "working",
    "reviewing",
    "presenting_result",
    "planning",
    "understanding",
    "recovering",
    "paused",
    "starting",
    "success",
    "idle",
    "disconnected",
)

_PRIORITY = {name: index for index, name in enumerate(PHASE_PRIORITY)}

#: Presentation implementations, heaviest first. The order *is* the degradation
#: ladder: :func:`_degrade` moves right and never left.
PRESENTATION_KINDS = (
    "full-3d",
    "lightweight-3d",
    "animated-2d",
    "static-image",
    "audio-only",
    "text-only",
)

_KIND_RANK = {name: index for index, name in enumerate(PRESENTATION_KINDS)}

#: What this build can actually draw.
#:
#: The distinction between *eligible* and *implemented* is load-bearing and is
#: the reason :class:`PresentationRecommendation` carries both. A capability
#: plan may well say this machine could run a full 3D companion; this build has
#: no 3D renderer, so it says "eligible" and selects something it has.
#: Collapsing the two would make the presentation state claim a renderer that
#: does not exist, and every consumer downstream would believe it.
#:
#: ``animated-2d`` was added when :mod:`companion.character.animated_renderer`
#: was implemented, and not before. It is one line, and it is the line that
#: makes every consumer start believing animation is available — so it moves
#: only when there is a renderer behind it, which is why the previous phase left
#: it out and said so.
#: ``full-3d`` and ``lightweight-3d`` joined this set in the 3D renderer phase,
#: and — like ``animated-2d`` before them — only once there was a renderer
#: behind them that had drawn a frame in a test. ``tests/companion/
#: test_three_d_render.py`` reads pixels out of a real GL context and asserts a
#: character appeared; that test is what this line is standing on.
IMPLEMENTED_PRESENTATIONS = frozenset({
    "full-3d", "lightweight-3d", "animated-2d", "static-image", "audio-only", "text-only",
})

#: Where the surface may sit. Naming only; a Wayland compositor decides actual
#: placement and :func:`window_directive` says so rather than pretending.
PLACEMENTS = ("center", "docked", "compact", "task-panel", "speech-bubble")

#: Ceilings on the projection itself. A presentation state is read on every
#: refresh by a client that may be running in 64 MB, so it is bounded here
#: rather than left to grow with the task.
MAX_OBSERVATIONS = 32
MAX_APPROVALS = 16
MAX_STATUS_LENGTH = 512
MAX_SUMMARY = 240

#: Which phase each canonical event type puts the surface into.
#:
#: This is a *display* mapping and never a lifecycle. It gates nothing, and
#: :mod:`companion.states` remains the only description of what a task may do.
#: Two entries are decided by the payload instead of the type, because the same
#: event type is emitted for opposite outcomes; they are handled in
#: :meth:`PresentationProjector.apply` and appear here with their optimistic
#: reading.
EVENT_PHASES: Mapping[str, str] = {
    "session_created": "idle",
    "task_created": "starting",
    "task_classified": "understanding",
    "capability_checked": "planning",
    "executor_selected": "planning",
    "reviewer_selected": "planning",
    "planning_started": "planning",
    "approval_requested": "waiting_for_approval",
    "approval_resolved": "working",
    "execution_started": "working",
    "operation_started": "working",
    "operation_progress": "working",
    "operation_completed": "working",
    # An operation failing is not the task failing. Mapping it to ``error``
    # would pin the surface at the top of the priority order while the executor
    # carried on replanning around it, and the user would be told the task had
    # stopped when it had not. The failure is recorded in ``errorSummary``,
    # where it stays visible without claiming to be terminal.
    "operation_failed": "working",
    "reviewer_observation": "reviewing",
    "reviewer_disagreement": "reviewing",
    "result_created": "presenting_result",
    "task_paused": "paused",
    "task_resumed": "working",
    "task_cancelled": "cancelled",
    "task_failed": "error",
    "task_completed": "success",
    "recovery_started": "recovering",
    "recovery_completed": "recovering",
    "task_state_changed": "",
}

#: Approval endings that mean the system withdrew the question, not that a
#: person answered it.
#:
#: None of them may move the presentation phase. A task the user paused is
#: paused, and it should project that way because its lifecycle says so — not
#: because "paused" was given a higher visual rank than "blocked" to paper over
#: a withdrawal being recorded as a refusal. That was the defect: pausing wrote
#: the withdrawn question into the record as ``denied``, denial blocks, and a
#: paused task showed as blocked about once in fifty runs.
_SYSTEM_WITHDRAWALS = frozenset({
    "invalidated",
    "superseded",
    "cancelled-with-task",
    "cancelled-with-pause",
})

#: How a terminal state is summarised for a client.
#:
#: The record keeps seven states; the surface needs four, because what a person
#: has to be able to tell apart is: it was allowed, I said no, it ran out of
#: time, or the system took the question back. Collapsing the last of those into
#: "denied" is the same defect the record had — it tells somebody they refused
#: something they did not.
PRESENTED_APPROVAL_STATE = {
    "approved": "granted",
    "granted": "granted",
    "denied-by-user": "denied",
    "denied": "denied",
    "expired": "expired",
    "invalidated": "withdrawn",
    "superseded": "withdrawn",
    "cancelled-with-task": "withdrawn",
    "cancelled-with-pause": "withdrawn",
}

#: What to say about each withdrawal, when the event carries no reason.
_WITHDRAWAL_TEXT = {
    "invalidated": "the question was withdrawn and will be asked again if it is still needed",
    "superseded": "the plan changed, so the question was withdrawn and will be asked again",
    "cancelled-with-task": "the task was cancelled, so the question was withdrawn",
    "cancelled-with-pause": "the task was paused, so the question was withdrawn",
}

#: Canonical task state -> phase, for the transitions whose event type carries
#: nothing but the move (``task_state_changed``) and for recovery's decisions.
TASK_STATE_PHASES: Mapping[str, str] = {
    "created": "starting",
    "classifying": "understanding",
    "waiting_for_capability": "planning",
    "waiting_for_executor": "planning",
    "waiting_for_approval": "waiting_for_approval",
    "planning": "planning",
    "executing": "working",
    "reviewing": "reviewing",
    "presenting": "presenting_result",
    "completed": "success",
    "blocked": "blocked",
    "failed": "error",
    "cancelled": "cancelled",
    "cancelling": "cancelling",
    "paused": "paused",
    "recovering": "recovering",
}


def escape_markup(text: str) -> str:
    """Neutralise Pango/GTK markup in a string bound for a label.

    The GTK client sets label text with ``set_text``, which does not parse
    markup, so this should be redundant. It is applied anyway at the point the
    string is produced rather than at the point it is displayed: a status line
    is assembled from event payloads, event payloads come from executors and
    tools, and "the widget happens not to parse markup" is a property of one
    call site rather than of the value. A later view that used ``set_markup``
    would otherwise turn a task summary into a rendering instruction.

    **Quotes are deliberately left alone.** They were escaped too, and the
    desktop showed a person this:

        Done. I made Pictures/holiday-resized.png at 100 pixels wide.
        Your original wasn&#39;t changed.

    Photographed on a booted guest. Every view in this product sets text with
    ``set_text`` — the GTK transcript and the GNOME Shell panel both say so in
    their own comments — so nothing ever turned the entity back into an
    apostrophe, and this product's voice is full of them: wasn't, didn't,
    you're.

    Dropping the two quote rules costs nothing, because neither character can
    introduce markup. Pango markup opens with ``<`` and an entity opens with
    ``&``; both are still escaped, so no tag can exist, and a quote only means
    anything *inside* a tag. The injection property is unchanged and the
    sentence is readable.

    The larger point stands and is not fixed here: escaping belongs to the view
    that parses markup, and no such view exists in this product today. A summary
    containing a literal ``&`` is still shown as ``&amp;``.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _text(value: Any, *, limit: int = MAX_SUMMARY) -> str:
    """One value from a payload: bounded, credential-free and markup-free.

    Escaping happens **here and once**. A status line is assembled from pieces
    that have each been through this, so the assembled line is bounded again by
    :func:`_bound` and not escaped a second time — escaping twice turns
    ``&lt;span`` into ``&amp;lt;span`` and the user is shown the escaping rather
    than the text.
    """
    return escape_markup(display_summary(str(value), limit=limit))


def _bound(value: Any, *, limit: int = MAX_STATUS_LENGTH) -> str:
    """A line already assembled from :func:`_text` pieces. Bounded, not escaped."""
    return display_summary(str(value), limit=limit)


@dataclass(frozen=True)
class ReviewerPresentation:
    """One reviewer observation, as the surface may show it.

    ``disagreement`` is separate from ``severity`` because §10 requires material
    disagreement to stay visible after the executor revises around it. A client
    that only had the severity would have to re-derive which observations were
    recorded as dissent, and would get it wrong the first time the severity
    thresholds moved.
    """

    reviewer_id: str
    severity: str = "info"
    category: str = "correctness"
    summary: str = ""
    suggested_action: str = ""
    evidence_event_ids: tuple[str, ...] = ()
    disagreement: bool = False
    round_number: int = 0
    absent: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "reviewerId": self.reviewer_id,
            "severity": self.severity,
            "category": self.category,
            "summary": self.summary,
            "suggestedAction": self.suggested_action,
            "evidenceEventIds": list(self.evidence_event_ids),
            "disagreement": self.disagreement,
            "roundNumber": self.round_number,
            "absent": self.absent,
        }


@dataclass(frozen=True)
class ApprovalPresentation:
    """One outstanding question, with every field the answer must carry back.

    §9 requires the Approval Centre to return the *original binding* rather than
    a bare yes. Every field here is part of that binding and is checked by
    :meth:`companion.runtime.CompanionRuntime` before a decision is recorded, so
    a client that altered the destination, the provider or the cost between
    display and submission is refused rather than obeyed.
    """

    request_id: str
    session_id: str
    task_id: str
    plan_id: str
    transition_id: str
    action: str
    reason: str = ""
    #: The binding destination, in the approval layer's own vocabulary:
    #: ``"local"`` or ``"remote"``. This is the value the runtime recorded and
    #: therefore the value a resolution must repeat.
    destination: str = "local"
    #: The specific place, for the person reading the dialog — a provider id, a
    #: hostname. Display only, and deliberately *outside* :meth:`binding`: it is
    #: derived from the requirement rather than recorded on the request, so
    #: comparing it would compare a rendering against a record.
    destination_detail: str = ""
    provider_id: str = ""
    data_classification: str = "internal"
    estimated_cost_units: int | None = None
    destination_fingerprint: str = ""
    expires_at_monotonic: float = 0.0
    alternatives: tuple[str, ...] = ()
    safe_default: str = "denied"
    decision: str = "pending"
    #: The structured facts the permission surface draws: application identity,
    #: resource, effect, and what the confinement does and does not allow.
    #:
    #: Display only, like :attr:`destination_detail` and for the same reason: it
    #: is a rendering, and binding a rendering would mean that rewording a
    #: sentence invalidates consent somebody already gave. Every value is
    #: bounded and escaped by :func:`_prompt` before it gets here, because these
    #: strings originate in an application's own manifest.
    prompt: Mapping[str, str] = field(default_factory=dict)

    def binding(self) -> dict[str, Any]:
        """Exactly the fields a resolution must repeat back, and nothing else.

        Expiry is bound and is *not* here. The runtime holds the expiry it
        recorded and checks against that; a client-supplied expiry would be the
        one field an attacker most wants to be allowed to restate.
        """
        return {
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "action": self.action,
            "destination": self.destination,
            "providerId": self.provider_id,
            "dataClassification": self.data_classification,
            "estimatedCostUnits": self.estimated_cost_units,
            "destinationFingerprint": self.destination_fingerprint,
        }

    def to_json(self) -> dict[str, Any]:
        value = self.binding()
        value.update({
            "reason": self.reason,
            "destinationDetail": self.destination_detail,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "alternatives": list(self.alternatives),
            "safeDefault": self.safe_default,
            "decision": self.decision,
            "prompt": dict(self.prompt),
        })
        return value


@dataclass(frozen=True)
class PresentationRecommendation:
    """What may be drawn, and what this build will actually draw."""

    #: What is selected. Always in :data:`IMPLEMENTED_PRESENTATIONS`.
    implementation: str = "text-only"
    #: What the machine and the policy would permit. May name something this
    #: build has no renderer for; saying so is the honest form of "eligible".
    eligible: str = "text-only"
    #: True when ``eligible`` is heavier than anything implemented — the case a
    #: reader needs in order not to mistake "we chose a static image" for "this
    #: machine cannot do better".
    limited_by_implementation: bool = False
    placement: str = "center"
    captions: bool = True
    audio_available: bool = False
    plan_id: str = ""
    reasons: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "eligible": self.eligible,
            "limitedByImplementation": self.limited_by_implementation,
            "placement": self.placement,
            "captions": self.captions,
            "audioAvailable": self.audio_available,
            "planId": self.plan_id,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PresentationState:
    """Everything a client may know, and nothing else.

    The absent fields are the specification: there is no place here for a
    model's reasoning, an API credential, a raw tool result, a screen capture,
    an audio sample, a provider token or an arbitrary Python object. Adding one
    would need a new field and a new line in the schema, which is the point.
    """

    session_id: str = ""
    task_id: str = ""
    phase: str = "idle"
    #: The phase the stream alone produced, before priority resolution. Kept so
    #: a client can explain why it is showing what it is showing, and so a test
    #: can separate a mapping fault from a priority fault.
    base_phase: str = "idle"
    status_text: str = ""
    progress: float = 0.0
    active_executor: str = ""
    reviewers: tuple[str, ...] = ()
    observations: tuple[ReviewerPresentation, ...] = ()
    current_operation: str = ""
    current_tool: str = ""
    approval_state: str = "not_required"
    approvals: tuple[ApprovalPresentation, ...] = ()
    result_summary: str = ""
    error_summary: str = ""
    privacy_classification: str = "internal"
    data_locality: str = "device-only"
    locality_indicator: str = "local"
    paid_provider: bool = False
    listening: bool = False
    speaking: bool = False
    microphone_active: bool = False
    recommendation: PresentationRecommendation = field(default_factory=PresentationRecommendation)
    #: The capability plan or approval plan the current decision was made
    #: against. A reference, not an explanation: the explanation lives in the
    #: event stream and this says which part of it to read.
    explanation_reference: str = ""
    #: The stream position this state was folded up to. A client sends it back
    #: as ``afterSequence`` and receives only what it has not seen.
    revision: int = 0
    #: True when anything the projection read was above the ``ui`` ceiling. A
    #: surface that is showing a redacted view should say so rather than look
    #: like a complete one.
    content_withheld: bool = False
    schema_version: int = PRESENTATION_SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "phase": self.phase,
            "basePhase": self.base_phase,
            "statusText": self.status_text,
            "progress": self.progress,
            "activeExecutor": self.active_executor,
            "reviewers": list(self.reviewers),
            "observations": [item.to_json() for item in self.observations],
            "currentOperation": self.current_operation,
            "currentTool": self.current_tool,
            "approvalState": self.approval_state,
            "approvals": [item.to_json() for item in self.approvals],
            "resultSummary": self.result_summary,
            "errorSummary": self.error_summary,
            "privacyClassification": self.privacy_classification,
            "dataLocality": self.data_locality,
            "localityIndicator": self.locality_indicator,
            "paidProvider": self.paid_provider,
            "listening": self.listening,
            "speaking": self.speaking,
            "microphoneActive": self.microphone_active,
            "recommendation": self.recommendation.to_json(),
            "explanationReference": self.explanation_reference,
            "revision": self.revision,
            "contentWithheld": self.content_withheld,
        }


def resolve_phase(
    base_phase: str,
    *,
    approvals_pending: bool = False,
    listening: bool = False,
    speaking: bool = False,
) -> str:
    """The phase to show when several are true at once.

    The candidates are gathered rather than ordered by recency, because recency
    is the wrong question: an ``operation_progress`` arriving after an
    ``approval_requested`` does not mean the question was answered.
    """
    candidates = [base_phase if base_phase in _PRIORITY else "idle"]
    if approvals_pending:
        candidates.append("waiting_for_approval")
    if listening:
        candidates.append("listening")
    if speaking:
        candidates.append("speaking")
    return min(candidates, key=lambda name: _PRIORITY[name])


# --------------------------------------------------------------------------- #
# The fold
# --------------------------------------------------------------------------- #


_STATUS: Mapping[str, str] = {
    "session_created": "Started a private session on this device.",
    "task_created": "Received the request and wrote it to the task record.",
    "task_classified": "Worked out what kind of task this is.",
    "capability_checked": "Checked what this machine is able to do.",
    "executor_selected": "Chose the component that will do the work.",
    "reviewer_selected": "Attached the observation-only reviewers.",
    "planning_started": "Preparing a plan.",
    "approval_requested": "Waiting for you to answer a question.",
    "approval_resolved": "Recorded your answer.",
    "execution_started": "Working.",
    "operation_started": "Working.",
    "operation_progress": "Working.",
    "operation_completed": "Finished a step.",
    "operation_failed": "A step failed.",
    "reviewer_observation": "A reviewer looked at the work.",
    "reviewer_disagreement": "A reviewer disagrees, and its objection is on the record.",
    "result_created": "Preparing the result.",
    "task_paused": "Paused.",
    "task_resumed": "Resumed.",
    "task_cancelled": "Stopped, at your request.",
    "task_failed": "The task failed.",
    "task_completed": "Done.",
    "recovery_started": "Checking what was interrupted.",
    "recovery_completed": "Finished checking what was interrupted.",
    "task_state_changed": "",
}


@dataclass(frozen=True)
class _Record:
    """One event, normalised, however it arrived.

    The fold reads exactly these fields, so a canonical :class:`TaskEvent` and
    the redacted document a client receives over the protocol reduce to the same
    thing before anything looks at them. Without this the runtime and the client
    would each have a fold, and §7's "replay restores the UI" would be a claim
    about two implementations agreeing.
    """

    session_id: str
    task_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    classification: str
    audit_reference: str


class PresentationProjector:
    """Folds canonical events into a :class:`PresentationState`, one at a time.

    Incremental on purpose. §7 has the client ask for events after a revision it
    already holds and apply them to what it already has, and a projector that
    could only fold a whole stream would make every refresh a full replay — on a
    machine where a session may hold ten thousand events.

    The fold is pure with respect to the events: applying the same events in the
    same order to a fresh projector always produces the same state, which is
    what makes "the UI is restored by replay" a test rather than a hope.
    """

    def __init__(self, *, audience: str = "ui", state: PresentationState | None = None) -> None:
        self.audience = audience
        self.state = state or PresentationState()
        self._pending: dict[str, ApprovalPresentation] = {
            item.request_id: item for item in self.state.approvals if item.decision == "pending"
        }
        self._resolved: dict[str, str] = {}
        self._last_decision = ""
        #: The attempt whose approval outcomes count. See :data:`_SYSTEM_WITHDRAWALS`.
        self._lifecycle_epoch = 0

    # -- reading -----------------------------------------------------------

    def apply(self, event: TaskEvent) -> PresentationState:
        """Fold one canonical event in and return the new state."""
        view = event.view(self.audience)
        payload = view.get("payload")
        return self._apply(
            _Record(
                session_id=event.session_id,
                task_id=event.task_id,
                sequence=event.sequence,
                event_type=event.event_type,
                payload=payload if isinstance(payload, Mapping) else {},
                classification=event.classification,
                audit_reference=event.audit_reference,
            )
        )

    def apply_document(self, document: Mapping[str, Any]) -> PresentationState:
        """Fold in an event as it came off the wire.

        The wire form is :meth:`companion.events.TaskEvent.view` — already
        projected for this audience, and therefore *not* reconstructible as a
        :class:`TaskEvent`: projecting the payload changes it, so the record no
        longer matches its own hash. That is correct and is why this method
        exists. §7 has the client rebuild by replaying the events the runtime
        supplied, and the events the runtime supplies are redacted ones; a
        client that could only fold verified originals could not replay at all
        without being handed material it is not cleared for.

        The integrity of the *stream* is checked where the stream lives, on
        every read in :meth:`companion.store.CompanionStore.read_stream`. What
        arrives here is a rendering, and it is treated as one.
        """
        if not isinstance(document, Mapping):
            raise ValueError("an event record must be an object")
        payload = document.get("payload")
        sequence = document.get("sequence")
        return self._apply(
            _Record(
                session_id=str(document.get("sessionId", "")),
                task_id=str(document.get("taskId", "")),
                sequence=int(sequence) if isinstance(sequence, int) and not isinstance(sequence, bool) else 0,
                event_type=str(document.get("eventType", "")),
                payload=payload if isinstance(payload, Mapping) else {},
                classification=str(document.get("classification", "internal")),
                audit_reference=str(document.get("auditReference", "")),
            )
        )

    # -- the fold ----------------------------------------------------------

    def _apply(self, event: "_Record") -> PresentationState:
        payload = event.payload
        try:
            withheld = not visible_to(self.audience, event.classification)
        except ValueError:
            # A classification this build does not know. Treated as withheld
            # rather than as visible: an unknown class is not a permission.
            withheld = True
        state = self.state
        changes: dict[str, Any] = {
            "session_id": event.session_id or state.session_id,
            "revision": max(state.revision, event.sequence),
        }
        if event.task_id:
            changes["task_id"] = event.task_id
        if withheld:
            changes["content_withheld"] = True
        if event.audit_reference:
            changes["explanation_reference"] = _text(event.audit_reference, limit=128)

        kind = event.event_type
        base = EVENT_PHASES.get(kind, state.base_phase)
        status = _STATUS.get(kind, state.status_text)

        if kind == "task_created":
            changes["privacy_classification"] = str(payload.get("classification", "internal"))
            changes["data_locality"] = str(payload.get("dataLocality", "device-only"))
            summary = _text(payload.get("summary", ""))
            status = f"Received: {summary}" if summary else status

        elif kind == "task_classified":
            task_type = _text(payload.get("taskType", ""), limit=64)
            status = f"This looks like a {task_type} task." if task_type else status

        elif kind == "capability_checked":
            eligible = bool(payload.get("eligible", False))
            plan_id = _text(payload.get("planId", ""), limit=128)
            if plan_id:
                changes["explanation_reference"] = plan_id
            signals = payload.get("signals")
            if isinstance(signals, Mapping):
                changes["_signals"] = dict(signals)
            if not eligible:
                base = "blocked"
                reasons = payload.get("reasons")
                detail = "; ".join(_text(item) for item in reasons[:3]) if isinstance(reasons, list) else ""
                status = "This cannot run here." + (f" {detail}" if detail else "")
                changes["error_summary"] = _text(detail or "no eligible executor", limit=MAX_STATUS_LENGTH)
            else:
                status = "This machine can do the work."

        elif kind == "executor_selected":
            executor = _text(payload.get("executorId", ""), limit=128)
            local = bool(payload.get("local", True))
            changes["active_executor"] = executor
            changes["locality_indicator"] = "local" if local else "remote"
            declaration = payload.get("declaration")
            if isinstance(declaration, Mapping):
                changes["paid_provider"] = str(declaration.get("costClass", "free")) == "paid"
            status = f"{executor} will do the work {'on this device' if local else 'remotely'}."

        elif kind == "reviewer_selected":
            ids = payload.get("reviewerIds")
            reviewers = tuple(_text(item, limit=128) for item in ids) if isinstance(ids, list) else ()
            changes["reviewers"] = reviewers
            status = (
                f"{len(reviewers)} observation-only reviewer(s) attached."
                if reviewers else "No reviewer is attached to this task."
            )

        elif kind == "planning_started":
            plan = payload.get("plan")
            summary = _text(plan.get("summary", "")) if isinstance(plan, Mapping) else ""
            status = f"Plan: {summary}" if summary else status

        elif kind == "approval_requested":
            status, base = self._approval_requested(event, payload, status, base, changes)

        elif kind == "approval_resolved":
            status, base = self._approval_resolved(payload, status, base, changes)

        elif kind == "operation_started":
            changes["current_operation"] = _text(payload.get("name", ""), limit=128)
            changes["current_tool"] = _text(payload.get("tool", ""), limit=128)
            status = f"Running {changes['current_operation'] or 'a step'}."

        elif kind == "operation_progress":
            value = payload.get("progress")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                # Monotonic. A bar that retreats says the machine has lost
                # track; the record says no such thing, so neither does this.
                changes["progress"] = max(state.progress, min(1.0, max(0.0, float(value) * 0.8)))
            if payload.get("skipped"):
                status = _text(payload.get("reason", "A step was skipped."), limit=MAX_STATUS_LENGTH)

        elif kind == "operation_completed":
            changes["current_operation"] = ""
            changes["current_tool"] = ""
            status = f"Finished {_text(payload.get('name', 'a step'), limit=128)}."

        elif kind == "operation_failed":
            changes["current_operation"] = ""
            changes["current_tool"] = ""
            changes["error_summary"] = _text(payload.get("error", "a step failed"), limit=MAX_STATUS_LENGTH)
            status = f"A step failed: {changes['error_summary']}"

        elif kind in ("reviewer_observation", "reviewer_disagreement"):
            observation = _observation(payload, disagreement=kind == "reviewer_disagreement")
            changes["observations"] = (*state.observations, observation)[-MAX_OBSERVATIONS:]
            status = f"Reviewer: {observation.summary}" if observation.summary else status

        elif kind == "result_created":
            result = payload.get("result")
            summary = _text(result.get("summary", "")) if isinstance(result, Mapping) else ""
            changes["result_summary"] = summary
            changes["progress"] = max(state.progress, 0.9)
            status = f"Result: {summary}" if summary else status

        elif kind == "task_completed":
            changes["progress"] = 1.0
            changes["current_operation"] = ""
            changes["current_tool"] = ""

        elif kind == "task_failed":
            changes["error_summary"] = _text(payload.get("error", "the task failed"), limit=MAX_STATUS_LENGTH)
            status = f"The task failed: {changes['error_summary']}"

        elif kind == "task_cancelled":
            changes["current_operation"] = ""
            changes["current_tool"] = ""
            self._withdraw_all("the task was cancelled")

        elif kind == "task_paused":
            base = "paused"

        elif kind == "task_resumed":
            base = TASK_STATE_PHASES.get(str(payload.get("resumedTo", "")), "working")

        elif kind == "recovery_completed":
            decision = str(payload.get("decision", ""))
            base = TASK_STATE_PHASES.get(decision, "recovering")
            reasons = payload.get("reasons")
            detail = "; ".join(_text(item) for item in reasons[:2]) if isinstance(reasons, list) else ""
            status = f"After the restart: {detail}" if detail else status

        elif kind == "task_state_changed":
            target = str(payload.get("to", ""))
            base = TASK_STATE_PHASES.get(target, state.base_phase)
            status = _state_status(target) or status

        signals = changes.pop("_signals", None)
        if signals is not None:
            self._capability_signals = dict(signals)

        changes["base_phase"] = base if base in _PRIORITY else state.base_phase
        changes["status_text"] = _bound(status)
        changes["approvals"] = tuple(self._approval_list())
        changes["approval_state"] = self._approval_state()
        self.state = replace(state, **changes)
        self.state = replace(
            self.state,
            phase=resolve_phase(
                self.state.base_phase,
                approvals_pending=bool(self._pending),
                listening=self.state.listening,
                speaking=self.state.speaking,
            ),
        )
        return self.state

    # -- approvals ---------------------------------------------------------

    def _approval_requested(
        self,
        event: TaskEvent,
        payload: Mapping[str, Any],
        status: str,
        base: str,
        changes: dict[str, Any],
    ) -> tuple[str, str]:
        if payload.get("batch"):
            # The transition marker, not one of the questions. Counting it would
            # show a phantom approval that nothing can ever answer.
            count = payload.get("requirementCount")
            return (
                f"Waiting for you to answer {count} question(s)."
                if isinstance(count, int) else status
            ), base
        request = payload.get("request")
        requirement = payload.get("requirement")
        if not isinstance(request, Mapping):
            return status, base
        presentation = _approval(
            request,
            requirement if isinstance(requirement, Mapping) else {},
            session_id=event.session_id,
            task_id=event.task_id,
        )
        if len(self._pending) < MAX_APPROVALS:
            self._pending[presentation.request_id] = presentation
        changes["explanation_reference"] = presentation.plan_id or changes.get(
            "explanation_reference", self.state.explanation_reference
        )
        return f"May I {_text(presentation.action.replace('_', ' '), limit=120)}?", base

    def _approval_resolved(
        self,
        payload: Mapping[str, Any],
        status: str,
        base: str,
        changes: dict[str, Any],
    ) -> tuple[str, str]:
        decision = str(payload.get("decision", "denied"))
        request_id = str(payload.get("requestId", ""))

        # §7: an outcome recorded against an earlier attempt at this task says
        # nothing about the current one. A resume produces the same plan and
        # transition ids when the plan is unchanged — deliberately, so that an
        # answer which still applies is kept — so every other field would match
        # and only the epoch distinguishes them.
        epoch = payload.get("lifecycleEpoch")
        if isinstance(epoch, int) and epoch < self._lifecycle_epoch:
            return status, base
        if isinstance(epoch, int):
            self._lifecycle_epoch = max(self._lifecycle_epoch, epoch)

        # A question the system withdrew is not an answer, and none of these
        # says anything about where the task went. Reporting them as a phase was
        # the defect: a task somebody paused projected as `blocked`, because the
        # withdrawal was written as a denial and a denial blocks. Only a person
        # declining blocks a task.
        if decision in _SYSTEM_WITHDRAWALS:
            if request_id:
                self._settle(request_id, decision)
            self._last_decision = decision
            detail = payload.get("reason") or payload.get("detail") or _WITHDRAWAL_TEXT.get(
                decision, "the question was withdrawn and not answered"
            )
            # The phase the stream already had, not this event's own mapping.
            return _text(str(detail), limit=MAX_STATUS_LENGTH), self.state.base_phase

        withdrawn = payload.get("withdrawn")
        if isinstance(withdrawn, list) and withdrawn:
            # A *withdrawal*, not an answer: the plan was superseded by a
            # replan, or the task was paused. Both settle the question and
            # neither says anything about where the task is — so the phase is
            # left where the stream had it. Treating a withdrawal as an expiry
            # showed "blocked" over a task that was busily replanning, and
            # "blocked" over a task the user had merely paused.
            for item in withdrawn:
                self._settle(str(item), "expired")
            self._last_decision = "expired"
            detail = payload.get("detail") or (
                "the plan changed, so the question was withdrawn and will be asked again"
            )
            # The phase the stream had *before* this event, not this event's own
            # mapping: `approval_resolved` maps to "working", which would move a
            # task the user had just paused back to looking busy.
            return _text(detail, limit=MAX_STATUS_LENGTH), self.state.base_phase
        if request_id:
            self._settle(request_id, decision)
        self._last_decision = decision
        if decision in ("granted", "approved"):
            return "You approved it; carrying on.", "working"
        if decision == "expired":
            changes["error_summary"] = _text(
                payload.get("detail", "the question expired before it was answered"),
                limit=MAX_STATUS_LENGTH,
            )
            return "The question expired and nothing was done.", "blocked"
        changes["error_summary"] = _text(
            payload.get("detail", "the request was declined"), limit=MAX_STATUS_LENGTH
        )
        return "Declined; nothing was done.", "blocked"

    def settle(self, request_id: str, decision: str) -> PresentationState:
        """Record an answer that reached the store without an event yet.

        The durable approval store is answered by the Approval Centre and by
        ``bunny-os companion approvals`` alike, and the corresponding
        ``approval_resolved`` event is written by the *task* when it next looks.
        Between those two moments the stream still shows a pending question. The
        runtime overlays what it knows here so the surface does not invite an
        answer to something already answered.
        """
        self._settle(request_id, decision)
        return self.refresh()

    def refresh(self) -> PresentationState:
        """Recompute the derived approval fields and the resolved phase."""
        self.state = replace(
            self.state,
            approvals=tuple(self._approval_list()),
            approval_state=self._approval_state(),
        )
        self.state = replace(
            self.state,
            phase=resolve_phase(
                self.state.base_phase,
                approvals_pending=bool(self._pending),
                listening=self.state.listening,
                speaking=self.state.speaking,
            ),
        )
        return self.state

    def _settle(self, request_id: str, decision: str) -> None:
        item = self._pending.pop(request_id, None)
        if item is not None:
            self._resolved[request_id] = decision
        elif request_id:
            self._resolved.setdefault(request_id, decision)

    def _withdraw_all(self, _reason: str) -> None:
        for request_id in list(self._pending):
            self._settle(request_id, "expired")

    def _approval_list(self) -> list[ApprovalPresentation]:
        return [self._pending[key] for key in sorted(self._pending)]

    def _approval_state(self) -> str:
        if self._pending:
            return "pending"
        if self._last_decision:
            return PRESENTED_APPROVAL_STATE.get(self._last_decision, self._last_decision)
        return "not_required"

    # -- client-side indicators -------------------------------------------

    def with_indicators(
        self,
        *,
        listening: bool = False,
        speaking: bool = False,
        microphone_active: bool = False,
    ) -> PresentationState:
        """Fold in the two facts the event stream does not hold.

        Listening and speaking happen on the user's own machine, in the client,
        and produce no canonical event — a microphone that wrote to the task
        record would be a microphone whose samples reached durable storage. So
        they are applied here, after the fold, and they participate in priority
        like any other phase.
        """
        self.state = replace(
            self.state,
            listening=listening,
            speaking=speaking,
            microphone_active=microphone_active,
        )
        self.state = replace(
            self.state,
            phase=resolve_phase(
                self.state.base_phase,
                approvals_pending=bool(self._pending),
                listening=listening,
                speaking=speaking,
            ),
        )
        return self.state

    def with_recommendation(self, recommendation: PresentationRecommendation) -> PresentationState:
        self.state = replace(self.state, recommendation=recommendation)
        return self.state

    @property
    def capability_signals(self) -> Mapping[str, Any]:
        """The signals the capability runtime reported, if this stream had any."""
        return getattr(self, "_capability_signals", {})


def _state_status(target: str) -> str:
    return {
        "classifying": "Working out what this is.",
        "cancelling": "Stopping.",
        "blocked": "This cannot go further without something changing.",
        "reviewing": "A reviewer is looking at the work.",
        "recovering": "Checking what was interrupted.",
    }.get(target, "")


def _observation(payload: Mapping[str, Any], *, disagreement: bool) -> ReviewerPresentation:
    evidence = payload.get("evidenceEventIds")
    return ReviewerPresentation(
        reviewer_id=_text(payload.get("reviewerId", ""), limit=128),
        severity=str(payload.get("severity", "info")),
        category=str(payload.get("category", "correctness")),
        summary=_text(payload.get("summary", "")),
        suggested_action=_text(payload.get("suggestedAction", "")),
        evidence_event_ids=tuple(
            _text(item, limit=64) for item in evidence[:8]
        ) if isinstance(evidence, list) else (),
        disagreement=disagreement,
        round_number=int(payload.get("roundNumber", 0) or 0),
        absent=bool(payload.get("absent", False)),
    )


#: The fields a permission surface may draw, and the length each is bounded to.
#:
#: An allowlist rather than "whatever the requester sent". These strings reach a
#: security dialog and several of them originate in an application's own
#: manifest — `applicationName` and the resource path are chosen by the thing
#: asking for permission. A surface that rendered every key in the mapping would
#: let a requester add a field, and a requester who can add a field to a
#: permission prompt can add a sentence to it.
#:
#: The lengths are short on purpose. §48 asks that the prompt stay visually
#: secure against hostile reason content, and the shape of that attack is a
#: name long enough to push the buttons off screen or to look like a second
#: sentence of the dialog's own copy.
PROMPT_FIELDS: Mapping[str, int] = {
    "kind": 32,
    "applicationName": 64,
    "applicationId": 96,
    "operationId": 64,
    "presentation": 200,
    "expectedEffect": 200,
    "disclosure": 160,
    "fileAccess": 96,
    "network": 32,
    "privateAppData": 32,
}


def _prompt(payload: Any) -> dict[str, str]:
    """The structured prompt, reduced to the fields a surface may draw.

    Unknown keys are dropped rather than truncated, and every kept value goes
    through :func:`_text`, so it is bounded and markup-free by the time it
    leaves this module. A prompt that arrives as anything but a mapping becomes
    an empty one: the surface then falls back to `reason`, which is the
    behaviour every build before this had.
    """
    if not isinstance(payload, Mapping):
        return {}
    kept: dict[str, str] = {}
    for field_name, limit in PROMPT_FIELDS.items():
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            kept[field_name] = _text(value, limit=limit)
    return kept


def _approval(
    request: Mapping[str, Any],
    requirement: Mapping[str, Any],
    *,
    session_id: str,
    task_id: str,
) -> ApprovalPresentation:
    cost = request.get("estimatedCostUnits")
    alternatives = request.get("alternatives")
    return ApprovalPresentation(
        request_id=str(request.get("requestId", "")),
        session_id=session_id,
        task_id=task_id,
        plan_id=str(request.get("planId", "")),
        transition_id=str(request.get("transitionId", "")),
        action=str(request.get("action", "")),
        reason=_text(request.get("reason", ""), limit=MAX_STATUS_LENGTH),
        # The request's own destination is the binding value; the requirement's
        # is the specific place, for the human reading the dialog. Binding the
        # rendering rather than the record would mean a change of wording could
        # invalidate consent while a change of provider might not.
        destination=str(request.get("destination", "local")),
        destination_detail=_text(requirement.get("destination", ""), limit=256),
        provider_id=str(request.get("providerId") or ""),
        data_classification=str(request.get("dataAffected", "internal")),
        estimated_cost_units=int(cost) if isinstance(cost, int) and not isinstance(cost, bool) else None,
        destination_fingerprint=str(requirement.get("destinationFingerprint", "")),
        expires_at_monotonic=float(request.get("expiresAtMonotonic", 0.0) or 0.0),
        alternatives=tuple(
            _text(item) for item in alternatives[:8]
        ) if isinstance(alternatives, list) else (),
        safe_default=str(request.get("safeDefault", "denied")),
        prompt=_prompt(request.get("prompt")),
    )


def project_presentation(
    events: Iterable[TaskEvent],
    *,
    audience: str = "ui",
    state: PresentationState | None = None,
    listening: bool = False,
    speaking: bool = False,
    microphone_active: bool = False,
) -> PresentationState:
    """Fold a whole stream. Equivalent to applying each event in turn."""
    projector = PresentationProjector(audience=audience, state=state)
    for event in events:
        projector.apply(event)
    return projector.with_indicators(
        listening=listening, speaking=speaking, microphone_active=microphone_active
    )


# --------------------------------------------------------------------------- #
# Presentation selection, bounded by what exists
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AccessibilityPreferences:
    """The user's own settings, which may only ever make the surface simpler."""

    reduced_motion: bool = False
    no_animation: bool = False
    high_contrast: bool = False
    text_scale: float = 1.0
    remote_rendering_requested: bool = False
    remote_rendering_permitted: bool = False

    def __post_init__(self) -> None:
        if self.available_memory_bytes is not None and self.available_memory_bytes < 0:
            raise ValueError("available memory cannot be negative")
        if self.vram_available_bytes is not None and self.vram_available_bytes < 0:
            raise ValueError("available VRAM cannot be negative")
        if self.battery_percent is not None and not 0.0 <= self.battery_percent <= 100.0:
            raise ValueError("battery percentage is invalid")
        if not 0.75 <= self.text_scale <= 3.0:
            raise ValueError("text scale is outside the supported range")


@dataclass(frozen=True)
class PresentationDecision:
    implementation: PresentationKind
    placement: Placement
    captions: bool
    visual_listening_indicator: bool
    visual_speaking_indicator: bool
    plan_id: str
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation.value,
            "placement": self.placement.value,
            "captions": self.captions,
            "visualListeningIndicator": self.visual_listening_indicator,
            "visualSpeakingIndicator": self.visual_speaking_indicator,
            "planId": self.plan_id,
            "reasons": list(self.reasons),
        }


def _degrade(current: PresentationKind, floor: PresentationKind) -> PresentationKind:
    return _LADDER[max(_RANK[current], _RANK[floor])]


def placement_for_phase(phase: CompanionPhase) -> Placement:
    if phase in {CompanionPhase.IDLE, CompanionPhase.GREETING, CompanionPhase.SLEEPING}:
        return Placement.CENTER
    if phase in {CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.BLOCKED, CompanionPhase.ERROR}:
        return Placement.TASK_PANEL
    if phase in {CompanionPhase.SPEAKING, CompanionPhase.PRESENTING_RESULT, CompanionPhase.SUCCESS}:
        return Placement.SPEECH_BUBBLE
    if phase in {CompanionPhase.WORKING, CompanionPhase.PLANNING, CompanionPhase.REVIEWING}:
        return Placement.DOCKED
    return Placement.COMPACT


def select_presentation(
    plan: CapabilityPresentationPlan,
    signals: PresentationSignals,
    *,
    phase: CompanionPhase = CompanionPhase.IDLE,
) -> PresentationDecision:
    """Select at or below the implementation authorized by the capability plan."""
    selected = plan.presentation_ceiling
    reasons = [
        f"capability plan {plan.plan_id} permits at most {plan.presentation_ceiling.value}"
    ]
    if plan.action not in {"start_local", "start_remote"}:
        selected = PresentationKind.TEXT_ONLY
        reasons.append(f"capability action is {plan.action}; only task text remains")

    if signals.user_preference is not None:
        preferred = _degrade(selected, signals.user_preference)
        if preferred != selected:
            selected = preferred
            reasons.append("user preference selected a lighter presentation")

    no_display = signals.headless or not signals.display_available
    if no_display:
        fallback = PresentationKind.AUDIO_ONLY if signals.audio_output_available else PresentationKind.TEXT_ONLY
        selected = _degrade(selected, fallback)
        # A text-only plan must not be upgraded to audio by a missing display.
        if plan.presentation_ceiling == PresentationKind.TEXT_ONLY:
            selected = PresentationKind.TEXT_ONLY
        reasons.append("no display is available; visual rendering is disabled")

    memory = signals.available_memory_bytes
    if memory is not None:
        if memory < 96 * MIB:
            selected = PresentationKind.TEXT_ONLY
            reasons.append("less than 96 MiB is available; text-only is the safe floor")
        elif memory < 256 * MIB:
            fallback = PresentationKind.AUDIO_ONLY if no_display and signals.audio_output_available else PresentationKind.TEXT_ONLY
            selected = _degrade(selected, fallback)
            reasons.append("available memory is below the static-image budget")
        elif memory < 768 * MIB:
            selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
            reasons.append("available memory limits presentation to a static image")
        elif memory < 2 * GIB:
            selected = _degrade(selected, PresentationKind.ANIMATED_2D)
            reasons.append("available memory limits presentation to animated 2D")

    if signals.memory_pressure:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("memory pressure caused an immediate graceful degradation")
    if signals.gpu_pressure:
        selected = _degrade(selected, PresentationKind.ANIMATED_2D)
        reasons.append("GPU pressure removed 3D rendering")
    if selected in {PresentationKind.FULL_3D, PresentationKind.LIGHTWEIGHT_3D}:
        vram = signals.vram_available_bytes
        if not signals.gpu_ready or (vram is not None and vram < GIB):
            selected = _degrade(selected, PresentationKind.ANIMATED_2D)
            reasons.append("GPU readiness or VRAM is insufficient for 3D")
    if signals.thermal_pressure:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("thermal pressure disabled decorative animation")
    if signals.on_battery and signals.battery_percent is not None and signals.battery_percent < 20:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("low battery selected a static presentation")
    if signals.foreground_workload_high:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("the foreground workload has priority over companion rendering")
    if signals.reduced_motion or signals.no_animation:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("accessibility motion preference overrides animation")
    if signals.remote_rendering_requested and not signals.remote_rendering_permitted:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("remote rendering was not permitted")
    if selected == PresentationKind.AUDIO_ONLY and not signals.audio_output_available:
        selected = PresentationKind.TEXT_ONLY
        reasons.append("audio output is unavailable; captions remain")

    return PresentationDecision(
        implementation=selected,
        placement=placement_for_phase(phase),
        # Captions remain in the typed stream even in audio-only/headless
        # presentation so a remote or later visual client can render them.
        captions=True,
        visual_listening_indicator=not no_display and selected != PresentationKind.AUDIO_ONLY,
        visual_speaking_indicator=not no_display and selected != PresentationKind.AUDIO_ONLY,
        plan_id=plan.plan_id,
    captions_always: bool = True
    prefer_text_only: bool = False

    def __post_init__(self) -> None:
        if not 0.75 <= self.text_scale <= 3.0:
            raise ValueError("text scale is outside the supported range (0.75 to 3.0)")

    def to_json(self) -> dict[str, Any]:
        return {
            "reducedMotion": self.reduced_motion,
            "noAnimation": self.no_animation,
            "highContrast": self.high_contrast,
            "textScale": self.text_scale,
            "captionsAlways": self.captions_always,
            "preferTextOnly": self.prefer_text_only,
        }


@dataclass(frozen=True)
class PresentationSignals:
    """The machine facts a presentation choice is made from.

    Every one of these comes either from the capability runtime's own signals —
    see :func:`signals_from_capability_event` — or from the client's own
    display. None of them is measured here: a second measurement would
    eventually disagree with the capability runtime's, and the user would be
    shown one answer while the system acted on another.
    """

    available_memory_bytes: int | None = None
    gpu_available: bool = False
    display_available: bool = True
    audio_output_available: bool = False
    headless: bool = False
    on_battery: bool = False
    battery_percent: float | None = None
    thermal_throttled: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "availableMemoryBytes": self.available_memory_bytes,
            "gpuAvailable": self.gpu_available,
            "displayAvailable": self.display_available,
            "audioOutputAvailable": self.audio_output_available,
            "headless": self.headless,
            "onBattery": self.on_battery,
            "batteryPercent": self.battery_percent,
            "thermalThrottled": self.thermal_throttled,
        }


def signals_from_capability_event(
    signals: Mapping[str, Any],
    *,
    display_available: bool = True,
    audio_output_available: bool = False,
    headless: bool = False,
) -> PresentationSignals:
    """Read the §11 signals the capability runtime already produced."""
    memory = signals.get("availableMemoryBytes")
    battery = signals.get("batteryPercent")
    return PresentationSignals(
        available_memory_bytes=int(memory) if isinstance(memory, int) and not isinstance(memory, bool) else None,
        gpu_available=bool(signals.get("gpuAvailable", False)),
        display_available=display_available,
        audio_output_available=audio_output_available,
        headless=headless,
        on_battery=bool(signals.get("onBattery", False)),
        battery_percent=float(battery) if isinstance(battery, (int, float)) and not isinstance(battery, bool) else None,
        thermal_throttled=bool(signals.get("thermalThrottled", False)),
    )


_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def _degrade(current: str, floor: str) -> str:
    """The lighter of two implementations. Never moves back up the ladder."""
    return PRESENTATION_KINDS[max(_KIND_RANK[current], _KIND_RANK[floor])]


def placement_for_phase(phase: str) -> str:
    if phase in ("idle", "starting", "recovering"):
        return "center"
    if phase in ("waiting_for_approval", "blocked", "error"):
        return "task-panel"
    if phase in ("speaking", "presenting_result", "success"):
        return "speech-bubble"
    if phase in ("working", "planning", "reviewing", "understanding", "listening"):
        return "docked"
    return "compact"


def select_presentation(
    signals: PresentationSignals,
    preferences: AccessibilityPreferences | None = None,
    *,
    phase: str = "idle",
    plan_id: str = "",
) -> PresentationRecommendation:
    """Choose a presentation, at or below what the machine and policy allow.

    Two answers come out of this, and keeping them apart is the whole point.
    ``eligible`` is what the machine could support; ``implementation`` is what
    this build will actually draw, and it is filtered through
    :data:`IMPLEMENTED_PRESENTATIONS` at the end.

    Since the 3D renderer landed the two are equal for every rung this function
    can produce, which is what ``limited_by_implementation`` records when they
    are not. The distinction is kept rather than collapsed because it has been
    load-bearing twice — once for animated 2D and once for 3D — and it will be
    again for whatever is above ``full-3d``.
    """
    preferences = preferences or AccessibilityPreferences()
    reasons: list[str] = []

    eligible = "full-3d"
    if not signals.gpu_available:
        eligible = _degrade(eligible, "animated-2d")
        reasons.append("no usable GPU was reported, so 3D is not eligible")
    memory = signals.available_memory_bytes
    if memory is not None:
        if memory < 96 * _MIB:
            eligible = _degrade(eligible, "text-only")
            reasons.append("less than 96 MiB is available; text is the safe floor")
        elif memory < 256 * _MIB:
            eligible = _degrade(eligible, "audio-only" if signals.audio_output_available else "text-only")
            reasons.append("available memory is below the static-image budget")
        elif memory < 768 * _MIB:
            eligible = _degrade(eligible, "static-image")
            reasons.append("available memory limits presentation to a static image")
        elif memory < 2 * _GIB:
            eligible = _degrade(eligible, "animated-2d")
            reasons.append("available memory limits presentation to animated 2D")
        elif memory < 3 * _GIB:
            eligible = _degrade(eligible, "lightweight-3d")
            reasons.append("available memory limits presentation to lightweight 3D")
    if signals.thermal_throttled:
        eligible = _degrade(eligible, "static-image")
        reasons.append("the machine is thermally throttled; decorative animation is off")
    if signals.on_battery and signals.battery_percent is not None and signals.battery_percent < 20:
        eligible = _degrade(eligible, "static-image")
        reasons.append("the battery is low; a static presentation is used")

    no_display = signals.headless or not signals.display_available
    if no_display:
        eligible = _degrade(eligible, "audio-only" if signals.audio_output_available else "text-only")
        reasons.append("no display is available")
    if preferences.reduced_motion or preferences.no_animation:
        eligible = _degrade(eligible, "static-image")
        reasons.append("the accessibility motion preference removes animation")
    if preferences.prefer_text_only:
        eligible = _degrade(eligible, "text-only")
        reasons.append("you asked for text only")

    selected = eligible
    limited = False
    while selected not in IMPLEMENTED_PRESENTATIONS:
        limited = True
        selected = PRESENTATION_KINDS[_KIND_RANK[selected] + 1]
    if selected == "audio-only" and not signals.audio_output_available:
        selected = "text-only"
        reasons.append("audio output is unavailable; captions remain")
    if limited:
        reasons.append(
            f"this build implements {', '.join(sorted(IMPLEMENTED_PRESENTATIONS))} only, "
            f"so {selected} was drawn where {eligible} would have been permitted"
        )

    return PresentationRecommendation(
        implementation=selected,
        eligible=eligible,
        limited_by_implementation=limited,
        placement=placement_for_phase(phase),
        # Captions are always produced, in every implementation. They are the
        # authoritative rendering of what the companion said; audio is the
        # optional one. An audio-only presentation still carries its captions so
        # a client that can show them does.
        captions=True,
        audio_available=signals.audio_output_available,
        plan_id=plan_id,
        reasons=tuple(reasons),
    )


class AdaptivePresentationController:
    """Immediate degradation, delayed recovery to prevent renderer flapping."""

    def __init__(self, *, recovery_samples: int = 3) -> None:
        if recovery_samples < 1:
            raise ValueError("recovery sample count must be positive")
        self.recovery_samples = recovery_samples
        self.current: PresentationDecision | None = None
        self._candidate: PresentationKind | None = None
        self._healthy_samples = 0

    def update(
        self,
        plan: CapabilityPresentationPlan,
        signals: PresentationSignals,
        *,
        phase: CompanionPhase = CompanionPhase.IDLE,
    ) -> PresentationDecision:
        proposed = select_presentation(plan, signals, phase=phase)
        if self.current is None:
            self.current = proposed
            return proposed
        current_rank = _RANK[self.current.implementation]
        proposed_rank = _RANK[proposed.implementation]
        if proposed_rank >= current_rank:
            self.current = proposed
            self._candidate = None
            self._healthy_samples = 0
            return proposed
        if self._candidate != proposed.implementation:
            self._candidate = proposed.implementation
            self._healthy_samples = 1
        else:
            self._healthy_samples += 1
        if self._healthy_samples >= self.recovery_samples:
            self.current = proposed
            self._candidate = None
            self._healthy_samples = 0
            return proposed
        held = PresentationDecision(
            implementation=self.current.implementation,
            placement=proposed.placement,
            captions=self.current.captions,
            visual_listening_indicator=self.current.visual_listening_indicator,
            visual_speaking_indicator=self.current.visual_speaking_indicator,
            plan_id=proposed.plan_id,
            reasons=(*proposed.reasons, "renderer recovery is held by hysteresis"),
        )
        self.current = held
        return held
# --------------------------------------------------------------------------- #
# Window policy
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MonitorGeometry:
    monitor_id: str
    x: int
    y: int
    width: int
    height: int
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    scale: float = 1.0


@dataclass(frozen=True)
class DesktopContext:
    monitors: tuple[MonitorGeometry, ...]
    active_monitor_id: str | None = None
    fullscreen_application: bool = False
    notifications_suppressed: bool = False
    active_application_bounds: tuple[int, int, int, int] | None = None
    monitors: tuple[MonitorGeometry, ...] = ()
    active_monitor_id: str = ""
    fullscreen_application: bool = False
    notifications_suppressed: bool = False


@dataclass(frozen=True)
class WindowPreferences:
    snap_position: str = "right"
    always_on_top: bool = False
    click_through_when_idle: bool = True
    hide_during_fullscreen: bool = False
    preserve_focus: bool = True

    def __post_init__(self) -> None:
        if self.snap_position not in {"left", "right", "top-left", "top-right", "bottom-left", "bottom-right"}:
            raise ValueError("window snap position is invalid")


@dataclass(frozen=True)
class WindowDirective:
    visible: bool
    placement: Placement
    monitor_id: str | None
    snap_position: str
    always_on_top: bool
    click_through: bool
    accept_focus: bool
    suppress_notification: bool
    compact_for_fullscreen: bool
    always_on_top: bool = False
    hide_during_fullscreen: bool = False
    #: Whether the surface refuses focus it was not given. Default ``True``:
    #: §13 forbids stealing focus during a refresh, and the only setting that
    #: makes that true by construction is one where the window never asks.
    preserve_focus: bool = True


@dataclass(frozen=True)
class WindowDirective:
    """What the client should do with its window, and what it may not claim.

    ``absolute_placement_available`` is ``False`` and there is no code path that
    sets it otherwise. GTK4 on Wayland does not expose window positioning to the
    application, and a directive that named a monitor and an offset would be a
    request the compositor is free to ignore — reported as though it had been
    obeyed. The placement here therefore drives *size and shape* only, and the
    field exists so a reader is told that rather than left to infer it.
    """

    visible: bool = True
    placement: str = "center"
    monitor_id: str = ""
    always_on_top: bool = False
    accept_focus: bool = False
    suppress_notification: bool = False
    compact_for_fullscreen: bool = False
    absolute_placement_available: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "visible": self.visible,
            "placement": self.placement.value,
            "monitorId": self.monitor_id,
            "snapPosition": self.snap_position,
            "alwaysOnTop": self.always_on_top,
            "clickThrough": self.click_through,
            "acceptFocus": self.accept_focus,
            "suppressNotification": self.suppress_notification,
            "compactForFullscreen": self.compact_for_fullscreen,
            "placement": self.placement,
            "monitorId": self.monitor_id,
            "alwaysOnTop": self.always_on_top,
            "acceptFocus": self.accept_focus,
            "suppressNotification": self.suppress_notification,
            "compactForFullscreen": self.compact_for_fullscreen,
            "absolutePlacementAvailable": self.absolute_placement_available,
        }


def window_directive(
    phase: CompanionPhase,
    preferences: WindowPreferences,
    context: DesktopContext,
) -> WindowDirective:
    approval = phase == CompanionPhase.WAITING_FOR_APPROVAL
    placement = placement_for_phase(phase)
    fullscreen = context.fullscreen_application and not approval
    if fullscreen:
        placement = Placement.COMPACT
    visible = not (fullscreen and preferences.hide_during_fullscreen)
    passive = phase in {CompanionPhase.IDLE, CompanionPhase.SLEEPING, CompanionPhase.WORKING}
    return WindowDirective(
        visible=visible,
        placement=placement,
        monitor_id=context.active_monitor_id or (context.monitors[0].monitor_id if context.monitors else None),
        snap_position=preferences.snap_position,
        always_on_top=preferences.always_on_top and not fullscreen,
        click_through=preferences.click_through_when_idle and passive and not approval,
        accept_focus=approval or not preferences.preserve_focus,
        suppress_notification=context.notifications_suppressed or fullscreen,
        compact_for_fullscreen=fullscreen,
    )
    phase: str,
    preferences: WindowPreferences | None = None,
    context: DesktopContext | None = None,
) -> WindowDirective:
    """Decide the window's shape from the phase. Pure, and display-free.

    The one case that takes focus is an outstanding approval, and it takes it
    because a question nobody can see is a question that will time out into a
    denial. Every other phase leaves focus exactly where the user put it — a
    refresh must never move it, which is why ``accept_focus`` is derived from
    the phase rather than raised whenever the state changes.
    """
    preferences = preferences or WindowPreferences()
    context = context or DesktopContext()
    approval = phase == "waiting_for_approval"
    placement = placement_for_phase(phase)
    fullscreen = context.fullscreen_application and not approval
    if fullscreen:
        placement = "compact"
    return WindowDirective(
        visible=not (fullscreen and preferences.hide_during_fullscreen),
        placement=placement,
        monitor_id=context.active_monitor_id or (
            context.monitors[0].monitor_id if context.monitors else ""
        ),
        always_on_top=preferences.always_on_top and not fullscreen,
        accept_focus=approval or not preferences.preserve_focus,
        suppress_notification=context.notifications_suppressed or fullscreen,
        compact_for_fullscreen=fullscreen,
        absolute_placement_available=False,
    )


def withheld(classification: str) -> str:
    """Re-exported so a client can render a withheld marker consistently."""
    return withheld_marker(classification)


def summarise(events: Sequence[TaskEvent]) -> PresentationState:
    """Convenience for the CLI: fold a stream at the ``ui`` audience."""
    return project_presentation(events)

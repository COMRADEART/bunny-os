# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure projection from companion runtime facts into visible character state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .schema import CharacterManifest, REQUIRED_CHARACTER_STATES


class CharacterState(str, Enum):
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
    RESEARCHING = "researching"
    TYPING = "typing"
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
    MOVING = "moving"
    REPOSITIONING = "repositioning"


if tuple(state.value for state in CharacterState) != REQUIRED_CHARACTER_STATES:
    raise AssertionError("character state enum and package contract have drifted")


FALLBACK_CHAINS: Mapping[str, tuple[str, ...]] = {
    "unavailable": ("unavailable", "disconnected", "idle", "static_fallback"),
    "starting": ("starting", "idle", "static_fallback"),
    "idle": ("idle", "static_fallback"),
    "greeting": ("greeting", "idle", "static_fallback"),
    "listening": ("listening", "idle", "static_fallback"),
    "transcribing": ("transcribing", "listening", "idle", "static_fallback"),
    "understanding": ("understanding", "planning", "working", "idle", "static_fallback"),
    "waiting_for_user": ("waiting_for_user", "listening", "idle", "static_fallback"),
    "waiting_for_approval": ("waiting_for_approval", "warning", "idle", "static_fallback"),
    "planning": ("planning", "thinking", "working", "idle", "static_fallback"),
    "working": ("working", "idle", "static_fallback"),
    "researching": ("researching", "working", "thinking", "idle", "static_fallback"),
    "typing": ("typing", "working", "idle", "static_fallback"),
    "reviewing": ("reviewing", "working", "thinking", "idle", "static_fallback"),
    "speaking": ("speaking", "idle", "static_fallback"),
    "presenting_result": ("presenting_result", "speaking", "success", "idle", "static_fallback"),
    "success": ("success", "idle", "static_fallback"),
    "warning": ("warning", "idle", "static_fallback"),
    "blocked": ("blocked", "warning", "idle", "static_fallback"),
    "degraded": ("degraded", "warning", "idle", "static_fallback"),
    "error": ("error", "warning", "idle", "static_fallback"),
    "paused": ("paused", "idle", "static_fallback"),
    "cancelled": ("cancelled", "idle", "static_fallback"),
    "disconnected": ("disconnected", "unavailable", "idle", "static_fallback"),
    "sleeping": ("sleeping", "idle", "static_fallback"),
    "moving": ("moving", "repositioning", "idle", "static_fallback"),
    "repositioning": ("repositioning", "moving", "idle", "static_fallback"),
}

RUNTIME_STATE_MAP: Mapping[str, CharacterState] = {
    "created": CharacterState.STARTING,
    "classifying": CharacterState.UNDERSTANDING,
    "waiting_for_capability": CharacterState.UNDERSTANDING,
    "waiting_for_executor": CharacterState.PLANNING,
    "waiting_for_approval": CharacterState.WAITING_FOR_APPROVAL,
    "planning": CharacterState.PLANNING,
    "executing": CharacterState.WORKING,
    "reviewing": CharacterState.REVIEWING,
    "presenting": CharacterState.PRESENTING_RESULT,
    "completed": CharacterState.SUCCESS,
    "blocked": CharacterState.BLOCKED,
    "failed": CharacterState.ERROR,
    "cancelled": CharacterState.CANCELLED,
    "cancelling": CharacterState.CANCELLED,
    "paused": CharacterState.PAUSED,
    "recovering": CharacterState.STARTING,
}


@dataclass(frozen=True)
class AccessibilityPreferences:
    reduced_motion: bool = False
    no_animation: bool = False
    disable_decorative_movement: bool = False
    disable_flashing: bool = False
    high_contrast: bool = False
    character_scale: float = 1.0
    bubble_scale: float = 1.0
    frame_rate_cap: int = 60

    def __post_init__(self) -> None:
        if not 0.5 <= self.character_scale <= 3.0:
            raise ValueError("character scale must be between 0.5 and 3")
        if not 0.75 <= self.bubble_scale <= 3.0:
            raise ValueError("bubble scale must be between 0.75 and 3")
        if not 1 <= self.frame_rate_cap <= 60:
            raise ValueError("frame-rate cap must be between 1 and 60")


@dataclass(frozen=True)
class StateMapperInput:
    """Everything the mapper is allowed to see. Nothing here is a task fact the
    canonical projection did not already establish.

    ``presentation_phase`` is the canonical
    :attr:`companion.presentation.PresentationState.phase` — already resolved by
    §12's priority order — and it is *authoritative*. Every other field either
    refines it within what it permits (``current_tool``, ``tool_activity``) or
    describes something the projection does not hold because it is not a
    property of the task at all: what the window is doing (``repositioning``),
    what the microphone is doing (``listening``, ``transcribing``), and whether
    the renderer itself is healthy.

    The first implementation of this took ``runtime_state`` — the *canonical
    task state* — and re-derived priority from a dozen flags. That was a second
    priority system running beside the projection's, and two priority systems
    disagree the first time one of them gains a state.
    """

    presentation_phase: str
    current_tool: str = ""
    tool_activity: str = ""
    approval_pending: bool = False
    speaking: bool = False
    listening: bool = False
    transcribing: bool = False
    repositioning: bool = False
    #: The session has been quiet long enough that the companion should visibly
    #: sleep. Not a task fact — the projection has no notion of "long enough" —
    #: which is exactly why it arrives here as a client flag alongside the
    #: microphone and the window drag.
    #:
    #: Before this, :attr:`CharacterState.SLEEPING` was in the enum, in the
    #: priority order, in every fallback chain and in the package contract, and
    #: nothing anywhere could produce it. §2 of the polished-alpha brief lists
    #: sleeping as one of the states the companion must be able to show.
    dormant: bool = False
    #: The companion is performing its first-run greeting. Set by the first-boot
    #: sequence and cleared when it ends; §9's "companion appears → greeting
    #: animation" is this flag's whole purpose, and like ``dormant`` it had a
    #: state, a chain and an animation slot but no way in.
    greeting: bool = False
    reviewer_warning: bool = False
    error_summary: str = ""
    effective_presentation: str = "animated-2d"
    degradation_explanation: str = ""
    accessibility: AccessibilityPreferences = AccessibilityPreferences()
    status_text: str = ""
    renderer_healthy: bool = True


@dataclass(frozen=True)
class MappedCharacterState:
    character_state: CharacterState
    resolved_package_state: str
    expression: str
    animation: str
    playback_policy: str
    loop: bool
    transition_type: str
    bubble_visible: bool
    bubble_anchor: dict[str, float | str]
    accessibility_description: str
    degradation_explanation: str
    frame_rate_cap: int
    fallback_chain: tuple[str, ...]
    priority_reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "characterState": self.character_state.value,
            "resolvedPackageState": self.resolved_package_state,
            "expression": self.expression,
            "animation": self.animation,
            "playbackPolicy": self.playback_policy,
            "loop": self.loop,
            "transitionType": self.transition_type,
            "bubbleVisible": self.bubble_visible,
            "bubbleAnchor": dict(self.bubble_anchor),
            "accessibilityDescription": self.accessibility_description,
            "degradationExplanation": self.degradation_explanation,
            "frameRateCap": self.frame_rate_cap,
            "fallbackChain": list(self.fallback_chain),
            "priorityReason": self.priority_reason,
        }


def resolve_state(manifest: CharacterManifest, state: CharacterState) -> tuple[str, str, tuple[str, ...]]:
    chain = FALLBACK_CHAINS[state.value]
    visited: list[str] = []
    for candidate in chain:
        visited.append(candidate)
        animation = manifest.state_map.get(candidate)
        if animation is not None:
            return candidate, animation, tuple(visited)
        if candidate == "static_fallback":
            return candidate, "__static_fallback__", tuple(visited)
    raise AssertionError("every fallback chain ends in static_fallback")


#: Canonical presentation phase -> character state, one to one.
#:
#: The canonical vocabulary is :data:`companion.presentation.PRESENTATION_PHASES`
#: and every one of its members appears here; a test compares the two lists, so
#: a phase added to the projection cannot silently render as idle.
CANONICAL_PHASE_STATES: Mapping[str, CharacterState] = {
    "idle": CharacterState.IDLE,
    "starting": CharacterState.STARTING,
    "recovering": CharacterState.STARTING,
    "understanding": CharacterState.UNDERSTANDING,
    "planning": CharacterState.PLANNING,
    "waiting_for_approval": CharacterState.WAITING_FOR_APPROVAL,
    "listening": CharacterState.LISTENING,
    "speaking": CharacterState.SPEAKING,
    "working": CharacterState.WORKING,
    "reviewing": CharacterState.REVIEWING,
    "presenting_result": CharacterState.PRESENTING_RESULT,
    "success": CharacterState.SUCCESS,
    "cancelling": CharacterState.CANCELLED,
    "cancelled": CharacterState.CANCELLED,
    "paused": CharacterState.PAUSED,
    "blocked": CharacterState.BLOCKED,
    "error": CharacterState.ERROR,
    "disconnected": CharacterState.DISCONNECTED,
}

#: §6's priority, most urgent first. Every character state is ranked; the ones
#: §6 names appear in this order and a test asserts that as a subsequence.
STATE_PRIORITY: tuple[CharacterState, ...] = (
    CharacterState.ERROR,
    CharacterState.BLOCKED,
    CharacterState.WAITING_FOR_APPROVAL,
    CharacterState.WARNING,
    CharacterState.CANCELLED,
    CharacterState.LISTENING,
    CharacterState.TRANSCRIBING,
    CharacterState.SPEAKING,
    CharacterState.WORKING,
    CharacterState.RESEARCHING,
    CharacterState.TYPING,
    CharacterState.REVIEWING,
    CharacterState.PRESENTING_RESULT,
    CharacterState.SUCCESS,
    CharacterState.PLANNING,
    CharacterState.UNDERSTANDING,
    CharacterState.WAITING_FOR_USER,
    CharacterState.PAUSED,
    CharacterState.DEGRADED,
    CharacterState.REPOSITIONING,
    CharacterState.MOVING,
    CharacterState.GREETING,
    CharacterState.STARTING,
    CharacterState.SLEEPING,
    CharacterState.IDLE,
    CharacterState.DISCONNECTED,
    CharacterState.UNAVAILABLE,
)

_PRIORITY_RANK = {state: index for index, state in enumerate(STATE_PRIORITY)}


def priority_rank(state: CharacterState) -> int:
    """Lower is more urgent. Used to prove a refinement did not hide anything."""
    return _PRIORITY_RANK[state]


#: Phases during which a client-side flag may refine the character state.
#:
#: Everything absent from this set — an error, a block, an approval, a
#: cancellation — is a phase in which the user needs to see the *task*, and a
#: microphone indicator or a window drag may not take the surface away from it.
#: This is the mechanism behind §6's "a decorative animation must never hide an
#: approval, warning or error": the refinement is not merely lower priority, it
#: is not consulted at all.
#: States that are the *same urgency* as their base, drawn more specifically.
#:
#: §6 puts working, researching and typing in one bucket — "active work" — so a
#: narrowing is not a demotion even though the total order has to put them in
#: some sequence. Without this the rank check, which is otherwise exactly right,
#: rejected ``typing`` as less urgent than ``working`` and the character never
#: showed the more specific state it had the art for.
_NARROWINGS: Mapping[CharacterState, frozenset[CharacterState]] = {
    CharacterState.WORKING: frozenset({CharacterState.RESEARCHING, CharacterState.TYPING}),
}

_REFINABLE_PHASES = frozenset({
    "idle", "starting", "recovering", "understanding", "planning",
    "working", "reviewing", "presenting_result", "success", "listening",
    "speaking", "paused",
})


def _select_state(value: StateMapperInput) -> tuple[CharacterState, str]:
    """Take the canonical phase and refine it, never overrule it.

    The canonical projection has already applied §12's priority across
    everything it knows. This function's whole job is to turn that one phase
    into a *character* state, using facts the projection does not hold, and the
    closing assertion is what keeps "refine" from quietly becoming "decide".
    """
    phase = value.presentation_phase
    base = CANONICAL_PHASE_STATES.get(phase)
    if base is None:
        # A phase this build does not know. Idle is the safe rendering — it
        # claims nothing — and the reason says so rather than pretending the
        # mapping was deliberate.
        return CharacterState.IDLE, f"unknown presentation phase {phase!r} renders as idle"

    reason = f"canonical presentation phase {phase}"

    # Refinements that make the surface *more* urgent are always permitted:
    # they can only ever move towards the thing the user must attend to.
    if value.approval_pending and base is not CharacterState.WAITING_FOR_APPROVAL:
        if priority_rank(CharacterState.WAITING_FOR_APPROVAL) < priority_rank(base):
            return CharacterState.WAITING_FOR_APPROVAL, "an approval is outstanding"
    if value.reviewer_warning and priority_rank(CharacterState.WARNING) < priority_rank(base):
        return CharacterState.WARNING, "a reviewer recorded a material disagreement"
    # An open microphone is shown in *every* phase, not only the refinable ones.
    #
    # This used to sit below with the decorative refinements, gated behind
    # ``_REFINABLE_PHASES``. The consequence was that a client whose runtime had
    # gone away rendered as ``disconnected`` while its microphone was still
    # open — a person being recorded with nothing on screen saying so. Whether
    # the phase is refinable is a question about *decoration*; a live capture
    # device is not decoration, and it is ranked below approvals and errors so
    # promoting it here can still never take the surface from a question.
    if value.transcribing and priority_rank(CharacterState.TRANSCRIBING) < priority_rank(base):
        return CharacterState.TRANSCRIBING, "the client is transcribing speech"
    if value.listening and priority_rank(CharacterState.LISTENING) < priority_rank(base):
        return CharacterState.LISTENING, "the microphone is on"
    if not value.renderer_healthy and priority_rank(CharacterState.DEGRADED) < priority_rank(base):
        return CharacterState.DEGRADED, "the renderer is degraded; the task is unaffected"

    if phase not in _REFINABLE_PHASES:
        return base, reason

    # Candidates, in §6's order among themselves. Gathered rather than returned
    # one by one, so the rank check below applies to *all* of them.
    #
    # Returning each from its own branch is how this went wrong twice: a
    # `repositioning` window drag rendered a paused task as "repositioning", and
    # an unhealthy renderer rendered it as "degraded" — both less urgent than
    # the canonical phase, both from a branch that had simply forgotten to ask.
    # One check at the end cannot forget.
    candidates: list[tuple[CharacterState, str]] = []
    if value.transcribing:
        candidates.append((CharacterState.TRANSCRIBING, "the client is transcribing speech"))
    if value.listening:
        candidates.append((CharacterState.LISTENING, "the microphone is on"))
    if value.speaking:
        candidates.append((CharacterState.SPEAKING, "the client is speaking the caption"))
    if value.repositioning:
        candidates.append(
            (CharacterState.REPOSITIONING, "the user is repositioning the character")
        )
    if value.greeting:
        candidates.append((CharacterState.GREETING, "the companion is giving its first-run greeting"))
    if value.dormant:
        # Ranked just above idle, so it wins against idle and loses to
        # everything else. A companion that slept through an approval because
        # the machine had been quiet is the failure this ordering prevents.
        candidates.append((CharacterState.SLEEPING, "the session has been quiet long enough to sleep"))
    # The one refinement drawn from the task itself, and it is a *narrowing*:
    # `working` becomes a more specific kind of working, never something else.
    if base is CharacterState.WORKING:
        activity = value.tool_activity.casefold()
        if activity in {"research", "researching", "web", "browse"}:
            candidates.append(
                (CharacterState.RESEARCHING, f"tool {value.current_tool} is a research activity")
            )
        elif activity in {"typing", "write", "editing"}:
            candidates.append(
                (CharacterState.TYPING, f"tool {value.current_tool} produces visible output")
            )
    if not value.renderer_healthy:
        candidates.append(
            (CharacterState.DEGRADED, "the renderer is degraded; the task is unaffected")
        )

    permitted = [
        item for item in candidates
        if priority_rank(item[0]) <= priority_rank(base) or item[0] in _NARROWINGS.get(base, ())
    ]
    if not permitted:
        return base, reason
    return min(permitted, key=lambda item: priority_rank(item[0]))


_DESCRIPTIONS: Mapping[CharacterState, str] = {
    CharacterState.UNAVAILABLE: "Bunny is unavailable.",
    CharacterState.STARTING: "Bunny is starting.",
    CharacterState.IDLE: "Bunny is idle and ready.",
    CharacterState.GREETING: "Bunny is greeting you.",
    CharacterState.LISTENING: "Bunny is listening.",
    CharacterState.TRANSCRIBING: "Bunny is transcribing speech.",
    CharacterState.UNDERSTANDING: "Bunny is interpreting the request.",
    CharacterState.WAITING_FOR_USER: "Bunny is waiting for your response.",
    CharacterState.WAITING_FOR_APPROVAL: "Bunny needs your approval before anything continues.",
    CharacterState.PLANNING: "Bunny is preparing the task plan.",
    CharacterState.WORKING: "Bunny is working on the task.",
    CharacterState.RESEARCHING: "Bunny is researching within the permitted task.",
    CharacterState.TYPING: "Bunny is preparing visible task output.",
    CharacterState.REVIEWING: "An observation-only reviewer is checking the task.",
    CharacterState.SPEAKING: "Bunny is speaking; captions are available.",
    CharacterState.PRESENTING_RESULT: "Bunny is presenting the result.",
    CharacterState.SUCCESS: "The task completed successfully.",
    CharacterState.WARNING: "The task has a warning that needs attention.",
    CharacterState.BLOCKED: "The task is blocked and has not continued.",
    CharacterState.DEGRADED: "Bunny's presentation is reduced; the task continues.",
    CharacterState.ERROR: "The task or renderer encountered an error.",
    CharacterState.PAUSED: "The task is paused.",
    CharacterState.CANCELLED: "The task was cancelled.",
    CharacterState.DISCONNECTED: "The visual companion is disconnected; the task may continue headlessly.",
    CharacterState.SLEEPING: "Bunny is sleeping.",
    CharacterState.MOVING: "Bunny is moving without taking keyboard focus.",
    CharacterState.REPOSITIONING: "Bunny is being repositioned without taking keyboard focus.",
}


def map_character_state(manifest: CharacterManifest, value: StateMapperInput) -> MappedCharacterState:
    """Map only declared inputs. No task-state shadow, no hidden inference.

    Pure: the same manifest and the same input always produce the same output,
    with no clock, no filesystem and no capability probe anywhere in it. That is
    what makes every state in §19's list a table-driven test rather than a
    scenario.
    """
    state, priority = _select_state(value)
    if value.accessibility.disable_decorative_movement and state is CharacterState.MOVING:
        state, priority = CharacterState.IDLE, "decorative movement disabled"
    resolved, animation_name, chain = resolve_state(manifest, state)
    if animation_name == "__static_fallback__":
        transition = "immediate"
        loop = False
        playback = "static"
    else:
        animation = manifest.animation(animation_name)
        transition = animation.transition
        loop = animation.loop
        playback = "loop" if animation.loop else "one-shot"
    if (
        value.accessibility.reduced_motion
        or value.accessibility.no_animation
        or value.accessibility.disable_flashing
    ):
        transition = "immediate"
        loop = False
        playback = "static-first-frame"
    if state in {CharacterState.WAITING_FOR_APPROVAL, CharacterState.ERROR, CharacterState.BLOCKED}:
        loop = False
        if playback == "loop":
            playback = "hold-first-frame"
    expression = next((name for name in (state.value, resolved, "neutral") if name in manifest.expression_map), "neutral")
    bubble = bool(value.status_text) and state in {
        CharacterState.WAITING_FOR_APPROVAL, CharacterState.WAITING_FOR_USER,
        CharacterState.SPEAKING, CharacterState.PRESENTING_RESULT,
        CharacterState.SUCCESS, CharacterState.WARNING, CharacterState.BLOCKED,
        CharacterState.ERROR,
    }
    degradation = value.degradation_explanation
    if value.effective_presentation == "text-only" and not degradation:
        degradation = "The capability presentation plan selected text-only output."
    if not value.renderer_healthy and not degradation:
        degradation = "The renderer failed and fell back; the task is unaffected."
    return MappedCharacterState(
        character_state=state,
        resolved_package_state=resolved,
        expression=expression,
        animation=animation_name,
        playback_policy=playback,
        loop=loop,
        transition_type=transition,
        bubble_visible=bubble,
        bubble_anchor=manifest.bubble_anchor.to_json(),
        accessibility_description=_DESCRIPTIONS[state],
        degradation_explanation=degradation,
        frame_rate_cap=value.accessibility.frame_rate_cap,
        fallback_chain=chain,
        priority_reason=priority,
    )

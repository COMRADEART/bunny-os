# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one door between the canonical companion and the character renderer.

Everything the renderer knows about a task arrives through this module, and it
arrives as a :class:`companion.presentation.PresentationState` — the projection
the integration runtime already computed, already resolved by §12 priority, and
already redacted at the ``ui`` ceiling. Nothing here reads a
:class:`companion.events.TaskEvent`, a :class:`companion.task.CompanionTask`, or
the store.

That is the point, and it is a deliberate departure from this renderer's first
implementation. That version had a ``context_from_events`` which walked the raw
event stream and built its own idea of what the task was doing — its own status
sentences, its own approval tracking, its own notion of which event meant
"working". It predated the canonical projection, and it was *a second
interpretation of the record*: the thing the integration phase existed to
remove. Two interpretations do not stay in agreement. The one that draws the
picture would eventually disagree with the one that decides whether the task
finished, and the user would be looking at the wrong one.

So the rule §11 states — *the renderer displays sanitized text supplied by the
integration runtime and must never construct task status from raw events
independently* — is enforced structurally rather than by discipline: this module
imports nothing that could construct it, and a test asserts that from the import
graph.

**The canonical phase is authoritative.** :func:`mapper_input_for` passes it
through untouched and :func:`companion.character.mapper.map_character_state` may
only *refine* it — turning ``working`` into ``typing`` when the runtime says
which tool is running. A test asserts that refinement never yields a less urgent
character state than the canonical phase implies, so a decorative refinement
cannot hide an approval, a warning or an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from companion.presentation import PresentationState

from .bubble import BubbleKind, sanitize_bubble_text
from .mapper import AccessibilityPreferences, StateMapperInput

__all__ = [
    "CharacterBubbleRequest",
    "bubble_request_for",
    "mapper_input_for",
    "presentation_state_from_json",
]

#: Tools whose names tell the surface something a person would recognise.
#:
#: Deliberately a small, explicit table rather than a substring search. A
#: renderer that guessed "this tool sounds like research" would be inventing a
#: fact about the task, which is the one thing this module exists to prevent. A
#: tool that is not named here renders as ``working``, which is true of every
#: tool.
_TOOL_ACTIVITY: Mapping[str, str] = {
    "text.count_words": "typing",
    "text.validate_count": "typing",
    "text.checksum": "typing",
    "notice.publish": "typing",
}


@dataclass(frozen=True)
class CharacterBubbleRequest:
    """What the speech bubble should say, and how urgently.

    The text is the projection's own — a caption, a result summary or an error
    summary the runtime already bounded, sanitized and stripped of markup. This
    module chooses *which* of them to show and nothing else; it never composes a
    sentence about the task.
    """

    text: str
    kind: BubbleKind
    persistent: bool
    visible: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "kind": self.kind.value,
            "persistent": self.persistent,
            "visible": self.visible,
        }


def mapper_input_for(
    state: PresentationState,
    *,
    accessibility: AccessibilityPreferences | None = None,
    listening: bool = False,
    speaking: bool = False,
    transcribing: bool = False,
    repositioning: bool = False,
    renderer_healthy: bool = True,
    degradation_explanation: str = "",
) -> StateMapperInput:
    """Translate the canonical projection into the mapper's input.

    The keyword arguments are the facts the canonical projection does not and
    should not hold. ``listening``, ``speaking`` and ``transcribing`` happen on
    the user's own machine in the client — audio that became a task event would
    be audio that reached durable storage — and ``repositioning`` and
    ``renderer_healthy`` are properties of the window and the renderer rather
    than of the task.
    """
    # A disagreement from the *latest* review round is a current warning. One
    # from an earlier round is history, and the projection keeps it — correctly,
    # because §10 requires material disagreement to stay visible after the
    # executor revises around it.
    #
    # Treating every disagreement in the list as current pinned the character in
    # `warning` for the rest of the task's life: the shipped reviewer objects to
    # round one's plan by design, the executor fixes it in round two, and the
    # character sat looking worried through the result, the success and
    # everything after. Visible in the record is not the same as true now.
    rounds = [item.round_number for item in state.observations]
    latest_round = max(rounds) if rounds else 0
    reviewer_warning = any(
        (item.disagreement or item.severity in ("high", "blocking"))
        and item.round_number >= latest_round
        for item in state.observations
    )
    return StateMapperInput(
        presentation_phase=state.phase,
        current_tool=state.current_tool,
        tool_activity=_TOOL_ACTIVITY.get(state.current_tool, ""),
        approval_pending=state.approval_state == "pending" or bool(state.approvals),
        listening=listening or state.listening,
        speaking=speaking or state.speaking,
        transcribing=transcribing,
        repositioning=repositioning,
        reviewer_warning=reviewer_warning,
        error_summary=state.error_summary,
        # The effective presentation the canonical runtime already decided.
        # Read, never recomputed: §2 forbids the renderer recalculating hardware
        # capability, and the projection's recommendation is the capability
        # runtime's own answer carried forward.
        effective_presentation=state.recommendation.implementation,
        degradation_explanation=degradation_explanation,
        accessibility=accessibility or AccessibilityPreferences(),
        status_text=state.status_text,
        renderer_healthy=renderer_healthy,
    )


def bubble_request_for(state: PresentationState) -> CharacterBubbleRequest:
    """Choose which of the projection's sentences the bubble shows.

    Priority matches §6's: an approval outranks an error outranks a result
    outranks the status line. An approval bubble is *persistent* — it has no
    timeout — because a question that faded off the screen would lapse into a
    denial with nobody having seen it.
    """
    # The canonical *phase* counts here, not only the approvals list. The
    # projection resolves priority before anything else sees it, so a phase of
    # ``waiting_for_approval`` means the user is being asked something — and a
    # bubble that decided otherwise because it could not find a matching record
    # would let a question show as an ordinary caption that times out.
    if state.phase == "waiting_for_approval" or state.approvals or state.approval_state == "pending":
        approval = state.approvals[0] if state.approvals else None
        text = approval.reason if approval is not None and approval.reason else state.status_text
        return CharacterBubbleRequest(
            sanitize_bubble_text(text), BubbleKind.APPROVAL, True, bool(text)
        )
    if state.phase in ("error", "blocked"):
        text = state.error_summary or state.status_text
        return CharacterBubbleRequest(
            sanitize_bubble_text(text), BubbleKind.ERROR, True, bool(text)
        )
    if state.error_summary:
        # A step failed and the task carried on. Shown as a warning, and not
        # persistent: it is information, not a decision waiting on somebody.
        return CharacterBubbleRequest(
            sanitize_bubble_text(state.error_summary), BubbleKind.WARNING, False, True
        )
    if state.phase in ("success", "presenting_result") and state.result_summary:
        return CharacterBubbleRequest(
            sanitize_bubble_text(state.result_summary), BubbleKind.CAPTION, False, True
        )
    text = state.status_text
    return CharacterBubbleRequest(
        sanitize_bubble_text(text), BubbleKind.CAPTION, False, bool(text)
    )


def presentation_state_from_json(document: Mapping[str, Any]) -> PresentationState:
    """Rebuild a projection received over the companion protocol.

    Delegates to the GTK client's own reader so the renderer and the window
    parse one wire format with one implementation. A renderer that wrote its own
    parser would be the same mistake as a renderer that wrote its own
    projection, one layer down.
    """
    from companion.gtk_shell import _state_from_json

    return _state_from_json(document)

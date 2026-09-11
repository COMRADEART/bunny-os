# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Outcome-oriented routing: people ask for results, not engines.

The default UX is not a model shop. A person says what they want done;
this module decides whether that happens on this computer, whether it
needs a cloud they already allowed, or whether it cannot be done offline
or under memory pressure — and it says so in a sentence they can read.

The decision itself is :func:`capability.router.route`. This module is
the *explanation* and the *outcome classification*. It never contacts a
named commercial API, never reads a credential, and never lists models
as merchandise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from capability.budget import compute_budget
from capability.model import Inventory
from capability.policy import Policy
from capability.router import (
    NullProvider,
    RemoteProvider,
    RouteDecision,
    TaskRequest,
    route,
)
from capability.scores import compute_scores
from companion.privacy import DATA_CLASSES, router_privacy

__all__ = [
    "OUTCOME_KINDS",
    "OutcomeExplanation",
    "OutcomeRequest",
    "explain_route",
    "route_outcome",
]

OUTCOME_KINDS = (
    "local-work",
    "private-work",
    "needs-network",
    "remember",
)

#: Outcomes a person can ask for without naming an engine. Matched on
#: casefolded substrings; unmatched text is still a local-work request,
#: never a prompt that picks a vendor.
_KIND_HINTS: Mapping[str, tuple[str, ...]] = {
    "needs-network": ("search the web", "look up online", "from the internet"),
    "remember": ("remember", "don't forget", "save this for later"),
    "private-work": ("password", "medical", "doctor", "secret", "private note"),
}


@dataclass(frozen=True)
class OutcomeRequest:
    """What the person asked for, as routing facts — not as a model name."""

    outcome: str
    kind: str = "local-work"
    privacy: str = "internal"
    offline: bool = False
    remote_allowed: bool = False
    local_memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in OUTCOME_KINDS:
            raise ValueError(f"unknown outcome kind: {self.kind!r}")
        if self.privacy not in DATA_CLASSES:
            raise ValueError(f"privacy must be one of {list(DATA_CLASSES)}")
        if len(self.outcome) > 512:
            object.__setattr__(self, "outcome", self.outcome[:511] + "…")

    def to_task(self, task_id: str = "outcome") -> TaskRequest:
        privacy = router_privacy(self.privacy)
        locality = "device-only" if self.kind in {"private-work", "remember"} else "any"
        return TaskRequest(
            id=task_id,
            capability="inference",
            privacy=privacy,
            data_locality=locality,
            requires_offline=self.offline or not self.remote_allowed,
            remote_allowed=self.remote_allowed and self.kind == "needs-network",
            local_memory_bytes=self.local_memory_bytes,
        )


@dataclass(frozen=True)
class OutcomeExplanation:
    """A routing decision a person can read without shopping for models."""

    outcome: str
    kind: str
    target: str
    headline: str
    detail: str
    locality: str
    memory_pressure: bool
    offline_refused: bool
    requires_approval: bool
    reasons: tuple[str, ...]
    decision: RouteDecision

    def to_json(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "kind": self.kind,
            "target": self.target,
            "headline": self.headline,
            "detail": self.detail,
            "locality": self.locality,
            "memoryPressure": self.memory_pressure,
            "offlineRefused": self.offline_refused,
            "requiresApproval": self.requires_approval,
            "reasons": list(self.reasons),
            "decision": self.decision.to_json(),
            "modelsOffered": [],
        }


def classify_outcome(text: str) -> str:
    lowered = str(text or "").strip().casefold()
    for kind, hints in _KIND_HINTS.items():
        if any(hint in lowered for hint in hints):
            return kind
    return "local-work"


def explain_route(request: OutcomeRequest, decision: RouteDecision) -> OutcomeExplanation:
    """Turn a :class:`RouteDecision` into the sentence the surface draws."""
    reasons = tuple(decision.reasons)
    joined = " ".join(reasons).casefold()
    memory = "mib" in joined and ("budget" in joined or "needs" in joined)
    offline = "offline" in joined or "no usable network" in joined
    if decision.target == "local":
        headline = "I'll do this on this computer."
        detail = "Nothing leaves this machine for this request."
        locality = "on this computer"
    elif decision.target == "remote":
        headline = "This needs a cloud you already allowed."
        detail = (
            "Only the authorised slice of this request would leave the computer, "
            "and only after you say so."
        )
        locality = "cloud, if you approve"
    else:
        if request.privacy in {"sensitive", "secret", "personal"}:
            headline = "This stays on this computer, and it cannot run here right now."
            detail = "I will not send private work to a cloud to make up for a weak machine."
        elif memory:
            headline = "This computer is too busy to do that right now."
            detail = "I will not send it somewhere else just because memory is tight."
        elif request.offline or offline:
            headline = "I can't do that while you're offline."
            detail = "This request would need the internet, and you asked me to stay offline."
        else:
            headline = "I can't do that with what's allowed right now."
            detail = "Remote help is off until you turn it on, and local work could not start."
        locality = "nowhere — refused"
    return OutcomeExplanation(
        outcome=request.outcome,
        kind=request.kind,
        target=decision.target,
        headline=headline,
        detail=detail,
        locality=locality,
        memory_pressure=memory,
        offline_refused=bool(request.offline or offline) and decision.target == "refused",
        requires_approval=bool(decision.requires_user_approval),
        reasons=reasons,
        decision=decision,
    )


def route_outcome(
    request: OutcomeRequest,
    inventory: Inventory,
    policy: Policy | None = None,
    providers: Sequence[RemoteProvider] = (),
    *,
    task_id: str = "outcome",
) -> OutcomeExplanation:
    """Route one outcome against a (possibly simulated) inventory.

    ``providers`` defaults to the refusing :class:`NullProvider`, which is
    the product default: no cloud until one is configured and allowed.
    """
    resolved = policy or Policy()
    if request.kind == "needs-network":
        # Searching the web is not a local inference task. Do not pretend a
        # local model fetched the internet.
        if request.offline or inventory.network.offline or not inventory.network.online:
            decision = RouteDecision(
                task_id, "refused",
                reasons=("this request needs the internet, and there is no usable network",),
            )
            return explain_route(request, decision)
        if not resolved.remote_execution.enabled:
            decision = RouteDecision(
                task_id, "refused",
                reasons=(
                    "this request needs the internet, and remote help is off until you turn it on",
                ),
            )
            return explain_route(request, decision)
    scores = compute_scores(inventory)
    budget = compute_budget(inventory, scores, resolved)
    destinations: Sequence[RemoteProvider] = providers or (NullProvider(),)
    decision = route(request.to_task(task_id), inventory, scores, budget, resolved, destinations)
    return explain_route(request, decision)

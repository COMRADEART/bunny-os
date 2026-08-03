# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking a person, and what to do while nobody has answered.

This is the interface only. The Approval Centre — the surface a user actually
sees — is deliberately not built here; what is built is the shape of the
question, so that whatever renders it later cannot render a question that omits
the cost, the destination or the alternative.

The single most important line in this module is the default:

    An unanswered request involving remote execution, money, destruction of
    user work, or interruption of something in progress is **denied**.

Not deferred, not retried, not "assumed fine because the machine is under
pressure". A timeout is an answer, and the answer is no. Anything else means a
user who walked away from their desk comes back to find their data was sent
somewhere because nobody said it should not be.

Approvals expire. An approval is consent to a specific act under specific
circumstances, and both change: consent to spend money on a task that was going
to cost ten cents is not consent to spend it on the same task an hour later
under a plan that now estimates four dollars. So an approval carries the plan it
was granted against, and a plan supersession invalidates it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, Sequence

__all__ = [
    "APPROVAL_DECISIONS",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalStore",
    "DEFAULT_APPROVAL_TTL_SECONDS",
    "DenyingApprovalStore",
    "InMemoryApprovalStore",
    "SENSITIVE_ACTIONS",
]

APPROVAL_DECISIONS = ("granted", "denied", "expired", "pending")

#: How long a granted approval stands. Short by design: an approval is consent
#: to something happening now, and a stale one is consent inferred rather than
#: given.
DEFAULT_APPROVAL_TTL_SECONDS = 900.0

#: Actions whose unanswered default must be denial. Named explicitly rather than
#: inferred, so that adding a new kind of consequential action requires somebody
#: to decide which list it belongs in.
SENSITIVE_ACTIONS = frozenset({
    "remote_dispatch",
    "paid_provider",
    "interrupt_user_work",
    "discard_unsaved_state",
    "stop_essential_service",
    "override_pinned_implementation",
    "send_sensitive_data",
})


@dataclass(frozen=True)
class ApprovalRequest:
    """One question put to a person, with everything needed to answer it.

    Every field exists because a request without it is a request nobody can
    answer responsibly. "May Bunny OS send this somewhere?" is not a question;
    "May Bunny OS send the text of your current document to provider X, which
    retains it for 30 days, at an estimated cost of 4 cents, when the
    alternative is a slower local answer?" is.
    """

    request_id: str
    plan_id: str
    transition_id: str
    service_id: str
    action: str
    #: Why the applicator wants to do this. Structured facts, not persuasion.
    reason: str
    #: What data is involved, in the vocabulary of ``capability.router``.
    data_affected: str = "none"
    #: "local" | "remote"
    destination: str = "local"
    provider_id: str | None = None
    #: Estimated spend in whole currency minor units. ``None`` means free;
    #: ``0`` means "no spend permitted", which is different.
    estimated_cost_units: int | None = None
    resource_impact: Mapping[str, Any] = field(default_factory=dict)
    expires_at_monotonic: float = 0.0
    #: What the user can have instead. Never empty for a sensitive action.
    alternatives: tuple[str, ...] = ()
    #: What happens if nobody answers. Validated below: for a sensitive action
    #: this must be a denial.
    safe_default: str = "denied"

    def __post_init__(self) -> None:
        if self.safe_default not in ("denied", "granted"):
            raise ValueError("safe_default must be 'denied' or 'granted'")
        if self.action in SENSITIVE_ACTIONS and self.safe_default != "denied":
            raise ValueError(
                f"{self.action!r} is a sensitive action and its unanswered default must be denial; "
                "a request that defaults to granted is not a request"
            )
        if self.action in SENSITIVE_ACTIONS and not self.alternatives:
            raise ValueError(
                f"{self.action!r} must state what the user gets if they decline; "
                "a refusal with no alternative is a dead end presented as a choice"
            )

    @property
    def sensitive(self) -> bool:
        return self.action in SENSITIVE_ACTIONS

    def expired(self, now: float) -> bool:
        return self.expires_at_monotonic > 0 and now > self.expires_at_monotonic

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "serviceId": self.service_id,
            "action": self.action,
            "sensitive": self.sensitive,
            "reason": self.reason,
            "dataAffected": self.data_affected,
            "destination": self.destination,
            "providerId": self.provider_id,
            "estimatedCostUnits": self.estimated_cost_units,
            "resourceImpact": dict(self.resource_impact),
            "expiresAtMonotonic": self.expires_at_monotonic,
            "alternatives": list(self.alternatives),
            "safeDefault": self.safe_default,
        }


@dataclass(frozen=True)
class ApprovalResponse:
    """What a person said, and the circumstances they said it about."""

    request_id: str
    decision: str
    #: The plan the approval was granted against. An approval does not survive a
    #: supersession: consent to an act under one set of numbers is not consent
    #: to the same act under different ones.
    plan_id: str = ""
    granted_at_monotonic: float = 0.0
    expires_at_monotonic: float = 0.0
    #: Who answered. Never a service; approvals come from people.
    responder: str = "user"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.decision not in APPROVAL_DECISIONS:
            raise ValueError(f"unknown approval decision: {self.decision!r}")

    def valid(self, now: float, *, plan_id: str | None = None) -> bool:
        if self.decision != "granted":
            return False
        if self.expires_at_monotonic > 0 and now > self.expires_at_monotonic:
            return False
        if plan_id is not None and self.plan_id and self.plan_id != plan_id:
            return False
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "decision": self.decision,
            "planId": self.plan_id,
            "grantedAtMonotonic": self.granted_at_monotonic,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "responder": self.responder,
            "detail": self.detail,
        }


class ApprovalStore(Protocol):
    """Where approval requests are raised and answers are looked up."""

    def request(self, item: ApprovalRequest) -> ApprovalResponse:
        """Raise a request and return the answer known *right now*.

        Never blocks. An applicator that waited on a person would hold a
        reconciliation open for as long as somebody's coffee break, and a
        reconciliation that is open is one that is not adapting to anything
        else that happens meanwhile.
        """

    def approved_services(self, plan_id: str, now: float) -> frozenset[str]:
        """Services with a currently valid approval under this plan."""


@dataclass
class DenyingApprovalStore:
    """The default store: raises requests, grants nothing.

    Every request is recorded so that a UI can later show what was asked, and
    every answer is a denial. This is what a Bunny OS with no Approval Centre
    connected does, and it is the correct behaviour rather than a placeholder:
    a machine with no way to ask a person must not act as though they said yes.
    """

    name: str = "denying"
    requests: list[ApprovalRequest] = field(default_factory=list)

    def request(self, item: ApprovalRequest) -> ApprovalResponse:
        self.requests.append(item)
        return ApprovalResponse(
            item.request_id, "denied", plan_id=item.plan_id,
            responder="default",
            detail=(
                "no approval surface is connected, so this defaults to denial; "
                "nothing was started, sent or interrupted"
            ),
        )

    def approved_services(self, plan_id: str, now: float) -> frozenset[str]:
        return frozenset()

    def pending(self) -> tuple[ApprovalRequest, ...]:
        return tuple(self.requests)

    def to_json(self) -> dict[str, Any]:
        return {
            "store": self.name,
            "note": "No approval is ever granted by this store.",
            "requests": [item.to_json() for item in self.requests],
        }


@dataclass
class InMemoryApprovalStore:
    """A store that can hold answers, for tests and for a connected UI.

    Answers are keyed by request id and validated against the plan they were
    granted for. Granting an approval here is the only way anything in this
    package proceeds past a sensitive action.
    """

    name: str = "in-memory"
    requests: dict[str, ApprovalRequest] = field(default_factory=dict)
    responses: dict[str, ApprovalResponse] = field(default_factory=dict)
    #: Service ids whose sensitive actions are pre-approved, with the plan id
    #: they were approved under.
    default_ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS

    def request(self, item: ApprovalRequest) -> ApprovalResponse:
        self.requests[item.request_id] = item
        existing = self.responses.get(item.request_id)
        if existing is None:
            return ApprovalResponse(item.request_id, "pending", plan_id=item.plan_id)
        return existing

    def grant(self, request_id: str, *, plan_id: str, now: float = 0.0, responder: str = "user") -> ApprovalResponse:
        response = ApprovalResponse(
            request_id, "granted", plan_id=plan_id,
            granted_at_monotonic=now,
            expires_at_monotonic=now + self.default_ttl_seconds,
            responder=responder,
        )
        self.responses[request_id] = response
        return response

    def deny(self, request_id: str, *, plan_id: str = "", responder: str = "user") -> ApprovalResponse:
        response = ApprovalResponse(request_id, "denied", plan_id=plan_id, responder=responder)
        self.responses[request_id] = response
        return response

    def approved_services(self, plan_id: str, now: float) -> frozenset[str]:
        approved: set[str] = set()
        for request_id, response in self.responses.items():
            item = self.requests.get(request_id)
            if item is None:
                continue
            if response.valid(now, plan_id=plan_id):
                approved.add(item.service_id)
        return frozenset(approved)

    def expire(self, now: float) -> tuple[str, ...]:
        """Mark timed-out approvals expired. Returns what lapsed."""
        lapsed: list[str] = []
        for request_id, response in sorted(self.responses.items()):
            if response.decision == "granted" and 0 < response.expires_at_monotonic < now:
                self.responses[request_id] = replace(response, decision="expired")
                lapsed.append(request_id)
        return tuple(lapsed)

    def invalidate_for_plan(self, plan_id: str) -> tuple[str, ...]:
        """Expire every approval granted against a superseded plan."""
        lapsed: list[str] = []
        for request_id, response in sorted(self.responses.items()):
            if response.decision == "granted" and response.plan_id and response.plan_id != plan_id:
                self.responses[request_id] = replace(
                    response, decision="expired",
                    detail=f"the plan this was granted against ({response.plan_id}) has been superseded",
                )
                lapsed.append(request_id)
        return tuple(lapsed)

    def to_json(self) -> dict[str, Any]:
        return {
            "store": self.name,
            "requests": [self.requests[key].to_json() for key in sorted(self.requests)],
            "responses": [self.responses[key].to_json() for key in sorted(self.responses)],
        }


def request_for_transition(
    *,
    plan_id: str,
    transition_id: str,
    service_id: str,
    action: str,
    reason: str,
    now: float,
    ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
    **fields: Any,
) -> ApprovalRequest:
    """Build a request with a deterministic id and a bounded lifetime."""
    return ApprovalRequest(
        request_id=f"approval:{transition_id}",
        plan_id=plan_id,
        transition_id=transition_id,
        service_id=service_id,
        action=action,
        reason=reason,
        expires_at_monotonic=now + ttl_seconds,
        **fields,
    )

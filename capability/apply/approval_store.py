# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A durable approval store: what a person was asked, and what they answered.

:mod:`capability.apply.approval` defines the question. This persists it and the
answer, because an approval that does not survive a supervisor restart is an
approval that has to be asked again every thirty seconds, and a user who is
asked the same question repeatedly stops reading it.

Three properties do the security work, and none of them is the file permissions:

**A decision names the plan it was made against.** Approving a dispatch under a
plan that estimated four cents does not approve the same dispatch under a plan
that now estimates four dollars. When the plan is superseded the approval
becomes invalid, and the store says *why* rather than silently dropping it.

**A decision cannot be forged by editing a field.** The record carries an
authorization digest over the fields that define what was consented to — the
plan, the transition, the action, the destination, the cost. Editing the
decision to ``granted`` without recomputing that digest produces a record the
store rejects. This is not cryptographic authentication and does not claim to
be: an attacker who can write the file can also recompute the digest. It
defends against the realistic case — a well-meaning administrator or a buggy
tool flipping a field — and the file permissions defend against the rest.

**Nothing is granted by default, ever.** A record whose decision cannot be
established is denied, an expired record is denied, and a record for a
superseded plan is denied. There is no code path in which absence of an answer
becomes an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from .approval import (
    APPROVAL_DECISIONS,
    ApprovalRequest,
    ApprovalResponse,
    DEFAULT_APPROVAL_TTL_SECONDS,
    SENSITIVE_ACTIONS,
)
from .durable import DurableFile, DurableState, SafeModeError

__all__ = [
    "STORE_SCHEMA_VERSION",
    "ApprovalRecord",
    "DurableApprovalStore",
    "authorization_digest",
]

#: Version of the persisted store payload.
STORE_SCHEMA_VERSION = 1

#: Records older than this are pruned. Bounded retention on a node whose storage
#: is the constraint; long enough that an audit can still reconstruct a session.
DEFAULT_RETENTION_SECONDS = 7 * 24 * 3600.0

#: How many records are kept whatever their age.
DEFAULT_MAXIMUM_RECORDS = 512


def authorization_digest(
    *,
    request_id: str,
    plan_id: str,
    transition_id: str,
    action: str,
    destination: str,
    estimated_cost_units: int | None,
    decision: str,
    decided_at_wall: float,
    actor: str,
) -> str:
    """A digest over exactly what was consented to.

    Every field here changes the meaning of the consent. The cost is included
    because "yes, spend four cents" is not "yes, spend anything"; the
    destination because "yes, send it to the loopback model" is not "yes, send
    it anywhere"; the timestamp and actor because a replayed record from
    yesterday is not today's answer.
    """
    material = json.dumps(
        {
            "requestId": request_id,
            "planId": plan_id,
            "transitionId": transition_id,
            "action": action,
            "destination": destination,
            "estimatedCostUnits": estimated_cost_units,
            "decision": decision,
            "decidedAtWall": round(decided_at_wall, 3),
            "actor": actor,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("ascii")).hexdigest()[:32]


@dataclass(frozen=True)
class ApprovalRecord:
    """One request and its fate, as persisted."""

    request: ApprovalRequest
    decision: str = "pending"
    decided_at_wall: float = 0.0
    decided_at_monotonic: float = 0.0
    actor: str = ""
    authorization: str = ""
    #: Why the store reached this decision, when it was not a person.
    detail: str = ""
    #: Audit record ids this decision is linked to.
    audit_events: tuple[str, ...] = ()
    revoked: bool = False

    def __post_init__(self) -> None:
        if self.decision not in APPROVAL_DECISIONS:
            raise ValueError(f"unknown approval decision: {self.decision!r}")

    @property
    def authorization_valid(self) -> bool:
        """Whether the decision matches its own authorization digest.

        A ``pending`` record carries no authorization and is trivially valid;
        it authorises nothing.
        """
        if self.decision == "pending":
            return True
        expected = authorization_digest(
            request_id=self.request.request_id,
            plan_id=self.request.plan_id,
            transition_id=self.request.transition_id,
            action=self.request.action,
            destination=self.request.destination,
            estimated_cost_units=self.request.estimated_cost_units,
            decision=self.decision,
            decided_at_wall=self.decided_at_wall,
            actor=self.actor,
        )
        return bool(self.authorization) and self.authorization == expected

    def grants(self, *, plan_id: str, now_monotonic: float, now_wall: float) -> tuple[bool, str]:
        """Whether this record authorises action now, and why not if it does not."""
        if self.revoked:
            return False, "the approval was revoked"
        if self.decision != "granted":
            return False, f"the request is {self.decision}"
        if not self.authorization_valid:
            return False, (
                "the record's authorization digest does not match its decision; it was "
                "edited outside the store and is not honoured"
            )
        if self.request.plan_id != plan_id:
            return False, (
                f"this was granted against plan {self.request.plan_id}, and the plan now in "
                f"force is {plan_id}; consent under one set of numbers is not consent under another"
            )
        expiry = self.request.expires_at_monotonic
        if expiry > 0 and now_monotonic > expiry:
            return False, "the approval expired"
        return True, "granted, unexpired, and for the plan in force"

    def to_json(self) -> dict[str, Any]:
        return {
            "storeSchemaVersion": STORE_SCHEMA_VERSION,
            "request": self.request.to_json(),
            "decision": self.decision,
            "decidedAtWall": self.decided_at_wall,
            "decidedAtMonotonic": self.decided_at_monotonic,
            "actor": self.actor,
            "authorization": self.authorization,
            "authorizationValid": self.authorization_valid,
            "detail": self.detail,
            "auditEvents": list(self.audit_events),
            "revoked": self.revoked,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "ApprovalRecord":
        if not isinstance(document, Mapping):
            raise ValueError("an approval record must be an object")
        raw = document.get("request")
        if not isinstance(raw, Mapping):
            raise ValueError("an approval record must carry its request")

        alternatives = raw.get("alternatives") or []
        request = ApprovalRequest(
            request_id=str(raw.get("requestId", "")),
            plan_id=str(raw.get("planId", "")),
            transition_id=str(raw.get("transitionId", "")),
            service_id=str(raw.get("serviceId", "")),
            action=str(raw.get("action", "")),
            reason=str(raw.get("reason", "")),
            data_affected=str(raw.get("dataAffected", "none")),
            destination=str(raw.get("destination", "local")),
            provider_id=raw.get("providerId"),
            estimated_cost_units=raw.get("estimatedCostUnits"),
            resource_impact=dict(raw.get("resourceImpact") or {}),
            expires_at_monotonic=float(raw.get("expiresAtMonotonic", 0.0) or 0.0),
            alternatives=tuple(str(item) for item in alternatives),
            safe_default=str(raw.get("safeDefault", "denied")),
        )
        decision = str(document.get("decision", "pending"))
        if decision not in APPROVAL_DECISIONS:
            raise ValueError(f"unknown decision {decision!r}")
        return cls(
            request=request,
            decision=decision,
            decided_at_wall=float(document.get("decidedAtWall", 0.0) or 0.0),
            decided_at_monotonic=float(document.get("decidedAtMonotonic", 0.0) or 0.0),
            actor=str(document.get("actor", "")),
            authorization=str(document.get("authorization", "")),
            detail=str(document.get("detail", "")),
            audit_events=tuple(str(item) for item in (document.get("auditEvents") or [])),
            revoked=bool(document.get("revoked", False)),
        )


@dataclass
class DurableApprovalStore:
    """An :class:`~capability.apply.approval.ApprovalStore` that persists.

    Satisfies the same protocol the applicator already consumes, so nothing
    upstream changes: ``request()`` returns the answer known right now and never
    blocks, and ``approved_services()`` reports what is currently authorised.
    """

    path: Path
    #: Mode 0600. These records name what a user was asked and what they said.
    state: DurableState = field(init=False)
    records: dict[str, ApprovalRecord] = field(default_factory=dict)
    default_ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS
    retention_seconds: float = DEFAULT_RETENTION_SECONDS
    maximum_records: int = DEFAULT_MAXIMUM_RECORDS
    name: str = "durable"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.state = DurableState(
            file=DurableFile(path=self.path, mode=0o600, directory_mode=0o700),
            default_factory=lambda: {"schemaVersion": STORE_SCHEMA_VERSION, "records": []},
        )

    # ------------------------------------------------------------------ #

    def load(self) -> tuple[str, ...]:
        """Restore. A damaged store denies everything rather than guessing."""
        outcome = self.state.load()
        warnings = list(outcome.problems)
        payload = outcome.payload if isinstance(outcome.payload, Mapping) else {}
        entries = payload.get("records")
        restored: dict[str, ApprovalRecord] = {}
        if isinstance(entries, list):
            for raw in entries:
                try:
                    record = ApprovalRecord.from_json(raw)
                except (ValueError, TypeError) as exc:
                    warnings.append(f"discarded an unreadable approval record: {exc}")
                    continue
                if record.decision != "pending" and not record.authorization_valid:
                    # Kept, but demoted. Deleting it would hide a tampering
                    # attempt; honouring it would be the tampering succeeding.
                    warnings.append(
                        f"approval {record.request.request_id} has an invalid authorization "
                        "digest and will not grant anything"
                    )
                restored[record.request.request_id] = record
        self.records = restored
        if outcome.safe_mode:
            warnings.append(
                "the approval store could not be trusted; every request will be denied until "
                "an operator resolves it"
            )
        self.warnings = tuple(warnings)
        return self.warnings

    @property
    def safe_mode(self) -> bool:
        return self.state.safe_mode

    def _persist(self) -> None:
        payload = {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "records": [
                self.records[key].to_json()
                for key in sorted(self.records)
            ],
        }
        self.state.save(payload)

    # ------------------------------------------------------------------ #
    # The ApprovalStore protocol
    # ------------------------------------------------------------------ #

    def request(self, item: ApprovalRequest) -> ApprovalResponse:
        """Record the request and return the answer known right now.

        Idempotent: raising the same request twice does not reset a decision
        already made, which is what stops a reconciliation loop from clearing
        an answer every thirty seconds.
        """
        existing = self.records.get(item.request_id)
        if existing is not None:
            return self._response_for(existing)

        record = ApprovalRecord(request=item, decision="pending")
        self.records[item.request_id] = record
        self._prune()
        try:
            self._persist()
        except OSError:
            # A store that cannot be written still answers correctly in memory,
            # and its answer is "pending", which grants nothing.
            pass
        return self._response_for(record)

    def approved_services(self, plan_id: str, now: float) -> frozenset[str]:
        """Services with a currently valid grant under this plan."""
        if self.safe_mode:
            return frozenset()
        wall = time.time()
        approved: set[str] = set()
        for record in self.records.values():
            granted, _ = record.grants(plan_id=plan_id, now_monotonic=now, now_wall=wall)
            if granted:
                approved.add(record.request.service_id)
        return frozenset(approved)

    def _response_for(self, record: ApprovalRecord) -> ApprovalResponse:
        return ApprovalResponse(
            record.request.request_id,
            record.decision,
            plan_id=record.request.plan_id,
            granted_at_monotonic=record.decided_at_monotonic,
            expires_at_monotonic=record.request.expires_at_monotonic,
            responder=record.actor or "store",
            detail=record.detail,
        )

    # ------------------------------------------------------------------ #
    # Operator surface
    # ------------------------------------------------------------------ #

    def pending(self) -> tuple[ApprovalRecord, ...]:
        return tuple(
            self.records[key] for key in sorted(self.records)
            if self.records[key].decision == "pending" and not self.records[key].revoked
        )

    def get(self, request_id: str) -> ApprovalRecord | None:
        return self.records.get(request_id)

    def decide(
        self, request_id: str, decision: str, *,
        actor: str, now_monotonic: float | None = None, detail: str = "",
        audit_events: Sequence[str] = (),
    ) -> ApprovalRecord:
        """Record a person's answer. The only way anything is ever granted.

        Refuses in safe mode: a store that could not be trusted on read must not
        accept a decision that would then be trusted on write.
        """
        if decision not in ("granted", "denied"):
            raise ValueError("a decision must be 'granted' or 'denied'")
        self.state.require_trusted(f"deciding approval {request_id}")

        record = self.records.get(request_id)
        if record is None:
            raise KeyError(f"no approval request {request_id!r}")
        if record.revoked:
            raise ValueError(f"approval {request_id!r} was revoked and cannot be decided")

        if record.decision in ("granted", "denied"):
            # Idempotent for the same answer; refused for a different one. An
            # approval that can be flipped after the fact is an approval that
            # can be flipped by whatever flipped it.
            if record.decision == decision:
                return record
            raise ValueError(
                f"approval {request_id!r} is already {record.decision} and cannot be changed "
                "to {decision!r}; raise a new request instead"
            )

        monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        wall = time.time()
        updated = replace(
            record,
            decision=decision,
            decided_at_wall=wall,
            decided_at_monotonic=monotonic,
            actor=actor,
            detail=detail,
            audit_events=tuple(audit_events),
            authorization=authorization_digest(
                request_id=record.request.request_id,
                plan_id=record.request.plan_id,
                transition_id=record.request.transition_id,
                action=record.request.action,
                destination=record.request.destination,
                estimated_cost_units=record.request.estimated_cost_units,
                decision=decision,
                decided_at_wall=wall,
                actor=actor,
            ),
        )
        self.records[request_id] = updated
        self._persist()
        return updated

    def revoke(self, request_id: str, *, actor: str, detail: str = "") -> ApprovalRecord:
        """Withdraw a grant. Permitted at any time; the safe direction."""
        self.state.require_trusted(f"revoking approval {request_id}")
        record = self.records.get(request_id)
        if record is None:
            raise KeyError(f"no approval request {request_id!r}")
        updated = replace(
            record, revoked=True,
            detail=detail or f"revoked by {actor}",
        )
        self.records[request_id] = updated
        self._persist()
        return updated

    def expire(self, now_monotonic: float) -> tuple[str, ...]:
        """Mark timed-out grants expired. Returns what lapsed."""
        lapsed: list[str] = []
        for key in sorted(self.records):
            record = self.records[key]
            expiry = record.request.expires_at_monotonic
            if record.decision in ("granted", "pending") and expiry > 0 and now_monotonic > expiry:
                self.records[key] = replace(
                    record, decision="expired",
                    detail="the request expired without being acted on",
                )
                lapsed.append(key)
        if lapsed:
            try:
                self._persist()
            except OSError:
                pass
        return tuple(lapsed)

    def invalidate_for_plan(self, plan_id: str) -> tuple[str, ...]:
        """Expire grants made against a superseded plan."""
        lapsed: list[str] = []
        for key in sorted(self.records):
            record = self.records[key]
            if record.decision == "granted" and record.request.plan_id and record.request.plan_id != plan_id:
                self.records[key] = replace(
                    record, decision="expired",
                    detail=(
                        f"the plan this was granted against ({record.request.plan_id}) has been "
                        f"superseded by {plan_id}"
                    ),
                )
                lapsed.append(key)
        if lapsed:
            try:
                self._persist()
            except OSError:
                pass
        return tuple(lapsed)

    def cancel_for_transition(self, transition_id: str, *, detail: str = "") -> tuple[str, ...]:
        """Withdraw requests whose transition is no longer going to happen."""
        cancelled: list[str] = []
        for key in sorted(self.records):
            record = self.records[key]
            if record.request.transition_id == transition_id and record.decision == "pending":
                self.records[key] = replace(
                    record, decision="expired",
                    detail=detail or "the transition this request was raised for was cancelled",
                )
                cancelled.append(key)
        if cancelled:
            try:
                self._persist()
            except OSError:
                pass
        return tuple(cancelled)

    def _prune(self) -> None:
        """Bounded retention, oldest resolved records first.

        Pending records are never pruned by age: an unanswered question is not
        stale, it is unanswered, and dropping it would silently withdraw a
        request a person may be about to answer.
        """
        if len(self.records) <= self.maximum_records:
            return
        resolved = sorted(
            (key for key, item in self.records.items() if item.decision != "pending"),
            key=lambda key: self.records[key].decided_at_wall,
        )
        excess = len(self.records) - self.maximum_records
        for key in resolved[:excess]:
            del self.records[key]

    # ------------------------------------------------------------------ #

    def to_json(self) -> dict[str, Any]:
        return {
            "store": self.name,
            "schemaVersion": STORE_SCHEMA_VERSION,
            "path": str(self.path),
            "safeMode": self.safe_mode,
            "warnings": list(self.warnings),
            "durability": self.state.describe(),
            "counts": {
                "total": len(self.records),
                "pending": len(self.pending()),
                "granted": sum(1 for item in self.records.values() if item.decision == "granted"),
                "denied": sum(1 for item in self.records.values() if item.decision == "denied"),
                "expired": sum(1 for item in self.records.values() if item.decision == "expired"),
                "revoked": sum(1 for item in self.records.values() if item.revoked),
            },
            "records": [self.records[key].to_json() for key in sorted(self.records)],
        }

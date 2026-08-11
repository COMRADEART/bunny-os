# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Approval Centre bridge over the existing capability approval records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import time
from typing import Any, Mapping

from capability.apply.approval import ApprovalRequest as CapabilityApprovalRequest
from capability.apply.approval_store import ApprovalRecord, DurableApprovalStore

from .coordination import ExecutionProposal
from .model import AgentIdentity, TaskSession, bounded_text, safe_identifier


class ApprovalError(RuntimeError):
    pass


class ApprovalExpired(ApprovalError):
    pass


class ApprovalReplay(ApprovalError):
    pass


class ApprovalScopeMismatch(ApprovalError):
    pass


class SupersededPlan(ApprovalError):
    pass


_AUTO_BOOT_IDENTITY = object()


def _system_boot_identity() -> str | None:
    """Return the Linux boot id used by installed Bunny OS, if available."""
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return None
    return value if value else None


@dataclass(frozen=True)
class ApprovalView:
    request_id: str
    task_id: str
    requested_action: str
    why_needed: str
    requesting_agent: str
    data_affected: str
    destination: str
    provider_destination: str | None
    locality: str
    estimated_cost_units: int | None
    resource_impact: Mapping[str, Any]
    alternatives: tuple[str, ...]
    expiration: str
    plan_id: str
    transition_id: str
    status: str
    safe_default: str = "denied"

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "taskId": self.task_id,
            "requestedAction": self.requested_action,
            "whyNeeded": self.why_needed,
            "requestingAgent": self.requesting_agent,
            "dataAffected": self.data_affected,
            "destination": self.destination,
            "providerDestination": self.provider_destination,
            "locality": self.locality,
            "estimatedCostUnits": self.estimated_cost_units,
            "resourceImpact": dict(self.resource_impact),
            "alternatives": list(self.alternatives),
            "expiration": self.expiration,
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "status": self.status,
            "safeDefault": self.safe_default,
            "actions": ["approve", "deny", "cancel_task"],
        }


@dataclass(frozen=True)
class ApprovalResolution:
    request_id: str
    decision: str
    plan_id: str
    transition_id: str
    destination: str
    provider_destination: str | None
    actor: str = "user"

    def __post_init__(self) -> None:
        safe_identifier(self.request_id, "approval request id")
        safe_identifier(self.plan_id, "approval plan id")
        safe_identifier(self.transition_id, "approval transition id")
        if self.decision not in {"approve", "deny", "cancel_task"}:
            raise ValueError("approval resolution is invalid")
        if self.destination not in {"local", "remote"}:
            raise ValueError("approval destination is invalid")
        if self.provider_destination is not None:
            safe_identifier(self.provider_destination, "approval provider destination")
        bounded_text(self.actor, "approval actor", 128)


@dataclass(frozen=True)
class ApprovalOutcome:
    request_id: str
    decision: str
    cancel_task: bool
    record: ApprovalRecord

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "decision": self.decision,
            "cancelTask": self.cancel_task,
            "record": self.record.to_json(),
        }


class ApprovalCentre:
    """Scope-validating visual/API surface for capability approval records."""

    def __init__(
        self,
        path: Path,
        *,
        boot_identity: str | None | object = _AUTO_BOOT_IDENTITY,
    ) -> None:
        self.store = DurableApprovalStore(path=path)
        warnings = list(self.store.load())
        self._task_by_request: dict[str, str] = {}
        identity = _system_boot_identity() if boot_identity is _AUTO_BOOT_IDENTITY else boot_identity
        if identity is None:
            warnings.append(
                "boot identity is unavailable; cross-boot monotonic approval expiry was not verified"
            )
        else:
            bounded_text(str(identity), "boot identity", 128)
            warnings.extend(self._bind_pending_to_boot(str(identity)))
        self.warnings = tuple(warnings)

    def _bind_pending_to_boot(self, identity: str) -> tuple[str, ...]:
        """Expire restored pending records if their monotonic clock was another boot."""
        marker = self.store.path.with_suffix(self.store.path.suffix + ".boot-id")
        warnings: list[str] = []
        previous: str | None = None
        marker_trusted = True
        try:
            if marker.is_symlink():
                marker_trusted = False
                warnings.append("approval boot marker is a symlink and was not trusted")
            elif marker.is_file():
                previous = marker.read_text(encoding="ascii").strip()
        except OSError as exc:
            marker_trusted = False
            warnings.append(f"approval boot marker could not be read: {type(exc).__name__}")

        if self.store.pending() and (not marker_trusted or previous != identity):
            for record in self.store.pending():
                self.store.cancel_for_transition(
                    record.request.transition_id,
                    detail="the request was safely expired because the system boot identity changed",
                )
            warnings.append("pending approvals from another or unknown boot were expired")

        if marker_trusted:
            temporary = marker.with_suffix(marker.suffix + ".new")
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                if temporary.is_symlink():
                    raise PermissionError("temporary boot marker is a symlink")
                temporary.write_text(identity + "\n", encoding="ascii", newline="\n")
                try:
                    temporary.chmod(0o600)
                except OSError:
                    pass
                os.replace(temporary, marker)
            except OSError as exc:
                warnings.append(f"approval boot marker could not be persisted: {type(exc).__name__}")
        return tuple(warnings)

    @staticmethod
    def request_for(task: TaskSession, proposal: ExecutionProposal, agent: AgentIdentity, *, now: float) -> CapabilityApprovalRequest:
        return CapabilityApprovalRequest(
            request_id=f"approval:{proposal.transition_id}",
            plan_id=proposal.plan_id,
            transition_id=proposal.transition_id,
            service_id=agent.agent_id,
            action=proposal.approval_action,
            reason=proposal.action_summary,
            data_affected=proposal.data_affected,
            destination=proposal.destination,
            provider_id=proposal.provider_id,
            estimated_cost_units=proposal.estimated_cost_units,
            resource_impact=dict(proposal.resource_impact),
            expires_at_monotonic=now + 900.0,
            alternatives=proposal.alternatives,
            safe_default="denied",
        )

    def request(self, task: TaskSession, proposal: ExecutionProposal, agent: AgentIdentity, *, now: float | None = None) -> ApprovalRecord:
        moment = time.monotonic() if now is None else now
        request = self.request_for(task, proposal, agent, now=moment)
        self._task_by_request[request.request_id] = task.task_id
        self.store.request(request)
        record = self.store.get(request.request_id)
        if record is None:
            raise ApprovalError("approval store did not retain the request")
        return record

    def associate(self, request_id: str, task_id: str) -> None:
        """Restore the task link kept outside the capability approval record."""
        safe_identifier(request_id, "approval request id")
        safe_identifier(task_id, "approval task id")
        self._task_by_request[request_id] = task_id

    @staticmethod
    def _expiration(record: ApprovalRecord, now_monotonic: float) -> str:
        remaining = max(0.0, record.request.expires_at_monotonic - now_monotonic)
        expires = datetime.now(timezone.utc) + timedelta(seconds=remaining)
        return expires.isoformat().replace("+00:00", "Z")

    def view(self, record: ApprovalRecord, *, task_id: str | None = None, now: float | None = None) -> ApprovalView:
        moment = time.monotonic() if now is None else now
        request = record.request
        return ApprovalView(
            request_id=request.request_id,
            task_id=task_id or self._task_by_request.get(request.request_id, "unknown-task"),
            requested_action=request.action,
            why_needed=request.reason,
            requesting_agent=request.service_id,
            data_affected=request.data_affected,
            destination=request.destination,
            provider_destination=request.provider_id,
            locality=request.destination,
            estimated_cost_units=request.estimated_cost_units,
            resource_impact=request.resource_impact,
            alternatives=request.alternatives,
            expiration=self._expiration(record, moment),
            plan_id=request.plan_id,
            transition_id=request.transition_id,
            status=record.decision,
            safe_default=request.safe_default,
        )

    def pending(self, *, task_id: str | None = None, now: float | None = None) -> tuple[ApprovalView, ...]:
        moment = time.monotonic() if now is None else now
        self.store.expire(moment)
        views: list[ApprovalView] = []
        for record in self.store.pending():
            related = self._task_by_request.get(record.request.request_id)
            if task_id is not None and related != task_id:
                continue
            views.append(self.view(record, task_id=related, now=moment))
        return tuple(views)

    def resolve(
        self,
        resolution: ApprovalResolution,
        *,
        current_plan_id: str,
        now: float | None = None,
        audit_events: tuple[str, ...] = (),
    ) -> ApprovalOutcome:
        moment = time.monotonic() if now is None else now
        record = self.store.get(resolution.request_id)
        if record is None:
            raise KeyError(f"no approval request {resolution.request_id!r}")
        request = record.request
        if request.expires_at_monotonic > 0 and moment > request.expires_at_monotonic:
            self.store.expire(moment)
            raise ApprovalExpired("the approval request has expired; no action was taken")
        if record.decision == "expired":
            raise ApprovalExpired("the approval request has expired; no action was taken")
        if record.decision != "pending":
            raise ApprovalReplay("the approval request was already resolved; replay was rejected")
        if request.plan_id != current_plan_id or resolution.plan_id != current_plan_id:
            raise SupersededPlan("the approval belongs to a superseded plan")
        mismatches: list[str] = []
        if resolution.transition_id != request.transition_id:
            mismatches.append("transition id")
        if resolution.destination != request.destination:
            mismatches.append("destination")
        if resolution.provider_destination != request.provider_id:
            mismatches.append("provider destination")
        if mismatches:
            raise ApprovalScopeMismatch(
                "approval scope changed (" + ", ".join(mismatches) + "); no action was taken"
            )

        stored_decision = "granted" if resolution.decision == "approve" else "denied"
        updated = self.store.decide(
            resolution.request_id,
            stored_decision,
            actor=resolution.actor,
            now_monotonic=moment,
            detail=(
                "approved through the Bunny Companion Approval Centre"
                if stored_decision == "granted"
                else "denied through the Bunny Companion Approval Centre"
            ),
            audit_events=audit_events,
        )
        return ApprovalOutcome(
            request_id=resolution.request_id,
            decision="approved" if stored_decision == "granted" else "denied",
            cancel_task=resolution.decision == "cancel_task",
            record=updated,
        )

    def invalidate_for_plan(self, current_plan_id: str) -> tuple[str, ...]:
        return self.store.invalidate_for_plan(current_plan_id)

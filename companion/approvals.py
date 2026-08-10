# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Consent: what has to be asked, and every way an answer stops counting.

This is a binding layer over the interface Bunny OS already has.
:class:`capability.apply.approval.ApprovalStore` defines what a request looks
like and states the rule that matters most — *an unanswered request involving
remote execution, money, destruction of user work, or interruption of something
in progress is denied* — and nothing here weakens it. What is added is the part
a companion task needs and a service transition does not: an approval belongs to
**this task**, at **this transition**, under **this plan**, to **this
destination**, and stops counting the moment any of those change.

Six checks, each of which is a real way consent gets misused:

``expired``      time ran out; consent to act now is not consent later
``replayed``     an already-answered request presented a second time
``wrong task``   an answer for one task used to authorise another
``wrong transition`` an answer for one step used to authorise a different step
``superseded``   the plan changed under the approval; the numbers a person saw
                 are not the numbers that would now apply
``destination``  the place the data would go changed after the person agreed

The destination check is the reason :class:`companion.task.ApprovalReference`
carries a fingerprint rather than a name. Comparing a digest of *everything*
about the destination — the provider, the locality, the retention, whether it
trains on input — catches the case where the provider id stayed the same and its
declaration did not.

Approvals do not survive a restart. Expiry is measured on the monotonic clock,
which restarts with the machine, so an approval granted before a reboot cannot
have its expiry evaluated afterwards. Rather than guess, :meth:`CompanionApprovalStore.load`
expires everything from a previous run and records that it did. The audit trail
survives; the *permission* does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Protocol, Sequence

from capability.apply.approval import (
    APPROVAL_DECISIONS,
    DEFAULT_APPROVAL_TTL_SECONDS,
    SENSITIVE_ACTIONS,
    ApprovalRequest,
    ApprovalResponse,
)
from capability.apply.identity import digest

from .errors import (
    ApprovalDenied,
    ApprovalExpired,
    ApprovalInvalidated,
    ApprovalMismatch,
    ApprovalReplayed,
    MalformedOutput,
    StoreError,
)
from .executor import TaskPlan
from .privacy import rank
from .session import CompanionSession
from .task import ApprovalReference, CompanionTask
from .tools import ToolBroker

__all__ = [
    "APPROVAL_TERMINAL_STATES",
    "USER_REFUSAL_STATES",
    "ApprovalGate",
    "ApprovalRequirement",
    "CompanionApprovalStore",
    "ConsentSource",
    "RefusingConsent",
    "ScriptedConsent",
    "destination_fingerprint",
    "operations_needing_approval",
    "requirements_for",
    "terminal_record",
]

#: How a question can finish, in the companion's own record.
#:
#: Deliberately richer than the durable store's vocabulary, which is shared with
#: the capability applicator and stays as it is. The store answers "may this act
#: proceed"; this answers "what happened to the question", and those are
#: different questions with different audiences. Writing one word for all of
#: them was a defect with a user-visible consequence: a question withdrawn
#: because somebody pressed pause was recorded as ``denied``, which says a
#: person refused, and the paused task then projected as ``blocked``.
APPROVAL_TERMINAL_STATES = (
    "approved",
    "denied-by-user",
    "expired",
    "invalidated",
    "superseded",
    "cancelled-with-task",
    "cancelled-with-pause",
)

#: The only states that mean a person actively refused. Everything else is the
#: system withdrawing a question, and no surface may present it as a refusal.
USER_REFUSAL_STATES = frozenset({"denied-by-user"})


def terminal_record(
    *,
    request_id: str,
    task_id: str,
    plan_id: str,
    transition_id: str,
    state: str,
    previous_state: str,
    reason: str,
    actor: str,
    at: str,
    binding_digest: str = "",
    lifecycle_epoch: int = 0,
) -> dict[str, Any]:
    """One question's ending, with everything needed to audit it later.

    Every field is here because its absence made a real record ambiguous.
    ``previous_state`` distinguishes a question that was withdrawn while pending
    from one withdrawn after it had been granted — the second is consent being
    taken back and the first is not. ``actor`` distinguishes the person from the
    system. ``lifecycle_epoch`` is what lets a projection ignore the outcome of
    a question asked before the task was paused and resumed.
    """
    if state not in APPROVAL_TERMINAL_STATES:
        raise MalformedOutput(
            f"{state!r} is not an approval terminal state; expected one of "
            f"{list(APPROVAL_TERMINAL_STATES)}"
        )
    return {
        "requestId": request_id,
        "taskId": task_id,
        "planId": plan_id,
        "transitionId": transition_id,
        "decision": state,
        "previousState": previous_state,
        "reason": reason,
        "actor": actor,
        "at": at,
        "bindingDigest": binding_digest,
        "lifecycleEpoch": lifecycle_epoch,
        # Said explicitly so that no reader has to infer it from the word.
        "userRefused": state in USER_REFUSAL_STATES,
    }


def destination_fingerprint(
    *,
    destination: str,
    provider_declaration: Mapping[str, Any] | None = None,
) -> str:
    """Everything about where data would go, in one comparable value."""
    return digest({
        "destination": destination,
        "provider": dict(provider_declaration) if provider_declaration else None,
    })


@dataclass(frozen=True)
class ApprovalRequirement:
    """One question that must be put to a person before an act."""

    action: str
    reason: str
    destination: str = "local"
    provider_id: str | None = None
    estimated_cost_units: int | None = None
    data_affected: str = "none"
    alternatives: tuple[str, ...] = ()
    #: The operation this is about, when it is about one. Empty for
    #: task-level approvals such as dispatching the whole task remotely.
    operation_name: str = ""
    destination_declaration: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.action not in SENSITIVE_ACTIONS:
            raise ApprovalMismatch(
                f"{self.action!r} is not a sensitive action; only sensitive actions are asked about"
            )
        if not self.alternatives:
            raise ApprovalMismatch(
                f"{self.action!r} must state what the user gets if they decline"
            )

    @property
    def fingerprint(self) -> str:
        return destination_fingerprint(
            destination=self.destination,
            provider_declaration=self.destination_declaration,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "destination": self.destination,
            "providerId": self.provider_id,
            "estimatedCostUnits": self.estimated_cost_units,
            "dataAffected": self.data_affected,
            "alternatives": list(self.alternatives),
            "operationName": self.operation_name,
            "destinationFingerprint": self.fingerprint,
        }


def requirements_for(
    task: CompanionTask,
    session: CompanionSession,
    plan: TaskPlan,
    *,
    executor_is_local: bool,
    executor_provider_id: str = "",
    executor_cost_class: str = "free",
    broker: ToolBroker | None = None,
    provider_declaration: Mapping[str, Any] | None = None,
) -> tuple[ApprovalRequirement, ...]:
    """Everything about this plan that needs a person to say yes.

    Derived from the *declarations*, not from the executor's own opinion. An
    executor that set ``requires_approval=False`` on an operation whose tool
    declares itself destructive still produces a requirement here — §12 lists
    what must be asked about, and an executor is not a party to that decision.
    """
    requirements: list[ApprovalRequirement] = []

    if not executor_is_local:
        requirements.append(ApprovalRequirement(
            action="remote_dispatch",
            reason=(
                f"Task {task.task_id} would be performed by {executor_provider_id or 'a remote provider'} "
                f"rather than on this device."
            ),
            destination=executor_provider_id or "remote",
            provider_id=executor_provider_id or None,
            estimated_cost_units=plan.estimated_cost_units,
            data_affected=task.classification,
            alternatives=("Wait for a local executor.", "Cancel the task."),
            destination_declaration=provider_declaration,
        ))
        if rank(task.classification) >= rank("personal"):
            requirements.append(ApprovalRequirement(
                action="send_sensitive_data",
                reason=(
                    f"The task is classified {task.classification} and its contents would leave this device."
                ),
                destination=executor_provider_id or "remote",
                provider_id=executor_provider_id or None,
                data_affected=task.classification,
                alternatives=("Run the task locally.", "Cancel the task."),
                destination_declaration=provider_declaration,
            ))

    if executor_cost_class == "paid" or plan.estimated_cost_units > 0:
        threshold = session.cost_policy.approval_threshold_units
        if plan.estimated_cost_units >= threshold:
            requirements.append(ApprovalRequirement(
                action="paid_provider",
                reason=(
                    f"This plan is estimated to spend {plan.estimated_cost_units} units."
                ),
                destination=executor_provider_id or "remote",
                provider_id=executor_provider_id or None,
                estimated_cost_units=plan.estimated_cost_units,
                data_affected=task.classification,
                alternatives=("Use a free local executor.", "Cancel the task."),
                destination_declaration=provider_declaration,
            ))

    for operation in plan.operations:
        declaration = broker.declaration(operation.tool) if broker is not None else None
        external = operation.destination != "local" or (declaration is not None and declaration.external_destination)
        if declaration is not None and declaration.destructive:
            requirements.append(ApprovalRequirement(
                action="discard_unsaved_state",
                reason=f"Operation {operation.name!r} uses {operation.tool!r}, which is declared destructive.",
                destination=operation.destination,
                data_affected=task.classification,
                alternatives=("Skip this step.", "Cancel the task."),
                operation_name=operation.name,
            ))
        if declaration is not None and declaration.interrupts_user:
            requirements.append(ApprovalRequirement(
                action="interrupt_user_work",
                reason=f"Operation {operation.name!r} would interrupt what you are doing.",
                destination=operation.destination,
                data_affected=task.classification,
                alternatives=("Do this later.", "Cancel the task."),
                operation_name=operation.name,
            ))
        if external:
            requirements.append(ApprovalRequirement(
                action="remote_dispatch",
                reason=(
                    f"Operation {operation.name!r} would reach {operation.destination!r}, "
                    "which is outside this device."
                ),
                destination=operation.destination,
                provider_id=operation.destination if operation.destination != "local" else None,
                estimated_cost_units=operation.estimated_cost_units,
                data_affected=task.classification,
                alternatives=("Plan this step locally.", "Cancel the task."),
                operation_name=operation.name,
                destination_declaration=provider_declaration,
            ))
    return tuple(requirements)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


@dataclass
class CompanionApprovalStore:
    """A durable :class:`capability.apply.approval.ApprovalStore`.

    It satisfies the existing protocol — :meth:`request` and
    :meth:`approved_services` — so anything in Bunny OS that already knows how
    to talk to an approval store can talk to this one. The additions are what a
    persisted store needs: answers can be recorded, and a run that inherits a
    file written by a previous run expires everything in it.

    Persisted with the same atomic-replace discipline as
    :mod:`companion.store`, because a half-written approval file is a file that
    might read as a grant.
    """

    path: Path | None = None
    default_ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS
    requests: dict[str, ApprovalRequest] = field(default_factory=dict)
    responses: dict[str, ApprovalResponse] = field(default_factory=dict)
    #: What loading found that had to be invalidated. Surfaced by the runtime as
    #: recovery warnings rather than swallowed.
    warnings: tuple[str, ...] = ()
    #: Identifies this process run. Anything in the file bearing a different one
    #: was granted against a monotonic clock that no longer exists.
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = "run-" + os.urandom(8).hex()

    # -- the ApprovalStore protocol ----------------------------------------

    def request(self, item: ApprovalRequest) -> ApprovalResponse:
        """Raise a request and return the answer known right now. Never blocks.

        The question is made durable here, not when it is answered. A request
        that only reached the disk once somebody replied would be invisible for
        exactly the window in which it is waiting to be replied to — which is
        the whole of its useful life, and the only window in which
        ``bunny-os companion approvals`` has anything to show.
        """
        self.requests[item.request_id] = item
        self.save()
        existing = self.responses.get(item.request_id)
        if existing is not None:
            return existing
        return ApprovalResponse(item.request_id, "pending", plan_id=item.plan_id)

    def approved_services(self, plan_id: str, now: float) -> frozenset[str]:
        approved: set[str] = set()
        for request_id, response in self.responses.items():
            item = self.requests.get(request_id)
            if item is not None and response.valid(now, plan_id=plan_id):
                approved.add(item.service_id)
        return frozenset(approved)

    # -- answering ---------------------------------------------------------

    def grant(self, request_id: str, *, plan_id: str, now: float, responder: str = "user", detail: str = "") -> ApprovalResponse:
        item = self.requests.get(request_id)
        if item is None:
            raise ApprovalMismatch(f"no approval request with id {request_id!r} was raised")
        response = ApprovalResponse(
            request_id, "granted", plan_id=plan_id,
            granted_at_monotonic=now,
            expires_at_monotonic=now + self.default_ttl_seconds,
            responder=responder, detail=detail,
        )
        self.responses[request_id] = response
        self.save()
        return response

    def deny(self, request_id: str, *, plan_id: str = "", responder: str = "user", detail: str = "") -> ApprovalResponse:
        response = ApprovalResponse(request_id, "denied", plan_id=plan_id, responder=responder, detail=detail)
        self.responses[request_id] = response
        self.save()
        return response

    def expire(self, now: float) -> tuple[str, ...]:
        """Mark timed-out requests and grants expired. Returns what lapsed."""
        lapsed: list[str] = []
        for request_id in sorted(self.requests):
            item = self.requests[request_id]
            response = self.responses.get(request_id)
            if response is not None and response.decision not in ("granted", "pending"):
                continue
            timed_out = (
                item.expired(now)
                if response is None or response.decision == "pending"
                else (response.expires_at_monotonic > 0 and now > response.expires_at_monotonic)
            )
            if timed_out:
                self.responses[request_id] = ApprovalResponse(
                    request_id, "expired", plan_id=item.plan_id, responder="system",
                    detail="the request timed out; the safe default applied and nothing was done",
                )
                lapsed.append(request_id)
        if lapsed:
            self.save()
        return tuple(lapsed)

    def invalidate_for_plan(self, plan_id: str) -> tuple[str, ...]:
        """Expire every grant made against a plan that has been superseded."""
        lapsed: list[str] = []
        for request_id in sorted(self.responses):
            response = self.responses[request_id]
            if response.decision == "granted" and response.plan_id and response.plan_id != plan_id:
                self.responses[request_id] = replace(
                    response, decision="expired",
                    detail=f"the plan this was granted against ({response.plan_id}) has been superseded",
                )
                lapsed.append(request_id)
        if lapsed:
            self.save()
        return tuple(lapsed)

    def pending(self) -> tuple[ApprovalRequest, ...]:
        return tuple(
            self.requests[request_id]
            for request_id in sorted(self.requests)
            if self.responses.get(request_id, ApprovalResponse(request_id, "pending")).decision == "pending"
        )

    def decision_for(self, request_id: str) -> ApprovalResponse | None:
        return self.responses.get(request_id)

    # -- persistence -------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "kind": "bunny-companion-approvals",
            "runId": self.run_id,
            "requests": [self.requests[key].to_json() for key in sorted(self.requests)],
            "responses": [self.responses[key].to_json() for key in sorted(self.responses)],
        }

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=str(self.path.parent),
            prefix=self.path.name + ".", suffix=".tmp", delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise StoreError(f"{self.path} could not be written: {exc}") from exc

    @classmethod
    def load(cls, path: Path, *, default_ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS) -> "CompanionApprovalStore":
        """Read a stored approval file, invalidating everything from before.

        A grant recorded by a previous run carries an expiry on a monotonic
        clock that no longer exists. It is not extended, not re-evaluated and
        not honoured; it is expired, and the fact is returned as a warning so
        the runtime can record it in the event stream. The request survives so
        a user can see what was asked and answer it again.
        """
        store = cls(path=path, default_ttl_seconds=default_ttl_seconds)
        if not path.is_file():
            return store
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not a readable approval record: {exc}") from exc
        if not isinstance(document, Mapping) or document.get("kind") != "bunny-companion-approvals":
            raise StoreError(f"{path} is not a companion approval record")

        for item in document.get("requests", ()):
            request = _request_from_json(item)
            store.requests[request.request_id] = request
        invalidated: list[str] = []
        for item in document.get("responses", ()):
            response = _response_from_json(item)
            if response.decision in ("granted", "pending"):
                store.responses[response.request_id] = replace(
                    response, decision="expired", responder="system",
                    detail=(
                        "this was recorded by an earlier run; its expiry was measured on a monotonic "
                        "clock that did not survive the restart, so it was expired rather than assumed"
                    ),
                )
                invalidated.append(response.request_id)
            else:
                store.responses[response.request_id] = response
        # A request raised before the restart and never answered is equally
        # unusable: nothing recorded when it would have timed out either.
        for request_id in sorted(store.requests):
            if request_id not in store.responses:
                store.responses[request_id] = ApprovalResponse(
                    request_id, "expired", plan_id=store.requests[request_id].plan_id, responder="system",
                    detail="this request was outstanding when the runtime stopped and did not survive it",
                )
                invalidated.append(request_id)
        if invalidated:
            store.warnings = (
                f"{len(invalidated)} approval(s) from a previous run were expired on load; "
                "consent does not survive a restart",
            )
        return store


def _request_from_json(document: Mapping[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=str(document.get("requestId", "")),
        plan_id=str(document.get("planId", "")),
        transition_id=str(document.get("transitionId", "")),
        service_id=str(document.get("serviceId", "")),
        action=str(document.get("action", "")),
        reason=str(document.get("reason", "")),
        data_affected=str(document.get("dataAffected", "none")),
        destination=str(document.get("destination", "local")),
        provider_id=document.get("providerId"),
        estimated_cost_units=document.get("estimatedCostUnits"),
        resource_impact=dict(document.get("resourceImpact") or {}),
        expires_at_monotonic=float(document.get("expiresAtMonotonic", 0.0) or 0.0),
        alternatives=tuple(str(item) for item in document.get("alternatives", ())),
        safe_default=str(document.get("safeDefault", "denied")),
    )


def _response_from_json(document: Mapping[str, Any]) -> ApprovalResponse:
    decision = str(document.get("decision", "pending"))
    if decision not in APPROVAL_DECISIONS:
        raise StoreError(f"unknown stored approval decision: {decision!r}")
    return ApprovalResponse(
        request_id=str(document.get("requestId", "")),
        decision=decision,
        plan_id=str(document.get("planId", "")),
        granted_at_monotonic=float(document.get("grantedAtMonotonic", 0.0) or 0.0),
        expires_at_monotonic=float(document.get("expiresAtMonotonic", 0.0) or 0.0),
        responder=str(document.get("responder", "user")),
        detail=str(document.get("detail", "")),
    )


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


class ConsentSource(Protocol):
    """Whatever stands between a raised question and a person's answer.

    Deliberately an interface with a refusing default. This phase has no user
    interface, so there is nothing here that can actually ask anybody; what
    there is, is the shape of the asking, and a default that answers *no* to
    everything. A runtime with no consent source connected behaves exactly like
    Bunny OS with no Approval Centre: it records the question and does nothing.
    """

    def answer(self, request: ApprovalRequest, *, now: float) -> str | None:
        """``"granted"``, ``"denied"``, or ``None`` for "nobody answered yet"."""


@dataclass(frozen=True)
class RefusingConsent:
    """The default. Records every question and grants nothing.

    Not a placeholder. A machine with no way to ask a person must not act as
    though they said yes, and this is the implementation of that sentence.
    """

    def answer(self, request: ApprovalRequest, *, now: float) -> str | None:
        return None


@dataclass(frozen=True)
class ScriptedConsent:
    """A stand-in for a person, for the vertical slice and the tests.

    Grants exactly the actions it was configured with and denies the rest. It
    exists so the demonstration can show consent being *given* — an approval
    flow only ever exercised in its refusing direction is one whose granting
    direction has never run. It must never be the default and is never
    constructed by :class:`companion.runtime.CompanionRuntime` itself.
    """

    granted_actions: tuple[str, ...] = ()
    denied_actions: tuple[str, ...] = ()
    #: Actions to leave unanswered, to exercise the no-response path.
    silent_actions: tuple[str, ...] = ()

    def answer(self, request: ApprovalRequest, *, now: float) -> str | None:
        if request.action in self.silent_actions:
            return None
        if request.action in self.denied_actions:
            return "denied"
        if request.action in self.granted_actions:
            return "granted"
        return None


@dataclass
class ApprovalGate:
    """Binds approvals to one task, one transition, one plan and one destination."""

    store: CompanionApprovalStore
    ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS
    consent: ConsentSource = field(default_factory=RefusingConsent)
    #: (task, transition, plan fingerprint) triples already spent in this run.
    #: An approval authorises one act; presenting the same one for a second act
    #: is the replay this set exists to catch. It is per-run because a run is the
    #: lifetime of the monotonic clock the expiry is measured on.
    consumed: set[tuple[str, str, str]] = field(default_factory=set)
    #: Request id to the terminal state it was withdrawn into, for questions the
    #: system took back. Kept beside the durable store rather than in it because
    #: the store's vocabulary is shared with the capability applicator; see
    #: :meth:`invalidate_for_task`. In memory, like ``consumed``, and for the
    #: same reason: it describes this run, and after a restart a task is
    #: recovered rather than resumed mid-question.
    withdrawn: dict[str, str] = field(default_factory=dict)

    def transition_id(self, plan: TaskPlan, index: int, requirement: ApprovalRequirement) -> str:
        """Identify one approvable step by the *content* of the plan.

        Derived from the plan fingerprint rather than the revision number, so
        that a replan producing an identical plan asks the same question and an
        answer already given still applies — and a replan producing a different
        plan asks a new one, which is exactly the supersession rule §12 requires.
        """
        return f"{plan.fingerprint}:{index}:{requirement.action}"

    def build(
        self,
        task: CompanionTask,
        requirement: ApprovalRequirement,
        plan: TaskPlan,
        *,
        transition_id: str,
        now: float,
    ) -> tuple[ApprovalRequest, ApprovalReference]:
        """Construct the question's identity, and write nothing anywhere.

        Separated from :meth:`prepare` so that a consent waiter can be
        registered *before* the question becomes durable. The order matters and
        the wrong one was a defect: a question reaches the durable store — and
        therefore the Approval Centre — before the worker registers anything to
        receive an answer, so an answer given in that window arrived to nobody.

        Building first makes the identity available to register against without
        any of it being visible yet: nothing here touches the store, the event
        stream or the task document, so a failure between this and
        :meth:`prepare` leaves no question anybody could see or answer.
        """
        request_id = f"approval:{task.task_id}:{transition_id}"
        request = ApprovalRequest(
            request_id=request_id,
            plan_id=plan.plan_id,
            transition_id=transition_id,
            service_id=f"companion.task.{task.task_id}",
            action=requirement.action,
            reason=requirement.reason,
            data_affected=requirement.data_affected,
            destination="remote" if requirement.destination != "local" else "local",
            provider_id=requirement.provider_id,
            estimated_cost_units=requirement.estimated_cost_units,
            resource_impact={"planRevision": plan.revision, "planFingerprint": plan.fingerprint},
            expires_at_monotonic=now + self.ttl_seconds,
            alternatives=requirement.alternatives,
            safe_default="denied",
        )
        reference = ApprovalReference(
            request_id=request_id,
            action=requirement.action,
            decision="pending",
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            transition_id=transition_id,
            destination_fingerprint=requirement.fingerprint,
        )
        return request, reference

    def persist(self, request: ApprovalRequest) -> ApprovalResponse:
        """Make a built question durable. This is what makes it displayable."""
        return self.store.request(request)

    def prepare(
        self,
        task: CompanionTask,
        requirement: ApprovalRequirement,
        plan: TaskPlan,
        *,
        transition_id: str,
        now: float,
    ) -> tuple[ApprovalRequest, ApprovalReference]:
        """Record the question durably, without yet asking anybody.

        Split out from :meth:`raise_request` so the runtime can write the
        ``approval_requested`` event **before** a consent source is consulted.
        With an Approval Centre attached, consulting the consent source blocks
        for as long as a person takes to answer — and while it blocked, the
        event that says a question was asked had not been written. The question
        was durable in this store, but the *stream* — the thing §7 has a
        restarted client replay to rebuild what it should be showing — did not
        mention it. A client that reconnected during exactly the window in which
        the user is being asked something would show a task quietly working.

        The two halves are used together everywhere. :meth:`raise_request`
        remains as their composition for callers with a non-blocking consent
        source, which is every test and the headless demonstration.

        Now itself the composition of :meth:`build` and :meth:`persist`, so that
        there is one construction of a question and not two. A caller that needs
        to register a consent waiter between the two uses them directly.
        """
        request, reference = self.build(
            task, requirement, plan, transition_id=transition_id, now=now
        )
        response = self.persist(request)
        return request, replace(reference, decision=response.decision)

    def seek_consent(
        self,
        request: ApprovalRequest,
        plan: TaskPlan,
        *,
        transition_id: str,
        now: float,
    ) -> ApprovalResponse:
        """Ask whatever stands in for a person, and record what they said.

        The answer is written to the durable store *before* it is used, so a
        grant that authorised an act is in the record whether or not the act
        then succeeded. May block: an interactive consent source waits for a
        human, and that is the whole reason this is a separate call.
        """
        existing = self.store.decision_for(request.request_id)
        if existing is not None and existing.decision != "pending":
            return existing
        said = self.consent.answer(request, now=now)
        if said == "granted":
            return self.store.grant(
                request.request_id, plan_id=plan.plan_id, now=now,
                detail=f"granted for plan {plan.fingerprint} step {transition_id}",
            )
        if said == "denied":
            return self.store.deny(
                request.request_id, plan_id=plan.plan_id,
                detail=f"declined for plan {plan.fingerprint} step {transition_id}",
            )
        return self.store.decision_for(request.request_id) or ApprovalResponse(
            request.request_id, "pending", plan_id=plan.plan_id
        )

    def raise_request(
        self,
        task: CompanionTask,
        requirement: ApprovalRequirement,
        plan: TaskPlan,
        *,
        transition_id: str,
        now: float,
    ) -> tuple[ApprovalRequest, ApprovalResponse, ApprovalReference]:
        """Put one question and take the answer in one step.

        The composition of :meth:`prepare` and :meth:`seek_consent`, for callers
        whose consent source does not block.
        """
        request, reference = self.prepare(
            task, requirement, plan, transition_id=transition_id, now=now
        )
        response = self.seek_consent(request, plan, transition_id=transition_id, now=now)
        return request, response, replace(reference, decision=response.decision)

    def resolve(
        self,
        task: CompanionTask,
        request_id: str,
        *,
        plan: TaskPlan,
        requirement: ApprovalRequirement,
        transition_id: str,
        now: float,
    ) -> ApprovalReference:
        """Check an answer against the act it is being used to authorise.

        Every refusal below is a separate exception type, because the caller
        does different things with each: an expired approval can be asked for
        again, a superseded one means replan first, and a replayed one means
        something is wrong with the caller.
        """
        reference = task.approval(request_id)
        if reference is None:
            raise ApprovalMismatch(
                f"approval {request_id!r} does not belong to task {task.task_id}"
            )
        if reference.transition_id != transition_id:
            raise ApprovalMismatch(
                f"approval {request_id!r} was granted for transition {reference.transition_id!r} "
                f"and is being used for {transition_id!r}"
            )
        spent = (task.task_id, transition_id, plan.fingerprint)
        if spent in self.consumed:
            raise ApprovalReplayed(
                f"approval {request_id!r} has already authorised this step of this plan; "
                "an approval authorises one act and cannot be spent twice"
            )
        if reference.destination_fingerprint != requirement.fingerprint:
            raise ApprovalMismatch(
                f"approval {request_id!r} was granted against a different destination; "
                "the place this would send data has changed since the question was answered"
            )
        if reference.plan_id != plan.plan_id or reference.plan_revision != plan.revision:
            raise ApprovalMismatch(
                f"approval {request_id!r} was granted against plan {reference.plan_id}"
                f"@{reference.plan_revision} and the current plan is {plan.plan_id}@{plan.revision}; "
                "a superseded plan invalidates the consent given for it"
            )

        request = self.store.requests.get(request_id)
        if request is None:
            raise ApprovalMismatch(f"no approval request with id {request_id!r} was raised")
        response = self.store.decision_for(request_id)

        if response is None or response.decision == "pending":
            # Nobody answered. §12: no response defaults to no action. This is
            # the branch that must never be softened.
            if request.expired(now):
                self.store.expire(now)
                raise ApprovalExpired(
                    f"nobody answered {request_id!r} before it expired; nothing was done"
                )
            raise ApprovalDenied(
                f"{request_id!r} has not been answered; the safe default is denial and nothing was done"
            )
        if response.decision == "expired":
            state = self.withdrawn.get(request_id)
            if state is not None:
                # Withdrawn by a stop, not lapsed by a clock. Reporting this as
                # an expiry was the visible half of the pause defect: the worker
                # arrived after the pause had already withdrawn the question and
                # overwrote "withdrawn" with an ending that blocks.
                raise ApprovalInvalidated(
                    f"approval {request_id!r} was withdrawn before it was answered"
                    + (f": {response.detail}" if response.detail else ""),
                    terminal_state=state,
                )
            raise ApprovalExpired(f"approval {request_id!r} has expired; nothing was done")
        if response.decision == "denied":
            raise ApprovalDenied(
                f"approval {request_id!r} was denied"
                + (f": {response.detail}" if response.detail else "")
            )
        if not response.valid(now, plan_id=plan.plan_id):
            raise ApprovalExpired(
                f"approval {request_id!r} is no longer valid for plan {plan.plan_id}"
            )
        self.consumed.add(spent)
        return replace(reference, decision="granted")

    def invalidate_for_task(
        self,
        task: CompanionTask,
        *,
        detail: str,
        terminal_state: str = "invalidated",
    ) -> tuple[str, ...]:
        """Withdraw every outstanding approval belonging to one task.

        Used by cancellation, by pausing, and by a replan that supersedes the
        plan a question was asked about. A pending question about a task nobody
        is running any more must not stay on a user's screen, and a granted one
        must not survive into whatever runs next.

        **The task document is not the only source, and relying on it alone was
        a real hole.** A question becomes durable in
        :meth:`CompanionApprovalStore.request` the moment it is raised; the
        reference reaches the *task document* a few lines later, when the runner
        next saves. Cancel or pause inside that window — which is precisely the
        window in which the user is looking at the question and most likely to
        press stop — and this method iterated an empty list and withdrew
        nothing. The question stayed pending, and the surface went on showing an
        Approve button for a task that had been stopped.

        So the store is asked too. Requests name their task in ``service_id``,
        which :meth:`raise_request` sets to ``companion.task.<id>``, and that is
        a fact recorded at the same instant as the request itself rather than
        one that catches up later.
        """
        owner = f"companion.task.{task.task_id}"
        candidates: dict[str, str] = {
            reference.request_id: reference.plan_id for reference in task.approvals
        }
        for request_id, request in self.store.requests.items():
            if request.service_id == owner:
                candidates.setdefault(request_id, request.plan_id)

        withdrawn: list[str] = []
        for request_id in sorted(candidates):
            if request_id not in self.store.requests:
                continue
            response = self.store.decision_for(request_id)
            if response is not None and response.decision not in ("granted", "pending"):
                continue
            self.store.responses[request_id] = ApprovalResponse(
                request_id, "expired",
                plan_id=candidates[request_id], responder="system", detail=detail,
            )
            # The durable store's vocabulary is shared with the capability
            # applicator and has one word — "expired" — for every way a question
            # can end without an answer. That is right for the store, whose
            # question is only "may this act proceed". It is not enough for the
            # record: a question withdrawn because the user paused and one that
            # simply timed out mean different things to the person who was
            # looking at it. The distinction is kept here so that a worker
            # arriving afterwards reports what actually happened.
            self.withdrawn[request_id] = terminal_state
            withdrawn.append(request_id)
        if withdrawn:
            self.store.save()
        return tuple(withdrawn)


def operations_needing_approval(
    plan: TaskPlan,
    requirements: Sequence[ApprovalRequirement],
) -> frozenset[str]:
    """Names of operations that cannot run until somebody says yes."""
    named = {item.operation_name for item in requirements if item.operation_name}
    if any(not item.operation_name for item in requirements):
        # A task-level requirement gates everything in the plan.
        return frozenset(item.name for item in plan.operations)
    return frozenset(named)

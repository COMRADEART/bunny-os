# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The remote-execution state machine, with nowhere to send anything.

Bunny OS integrates with no commercial AI provider, and this module does not
change that. What it provides is the state model a dispatch would move through,
implemented and tested, so that when a provider integration is written the hard
parts — cancellation, idempotency, the difference between "failed" and "lost",
provenance of a result — already exist and are already correct.

The states, and why each one is separate:

``not_permitted``       policy forbids it. The terminal state for most machines.
``awaiting_approval``   a person has been asked and has not answered.
``awaiting_provider``   approved, but no authenticated provider is available.
``queued``              accepted locally; nothing has left the machine.
``dispatching``         the request is going out. **Data may leave here.**
``active``              the provider has it and is working.
``completing``          a result is arriving.
``completed``           done, with provenance.
``failed``              the provider said no, or the transport broke.
``cancelled``           we withdrew it. May still be running remotely.
``lost``                we do not know. Distinguished from ``failed`` because
                        the responses differ: a failed task may be retried, a
                        lost one must first be reconciled, or the same work runs
                        twice on somebody's bill.
``reconciliation_required``  a lost task whose fate must be established before
                        anything else happens to it.

**The boundary between ``queued`` and ``dispatching`` is the privacy boundary.**
Everything up to and including ``queued`` is local bookkeeping and can be
undone silently. ``dispatching`` is the first state in which a user's data has
left their machine, and it is therefore the only transition that requires every
precondition to hold simultaneously: policy, approval, provider authentication,
privacy compatibility and an idempotency token.

**No credential ever appears here.** Not in a field, not in a log line, not in a
test fixture. :class:`RemoteTask` has no place to put one, which is the only
reliable way to guarantee one is never written to a log.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from typing import Any, Mapping, Protocol, Sequence

__all__ = [
    "REMOTE_STATES",
    "RemoteDispatchGuard",
    "RemoteTask",
    "RemoteTaskLedger",
    "TERMINAL_REMOTE_STATES",
    "TestProvider",
    "idempotency_token",
]

REMOTE_STATES = (
    "not_permitted",
    "awaiting_approval",
    "awaiting_provider",
    "queued",
    "dispatching",
    "active",
    "completing",
    "completed",
    "failed",
    "cancelled",
    "lost",
    "reconciliation_required",
)

TERMINAL_REMOTE_STATES = frozenset({"not_permitted", "completed", "failed", "cancelled"})

#: The state in which data first leaves. Named so that the check protecting it
#: cannot be moved without the name moving too.
EGRESS_STATE = "dispatching"

#: Legal moves. A transition not listed here is refused, which turns a whole
#: class of bug — a task that goes from ``completed`` back to ``active``, a
#: cancellation that resurrects — into an error at the moment it is attempted.
_ALLOWED: Mapping[str, frozenset[str]] = {
    "not_permitted": frozenset(),
    "awaiting_approval": frozenset({"awaiting_provider", "queued", "not_permitted", "cancelled"}),
    "awaiting_provider": frozenset({"queued", "not_permitted", "cancelled", "failed"}),
    "queued": frozenset({"dispatching", "cancelled", "not_permitted", "failed"}),
    "dispatching": frozenset({"active", "failed", "lost", "cancelled"}),
    "active": frozenset({"completing", "failed", "lost", "cancelled"}),
    "completing": frozenset({"completed", "failed", "lost"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset({"reconciliation_required"}),
    "lost": frozenset({"reconciliation_required"}),
    "reconciliation_required": frozenset({"completed", "failed", "cancelled"}),
}


class RemoteStateError(RuntimeError):
    """An illegal move in the remote task state machine."""


def idempotency_token(plan_id: str, transition_id: str, task_id: str) -> str:
    """A token that names *this* unit of work, stably.

    Derived, not random. If the applicator crashes between dispatching a task
    and recording that it did, the recovery path recomputes the same token and
    the provider can recognise the retry as the same request. A random token
    would make that recovery indistinguishable from a second request, and the
    user would be billed for both.
    """
    material = f"{plan_id}|{transition_id}|{task_id}".encode("utf-8")
    return "idem-" + hashlib.sha256(material).hexdigest()[:24]


@dataclass(frozen=True)
class ProviderIdentity:
    """An authenticated provider, as far as this layer needs to know.

    Deliberately not a credential holder. Authentication happens elsewhere and
    this records only that it *succeeded*, plus the declarations the routing
    layer already requires. A provider that cannot present this has not been
    authenticated, and an unauthenticated provider is never dispatched to.
    """

    provider_id: str
    authenticated: bool
    #: Capabilities the provider states it can serve.
    capabilities: tuple[str, ...] = ()
    #: "none" | "ephemeral" | "logged" | "unspecified"
    retention: str = "unspecified"
    trains_on_input: bool | None = None
    #: Highest privacy class this provider may receive, from policy.
    maximum_privacy_class: str = "public"

    @property
    def usable(self) -> bool:
        return (
            self.authenticated
            and self.retention in ("none", "ephemeral", "logged")
            and self.trains_on_input is not None
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "authenticated": self.authenticated,
            "capabilities": list(self.capabilities),
            "retention": self.retention,
            "trainsOnInput": self.trains_on_input,
            "maximumPrivacyClass": self.maximum_privacy_class,
            "usable": self.usable,
        }


@dataclass(frozen=True)
class RemoteTask:
    """One unit of work that might run somewhere other than this machine."""

    task_id: str
    plan_id: str
    transition_id: str
    service_id: str
    capability: str
    #: From ``capability.router.PRIVACY_CLASSES``.
    data_classification: str = "internal"
    state: str = "not_permitted"
    provider_id: str | None = None
    idempotency_token: str = ""
    attempt: int = 0
    maximum_attempts: int = 2
    created_at_monotonic: float = 0.0
    updated_at_monotonic: float = 0.0
    #: Where the result came from, recorded when one arrives. A result with no
    #: provenance is a result nobody can audit.
    result_provenance: Mapping[str, Any] | None = None
    detail: str = ""
    #: Every state this task has been in, for the audit trail.
    history: tuple[tuple[float, str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.state not in REMOTE_STATES:
            raise ValueError(f"unknown remote state: {self.state!r}")

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_REMOTE_STATES

    @property
    def data_has_left(self) -> bool:
        """Whether anything of the user's has actually gone anywhere.

        Answered from the history rather than from the current state, because a
        task that reached ``dispatching`` and then failed has still sent
        something, and a user asking "did my document leave this machine" must
        not be told no because the request errored afterwards.
        """
        return any(state == EGRESS_STATE for _, state, _ in self.history) or self.state in (
            EGRESS_STATE, "active", "completing", "completed", "lost", "reconciliation_required",
        )

    def move(self, state: str, *, now: float, detail: str = "") -> "RemoteTask":
        if state not in REMOTE_STATES:
            raise RemoteStateError(f"unknown remote state: {state!r}")
        if state not in _ALLOWED.get(self.state, frozenset()):
            raise RemoteStateError(
                f"{self.task_id}: {self.state} -> {state} is not a legal transition"
            )
        return replace(
            self, state=state, updated_at_monotonic=now, detail=detail,
            history=(*self.history, (now, state, detail)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "serviceId": self.service_id,
            "capability": self.capability,
            "dataClassification": self.data_classification,
            "state": self.state,
            "terminal": self.terminal,
            "dataHasLeftTheDevice": self.data_has_left,
            "providerId": self.provider_id,
            "idempotencyToken": self.idempotency_token,
            "attempt": self.attempt,
            "maximumAttempts": self.maximum_attempts,
            "resultProvenance": dict(self.result_provenance) if self.result_provenance else None,
            "detail": self.detail,
            "history": [
                {"atMonotonic": at, "state": state, "detail": detail}
                for at, state, detail in self.history
            ],
        }


_PRIVACY_RANK = {name: index for index, name in enumerate(("public", "internal", "sensitive", "secret"))}


@dataclass(frozen=True)
class RemoteDispatchGuard:
    """Every precondition for data leaving the machine, checked together.

    Deliberately one function rather than a sequence of calls the caller
    assembles. A caller that assembles its own sequence can omit one, and the
    one it omits will be the one that mattered.
    """

    policy: Any
    provider: ProviderIdentity | None = None
    approved: bool = False
    network_online: bool = True

    def refusals(self, task: RemoteTask) -> tuple[str, ...]:
        """Every reason this task may not be dispatched. Empty means it may."""
        problems: list[str] = []
        remote = getattr(self.policy, "remote_execution", None)

        if not bool(getattr(remote, "enabled", False)):
            problems.append("remote execution is disabled in policy")

        if task.data_classification == "secret":
            problems.append("the task is classified secret and never leaves the device")
        elif (
            _PRIVACY_RANK.get(task.data_classification, 0) >= _PRIVACY_RANK["sensitive"]
            and not bool(getattr(remote, "allow_sensitive_data", False))
        ):
            problems.append(
                f"the task is classified {task.data_classification} and "
                "remoteExecution.allowSensitiveData is false"
            )

        if self.provider is None:
            problems.append("no provider has been authenticated for this dispatch")
        else:
            if not self.provider.authenticated:
                problems.append(f"provider {self.provider.provider_id!r} is not authenticated")
            if not self.provider.usable:
                problems.append(
                    f"provider {self.provider.provider_id!r} has not declared retention or training use; "
                    "an undeclared provider fails closed"
                )
            if task.capability not in self.provider.capabilities:
                problems.append(
                    f"provider {self.provider.provider_id!r} does not serve {task.capability!r}"
                )
            permits = getattr(remote, "permits", None)
            if callable(permits) and not permits(self.provider.provider_id):
                problems.append(
                    f"provider {self.provider.provider_id!r} is not in remoteExecution.permittedProviders"
                )
            if (
                _PRIVACY_RANK.get(task.data_classification, 0)
                > _PRIVACY_RANK.get(self.provider.maximum_privacy_class, 0)
            ):
                problems.append(
                    f"the task is classified {task.data_classification} and provider "
                    f"{self.provider.provider_id!r} may receive at most "
                    f"{self.provider.maximum_privacy_class}"
                )

        if bool(getattr(remote, "require_user_approval", True)) and not self.approved:
            problems.append("remoteExecution.requireUserApproval is true and no approval has been given")

        if not self.network_online:
            problems.append("there is no route to any provider")

        if not task.idempotency_token:
            problems.append(
                "this task has no idempotency token; a dispatch that cannot be recognised as a "
                "retry may be billed and executed twice"
            )

        if task.attempt >= task.maximum_attempts:
            problems.append(
                f"this task has already been attempted {task.attempt} times against a "
                f"{task.maximum_attempts} attempt limit"
            )
        return tuple(problems)

    def dispatch(self, task: RemoteTask, *, now: float) -> RemoteTask:
        """Move a queued task to ``dispatching``, or to a state explaining why not.

        This is the only function in Bunny OS that authorises data leaving the
        machine, and it authorises nothing unless every refusal is empty.
        """
        problems = self.refusals(task)
        if problems:
            detail = "; ".join(problems)
            if task.state == "queued" and "no approval has been given" in detail:
                return task.move("not_permitted", now=now, detail=detail)
            if task.state in ("awaiting_approval", "awaiting_provider", "queued"):
                return task.move("not_permitted", now=now, detail=detail)
            return task
        provider_id = self.provider.provider_id if self.provider is not None else None
        return replace(
            task.move(EGRESS_STATE, now=now, detail=f"dispatching to {provider_id}"),
            provider_id=provider_id,
            attempt=task.attempt + 1,
        )


class RemoteProviderTransport(Protocol):
    """What a real integration would have to implement. None does, yet."""

    identity: ProviderIdentity

    def submit(self, task: RemoteTask, payload: Any) -> str:
        """Send the work. Returns a provider-side handle."""

    def poll(self, handle: str) -> str:
        """One of :data:`REMOTE_STATES`."""

    def cancel(self, handle: str) -> bool:
        """Withdraw the work. Returns whether the provider confirmed it."""


@dataclass
class TestProvider:
    """A provider that exists only for tests. It sends nothing anywhere.

    Named ``TestProvider`` rather than something that sounds like a product, so
    that a grep for a provider name in this repository finds only this.
    """

    identity: ProviderIdentity
    submitted: list[tuple[str, str]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    #: What :meth:`poll` reports, in order. Exhausting it repeats the last value.
    poll_sequence: list[str] = field(default_factory=lambda: ["active", "completing", "completed"])
    _polls: int = 0

    def submit(self, task: RemoteTask, payload: Any = None) -> str:
        handle = f"test-handle-{task.idempotency_token}"
        self.submitted.append((task.task_id, task.idempotency_token))
        return handle

    def poll(self, handle: str) -> str:
        if not self.poll_sequence:
            return "lost"
        index = min(self._polls, len(self.poll_sequence) - 1)
        self._polls += 1
        return self.poll_sequence[index]

    def cancel(self, handle: str) -> bool:
        self.cancelled.append(handle)
        return True


@dataclass
class RemoteTaskLedger:
    """Every remote task this machine knows about, and their fates."""

    tasks: dict[str, RemoteTask] = field(default_factory=dict)

    def add(self, task: RemoteTask) -> RemoteTask:
        self.tasks[task.task_id] = task
        return task

    def update(self, task: RemoteTask) -> RemoteTask:
        self.tasks[task.task_id] = task
        return task

    def needing_reconciliation(self) -> tuple[RemoteTask, ...]:
        """Tasks whose fate is unknown and must be established.

        These are the ones that cost money twice if handled carelessly. A lost
        task is not retried until somebody has established whether the first
        attempt is still running.
        """
        return tuple(
            self.tasks[key] for key in sorted(self.tasks)
            if self.tasks[key].state in ("lost", "reconciliation_required")
        )

    def data_egress_count(self) -> int:
        """How many tasks have actually sent something. For the privacy surface."""
        return sum(1 for item in self.tasks.values() if item.data_has_left)

    def to_json(self) -> dict[str, Any]:
        return {
            "tasks": [self.tasks[key].to_json() for key in sorted(self.tasks)],
            "needingReconciliation": [item.task_id for item in self.needing_reconciliation()],
            "tasksThatSentData": self.data_egress_count(),
        }


def new_task(
    *,
    task_id: str,
    plan_id: str,
    transition_id: str,
    service_id: str,
    capability: str,
    data_classification: str = "internal",
    now: float = 0.0,
    policy: Any = None,
) -> RemoteTask:
    """Create a task in the correct initial state for the current policy.

    A machine with remote execution off produces tasks in ``not_permitted``, and
    ``not_permitted`` has no outgoing transitions. There is no sequence of calls
    that walks such a task to ``dispatching``, which is a stronger guarantee
    than a check somebody has to remember to run.
    """
    remote = getattr(policy, "remote_execution", None)
    if not bool(getattr(remote, "enabled", False)):
        state, detail = "not_permitted", "remote execution is disabled in policy"
    elif bool(getattr(remote, "require_user_approval", True)):
        state, detail = "awaiting_approval", "this dispatch needs the user to say yes"
    else:
        state, detail = "awaiting_provider", "waiting for an authenticated provider"
    return RemoteTask(
        task_id=task_id,
        plan_id=plan_id,
        transition_id=transition_id,
        service_id=service_id,
        capability=capability,
        data_classification=data_classification,
        state=state,
        idempotency_token=idempotency_token(plan_id, transition_id, task_id),
        created_at_monotonic=now,
        updated_at_monotonic=now,
        detail=detail,
        history=((now, state, detail),),
    )

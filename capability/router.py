# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local-versus-remote execution for individual tasks.

:mod:`capability.engine` decides what *services* run. This module decides where
one *task* runs, which is a different question asked far more often and against
much stronger constraints. A service placement is a resource decision; a task
placement can be a disclosure.

The rule that shapes everything here, from §9 of the brief:

    Sensitive tasks must not be sent remotely merely because the local device
    is weak.

So local incapability is never an argument for remote execution. The routing
order is **permission first, capability second**: a task that may not leave the
device is refused before anything asks whether it could have run here. A weak
machine running a sensitive task gets "this cannot be done here, and it may not
be done elsewhere", which is the honest answer, rather than a quiet upload.

Providers are an interface, not an integration. :class:`RemoteProvider` is a
protocol with a declaration block; :class:`NullProvider` and the test doubles
are the only implementations in this repository. Nothing here contacts a named
commercial service, and no credential is read, stored or logged by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .budget import Budget
from .model import Inventory
from .policy import Policy
from .scores import ScoreSet

__all__ = [
    "DATA_LOCALITIES",
    "LATENCY_PREFERENCES",
    "NullProvider",
    "PRIVACY_CLASSES",
    "ProviderDeclaration",
    "RemoteProvider",
    "RouteDecision",
    "TaskRequest",
    "route",
]

#: Increasing sensitivity. ``sensitive`` and above never leave the device
#: unless policy explicitly permits it, and ``secret`` never leaves at all.
PRIVACY_CLASSES = ("public", "internal", "sensitive", "secret")

#: Where a task's data is permitted to be processed.
DATA_LOCALITIES = ("any", "trusted-remote", "device-only")

LATENCY_PREFERENCES = ("interactive", "batch")

_PRIVACY_RANK = {name: index for index, name in enumerate(PRIVACY_CLASSES)}


@dataclass(frozen=True)
class ProviderDeclaration:
    """What a remote provider states about itself, mechanically.

    Every field here is read by the router or rendered into a disclosure. There
    is deliberately no free-text "description of our privacy practices": a
    disclosure that renders from prose cannot be checked, and an undeclared
    field fails closed rather than being assumed benign.
    """

    id: str
    title: str
    #: "loopback" | "private-network" | "hosted"
    locality: str = "hosted"
    #: "none" | "ephemeral" | "logged" | "unspecified"
    retention: str = "unspecified"
    trains_on_input: bool | None = None
    costs_money: bool = True
    #: Capability names this provider can serve, e.g. ``("inference", "tts")``.
    capabilities: tuple[str, ...] = ()
    jurisdiction: str = "unspecified"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "locality": self.locality,
            "retention": self.retention,
            "trainsOnInput": self.trains_on_input,
            "costsMoney": self.costs_money,
            "capabilities": list(self.capabilities),
            "jurisdiction": self.jurisdiction,
        }

    @property
    def fully_declared(self) -> bool:
        """Whether enough is declared to route to this provider at all.

        Undeclared fails closed. A provider that will not say whether it trains
        on input, or how long it retains data, cannot be the destination for a
        routing decision the user is entitled to understand.
        """
        return (
            self.retention in ("none", "ephemeral", "logged")
            and self.trains_on_input is not None
            and self.locality in ("loopback", "private-network", "hosted")
        )


class RemoteProvider(Protocol):
    """A destination for remote work.

    Implementations live outside this repository. Bunny OS ships the interface
    and a refusing default so that the routing logic is complete and testable
    without any real integration existing.
    """

    declaration: ProviderDeclaration

    def available(self) -> bool:
        """Whether this provider can be reached and is configured right now."""


@dataclass(frozen=True)
class NullProvider:
    """The default provider: declares nothing, accepts nothing.

    Its purpose is to make "no provider is configured" a first-class, testable
    state rather than an empty collection everything has to special-case.
    """

    declaration: ProviderDeclaration = field(default_factory=lambda: ProviderDeclaration(
        id="none", title="No remote provider configured", locality="hosted",
        retention="unspecified", trains_on_input=None, costs_money=False, capabilities=(),
    ))

    def available(self) -> bool:
        return False


@dataclass(frozen=True)
class TaskRequest:
    """One unit of work, with everything needed to decide where it may run."""

    id: str
    #: What the task needs, e.g. ``"inference"``, ``"tts"``, ``"stt"``, ``"render"``.
    capability: str
    privacy: str = "internal"
    data_locality: str = "any"
    latency: str = "interactive"
    #: Maximum the user will spend, in whole currency minor units. ``0`` means
    #: nothing may be spent, which is not the same as no limit.
    maximum_cost_units: int = 0
    #: The task must complete without network access.
    requires_offline: bool = False
    #: Task-level opt-in. Even ``True`` cannot widen what policy permits.
    remote_allowed: bool = True
    #: The user has already approved this dispatch.
    user_approved: bool = False
    #: Memory this task needs to run locally, if known.
    local_memory_bytes: int | None = None
    #: Score dimensions this task needs locally, e.g. ``{"local_ai": 40}``.
    local_requirements: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.privacy not in PRIVACY_CLASSES:
            raise ValueError(f"privacy must be one of {list(PRIVACY_CLASSES)}")
        if self.data_locality not in DATA_LOCALITIES:
            raise ValueError(f"dataLocality must be one of {list(DATA_LOCALITIES)}")
        if self.latency not in LATENCY_PREFERENCES:
            raise ValueError(f"latency must be one of {list(LATENCY_PREFERENCES)}")

    @property
    def may_ever_leave_device(self) -> bool:
        """A fixed property of the task, before any policy or hardware is read."""
        return (
            self.remote_allowed
            and self.data_locality != "device-only"
            and not self.requires_offline
            and self.privacy != "secret"
        )


@dataclass(frozen=True)
class RouteDecision:
    """Where a task runs, and every reason. Reconstructible after the fact."""

    task_id: str
    target: str            # "local" | "remote" | "refused"
    provider_id: str | None = None
    reasons: Sequence[str] = ()
    disclosure: Mapping[str, Any] = field(default_factory=dict)
    requires_user_approval: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "target": self.target,
            "providerId": self.provider_id,
            "requiresUserApproval": self.requires_user_approval,
            "reasons": list(self.reasons),
            "disclosure": dict(self.disclosure),
        }


def _local_feasible(
    task: TaskRequest,
    scores: ScoreSet,
    budget: Budget,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    feasible = True

    if task.local_memory_bytes is not None:
        if budget.currently_allocatable_bytes < task.local_memory_bytes:
            feasible = False
            reasons.append(
                f"needs {task.local_memory_bytes // (1024 ** 2)} MiB and "
                f"{budget.currently_allocatable_bytes // (1024 ** 2)} MiB of budget remains"
            )

    for dimension, minimum in sorted(task.local_requirements.items()):
        score = scores.get(dimension)
        # when_unknown=False: an unmeasured dimension does not satisfy a
        # requirement. Local execution is not attempted on a capability nobody
        # established, because the failure mode is a task that starts and dies.
        if not score.at_least(minimum, when_unknown=False):
            feasible = False
            reasons.append(
                f"{dimension} is "
                + ("unmeasured" if score.value is None else f"{score.value:.0f}")
                + f" against a required {minimum:.0f}"
            )
    return feasible, reasons


def route(
    task: TaskRequest,
    inventory: Inventory,
    scores: ScoreSet,
    budget: Budget,
    policy: Policy,
    providers: Sequence[RemoteProvider] = (),
) -> RouteDecision:
    """Decide where one task runs.

    The order below is the contract. Locality permission is settled before
    capability is consulted, so that no path exists by which a weak machine
    argues its way into sending data it may not send.
    """
    reasons: list[str] = []

    # 1. Can this task leave the device at all? Asked first, and independently
    #    of whether it could run here.
    may_leave = task.may_ever_leave_device
    if not may_leave:
        if task.privacy == "secret":
            reasons.append("the task is classified secret and never leaves the device")
        if task.data_locality == "device-only":
            reasons.append("the task declares device-only data locality")
        if task.requires_offline:
            reasons.append("the task declares an offline requirement")
        if not task.remote_allowed:
            reasons.append("the task does not permit remote execution")

    # 2. Could it run here?
    feasible, local_reasons = _local_feasible(task, scores, budget)
    if feasible:
        return RouteDecision(
            task.id, "local",
            reasons=(*reasons, "local execution satisfies every requirement, and local is preferred"),
        )

    reasons.extend(f"local execution is not possible: {item}" for item in local_reasons)

    if not may_leave:
        return RouteDecision(
            task.id, "refused",
            reasons=(*reasons, "this task may not be executed remotely, so it cannot be executed"),
        )

    # 3. Only now is remote considered — and only under policy.
    if not policy.remote_execution.enabled:
        return RouteDecision(
            task.id, "refused",
            reasons=(*reasons, "remote execution is disabled in policy; nothing is dispatched by default"),
        )
    if _PRIVACY_RANK[task.privacy] >= _PRIVACY_RANK["sensitive"] and not policy.remote_execution.allow_sensitive_data:
        return RouteDecision(
            task.id, "refused",
            reasons=(*reasons, f"the task is classified {task.privacy} and remoteExecution.allowSensitiveData is false"),
        )
    if not inventory.network.online:
        return RouteDecision(
            task.id, "refused",
            reasons=(*reasons, "there is no usable network route to any provider"),
        )
    if not policy.metered_network_allowed and inventory.network.metered.get(None) is not False:
        return RouteDecision(
            task.id, "refused",
            reasons=(*reasons, "the connection is metered or of unknown metering, and meteredNetworkAllowed is false"),
        )

    for provider in providers:
        declaration = provider.declaration
        if task.capability not in declaration.capabilities:
            continue
        if not policy.remote_execution.permits(declaration.id):
            reasons.append(f"provider {declaration.id!r} is not in permittedProviders")
            continue
        if not declaration.fully_declared:
            reasons.append(
                f"provider {declaration.id!r} has not declared retention, training use or locality; "
                "an undeclared provider fails closed"
            )
            continue
        if declaration.costs_money and task.maximum_cost_units <= 0:
            reasons.append(f"provider {declaration.id!r} bills for use and the task permits no spend")
            continue
        if not provider.available():
            reasons.append(f"provider {declaration.id!r} is configured but not currently available")
            continue

        needs_approval = policy.remote_execution.require_user_approval and not task.user_approved
        return RouteDecision(
            task.id,
            "remote" if not needs_approval else "refused",
            provider_id=declaration.id,
            requires_user_approval=needs_approval,
            reasons=(
                *reasons,
                f"provider {declaration.id!r} serves {task.capability} and is permitted by policy",
                *(("the user has not approved this dispatch and requireUserApproval is true",) if needs_approval else ()),
            ),
            disclosure={
                "provider": declaration.to_json(),
                "capability": task.capability,
                "privacy": task.privacy,
                "whatLeavesTheDevice": f"the inputs of task {task.id}",
                "costPermitted": task.maximum_cost_units,
            },
        )

    return RouteDecision(
        task.id, "refused",
        reasons=(*reasons, f"no permitted, fully declared provider serves {task.capability!r}"),
    )

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""User and administrator policy: constraints on automatic adaptation.

A preference here is a **constraint on the search**, never a mode switch. That
distinction is §12 of the brief and it is structural rather than stylistic:
``maximum_background_cpu_percent`` narrows what the budget engine may allocate
and the policy engine then re-derives every decision from the narrowed budget.
It does not select a "power profile" that some other code branches on. There is
no branch to write, because there is no mode to branch on.

Defaults are privacy-preserving and local-first, and the two that matter most
are:

* ``remote_execution.enabled`` is ``False``. Remote execution is opt-in. A weak
  machine does not acquire permission to send a user's data somewhere by virtue
  of being weak.
* ``remote_execution.allow_sensitive_data`` is ``False``, independently. Turning
  remote execution on does not turn sensitive-data egress on with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

__all__ = [
    "DEFAULT_POLICY_PATH",
    "DEPRECATED_KEYS",
    "Policy",
    "PolicyError",
    "RemoteExecutionPolicy",
    "load_policy",
    "parse_policy",
]

#: System policy. User overrides live in ``$XDG_CONFIG_HOME/bunny-os/capability.json``
#: and may only narrow what this file permits.
DEFAULT_POLICY_PATH = Path("/etc/bunny-os/capability-policy.json")

#: Configuration keys from earlier mode-based designs. Each is refused with the
#: capability-shaped replacement named, so a stale config produces an actionable
#: error rather than being silently ignored — which would leave the operator
#: believing a limit was in force when it was not.
#:
#: Nothing in this repository ever shipped these keys; see
#: ``MODE_MIGRATION_REPORT.md``. They are listed because the brief requires a
#: migration path, and because a user arriving from another adaptive-OS design
#: will reach for exactly these names.
DEPRECATED_KEYS: Mapping[str, str] = {
    "performanceMode": "set maximumBackgroundCpuPercent and maximumServiceMemoryBytes instead",
    "performance_mode": "set maximumBackgroundCpuPercent and maximumServiceMemoryBytes instead",
    "hardwareTier": "capability is derived from measurement; there is no tier to declare",
    "hardware_tier": "capability is derived from measurement; there is no tier to declare",
    "capabilityTier": "capability is derived from measurement; there is no tier to declare",
    "profile": "use disabledServices and pinnedImplementations to constrain specific services",
    "mode": "use disabledServices and pinnedImplementations to constrain specific services",
    "powerLevel": "set preferLowEnergy, or a maximumBackgroundCpuPercent",
}

_VALID_LATENCY = ("interactive", "batch")


class PolicyError(ValueError):
    """A policy document that cannot be honoured as written."""


@dataclass(frozen=True)
class RemoteExecutionPolicy:
    enabled: bool = False
    require_user_approval: bool = True
    allow_sensitive_data: bool = False
    permitted_providers: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "requireUserApproval": self.require_user_approval,
            "allowSensitiveData": self.allow_sensitive_data,
            "permittedProviders": list(self.permitted_providers),
        }

    def permits(self, provider: str) -> bool:
        """Remote execution is allowed only to a named, permitted provider.

        An empty allowlist permits nothing even when ``enabled`` is true. "On"
        is not a destination, and a provider the user never named is not one
        they consented to.
        """
        return self.enabled and provider in self.permitted_providers


@dataclass(frozen=True)
class Policy:
    """The full set of constraints applied to automatic adaptation."""

    #: Share of total CPU the budget engine may allocate to work nobody is
    #: waiting on. ``None`` means "derive it from measured headroom".
    maximum_background_cpu_percent: float | None = None
    #: Hard ceiling on memory across all Bunny OS services, in bytes.
    maximum_service_memory_bytes: int | None = None
    #: Fraction of usable memory held back from every allocation. Raising this
    #: makes the machine safer and Bunny OS smaller; it can never be lowered
    #: below :data:`MINIMUM_RESERVE_FRACTION` in the budget engine.
    protected_reserve_fraction: float | None = None

    prefer_local: bool = True
    prefer_low_energy: bool = False
    metered_network_allowed: bool = False
    confirm_before_paid_api: bool = True

    remote_execution: RemoteExecutionPolicy = field(default_factory=RemoteExecutionPolicy)

    #: Service ids the user has switched off. An entry here is final: the
    #: policy engine will not start the service for any reason.
    disabled_services: tuple[str, ...] = ()
    #: ``{service id: implementation id}``. Honoured when the implementation's
    #: requirements are met, refused with an explanation when they are not — a
    #: pin is a preference, not a licence to overcommit the machine.
    pinned_implementations: Mapping[str, str] = field(default_factory=dict)

    #: Seconds a service must remain in its current state before the engine may
    #: change it again. Prevents a service oscillating around a threshold.
    state_change_cooldown_seconds: float = 60.0
    #: Fractional band around each threshold. A stopped service needs
    #: ``threshold * (1 + hysteresis)`` to start; a running one keeps running
    #: until ``threshold * (1 - hysteresis)``.
    hysteresis_fraction: float = 0.15
    #: How often runtime monitoring re-evaluates. Configurable per §17.
    monitor_interval_seconds: float = 30.0

    #: Endpoints the reachability probe may contact, as ``host:port``. Empty by
    #: default: nothing is contacted unless the user configured somewhere.
    reachability_endpoints: tuple[tuple[str, int], ...] = ()

    source: str = "defaults"
    warnings: tuple[str, ...] = ()

    def with_warnings(self, extra: Sequence[str]) -> "Policy":
        return replace(self, warnings=tuple([*self.warnings, *extra]))

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "maximumBackgroundCpuPercent": self.maximum_background_cpu_percent,
            "maximumServiceMemoryBytes": self.maximum_service_memory_bytes,
            "protectedReserveFraction": self.protected_reserve_fraction,
            "preferLocal": self.prefer_local,
            "preferLowEnergy": self.prefer_low_energy,
            "meteredNetworkAllowed": self.metered_network_allowed,
            "confirmBeforePaidApi": self.confirm_before_paid_api,
            "remoteExecution": self.remote_execution.to_json(),
            "disabledServices": list(self.disabled_services),
            "pinnedImplementations": dict(self.pinned_implementations),
            "stateChangeCooldownSeconds": self.state_change_cooldown_seconds,
            "hysteresisFraction": self.hysteresis_fraction,
            "monitorIntervalSeconds": self.monitor_interval_seconds,
            "reachabilityEndpoints": [f"{host}:{port}" for host, port in self.reachability_endpoints],
            "warnings": list(self.warnings),
        }


def _number(document: Mapping[str, Any], key: str, *, minimum: float, maximum: float) -> float | None:
    if key not in document or document[key] is None:
        return None
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{key} must be a number")
    if not minimum <= value <= maximum:
        raise PolicyError(f"{key} must be between {minimum} and {maximum}")
    return float(value)


def _boolean(document: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in document:
        return default
    value = document[key]
    if not isinstance(value, bool):
        raise PolicyError(f"{key} must be true or false")
    return value


def _strings(document: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = document.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PolicyError(f"{key} must be an array of strings")
    return tuple(value)


def _endpoints(document: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    endpoints: list[tuple[str, int]] = []
    for item in _strings(document, "reachabilityEndpoints"):
        host, separator, port = item.rpartition(":")
        if not separator or not port.isdigit() or not host:
            raise PolicyError(f"reachabilityEndpoints entry {item!r} must be host:port")
        number = int(port)
        if not 1 <= number <= 65535:
            raise PolicyError(f"reachabilityEndpoints entry {item!r} has an invalid port")
        # The host is never interpolated into a command; it reaches only
        # socket.create_connection. Length-bounded to keep a pathological
        # config from producing an unbounded connect attempt.
        endpoints.append((host[:253], number))
    return tuple(endpoints)


def parse_policy(document: Mapping[str, Any], *, source: str = "document") -> Policy:
    """Validate a policy document into a :class:`Policy`.

    Refuses rather than repairs. A policy that cannot be honoured as written is
    an operator error, and silently substituting a default would leave a limit
    the operator believes is in force silently absent.
    """
    if not isinstance(document, Mapping):
        raise PolicyError("policy must be a JSON object")

    stale = sorted(set(document).intersection(DEPRECATED_KEYS))
    if stale:
        raise PolicyError(
            "this policy uses mode-based keys that Bunny OS does not have: "
            + "; ".join(f"{key} ({DEPRECATED_KEYS[key]})" for key in stale)
        )

    version = document.get("schemaVersion", 1)
    if version != 1:
        raise PolicyError(f"unsupported policy schemaVersion: {version!r}")

    remote_document = document.get("remoteExecution", {})
    if not isinstance(remote_document, Mapping):
        raise PolicyError("remoteExecution must be an object")
    remote = RemoteExecutionPolicy(
        enabled=_boolean(remote_document, "enabled", False),
        require_user_approval=_boolean(remote_document, "requireUserApproval", True),
        allow_sensitive_data=_boolean(remote_document, "allowSensitiveData", False),
        permitted_providers=_strings(remote_document, "permittedProviders"),
    )

    warnings: list[str] = []
    if remote.enabled and not remote.permitted_providers:
        warnings.append(
            "remoteExecution.enabled is true but permittedProviders is empty, "
            "so no task can be dispatched anywhere. Name a provider or turn it off."
        )
    if remote.allow_sensitive_data and not remote.enabled:
        warnings.append(
            "remoteExecution.allowSensitiveData is true while remoteExecution.enabled "
            "is false; it has no effect until remote execution is enabled."
        )

    pinned = document.get("pinnedImplementations", {})
    if not isinstance(pinned, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in pinned.items()
    ):
        raise PolicyError("pinnedImplementations must map service ids to implementation ids")

    return Policy(
        maximum_background_cpu_percent=_number(document, "maximumBackgroundCpuPercent", minimum=0.0, maximum=100.0),
        maximum_service_memory_bytes=(
            int(value) if (value := _number(document, "maximumServiceMemoryBytes", minimum=0, maximum=2 ** 53)) is not None else None
        ),
        protected_reserve_fraction=_number(document, "protectedReserveFraction", minimum=0.0, maximum=0.9),
        prefer_local=_boolean(document, "preferLocal", True),
        prefer_low_energy=_boolean(document, "preferLowEnergy", False),
        metered_network_allowed=_boolean(document, "meteredNetworkAllowed", False),
        confirm_before_paid_api=_boolean(document, "confirmBeforePaidApi", True),
        remote_execution=remote,
        disabled_services=_strings(document, "disabledServices"),
        pinned_implementations=dict(pinned),
        state_change_cooldown_seconds=_number(document, "stateChangeCooldownSeconds", minimum=0.0, maximum=3600.0) or 60.0,
        hysteresis_fraction=(
            value if (value := _number(document, "hysteresisFraction", minimum=0.0, maximum=0.5)) is not None else 0.15
        ),
        monitor_interval_seconds=_number(document, "monitorIntervalSeconds", minimum=1.0, maximum=3600.0) or 30.0,
        reachability_endpoints=_endpoints(document),
        source=source,
        warnings=tuple(warnings),
    )


def _permission_warning(path: Path) -> str | None:
    """Refuse to trust a policy file the world can rewrite.

    A capability policy decides whether remote execution is permitted and which
    providers may receive data. A group- or world-writable one is a privilege
    escalation waiting to be used, so it is reported rather than quietly obeyed.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if os.name == "nt":
        # Windows does not carry POSIX mode bits meaningfully; the check is a
        # no-op here rather than a false alarm on every development checkout.
        return None
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        return (
            f"{path} is writable by group or others (mode {stat.S_IMODE(mode):04o}); "
            "capability policy should be 0644 root-owned or stricter"
        )
    return None


def load_policy(path: Path | None = None, *, user_path: Path | None = None) -> Policy:
    """System policy, then user overrides, with the user unable to widen.

    Only the constraint-shaped fields are user-overridable, and only in the
    narrowing direction. A user cannot grant themselves remote execution the
    system policy withheld, which is what keeps this a preference surface rather
    than a policy bypass.
    """
    system_path = DEFAULT_POLICY_PATH if path is None else path
    policy = Policy()
    warnings: list[str] = []

    if system_path.is_file():
        warning = _permission_warning(system_path)
        if warning:
            warnings.append(warning)
        try:
            document = json.loads(system_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError(f"{system_path} could not be read: {exc}") from exc
        policy = parse_policy(document, source=str(system_path))

    if user_path is not None and user_path.is_file():
        try:
            document = json.loads(user_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError(f"{user_path} could not be read: {exc}") from exc
        user = parse_policy(document, source=str(user_path))
        policy = _narrow(policy, user)
        warnings.extend(user.warnings)

    return policy.with_warnings(warnings)


def _narrow(system: Policy, user: Policy) -> Policy:
    """Apply user preferences, taking the more restrictive value everywhere."""

    def smaller(left: float | None, right: float | None) -> float | None:
        values = [value for value in (left, right) if value is not None]
        return min(values) if values else None

    def larger(left: float | None, right: float | None) -> float | None:
        values = [value for value in (left, right) if value is not None]
        return max(values) if values else None

    remote = RemoteExecutionPolicy(
        enabled=system.remote_execution.enabled and user.remote_execution.enabled,
        require_user_approval=system.remote_execution.require_user_approval or user.remote_execution.require_user_approval,
        allow_sensitive_data=system.remote_execution.allow_sensitive_data and user.remote_execution.allow_sensitive_data,
        # Intersection: a user may decline providers the system permits, never add one.
        permitted_providers=tuple(
            provider for provider in user.remote_execution.permitted_providers
            if provider in system.remote_execution.permitted_providers
        ),
    )
    return replace(
        user,
        maximum_background_cpu_percent=smaller(system.maximum_background_cpu_percent, user.maximum_background_cpu_percent),
        maximum_service_memory_bytes=(
            int(value) if (value := smaller(system.maximum_service_memory_bytes, user.maximum_service_memory_bytes)) is not None else None
        ),
        protected_reserve_fraction=larger(system.protected_reserve_fraction, user.protected_reserve_fraction),
        metered_network_allowed=system.metered_network_allowed and user.metered_network_allowed,
        confirm_before_paid_api=system.confirm_before_paid_api or user.confirm_before_paid_api,
        remote_execution=remote,
        # Union: either layer may switch a service off; neither may switch on
        # what the other switched off.
        disabled_services=tuple(sorted(set(system.disabled_services) | set(user.disabled_services))),
        source=f"{system.source} + {user.source}",
    )

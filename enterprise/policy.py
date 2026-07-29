"""Typed device policy agent.

The central rule: every policy maps to exactly one typed, named operation with a
validated desired state. There is no operation that accepts a command, an argv, a
script, a path chosen by the server, or an environment. This mirrors the existing
broker design, whose ``backend.py`` docstring already states "No operation accepts
an executable or argv".

A second rule is enforced here rather than left to documentation: a set of
*safety invariants* cannot be expressed as a policy at all. An organisation can
require encryption; it cannot disable update signature verification, weaken a
privacy default, or make private Bunny memory visible. Those are not
low-precedence preferences that lose a conflict — they are unrepresentable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping, Sequence

SCHEMA_VERSION = 1

ENFORCEMENT_TYPES = ("informational", "recommended", "enforced", "blocked")
POLICY_SCOPES = ("organisation", "device-group", "device", "user")
REMEDIATION_BEHAVIOURS = ("none", "notify", "remediate", "block-until-compliant")

#: States a policy may report after evaluation on a device.
POLICY_RESULTS = ("compliant", "non-compliant", "remediating", "not-applicable", "unknown", "expired")

_POLICY_ID = re.compile(r"^POL-[0-9]{4}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

#: Settings no organisation policy may target, regardless of enforcement type.
#: These are refused at parse time so an unreviewed policy cannot even be stored.
SAFETY_INVARIANTS = frozenset({
    "os.update.signature-verification",
    "os.update.trust-root",
    "os.security.warnings-visible",
    "os.recovery.enabled",
    "bunny.privacy.dashboard-visible",
    "bunny.permissions.enforcement",
    "bunny.permissions.prompt-required",
    "bunny.memory.expose-to-organisation",
    "bunny.memory.export-to-fleet",
    "bunny.prompts.expose-to-organisation",
    "bunny.diagnostics.redaction",
    "sync.end-to-end-encryption",
})


class PolicyError(ValueError):
    """Raised when a policy is malformed, unsupported, or forbidden."""


def _require_bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise PolicyError(f"{name} must be a boolean")


def _require_enum(value: Any, allowed: Sequence[str], name: str) -> None:
    if value not in allowed:
        raise PolicyError(f"{name} must be one of {', '.join(allowed)}")


def _require_package_list(value: Any, name: str) -> None:
    if not isinstance(value, list) or not value:
        raise PolicyError(f"{name} must be a non-empty list of package identifiers")
    if len(value) > 512:
        raise PolicyError(f"{name} exceeds the 512-entry limit")
    for item in value:
        if not isinstance(item, str) or not _PACKAGE_ID.match(item):
            raise PolicyError(f"{name} contains an invalid package identifier: {item!r}")


def _validate_update_channel(state: Any) -> None:
    _require_enum(state, ("developer", "beta", "stable"), "update channel")


def _validate_update_deadline(state: Any) -> None:
    if not isinstance(state, int) or isinstance(state, bool) or not 0 <= state <= 90:
        raise PolicyError("update deadline must be a whole number of days between 0 and 90")


def _validate_firewall_baseline(state: Any) -> None:
    _require_enum(state, ("default-drop", "default-drop-with-approved-exceptions"), "firewall baseline")


def _validate_screen_lock(state: Any) -> None:
    if not isinstance(state, Mapping):
        raise PolicyError("screen-lock policy must be an object")
    if set(state) != {"requireLock", "maxIdleSeconds"}:
        raise PolicyError("screen-lock policy requires exactly requireLock and maxIdleSeconds")
    _require_bool(state["requireLock"], "requireLock")
    idle = state["maxIdleSeconds"]
    if not isinstance(idle, int) or isinstance(idle, bool) or not 30 <= idle <= 3600:
        raise PolicyError("maxIdleSeconds must be between 30 and 3600")


def _validate_requirement(state: Any) -> None:
    _require_enum(state, ("required", "recommended", "not-required"), "requirement")


def _validate_minimum_version(state: Any) -> None:
    if not isinstance(state, str) or not _SEMVER.match(state):
        raise PolicyError("minimum OS version must be a semantic version")


def _validate_recovery_readiness(state: Any) -> None:
    _require_enum(state, ("required", "recommended"), "recovery readiness")


def _validate_allowlist(state: Any) -> None:
    _require_package_list(state, "application allowlist")


def _validate_blocklist(state: Any) -> None:
    _require_package_list(state, "application blocklist")


def _validate_provider_policy(state: Any) -> None:
    if not isinstance(state, Mapping):
        raise PolicyError("provider policy must be an object")
    if any(
        str(key).replace("_", "").replace("-", "").casefold()
        in {"apikey", "token", "secret", "credential", "credentials", "password", "passphrase", "privatekey"}
        for key in state
    ):
        raise PolicyError("provider policy must reference a credential source, never a credential value")
    allowed = {
        "localOnly", "approvedProviders", "approvedRegions", "approvedModels",
        "maximumDataClassification", "cloudFallback", "credentialSource", "usageLimit", "costLimit",
    }
    unexpected = sorted(set(state) - allowed)
    if unexpected:
        raise PolicyError("unknown provider policy fields: " + ", ".join(unexpected))
    if "localOnly" in state:
        _require_bool(state["localOnly"], "provider policy localOnly")
    if "cloudFallback" in state:
        _require_enum(state["cloudFallback"], ("never", "ask"), "cloudFallback")
    if "credentialSource" in state:
        _require_enum(
            state["credentialSource"],
            ("organisation-managed", "user-supplied", "local-only"),
            "credentialSource",
        )
    if "maximumDataClassification" in state:
        _require_enum(
            state["maximumDataClassification"],
            ("public", "internal", "confidential", "restricted"),
            "maximumDataClassification",
        )
    for key in ("approvedProviders", "approvedRegions", "approvedModels"):
        if key in state and (not isinstance(state[key], list) or not all(isinstance(item, str) for item in state[key])):
            raise PolicyError(f"{key} must be a list of strings")
    for key in ("usageLimit", "costLimit"):
        if key in state:
            value = state[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PolicyError(f"{key} must be a non-negative whole number")


def _validate_plugin_policy(state: Any) -> None:
    if not isinstance(state, Mapping):
        raise PolicyError("plugin policy must be an object")
    allowed = {
        "publisherAllowlist", "publisherBlocklist", "pluginAllowlist", "pluginBlocklist",
        "maximumCapability", "networkPolicy", "versionPins", "revokedPlugins",
    }
    unexpected = sorted(set(state) - allowed)
    if unexpected:
        raise PolicyError("unknown plugin policy fields: " + ", ".join(unexpected))
    for key in ("publisherAllowlist", "publisherBlocklist", "pluginAllowlist", "pluginBlocklist", "revokedPlugins"):
        if key in state and (not isinstance(state[key], list) or not all(isinstance(item, str) for item in state[key])):
            raise PolicyError(f"{key} must be a list of strings")
    if "maximumCapability" in state:
        _require_enum(
            state["maximumCapability"],
            ("none", "read-only", "workspace-scoped", "full-requested"),
            "maximumCapability",
        )
    if "networkPolicy" in state:
        _require_enum(state["networkPolicy"], ("deny", "allowlist", "grant-per-plugin"), "plugin networkPolicy")
    if "versionPins" in state:
        pins = state["versionPins"]
        if not isinstance(pins, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in pins.items()
        ):
            raise PolicyError("versionPins must map plugin identifiers to version strings")
    if state.get("maximumCapability") == "full-requested" and not state.get("pluginAllowlist"):
        raise PolicyError(
            "a full-requested capability ceiling requires an explicit plugin allowlist; "
            "capabilities are never granted silently"
        )


def _validate_removable_media(state: Any) -> None:
    _require_enum(state, ("allow", "read-only", "deny"), "removable media policy")


def _validate_diagnostic_export(state: Any) -> None:
    _require_enum(state, ("local-only", "local-only-with-approval", "deny"), "diagnostic export policy")


def _validate_local_only_ai(state: Any) -> None:
    _require_bool(state, "local-only AI requirement")


@dataclass(frozen=True)
class PolicyDomain:
    """One managed domain and the single typed operation that applies it."""

    domain: str
    operation: str
    description: str
    validate: Callable[[Any], None]
    userOverridable: bool = False


#: The complete set of managed domains. A policy naming a domain outside this
#: registry is rejected, which is what keeps the agent's capability surface fixed.
MANAGED_DOMAINS: tuple[PolicyDomain, ...] = (
    PolicyDomain("update-channel", "policy.update.channel.set", "Pin the update channel", _validate_update_channel),
    PolicyDomain("update-deadline", "policy.update.deadline.set", "Days before an offered update becomes mandatory", _validate_update_deadline),
    PolicyDomain("application-allowlist", "policy.application.allowlist.set", "Applications permitted to install", _validate_allowlist),
    PolicyDomain("application-blocklist", "policy.application.blocklist.set", "Applications refused installation", _validate_blocklist),
    PolicyDomain("firewall-baseline", "policy.firewall.baseline.set", "Minimum firewall posture", _validate_firewall_baseline),
    PolicyDomain("screen-lock", "policy.screenlock.set", "Screen-lock requirement and idle limit", _validate_screen_lock),
    PolicyDomain("encryption-requirement", "policy.encryption.requirement.set", "Full-disk encryption requirement", _validate_requirement),
    PolicyDomain("secure-boot-requirement", "policy.secureboot.requirement.set", "Secure Boot requirement", _validate_requirement),
    PolicyDomain("minimum-os-version", "policy.os.minimum-version.set", "Lowest permitted OS version", _validate_minimum_version),
    PolicyDomain("recovery-readiness", "policy.recovery.readiness.set", "Recovery availability requirement", _validate_recovery_readiness),
    PolicyDomain("bunny-provider-policy", "policy.bunny.provider.set", "Approved AI providers, regions, models, and limits", _validate_provider_policy),
    PolicyDomain("local-only-ai-requirement", "policy.bunny.local-only.set", "Require local-only AI operation", _validate_local_only_ai),
    PolicyDomain("plugin-policy", "policy.bunny.plugins.set", "Plugin publisher, capability, and network limits", _validate_plugin_policy),
    PolicyDomain("removable-media-policy", "policy.removable-media.set", "Removable media access", _validate_removable_media),
    PolicyDomain("diagnostic-export-policy", "policy.diagnostics.export.set", "Diagnostic export permission", _validate_diagnostic_export),
)

_DOMAINS_BY_NAME = {domain.domain: domain for domain in MANAGED_DOMAINS}
TYPED_OPERATIONS = tuple(sorted(domain.operation for domain in MANAGED_DOMAINS))

#: Keys that would turn a policy into an execution channel.
_EXECUTION_KEYS = frozenset({
    "command", "commands", "exec", "execstart", "argv", "script", "scripts", "shell",
    "interpreter", "entrypoint", "runas", "path", "binary", "payload", "powershell", "bash",
})


@dataclass(frozen=True)
class Policy:
    policyId: str
    version: int
    domain: str
    operation: str
    scope: str
    owner: str
    desiredState: Any
    enforcementType: str
    effectiveFrom: str
    expiresAt: str | None
    priority: int
    conflictRule: str
    remediation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policyId,
            "version": self.version,
            "domain": self.domain,
            "operation": self.operation,
            "scope": self.scope,
            "owner": self.owner,
            "desiredState": self.desiredState,
            "enforcementType": self.enforcementType,
            "effectiveFrom": self.effectiveFrom,
            "expiresAt": self.expiresAt,
            "priority": self.priority,
            "conflictRule": self.conflictRule,
            "remediation": self.remediation,
        }


def _assert_no_execution_channel(value: Any, path: str = "desiredState") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            folded = str(key).replace("_", "").replace("-", "").casefold()
            if folded in _EXECUTION_KEYS:
                raise PolicyError(
                    f"policy {path}.{key} would create an execution channel; "
                    "the policy agent exposes no generic execution operation"
                )
            _assert_no_execution_channel(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_execution_channel(item, f"{path}[{index}]")


def parse_policy(record: Mapping[str, Any], *, now: datetime | None = None) -> Policy:
    """Validate one policy record and bind it to its typed operation."""
    if not isinstance(record, Mapping):
        raise PolicyError("policy must be a mapping")

    allowed = {
        "schemaVersion", "policyId", "version", "domain", "scope", "owner", "desiredState",
        "enforcementType", "effectiveFrom", "expiresAt", "priority", "conflictRule", "remediation",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise PolicyError("unknown policy fields: " + ", ".join(unexpected))
    missing = sorted(allowed - {"expiresAt"} - set(record))
    if missing:
        raise PolicyError("missing policy fields: " + ", ".join(missing))

    if record["schemaVersion"] != SCHEMA_VERSION:
        raise PolicyError(f"unsupported policy schemaVersion {record['schemaVersion']!r}")

    policy_id = record["policyId"]
    if not isinstance(policy_id, str) or not _POLICY_ID.match(policy_id):
        raise PolicyError("policyId must match POL-<4 digits>")

    version = record["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PolicyError("version must be a positive whole number")

    domain_name = record["domain"]
    if domain_name in SAFETY_INVARIANTS:
        raise PolicyError(
            f"{domain_name!r} is a safety invariant and cannot be set by organisation policy"
        )
    domain = _DOMAINS_BY_NAME.get(domain_name)
    if domain is None:
        raise PolicyError(
            f"unknown policy domain {domain_name!r}; supported domains are "
            + ", ".join(sorted(_DOMAINS_BY_NAME))
        )

    scope = record["scope"]
    _require_enum(scope, POLICY_SCOPES, "scope")

    owner = record["owner"]
    if not isinstance(owner, str) or not owner:
        raise PolicyError("owner must name the accountable administrator or role")

    enforcement = record["enforcementType"]
    _require_enum(enforcement, ENFORCEMENT_TYPES, "enforcementType")

    remediation = record["remediation"]
    _require_enum(remediation, REMEDIATION_BEHAVIOURS, "remediation")

    priority = record["priority"]
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 1000:
        raise PolicyError("priority must be a whole number between 0 and 1000")

    conflict_rule = record["conflictRule"]
    _require_enum(conflict_rule, ("most-restrictive-wins", "highest-priority-wins", "closest-scope-wins"), "conflictRule")

    effective_from = record["effectiveFrom"]
    if not isinstance(effective_from, str) or not _RFC3339.match(effective_from):
        raise PolicyError("effectiveFrom must be an RFC 3339 timestamp")

    expires_at = record.get("expiresAt")
    if expires_at is not None:
        if not isinstance(expires_at, str) or not _RFC3339.match(expires_at):
            raise PolicyError("expiresAt must be an RFC 3339 timestamp when present")
        if expires_at <= effective_from:
            raise PolicyError("expiresAt must be after effectiveFrom")

    desired_state = record["desiredState"]
    _assert_no_execution_channel(desired_state)
    domain.validate(desired_state)

    if enforcement == "blocked" and remediation == "none":
        raise PolicyError("a blocked policy must declare a remediation behaviour other than none")

    return Policy(
        policyId=policy_id,
        version=version,
        domain=domain_name,
        operation=domain.operation,
        scope=scope,
        owner=owner,
        desiredState=desired_state,
        enforcementType=enforcement,
        effectiveFrom=effective_from,
        expiresAt=expires_at,
        priority=priority,
        conflictRule=conflict_rule,
        remediation=remediation,
    )


def is_active(policy: Policy, *, now: datetime | None = None) -> bool:
    """Return whether a policy is within its effective window."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    effective = datetime.fromisoformat(policy.effectiveFrom.replace("Z", "+00:00")).astimezone(timezone.utc)
    if current < effective:
        return False
    if policy.expiresAt is None:
        return True
    expires = datetime.fromisoformat(policy.expiresAt.replace("Z", "+00:00")).astimezone(timezone.utc)
    return current < expires


def describe_domains() -> list[dict[str, Any]]:
    """Return the managed-domain catalogue for documentation and console display."""
    return [
        {
            "domain": item.domain,
            "operation": item.operation,
            "description": item.description,
            "userOverridable": item.userOverridable,
        }
        for item in MANAGED_DOMAINS
    ]

# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed policy operations for the policy socket.

Like ``backend.py``, no operation accepts an executable, argv, or a
caller-supplied path. Unlike ``backend.py``, no operation shells out at all:
applying a policy is a validated, atomic write of a root-owned overlay file.

The request carries only ``policyId`` and ``version``. The desired state is
read from the staged bundle that the policy agent already verified against the
organisation's signature, so the socket is not a channel for novel values.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .auth import PeerIdentity
from .backend import BackendError

#: Written by the policy agent after it verifies a signed bundle. Root-only.
STAGED_POLICY_PATH = Path("/var/lib/bunny-os/policy/staged-policies.json")

#: Read by the desktop settings layer as the organisation overlay. Root-owned,
#: world-readable, never user-writable.
MANAGED_SETTINGS_PATH = Path("/etc/bunny-os/managed-settings.json")

MAX_STAGED_BYTES = 1024 * 1024

#: Policy domains that resolve to a per-user shell setting. Every other domain
#: is recorded under ``osPolicy`` for the component that owns it; nothing is
#: silently dropped.
_SETTING_BINDINGS: dict[str, str] = {
    "local-only-ai-requirement": "localOnlyMode",
    "diagnostic-export-policy": "diagnosticsPolicy",
}

#: Domains whose desired state is an object, with a named field bound to a
#: shell setting.
_NESTED_SETTING_BINDINGS: dict[str, tuple[str, str]] = {
    "bunny-provider-policy": ("cloudFallback", "cloudFailoverPolicy"),
    "plugin-policy": ("networkPolicy", "pluginNetworkDefault"),
}

_OPERATION_DOMAINS = {
    "policy.application.allowlist.set": "application-allowlist",
    "policy.application.blocklist.set": "application-blocklist",
    "policy.bunny.local-only.set": "local-only-ai-requirement",
    "policy.bunny.plugins.set": "plugin-policy",
    "policy.bunny.provider.set": "bunny-provider-policy",
    "policy.diagnostics.export.set": "diagnostic-export-policy",
    "policy.encryption.requirement.set": "encryption-requirement",
    "policy.firewall.baseline.set": "firewall-baseline",
    "policy.os.minimum-version.set": "minimum-os-version",
    "policy.recovery.readiness.set": "recovery-readiness",
    "policy.removable-media.set": "removable-media-policy",
    "policy.screenlock.set": "screen-lock",
    "policy.secureboot.requirement.set": "secure-boot-requirement",
    "policy.update.channel.set": "update-channel",
    "policy.update.deadline.set": "update-deadline",
}


def _read_staged() -> dict[str, Any]:
    try:
        raw = STAGED_POLICY_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise BackendError("policy_unavailable", "no staged policy bundle is present") from exc
    except OSError as exc:
        raise BackendError("policy_unavailable", "staged policy bundle is unreadable") from exc
    if len(raw) > MAX_STAGED_BYTES:
        raise BackendError("policy_invalid", "staged policy bundle exceeds 1 MiB")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackendError("policy_invalid", "staged policy bundle is not valid JSON") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise BackendError("policy_invalid", "staged policy bundle schema is unsupported")
    if not isinstance(value.get("policies"), list):
        raise BackendError("policy_invalid", "staged policy bundle has no policy list")
    return value


def _find(staged: dict[str, Any], policy_id: str, version: int) -> dict[str, Any]:
    for entry in staged["policies"]:
        if not isinstance(entry, dict):
            continue
        if entry.get("policyId") == policy_id:
            if entry.get("version") != version:
                raise BackendError(
                    "policy_version_mismatch",
                    "the staged policy version does not match the requested version",
                )
            return entry
    raise BackendError("policy_not_found", "the requested policy is not in the staged bundle")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_overlay() -> dict[str, Any]:
    try:
        value = json.loads(MANAGED_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schemaVersion": 1, "organisationId": None, "updatedAt": None, "settings": {}, "osPolicy": {}}
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        return {"schemaVersion": 1, "organisationId": None, "updatedAt": None, "settings": {}, "osPolicy": {}}
    value.setdefault("settings", {})
    value.setdefault("osPolicy", {})
    return value


def apply_policy(method: str, policy_id: str, version: int) -> dict[str, Any]:
    """Apply one staged policy to the managed overlay."""
    domain = _OPERATION_DOMAINS.get(method)
    if domain is None:
        raise BackendError("unknown_method", "method is not a policy operation")

    staged = _read_staged()
    entry = _find(staged, policy_id, version)
    if entry.get("domain") != domain:
        raise BackendError(
            "policy_domain_mismatch",
            "the staged policy domain does not match the requested operation",
        )
    desired = entry.get("desiredState")
    enforcement = entry.get("enforcementType")
    if enforcement not in {"informational", "recommended", "enforced", "blocked"}:
        raise BackendError("policy_invalid", "staged policy has an unsupported enforcement type")

    overlay = _load_overlay()
    overlay["organisationId"] = staged.get("organisationId")
    overlay["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    binding: dict[str, Any] = {
        "desiredState": desired,
        "policyId": policy_id,
        "version": version,
        "enforcementType": enforcement,
    }
    overlay["osPolicy"][domain] = binding

    # Only an enforced or blocked policy locks a user-visible setting.
    # Informational and recommended policies are recorded and displayed but do
    # not take the control away from the user.
    locked_setting: str | None = None
    if enforcement in {"enforced", "blocked"}:
        if domain in _SETTING_BINDINGS:
            locked_setting = _SETTING_BINDINGS[domain]
            overlay["settings"][locked_setting] = {
                "value": desired,
                "policyId": policy_id,
                "version": version,
            }
        elif domain in _NESTED_SETTING_BINDINGS and isinstance(desired, dict):
            field, setting = _NESTED_SETTING_BINDINGS[domain]
            if field in desired:
                locked_setting = setting
                overlay["settings"][setting] = {
                    "value": desired[field],
                    "policyId": policy_id,
                    "version": version,
                }

    _atomic_write(MANAGED_SETTINGS_PATH, overlay)
    return {
        "applied": True,
        "domain": domain,
        "policyId": policy_id,
        "version": version,
        "enforcementType": enforcement,
        "lockedSetting": locked_setting,
    }


def read_status() -> dict[str, Any]:
    """Report which policies are currently applied. Reads no user data."""
    overlay = _load_overlay()
    return {
        "organisationId": overlay.get("organisationId"),
        "updatedAt": overlay.get("updatedAt"),
        "appliedDomains": sorted(overlay.get("osPolicy", {})),
        "lockedSettings": sorted(overlay.get("settings", {})),
        "stagedBundlePresent": STAGED_POLICY_PATH.is_file(),
    }


def execute(
    method: str,
    params: dict[str, Any],
    peer: PeerIdentity,
    request_id: str,
    cancel: Any = None,
) -> dict[str, Any]:
    """Dispatch a policy-socket operation. No subprocess, no argv, no path input."""
    if method == "policy.status.read":
        return read_status()
    return apply_policy(method, params["policyId"], params["version"])

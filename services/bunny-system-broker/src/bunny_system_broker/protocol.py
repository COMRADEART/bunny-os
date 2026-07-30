"""Strict request and argument validation for the broker wire protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable

from . import CONTRACT_VERSION


class ProtocolError(ValueError):
    """A stable, client-safe protocol failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MethodSpec:
    mutating: bool
    polkit_action: str | None
    timeout_seconds: int
    validate_params: Callable[[dict[str, Any]], dict[str, Any]]


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_NONCE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_SERVICE_NAMES = {
    "bunny-system-broker.service",
    "bunny-update-agent@check.service",
    "bunny-update-agent@stage.service",
    "bunny-update-agent@install.service",
    "bunny-health-check.service",
    "bunny-recovery-prepare.service",
    "firewalld.service",
    "NetworkManager.service",
    "gdm.service",
}


def _exact(params: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ProtocolError("invalid_params", f"unknown parameter: {sorted(unknown)[0]}")


def _none(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, set())
    return {}


def _service(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, {"service"})
    service = params.get("service")
    if service not in _SERVICE_NAMES:
        raise ProtocolError("invalid_params", "service is not in the broker allowlist")
    return {"service": service}


def _recovery(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, {"mode"})
    mode = params.get("mode")
    if mode not in {"recovery", "safe-graphics"}:
        raise ProtocolError("invalid_params", "mode must be recovery or safe-graphics")
    return {"mode": mode}


def _enabled(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, {"enabled"})
    enabled = params.get("enabled")
    if not isinstance(enabled, bool):
        raise ProtocolError("invalid_params", "enabled must be a boolean")
    return {"enabled": enabled}


def _logs(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, {"sinceMinutes"})
    value = params.get("sinceMinutes", 60)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
        raise ProtocolError("invalid_params", "sinceMinutes must be an integer from 1 to 1440")
    return {"sinceMinutes": value}


def _cancel(params: dict[str, Any]) -> dict[str, Any]:
    _exact(params, {"requestId"})
    request_id = params.get("requestId")
    if not isinstance(request_id, str) or not _SAFE_ID.fullmatch(request_id):
        raise ProtocolError("invalid_params", "requestId is invalid")
    return {"requestId": request_id}


METHODS: dict[str, MethodSpec] = {
    "system.status.read": MethodSpec(False, None, 5, _none),
    "power.shutdown": MethodSpec(True, "art.comrade.bunny-os.power", 20, _none),
    "power.reboot": MethodSpec(True, "art.comrade.bunny-os.power", 20, _none),
    "power.suspend": MethodSpec(True, "art.comrade.bunny-os.power", 20, _none),
    "service.status.read": MethodSpec(False, None, 5, _service),
    "network.status.read": MethodSpec(False, None, 5, _none),
    "update.status.read": MethodSpec(False, None, 5, _none),
    "update.check": MethodSpec(True, "art.comrade.bunny-os.update", 45, _none),
    "update.stage": MethodSpec(True, "art.comrade.bunny-os.update", 5100, _none),
    "update.install": MethodSpec(True, "art.comrade.bunny-os.update", 120, _none),
    "update.preference.set": MethodSpec(True, "art.comrade.bunny-os.update", 30, _enabled),
    "rollback.list": MethodSpec(False, None, 10, _none),
    "rollback.select": MethodSpec(True, "art.comrade.bunny-os.rollback", 30, _none),
    "recovery.status.read": MethodSpec(False, None, 5, _none),
    "recovery.schedule": MethodSpec(True, "art.comrade.bunny-os.recovery", 15, _recovery),
    "logs.export": MethodSpec(True, "art.comrade.bunny-os.diagnostics", 120, _logs),
    "hardware.inventory.read": MethodSpec(False, None, 20, _none),
    "request.cancel": MethodSpec(False, None, 5, _cancel),
}


def _policy(params: dict[str, Any]) -> dict[str, Any]:
    """Validate a policy application request.

    The socket carries only an identifier and a version. It never carries a
    desired state: the broker reads the already-validated policy from the
    root-only staged bundle, so a compromised control plane cannot push a
    novel value through this interface, and the broker does not have to
    re-implement the fifteen per-domain validators that live in
    ``enterprise/policy.py``.
    """
    _exact(params, {"policyId", "version"})
    policy_id = params.get("policyId")
    if not isinstance(policy_id, str) or not _POLICY_ID.fullmatch(policy_id):
        raise ProtocolError("invalid_params", "policyId must match POL-<4 digits>")
    version = params.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 1_000_000:
        raise ProtocolError("invalid_params", "version must be a positive integer")
    return {"policyId": policy_id, "version": version}


_POLICY_ID = re.compile(r"^POL-[0-9]{4}$")

#: The fifteen typed policy operations. These are duplicated literally rather
#: than imported from ``enterprise.policy`` because this package deliberately
#: uses only the standard library; ``tests/broker`` asserts the two lists stay
#: identical, so drift fails a test rather than passing silently.
POLICY_OPERATIONS = (
    "policy.application.allowlist.set",
    "policy.application.blocklist.set",
    "policy.bunny.local-only.set",
    "policy.bunny.plugins.set",
    "policy.bunny.provider.set",
    "policy.diagnostics.export.set",
    "policy.encryption.requirement.set",
    "policy.firewall.baseline.set",
    "policy.os.minimum-version.set",
    "policy.recovery.readiness.set",
    "policy.removable-media.set",
    "policy.screenlock.set",
    "policy.secureboot.requirement.set",
    "policy.update.channel.set",
    "policy.update.deadline.set",
)

#: The policy socket's complete method surface. It shares no entry with
#: ``METHODS``: a policy agent cannot reboot, stage an update, or export logs,
#: and a desktop client cannot apply policy.
POLICY_METHODS: dict[str, MethodSpec] = {
    **{name: MethodSpec(True, None, 30, _policy) for name in POLICY_OPERATIONS},
    "policy.status.read": MethodSpec(False, None, 5, _none),
    "request.cancel": MethodSpec(False, None, 5, _cancel),
}


@dataclass(frozen=True)
class ValidatedRequest:
    request_id: str
    method: str
    params: dict[str, Any]
    timestamp: datetime
    nonce: str
    spec: MethodSpec


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ProtocolError("invalid_request", "timestamp must be an RFC 3339 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProtocolError("invalid_request", "timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProtocolError("invalid_request", "timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_request(
    payload: Any,
    now: datetime | None = None,
    *,
    methods: dict[str, MethodSpec] | None = None,
) -> ValidatedRequest:
    """Validate one request against a method table.

    ``methods`` defaults to the user-socket table, so every existing caller is
    unchanged. The policy socket passes ``POLICY_METHODS``, which is how a
    method allowed on one socket stays rejected on the other.
    """
    table = METHODS if methods is None else methods
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_request", "request must be an object")
    expected = {"contractVersion", "id", "method", "params", "timestamp", "nonce"}
    missing = expected - set(payload)
    unknown = set(payload) - expected
    if missing:
        raise ProtocolError("invalid_request", f"missing field: {sorted(missing)[0]}")
    if unknown:
        raise ProtocolError("invalid_request", f"unknown field: {sorted(unknown)[0]}")
    if payload["contractVersion"] != CONTRACT_VERSION:
        raise ProtocolError("incompatible_contract", "Bunny OS contract version is incompatible")
    request_id = payload["id"]
    if not isinstance(request_id, str) or not _SAFE_ID.fullmatch(request_id):
        raise ProtocolError("invalid_request", "id is invalid")
    method = payload["method"]
    if not isinstance(method, str) or method not in table:
        raise ProtocolError("unknown_method", "method is not allowed")
    params = payload["params"]
    if not isinstance(params, dict):
        raise ProtocolError("invalid_params", "params must be an object")
    timestamp = _parse_timestamp(payload["timestamp"])
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if abs((current - timestamp).total_seconds()) > 30:
        raise ProtocolError("stale_request", "request timestamp is outside the 30 second window")
    nonce = payload["nonce"]
    if not isinstance(nonce, str) or not _SAFE_NONCE.fullmatch(nonce):
        raise ProtocolError("invalid_request", "nonce is invalid")
    spec = table[method]
    return ValidatedRequest(request_id, method, spec.validate_params(params), timestamp, nonce, spec)


def success_response(request_id: str, result: Any) -> dict[str, Any]:
    return {"contractVersion": CONTRACT_VERSION, "id": request_id, "ok": True, "result": result}


def error_response(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {
        "contractVersion": CONTRACT_VERSION,
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }

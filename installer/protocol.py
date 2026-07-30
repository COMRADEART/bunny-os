# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed installer protocol validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping


SCHEMA_VERSION = 1
OPERATIONS = frozenset(
    {
        "installer.initialize",
        "installer.probe",
        "installer.plan.validate",
        "installer.plan.preview",
        "installer.install.start",
        "installer.install.status",
        "installer.install.cancel",
        "installer.install.logs",
        "installer.install.verify",
        "installer.recovery.prepare",
    }
)
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SECRET_KEYS = frozenset({"password", "passphrase", "recoverykey", "rawkey", "providerkey", "token", "secret"})


class ProtocolError(ValueError):
    """A request is malformed or violates the protocol boundary."""


@dataclass(frozen=True)
class InstallerRequest:
    schema_version: int
    request_id: str
    installation_id: str
    operation: str
    nonce: str
    timestamp: datetime
    params: Mapping[str, Any]


def _contains_secret_field(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in SECRET_KEYS or _contains_secret_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False


def parse_request(payload: Mapping[str, Any], *, now: datetime | None = None) -> InstallerRequest:
    allowed = {"schemaVersion", "requestId", "installationId", "operation", "nonce", "timestamp", "params"}
    required = allowed
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - allowed)
        raise ProtocolError(f"request fields mismatch; missing={missing}, extra={extra}")
    if payload["schemaVersion"] != SCHEMA_VERSION:
        raise ProtocolError("unsupported schemaVersion")
    request_id = payload["requestId"]
    installation_id = payload["installationId"]
    nonce = payload["nonce"]
    operation = payload["operation"]
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ProtocolError("invalid requestId")
    if not isinstance(installation_id, str) or not REQUEST_ID.fullmatch(installation_id):
        raise ProtocolError("invalid installationId")
    if operation not in OPERATIONS:
        raise ProtocolError("unknown installer operation")
    if not isinstance(nonce, str) or not NONCE.fullmatch(nonce):
        raise ProtocolError("invalid nonce")
    params = payload["params"]
    if not isinstance(params, Mapping):
        raise ProtocolError("params must be an object")
    if _contains_secret_field(params):
        raise ProtocolError("secrets are forbidden in protocol payloads")
    timestamp_text = payload["timestamp"]
    if not isinstance(timestamp_text, str):
        raise ProtocolError("timestamp must be RFC3339 text")
    try:
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProtocolError("invalid timestamp") from error
    if timestamp.tzinfo is None:
        raise ProtocolError("timestamp requires a timezone")
    current = now or datetime.now(timezone.utc)
    if abs((current - timestamp.astimezone(timezone.utc)).total_seconds()) > 60:
        raise ProtocolError("stale installer request")
    return InstallerRequest(
        schema_version=SCHEMA_VERSION,
        request_id=request_id,
        installation_id=installation_id,
        operation=operation,
        nonce=nonce,
        timestamp=timestamp,
        params=params,
    )

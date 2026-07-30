# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured, secret-free installer audit records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


REDACT_KEYS = frozenset(
    {
        "password",
        "passwordsecretref",
        "passphrase",
        "recoverykey",
        "rawkey",
        "secret",
        "secretref",
        "providerkey",
        "token",
        "serial",
        "uuid",
        "usercontents",
    }
)


def redact(value: object) -> object:
    if isinstance(value, Mapping):
        clean: dict[str, object] = {}
        for key, child in value.items():
            clean[str(key)] = "[redacted]" if str(key).casefold() in REDACT_KEYS else redact(child)
        return clean
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "[truncated]"
    return deepcopy(value)


def record(*, stage: str, operation_id: str, correlation_id: str, target_reference: str | None, result: str, detail: object | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "operationId": operation_id,
        "correlationId": correlation_id,
        "targetReference": target_reference,
        "result": result,
        "detail": redact(detail) if detail is not None else None,
    }


def append(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(redact(entry), sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = path.open("a", encoding="utf-8", newline="\n")
    try:
        descriptor.write(payload)
        descriptor.flush()
    finally:
        descriptor.close()
    try:
        path.chmod(0o600)
    except OSError:
        pass

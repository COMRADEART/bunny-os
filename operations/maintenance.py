"""Read-only maintenance alert evaluation; this module cannot publish releases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("maintenance timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("maintenance timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def evaluate_alerts(records: Iterable[Mapping[str, Any]], now: datetime | None = None) -> list[dict[str, str]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts: list[dict[str, str]] = []
    allowed = {"signing-key", "metadata", "mirror", "recovery-image", "kernel", "application-runtime", "vulnerability-feed", "package"}
    for record in records:
        kind = record.get("kind")
        if kind not in allowed:
            raise ValueError("unsupported maintenance record kind")
        status = record.get("status")
        if status in {"broken", "unsupported", "outdated"}:
            alerts.append({"kind": str(kind), "id": str(record.get("id", "unknown")), "reason": str(status), "action": "alert-only"})
        expires = record.get("expiresAt")
        if expires is not None and _time(expires) <= current + timedelta(days=30):
            alerts.append({"kind": str(kind), "id": str(record.get("id", "unknown")), "reason": "expires-within-30-days", "action": "alert-only"})
    return alerts

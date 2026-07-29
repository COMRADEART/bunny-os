"""Fail-closed update, migration, and downgrade compatibility matrix."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


REQUIRED = frozenset({
    "sourceRelease", "targetRelease", "directUpdateSupported", "intermediateRelease", "databaseMigration",
    "configurationMigration", "recoveryImageRequired", "rollbackStatus", "downgradeStatus", "knownLimitations",
})


def validate_entry(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != REQUIRED:
        raise ValueError("update compatibility fields do not match schema version 1")
    if not isinstance(raw.get("directUpdateSupported"), bool) or not isinstance(raw.get("recoveryImageRequired"), bool):
        raise ValueError("compatibility booleans are invalid")
    for field in REQUIRED - {"directUpdateSupported", "recoveryImageRequired"}:
        if not isinstance(raw.get(field), str):
            raise ValueError(f"{field} must be a string")
    if raw["directUpdateSupported"] and raw["rollbackStatus"] not in {"qualified", "qualified_with_limitations"}:
        raise ValueError("a supported update requires a qualified rollback path")
    return dict(raw)


def resolve_update(source: str, target: str, entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    matches = [validate_entry(item) for item in entries if item.get("sourceRelease") == source and item.get("targetRelease") == target]
    if len(matches) != 1:
        return {"allowed": False, "reason": "unsupported-release-jump"}
    entry = matches[0]
    if not entry["directUpdateSupported"]:
        return {"allowed": False, "reason": "direct-update-not-qualified", "intermediateRelease": entry["intermediateRelease"]}
    return {"allowed": True, "entry": entry}

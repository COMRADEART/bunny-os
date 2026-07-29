"""Privacy-safe crash metadata aggregation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from .taxonomy import validate_component


APPROVED_FIELDS = frozenset({"component", "version", "architecture", "stackSignature", "driver", "kernel", "deploymentVersion"})


def normalize_crash(raw: Mapping[str, Any]) -> dict[str, str]:
    if set(raw) != APPROVED_FIELDS:
        raise ValueError("crash report must contain only approved non-identifying metadata")
    validate_component(raw.get("component"))
    result: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError(f"invalid crash metadata: {key}")
        result[key] = value
    return result


def aggregate_crashes(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter((item["component"], item["stackSignature"], item["version"]) for item in map(normalize_crash, values))
    return [
        {"component": key[0], "stackSignature": key[1], "version": key[2], "count": count}
        for key, count in sorted(counter.items())
    ]

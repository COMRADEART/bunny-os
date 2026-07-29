"""Failure signature catalogue and deterministic matching."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .taxonomy import validate_component, validate_severity


SAFE_SIGNATURE_ID = re.compile(r"FS-[0-9]{4}\Z")
REQUIRED = frozenset({
    "id", "name", "component", "signature", "affectedVersions", "affectedHardware", "detectionMethod",
    "severity", "workaround", "fixedVersion", "regressionTest",
})


def validate_signature(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != REQUIRED:
        raise ValueError("failure signature fields do not match schema version 1")
    if not isinstance(raw.get("id"), str) or not SAFE_SIGNATURE_ID.fullmatch(str(raw["id"])):
        raise ValueError("failure signature ID is invalid")
    validate_component(raw.get("component"))
    validate_severity(raw.get("severity"))
    signature = raw.get("signature")
    if not isinstance(signature, str) or not signature or len(signature) > 256:
        raise ValueError("failure signature is invalid")
    for field in ("affectedVersions", "affectedHardware"):
        if not isinstance(raw.get(field), list) or not all(isinstance(item, str) for item in raw[field]):
            raise ValueError(f"{field} must be a string array")
    return dict(raw)


def match_signatures(event: Mapping[str, Any], catalogue: Iterable[Mapping[str, Any]]) -> list[str]:
    component = event.get("component")
    haystack = " ".join(str(event.get(field, "")) for field in ("errorSignature", "stackSignature", "message")).casefold()
    matches = []
    for raw in catalogue:
        item = validate_signature(raw)
        if item["component"] == component and str(item["signature"]).casefold() in haystack:
            matches.append(str(item["id"]))
    return sorted(matches)

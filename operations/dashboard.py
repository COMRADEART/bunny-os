"""Local release-dashboard rendering without invented scores."""

from __future__ import annotations

from typing import Any, Mapping


FIELDS = (
    "candidateVersion", "buildStatus", "testStatus", "openBlockers", "securityStatus", "privacyStatus",
    "accessibilityStatus", "installerStatus", "updateStatus", "rollbackStatus", "recoveryStatus",
    "hardwareCoverage", "documentationStatus", "signingStatus", "artifactStatus",
)


def render_markdown(values: Mapping[str, Any]) -> str:
    if set(values) != set(FIELDS):
        raise ValueError("release dashboard fields are incomplete")
    if any("percent" in str(key).casefold() or "%" in str(value) for key, value in values.items()):
        raise ValueError("release dashboard must not display fabricated percentages")
    lines = ["# Bunny OS stable qualification dashboard", "", "| Signal | Evidence status |", "|---|---|"]
    for field in FIELDS:
        value = values[field]
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "none recorded"
        lines.append(f"| {field} | {value} |")
    return "\n".join(lines) + "\n"

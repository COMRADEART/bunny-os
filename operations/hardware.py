"""Evidence-only stable hardware tier classification."""

from __future__ import annotations

from typing import Any, Mapping


TIERS = ("Stable recommended", "Stable supported", "Best effort", "Experimental", "Unsupported", "Untested")
RECOMMENDED_EVIDENCE = (
    "cleanInstallation", "encryptedInstallation", "update", "rollback", "recovery", "graphics", "network", "audio", "suspendResume",
)
SUPPORTED_EVIDENCE = ("cleanInstallation", "dailyUse", "graphics", "network", "audio")


def classify_hardware(report: Mapping[str, Any]) -> str:
    if report.get("explicitlyUnsupported") is True:
        return "Unsupported"
    executions = report.get("executions")
    if not isinstance(executions, list) or not executions:
        return "Untested"
    evidence = report.get("evidence")
    if not isinstance(evidence, Mapping):
        return "Experimental"
    open_severities = report.get("openIssueSeverities", [])
    if not isinstance(open_severities, list):
        raise ValueError("openIssueSeverities must be an array")
    if all(evidence.get(key) is True for key in RECOMMENDED_EVIDENCE) and not any(value in {"Blocker", "Critical", "High"} for value in open_severities):
        return "Stable recommended"
    if all(evidence.get(key) is True for key in SUPPORTED_EVIDENCE) and not any(value in {"Blocker", "Critical"} for value in open_severities):
        return "Stable supported"
    if report.get("expectedToWork") is True and not any(value in {"Blocker", "Critical"} for value in open_severities):
        return "Best effort"
    return "Experimental"

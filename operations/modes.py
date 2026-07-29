"""Evidence rules for multi-user, local-only, and Bunny-disabled qualification."""

from __future__ import annotations

from typing import Any, Mapping


MODE_REQUIREMENTS = {
    "multi-user": ("separateMemory", "separateCredentials", "separatePlugins", "separateWorkspaces", "lockScreen", "noCrossUserExposure"),
    "local-only": ("noNetwork", "noCloudProvider", "offlineApplications", "offlineDocumentation", "offlineRecovery", "offlineDiagnostics"),
    "bunny-disabled": ("login", "applications", "terminal", "files", "settings", "network", "updates", "recovery", "applicationInstallation", "accessibility"),
}


def evaluate_mode(name: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if name not in MODE_REQUIREMENTS:
        raise ValueError("unknown qualification mode")
    missing = [field for field in MODE_REQUIREMENTS[name] if evidence.get(field) is not True]
    return {"mode": name, "qualified": not missing, "missingEvidence": missing}

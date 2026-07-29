"""Normative Phase 5 issue component and severity taxonomy."""

from __future__ import annotations


COMPONENTS = (
    "Boot", "Installer", "Encryption", "Secure Boot", "Recovery", "Updates", "Rollback",
    "Kernel", "Firmware", "Graphics", "Display", "Wi-Fi", "Bluetooth", "Audio", "Camera",
    "Suspend", "Power", "Bunny Shell", "Bunny Core", "Bunny Desktop", "Privileged broker",
    "Applications", "Flatpak", "Accessibility", "Privacy", "Security", "Performance", "Documentation",
)

SEVERITIES = ("Blocker", "Critical", "High", "Medium", "Low", "Enhancement")
SEVERITY_RANK = {value: index for index, value in enumerate(SEVERITIES)}
SEVERITY_CRITERIA = {
    "Blocker": "Prevents qualification or safe use of every supported path; no acceptable workaround.",
    "Critical": "Data loss, security boundary bypass, cross-user disclosure, or common-path unusability.",
    "High": "Major supported workflow failure with a limited or operationally costly workaround.",
    "Medium": "Supported behavior is impaired, but a documented low-risk workaround exists.",
    "Low": "Limited impact, cosmetic defect, or uncommon supported edge case.",
    "Enhancement": "Requested behavior that is not a defect in the documented support contract.",
}


def validate_component(value: object) -> str:
    if not isinstance(value, str) or value not in COMPONENTS:
        raise ValueError("component is not in the Phase 5 taxonomy")
    return value


def validate_severity(value: object) -> str:
    if not isinstance(value, str) or value not in SEVERITIES:
        raise ValueError("severity is not in the Phase 5 taxonomy")
    return value


def is_high_severity(value: str) -> bool:
    return SEVERITY_RANK[validate_severity(value)] <= SEVERITY_RANK["High"]

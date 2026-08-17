"""Normative Phase 5 issue component and severity taxonomy."""

from __future__ import annotations


#: Every component an incoming report may be classified as.
#:
#: The last four were added in Phase 5, and the reason is worth keeping. This
#: taxonomy was cut on 2026-07-29, before the Companion runtime, the voice
#: runtime, the Trust prompt and App Capsules existed. §21 of the Phase 5
#: directive asks for Alpha feedback about, in its own words, the Companion,
#: Voice and Permissions — and an alpha tester reporting "Bunny did not hear
#: me" had no component to file it under. The nearest available were
#: ``Audio`` (which is the sound stack, not the speech runtime) and ``Bunny
#: Core`` (which is everything), so the two most likely outcomes were a
#: misfiled report or an unfiled one.
#:
#: A feedback instrument that cannot name the thing being reported does not
#: return "unknown"; it returns a wrong classification that looks like data.
#:
#: Mirrored in ``schemas/beta-feedback.schema.json`` and bound to it by
#: ``tests/operations/test_feedback_taxonomy.py`` — two copies of a list are
#: two chances to update one of them.
COMPONENTS = (
    "Boot", "Installer", "Encryption", "Secure Boot", "Recovery", "Updates", "Rollback",
    "Kernel", "Firmware", "Graphics", "Display", "Wi-Fi", "Bluetooth", "Audio", "Camera",
    "Suspend", "Power", "Bunny Shell", "Bunny Core", "Bunny Desktop", "Privileged broker",
    "Applications", "Flatpak", "Accessibility", "Privacy", "Security", "Performance", "Documentation",
    "Companion", "Voice", "Trust", "App capsules",
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

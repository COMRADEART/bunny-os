"""Privacy-preserving fleet health reporting.

Follows the ``operations/crash.py`` pattern of exact-set equality against a
closed allowlist, and reuses the vocabularies already defined in
``operations/redaction.py`` so that a field prohibited from a diagnostic export
cannot reappear in a fleet report.

Every allowed field is a categorical or version value. There are no free-text
fields, no counts of user activity, and no durations, because a duration is the
easiest way for an operational metric to become a behavioural one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from operations.redaction import EXCLUDED_CONTENT_KEYS, IDENTIFIER_KEYS, SECRET_KEYS

SCHEMA_VERSION = 1

#: The complete fleet health surface. Exact-set equality is enforced.
APPROVED_FIELDS = frozenset({
    "osVersion",
    "updateState",
    "recoveryReadiness",
    "encryptionState",
    "secureBootState",
    "policyAgentHealth",
    "requiredServiceStatus",
    "storageHealthCategory",
    "hardwareSupportCategory",
    "criticalSecurityAdvisoryStatus",
})

#: Named prohibitions. Redundant with the allowlist by design: the allowlist
#: prevents the field, and this set produces a specific, reviewable refusal.
PROHIBITED_FIELDS = frozenset({
    "prompts", "prompt", "conversation", "conversations", "chathistory",
    "memory", "memories", "memorycontents",
    "filenames", "filename", "filepaths", "documents", "documenttitles",
    "browserhistory", "visitedurls",
    "terminalhistory", "commandhistory", "shellhistory",
    "applicationusageduration", "usageduration", "activeminutes", "screentime",
    "keyboardactivity", "keystrokes", "mouseactivity", "inputevents",
    "screenshot", "screenshots", "screencapture",
    "cameracontent", "cameraframe", "microphonecontent", "audiosample",
    "location", "geolocation", "wifinetworks", "nearbydevices",
})

RECOVERY_READINESS = ("ready", "not-ready", "unknown")
ENCRYPTION_STATES = ("encrypted", "not-encrypted", "unknown")
SECURE_BOOT_STATES = ("enabled", "enabled-with-limitations", "disabled", "unknown")
POLICY_AGENT_HEALTH = ("healthy", "degraded", "stopped", "not-installed")
SERVICE_STATUS = ("all-running", "degraded", "failed", "unknown")

#: Storage is reported as a category, never as a serial, model, or SMART dump.
STORAGE_HEALTH_CATEGORIES = ("healthy", "wear-warning", "failing", "unknown")

#: Reuses the tier vocabulary from ``operations/hardware.py`` conceptually, kept
#: as categories so a device never reports a unique hardware fingerprint.
HARDWARE_SUPPORT_CATEGORIES = (
    "stable-recommended", "stable-supported", "best-effort", "experimental", "unsupported", "untested",
)

ADVISORY_STATUS = ("none-open", "open-patch-available", "open-no-patch", "patched", "unknown")

_VERSION = "osVersion"


class HealthError(ValueError):
    """Raised when a fleet health report violates the declared boundary."""


def _folded(key: str) -> str:
    return key.replace("_", "").replace("-", "").casefold()


@dataclass(frozen=True)
class FleetHealth:
    osVersion: str
    updateState: str
    recoveryReadiness: str
    encryptionState: str
    secureBootState: str
    policyAgentHealth: str
    requiredServiceStatus: str
    storageHealthCategory: str
    hardwareSupportCategory: str
    criticalSecurityAdvisoryStatus: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "osVersion": self.osVersion,
            "updateState": self.updateState,
            "recoveryReadiness": self.recoveryReadiness,
            "encryptionState": self.encryptionState,
            "secureBootState": self.secureBootState,
            "policyAgentHealth": self.policyAgentHealth,
            "requiredServiceStatus": self.requiredServiceStatus,
            "storageHealthCategory": self.storageHealthCategory,
            "hardwareSupportCategory": self.hardwareSupportCategory,
            "criticalSecurityAdvisoryStatus": self.criticalSecurityAdvisoryStatus,
        }


def assert_no_prohibited_fields(payload: Mapping[str, Any]) -> None:
    """Refuse content, secret, identifier, and behavioural fields by name.

    Draws on the redaction vocabularies so that fleet health and diagnostic
    export share one definition of forbidden data.
    """
    if not isinstance(payload, Mapping):
        raise HealthError("payload must be a mapping")
    for raw_key in payload:
        folded = _folded(str(raw_key))
        if folded in PROHIBITED_FIELDS:
            raise HealthError(f"prohibited fleet health field: {raw_key!r}")
        if folded in EXCLUDED_CONTENT_KEYS:
            raise HealthError(f"forbidden content field in fleet health: {raw_key!r}")
        if folded in SECRET_KEYS:
            raise HealthError(f"secret field in fleet health: {raw_key!r}")
        if folded in IDENTIFIER_KEYS:
            raise HealthError(
                f"identifying field in fleet health: {raw_key!r}; "
                "device correlation uses the enrolment identity supplied out of band, not an inline identifier"
            )


def parse_health(payload: Mapping[str, Any]) -> FleetHealth:
    """Validate one fleet health report."""
    assert_no_prohibited_fields(payload)

    if set(payload) != APPROVED_FIELDS:
        missing = sorted(APPROVED_FIELDS - set(payload))
        extra = sorted(set(payload) - APPROVED_FIELDS)
        raise HealthError(f"fleet health fields mismatch; missing={missing}, extra={extra}")

    version = payload[_VERSION]
    if not isinstance(version, str) or not version or len(version) > 64:
        raise HealthError("osVersion must be a short non-empty string")

    from enterprise.fleet import UPDATE_STATES

    checks = (
        ("updateState", UPDATE_STATES),
        ("recoveryReadiness", RECOVERY_READINESS),
        ("encryptionState", ENCRYPTION_STATES),
        ("secureBootState", SECURE_BOOT_STATES),
        ("policyAgentHealth", POLICY_AGENT_HEALTH),
        ("requiredServiceStatus", SERVICE_STATUS),
        ("storageHealthCategory", STORAGE_HEALTH_CATEGORIES),
        ("hardwareSupportCategory", HARDWARE_SUPPORT_CATEGORIES),
        ("criticalSecurityAdvisoryStatus", ADVISORY_STATUS),
    )
    for field, allowed in checks:
        if payload[field] not in allowed:
            raise HealthError(f"{field} {payload[field]!r} is not one of {', '.join(allowed)}")

    return FleetHealth(
        osVersion=version,
        updateState=payload["updateState"],
        recoveryReadiness=payload["recoveryReadiness"],
        encryptionState=payload["encryptionState"],
        secureBootState=payload["secureBootState"],
        policyAgentHealth=payload["policyAgentHealth"],
        requiredServiceStatus=payload["requiredServiceStatus"],
        storageHealthCategory=payload["storageHealthCategory"],
        hardwareSupportCategory=payload["hardwareSupportCategory"],
        criticalSecurityAdvisoryStatus=payload["criticalSecurityAdvisoryStatus"],
    )


def describe_visible_fields() -> list[dict[str, str]]:
    """Return exactly what an organisation administrator can see, for disclosure."""
    return [
        {"field": "osVersion", "meaning": "The Bunny OS version string."},
        {"field": "updateState", "meaning": "Whether an update is offered, staged, installed, failed, or rolled back."},
        {"field": "recoveryReadiness", "meaning": "Whether a verified recovery path is available."},
        {"field": "encryptionState", "meaning": "Whether full-disk encryption is active."},
        {"field": "secureBootState", "meaning": "Whether Secure Boot is enabled."},
        {"field": "policyAgentHealth", "meaning": "Whether the policy agent is running."},
        {"field": "requiredServiceStatus", "meaning": "Whether required system services are running."},
        {"field": "storageHealthCategory", "meaning": "A storage health category, never a serial or SMART dump."},
        {"field": "hardwareSupportCategory", "meaning": "The support tier of this hardware."},
        {"field": "criticalSecurityAdvisoryStatus", "meaning": "Whether a critical advisory is open or patched."},
    ]

"""Kiosk, dedicated-purpose, and shared laboratory device profiles.

A restricted profile removes *user-facing* capability. It never removes a
*security* capability: update signature verification, Secure Boot enforcement,
recovery availability, and encryption stay as they are, and attempting to set them
from a kiosk profile is a rejection.

Shared laboratory devices get their own rules because the risk is different: the
threat is one user seeing another user's data on the same machine. Bunny memory
is never shared between users by default, and a shared local model is a
*read-only weights* share, never a shared conversation or memory store.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

KIOSK_MODES = ("single-application", "restricted-desktop", "digital-signage")

SESSION_TYPES = ("ephemeral", "persistent-named")

#: Settings a restricted profile may constrain.
RESTRICTABLE_SETTINGS = frozenset({
    "settingsPanelsVisible",
    "terminalAvailable",
    "applicationInstallation",
    "removableMedia",
    "printing",
    "networkConfiguration",
    "screenshotCapture",
    "developerTools",
})

#: Settings a restricted profile may never weaken. Present as an explicit list so
#: the refusal names the specific protection rather than failing generically.
PROTECTED_SETTINGS = frozenset({
    "updateSignatureVerification",
    "secureBootEnforcement",
    "recoveryAvailable",
    "diskEncryption",
    "brokerAllowlist",
    "polkitRequired",
    "privacyDefaults",
    "selinuxMode",
    "auditLogging",
})

_PROFILE_ID = re.compile(r"^ksk-[a-z0-9][a-z0-9-]{1,62}$")
_FLATPAK_ID = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+){2,}$")
_HOSTNAME_PATTERN = re.compile(r"^(?:\*\.)?[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")

MINIMUM_STORAGE_QUOTA_MB = 64
MAXIMUM_SESSION_IDLE_SECONDS = 7200


class KioskError(ValueError):
    """Raised when a restricted profile is malformed or would weaken security."""


@dataclass(frozen=True)
class KioskProfile:
    profileId: str
    mode: str
    fixedApplication: str | None
    networkAllowlist: tuple[str, ...]
    localStorageQuotaMb: int
    automaticRecovery: bool
    administratorExitEnabled: bool
    sessionIdleResetSeconds: int
    restrictions: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "profileId": self.profileId,
            "mode": self.mode,
            "fixedApplication": self.fixedApplication,
            "networkAllowlist": list(self.networkAllowlist),
            "localStorageQuotaMb": self.localStorageQuotaMb,
            "automaticRecovery": self.automaticRecovery,
            "administratorExitEnabled": self.administratorExitEnabled,
            "sessionIdleResetSeconds": self.sessionIdleResetSeconds,
            "restrictions": dict(self.restrictions),
        }


def parse_kiosk_profile(record: Mapping[str, Any]) -> KioskProfile:
    """Validate a kiosk or dedicated-purpose profile."""
    if not isinstance(record, Mapping):
        raise KioskError("profile must be a mapping")

    allowed = {
        "schemaVersion", "profileId", "mode", "fixedApplication", "networkAllowlist",
        "localStorageQuotaMb", "automaticRecovery", "administratorExitEnabled",
        "sessionIdleResetSeconds", "restrictions",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise KioskError("unknown kiosk profile fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise KioskError("unsupported kiosk profile schemaVersion")

    profile_id = record.get("profileId")
    if not isinstance(profile_id, str) or not _PROFILE_ID.match(profile_id):
        raise KioskError("profileId must match ksk-<slug>")

    mode = record.get("mode")
    if mode not in KIOSK_MODES:
        raise KioskError(f"mode {mode!r} is not a recognised kiosk mode")

    fixed_application = record.get("fixedApplication")
    if mode == "single-application":
        if not isinstance(fixed_application, str) or not _FLATPAK_ID.match(fixed_application):
            raise KioskError("single-application mode requires a fixedApplication reverse-DNS id")
    elif fixed_application is not None:
        raise KioskError("fixedApplication applies only to single-application mode")

    allowlist = record.get("networkAllowlist", [])
    if not isinstance(allowlist, list):
        raise KioskError("networkAllowlist must be a list")
    for entry in allowlist:
        if not isinstance(entry, str) or not _HOSTNAME_PATTERN.match(entry):
            raise KioskError(f"networkAllowlist entry {entry!r} is not a valid host pattern")

    quota = record.get("localStorageQuotaMb", MINIMUM_STORAGE_QUOTA_MB)
    if not isinstance(quota, int) or isinstance(quota, bool) or quota < MINIMUM_STORAGE_QUOTA_MB:
        raise KioskError(f"localStorageQuotaMb must be at least {MINIMUM_STORAGE_QUOTA_MB}")

    automatic_recovery = record.get("automaticRecovery", True)
    administrator_exit = record.get("administratorExitEnabled", True)
    for name, value in (("automaticRecovery", automatic_recovery), ("administratorExitEnabled", administrator_exit)):
        if not isinstance(value, bool):
            raise KioskError(f"{name} must be a boolean")
    if administrator_exit is False:
        raise KioskError(
            "administratorExitEnabled cannot be false; a local administrator must always be able to "
            "leave kiosk mode on the physical console"
        )

    idle = record.get("sessionIdleResetSeconds", 300)
    if not isinstance(idle, int) or isinstance(idle, bool) or not 30 <= idle <= MAXIMUM_SESSION_IDLE_SECONDS:
        raise KioskError(f"sessionIdleResetSeconds must be between 30 and {MAXIMUM_SESSION_IDLE_SECONDS}")

    restrictions = record.get("restrictions", {})
    if not isinstance(restrictions, Mapping):
        raise KioskError("restrictions must be an object")
    protected = sorted(set(restrictions) & PROTECTED_SETTINGS)
    if protected:
        raise KioskError(
            "kiosk mode cannot alter security protections: " + ", ".join(protected)
        )
    unknown = sorted(set(restrictions) - RESTRICTABLE_SETTINGS)
    if unknown:
        raise KioskError("unknown restriction keys: " + ", ".join(unknown))

    return KioskProfile(
        profileId=profile_id,
        mode=mode,
        fixedApplication=fixed_application,
        networkAllowlist=tuple(allowlist),
        localStorageQuotaMb=quota,
        automaticRecovery=automatic_recovery,
        administratorExitEnabled=True,
        sessionIdleResetSeconds=idle,
        restrictions=dict(restrictions),
    )


@dataclass(frozen=True)
class SharedDevicePolicy:
    sessionType: str
    cleanupOnLogout: bool
    storageQuotaMb: int
    shareLocalModelWeights: bool
    shareBunnyMemory: bool
    organisationApplications: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessionType": self.sessionType,
            "cleanupOnLogout": self.cleanupOnLogout,
            "storageQuotaMb": self.storageQuotaMb,
            "shareLocalModelWeights": self.shareLocalModelWeights,
            "shareBunnyMemory": self.shareBunnyMemory,
            "organisationApplications": list(self.organisationApplications),
        }


def parse_shared_device_policy(record: Mapping[str, Any]) -> SharedDevicePolicy:
    """Validate a shared laboratory device policy.

    ``shareBunnyMemory`` defaults to ``False`` and setting it to ``True`` is
    refused: Bunny memory is per-user, and a shared laboratory device is exactly
    the situation where cross-user memory exposure would be most harmful.
    """
    if not isinstance(record, Mapping):
        raise KioskError("shared device policy must be a mapping")

    allowed = {
        "schemaVersion", "sessionType", "cleanupOnLogout", "storageQuotaMb",
        "shareLocalModelWeights", "shareBunnyMemory", "organisationApplications",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise KioskError("unknown shared device fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise KioskError("unsupported shared device schemaVersion")

    session_type = record.get("sessionType")
    if session_type not in SESSION_TYPES:
        raise KioskError(f"sessionType {session_type!r} is not recognised")

    cleanup = record.get("cleanupOnLogout", session_type == "ephemeral")
    if not isinstance(cleanup, bool):
        raise KioskError("cleanupOnLogout must be a boolean")
    if session_type == "ephemeral" and cleanup is False:
        raise KioskError("an ephemeral session must clean up local user data on logout")

    quota = record.get("storageQuotaMb", 1024)
    if not isinstance(quota, int) or isinstance(quota, bool) or quota < MINIMUM_STORAGE_QUOTA_MB:
        raise KioskError(f"storageQuotaMb must be at least {MINIMUM_STORAGE_QUOTA_MB}")

    share_weights = record.get("shareLocalModelWeights", False)
    if not isinstance(share_weights, bool):
        raise KioskError("shareLocalModelWeights must be a boolean")

    share_memory = record.get("shareBunnyMemory", False)
    if share_memory is not False:
        raise KioskError(
            "shareBunnyMemory must be false; Bunny memory is never shared between users on a shared device"
        )

    applications = record.get("organisationApplications", [])
    if not isinstance(applications, list) or any(not isinstance(item, str) or not item for item in applications):
        raise KioskError("organisationApplications must be a list of non-empty strings")

    return SharedDevicePolicy(
        sessionType=session_type,
        cleanupOnLogout=cleanup,
        storageQuotaMb=quota,
        shareLocalModelWeights=share_weights,
        shareBunnyMemory=False,
        organisationApplications=tuple(applications),
    )

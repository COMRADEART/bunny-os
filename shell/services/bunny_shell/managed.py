# SPDX-License-Identifier: GPL-3.0-or-later
"""Organisation-managed settings overlay.

The overlay is written by the privileged broker (``policy_backend.apply_policy``)
after the policy agent verifies a signed bundle. It is root-owned and
world-readable; a user process only ever reads it.

It deliberately does not use ``JsonStore``. ``assert_private_file`` refuses a
file owned by another uid, which is correct for per-user state and exactly wrong
here: this file *must* be owned by root and not by the reading user.

Two rules keep an organisation inside its boundary:

* ``MANAGEABLE_SETTINGS`` is an allowlist, not a blocklist. A key that is not
  listed cannot be managed even if the overlay names it.
* A value that fails the setting's own validator is discarded rather than
  applied. A malformed organisation policy must not brick a desktop, but it
  must also never take effect silently, so it is reported in ``rejected``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MANAGED_PATH = Path("/etc/bunny-os/managed-settings.json")

#: Environment override, used by tests and by a non-root development session.
MANAGED_PATH_ENV = "BUNNY_MANAGED_SETTINGS"

MAX_OVERLAY_BYTES = 256 * 1024

#: Settings an organisation policy may lock. Anything absent here is refused
#: even when the overlay names it.
#:
#: ``telemetryEnabled`` is deliberately excluded: the schema pins it to false
#: and no organisation may turn telemetry on. ``theme``, ``textScalePercent``
#: and the accessibility settings are excluded because an organisation has no
#: legitimate need to take a user's accessibility controls away.
MANAGEABLE_SETTINGS = frozenset({
    "localOnlyMode",
    "offlineMode",
    "cloudFailoverPolicy",
    "defaultProviderAlias",
    "defaultModel",
    "pluginNetworkDefault",
    "diagnosticsPolicy",
    "unattendedJobs",
    "checkpointRetentionDays",
    "approvedSearchLocations",
    "clipboardHistory",
    "launchBunnyAtLogin",
})

#: Never manageable, listed by name so the refusal is visible in review rather
#: than implied by absence from the allowlist above.
NEVER_MANAGEABLE_SETTINGS = frozenset({
    "telemetryEnabled",
    "reducedMotion",
    "reducedTransparency",
    "theme",
    "textScalePercent",
    "memoryEnabled",
})


@dataclass(frozen=True)
class ManagedSetting:
    value: Any
    policyId: str
    version: int


@dataclass
class ManagedOverlay:
    organisationId: str | None = None
    updatedAt: str | None = None
    settings: dict[str, ManagedSetting] = field(default_factory=dict)
    osPolicy: dict[str, Any] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.organisationId is not None or bool(self.settings)

    def is_locked(self, key: str) -> bool:
        return key in self.settings

    def as_dict(self) -> dict[str, Any]:
        return {
            "organisationId": self.organisationId,
            "updatedAt": self.updatedAt,
            "lockedSettings": sorted(self.settings),
            "osPolicy": sorted(self.osPolicy),
            "rejected": list(self.rejected),
        }


def managed_path() -> Path:
    override = os.environ.get(MANAGED_PATH_ENV)
    return Path(override) if override else DEFAULT_MANAGED_PATH


def load_overlay(path: Path | None = None, *, validators: dict[str, Any] | None = None) -> ManagedOverlay:
    """Read and validate the managed overlay.

    Any failure to read or parse yields an empty overlay: an unreadable
    organisation policy leaves the user in control rather than locking them out
    of their own machine.
    """
    target = path or managed_path()
    overlay = ManagedOverlay()
    try:
        if target.is_symlink():
            overlay.rejected.append("overlay path is a symlink")
            return overlay
        raw = target.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return overlay
    except OSError:
        overlay.rejected.append("overlay is unreadable")
        return overlay

    if len(raw) > MAX_OVERLAY_BYTES:
        overlay.rejected.append("overlay exceeds the size limit")
        return overlay
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        overlay.rejected.append("overlay is not valid JSON")
        return overlay
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        overlay.rejected.append("overlay schema version is unsupported")
        return overlay

    organisation = document.get("organisationId")
    overlay.organisationId = organisation if isinstance(organisation, str) else None
    updated = document.get("updatedAt")
    overlay.updatedAt = updated if isinstance(updated, str) else None
    os_policy = document.get("osPolicy")
    overlay.osPolicy = dict(os_policy) if isinstance(os_policy, dict) else {}

    entries = document.get("settings")
    if not isinstance(entries, dict):
        return overlay

    from .settings import DEFINITIONS

    checks = validators or {key: meta["validate"] for key, meta in DEFINITIONS.items()}

    for key in sorted(entries):
        entry = entries[key]
        if key in NEVER_MANAGEABLE_SETTINGS:
            overlay.rejected.append(f"{key}: this setting can never be managed by an organisation")
            continue
        if key not in MANAGEABLE_SETTINGS:
            overlay.rejected.append(f"{key}: not an organisation-manageable setting")
            continue
        if key not in checks:
            overlay.rejected.append(f"{key}: unknown setting")
            continue
        if not isinstance(entry, dict) or "value" not in entry:
            overlay.rejected.append(f"{key}: malformed overlay entry")
            continue
        policy_id = entry.get("policyId")
        version = entry.get("version")
        if not isinstance(policy_id, str) or not policy_id:
            overlay.rejected.append(f"{key}: overlay entry has no policyId")
            continue
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            overlay.rejected.append(f"{key}: overlay entry has no valid version")
            continue
        try:
            value = checks[key](entry["value"])
        except ValueError as error:
            overlay.rejected.append(f"{key}: organisation value rejected ({error})")
            continue
        overlay.settings[key] = ManagedSetting(value=value, policyId=policy_id, version=version)

    return overlay

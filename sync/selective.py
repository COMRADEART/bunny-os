"""Selective sync and syncable domains.

Default posture: nothing syncs. Enabling sync enables an *account*, not a data
flow; each domain is then chosen individually. Domains marked sensitive stay
local-only until the user selects them explicitly, and selecting them requires an
acknowledgement rather than a toggle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SyncDomain:
    domain: str
    description: str
    sensitive: bool
    defaultEnabled: bool = False
    requiresAcknowledgement: bool = False


#: Every syncable domain. ``defaultEnabled`` is false for all of them.
SYNC_DOMAINS: tuple[SyncDomain, ...] = (
    SyncDomain("preferences", "Bunny and desktop preferences", sensitive=False),
    SyncDomain("bookmarks", "Saved links and references", sensitive=False),
    SyncDomain("workspaces", "Workspace metadata, not workspace file contents", sensitive=False),
    SyncDomain("plans", "Saved plans", sensitive=False),
    SyncDomain("tasks", "Task lists and completion state", sensitive=False),
    SyncDomain("configuration", "Selected application configuration", sensitive=False),
    SyncDomain(
        "approved-memories",
        "Memories you have explicitly approved for sync",
        sensitive=True,
        requiresAcknowledgement=True,
    ),
    SyncDomain(
        "conversation-metadata",
        "Conversation titles and timestamps, not message contents",
        sensitive=True,
        requiresAcknowledgement=True,
    ),
    SyncDomain(
        "approved-files",
        "Files in folders you select",
        sensitive=True,
        requiresAcknowledgement=True,
    ),
    SyncDomain(
        "encrypted-backups",
        "Full encrypted device backups",
        sensitive=True,
        requiresAcknowledgement=True,
    ),
)

_DOMAINS_BY_NAME = {domain.domain: domain for domain in SYNC_DOMAINS}

SENSITIVE_DOMAINS = frozenset(domain.domain for domain in SYNC_DOMAINS if domain.sensitive)


class SelectiveSyncError(ValueError):
    """Raised when a sync selection is invalid or under-acknowledged."""


@dataclass(frozen=True)
class SyncSelection:
    enabledDomains: tuple[str, ...]
    devices: tuple[str, ...]
    acknowledgedSensitiveDomains: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabledDomains": list(self.enabledDomains),
            "devices": list(self.devices),
            "acknowledgedSensitiveDomains": list(self.acknowledgedSensitiveDomains),
        }


def default_selection() -> dict[str, Any]:
    """Return the default sync selection: nothing enabled."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "enabledDomains": [],
        "devices": [],
        "acknowledgedSensitiveDomains": [],
        "note": "Sync is enabled per domain. Nothing synchronises until a domain is chosen.",
    }


def parse_selection(record: Mapping[str, Any]) -> SyncSelection:
    """Validate a sync selection.

    A sensitive domain may only be enabled when it also appears in
    ``acknowledgedSensitiveDomains``, so enabling memory sync cannot happen as a
    side effect of enabling something else.
    """
    if not isinstance(record, Mapping):
        raise SelectiveSyncError("selection must be a mapping")

    allowed = {"schemaVersion", "enabledDomains", "devices", "acknowledgedSensitiveDomains"}
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise SelectiveSyncError("unknown selection fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise SelectiveSyncError("unsupported selection schemaVersion")

    enabled = record.get("enabledDomains", [])
    if not isinstance(enabled, list):
        raise SelectiveSyncError("enabledDomains must be a list")
    unknown = sorted(set(map(str, enabled)) - set(_DOMAINS_BY_NAME))
    if unknown:
        raise SelectiveSyncError("unknown sync domains: " + ", ".join(unknown))

    devices = record.get("devices", [])
    if not isinstance(devices, list) or any(not isinstance(item, str) or not item for item in devices):
        raise SelectiveSyncError("devices must be a list of device key ids")

    acknowledged = record.get("acknowledgedSensitiveDomains", [])
    if not isinstance(acknowledged, list):
        raise SelectiveSyncError("acknowledgedSensitiveDomains must be a list")
    unknown_ack = sorted(set(map(str, acknowledged)) - SENSITIVE_DOMAINS)
    if unknown_ack:
        raise SelectiveSyncError(
            "acknowledgedSensitiveDomains may only name sensitive domains: " + ", ".join(unknown_ack)
        )

    missing_ack = sorted(set(map(str, enabled)) & SENSITIVE_DOMAINS - set(map(str, acknowledged)))
    if missing_ack:
        raise SelectiveSyncError(
            "these sensitive domains require explicit acknowledgement before they sync: "
            + ", ".join(missing_ack)
        )

    if enabled and not devices:
        raise SelectiveSyncError("at least one device must be selected before any domain can sync")

    return SyncSelection(
        enabledDomains=tuple(sorted(set(map(str, enabled)))),
        devices=tuple(sorted(set(map(str, devices)))),
        acknowledgedSensitiveDomains=tuple(sorted(set(map(str, acknowledged)))),
    )


def describe_domains() -> list[dict[str, Any]]:
    """Return the domain catalogue for the sync settings surface."""
    return [
        {
            "domain": domain.domain,
            "description": domain.description,
            "sensitive": domain.sensitive,
            "defaultEnabled": domain.defaultEnabled,
            "requiresAcknowledgement": domain.requiresAcknowledgement,
        }
        for domain in SYNC_DOMAINS
    ]


def local_only_domains(selection: Mapping[str, Any]) -> list[str]:
    """Return domains that remain local-only under this selection."""
    parsed = parse_selection(selection)
    return sorted(set(_DOMAINS_BY_NAME) - set(parsed.enabledDomains))

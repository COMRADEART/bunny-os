"""Backup, restore, and device-to-device migration.

The rule that shapes the design: a restore never overwrites the destination
silently. Every restore produces a *preview* first, and applying a restore requires
an explicit acknowledgement that names what will be replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

TRANSFER_METHODS = (
    "encrypted-backup-file",
    "local-external-drive",
    "direct-device-transfer",
    "sync-assisted-transfer",
)

RESTORE_MODES = ("preview", "selective", "full")

CONFLICT_ACTIONS = ("keep-destination", "keep-source", "keep-both", "review")

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DEVICE_KEY_ID = re.compile(r"^dev-[0-9a-f]{16}$")


class MigrationError(ValueError):
    """Raised when a backup or restore request is unsafe or malformed."""


@dataclass(frozen=True)
class RestorePreview:
    method: str
    mode: str
    compatible: bool
    collections: tuple[str, ...]
    wouldReplace: tuple[str, ...]
    wouldAdd: tuple[str, ...]
    conflicts: tuple[str, ...]
    blockers: tuple[str, ...]
    acknowledgementRequired: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "mode": self.mode,
            "compatible": self.compatible,
            "collections": list(self.collections),
            "wouldReplace": list(self.wouldReplace),
            "wouldAdd": list(self.wouldAdd),
            "conflicts": list(self.conflicts),
            "blockers": list(self.blockers),
            "acknowledgementRequired": self.acknowledgementRequired,
        }


def _check_compatibility(source_version: str, destination_version: str, blockers: list[str]) -> bool:
    for name, value in (("sourceOsVersion", source_version), ("destinationOsVersion", destination_version)):
        if not isinstance(value, str) or not _VERSION.match(value):
            raise MigrationError(f"{name} must be a semantic version")
    source_major, source_minor, _ = (int(part) for part in source_version.split("."))
    dest_major, dest_minor, _ = (int(part) for part in destination_version.split("."))
    if dest_major < source_major or (dest_major == source_major and dest_minor < source_minor):
        blockers.append(
            f"the destination runs {destination_version} but the backup came from {source_version}; "
            "restoring to an older version is refused because migrations are not reversible"
        )
        return False
    if dest_major > source_major:
        blockers.append(
            f"a major version change from {source_version} to {destination_version} requires a "
            "reviewed migration route; no automatic route exists"
        )
        return False
    return True


def preview_restore(request: Mapping[str, Any]) -> RestorePreview:
    """Produce a restore preview. This never writes anything."""
    if not isinstance(request, Mapping):
        raise MigrationError("request must be a mapping")

    allowed = {
        "schemaVersion", "method", "mode", "sourceOsVersion", "destinationOsVersion",
        "sourceCollections", "destinationCollections", "sourceDeviceKeyId", "backupSignatureVerified",
    }
    extra = sorted(set(request) - allowed)
    if extra:
        raise MigrationError("unknown migration fields: " + ", ".join(extra))
    missing = sorted(allowed - {"sourceDeviceKeyId"} - set(request))
    if missing:
        raise MigrationError("missing migration fields: " + ", ".join(missing))
    if request["schemaVersion"] != SCHEMA_VERSION:
        raise MigrationError("unsupported migration schemaVersion")

    method = request["method"]
    if method not in TRANSFER_METHODS:
        raise MigrationError(f"method {method!r} is not a recognised transfer method")

    mode = request["mode"]
    if mode not in RESTORE_MODES:
        raise MigrationError(f"mode {mode!r} is not a recognised restore mode")

    source = request["sourceCollections"]
    destination = request["destinationCollections"]
    for name, value in (("sourceCollections", source), ("destinationCollections", destination)):
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise MigrationError(f"{name} must be a list of non-empty strings")

    blockers: list[str] = []

    if request.get("backupSignatureVerified") is not True:
        blockers.append(
            "the backup's integrity was not verified; an unverified backup is never restored"
        )

    if method == "direct-device-transfer":
        device = request.get("sourceDeviceKeyId")
        if not isinstance(device, str) or not _DEVICE_KEY_ID.match(device):
            blockers.append("direct device transfer requires an authenticated source device key id")

    compatible = _check_compatibility(request["sourceOsVersion"], request["destinationOsVersion"], blockers)

    source_set = set(source)
    destination_set = set(destination)
    would_replace = tuple(sorted(source_set & destination_set))
    would_add = tuple(sorted(source_set - destination_set))

    conflicts = tuple(
        f"{name}: exists on both devices and will be resolved by your chosen action"
        for name in would_replace
    )

    return RestorePreview(
        method=method,
        mode=mode,
        compatible=compatible and not blockers,
        collections=tuple(sorted(source_set)),
        wouldReplace=would_replace,
        wouldAdd=would_add,
        conflicts=conflicts,
        blockers=tuple(blockers),
        acknowledgementRequired=bool(would_replace),
    )


def apply_restore(preview: RestorePreview, *, acknowledgedReplacements: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Authorise a restore only when every replacement was acknowledged."""
    if preview.blockers:
        raise MigrationError(
            "restore refused; unresolved blockers: " + "; ".join(preview.blockers)
        )
    if preview.mode == "preview":
        raise MigrationError("a preview cannot be applied; choose selective or full restore")

    acknowledged = set(acknowledgedReplacements or ())
    unacknowledged = sorted(set(preview.wouldReplace) - acknowledged)
    if unacknowledged:
        raise MigrationError(
            "these collections would be replaced but were not acknowledged: " + ", ".join(unacknowledged)
            + ". A restore never overwrites the destination silently."
        )

    return {
        "applied": True,
        "mode": preview.mode,
        "replaced": sorted(preview.wouldReplace),
        "added": sorted(preview.wouldAdd),
        "conflictAction": "keep-both",
        "note": "Replaced collections are retained as conflict copies until you confirm the result.",
    }


def describe_methods() -> list[dict[str, str]]:
    """Return the supported transfer methods for documentation."""
    return [
        {"method": "encrypted-backup-file", "requires": "the backup passphrase or recovery secret"},
        {"method": "local-external-drive", "requires": "physical access and the backup passphrase"},
        {"method": "direct-device-transfer", "requires": "both devices present and an authenticated pairing"},
        {"method": "sync-assisted-transfer", "requires": "an account and the collections already selected for sync"},
    ]

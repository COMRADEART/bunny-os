"""Deletion semantics.

Six distinct scopes exist because "delete" means six different things and
conflating them is how a product ends up claiming data is gone when it is not.

Retention delays are reported, not hidden. Bunny OS does not claim instantaneous
physical deletion from every backup and disaster-recovery copy, because that claim
cannot be verified from the client side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 1

DELETION_SCOPES = (
    "local-deletion",
    "all-synced-devices",
    "server-encrypted-object-deletion",
    "account-deletion",
    "organisation-data-removal",
    "device-decommission",
)

#: Maximum time a deleted encrypted object may persist in backups and
#: disaster-recovery copies. Stated as a bound, not as "immediately".
BACKUP_RETENTION_DAYS = 35
DISASTER_RECOVERY_RETENTION_DAYS = 35
TOMBSTONE_RETENTION_DAYS = 180


class DeletionError(ValueError):
    """Raised when a deletion request is malformed or over-claims its effect."""


@dataclass(frozen=True)
class DeletionEffect:
    scope: str
    removesLocalPlaintext: bool
    removesFromOtherDevices: bool
    removesServerCiphertext: bool
    tombstonePropagated: bool
    maximumBackupPersistenceDays: int
    irreversible: bool
    statement: str
    caveats: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "removesLocalPlaintext": self.removesLocalPlaintext,
            "removesFromOtherDevices": self.removesFromOtherDevices,
            "removesServerCiphertext": self.removesServerCiphertext,
            "tombstonePropagated": self.tombstonePropagated,
            "maximumBackupPersistenceDays": self.maximumBackupPersistenceDays,
            "irreversible": self.irreversible,
            "statement": self.statement,
            "caveats": list(self.caveats),
        }


_EFFECTS: dict[str, DeletionEffect] = {
    "local-deletion": DeletionEffect(
        scope="local-deletion",
        removesLocalPlaintext=True,
        removesFromOtherDevices=False,
        removesServerCiphertext=False,
        tombstonePropagated=False,
        maximumBackupPersistenceDays=0,
        irreversible=False,
        statement="Removed from this device only.",
        caveats=(
            "Other paired devices keep their copy until you delete across devices.",
            "The encrypted object remains on the server.",
        ),
    ),
    "all-synced-devices": DeletionEffect(
        scope="all-synced-devices",
        removesLocalPlaintext=True,
        removesFromOtherDevices=True,
        removesServerCiphertext=False,
        tombstonePropagated=True,
        maximumBackupPersistenceDays=0,
        irreversible=False,
        statement="Removed from every device that is online, and from offline devices when they next sync.",
        caveats=(
            "A tombstone is retained so the deletion is not undone by a device that was offline.",
            f"Tombstones are kept for up to {TOMBSTONE_RETENTION_DAYS} days.",
            "The encrypted object remains on the server until server deletion is requested.",
        ),
    ),
    "server-encrypted-object-deletion": DeletionEffect(
        scope="server-encrypted-object-deletion",
        removesLocalPlaintext=False,
        removesFromOtherDevices=False,
        removesServerCiphertext=True,
        tombstonePropagated=True,
        maximumBackupPersistenceDays=BACKUP_RETENTION_DAYS,
        irreversible=False,
        statement="The encrypted object is deleted from live server storage.",
        caveats=(
            f"Copies may persist in backups and disaster-recovery systems for up to "
            f"{BACKUP_RETENTION_DAYS} days before expiry.",
            "Those copies remain encrypted and the service cannot read them.",
            "Instantaneous physical deletion from all backups is not claimed.",
        ),
    ),
    "account-deletion": DeletionEffect(
        scope="account-deletion",
        removesLocalPlaintext=False,
        removesFromOtherDevices=False,
        removesServerCiphertext=True,
        tombstonePropagated=False,
        maximumBackupPersistenceDays=max(BACKUP_RETENTION_DAYS, DISASTER_RECOVERY_RETENTION_DAYS),
        irreversible=True,
        statement="The account, its device registry, and all its encrypted objects are deleted.",
        caveats=(
            "Local data on your devices is not deleted; delete it separately if you want it gone.",
            f"Backup and disaster-recovery copies expire within "
            f"{max(BACKUP_RETENTION_DAYS, DISASTER_RECOVERY_RETENTION_DAYS)} days.",
            "Deleting the account does not delete your keys from your devices.",
            "This cannot be undone; without the account there is no server-side copy to restore.",
        ),
    ),
    "organisation-data-removal": DeletionEffect(
        scope="organisation-data-removal",
        removesLocalPlaintext=True,
        removesFromOtherDevices=False,
        removesServerCiphertext=False,
        tombstonePropagated=False,
        maximumBackupPersistenceDays=0,
        irreversible=False,
        statement="Organisation profiles, managed configuration, and organisation credentials are removed.",
        caveats=(
            "Personal accounts, personal files, and private Bunny memories are not touched.",
            "Audit records of the removal are retained by the organisation.",
        ),
    ),
    "device-decommission": DeletionEffect(
        scope="device-decommission",
        removesLocalPlaintext=True,
        removesFromOtherDevices=False,
        removesServerCiphertext=False,
        tombstonePropagated=False,
        maximumBackupPersistenceDays=0,
        irreversible=True,
        statement="The device is removed from the account and its keys are revoked and rotated.",
        caveats=(
            "Objects the device already downloaded cannot be retracted.",
            "The device can no longer decrypt objects uploaded after revocation.",
        ),
    ),
}


def describe_deletion(scope: str) -> DeletionEffect:
    """Return the exact effect of one deletion scope."""
    effect = _EFFECTS.get(scope)
    if effect is None:
        raise DeletionError(f"unknown deletion scope {scope!r}; scopes are {', '.join(DELETION_SCOPES)}")
    return effect


def describe_all() -> list[dict[str, Any]]:
    """Return every deletion scope for documentation and the privacy review."""
    return [_EFFECTS[scope].as_dict() for scope in DELETION_SCOPES]


def assert_no_overclaim(scope: str, statement: str) -> None:
    """Refuse a user-facing statement that overstates a deletion's reach."""
    effect = describe_deletion(scope)
    lowered = statement.casefold()
    for phrase in ("permanently erased everywhere", "immediately deleted from all backups",
                   "completely gone", "unrecoverable everywhere", "wiped from all systems instantly"):
        if phrase in lowered:
            raise DeletionError(
                f"the phrase {phrase!r} overstates {scope}: backup copies may persist for up to "
                f"{effect.maximumBackupPersistenceDays} days"
            )
    if not effect.removesServerCiphertext and "deleted from the server" in lowered:
        raise DeletionError(
            f"{scope} does not delete the server copy; do not state that it does"
        )

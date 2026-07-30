"""Sync key hierarchy, rotation, and device revocation.

Hierarchy::

    User recovery secret
        |
    User root key
        |
        +-- Device wrapping keys        (one per paired device)
        +-- Memory collection key
        +-- Workspace collection key
        +-- Backup collection key
        +-- File collection keys        (one per file collection)

The root key is derived from the recovery secret and never leaves the device in
plaintext. Collection keys are wrapped to each device's wrapping key, so adding a
device is a rewrap and removing one is a rotate-then-rewrap.

This module computes *plans* and validates *structure*. It performs no key
derivation: the labels below are the specification a reviewed implementation must
use, not an implementation. See ``docs/SYNC_CRYPTOGRAPHY.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1

#: Key derivation is specified as HKDF-SHA256 with these exact info labels.
#: Distinct labels per purpose prevent a key from being valid in two contexts.
DERIVATION_LABELS = {
    "user-root-key": b"bunny-os/sync/v1/user-root-key",
    "device-wrapping-key": b"bunny-os/sync/v1/device-wrapping-key",
    "collection-key": b"bunny-os/sync/v1/collection-key",
    "object-key": b"bunny-os/sync/v1/object-key",
    "backup-key": b"bunny-os/sync/v1/backup-key",
}

KEY_ROLES = ("user-root-key", "device-wrapping-key", "collection-key", "object-key", "backup-key")

#: Collections with a dedicated key. ``file-collection`` is a family: each user
#: file collection receives its own key so revoking access to one does not
#: require rotating the others.
COLLECTION_KINDS = (
    "memory",
    "workspace",
    "backup",
    "file-collection",
    "preferences",
    "conversation-metadata",
    "bookmarks",
    "plans",
    "tasks",
    "configuration",
)

DEVICE_STATES = ("active", "revoked", "pending-pairing")

_DEVICE_KEY_ID = re.compile(r"^dev-[0-9a-f]{16}$")
_COLLECTION_ID = re.compile(r"^col-[a-z0-9][a-z0-9-]{1,62}$")
_COLLECTION_KEY_ID = re.compile(r"^ck-[0-9a-f]{16}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class KeyHierarchyError(ValueError):
    """Raised when a keyring record or key operation is invalid."""


@dataclass(frozen=True)
class DeviceRecord:
    deviceKeyId: str
    displayName: str
    state: str
    addedAt: str
    revokedAt: str | None
    keyStorage: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "deviceKeyId": self.deviceKeyId,
            "displayName": self.displayName,
            "state": self.state,
            "addedAt": self.addedAt,
            "revokedAt": self.revokedAt,
            "keyStorage": self.keyStorage,
        }


@dataclass(frozen=True)
class CollectionKeyRecord:
    collectionId: str
    kind: str
    keyId: str
    generation: int
    wrappedForDevices: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "collectionId": self.collectionId,
            "kind": self.kind,
            "keyId": self.keyId,
            "generation": self.generation,
            "wrappedForDevices": list(self.wrappedForDevices),
        }


def parse_device(record: Mapping[str, Any]) -> DeviceRecord:
    """Validate one paired-device record."""
    if not isinstance(record, Mapping):
        raise KeyHierarchyError("device record must be a mapping")
    allowed = {"deviceKeyId", "displayName", "state", "addedAt", "revokedAt", "keyStorage"}
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise KeyHierarchyError("unknown device fields: " + ", ".join(unexpected))

    key_id = record.get("deviceKeyId")
    if not isinstance(key_id, str) or not _DEVICE_KEY_ID.match(key_id):
        raise KeyHierarchyError("deviceKeyId must match dev-<16 hex>")

    display_name = record.get("displayName")
    if not isinstance(display_name, str) or not display_name or len(display_name) > 64:
        raise KeyHierarchyError("displayName must be a short non-empty string")

    state = record.get("state")
    if state not in DEVICE_STATES:
        raise KeyHierarchyError(f"device state {state!r} is not recognised")

    added_at = record.get("addedAt")
    if not isinstance(added_at, str) or not _RFC3339.match(added_at):
        raise KeyHierarchyError("addedAt must be an RFC 3339 timestamp")

    revoked_at = record.get("revokedAt")
    if state == "revoked":
        if not isinstance(revoked_at, str) or not _RFC3339.match(revoked_at):
            raise KeyHierarchyError("a revoked device must record revokedAt")
    elif revoked_at is not None:
        raise KeyHierarchyError("revokedAt is only valid for a revoked device")

    storage = record.get("keyStorage")
    if storage not in ("tpm-2.0", "software-protected"):
        raise KeyHierarchyError("keyStorage must be tpm-2.0 or software-protected")

    return DeviceRecord(
        deviceKeyId=key_id,
        displayName=display_name,
        state=state,
        addedAt=added_at,
        revokedAt=revoked_at,
        keyStorage=storage,
    )


def parse_collection_key(record: Mapping[str, Any], *, known_devices: Sequence[str] | None = None) -> CollectionKeyRecord:
    """Validate one collection key record."""
    if not isinstance(record, Mapping):
        raise KeyHierarchyError("collection key record must be a mapping")
    allowed = {"collectionId", "kind", "keyId", "generation", "wrappedForDevices"}
    if set(record) != allowed:
        missing = sorted(allowed - set(record))
        extra = sorted(set(record) - allowed)
        raise KeyHierarchyError(f"collection key fields mismatch; missing={missing}, extra={extra}")

    collection_id = record["collectionId"]
    if not isinstance(collection_id, str) or not _COLLECTION_ID.match(collection_id):
        raise KeyHierarchyError("collectionId must match col-<slug>")

    kind = record["kind"]
    if kind not in COLLECTION_KINDS:
        raise KeyHierarchyError(f"collection kind {kind!r} is not recognised")

    key_id = record["keyId"]
    if not isinstance(key_id, str) or not _COLLECTION_KEY_ID.match(key_id):
        raise KeyHierarchyError("collection keyId must match ck-<16 hex>")

    generation = record["generation"]
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise KeyHierarchyError("generation must be a positive whole number")

    wrapped = record["wrappedForDevices"]
    if not isinstance(wrapped, list) or not wrapped:
        raise KeyHierarchyError("a collection key must be wrapped for at least one device")
    for entry in wrapped:
        if not isinstance(entry, str) or not _DEVICE_KEY_ID.match(entry):
            raise KeyHierarchyError(f"wrappedForDevices entry {entry!r} is not a device key id")
    if len(set(wrapped)) != len(wrapped):
        raise KeyHierarchyError("wrappedForDevices contains duplicates")
    if known_devices is not None:
        unknown = sorted(set(wrapped) - set(known_devices))
        if unknown:
            raise KeyHierarchyError("collection key is wrapped for unknown devices: " + ", ".join(unknown))

    return CollectionKeyRecord(
        collectionId=collection_id,
        kind=kind,
        keyId=key_id,
        generation=generation,
        wrappedForDevices=tuple(wrapped),
    )


def parse_keyring(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a whole keyring: devices plus collection keys.

    Refuses a keyring that still wraps a collection key for a revoked device,
    which is the concrete meaning of "device revocation rotates relevant access".
    """
    if not isinstance(record, Mapping):
        raise KeyHierarchyError("keyring must be a mapping")
    allowed = {"schemaVersion", "devices", "collectionKeys", "rootKeyGeneration"}
    if set(record) != allowed:
        missing = sorted(allowed - set(record))
        extra = sorted(set(record) - allowed)
        raise KeyHierarchyError(f"keyring fields mismatch; missing={missing}, extra={extra}")
    if record["schemaVersion"] != SCHEMA_VERSION:
        raise KeyHierarchyError("unsupported keyring schemaVersion")

    root_generation = record["rootKeyGeneration"]
    if not isinstance(root_generation, int) or isinstance(root_generation, bool) or root_generation < 1:
        raise KeyHierarchyError("rootKeyGeneration must be a positive whole number")

    devices_raw = record["devices"]
    if not isinstance(devices_raw, list) or not devices_raw:
        raise KeyHierarchyError("a keyring must contain at least one device")
    devices = [parse_device(item) for item in devices_raw]
    if len({device.deviceKeyId for device in devices}) != len(devices):
        raise KeyHierarchyError("duplicate deviceKeyId in keyring")

    active = [device.deviceKeyId for device in devices if device.state == "active"]
    revoked = {device.deviceKeyId for device in devices if device.state == "revoked"}
    if not active:
        raise KeyHierarchyError("a keyring must retain at least one active device")

    known = [device.deviceKeyId for device in devices]
    keys_raw = record["collectionKeys"]
    if not isinstance(keys_raw, list):
        raise KeyHierarchyError("collectionKeys must be a list")
    keys = [parse_collection_key(item, known_devices=known) for item in keys_raw]

    for key in keys:
        still_wrapped = sorted(set(key.wrappedForDevices) & revoked)
        if still_wrapped:
            raise KeyHierarchyError(
                f"collection {key.collectionId} is still wrapped for revoked devices "
                f"{', '.join(still_wrapped)}; revocation must rotate and rewrap the key"
            )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "rootKeyGeneration": root_generation,
        "devices": [device.as_dict() for device in devices],
        "collectionKeys": [key.as_dict() for key in keys],
        "activeDeviceCount": len(active),
        "revokedDeviceCount": len(revoked),
    }


@dataclass(frozen=True)
class KeyOperationPlan:
    operation: str
    rotateCollections: tuple[str, ...]
    rewrapForDevices: tuple[str, ...]
    rotateRootKey: bool
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "rotateCollections": list(self.rotateCollections),
            "rewrapForDevices": list(self.rewrapForDevices),
            "rotateRootKey": self.rotateRootKey,
            "notes": list(self.notes),
        }


def plan_device_addition(keyring: Mapping[str, Any], device_key_id: str, *, collections: Iterable[str]) -> KeyOperationPlan:
    """Plan adding a device: rewrap selected collection keys, rotate nothing.

    Adding a device grants access going forward and, unavoidably, to already
    uploaded objects in the collections it is granted. That is stated rather than
    obscured.
    """
    parse_keyring(keyring)
    if not _DEVICE_KEY_ID.match(device_key_id):
        raise KeyHierarchyError("deviceKeyId must match dev-<16 hex>")
    selected = tuple(sorted(set(collections)))
    if not selected:
        raise KeyHierarchyError("device addition must name at least one collection to grant")
    return KeyOperationPlan(
        operation="add-device",
        rotateCollections=(),
        rewrapForDevices=(device_key_id,),
        rotateRootKey=False,
        notes=(
            "The new device can decrypt existing objects in the granted collections, "
            "because those objects are encrypted under the current collection keys.",
            "Collections not named here remain inaccessible to the new device.",
        ),
    )


def plan_device_revocation(
    keyring: Mapping[str, Any],
    device_key_id: str,
    *,
    suspected_compromise: bool = False,
) -> KeyOperationPlan:
    """Plan revoking a device.

    Every collection the device could read is rotated, and the new generation is
    rewrapped for the remaining active devices only. On suspected compromise the
    root key is rotated too, because a compromised device may have exfiltrated it.
    """
    parsed = parse_keyring(keyring)
    if not _DEVICE_KEY_ID.match(device_key_id):
        raise KeyHierarchyError("deviceKeyId must match dev-<16 hex>")

    devices = {item["deviceKeyId"]: item for item in parsed["devices"]}
    if device_key_id not in devices:
        raise KeyHierarchyError(f"device {device_key_id} is not in this keyring")
    if devices[device_key_id]["state"] == "revoked":
        raise KeyHierarchyError(f"device {device_key_id} is already revoked")

    remaining = tuple(
        sorted(
            item["deviceKeyId"] for item in parsed["devices"]
            if item["state"] == "active" and item["deviceKeyId"] != device_key_id
        )
    )
    if not remaining:
        raise KeyHierarchyError(
            "revoking this device would leave no active device; add another device or use account deletion"
        )

    affected = tuple(
        sorted(
            key["collectionId"] for key in parsed["collectionKeys"]
            if device_key_id in key["wrappedForDevices"]
        )
    )

    notes = [
        "Objects the revoked device already downloaded cannot be retracted; only future objects are protected.",
        "The revoked device is removed from the service device registry so it can no longer authenticate.",
    ]
    if suspected_compromise:
        notes.append("The user root key is rotated because a compromised device may hold a copy.")

    return KeyOperationPlan(
        operation="revoke-device",
        rotateCollections=affected,
        rewrapForDevices=remaining,
        rotateRootKey=suspected_compromise,
        notes=tuple(notes),
    )


def plan_collection_rotation(keyring: Mapping[str, Any], collection_id: str) -> KeyOperationPlan:
    """Plan a scheduled collection key rotation."""
    parsed = parse_keyring(keyring)
    match = next((key for key in parsed["collectionKeys"] if key["collectionId"] == collection_id), None)
    if match is None:
        raise KeyHierarchyError(f"collection {collection_id} is not in this keyring")
    active = tuple(sorted(item["deviceKeyId"] for item in parsed["devices"] if item["state"] == "active"))
    return KeyOperationPlan(
        operation="rotate-collection",
        rotateCollections=(collection_id,),
        rewrapForDevices=active,
        rotateRootKey=False,
        notes=(
            f"Generation advances from {match['generation']} to {match['generation'] + 1}.",
            "Existing objects remain readable under their original generation until re-encrypted.",
        ),
    )

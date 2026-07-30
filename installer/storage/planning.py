# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure partition-plan generation; this module never writes a disk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import DiskInfo, PartitionInfo
from .safety import assess_target, disk_identity


MIB = 1024**2
GIB = 1024**3
ESP_SIZE = 1024 * MIB
BOOT_SIZE = 2048 * MIB
MIN_ROOT = 30 * GIB
ALIGNMENT = 4 * MIB
SUPPORTED_FILESYSTEMS = frozenset({"ext4", "btrfs", "xfs", "vfat", "swap", "crypto_luks"})
SUPPORTED_MODES = frozenset({"erase_disk", "install_alongside", "replace_partition", "manual", "oem"})


@dataclass(frozen=True)
class PlannedPartition:
    action: str
    role: str
    startBytes: int
    sizeBytes: int
    filesystem: str
    mountPoint: str | None
    encrypt: bool = False
    preserve: bool = False
    sourcePartitionId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aligned(value: int) -> int:
    return value - (value % ALIGNMENT)


def _base_layout(available: int, *, encryption: bool, start: int = 0, reuse_esp: PartitionInfo | None = None) -> list[PlannedPartition]:
    cursor = _aligned(start + ALIGNMENT)
    layout: list[PlannedPartition] = []
    if reuse_esp is None:
        layout.append(PlannedPartition("create", "efi", cursor, ESP_SIZE, "vfat", "/boot/efi"))
        cursor += ESP_SIZE
    else:
        layout.append(PlannedPartition("reuse", "efi", 0, reuse_esp.sizeBytes, "vfat", "/boot/efi", preserve=True, sourcePartitionId=reuse_esp.id))
    cursor = _aligned(cursor + ALIGNMENT)
    layout.append(PlannedPartition("create", "boot", cursor, BOOT_SIZE, "ext4", "/boot"))
    cursor += BOOT_SIZE + ALIGNMENT
    root_size = _aligned(available - (cursor - start) - ALIGNMENT)
    if root_size < MIN_ROOT:
        raise ValueError("insufficient space for Bunny OS root deployment")
    layout.append(
        PlannedPartition(
            "create",
            "system",
            cursor,
            root_size,
            "crypto_luks" if encryption else "ext4",
            "/",
            encrypt=encryption,
        )
    )
    return layout


def automatic_plan(
    disk: DiskInfo,
    *,
    mode: str,
    encryption: bool,
    free_start_bytes: int | None = None,
    free_size_bytes: int | None = None,
) -> dict[str, Any]:
    if mode not in SUPPORTED_MODES:
        raise ValueError("unsupported installation mode")
    findings = assess_target(disk, mode=mode)
    blocking = [item for item in findings if item.blocks]
    if blocking:
        raise ValueError("unsafe target: " + ", ".join(item.code for item in blocking))
    if mode not in {"erase_disk", "install_alongside", "oem"}:
        raise ValueError("automatic planner supports erase, alongside, and OEM only")
    if mode in {"erase_disk", "oem"}:
        partitions = _base_layout(disk.sizeBytes, encryption=encryption)
    else:
        if free_start_bytes is None or free_size_bytes is None:
            raise ValueError("alongside mode requires verified unallocated space")
        esp = next((part for part in disk.partitions if (part.filesystem or "").lower() in {"vfat", "fat32"} and part.sizeBytes >= 100 * MIB), None)
        partitions = _base_layout(free_size_bytes, encryption=encryption, start=free_start_bytes, reuse_esp=esp)
    return {
        "schemaVersion": 1,
        "mode": mode,
        "targetDisk": {"id": disk.id, "devicePath": disk.devicePath, "expectedSizeBytes": disk.sizeBytes, "displayIdentity": disk_identity(disk)},
        "partitions": [item.to_dict() for item in partitions],
        "encryption": {"enabled": encryption, "type": "luks2" if encryption else "none", "recoveryKeyRequired": encryption},
        "boot": {"firmware": "uefi", "bootloader": "fedora-shim-grub", "preserveExistingEntries": True},
        "operationsAreReversibleAfterWrite": False,
        "warnings": [asdict(item) for item in findings],
    }


def validate_manual(partitions: Iterable[PlannedPartition]) -> tuple[str, ...]:
    items = tuple(partitions)
    errors: list[str] = []
    mounts = [item.mountPoint for item in items if item.mountPoint]
    for mount in mounts:
        if not mount.startswith("/") or ".." in mount.split("/"):
            errors.append(f"invalid mount point: {mount}")
    duplicates = sorted({mount for mount in mounts if mounts.count(mount) > 1})
    if duplicates:
        errors.append("duplicate mount points: " + ", ".join(duplicates))
    if "/" not in mounts:
        errors.append("missing root mount point")
    if "/boot" not in mounts:
        errors.append("missing /boot mount point")
    if "/boot/efi" not in mounts:
        errors.append("missing EFI System Partition")
    for item in items:
        if item.filesystem not in SUPPORTED_FILESYSTEMS:
            errors.append(f"unsupported filesystem: {item.filesystem}")
        if item.sizeBytes <= 0 or item.startBytes < 0:
            errors.append(f"invalid size or offset for {item.role}")
        if item.preserve and item.action == "format":
            errors.append(f"preserved partition cannot be formatted: {item.role}")
        if item.role == "efi" and item.filesystem != "vfat":
            errors.append("EFI System Partition must use vfat")
    ordered = sorted((item.startBytes, item.startBytes + item.sizeBytes, item.role) for item in items if not item.preserve)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            errors.append(f"partition overlap: {previous[2]} and {current[2]}")
    return tuple(dict.fromkeys(errors))


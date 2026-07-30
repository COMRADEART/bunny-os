# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-component installation plan validation."""

from __future__ import annotations

from typing import Any, Mapping

from installer.storage.models import DiskInfo
from installer.users.validation import validate_user_plan


MODES = frozenset({"erase_disk", "install_alongside", "replace_partition", "manual", "oem"})


def validate_plan(plan: Mapping[str, Any], disks: list[DiskInfo]) -> tuple[str, ...]:
    errors: list[str] = []
    required = {
        "schemaVersion",
        "installationId",
        "mode",
        "targetDisk",
        "partitions",
        "encryption",
        "boot",
        "user",
        "locale",
        "network",
        "recovery",
        "applicationProfile",
    }
    extra = set(plan) - required
    missing = required - set(plan)
    if extra:
        errors.append("unknown plan fields: " + ", ".join(sorted(extra)))
    if missing:
        errors.append("missing plan fields: " + ", ".join(sorted(missing)))
    if plan.get("schemaVersion") != 1:
        errors.append("unsupported plan schema version")
    if plan.get("mode") not in MODES:
        errors.append("unsupported installation mode")
    target = plan.get("targetDisk")
    selected: DiskInfo | None = None
    if not isinstance(target, Mapping):
        errors.append("targetDisk must be an object")
    else:
        selected = next((disk for disk in disks if disk.id == target.get("id")), None)
        if selected is None:
            errors.append("target disk is no longer present")
        else:
            if target.get("devicePath") != selected.devicePath or target.get("expectedSizeBytes") != selected.sizeBytes:
                errors.append("target disk identity changed after probe")
            if selected.installationMedia:
                errors.append("installation media cannot be selected")
            if selected.readOnly:
                errors.append("read-only target cannot be selected")
    partitions = plan.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        errors.append("at least one planned partition is required")
    else:
        roles = [item.get("role") for item in partitions if isinstance(item, Mapping)]
        if "efi" not in roles or "boot" not in roles or "system" not in roles:
            errors.append("UEFI, boot, and system roles are required")
        for item in partitions:
            if not isinstance(item, Mapping):
                errors.append("partition entries must be objects")
                continue
            if item.get("action") not in {"create", "reuse", "format", "resize"}:
                errors.append("invalid partition action")
            size = item.get("sizeBytes")
            if not isinstance(size, int) or size <= 0:
                errors.append("partition size must be a positive integer")
    encryption = plan.get("encryption")
    if not isinstance(encryption, Mapping):
        errors.append("encryption must be an object")
    elif encryption.get("enabled"):
        if encryption.get("type") != "luks2":
            errors.append("encrypted plans require LUKS2")
        if not encryption.get("recoveryKeyRequired"):
            errors.append("encrypted plans require recovery-key acknowledgement")
    boot = plan.get("boot")
    if not isinstance(boot, Mapping) or boot.get("firmware") != "uefi":
        errors.append("only UEFI installation is supported")
    user = plan.get("user")
    if not isinstance(user, Mapping):
        errors.append("user plan must be an object")
    else:
        errors.extend(validate_user_plan(user))
    return tuple(dict.fromkeys(errors))

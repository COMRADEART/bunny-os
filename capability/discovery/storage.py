# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Root filesystem capacity, writability, class and I/O pressure."""

from __future__ import annotations

import os
from pathlib import Path
import re

from ..model import StorageFacts, absent, measured, unknown
from .memory import pressure
from .sources import Deadline, read_int, read_text, sanitize

__all__ = ["mount_for", "probe", "storage_class"]

#: Partition suffixes differ by device family: ``sda1`` strips a bare digit,
#: while ``nvme0n1p1`` and ``mmcblk0p1`` strip a ``p``-prefixed one. Getting
#: this wrong means looking up ``/sys/block/nvme0n1p1``, which does not exist,
#: and reporting the storage class as unknown on every NVMe machine.
_PARTITION = re.compile(r"^(?P<disk>.+?)(?:p?\d+)$")


def mount_for(target: str) -> tuple[str, str, tuple[str, ...]] | None:
    """``(source, filesystem, options)`` for the mount covering ``target``.

    The longest matching mount point wins, so ``/var`` on its own filesystem is
    reported instead of ``/``.
    """
    text = read_text("/proc/self/mounts", limit=256 * 1024)
    if text is None:
        return None
    best: tuple[str, str, tuple[str, ...]] | None = None
    best_length = -1
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        source, point, filesystem, options = fields[0], fields[1], fields[2], fields[3]
        # /proc/self/mounts octal-escapes spaces and tabs in paths.
        point = point.replace("\\040", " ").replace("\\011", "\t")
        if (target == point or target.startswith(point.rstrip("/") + "/")) and len(point) > best_length:
            best_length = len(point)
            best = (source, filesystem, tuple(options.split(",")))
    return best


def storage_class(source: str) -> tuple[str | None, str]:
    """``rotational``/``solid-state`` for the block device behind a mount.

    Returns ``None`` for anything that is not a plain block device — overlayfs,
    tmpfs, NFS, a device-mapper target whose members are not inspected — because
    the honest answer for those is that the class is not determinable from here,
    not that it is unknown-and-probably-a-disk.
    """
    if not source.startswith("/dev/"):
        return None, f"{sanitize(source, limit=48)} is not a block device"
    name = Path(source).name
    if name.startswith("dm-") or name.startswith("md"):
        return None, "device-mapper or MD target; member devices are not inspected"
    candidates = [name]
    match = _PARTITION.match(name)
    if match:
        candidates.append(match.group("disk"))
    for candidate in candidates:
        value = read_int(f"/sys/block/{candidate}/queue/rotational")
        if value is not None:
            return ("rotational" if value == 1 else "solid-state"), f"/sys/block/{candidate}/queue/rotational"
    return None, f"no queue/rotational for {sanitize(name, limit=32)}"


def _statvfs(path: str) -> tuple[int, int] | None:
    try:
        stat = os.statvfs(path)
    except (OSError, AttributeError):
        return None
    # f_bavail, not f_bfree: the reserved blocks are not available to Bunny OS
    # and counting them is how a "10 GB free" report becomes ENOSPC.
    return stat.f_frsize * stat.f_blocks, stat.f_frsize * stat.f_bavail


def probe(deadline: Deadline) -> StorageFacts:
    root = _statvfs("/")
    if root is None:
        total = unknown("statvfs", "/ could not be stat'ed")
        available = unknown("statvfs")
    else:
        total = measured(root[0], "statvfs /")
        available = measured(root[1], "statvfs / (f_bavail)")

    mount = mount_for("/")
    if mount is None:
        filesystem = unknown("/proc/self/mounts", "unreadable")
        read_only = unknown("/proc/self/mounts")
        class_observation = unknown("/sys/block")
    else:
        source, kind, options = mount
        filesystem = measured(sanitize(kind, limit=32), "/proc/self/mounts")
        read_only = measured("ro" in options, "/proc/self/mounts")
        name, detail = storage_class(source)
        class_observation = (
            measured(name, "/sys/block", detail) if name else unknown("/sys/block", detail)
        )

    share, share_source = pressure("io")
    io_pressure = measured(share, share_source) if share is not None else absent("psi", share_source)

    temporary = _statvfs("/tmp")
    if temporary is None:
        temporary_available = unknown("statvfs", "/tmp could not be stat'ed")
    else:
        temporary_available = measured(temporary[1], "statvfs /tmp")

    return StorageFacts(
        root_total_bytes=total,
        root_available_bytes=available,
        filesystem=filesystem,
        read_only=read_only,
        storage_class=class_observation,
        io_pressure_some_avg10=io_pressure,
        temporary_available_bytes=temporary_available,
    )

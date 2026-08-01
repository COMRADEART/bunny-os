# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a bootc/ostree installed disk offline, without guessing.

``guestfish -i`` and ``inspect-os`` find nothing on these disks. Measured on
the qualified installation: ``list-filesystems`` reports the three partitions
correctly, and inspection returns an empty set, because libguestfs looks for
a conventional root — an ``/etc`` and an ``/usr`` at the top of a filesystem —
and a bootc system keeps its root inside an ostree deployment with ``/etc``
and ``/var`` composed at boot.

Every collector therefore mounts explicitly and asks this module where things
live:

    physical root partition   the ext4 filesystem holding /ostree
    deployment root           /ostree/deploy/<stateroot>/deploy/<checksum>.0
                              — the read-only root the booted system runs
    stateroot var             /ostree/deploy/<stateroot>/var
                              — the mutable /var, where the journal and
                              per-installation state actually are

Nothing here falls back to a guess. Zero deployments, or several where one is
expected, is refused with what was found: a collector that picked one would
produce evidence about a disk nobody chose.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

__all__ = [
    "DiskLayoutError",
    "root_partition",
    "deployment_roots",
    "single_deployment_root",
    "stateroot_var",
    "guestfish",
]


class DiskLayoutError(RuntimeError):
    """The disk does not present the bootc layout the collectors require."""


def guestfish(disk: Path, *commands: str, timeout: int = 900) -> str:
    """Run guestfish read-only with an explicit root mount already applied."""
    root = root_partition(disk)
    argv = ["guestfish", "--ro", "-a", str(disk), "run", ":",
            "mount-ro", root, "/", ":", *commands]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise DiskLayoutError(
            f"guestfish failed on {disk.name}: {result.stderr.strip()[:300]}"
        )
    return result.stdout


def _raw_guestfish(disk: Path, *commands: str, timeout: int = 900) -> str:
    argv = ["guestfish", "--ro", "-a", str(disk), "run", ":", *commands]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise DiskLayoutError(
            f"guestfish failed on {disk.name}: {result.stderr.strip()[:300]}"
        )
    return result.stdout


_ROOT_CACHE: dict[str, str] = {}


def root_partition(disk: Path) -> str:
    """The ext4 filesystem carrying /ostree.

    Chosen by content, not by size or position: an installation with a
    separate /boot has two ext4 filesystems, and the one holding the
    deployments is the only one this can mean.
    """
    key = str(disk.resolve())
    if key in _ROOT_CACHE:
        return _ROOT_CACHE[key]

    listing = _raw_guestfish(disk, "list-filesystems")
    candidates = []
    for line in listing.splitlines():
        if ":" not in line:
            continue
        device, _, kind = line.partition(":")
        if kind.strip() in ("ext4", "xfs", "btrfs"):
            candidates.append(device.strip())
    if not candidates:
        raise DiskLayoutError(f"{disk.name} carries no ext4/xfs/btrfs filesystem")

    holding: list[str] = []
    for device in candidates:
        probe = subprocess.run(
            ["guestfish", "--ro", "-a", str(disk), "run", ":",
             "mount-ro", device, "/", ":", "exists", "/ostree"],
            capture_output=True, text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "true":
            holding.append(device)
    if len(holding) != 1:
        raise DiskLayoutError(
            f"{disk.name}: expected exactly one filesystem holding /ostree, "
            f"found {holding or 'none'} among {candidates}. Naming one would be "
            "a guess about which system is being measured."
        )
    _ROOT_CACHE[key] = holding[0]
    return holding[0]


def deployment_roots(disk: Path) -> list[str]:
    """Every deployment root on the disk, newest first as ostree orders them."""
    listing = guestfish(disk, "glob-expand", "/ostree/deploy/*/deploy/*.0/")
    return [line.strip().rstrip("/") for line in listing.splitlines() if line.strip()]


def single_deployment_root(disk: Path) -> str:
    roots = deployment_roots(disk)
    if len(roots) != 1:
        raise DiskLayoutError(
            f"{disk.name}: expected exactly one deployment, found {len(roots)}: "
            f"{roots}. A collection that picked one would be evidence about a "
            "deployment nobody chose."
        )
    return roots[0]


def stateroot_var(disk: Path) -> str:
    """The mutable /var of the single stateroot."""
    listing = guestfish(disk, "glob-expand", "/ostree/deploy/*/var/")
    vars_found = [line.strip().rstrip("/") for line in listing.splitlines() if line.strip()]
    if len(vars_found) != 1:
        raise DiskLayoutError(
            f"{disk.name}: expected exactly one stateroot var, found {vars_found}"
        )
    return vars_found[0]

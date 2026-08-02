# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline access to the qualified installable disk for dsq collectors.

The installable disk carries an ostree/ directory on the boot partition as
well as on the root, so ostree_disk's "exactly one filesystem holding
/ostree" rule refuses it. Resolution here is still not a guess: the root is
the one filesystem holding /ostree/deploy, and finding two of those is
refused exactly as before. Importing this module patches ostree_disk so
every helper there (deployment_roots, stateroot_var, guestfish) works on
both installable disks and installed target disks.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT / "qualification" / "installed-system" / "scripts"))

import ostree_disk  # noqa: E402
from ostree_disk import (  # noqa: E402,F401  (re-exported for collectors)
    DiskLayoutError,
    deployment_roots,
    guestfish,
    single_deployment_root,
    stateroot_var,
)

_orig_root_partition = ostree_disk.root_partition


def _root_partition(disk: Path) -> str:
    try:
        return _orig_root_partition(disk)
    except ostree_disk.DiskLayoutError:
        pass
    listing = subprocess.run(
        ["guestfish", "--ro", "-a", str(disk), "run", ":", "list-filesystems"],
        capture_output=True, text=True, timeout=900, check=True).stdout
    candidates = []
    for line in listing.splitlines():
        device = line.split(":")[0].strip()
        if not device.startswith("/dev/"):
            continue
        probe = subprocess.run(
            ["guestfish", "--ro", "-a", str(disk), "run", ":",
             "mount-ro", device, "/", ":", "exists", "/ostree/deploy"],
            capture_output=True, text=True, timeout=900)
        if probe.returncode == 0 and probe.stdout.strip() == "true":
            candidates.append(device)
    if len(candidates) != 1:
        raise ostree_disk.DiskLayoutError(
            f"{disk.name}: expected exactly one filesystem holding "
            f"/ostree/deploy, found {candidates}")
    ostree_disk._ROOT_CACHE[str(disk)] = candidates[0]
    return candidates[0]


ostree_disk.root_partition = _root_partition
root_partition = _root_partition

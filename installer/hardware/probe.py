# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only Linux hardware preflight probe."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

from .preflight import classify


LSPCI = ("/usr/bin/lspci", "-mm", "-nn")


def _memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 0


def _secure_boot() -> str:
    for path in Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"):
        try:
            value = path.read_bytes()
        except OSError:
            return "unknown"
        if len(value) >= 5:
            return "enabled" if value[4] == 1 else "disabled"
    return "unknown"


def _pci() -> list[tuple[str, str, str]]:
    if not Path(LSPCI[0]).is_file():
        return []
    completed = subprocess.run(LSPCI, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, env={"PATH": "/usr/bin:/usr/sbin", "LC_ALL": "C"})
    if completed.returncode != 0 or len(completed.stdout) > 1024 * 1024:
        return []
    devices: list[tuple[str, str, str]] = []
    for line in completed.stdout.splitlines()[:1024]:
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        if len(fields) < 4:
            continue
        class_text = fields[1]
        category = "graphics" if any(term in class_text.lower() for term in ("vga", "display", "3d")) else "network" if "network" in class_text.lower() else "other"
        devices.append((category, fields[2][:128], fields[3][:128]))
    return devices


def probe(*, storage_bytes: int) -> dict[str, object]:
    linux = sys.platform.startswith("linux")
    firmware = "uefi" if linux and Path("/sys/firmware/efi").is_dir() else "bios" if linux else "unknown"
    return classify(
        architecture=platform.machine().lower(),
        ram_bytes=_memory_bytes(),
        storage_bytes=storage_bytes,
        firmware_mode=firmware,
        secure_boot=_secure_boot() if linux else "unknown",
        tpm_present=linux and any(Path("/sys/class/tpm").glob("tpm*")),
        pci_devices=_pci(),
    )


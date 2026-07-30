# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed-command, read-only block-device probe."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .models import DiskInfo, parse_lsblk


LSBLK_COMMAND = (
    "/usr/bin/lsblk",
    "--json",
    "--bytes",
    "--output",
    "NAME,KNAME,PATH,TYPE,SIZE,LOG-SEC,PHY-SEC,RM,RO,ROTA,TRAN,MODEL,SERIAL,FSTYPE,FSVER,LABEL,UUID,PARTTYPE,PARTLABEL,MOUNTPOINTS,PKNAME",
)


def discover(*, installation_source: str | None = None, timeout: float = 10.0) -> list[DiskInfo]:
    completed = subprocess.run(
        LSBLK_COMMAND,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/usr/sbin"},
    )
    if len(completed.stdout) > 4 * 1024 * 1024:
        raise ValueError("lsblk output exceeds limit")
    payload: Any = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("lsblk returned a non-object")
    return parse_lsblk(payload, installation_source=installation_source)


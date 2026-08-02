#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 1 — resolve the exact affected units from the qualified image.

The prior pass reported failures under shortened or mangled names
("1.2-org.gnome.Shell.Screencast@0.service" is a collector artifact: the
canonical transient unit is dbus-:1.2-org.gnome.Shell.Screencast@0.service,
and ":1.2" is a per-boot D-Bus connection ID). This script reads the unit
definitions from the qualified disk offline, so every later classification
rests on the image's actual unit semantics, not on folklore.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT / "qualification" / "installed-system" / "scripts"))

sys.path.insert(0, str(SCRIPT_DIR))
from dsq_disk import guestfish, single_deployment_root  # noqa: E402


def read_file(disk: Path, dep: str, path: str) -> str | None:
    try:
        return guestfish(disk, "cat", f"{dep}{path}")
    except Exception:
        return None


def read_link(disk: Path, dep: str, path: str) -> str | None:
    try:
        return guestfish(disk, "readlink", f"{dep}{path}").strip()
    except Exception:
        return None


def exists(disk: Path, dep: str, path: str) -> bool:
    try:
        return guestfish(disk, "exists", f"{dep}{path}").strip() == "true"
    except Exception:
        return False


def main() -> int:
    disk = Path(sys.argv[1])
    out = Path(sys.argv[2])
    dep = single_deployment_root(disk)

    facts: dict[str, object] = {"disk": disk.name, "deploymentRoot": dep}

    units = {}
    for unit in ("gdm.service", "avahi-daemon.service", "avahi-daemon.socket",
                 "accounts-daemon.service", "plymouth-quit.service"):
        body = read_file(disk, dep, f"/usr/lib/systemd/system/{unit}")
        units[unit] = {
            "unitFilePath": f"/usr/lib/systemd/system/{unit}" if body else None,
            "body": body,
            "etcOverride": read_file(disk, dep, f"/etc/systemd/system/{unit}"),
        }
    facts["systemUnits"] = units

    # display-manager.service is an alias; record where the symlink points
    facts["displayManagerAlias"] = {
        "etc": read_link(disk, dep, "/etc/systemd/system/display-manager.service"),
        "usr": read_link(disk, dep, "/usr/lib/systemd/system/display-manager.service"),
    }

    # graphical.target wants
    try:
        facts["graphicalTargetWants"] = guestfish(
            disk, "ls", f"{dep}/etc/systemd/system/graphical.target.wants").split()
    except Exception:
        facts["graphicalTargetWants"] = None
    try:
        facts["multiUserWantsAvahi"] = exists(
            disk, dep,
            "/etc/systemd/system/multi-user.target.wants/avahi-daemon.service")
    except Exception:
        pass

    # The screencast unit is transient: dbus-broker creates
    # dbus-:<connection>-org.gnome.Shell.Screencast@<instance>.service on the
    # user bus from this activation file. There is no unit file to read; the
    # D-Bus service file *is* its definition.
    facts["screencast"] = {
        "dbusServiceFile": read_file(
            disk, dep,
            "/usr/share/dbus-1/services/org.gnome.Shell.Screencast.service"),
        "systemdUserUnitExists": exists(
            disk, dep,
            "/usr/lib/systemd/user/org.gnome.Shell.Screencast.service"),
    }

    # GDM configuration: who is the launch environment?
    facts["gdmCustomConf"] = read_file(disk, dep, "/etc/gdm/custom.conf")
    facts["gnomeInitialSetupDone"] = read_file(
        disk, dep, "/var/lib/gdm/.config/gnome-initial-setup-done")

    # Accounts present on the image: decides whether the launch environment
    # is the greeter or gnome-initial-setup.
    passwd = read_file(disk, dep, "/etc/passwd") or ""
    facts["loginCapableUsers"] = [
        line.split(":")[0] for line in passwd.splitlines()
        if line and int(line.split(":")[2]) >= 1000
        and "nologin" not in line and "false" not in line]
    facts["gnomeInitialSetupPasswd"] = [
        line for line in passwd.splitlines() if "gnome-initial-setup" in line]

    # Presets that decide enablement state
    presets = {}
    for pf in ("90-default.preset", "99-default-disable.preset",
               "80-workstation.preset", "50-bunny.preset"):
        body = read_file(disk, dep, f"/usr/lib/systemd/system-preset/{pf}")
        if body is not None:
            presets[pf] = [l for l in body.splitlines()
                           if any(k in l for k in ("gdm", "avahi"))]
    facts["presetLines"] = presets

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

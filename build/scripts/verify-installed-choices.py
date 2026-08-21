#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the installed system and check that setup's choices actually took.

§45 is precise about the thing this must not do: *"Do not infer from installer
state. Read the installed system."* So nothing here trusts
``/var/lib/bunny-setup/choices.json``. That document is read for one purpose
only — to learn what to *expect* — and every expectation is then checked against
a different file that a different program wrote.

That distinction is the whole value of the check. Three things exist and they are
not the same:

*what was chosen*   — `choices.json`, written by the setup surface;
*what was applied*  — `~/.local/state/bunny-os/applied.json`, written by first run;
*what is true*      — `/etc/locale.conf`, `/etc/passwd`, the LUKS header.

A run that compared the first against the second would pass while the system was
configured differently from both.

## Offline, through the disk image

`guestfish` reads the installed filesystem without booting it, which matters for
two reasons: an unbootable system can still be inspected, so a failure is
diagnosable rather than merely a black screen; and nothing in the guest can
influence the answer.

The bootc layout puts the real root inside an ostree deployment, so paths resolve
under ``/ostree/deploy/*/deploy/*/`` rather than at ``/``.

## Partitions are found, not counted

An earlier version hardcoded ``/dev/sda3`` for boot and ``/dev/sda4`` for root.
This installer's kickstart creates exactly three partitions — EFI, boot, root —
so root is the third, and every per-setting check would have failed to mount and
reported "unreadable" on a perfectly good installation.

The offset was not the mistake; hardcoding was. A layout is a property of the
plan, and a plan that grows a swap partition renumbers everything after it. So
each filesystem is mounted and identified by what is *on* it: ``/ostree`` marks
the root, ``/loader`` marks the boot filesystem.

    python3 build/scripts/verify-installed-choices.py --disk target.qcow2

Encrypted installs need ``--passphrase``; without one the root cannot be read and
the check says so rather than skipping quietly — an unreadable root is itself
evidence that encryption happened.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

CHECKS = {
    "language": ("/etc/locale.conf", r"LANG=([\w.@-]+)"),
    "keyboard": ("/etc/vconsole.conf", r"KEYMAP=([\w-]+)"),
    "hostname": ("/etc/hostname", r"(.+)"),
}


def guestfish(disk: Path, script: str, *, passphrase: str | None = None) -> str:
    """Run a guestfish script against the image, read-only."""
    command = ["guestfish", "--ro", "-a", str(disk)]
    if passphrase:
        command += ["--key", "all:key:" + passphrase]
    try:
        completed = subprocess.run(command, input=script, capture_output=True,
                                   text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as error:
        return f"__ERROR__ {type(error).__name__}: {error}"
    if completed.returncode != 0:
        return f"__ERROR__ {completed.stderr.strip()[:400]}"
    return completed.stdout


def _script(*lines: str) -> str:
    return "\n".join(("run",) + lines) + "\n"


def find_partitions(disk: Path, passphrase: str | None) -> dict[str, str]:
    """Which device is root and which is boot, by looking rather than counting."""
    listing = guestfish(disk, _script("list-filesystems"), passphrase=passphrase)
    if listing.startswith("__ERROR__"):
        return {"error": listing}

    devices = []
    for line in listing.splitlines():
        name, _, kind = line.partition(":")
        name, kind = name.strip(), kind.strip()
        if name.startswith("/dev/") and kind not in {"", "unknown", "swap"}:
            devices.append(name)

    found: dict[str, str] = {}
    for device in devices:
        if "root" in found and "boot" in found:
            break
        probe = guestfish(disk, _script(f"mount-ro {device} /", "ls /"),
                          passphrase=passphrase)
        if probe.startswith("__ERROR__"):
            continue
        entries = set(probe.split())
        if "ostree" in entries and "root" not in found:
            found["root"] = device
        elif "loader" in entries and "boot" not in found:
            found["boot"] = device
    return found


def _read(disk: Path, device: str, path: str, passphrase: str | None) -> str:
    return guestfish(
        disk,
        _script(f"mount-ro {device} /", f"glob cat /ostree/deploy/*/deploy/*{path}"),
        passphrase=passphrase,
    )


def inspect(disk: Path, *, passphrase: str | None, expected: dict[str, Any]) -> dict[str, Any]:
    """Everything readable, and what it should have been."""
    observed: dict[str, Any] = {}
    findings: list[str] = []
    checked: dict[str, Any] = {}

    filesystems = guestfish(disk, _script("list-filesystems"), passphrase=passphrase)
    observed["filesystems"] = filesystems.strip().splitlines()
    if filesystems.startswith("__ERROR__"):
        findings.append(f"the disk image could not be read: {filesystems[:200]}")
        return {"observed": observed, "findings": findings, "checked": checked}

    # §13: an encrypted install must actually have a LUKS header on the target.
    wanted_encryption = bool(expected.get("encryption", {}).get("enabled"))
    observed["luksPresent"] = "crypto_LUKS" in filesystems
    if wanted_encryption and not observed["luksPresent"]:
        findings.append("encryption was chosen but no LUKS volume exists on the disk")
    if expected and not wanted_encryption and observed["luksPresent"]:
        findings.append("encryption was not chosen but a LUKS volume exists")

    partitions = find_partitions(disk, passphrase)
    observed["partitions"] = partitions
    boot_device = partitions.get("boot")
    root_device = partitions.get("root")

    # The bootloader: an installation that cannot boot is not an installation,
    # and this is the check that separates a real completion from a claimed one.
    entries = guestfish(disk, _script(f"mount-ro {boot_device} /", "ls /loader/entries"),
                        passphrase=passphrase) if boot_device else "__ERROR__ no boot filesystem"
    observed["bootEntries"] = [] if entries.startswith("__ERROR__") else \
        [line for line in entries.split() if line.endswith(".conf")]
    if not observed["bootEntries"]:
        findings.append("no bootloader entry was written; the system would not boot")

    if observed["luksPresent"] and not passphrase:
        observed["rootFilesystem"] = "unreadable (encrypted, no passphrase supplied)"
        findings.append("the root filesystem is encrypted and no passphrase was given, "
                        "so the per-setting checks could not run")
        return {"observed": observed, "findings": findings, "checked": checked}

    if not root_device:
        findings.append("no filesystem carrying an ostree deployment was found; "
                        "the installation did not complete")
        return {"observed": observed, "findings": findings, "checked": checked}

    deployment = guestfish(
        disk, _script(f"mount-ro {root_device} /", "glob ls /ostree/deploy/*/deploy/"),
        passphrase=passphrase)
    observed["deployment"] = deployment.strip().splitlines()[:3]

    for name, (path, pattern) in CHECKS.items():
        body = _read(disk, root_device, path, passphrase)
        if body.startswith("__ERROR__"):
            checked[name] = {"read": False, "detail": body[:160]}
            continue
        match = re.search(pattern, body)
        checked[name] = {"read": True,
                         "value": match.group(1).strip() if match else None}

    # The account: read from /etc/passwd on the installed system, never from the
    # document that asked for it.
    passwd = _read(disk, root_device, "/etc/passwd", passphrase)
    username = expected.get("account", {}).get("username", "")
    checked["account"] = {
        "read": not passwd.startswith("__ERROR__"),
        "present": bool(username) and ("\n" + passwd).find("\n" + username + ":") >= 0,
        "username": username,
    }
    if username and not checked["account"]["present"]:
        findings.append(f"the account {username!r} does not exist on the installed system")

    # Root must be locked: `rootpw --lock` in the kickstart, verified in shadow.
    shadow = _read(disk, root_device, "/etc/shadow", passphrase)
    root_line = next((line for line in shadow.splitlines() if line.startswith("root:")), "")
    locked = root_line.split(":")[1].startswith(("!", "*")) if root_line else None
    checked["rootLocked"] = {"read": bool(root_line), "locked": locked}
    if root_line and not locked:
        findings.append("the root account is not locked on the installed system")

    # §45: what setup wrote, present on the target so first boot can apply it.
    choices = guestfish(
        disk, _script(f"mount-ro {root_device} /",
                      "glob ls /ostree/deploy/*/var/lib/bunny-setup/"),
        passphrase=passphrase)
    checked["choicesOnTarget"] = {
        "read": not choices.startswith("__ERROR__"),
        "files": [] if choices.startswith("__ERROR__") else choices.split(),
    }

    # Compare what is true against what was chosen.
    locale = expected.get("locale", {})
    if checked.get("language", {}).get("value") and locale.get("language"):
        want = locale["language"].replace("-", "_")
        got = checked["language"]["value"]
        if not got.startswith(want):
            findings.append(f"language: chose {want}, the system has {got}")
    if checked.get("keyboard", {}).get("value") and locale.get("keyboardLayout"):
        if checked["keyboard"]["value"] != locale["keyboardLayout"]:
            findings.append(f"keyboard: chose {locale['keyboardLayout']}, "
                            f"the system has {checked['keyboard']['value']}")

    return {"observed": observed, "findings": findings, "checked": checked}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--passphrase")
    parser.add_argument("--expected", type=Path,
                        help="the choices.json setup wrote, read only to learn "
                             "what to expect")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    if not shutil.which("guestfish"):
        sys.stderr.write("guestfish is required to read the installed system\n")
        return 3
    if not arguments.disk.is_file():
        sys.stderr.write(f"no such disk image: {arguments.disk}\n")
        return 2

    expected: dict[str, Any] = {}
    if arguments.expected and arguments.expected.is_file():
        expected = json.loads(arguments.expected.read_text(encoding="utf-8"))

    result = inspect(arguments.disk, passphrase=arguments.passphrase, expected=expected)
    report = {
        "schemaVersion": 1,
        "note": "Read from the installed filesystem. `expected` is used only to know "
                "what to look for; every value below came from a file on the target.",
        "disk": str(arguments.disk),
        "expectedFrom": str(arguments.expected) if arguments.expected else None,
        **result,
    }
    document = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(document, encoding="utf-8", newline="\n")
    sys.stdout.write(document)
    return 0 if not result["findings"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

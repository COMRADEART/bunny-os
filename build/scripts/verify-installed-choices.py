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
*what was applied*  — whatever first-boot recorded having done;
*what is true*      — `/etc/locale.conf`, `/etc/passwd`, the LUKS header, dconf.

A run that compared the first against the second would pass while the system was
configured differently from both.

## Offline, through the disk image

`guestfish` reads the installed filesystem without booting it, which matters for
two reasons: an unbootable system can still be inspected, so a failure is
diagnosable rather than merely a black screen; and nothing in the guest can
influence the answer.

The bootc layout puts the real root inside an ostree deployment, so paths are
resolved under ``/ostree/deploy/*/deploy/*/`` rather than at ``/``.

    python3 build/scripts/verify-installed-choices.py --disk target.qcow2

Encrypted installs: the root filesystem is inside LUKS and cannot be read without
the passphrase. Pass ``--passphrase`` to unlock it, or the check reports what it
could see and marks the rest ``unreadable`` — which is itself evidence that
encryption happened.
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


def guestfish(disk: Path, script: str, *, passphrase: str | None = None) -> str:
    """Run a guestfish script against the image, read-only."""
    command = ["guestfish", "--ro", "-a", str(disk)]
    if passphrase:
        command += ["--key", "all:key:" + passphrase]
    completed = subprocess.run(command, input=script, capture_output=True,
                               text=True, timeout=600)
    if completed.returncode != 0:
        return f"__ERROR__ {completed.stderr.strip()[:400]}"
    return completed.stdout


def _root_prefix(disk: Path, passphrase: str | None) -> tuple[str, str]:
    """Find the ostree deployment root, or say why it could not be found."""
    listing = guestfish(disk, "run\nlist-filesystems\n", passphrase=passphrase)
    if listing.startswith("__ERROR__"):
        return "", listing
    # The deployment lives on the root filesystem; find it by looking.
    probe = guestfish(
        disk,
        "run\n"
        "mount /dev/sda4 /\n"
        "glob ls /ostree/deploy/*/deploy/\n",
        passphrase=passphrase,
    )
    if probe.startswith("__ERROR__"):
        return "", probe
    return probe.strip(), listing


CHECKS = {
    "language": ("/etc/locale.conf", r"LANG=([\w.@-]+)"),
    "keyboard": ("/etc/vconsole.conf", r"KEYMAP=([\w-]+)"),
    "hostname": ("/etc/hostname", r"(.+)"),
}


def inspect(disk: Path, *, passphrase: str | None, expected: dict[str, Any]) -> dict[str, Any]:
    """Everything readable, and what it should have been."""
    observed: dict[str, Any] = {}
    findings: list[str] = []

    filesystems = guestfish(disk, "run\nlist-filesystems\n", passphrase=passphrase)
    observed["filesystems"] = filesystems.strip().splitlines()

    # §13: an encrypted install must actually have a LUKS header on the target.
    observed["luksPresent"] = "crypto_LUKS" in filesystems
    if expected.get("encryption", {}).get("enabled") and not observed["luksPresent"]:
        findings.append("encryption was chosen but no LUKS volume exists on the disk")
    if not expected.get("encryption", {}).get("enabled") and observed["luksPresent"]:
        findings.append("encryption was not chosen but a LUKS volume exists")

    # The bootloader: an installation that cannot boot is not an installation.
    entries = guestfish(disk, "run\nmount /dev/sda3 /\nls /loader/entries\n",
                        passphrase=passphrase)
    observed["bootEntries"] = [] if entries.startswith("__ERROR__") else \
        [line for line in entries.strip().splitlines() if line.endswith(".conf")]
    if not observed["bootEntries"]:
        findings.append("no bootloader entry was written; the system would not boot")

    if observed["luksPresent"] and not passphrase:
        observed["rootFilesystem"] = "unreadable (encrypted, no passphrase supplied)"
        findings.append(
            "the root filesystem is encrypted and no passphrase was given, so the "
            "per-setting checks below could not run")
        return {"observed": observed, "findings": findings, "checked": {}}

    deployment, _ = _root_prefix(disk, passphrase)
    observed["deployment"] = deployment.strip().splitlines()[:3]

    checked: dict[str, Any] = {}
    for name, (path, pattern) in CHECKS.items():
        body = guestfish(
            disk,
            f"run\nmount /dev/sda4 /\nglob cat /ostree/deploy/*/deploy/*{path}\n",
            passphrase=passphrase,
        )
        if body.startswith("__ERROR__"):
            checked[name] = {"read": False, "detail": body[:120]}
            continue
        match = re.search(pattern, body)
        checked[name] = {"read": True, "value": match.group(1).strip() if match else None}

    # The account: read from /etc/passwd on the installed system, not from the
    # document that asked for it.
    passwd = guestfish(
        disk,
        "run\nmount /dev/sda4 /\nglob cat /ostree/deploy/*/deploy/*/etc/passwd\n",
        passphrase=passphrase,
    )
    username = expected.get("account", {}).get("username", "")
    checked["account"] = {
        "read": not passwd.startswith("__ERROR__"),
        "present": bool(username) and f"\n{username}:" in ("\n" + passwd),
        "username": username,
    }
    if username and not checked["account"]["present"]:
        findings.append(f"the account {username!r} does not exist on the installed system")

    # Root must be locked: `rootpw --lock` in the kickstart, verified in shadow.
    shadow = guestfish(
        disk,
        "run\nmount /dev/sda4 /\nglob cat /ostree/deploy/*/deploy/*/etc/shadow\n",
        passphrase=passphrase,
    )
    root_line = next((line for line in shadow.splitlines() if line.startswith("root:")), "")
    checked["rootLocked"] = {"read": bool(root_line),
                             "locked": root_line.split(":")[1].startswith("!") if root_line else None}
    if root_line and not checked["rootLocked"]["locked"]:
        findings.append("the root account is not locked on the installed system")

    # Compare what is true against what was chosen.
    locale = expected.get("locale", {})
    if checked.get("language", {}).get("value") and locale.get("language"):
        want = locale["language"].replace("-", "_")
        got = checked["language"]["value"]
        if not got.startswith(want):
            findings.append(f"language: chose {want}, the system has {got}")
    if checked.get("keyboard", {}).get("value") and locale.get("keyboardLayout"):
        if checked["keyboard"]["value"] != locale["keyboardLayout"]:
            findings.append(
                f"keyboard: chose {locale['keyboardLayout']}, "
                f"the system has {checked['keyboard']['value']}")

    return {"observed": observed, "findings": findings, "checked": checked}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--passphrase")
    parser.add_argument("--expected", type=Path,
                        help="the choices.json the setup surface wrote, read only to "
                             "learn what to expect")
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

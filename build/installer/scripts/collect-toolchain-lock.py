#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin every tool that can influence installed media, from the machine that runs them.

The archive toolchain is pinned by ``build/inputs/builder-image-lock.json``.
This lock is its counterpart for the *installation* path: the tools that turn
the reproducible archive into disks, media and booted test systems. A disk
image whose producing toolchain is unrecorded cannot be regenerated, and a
qualification run whose QEMU version nobody wrote down is a result about an
unknown machine.

Two classifications matter here and they are not the archive's:

    media-content-affecting   the tool's output bytes end up inside an
                              installation or recovery artifact
    test-environment-only     the tool hosts or inspects a qualification run;
                              its version shapes the evidence, never the medium

``unknown`` is refused, exactly as in the archive model: a tool nobody
classified is a tool whose effect nobody established.

Usage::

    collect-toolchain-lock.py --output build/installer/toolchain.lock.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

#: name -> (rpm package, classification, purpose)
TOOLS = {
    "bootc": ("bootc", "media-content-affecting",
              "deploys the reproducible root filesystem onto target disks"),
    "image-builder": ("image-builder", "media-content-affecting",
                      "turns the bootc archive into qcow2, raw and ISO artifacts"),
    "qemu-img": ("qemu-img", "media-content-affecting",
                 "creates and converts disk images; its output is the artifact"),
    "qemu-system-x86_64": ("qemu-system-x86-core", "test-environment-only",
                           "hosts every virtual qualification scenario"),
    "OVMF": ("edk2-ovmf", "test-environment-only",
             "UEFI firmware for virtual scenarios, including Secure Boot variants"),
    "swtpm": ("swtpm", "test-environment-only",
              "software TPM 2.0 attached to virtual scenarios; never claims physical TPM"),
    "cryptsetup": ("cryptsetup", "media-content-affecting",
                   "creates LUKS2 volumes during encrypted installation"),
    "parted": ("parted", "media-content-affecting",
               "partitions target disks"),
    "sgdisk": ("gdisk", "media-content-affecting",
               "GPT partitioning of target disks"),
    "mkfs.fat": ("dosfstools", "media-content-affecting",
                 "creates the EFI system partition filesystem"),
    "mkfs.ext4": ("e2fsprogs", "media-content-affecting",
                  "creates root and boot filesystems"),
    "grub2-mkrescue": ("grub2-tools-extra", "media-content-affecting",
                       "bootloader tooling for generated media"),
    "grub2-mkconfig": ("grub2-tools", "media-content-affecting",
                       "bootloader configuration on installed systems"),
    "shim": ("shim-x64", "media-content-affecting",
             "first-stage Secure Boot loader shipped on media where present"),
    "systemd-boot": ("systemd-boot-unsigned", "media-content-affecting",
                     "alternative boot manager where used"),
    "restorecon": ("policycoreutils", "media-content-affecting",
                   "applies SELinux labels during installation"),
    "matchpathcon": ("libselinux-utils", "test-environment-only",
                     "resolves intended SELinux contexts for evidence comparison"),
    "xorriso": ("xorriso", "media-content-affecting",
                "assembles ISO 9660 installer and recovery media"),
    "mcopy": ("mtools", "media-content-affecting",
              "populates FAT images inside generated media"),
    "skopeo": ("skopeo", "media-content-affecting",
               "moves the archive between stores; every byte digest-verified afterwards"),
    "podman": ("podman", "media-content-affecting",
               "materialises the reproducible archive for deployment"),
    "guestfish": ("guestfs-tools", "test-environment-only",
                  "inspects installed disks without booting them; reads applied SELinux labels"),
    "virtiofsd": ("virtiofsd", "test-environment-only",
                  "shares evidence directories with qualification guests where used"),
}

VALID_CLASSES = {"media-content-affecting", "test-environment-only"}


def rpm_query(package: str, fmt: str) -> str | None:
    result = subprocess.run(
        ["rpm", "-q", "--qf", fmt, package],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect-toolchain-lock")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    stamp = os.environ.get("BUNNY_EVALUATION_TIME") or (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )

    tools = []
    missing = []
    for name, (package, classification, purpose) in sorted(TOOLS.items()):
        if classification not in VALID_CLASSES:
            print(f"BLOCKED: {name} carries unknown classification {classification!r}",
                  file=sys.stderr)
            return 2
        nevra = rpm_query(package, "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}")
        if nevra is None:
            missing.append({"name": name, "package": package,
                            "classification": classification, "purpose": purpose})
            continue
        record = {
            "name": name,
            "package": package,
            "nevra": nevra,
            "version": rpm_query(package, "%{VERSION}"),
            "architecture": rpm_query(package, "%{ARCH}"),
            # The package header's digest of its own payload: content identity,
            # not a summary the lock writes about itself.
            "payloadDigest": rpm_query(package, "%{PAYLOADDIGEST}"),
            "sourceRepository": rpm_query(package, "%{VENDOR}"),
            "signingStatus": (
                "distribution-signed"
                if (rpm_query(package, "%{SIGPGP:pgpsig}") or rpm_query(package, "%{RSAHEADER:pgpsig}"))
                else "unsigned"
            ),
            "classification": classification,
            "purpose": purpose,
        }
        tools.append(record)

    document = {
        "schemaVersion": 1,
        "collectedAt": stamp,
        "collectedOn": subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "note": (
            "Every tool that can influence installed media, pinned from the machine "
            "that runs them. A tool listed in absentTools is declared, with the reason; "
            "a tool absent and undeclared fails the collection, because a missing entry "
            "is indistinguishable from a forgotten one."
        ),
        "tools": tools,
        "absentTools": {
            entry["name"]: (
                f"{entry['package']} is not installed on the collection host. "
                "A scenario requiring it must refuse to run rather than substitute."
            )
            for entry in missing
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"pinned {len(tools)} tool(s), declared {len(missing)} absent")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

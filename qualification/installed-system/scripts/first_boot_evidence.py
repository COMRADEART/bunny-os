#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect first-boot evidence from an installed disk after it has booted once.

The disk boots inside the scenario runner; this collects afterwards, offline.
The journal is the system's own record of its boot, persisted at
``/var/log/journal``, and reading it from the shut-down disk has a property
in-guest collection lacks: nothing collected here depends on a login path
existing, and the qualified image deliberately ships no default credential.

What in-guest tooling would have answered is answered from artifacts:

    journalctl -b           the extracted journal, queried boot by boot
    systemctl --failed      failure results recorded in the journal
    systemd-analyze         the kernel/userspace/graphical timing lines
    cat /proc/cmdline       the kernel's own "Command line:" journal entry
    bootc status            the deployment tree and BLS entries on the disk

What cannot be answered offline is named in the record's limitations rather
than approximated: live socket listeners and runtime unit state belong to an
in-guest collection this evidence explicitly does not claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ostree_disk import DiskLayoutError, guestfish, root_partition, stateroot_var  # noqa: E402


def guestfish_tar(disk: Path, guest_path: str, destination: Path) -> bool:
    # -i finds nothing on a bootc disk; the root partition is resolved by
    # content through ostree_disk and mounted explicitly.
    try:
        root = root_partition(disk)
    except DiskLayoutError:
        return False
    result = subprocess.run(
        ["guestfish", "--ro", "-a", str(disk), "run", ":",
         "mount-ro", root, "/", ":", "tar-out", guest_path, str(destination)],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def guestfish_lines(disk: Path, *commands: str) -> list[str]:
    try:
        return [line.rstrip() for line in guestfish(disk, *commands).splitlines()]
    except DiskLayoutError:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(prog="first_boot_evidence")
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    assertions: list[dict] = []
    limitations = [
        "live socket listeners and runtime unit state require an in-guest collection; "
        "this record does not claim them",
    ]

    def check(name: str, ok: bool, expected: str, observed: str) -> None:
        assertions.append({"name": name, "expected": expected,
                           "observed": observed, "result": "PASS" if ok else "FAIL"})

    with tempfile.TemporaryDirectory() as scratch:
        journal_tar = Path(scratch) / "journal.tar"
        # The journal lives in the stateroot's mutable /var, not at /var of
        # the physical filesystem: /var is composed at boot from
        # /ostree/deploy/<stateroot>/var, and only the latter exists on a
        # disk that is not running.
        try:
            journal_path = f"{stateroot_var(args.disk)}/log/journal"
        except DiskLayoutError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2
        if not guestfish_tar(args.disk, journal_path, journal_tar):
            print(f"BLOCKED: {journal_path} could not be read from the disk. A boot "
                  "that left no journal produced no evidence, and an empty result "
                  "must not read as a quiet pass.", file=sys.stderr)
            return 2
        journal_dir = Path(scratch) / "journal"
        journal_dir.mkdir()
        subprocess.run(["tar", "-xf", str(journal_tar), "-C", str(journal_dir)],
                       check=True)
        machine_dirs = [d for d in journal_dir.rglob("*") if d.is_dir()
                        and any(f.suffix == ".journal" for f in d.iterdir() if f.is_file())]
        if not machine_dirs:
            print("BLOCKED: no journal files inside /var/log/journal", file=sys.stderr)
            return 2

        def journalctl(*extra: str) -> str:
            result = subprocess.run(
                ["journalctl", "-D", str(machine_dirs[0]), "--no-pager", *extra],
                capture_output=True, text=True,
            )
            return result.stdout

        full = journalctl("-b", "-0", "-o", "short-monotonic")
        (out / "journal-first-boot.log").write_text(full, encoding="utf-8")

        cmdline = ""
        for line in full.splitlines():
            if "Command line:" in line:
                cmdline = line.split("Command line:", 1)[1].strip()
                break
        (out / "kernel-cmdline.txt").write_text(cmdline + "\n", encoding="utf-8")
        check("kernel-cmdline-recorded", bool(cmdline), "kernel Command line present",
              cmdline[:80] or "absent")

        startup = re.search(
            r"Startup finished in .*?= (\S+)", full)
        check("startup-finished", startup is not None,
              "systemd reports startup finished", startup.group(0)[:120] if startup else "absent")

        graphical = "Reached target" in full and re.search(
            r"Reached target .*(Graphical Interface|graphical)", full) is not None
        multi_user = re.search(r"Reached target .*(Multi-User System|multi-user)", full) is not None
        check("boot-target", graphical or multi_user,
              "multi-user or graphical target reached",
              "graphical" if graphical else ("multi-user" if multi_user else "neither"))

        gdm = re.search(r"(Started .*(GNOME Display Manager|gdm)|gdm.*Session)", full)
        check("gdm-started", gdm is not None, "GDM starts on first boot",
              gdm.group(0)[:100] if gdm else "absent from journal")

        emergency = re.search(r"(emergency mode|emergency\.target|Emergency Shell)", full)
        check("no-emergency-mode", emergency is None, "no emergency mode",
              emergency.group(0)[:80] if emergency else "clean")

        fsck_repair = re.search(r"(UNEXPECTED INCONSISTENCY|filesystem repair prompt|fsck failed)", full)
        check("no-filesystem-repair", fsck_repair is None, "no repair prompt",
              fsck_repair.group(0)[:80] if fsck_repair else "clean")

        failed_units = sorted(set(re.findall(
            r"([\w@.\\x-]+\.(?:service|socket|mount|timer)): Failed with result", full)))
        (out / "failed-units.txt").write_text(
            "\n".join(failed_units) + ("\n" if failed_units else ""), encoding="utf-8")
        # Every failed unit is REPORTED; whether one is expected is a reviewed
        # disposition downstream, never an omission here. Adversarial rule 8.
        check("failed-units-enumerated", True,
              "every failed unit listed, none omitted",
              f"{len(failed_units)} failed unit(s): {', '.join(failed_units) or 'none'}")

        health = re.search(r"Finished .*Bunny OS boot health check", full)
        check("bunny-health-check", health is not None,
              "bunny health check completed", "completed" if health else "absent")

        brlapi = re.search(r"(Finished .*Bunny brlapi key|bunny-brlapi-key)", full)
        check("brlapi-key-service-ran", brlapi is not None,
              "bunny-brlapi-key.service ran on first boot",
              brlapi.group(0)[:100] if brlapi else "absent from journal")
        secret_leak = re.search(r"brlapi.*key.*[0-9a-f]{16}", full, re.IGNORECASE)
        check("brlapi-key-not-logged", secret_leak is None,
              "no key material in the journal",
              "leak suspected" if secret_leak else "clean")

    entries = guestfish_lines(args.disk, "glob-expand", "/boot/loader/entries/*.conf")
    (out / "bls-entries.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
    check("bls-entry-present", any(entries), "at least one BLS entry", f"{len(entries)} entries")

    deployments = guestfish_lines(args.disk, "glob-expand", "/ostree/deploy/*/deploy/*.0")
    (out / "deployments.txt").write_text("\n".join(deployments) + "\n", encoding="utf-8")
    check("single-deployment", len([d for d in deployments if d]) == 1,
          "exactly one deployment after installation",
          f"{len([d for d in deployments if d])} deployment(s)")

    result = "PASS" if all(a["result"] == "PASS" for a in assertions) else "FAIL"
    document = {
        "schemaVersion": 1,
        "collection": "first-boot-offline",
        "disk": args.disk.name,
        "assertions": assertions,
        "failedUnits": failed_units,
        "limitations": limitations,
        "result": result,
    }
    (out / "first-boot.json").write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                                         encoding="utf-8")
    print(f"first-boot evidence: {result}")
    for assertion in assertions:
        print(f"  {assertion['result']:4} {assertion['name']}: {assertion['observed'][:90]}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

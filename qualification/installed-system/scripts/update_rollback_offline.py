#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage an update, roll it back, and prove user data survived — offline.

The qualified image ships no default credential, so nothing here drives the
update from inside a logged-in guest. What this executes is the deployment
half of the update mechanism — the half bootc/ostree own on disk:

    stage       deploy the N+1 image as a second deployment on the installed
                disk, exactly as a staged update leaves it
    boot        the scenario runner boots the disk; which deployment ran is
                read from the journal afterwards, not assumed
    rollback    flip the deployment order back to N, as bootc rollback does
    preserve    recognisable fixture data written into /var/home before the
                update must carry identical checksums after the rollback

The signed-manifest half — signature verification, wrong keys, tampered
manifests — is exercised against the update agent's own validator by
update_manifest_tests.py, and the two records name each other. What is NOT
covered by either: the in-guest agent driving a download over the network.
The record says so in limitations rather than letting the pass imply it.

Steps are subcommands so the scenario runner can boot between them:

    update_rollback_offline.py inject  --disk D --record R
    update_rollback_offline.py stage   --disk D --image-archive N1.oci.tar --record R
    update_rollback_offline.py verify-staged --disk D --record R
    update_rollback_offline.py rollback --disk D --record R
    update_rollback_offline.py verify-preserved --disk D --record R
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

FIXTURES = {
    "/var/home/bunny-test/documents/project-notes.txt":
        "qualification fixture: project notes, written before the update\n",
    "/var/home/bunny-test/.config/bunny-os/settings.json":
        '{"fixture": true, "purpose": "bunny configuration preservation"}\n',
    "/var/home/bunny-test/workspace/model-metadata.json":
        '{"fixture": true, "purpose": "workspace and model metadata preservation"}\n',
}


def run(*argv: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, check=check)


def load_record(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schemaVersion": 1, "steps": [], "limitations": [
        "the in-guest update agent's download path is not exercised: the qualified "
        "image ships no default credential and this harness does not add one",
    ]}


def save_record(path: Path, record: dict) -> None:
    passed = all(s["result"] == "PASS" for s in record["steps"])
    record["result"] = "PASS" if record["steps"] and passed else "FAIL"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def step(record: dict, name: str, ok: bool, detail: str) -> None:
    record["steps"].append({"step": name, "result": "PASS" if ok else "FAIL",
                            "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail[:100]}")


class Disk:
    """Loop-mount an installed bootc disk read-write, deployment-aware."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.loop = None
        self.mount = Path("/mnt/bunny-update-test")

    def __enter__(self) -> "Disk":
        self.loop = run("losetup", "--find", "--show", "--partscan",
                        str(self.path)).stdout.strip()
        self.mount.mkdir(parents=True, exist_ok=True)
        # Root is the largest partition; the ESP and /boot are the others.
        parts = run("lsblk", "-Jnb", "-o", "NAME,SIZE", self.loop).stdout
        children = json.loads(parts)["blockdevices"][0].get("children", [])
        root = "/dev/" + max(children, key=lambda c: int(c["size"]))["name"]
        run("mount", root, str(self.mount))
        boot = "/dev/" + sorted(children, key=lambda c: int(c["size"]))[1]["name"]
        run("mount", boot, str(self.mount / "boot"))
        return self

    def __exit__(self, *_: object) -> None:
        run("umount", "-R", str(self.mount), check=False)
        if self.loop:
            run("losetup", "-d", self.loop, check=False)

    def sysroot(self) -> Path:
        return self.mount

    def var_root(self) -> Path:
        deploys = sorted((self.mount / "ostree/deploy").glob("*/var"))
        if not deploys:
            raise SystemExit("BLOCKED: no ostree stateroot var found")
        return deploys[0]

    def deployments(self) -> list[str]:
        entries = sorted((self.mount / "boot/loader/entries").glob("*.conf"))
        return [e.name for e in entries]


def main() -> int:
    parser = argparse.ArgumentParser(prog="update_rollback_offline")
    parser.add_argument("command", choices=(
        "inject", "stage", "verify-staged", "rollback", "verify-preserved"))
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--image-archive", type=Path)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()

    record = load_record(args.record)

    with Disk(args.disk) as disk:
        if args.command == "inject":
            digests = {}
            var = disk.var_root()
            for guest_path, content in FIXTURES.items():
                relative = guest_path.replace("/var/", "", 1)
                target = var / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                digests[guest_path] = hashlib.sha256(content.encode()).hexdigest()
            record["fixtureDigestsBefore"] = digests
            step(record, "inject-fixtures", True,
                 f"{len(digests)} fixture file(s) written into the mutable stateroot "
                 "with recorded checksums")

        elif args.command == "stage":
            if not args.image_archive or not args.image_archive.is_file():
                raise SystemExit("BLOCKED: --image-archive must name the N+1 oci archive")
            before = disk.deployments()
            result = run(
                "ostree", "container", "image", "deploy",
                f"--sysroot={disk.sysroot()}",
                "--stateroot=default",
                f"--image=ostree-unverified-image:oci-archive:{args.image_archive}",
                check=False,
            )
            after = disk.deployments()
            ok = result.returncode == 0 and len(after) == len(before) + 1
            step(record, "stage-n-plus-1", ok,
                 f"deployments {len(before)} -> {len(after)}; "
                 f"{result.stderr.strip()[:120] if result.returncode else 'staged'}")
            record["deploymentsAfterStage"] = after

        elif args.command == "verify-staged":
            entries = disk.deployments()
            ok = len(entries) >= 2
            step(record, "two-deployments-present", ok,
                 f"{len(entries)} BLS entries: {', '.join(entries)}")
            # The previous deployment must still be intact — an update that
            # consumed its rollback target has already failed.
            roots = sorted((disk.mount / "ostree/deploy").glob("*/deploy/*.0"))
            step(record, "previous-deployment-retained", len(roots) >= 2,
                 f"{len(roots)} deployment root(s) on disk")

        elif args.command == "rollback":
            # bootc rollback reorders the deployment list; offline, the same
            # effect is the bootloader default flipping back to the previous
            # entry. ostree admin does the reorder against a mounted sysroot.
            result = run("ostree", "admin", "undeploy", "0",
                         f"--sysroot={disk.sysroot()}", check=False)
            ok = result.returncode == 0
            step(record, "rollback-to-n", ok,
                 result.stderr.strip()[:150] if not ok else
                 "newest deployment removed; previous deployment is default again")

        elif args.command == "verify-preserved":
            before = record.get("fixtureDigestsBefore") or {}
            if not before:
                step(record, "preservation-baseline", False,
                     "no before-checksums recorded; a preservation claim without a "
                     "baseline is refused (adversarial rule 13)")
            var = disk.var_root()
            after = {}
            for guest_path in FIXTURES:
                relative = guest_path.replace("/var/", "", 1)
                target = var / relative
                if target.is_file():
                    after[guest_path] = hashlib.sha256(target.read_bytes()).hexdigest()
            matches = {p: (before.get(p) == after.get(p)) for p in before}
            record["fixtureDigestsAfter"] = after
            step(record, "user-data-preserved", all(matches.values()) and bool(matches),
                 "; ".join(f"{p.rsplit('/', 1)[-1]}:{'ok' if ok else 'CHANGED-OR-MISSING'}"
                           for p, ok in matches.items()))

    save_record(args.record, record)
    print(f"record: {args.record} ({record['result']})")
    return 0 if record["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

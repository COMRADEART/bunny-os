#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect applied SELinux contexts from an installed disk, without booting it.

The archive-stage half of the SELinux dimension — intended contexts, resolved
through matchpathcon — has matched across three builders. This collects the
other half the comparison model already has a slot for: what the installed
filesystem is *actually* labelled with, read from the ``security.selinux``
xattr of every file on the deployed root.

The disk is opened read-only through libguestfs and streamed out as a tar
that carries xattrs; the labels come from the tar's PAX headers. Nothing here
mounts the disk read-write, boots it, or trusts the guest to report on
itself: a system asked about its own labels answers through the very policy
being verified, and an offline read does not.

Differences against the intended manifest are classified downstream by
``compare_selinux_manifests.py`` into the states the qualification defines;
this collector only measures.

Usage::

    collect_applied_selinux.py --disk installed.qcow2 --root /dev/sda3 \
        --output applied-selinux.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ostree_disk import (  # noqa: E402
    DiskLayoutError,
    root_partition,
    single_deployment_root,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_applied_selinux")
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--root", default="", help="root partition device inside the disk; "
                        "discovered via inspect-os when omitted")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--subtree", default="/",
                        help="collect below this guest path (default: whole root)")
    args = parser.parse_args()

    if not args.disk.is_file():
        print(f"BLOCKED: {args.disk} does not exist", file=sys.stderr)
        return 2

    # inspect-os finds nothing on a bootc disk — measured — so the layout
    # comes from ostree_disk, which mounts explicitly and refuses to guess.
    try:
        root = args.root or root_partition(args.disk)
        subtree = args.subtree
        if subtree == "/":
            # The deployed root, not the physical filesystem: /ostree/repo is
            # the deployment mechanism's own store and its labels are not what
            # the intended-context manifest describes.
            subtree = single_deployment_root(args.disk)
    except DiskLayoutError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    # tar-out with xattrs:true carries every security.selinux label in PAX
    # headers. Streaming through tarfile keeps memory flat at ~one member.
    process = subprocess.Popen(
        ["guestfish", "--ro", "-a", str(args.disk),
         "run", ":", "mount-ro", root, "/", ":",
         "tar-out", subtree, "-", "xattrs:true"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdout is not None

    contexts: dict[str, str] = {}
    unlabelled = 0
    total = 0
    try:
        archive = tarfile.open(fileobj=process.stdout, mode="r|")
        for member in archive:
            total += 1
            headers = member.pax_headers or {}
            label = headers.get("SCHILY.xattr.security.selinux") or headers.get(
                "RHT.security.selinux"
            )
            name = "/" + member.name.lstrip("./").lstrip("/")
            if label:
                contexts[name] = label.rstrip("\x00")
            else:
                unlabelled += 1
    except tarfile.TarError as exc:
        process.kill()
        print(f"BLOCKED: reading the guest tar stream failed: {exc}", file=sys.stderr)
        return 2
    finally:
        return_code = process.wait()
    if return_code != 0:
        stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
        print(f"BLOCKED: guestfish exited {return_code}: {stderr[:400]}", file=sys.stderr)
        return 2

    if not contexts:
        # An empty result is a collection failure until proven otherwise —
        # adversarial rule: empty AVC or label results caused by a broken
        # collector must not read as "no findings".
        print(
            "BLOCKED: zero labels were collected. An installed SELinux system has "
            "labels on essentially every file; an empty manifest is a collection "
            "failure, not a clean result.",
            file=sys.stderr,
        )
        return 2

    document = {
        "schemaVersion": 1,
        "collectionMode": "installed-system-offline",
        "collectedFrom": str(args.disk.name),
        "rootDevice": root,
        "subtree": subtree,
        "entryCount": total,
        "labelledCount": len(contexts),
        "unlabelledCount": unlabelled,
        "appliedSelinuxContexts": dict(sorted(contexts.items())),
        "note": (
            "Read from security.selinux xattrs through a read-only libguestfs "
            "mount. This measures the deployed filesystem, not a booted system's "
            "runtime view; enforcing mode, loaded policy and AVC state are "
            "separate, in-guest collections."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"{len(contexts)} labelled path(s) of {total}; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

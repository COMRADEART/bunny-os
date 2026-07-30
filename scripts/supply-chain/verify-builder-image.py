#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify the builder image before a qualification build uses it.

The builder image is the environment both builders run, so it is the one input
whose compromise would be invisible in every other check: an image that built
the artifact wrongly would also generate the evidence saying it built correctly.

What is verified:

* the reference is digest-pinned — a mutable builder tag is refused outright;
* the retained image is present and its manifest hashes to the locked digest;
* every pinned tool carries a version and a classification;
* nothing is classified ``unknown``;
* the Containerfile on disk still hashes to what the lock recorded, so a lock
  describing a builder nobody can rebuild is caught.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import SupplyChainError, parse_builder_image_lock  # noqa: E402

REFUSED = 2
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(prog="verify-builder-image")
    parser.add_argument("--lock", type=Path, default=ROOT / "build" / "inputs" / "builder-image-lock.json")
    parser.add_argument("--containerfile", type=Path, default=ROOT / "build" / "builder" / "Containerfile")
    parser.add_argument("--skip-layout-check", action="store_true")
    args = parser.parse_args()

    if not args.lock.is_file():
        print(
            f"BLOCKED: no builder image lock at {args.lock}. A build whose environment was never "
            "recorded cannot be shown to have used the recorded environment.",
            file=sys.stderr,
        )
        return REFUSED

    try:
        lock = parse_builder_image_lock(json.loads(args.lock.read_text(encoding="utf-8")))
    except SupplyChainError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return REFUSED

    failures: list[str] = []

    if lock.verificationStatus != "verified":
        failures.append(f"the lock records verificationStatus={lock.verificationStatus!r}")

    if lock.unknownTools:
        failures.append(
            "these tools are classified 'unknown': "
            + ", ".join(lock.unknownTools)
            + ". A tool whose effect on the artifact nobody has established cannot be assumed to "
            "have none"
        )

    if args.containerfile.is_file():
        actual = hashlib.sha256(args.containerfile.read_bytes()).hexdigest()
        if actual != lock.containerfileDigest:
            failures.append(
                f"the Containerfile has changed since the builder was built: lock "
                f"{lock.containerfileDigest[:16]} vs file {actual[:16]}. The lock describes an "
                "image this source tree would no longer produce"
            )
    else:
        failures.append(f"the builder Containerfile is missing at {args.containerfile}")

    if not args.skip_layout_check:
        layout = lock.builderReference.split("@", 1)[0]
        if Path(layout).is_dir():
            observed = subprocess.run(
                ["skopeo", "inspect", "--raw", f"oci:{layout}:builder"],
                capture_output=True,
            )
            if observed.returncode != 0:
                failures.append(
                    f"the retained builder image at {layout} could not be read: "
                    + observed.stderr.decode("utf-8", "replace").strip()
                )
            else:
                digest = "sha256:" + hashlib.sha256(observed.stdout).hexdigest()
                if digest != lock.builderDigest:
                    failures.append(
                        f"the retained builder manifest hashes to {digest} and the lock says "
                        f"{lock.builderDigest}"
                    )
        else:
            # A registry reference cannot be checked without network access, and
            # saying so is better than reporting a check that did not run.
            print(
                f"note: {layout} is not a local layout, so the retained image was not re-hashed "
                "here. The build itself pulls by digest and would fail on a mismatch."
            )

    if failures:
        print("BLOCKED: the builder image did not verify:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return REFUSED

    by_class: dict[str, list[str]] = {}
    for tool in lock.tools:
        by_class.setdefault(tool.classification, []).append(tool.name)

    print(f"builder image verified: {lock.builderReference}")
    print(f"  base            {lock.baseReference}")
    print(f"  source commit   {lock.sourceCommit[:12]}")
    print(f"  containerfile   {lock.containerfileDigest[:16]}")
    for classification in sorted(by_class):
        names = sorted(by_class[classification])
        print(f"  {classification:<24} {len(names):>2}: {', '.join(names)}")
    absent = json.loads(args.lock.read_text(encoding="utf-8")).get("absentTools") or {}
    if absent:
        print(f"  declared absent          {len(absent)}: {', '.join(sorted(absent))}")
    print(f"  lock            {display_path(args.lock, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

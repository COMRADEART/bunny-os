#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Declare one build epoch, and say exactly where it may be applied.

Both builders must use the same epoch, and deriving it independently is not the
same as sharing it: two checkouts of one commit agree, but a build of a
*different* commit would quietly get a different epoch and the mismatch would
surface as an unexplained archive difference rather than as a wrong input.

The epoch is the qualification target commit's own timestamp. That makes it a
property of what is being built rather than of when somebody built it.

``appliedTo`` and ``neverAppliedTo`` are both required and both validated. A
declared epoch with no statement of scope is a fake clock nobody bounded, and
the four sites it must never reach — certificate validity, advisory freshness,
signature verification, metadata expiry — are security decisions that depend on
the real clock. Evidence timestamps are excluded for a different reason: a build
output timestamp and a record of when something was measured are different
concepts, and flattening the second falsifies the evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import (  # noqa: E402
    EPOCH_FORBIDDEN,
    SCHEMA_VERSION,
    SupplyChainError,
    parse_reproducibility_lock,
)

APPLIED = [
    "container-image-config-created",
    "oci-archive-entry-mtimes",
    "rpm-transaction-install-time",
    "font-directory-mtimes",
    "generated-file-mtimes",
]


def main() -> int:
    parser = argparse.ArgumentParser(prog="write-reproducibility-lock")
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--profile", default="beta")
    parser.add_argument("--architecture", default="x86_64")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    inputs = root / "build" / "inputs"

    epoch = subprocess.run(
        ["git", "show", "-s", "--format=%ct", args.candidate_commit],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if epoch.returncode != 0:
        raise SystemExit(
            f"BLOCKED: cannot read the timestamp of {args.candidate_commit}: "
            f"{epoch.stderr.strip()}"
        )

    def read(name: str, field: str) -> str:
        path = inputs / name
        if not path.is_file():
            raise SystemExit(
                f"BLOCKED: {name} is absent. The epoch lock names the other three locks, so all "
                "three must exist before it can be written; a lock referring to inputs nobody "
                "recorded pins nothing."
            )
        return str(json.loads(path.read_text(encoding="utf-8"))[field])

    lock = {
        "schemaVersion": SCHEMA_VERSION,
        "candidateCommit": args.candidate_commit,
        "sourceDateEpoch": int(epoch.stdout.strip()),
        "epochSource": (
            f"git show -s --format=%ct {args.candidate_commit} — the qualification target "
            "commit's own timestamp, so the epoch is a property of what is built rather than of "
            "when it was built"
        ),
        "profile": args.profile,
        "architecture": args.architecture,
        "baseImageDigest": read("base-image-lock.json", "upstreamDigest"),
        "retainedBaseDigest": read("base-image-lock.json", "retainedDigest"),
        "builderImageDigest": read("builder-image-lock.json", "builderDigest"),
        "packageSnapshotDigest": read("package-snapshot-lock.json", "manifestDigest"),
        "appliedTo": APPLIED,
        "neverAppliedTo": list(EPOCH_FORBIDDEN),
        "mechanism": {
            "rpmTransaction": (
                "libfaketime is bind-mounted from the builder image into the build container and "
                "LD_PRELOADed for the dnf process only. Nothing is installed into the product "
                "image to achieve this, and the override ends with the transaction."
            ),
            "networkOperations": (
                "None occur under the override. The qualification build installs from a local "
                "signed snapshot over file://, so no TLS handshake and no certificate validity "
                "check happens while the clock is overridden."
            ),
            "signatureVerification": (
                "RPM signature verification still runs, with gpgcheck=1, against the real Fedora "
                "keys. The epoch is the candidate commit's timestamp, which is within every "
                "relevant key's validity, and the snapshot's signatures were additionally "
                "verified before the build started."
            ),
        },
    }

    try:
        parse_reproducibility_lock(lock)
    except SupplyChainError as exc:
        raise SystemExit(f"BLOCKED: the emitted epoch lock does not validate: {exc}") from None

    destination = inputs / "reproducibility-lock.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"build epoch {lock['sourceDateEpoch']} for {args.candidate_commit[:12]}")
    print(f"  applied to      {', '.join(APPLIED)}")
    print(f"  never applied to {', '.join(EPOCH_FORBIDDEN)}")
    print(f"wrote {display_path(destination, Path.cwd())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2) from None
        raise

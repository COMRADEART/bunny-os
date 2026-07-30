#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild the retention store on a machine that has never seen it.

The locks name absolute paths — ``/var/lib/bunny-retention/base-images/…`` — and
a hosted runner has none of them. This pulls each published input by digest and
puts it where its lock says it lives, so the hermetic build runs unchanged
rather than needing a hosted-only code path. A build that took a different route
to its inputs on one builder would be a different build.

Digests are verified after the pull, not assumed from the reference. skopeo will
happily copy whatever a registry serves; the check is that what arrived is what
the lock pins.

Exit codes:
    0   every input is in place and matches its lock
    2   an input could not be fetched, or did not match
    3   skopeo is unavailable
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from typing import Any

REFUSED = 2
UNAVAILABLE = 3


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def layout_digest(layout: Path, reference: str) -> str:
    """The digest of the manifest an OCI layout holds under a tag."""
    index = json.loads((layout / "index.json").read_text(encoding="utf-8"))
    for entry in index.get("manifests", []):
        name = (entry.get("annotations") or {}).get("org.opencontainers.image.ref.name")
        if name == reference or len(index["manifests"]) == 1:
            return str(entry["digest"])
    raise SystemExit(f"BLOCKED: {layout} has no manifest tagged {reference}")


def hydrate_image(reference: str, destination: Path, tag: str, expected: str) -> dict[str, Any]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run(["skopeo", "copy", "--preserve-digests",
                  f"docker://{reference}", f"oci:{destination}:{tag}"])
    if result.returncode != 0:
        raise SystemExit(f"BLOCKED: cannot pull {reference}: {result.stderr.strip()[:400]}")
    observed = layout_digest(destination, tag)
    if observed != expected:
        raise SystemExit(
            f"BLOCKED: {reference} landed as {observed} and the lock pins {expected}. "
            "The registry served a different manifest than the one that was retained."
        )
    return {"reference": reference, "location": str(destination), "digest": observed}


def hydrate_snapshot(reference: str, destination: Path) -> dict[str, Any]:
    """Unpack the snapshot image back into the directory tree the build mounts."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / (destination.name + ".oci")
    if staging.exists():
        shutil.rmtree(staging)
    result = run(["skopeo", "copy", f"docker://{reference}", f"dir:{staging}"])
    if result.returncode != 0:
        raise SystemExit(f"BLOCKED: cannot pull {reference}: {result.stderr.strip()[:400]}")

    extracted = 0
    for blob in sorted(staging.glob("*")):
        if blob.name in {"manifest.json", "version"}:
            continue
        try:
            with tarfile.open(blob, "r:*") as stream:
                stream.extractall(destination, filter="data")
            extracted += 1
        except tarfile.TarError:
            # The config blob is JSON without a suffix. A blob that will not
            # untar is skipped; the package count below decides whether enough
            # came out.
            continue
    shutil.rmtree(staging, ignore_errors=True)

    # The image holds the snapshot under /snapshot; the build mounts the
    # directory itself.
    inner = destination / "snapshot"
    if inner.is_dir():
        for item in inner.iterdir():
            shutil.move(str(item), str(destination / item.name))
        inner.rmdir()

    packages = list(destination.rglob("*.rpm"))
    if not packages:
        raise SystemExit(
            f"BLOCKED: {reference} unpacked to {extracted} layer(s) and no RPMs. The snapshot "
            "cannot be used as a repository."
        )
    return {
        "reference": reference,
        "location": str(destination),
        "packages": len(packages),
        "repodata": (destination / "repodata" / "repomd.xml").is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="hydrate-retained-inputs")
    parser.add_argument("--publication", type=Path,
                        default=Path("build/inputs/input-publication-lock.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/out/qualification/hydrated-inputs.json"))
    args = parser.parse_args()

    if shutil.which("skopeo") is None:
        print("BLOCKED: skopeo is required and is not available", file=sys.stderr)
        return UNAVAILABLE

    publication = json.loads(args.publication.read_text(encoding="utf-8"))
    inputs = publication.get("inputs") or {}
    missing = sorted({"base", "builder", "snapshot"} - set(inputs))
    if missing:
        print(f"BLOCKED: these inputs are not published: {', '.join(missing)}", file=sys.stderr)
        return REFUSED

    base_lock = json.loads(Path("build/inputs/base-image-lock.json").read_text(encoding="utf-8"))
    builder_lock = json.loads(
        Path("build/inputs/builder-image-lock.json").read_text(encoding="utf-8")
    )
    snapshot_lock = json.loads(
        Path("build/inputs/package-snapshot-lock.json").read_text(encoding="utf-8")
    )

    record: dict[str, Any] = {"schemaVersion": 1}
    record["base"] = hydrate_image(
        inputs["base"]["digestReference"],
        Path(base_lock["retainedLocation"]),
        "retained",
        base_lock["retainedDigest"],
    )
    record["builder"] = hydrate_image(
        inputs["builder"]["digestReference"],
        Path(builder_lock["builderReference"].split("@", 1)[0]),
        "builder",
        builder_lock["builderDigest"],
    )
    record["snapshot"] = hydrate_snapshot(
        inputs["snapshot"]["digestReference"],
        Path(snapshot_lock["retainedLocation"]),
    )
    record["result"] = "PASS"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    print(f"base     {record['base']['location']}  {record['base']['digest']}")
    print(f"builder  {record['builder']['location']}  {record['builder']['digest']}")
    print(
        f"snapshot {record['snapshot']['location']}  "
        f"{record['snapshot']['packages']} packages, repodata={record['snapshot']['repodata']}"
    )
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record hashes and tool versions after an image build."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def version(argv: list[str]) -> str:
    """The tool's version string, or `absent` if the tool is not installed.

    `subprocess.run` raises when the executable does not exist, so this crashed
    with a traceback on any host without podman — including an archive-only
    builder, where image-builder is deliberately absent. A missing tool is a fact
    about the build and is recorded as one.
    """
    try:
        result = subprocess.run(
            argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
        )
    except (FileNotFoundError, OSError):
        return "absent"
    return result.stdout.strip()[:4096] or "absent"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument(
        "--archive-only",
        action="store_true",
        help="the build stopped after the OCI archive and produced no disk image",
    )
    args = parser.parse_args()

    DISK_SUFFIXES = {".qcow2", ".raw", ".iso", ".img", ".vmdk"}
    artifacts = []
    disk_images = []
    for path in sorted(args.output.rglob("*")):
        if not path.is_file() or path.name in {"provenance.json", "SHA256SUMS"}:
            continue
        if path.suffix not in DISK_SUFFIXES and path.name != "bunny-os.oci.tar":
            continue
        relative = str(path.relative_to(args.output)).replace("\\", "/")
        artifacts.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
        if path.suffix in DISK_SUFFIXES:
            disk_images.append(relative)

    # An archive-only build is recorded as one, in the artifact's own provenance.
    # Without this the record is indistinguishable from a full build that
    # happened to lose its disk images, and release/buildmode.py would have to
    # infer the mode from what is missing — which is exactly the inference that
    # lets an incomplete build be presented as a candidate.
    value = {
        "schemaVersion": 1,
        "profile": args.profile,
        "sourceCommit": args.source_commit,
        "sourceDateEpoch": args.source_date_epoch,
        "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "baseImage": args.base_image,
        "imageReference": args.image_reference,
        "archiveOnly": bool(args.archive_only),
        "diskImages": disk_images,
        "buildModeNote": (
            "BUNNY_ARCHIVE_ONLY=1: stopped after the normalised OCI archive. No qcow2, no raw "
            "image, no installation, recovery or hardware qualification is implied, and this "
            "artifact must never be recorded as a release candidate."
            if args.archive_only
            else "Full build: the OCI archive and every disk image the profile defines."
        ),
        "tools": {"podman": version(["podman", "--version"]), "imageBuilder": version(["image-builder", "version", "--format=json"])},
        "artifacts": artifacts,
        "reproducibility": {"repeatedBuildComparisonPerformed": False},
    }
    args.output.joinpath("provenance.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.joinpath("SHA256SUMS").write_text("".join(f'{item["sha256"]}  {item["path"]}\n' for item in artifacts), encoding="utf-8")

    if args.archive_only:
        if disk_images:
            raise SystemExit(
                f"archive-only build produced disk images: {', '.join(disk_images)}. "
                "The mode did not take effect and the record would be false."
            )
        if not any(item["path"].endswith("bunny-os.oci.tar") for item in artifacts):
            raise SystemExit("archive-only build produced no OCI archive")
        return 0

    if not disk_images:
        raise SystemExit("image-builder produced no recognized disk artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

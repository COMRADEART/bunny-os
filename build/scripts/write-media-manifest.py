#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a deterministic checksum manifest for completed media artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


DISK_SUFFIXES = {".iso", ".qcow2", ".raw", ".img", ".vmdk"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_provenance(
    root: Path, source_commit: str, files: list[dict[str, Any]]
) -> None:
    """Refuse a media manifest that would bless stale artifact provenance."""

    provenance_path = root / "provenance.json"
    if not provenance_path.is_file():
        return

    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read artifact provenance: {error}") from error

    if provenance.get("sourceCommit") != source_commit:
        raise SystemExit("artifact provenance source commit does not match the media manifest")

    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("artifact provenance has no artifacts list")

    hashed = {str(item["path"]): item for item in files}
    actual_artifacts = {
        path
        for path in hashed
        if PurePosixPath(path).suffix.lower() in DISK_SUFFIXES
        or PurePosixPath(path).name == "bunny-os.oci.tar"
    }
    declared: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SystemExit(f"artifact provenance entry {index} has no valid path")
        value = item["path"]
        relative = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != value
        ):
            raise SystemExit(f"artifact provenance contains an unsafe path: {value!r}")
        if value in declared:
            raise SystemExit(f"artifact provenance repeats a path: {value}")
        declared[value] = item

    declared_artifacts = set(declared)
    if declared_artifacts != actual_artifacts:
        missing = sorted(actual_artifacts - declared_artifacts)
        stale = sorted(declared_artifacts - actual_artifacts)
        raise SystemExit(
            "artifact provenance disagrees with the final media tree: "
            f"missing={missing}, stale={stale}"
        )

    actual_disks = sorted(
        path
        for path in actual_artifacts
        if PurePosixPath(path).suffix.lower() in DISK_SUFFIXES
    )
    if provenance.get("diskImages") != actual_disks:
        raise SystemExit("artifact provenance diskImages do not match the final media tree")

    for path, item in declared.items():
        target = root.joinpath(*PurePosixPath(path).parts)
        if item.get("size") != target.stat().st_size:
            raise SystemExit(f"artifact provenance size does not match: {path}")
        if item.get("sha256") != hashed[path]["sha256"]:
            raise SystemExit(f"artifact provenance digest does not match: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image-version", required=True)
    args = parser.parse_args()
    files = []
    excluded = {"BUNNY-MANIFEST.json", "BUNNY-MANIFEST.json.sig"}
    for path in sorted(args.root.rglob("*")):
        if not path.is_file() or path.name in excluded or path.is_symlink():
            continue
        relative = path.relative_to(args.root).as_posix()
        critical = path.suffix.lower() in DISK_SUFFIXES or path.name in {
            "provenance.json",
            "SHA256SUMS",
            "checksums.sha256",
        }
        files.append({"path": relative, "sha256": digest(path), "critical": critical})
    if not files:
        raise SystemExit("no media artifacts found")
    validate_provenance(args.root, args.source_commit, files)
    payload = {"schemaVersion": 1, "imageVersion": args.image_version, "sourceCommit": args.source_commit, "files": files}
    target = args.root / "BUNNY-MANIFEST.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3
"""Record hashes and tool versions after an image build."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def version(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return result.stdout.strip()[:4096]


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
    args = parser.parse_args()
    artifacts = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file() and path.name not in {"provenance.json", "SHA256SUMS"} and (path.suffix in {".qcow2", ".raw", ".iso", ".vmdk"} or path.name == "bunny-os.oci.tar"):
            digest = sha256(path)
            artifacts.append({"path": str(path.relative_to(args.output)), "size": path.stat().st_size, "sha256": digest})
    value = {
        "schemaVersion": 1,
        "profile": args.profile,
        "sourceCommit": args.source_commit,
        "sourceDateEpoch": args.source_date_epoch,
        "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "baseImage": args.base_image,
        "imageReference": args.image_reference,
        "tools": {"podman": version(["podman", "--version"]), "imageBuilder": version(["image-builder", "version", "--format=json"])},
        "artifacts": artifacts,
        "reproducibility": {"repeatedBuildComparisonPerformed": False},
    }
    args.output.joinpath("provenance.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.joinpath("SHA256SUMS").write_text("".join(f'{item["sha256"]}  {item["path"]}\n' for item in artifacts), encoding="utf-8")
    if not artifacts:
        raise SystemExit("image-builder produced no recognized disk artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

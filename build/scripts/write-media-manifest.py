#!/usr/bin/python3
"""Write a deterministic checksum manifest for completed media artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


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
        critical = path.suffix.lower() in {".iso", ".qcow2", ".raw", ".img"} or path.name in {"provenance.json", "checksums.sha256"}
        files.append({"path": relative, "sha256": digest(path), "critical": critical})
    if not files:
        raise SystemExit("no media artifacts found")
    payload = {"schemaVersion": 1, "imageVersion": args.image_version, "sourceCommit": args.source_commit, "files": files}
    target = args.root / "BUNNY-MANIFEST.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

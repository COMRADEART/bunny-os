#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify stable-candidate structure, file hashes, and detached manifest signature."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from operations.candidate import validate_candidate


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.candidate / "STABLE-CANDIDATE.json"
    signature_path = args.candidate / "STABLE-CANDIDATE.json.sig"
    if not manifest_path.is_file() or not signature_path.is_file() or not args.public_key.is_file():
        raise SystemExit("candidate manifest, detached signature, and public key are required")
    manifest = validate_candidate(json.loads(manifest_path.read_text(encoding="utf-8")))
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("openssl is required")
    for artifact in manifest["artifacts"]:
        path = (args.candidate / artifact["path"]).resolve()
        if args.candidate.resolve() not in path.parents or not path.is_file() or path.is_symlink():
            raise SystemExit(f"candidate artifact path is unsafe or absent: {artifact['path']}")
        if sha256(path) != artifact["sha256"]:
            raise SystemExit(f"candidate artifact checksum mismatch: {artifact['path']}")
        artifact_signature = path.with_name(path.name + ".sig")
        if not artifact_signature.is_file() or artifact_signature.is_symlink():
            raise SystemExit(f"candidate artifact detached signature is absent: {artifact['path']}")
        artifact_result = subprocess.run(
            [openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(args.public_key), "-rawin", "-in", str(path), "-sigfile", str(artifact_signature)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if artifact_result.returncode:
            raise SystemExit(f"candidate artifact signature verification failed: {artifact['path']}")
    result = subprocess.run(
        [openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(args.public_key), "-rawin", "-in", str(manifest_path), "-sigfile", str(signature_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise SystemExit("candidate detached signature verification failed")
    print("stable candidate structure, hashes, and manifest signature verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sign every stable-candidate artifact and the immutable candidate manifest."""

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


def safe_artifact(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
        raise SystemExit(f"candidate artifact path is unsafe or absent: {relative}")
    return path


def sign(openssl: str, key: Path, source: Path, destination: Path) -> None:
    result = subprocess.run(
        [openssl, "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(source), "-out", str(destination)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    if result.returncode:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"failed to sign {source.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    key = args.private_key.resolve()
    if not key.is_file():
        raise SystemExit("BUNNY_STABLE_SIGNING_KEY must name an external protected private key")
    try:
        key.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("private signing keys must not be stored in the repository")
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("missing openssl")
    manifest_path = candidate / "STABLE-CANDIDATE.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SystemExit("missing stable candidate manifest")
    manifest = validate_candidate(json.loads(manifest_path.read_text(encoding="utf-8")))
    for artifact in manifest["artifacts"]:
        path = safe_artifact(candidate, artifact["path"])
        if sha256(path) != artifact["sha256"]:
            raise SystemExit(f"candidate artifact checksum mismatch: {artifact['path']}")
        sign(openssl, key, path, path.with_name(path.name + ".sig"))
    sign(openssl, key, manifest_path, manifest_path.with_name(manifest_path.name + ".sig"))
    print("signed all candidate artifacts and the candidate manifest; independent verification and approvals remain required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

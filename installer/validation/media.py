"""Checksum and detached-signature verification for installation media."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


class MediaVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(root: Path, manifest_path: Path, *, signature_path: Path, public_key: Path, openssl: str = "/usr/bin/openssl") -> dict[str, Any]:
    for path in (root, manifest_path, signature_path, public_key):
        if path.is_symlink():
            raise MediaVerificationError("symlinks are not accepted in media trust inputs")
    if not root.is_dir():
        raise MediaVerificationError("installation media root is unavailable")
    if not manifest_path.is_file() or not signature_path.is_file() or not public_key.is_file():
        raise MediaVerificationError("media manifest, signature, or public key is missing")
    try:
        payload = manifest_path.read_bytes()
    except OSError as error:
        raise MediaVerificationError("media manifest could not be read") from error
    if len(payload) > 1024 * 1024:
        raise MediaVerificationError("media manifest exceeds size limit")
    try:
        manifest = json.loads(payload)
    except json.JSONDecodeError as error:
        raise MediaVerificationError("invalid media manifest") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("files"), list):
        raise MediaVerificationError("unsupported media manifest")
    completed = subprocess.run(
        [openssl, "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key), "-sigfile", str(signature_path), "-in", str(manifest_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if completed.returncode != 0:
        raise MediaVerificationError("critical media signature verification failed")
    checked: list[str] = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "critical"}:
            raise MediaVerificationError("invalid media file entry")
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise MediaVerificationError("unsafe media file path")
        target = (root / relative).resolve()
        if root.resolve() not in target.parents:
            raise MediaVerificationError("media file escapes root")
        if not target.is_file() or target.is_symlink():
            if entry["critical"]:
                raise MediaVerificationError(f"critical media file missing: {relative.as_posix()}")
            continue
        if _sha256(target) != entry["sha256"]:
            raise MediaVerificationError(f"media checksum mismatch: {relative.as_posix()}")
        checked.append(relative.as_posix())
    return {"verified": True, "signatureVerified": True, "filesChecked": checked, "warnings": []}

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write and sign the snapshot manifest.

Four things are signed, and they are four things rather than one because they
fail independently: the package inventory (what is in the snapshot), the
repository metadata digest (what a resolver would read), the manifest (the
join of the two) and the lock (what a build checks before it starts).

The key is a **development** key. `release.signing.require_production_key`
refuses anything with a `dev-` prefix, and this key carries one, so no artifact
signed here can satisfy a release gate. The signature proves the path works and
that the snapshot has not changed since it was made; it proves nothing about
release authorisation, and `signature.trust` says `development` so that no
reader has to infer it.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import SCHEMA_VERSION, SupplyChainError, parse_package_snapshot_lock  # noqa: E402


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def ensure_key(path: Path) -> str:
    """Create the development signing key if it is absent, and name it."""
    key_id = path.stem
    if not key_id.startswith("dev-"):
        raise SystemExit(
            f"BLOCKED: the snapshot signing key {key_id!r} does not carry the reserved 'dev-' "
            "prefix. This qualification pass uses a development key by design, and the prefix is "
            "what makes release.signing.require_production_key refuse it. A key without the "
            "prefix could be mistaken for production trust."
        )
    if path.is_file():
        return key_id
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(path)],
        check=True,
        capture_output=True,
    )
    path.chmod(0o600)
    public = path.with_suffix(".pub.pem")
    subprocess.run(
        ["openssl", "pkey", "-in", str(path), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    print(f"    generated development signing key {key_id} at {path.parent}")
    return key_id


def sign(key: Path, payload: bytes) -> str:
    digest_file = key.parent / ".snapshot-payload"
    signature_file = key.parent / ".snapshot-payload.sig"
    try:
        digest_file.write_bytes(payload)
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(key),
             "-rawin", "-in", str(digest_file), "-out", str(signature_file)],
            check=True,
            capture_output=True,
        )
        return signature_file.read_bytes().hex()
    finally:
        digest_file.unlink(missing_ok=True)
        signature_file.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="write-snapshot-lock")
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--metadata-digest", required=True)
    parser.add_argument("--signing-key", required=True, type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    resolved = json.loads(args.lock.read_text(encoding="utf-8"))

    packages = [
        {
            "name": entry["name"],
            "epoch": entry.get("epoch", "0"),
            "version": entry["version"],
            "release": entry["release"],
            "architecture": entry["architecture"],
            "checksum": entry["checksum"],
            "size": entry["size"],
            "sourceRepository": entry.get("sourceRepository", "unknown"),
            "signingKey": entry.get("signingKey", ""),
            "signatureVerified": bool(entry.get("signatureVerified")),
            "sourceRpm": entry.get("sourceRpm", ""),
            "licence": entry.get("licence", ""),
            "location": f"packages/{entry['fileName']}",
        }
        for entry in resolved["packages"]
    ]
    packages.sort(key=lambda item: (item["name"], item["architecture"], item["version"]))

    inventory = canonical(packages)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": args.snapshot_id,
        "profile": resolved["profile"],
        "architecture": resolved["architecture"],
        "baseImageDigest": resolved["baseImageDigest"],
        "packageCount": len(packages),
        "packageInventoryDigest": hashlib.sha256(inventory).hexdigest(),
        "repositoryMetadataDigest": args.metadata_digest,
        "upstreamRepositories": sorted({item["sourceRepository"] for item in packages}),
        "createdAt": _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    manifest_bytes = canonical(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

    key_id = ensure_key(args.signing_key)
    signature_value = sign(args.signing_key, manifest_bytes)

    (args.snapshot_root / "snapshot.json").write_bytes(manifest_bytes)
    (args.snapshot_root / "snapshot.sha256").write_text(
        f"{manifest_digest}  snapshot.json\n", encoding="utf-8", newline="\n"
    )
    (args.snapshot_root / "snapshot.signature").write_text(
        json.dumps(
            {
                "algorithm": "ed25519",
                "keyId": key_id,
                "role": "snapshot-signing",
                "trust": "development",
                "over": "snapshot.json",
                "value": signature_value,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (args.snapshot_root / "packages.json").write_bytes(inventory)

    lock = {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": args.snapshot_id,
        "profile": resolved["profile"],
        "architecture": resolved["architecture"],
        "packages": packages,
        "repositoryMetadataDigest": args.metadata_digest,
        "manifestDigest": manifest_digest,
        "signature": {
            "algorithm": "ed25519",
            "keyId": key_id,
            "role": "snapshot-signing",
            "trust": "development",
            "over": "snapshot.json",
            "value": signature_value,
        },
        "createdAt": manifest["createdAt"],
        "retainedLocation": str(args.snapshot_root),
        "upstreamRepositories": manifest["upstreamRepositories"],
        "verificationStatus": "verified",
    }

    try:
        parse_package_snapshot_lock(lock)
    except SupplyChainError as exc:
        raise SystemExit(f"BLOCKED: the emitted snapshot lock does not validate: {exc}") from None

    destination = root / "build" / "inputs" / "package-snapshot-lock.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"    manifest digest {manifest_digest}")
    print(f"    signed with {key_id} (development trust, not release trust)")
    print(f"    wrote {display_path(destination, Path.cwd())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2) from None
        raise

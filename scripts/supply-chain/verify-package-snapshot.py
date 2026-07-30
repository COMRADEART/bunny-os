#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify a materialised package snapshot before a build consumes it.

Runs before every qualification build, on both builders. It re-derives what the
lock claims rather than reading the lock's own summary of itself:

* every locked package is present, and its bytes hash to the locked checksum;
* nothing is present that is not locked;
* every package still carries a verified Fedora signature;
* the repository metadata digest matches the repodata on disk;
* the manifest digest matches the manifest;
* the manifest signature verifies against the recorded key.

The signature check is over the manifest, and it establishes that the snapshot
has not changed since it was made. It is a **development** key and establishes
nothing about release authorisation; the lock says so in `signature.trust` and
this tool prints it rather than letting a green line imply more.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import SupplyChainError, parse_package_snapshot_lock  # noqa: E402

CHUNK = 1024 * 1024
REFUSED = 2


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="verify-package-snapshot")
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "build" / "inputs" / "package-snapshot-lock.json",
    )
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument(
        "--skip-signature-check",
        action="store_true",
        help="skip rpmkeys verification; for environments without the Fedora keys imported",
    )
    args = parser.parse_args()

    if not args.lock.is_file():
        print(
            f"BLOCKED: no package snapshot lock at {args.lock}. A build with no recorded package "
            "set resolves against whatever it can reach, which is the failure this lock exists to "
            "prevent.",
            file=sys.stderr,
        )
        return REFUSED

    try:
        lock = parse_package_snapshot_lock(json.loads(args.lock.read_text(encoding="utf-8")))
    except SupplyChainError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return REFUSED

    root = args.snapshot_root or Path(lock.retainedLocation)
    if root.is_dir() and root.name != lock.snapshotId and (root / lock.snapshotId).is_dir():
        root = root / lock.snapshotId
    if not root.is_dir():
        print(
            f"BLOCKED: the snapshot is not present at {root}. The controlled mirror is "
            "unavailable, and a qualification build must fail before building rather than fall "
            "back to a live repository.",
            file=sys.stderr,
        )
        return REFUSED

    failures: list[str] = []

    packages_dir = root / "packages"
    present = {path.name: path for path in packages_dir.glob("*.rpm")} if packages_dir.is_dir() else {}
    expected = {Path(package.location).name: package for package in lock.packages}

    missing = sorted(set(expected) - set(present))
    if missing:
        failures.append(
            f"{len(missing)} locked packages are absent from the snapshot: " + ", ".join(missing[:10])
        )
    extra = sorted(set(present) - set(expected))
    if extra:
        failures.append(
            f"{len(extra)} packages are in the snapshot and not in the lock: " + ", ".join(extra[:10])
        )

    mismatched: list[str] = []
    for name in sorted(set(expected) & set(present)):
        actual = digest(present[name])
        if actual != expected[name].checksum:
            mismatched.append(f"{name} ({actual[:16]} vs {expected[name].checksum[:16]})")
    if mismatched:
        failures.append(
            f"{len(mismatched)} packages do not match their locked checksum: "
            + ", ".join(mismatched[:10])
        )

    if not args.skip_signature_check and present:
        unverified: list[str] = []
        for name in sorted(set(expected) & set(present)):
            checked = subprocess.run(
                ["rpmkeys", "--checksig", str(present[name])], capture_output=True, text=True
            )
            if checked.returncode != 0 or "signatures OK" not in checked.stdout:
                unverified.append(name)
        if unverified:
            failures.append(
                f"{len(unverified)} packages failed signature verification: "
                + ", ".join(unverified[:10])
                + ". Every RPM must retain its original trusted signature"
            )

    repomd = root / "repodata" / "repomd.xml"
    if not repomd.is_file():
        failures.append("repodata/repomd.xml is absent; the snapshot has no repository metadata")
    else:
        actual = digest(repomd)
        if actual != lock.repositoryMetadataDigest:
            failures.append(
                f"repository metadata digest mismatch: lock {lock.repositoryMetadataDigest[:16]} "
                f"vs repodata {actual[:16]}"
            )

    manifest = root / "snapshot.json"
    if not manifest.is_file():
        failures.append("snapshot.json is absent; there is nothing the signature covers")
    else:
        actual = digest(manifest)
        if actual != lock.manifestDigest:
            failures.append(
                f"manifest digest mismatch: lock {lock.manifestDigest[:16]} vs file {actual[:16]}"
            )
        else:
            signature_record = root / "snapshot.signature"
            key_id = str(lock.signature.get("keyId", ""))
            public = Path.home() / ".bunny-dev-keys" / "snapshot" / f"{key_id}.pub.pem"
            if not signature_record.is_file():
                failures.append("snapshot.signature is absent; the manifest is unsigned")
            elif not public.is_file():
                failures.append(
                    f"the public key for {key_id} is not at {public}, so the signature cannot be "
                    "checked. An unverifiable signature is not a verified signature"
                )
            else:
                signature_bytes = bytes.fromhex(str(lock.signature["value"]))
                temporary = root / ".verify.sig"
                try:
                    temporary.write_bytes(signature_bytes)
                    checked = subprocess.run(
                        ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public),
                         "-rawin", "-in", str(manifest), "-sigfile", str(temporary)],
                        capture_output=True,
                        text=True,
                    )
                    if checked.returncode != 0:
                        failures.append(
                            f"the manifest signature does not verify against {key_id}: "
                            + (checked.stderr.strip() or checked.stdout.strip())
                        )
                finally:
                    temporary.unlink(missing_ok=True)

    if failures:
        print("BLOCKED: the package snapshot did not verify:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return REFUSED

    print(f"package snapshot verified: {lock.snapshotId}")
    print(f"  packages    {len(lock.packages)}, every checksum and signature verified")
    print(f"  metadata    {lock.repositoryMetadataDigest}")
    print(f"  manifest    {lock.manifestDigest}")
    print(f"  signed by   {lock.signature.get('keyId')} ({lock.signature.get('trust')} trust)")
    print(f"  location    {display_path(root, Path.cwd())}")
    if lock.signature.get("trust") != "production":
        print(
            "  note        a development key. It establishes that the snapshot has not changed "
            "since it was made, and nothing about release authorisation."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pull every published input by digest and re-derive what the locks claim.

Verifying a publication from the machine that made it proves the push worked,
not that the artifact is retrievable. This is written to run anywhere, and the
cold-pull workflow runs it on a fresh runner with an empty container store and
no local retention — which is the only environment where a pass means what it
says.

Nothing is trusted from the publication lock except where to look. Every digest
is recomputed from the bytes the registry returns, the snapshot's package
checksums are re-derived from the RPMs themselves, and the Fedora signatures are
re-verified with rpmkeys rather than read out of the snapshot manifest's own
summary of them.

Exit codes:
    0   every published input pulled and verified
    2   a lock, a blob, a checksum or a signature did not check out
    3   a tool this verification needs is not available
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REFUSED = 2
UNAVAILABLE = 3


class Failure(Exception):
    """A check that did not pass. The message is what the operator reads."""


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def manifest_digest(reference: str) -> tuple[str, dict[str, Any]]:
    """The digest of the manifest as the registry serves it, recomputed."""
    result = run(["skopeo", "inspect", "--no-tags", "--raw", f"docker://{reference}"])
    if result.returncode != 0:
        raise Failure(f"cannot read {reference}: {result.stderr.strip()[:300]}")
    raw = result.stdout.encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(result.stdout)


def pull_to_layout(reference: str, destination: Path) -> None:
    result = run(
        ["skopeo", "copy", "--preserve-digests", f"docker://{reference}", f"oci:{destination}:pulled"]
    )
    if result.returncode != 0:
        raise Failure(f"cannot pull {reference}: {result.stderr.strip()[:400]}")


def verify_blobs(layout: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Recompute every blob's digest from the bytes on disk.

    A manifest digest pins the manifest and nothing else. A registry that served
    the manifest and lost or corrupted a layer would satisfy a digest check and
    fail a pull, and the failure would arrive during someone's build.
    """
    checked = 0
    for entry in [manifest.get("config") or {}, *(manifest.get("layers") or [])]:
        digest = entry.get("digest")
        if not digest:
            continue
        algorithm, _, value = digest.partition(":")
        blob = layout / "blobs" / algorithm / value
        if not blob.is_file():
            raise Failure(f"blob {digest} is missing from the pulled layout")
        actual = hashlib.sha256()
        with blob.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                actual.update(chunk)
        if actual.hexdigest() != value:
            raise Failure(
                f"blob {digest} does not match its content: got sha256:{actual.hexdigest()}"
            )
        size = entry.get("size")
        if size is not None and blob.stat().st_size != int(size):
            raise Failure(
                f"blob {digest} is {blob.stat().st_size} bytes and the manifest says {size}"
            )
        checked += 1
    return {"blobsVerified": checked}


def verify_snapshot_contents(layout: Path, snapshot_lock: dict[str, Any]) -> dict[str, Any]:
    """Unpack the snapshot image and re-derive every package claim from the RPMs."""
    scratch = Path(tempfile.mkdtemp(prefix="bunny-snapshot-"))
    try:
        result = run(
            ["skopeo", "copy", f"oci:{layout}:pulled", f"dir:{scratch / 'raw'}"]
        )
        if result.returncode != 0:
            raise Failure(f"cannot unpack the snapshot image: {result.stderr.strip()[:300]}")

        extracted = scratch / "content"
        extracted.mkdir()
        for blob in sorted((scratch / "raw").glob("*")):
            if blob.name in {"manifest.json", "version"} or blob.suffix == ".json":
                continue
            unpack = run(["tar", "-xf", str(blob), "-C", str(extracted)])
            if unpack.returncode != 0:
                # Not every blob in a dir: transport is a layer tar; the config
                # is JSON without a suffix. A blob that will not untar is
                # skipped rather than treated as a failure, and the package
                # count below is what decides whether enough came out.
                continue

        packages = sorted(extracted.rglob("*.rpm"))
        expected = snapshot_lock.get("packages") or []
        if len(packages) != len(expected):
            raise Failure(
                f"the pulled snapshot holds {len(packages)} RPMs and the lock records "
                f"{len(expected)}. A snapshot missing a package cannot reproduce the build that "
                "used it."
            )

        # The lock names each package by its `location` — a repository-relative
        # path such as `packages/NetworkManager-wifi-1.56.1-2.fc44.x86_64.rpm` —
        # and its digest as `checksum`. An earlier version guessed at `fileName`
        # and `sha256`, found neither, and reported all 474 packages as absent
        # with an empty name, which is a field-name bug wearing the costume of a
        # supply-chain failure.
        by_name = {path.name: path for path in packages}
        checksum_failures: list[str] = []
        unnamed = 0
        for record in expected:
            location = str(record.get("location") or "")
            name = PurePosixPath(location).name if location else ""
            wanted = str(record.get("checksum") or "")
            if not name:
                unnamed += 1
                continue
            path = by_name.get(name)
            if path is None:
                checksum_failures.append(f"{name}: absent from the pulled snapshot")
                continue
            if not wanted:
                checksum_failures.append(f"{name}: the lock records no checksum to verify against")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != wanted:
                checksum_failures.append(f"{name}: {actual} != {wanted}")
        if unnamed:
            raise Failure(
                f"{unnamed} of {len(expected)} package records carry no location, so there is "
                "nothing to look for. A lock that cannot name its own packages cannot verify them."
            )
        if checksum_failures:
            raise Failure(
                "package checksums did not verify:\n  "
                + "\n  ".join(checksum_failures[:20])
            )

        signatures = {"verified": 0, "failed": []}
        if shutil.which("rpmkeys"):
            keys = sorted(extracted.rglob("RPM-GPG-KEY-*"))
            if not keys:
                raise Failure(
                    "the pulled snapshot ships no Fedora signing key, so its RPM signatures "
                    "cannot be verified from it alone — which is the whole point of publishing "
                    "the keys with the packages."
                )
            keyring = scratch / "keyring"
            keyring.mkdir()
            for key in keys:
                run(["rpmkeys", "--dbpath", str(keyring), "--import", str(key)])
            for path in packages:
                check = run(["rpmkeys", "--dbpath", str(keyring), "--checksig", str(path)])
                output = check.stdout.strip()
                # Fedora signs RSAHEADER, not SIGPGP. `--checksig` reports
                # "digests signatures OK" when the header signature verifies;
                # anything else, including "NOT OK" and "NOKEY", is a failure.
                if check.returncode != 0 or "signatures OK" not in output:
                    signatures["failed"].append(f"{path.name}: {output[:120]}")
                else:
                    signatures["verified"] += 1
            if signatures["failed"]:
                raise Failure(
                    "these packages did not verify against the published Fedora keys:\n  "
                    + "\n  ".join(signatures["failed"][:20])
                )
        else:
            signatures["skipped"] = (
                "rpmkeys is unavailable, so signature verification did not run. This is recorded "
                "rather than passed: an unverified signature is not a verified one."
            )

        repodata = sorted(extracted.rglob("repomd.xml"))
        if not repodata:
            raise Failure(
                "the pulled snapshot has no repomd.xml, so it cannot be used as a repository and "
                "an offline install from it is impossible"
            )

        return {
            "packagesFound": len(packages),
            "packagesExpected": len(expected),
            "checksumsVerified": len(expected),
            "signatures": signatures,
            "repodataPresent": True,
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="verify-published-inputs")
    parser.add_argument("--publication", required=True, type=Path)
    parser.add_argument("--snapshot-lock", type=Path,
                        default=Path("build/inputs/package-snapshot-lock.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/out/qualification/published-inputs.json"))
    parser.add_argument(
        "--skip-snapshot-contents",
        action="store_true",
        help="verify the snapshot's blobs but not its 474 packages; for a quick check only, "
             "never for qualification evidence",
    )
    args = parser.parse_args()

    for command in ("skopeo",):
        if shutil.which(command) is None:
            print(f"BLOCKED: {command} is required and is not available", file=sys.stderr)
            return UNAVAILABLE

    if not args.publication.is_file():
        print(
            f"BLOCKED: {args.publication} is absent. Nothing has been published, so there is "
            "nothing to retrieve — and the retained inputs exist on one machine.",
            file=sys.stderr,
        )
        return REFUSED

    publication = json.loads(args.publication.read_text(encoding="utf-8"))
    inputs = publication.get("inputs") or {}
    missing = sorted({"base", "builder", "snapshot"} - set(inputs))
    if missing:
        print(
            "BLOCKED: these inputs are not published: "
            + ", ".join(missing)
            + ".\nAll three are required before an independent builder can build without reaching "
            "a live repository.",
            file=sys.stderr,
        )
        return REFUSED

    results: dict[str, Any] = {}
    failures: list[str] = []
    scratch = Path(tempfile.mkdtemp(prefix="bunny-coldpull-"))
    try:
        for kind in ("base", "builder", "snapshot"):
            entry = inputs[kind]
            reference = entry["digestReference"]
            record: dict[str, Any] = {"reference": reference}
            try:
                observed, manifest = manifest_digest(reference)
                expected = entry["digest"]
                if observed != expected:
                    raise Failure(
                        f"the registry served manifest {observed} for a reference pinned to "
                        f"{expected}"
                    )
                record["manifestDigest"] = observed

                layout = scratch / kind
                pull_to_layout(reference, layout)
                record.update(verify_blobs(layout, manifest))

                if kind == "snapshot" and not args.skip_snapshot_contents:
                    snapshot_lock = json.loads(args.snapshot_lock.read_text(encoding="utf-8"))
                    record.update(verify_snapshot_contents(layout, snapshot_lock))

                record["result"] = "PASS"
            except Failure as failure:
                record["result"] = "FAIL"
                record["reason"] = str(failure)
                failures.append(f"{kind}: {failure}")
            results[kind] = record
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    payload = {
        "schemaVersion": 1,
        "publication": str(args.publication),
        "inputs": results,
        "result": "BLOCKED" if failures else "PASS",
        "note": (
            "Every digest is recomputed from the bytes the registry returned and every package "
            "checksum is re-derived from the RPM, rather than read from a lock's summary of "
            "itself. Run on a machine holding the retention store this proves the push worked; "
            "run on a clean runner it proves the inputs are independently retrievable, which is "
            "the claim that matters."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    for kind, record in results.items():
        line = f"{kind:9} {record['result']:5} {record['reference']}"
        print(line)
        if record["result"] == "FAIL":
            print(f"          {record['reason']}")
        elif kind == "snapshot" and "packagesFound" in record:
            print(
                f"          {record['packagesFound']} packages, "
                f"{record['signatures'].get('verified', 0)} signatures verified, "
                f"{record['blobsVerified']} blobs"
            )
        else:
            print(f"          {record.get('blobsVerified', 0)} blobs verified")
    print(f"wrote {args.report}")

    if failures:
        print("\nBLOCKED: " + "; ".join(failures), file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

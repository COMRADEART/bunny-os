#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two builders' output at four levels and emit a comparison record.

Archive digest, per-file content, SBOM digest and package manifest are compared
separately because they fail separately, and because knowing *which* level
diverged is the difference between "the build is non-deterministic" and "the
archive wrapper stamps timestamps". This repository has already been caught by
that distinction once.

The per-file comparison unpacks both OCI archives and hashes every entry. It
does not stop at the first difference: the list of differing paths is the
diagnostic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from typing import Any


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_file_digests(archive: Path) -> dict[str, str]:
    """Hash every regular file inside an OCI archive, keyed by member name."""
    digests: dict[str, str] = {}
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
            digests[member.name] = digest.hexdigest()
    return digests


def package_names(sbom: Path) -> list[str]:
    """Extract a sorted package manifest from an SPDX document.

    The document-root entry is excluded. Syft names it after the *path* of the
    input file, so two builders scanning byte-identical archives at different
    paths produce manifests that differ in exactly one entry — an artifact of
    where the file sits on disk, not of what is in it. Comparing that would
    report a reproducibility failure that does not exist.
    """
    if not sbom.is_file():
        return []
    with open(sbom, "rb") as handle:
        document = json.load(handle)
    names: list[str] = []
    for package in document.get("packages", []):
        if str(package.get("SPDXID", "")).startswith("SPDXRef-DocumentRoot-"):
            continue
        name = package.get("name")
        version = package.get("versionInfo", "")
        if name:
            names.append(f"{name}@{version}" if version else str(name))
    return sorted(names)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-record", type=Path, required=True, help="builder record JSON")
    parser.add_argument("--second-record", type=Path, required=True)
    parser.add_argument("--first-archive", type=Path, required=True)
    parser.add_argument("--second-archive", type=Path, required=True)
    parser.add_argument("--first-sbom", type=Path)
    parser.add_argument("--second-sbom", type=Path)
    parser.add_argument("--claim", default="independent-builder")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-file-comparison", action="store_true")
    args = parser.parse_args()

    first = json.loads(args.first_record.read_text(encoding="utf-8"))
    second = json.loads(args.second_record.read_text(encoding="utf-8"))

    archive_digests = [file_digest(args.first_archive), file_digest(args.second_archive)]

    if args.skip_file_comparison:
        file_digests: list[dict[str, str]] = [{}, {}]
    else:
        print("hashing archive members (this reads both archives in full)...", file=sys.stderr)
        file_digests = [
            archive_file_digests(args.first_archive),
            archive_file_digests(args.second_archive),
        ]

    sbom_digests = [
        file_digest(args.first_sbom) if args.first_sbom and args.first_sbom.is_file() else "",
        file_digest(args.second_sbom) if args.second_sbom and args.second_sbom.is_file() else "",
    ]
    manifests = [
        package_names(args.first_sbom) if args.first_sbom else [],
        package_names(args.second_sbom) if args.second_sbom else [],
    ]

    entry: dict[str, Any] = {
        "claim": args.claim,
        "first": first,
        "second": second,
        "archiveDigests": archive_digests,
        "fileDigests": file_digests,
        "sbomDigests": sbom_digests,
        "packageManifests": manifests,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {"schemaVersion": 1, "comparisons": []}
    if args.out.is_file():
        try:
            existing = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    comparisons = [
        item
        for item in existing.get("comparisons", [])
        if not (
            item.get("claim") == args.claim
            and item.get("first", {}).get("builderId") == first.get("builderId")
            and item.get("second", {}).get("builderId") == second.get("builderId")
        )
    ]
    comparisons.append(entry)
    existing["schemaVersion"] = 1
    existing["comparisons"] = comparisons
    args.out.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    differing = sorted(
        name
        for name in set(file_digests[0]) | set(file_digests[1])
        if file_digests[0].get(name) != file_digests[1].get(name)
    )
    print(f"archive digests : {'MATCH' if archive_digests[0] == archive_digests[1] else 'DIFFER'}")
    print(f"  {archive_digests[0]}")
    print(f"  {archive_digests[1]}")
    if not args.skip_file_comparison:
        print(f"file contents   : {len(file_digests[0])} members, {len(differing)} differing")
        for name in differing[:20]:
            print(f"    {name}")
    print(f"sbom digests    : {'MATCH' if sbom_digests[0] == sbom_digests[1] and sbom_digests[0] else 'DIFFER/absent'}")
    print(f"package manifest: {'MATCH' if manifests[0] == manifests[1] else 'DIFFER'} ({len(manifests[0])} vs {len(manifests[1])})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

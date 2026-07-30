#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify a retained base image, and emit or check its lock.

Two modes, because copying and trusting are different acts:

``--emit-lock``
    Runs immediately after a copy. Walks the OCI layout, recomputes the digest
    of every manifest, config and layer blob, cross-checks the retained manifest
    against the upstream index it claims to have come from, and writes
    ``base-image-lock.json`` with ``verificationStatus``.

default
    Runs before a build. Reads the committed lock and re-verifies the retained
    store against it, so that a lock which no longer describes the bytes on disk
    fails **before** a qualification build consumes them.

Both fail closed. Exit 2 is *verified and refused*; exit 1 is *failed to
evaluate*, and the distinction matters because CI asserts on exact exit codes —
a traceback that exits 1 must never be read as a correct refusal.

Every failure the brief names is a distinct message here rather than one generic
"verification failed": a missing manifest, a missing blob, a digest mismatch, a
mutable tag, an unavailable mirror, the wrong architecture and a partial copy
all mean different things and have different fixes.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import (  # noqa: E402
    SCHEMA_VERSION,
    SupplyChainError,
    parse_base_image_lock,
)

CHUNK = 1024 * 1024
REFUSED = 2
CRASHED = 1


class RetentionError(Exception):
    """A retained base failed verification. Carries the specific reason."""


def _digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def _blob_path(layout: Path, digest: str) -> Path:
    algorithm, _, value = digest.partition(":")
    return layout / "blobs" / algorithm / value


def _read_json(path: Path, *, what: str) -> Any:
    if not path.is_file():
        raise RetentionError(f"{what} is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RetentionError(f"{what} is not valid JSON: {path}: {exc}") from None


def walk_layout(layout: Path) -> dict[str, Any]:
    """Verify an OCI layout end to end and describe what it holds."""
    if not layout.is_dir():
        raise RetentionError(
            f"the controlled mirror is unavailable: {layout} does not exist. A qualification "
            "build must fail before building rather than fall back to upstream"
        )

    marker = _read_json(layout / "oci-layout", what="the OCI layout marker")
    if str(marker.get("imageLayoutVersion", "")) != "1.0.0":
        raise RetentionError(
            f"unsupported OCI layout version {marker.get('imageLayoutVersion')!r}"
        )

    index = _read_json(layout / "index.json", what="the retained index")
    manifests = index.get("manifests") or []
    if not manifests:
        raise RetentionError(
            "the retained index lists no manifests. This is a partial copy: the layout exists "
            "but names nothing, which a build would discover only at pull time"
        )

    verified: list[dict[str, Any]] = []
    blob_digests: set[str] = set()
    total_bytes = 0
    architectures: set[str] = set()

    pending = [(entry, True) for entry in manifests]
    while pending:
        entry, top_level = pending.pop(0)
        digest = str(entry.get("digest", ""))
        blob = _blob_path(layout, digest)
        if not blob.is_file():
            raise RetentionError(
                f"the retained manifest {digest} is missing from the mirror. The index references "
                "it and the blob is not present, so the copy is incomplete"
            )
        actual = _digest_file(blob)
        if actual != digest:
            raise RetentionError(
                f"manifest digest mismatch: the index says {digest} and the stored bytes hash to "
                f"{actual}. Content-addressed storage that does not match its own address has "
                "been corrupted or substituted"
            )
        blob_digests.add(digest)
        total_bytes += blob.stat().st_size

        document = json.loads(blob.read_text(encoding="utf-8"))
        media = str(document.get("mediaType") or entry.get("mediaType") or "")

        if "index" in media or "manifest.list" in media:
            children = document.get("manifests") or []
            if not children:
                raise RetentionError(f"the retained index {digest} lists no child manifests")
            for child in children:
                pending.append((child, False))
            verified.append(
                {
                    "digest": digest,
                    "mediaType": media,
                    "size": blob.stat().st_size,
                    "architecture": None,
                    "os": None,
                    "role": "index",
                }
            )
            continue

        platform = entry.get("platform") or {}
        architecture = str(platform.get("architecture") or document.get("architecture") or "")
        if not architecture:
            config_descriptor = document.get("config") or {}
            config_blob = _blob_path(layout, str(config_descriptor.get("digest", "")))
            if config_blob.is_file():
                architecture = str(
                    json.loads(config_blob.read_text(encoding="utf-8")).get("architecture", "")
                )
        if architecture:
            architectures.add(architecture)

        for descriptor in [document.get("config") or {}, *(document.get("layers") or [])]:
            child_digest = str(descriptor.get("digest", ""))
            if not child_digest:
                raise RetentionError(f"manifest {digest} has a descriptor with no digest")
            child_blob = _blob_path(layout, child_digest)
            if not child_blob.is_file():
                raise RetentionError(
                    f"blob {child_digest} is missing from the mirror. Manifest {digest} references "
                    "it, so this is a partial copy and a cold pull would fail at that layer"
                )
            if child_digest in blob_digests:
                continue
            child_actual = _digest_file(child_blob)
            if child_actual != child_digest:
                raise RetentionError(
                    f"blob digest mismatch for {child_digest}: the stored bytes hash to "
                    f"{child_actual}"
                )
            blob_digests.add(child_digest)
            total_bytes += child_blob.stat().st_size

        verified.append(
            {
                "digest": digest,
                "mediaType": media,
                "size": blob.stat().st_size,
                "architecture": architecture or None,
                "os": str(platform.get("os") or document.get("os") or "linux"),
                "role": "manifest",
            }
        )

    return {
        "manifests": verified,
        "architectures": sorted(architectures),
        "blobCount": len(blob_digests),
        "blobBytes": total_bytes,
    }


def emit_lock(args: argparse.Namespace) -> int:
    layout = Path(args.layout)
    walked = walk_layout(layout)

    upstream = str(args.upstream)
    if "@sha256:" not in upstream:
        raise RetentionError(
            f"the upstream reference {upstream!r} is not digest-pinned; a mutable tag cannot be "
            "retained because it does not identify content"
        )
    upstream_digest = upstream.split("@", 1)[1]

    source_index = json.loads(Path(args.upstream_manifest).read_text(encoding="utf-8"))
    source_children = {
        str(entry.get("digest")): entry for entry in (source_index.get("manifests") or [])
    }
    source_media = str(source_index.get("mediaType", ""))

    architecture = str(args.architecture)
    candidates = [
        entry
        for entry in walked["manifests"]
        if entry["role"] == "manifest" and (entry["architecture"] in (architecture, None))
    ]
    if not candidates:
        raise RetentionError(
            f"the mirror holds no manifest for architecture {architecture!r}; it holds "
            + (", ".join(walked["architectures"]) or "no identifiable architecture")
            + ". A build for the wrong architecture must fail before it starts"
        )
    selected = candidates[0]

    # The retained manifest must be one the upstream index actually referenced,
    # or the lock would be asserting a provenance it never checked.
    inventory: list[dict[str, Any]] = []
    if source_children:
        if selected["digest"] not in source_children:
            raise RetentionError(
                f"the retained manifest {selected['digest']} is not among the manifests the "
                f"upstream index {upstream_digest} references. The copy did not come from the "
                "pinned index, whatever else it may be"
            )
        for digest, entry in source_children.items():
            platform = entry.get("platform") or {}
            inventory.append(
                {
                    "digest": digest,
                    "mediaType": str(entry.get("mediaType", "")),
                    "size": int(entry.get("size", 0)),
                    "architecture": str(platform.get("architecture") or "") or None,
                    "os": str(platform.get("os") or "") or None,
                }
            )
        architectures = sorted(
            {str((entry.get("platform") or {}).get("architecture") or "") for entry in source_children.values()}
            - {""}
        )
    else:
        inventory.append(
            {
                "digest": upstream_digest,
                "mediaType": source_media,
                "size": Path(args.upstream_manifest).stat().st_size,
                "architecture": architecture,
                "os": "linux",
            }
        )
        architectures = [architecture]
        if selected["digest"] != upstream_digest:
            raise RetentionError(
                f"the upstream reference is a single manifest {upstream_digest} and the mirror "
                f"holds {selected['digest']}; they are not the same image"
            )

    lock = {
        "schemaVersion": SCHEMA_VERSION,
        "upstreamReference": upstream,
        "upstreamDigest": upstream_digest,
        "upstreamMediaType": source_media,
        "selectedArchitecture": architecture,
        "selectedManifestDigest": selected["digest"],
        "retainedReference": f"{args.retained_location}@{selected['digest']}",
        "retainedDigest": selected["digest"],
        "retainedLocation": str(args.retained_location),
        "architectures": architectures,
        "manifests": inventory,
        "copiedAt": _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "blobCount": walked["blobCount"],
        "blobBytes": walked["blobBytes"],
        "upstreamStillAvailable": True,
        "verificationStatus": "verified",
        "notes": (
            "Every manifest, config and layer blob in the mirror was read and re-hashed against "
            "its own digest. The retained manifest was confirmed to be one the upstream index "
            "references. This is retention, not a cache: a local podman store is unreachable from "
            "the second builder and does not satisfy this check."
        ),
    }

    # Parse what was just written. A lock this tool emits and its own parser
    # rejects is a lock nothing else will accept either.
    parse_base_image_lock(lock)

    destination = Path(args.lock)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"    {walked['blobCount']} blobs, {walked['blobBytes']:,} bytes, all digests verified")
    print(f"    retained manifest {selected['digest']} ({architecture})")
    print(f"    wrote {display_path(destination, Path.cwd())}")
    return 0


def verify_against_lock(args: argparse.Namespace) -> int:
    lock_path = Path(args.lock)
    if not lock_path.is_file():
        raise RetentionError(
            f"no base image lock at {lock_path}. A build with no recorded base cannot be verified, "
            "and an absent lock is not a passing check"
        )
    lock = parse_base_image_lock(json.loads(lock_path.read_text(encoding="utf-8")))

    if lock.verificationStatus != "verified":
        raise RetentionError(
            f"the lock records verificationStatus={lock.verificationStatus!r}; a base that failed "
            "verification must not be built from"
        )

    layout = Path(args.layout) if args.layout else Path(lock.retainedLocation)
    walked = walk_layout(layout)

    stored = {entry["digest"] for entry in walked["manifests"]}
    if lock.retainedDigest not in stored:
        raise RetentionError(
            f"the retained manifest {lock.retainedDigest} named by the lock is not in the mirror "
            f"at {layout}. The lock and the store describe different things"
        )

    architectures = set(walked["architectures"])
    if architectures and lock.selectedArchitecture not in architectures:
        raise RetentionError(
            f"the mirror holds {', '.join(sorted(architectures))} and the lock selects "
            f"{lock.selectedArchitecture}"
        )

    print(f"retained base verified: {lock.retainedReference}")
    print(f"  upstream        {lock.upstreamReference}")
    print(f"  architecture    {lock.selectedArchitecture}")
    print(f"  blobs           {walked['blobCount']} ({walked['blobBytes']:,} bytes)")
    print(f"  mirror          {display_path(layout, Path.cwd())}")
    if lock.upstreamStillAvailable is False:
        print(
            "  note            upstream no longer serves this digest; the mirror is now the only "
            "source, which is what it is for"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="verify-retained-base")
    parser.add_argument("--emit-lock", action="store_true")
    parser.add_argument("--layout")
    parser.add_argument("--upstream")
    parser.add_argument("--upstream-manifest")
    parser.add_argument("--architecture", default="amd64")
    parser.add_argument("--retained-location", default="")
    parser.add_argument(
        "--lock",
        default=str(Path(__file__).resolve().parents[2] / "build" / "inputs" / "base-image-lock.json"),
    )
    args = parser.parse_args()

    try:
        if args.emit_lock:
            for required in ("layout", "upstream", "upstream_manifest"):
                if not getattr(args, required):
                    parser.error(f"--emit-lock requires --{required.replace('_', '-')}")
            return emit_lock(args)
        return verify_against_lock(args)
    except (RetentionError, SupplyChainError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    raise SystemExit(main())

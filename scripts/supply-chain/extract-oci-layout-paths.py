#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract paths from a retained OCI *layout* on disk, without a container runtime.

``extract_archive_paths.py`` does this for an OCI archive. A retained image is a
layout — a directory of blobs with an ``index.json`` — and reaching into one has
been done three different ways in this repository, each with its own failure.

Pulling it into podman and running a container is the obvious one and it does not
work where it is needed: the snapshot materialiser already re-executes inside the
pinned builder, and from there ``localhost/bunny-os-retained-base:…`` is not an
image, it is a hostname. podman tries to resolve a registry called ``localhost``
and fails with a connection refused, which is a confusing way to say "that tag
belongs to a different machine's store".

``skopeo copy`` to a directory works and moves the whole image; for two 1 KB
signing keys out of a 1 GB base that is the wrong shape.

This reads the layout the way the format documents it: ``index.json`` names a
manifest, the manifest names layers, each layer is a tar (usually gzipped), and
later layers win. Whiteouts are honoured so an extracted file is the one the
image would actually have.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import io
import json
from pathlib import Path
import posixpath
import sys
import tarfile

REFUSED = 2


def _normalise(name: str) -> str:
    return posixpath.normpath(name.lstrip("./")).lstrip("/")


def blob_path(layout: Path, digest: str) -> Path:
    algorithm, _, value = digest.partition(":")
    return layout / "blobs" / algorithm / value


def select_manifest(layout: Path, reference: str | None) -> dict:
    index = json.loads((layout / "index.json").read_text(encoding="utf-8"))
    manifests = index.get("manifests") or []
    if not manifests:
        raise SystemExit(f"BLOCKED: {layout}/index.json names no manifest")

    chosen = manifests[0]
    if reference:
        for entry in manifests:
            if (entry.get("annotations") or {}).get("org.opencontainers.image.ref.name") == reference:
                chosen = entry
                break
        else:
            raise SystemExit(
                f"BLOCKED: {layout} has no manifest tagged {reference!r}; it has "
                + ", ".join(
                    str((m.get("annotations") or {}).get("org.opencontainers.image.ref.name"))
                    for m in manifests
                )
            )

    manifest = json.loads(blob_path(layout, chosen["digest"]).read_bytes())
    # An index of indexes: a multi-architecture image points at per-architecture
    # manifests. Descending blindly would extract from whichever came first.
    if "manifests" in manifest and "layers" not in manifest:
        raise SystemExit(
            f"BLOCKED: {chosen['digest']} is an image index, not a manifest. This layout retains "
            "more than one architecture and the caller must say which."
        )
    return manifest


def _layers(layout: Path, manifest: dict):
    for layer in manifest.get("layers") or []:
        payload = blob_path(layout, layer["digest"]).read_bytes()
        if layer.get("mediaType", "").endswith("gzip") or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        yield tarfile.open(fileobj=io.BytesIO(payload), mode="r:")


def extract(layout: Path, manifest: dict, patterns: list[str]) -> dict[str, bytes]:
    """Content for every path matching a pattern, hard links resolved.

    A bootc image does not store file content at the path you ask for. Content
    lives in the ostree repository and the visible path is a **hard link** into
    it:

        etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary
            type=1  size=0
            link -> sysroot/ostree/repo/objects/12/2779…file

    An extractor that only took regular files found nothing and reported the
    keys as absent from an image that ships them. So a match that is a link
    records where to look, and a second pass fetches the target — second pass
    because the target can appear in an earlier layer than the link.
    """
    found: dict[str, bytes] = {}
    links: dict[str, str] = {}

    for stream in _layers(layout, manifest):
        with stream:
            for member in stream:
                name = _normalise(member.name)
                base = posixpath.basename(name)
                parent = posixpath.dirname(name)
                if base == ".wh..wh..opq":
                    for existing in [e for e in found if e.startswith(parent + "/")]:
                        found.pop(existing, None)
                        links.pop(existing, None)
                    continue
                if base.startswith(".wh."):
                    target = posixpath.join(parent, base[4:]) if parent else base[4:]
                    found.pop(target, None)
                    links.pop(target, None)
                    continue
                if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    continue
                if member.isreg():
                    handle = stream.extractfile(member)
                    if handle is not None:
                        found[name] = handle.read()
                        links.pop(name, None)
                elif member.islnk():
                    links[name] = _normalise(member.linkname)

    wanted = {target for name, target in links.items() if name not in found}
    if wanted:
        resolved: dict[str, bytes] = {}
        for stream in _layers(layout, manifest):
            with stream:
                for member in stream:
                    name = _normalise(member.name)
                    if name in wanted and member.isreg():
                        handle = stream.extractfile(member)
                        if handle is not None:
                            resolved[name] = handle.read()
        for name, target in links.items():
            if name not in found and target in resolved:
                found[name] = resolved[target]

    return found


def main() -> int:
    parser = argparse.ArgumentParser(prog="extract-oci-layout-paths")
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--reference", help="the layout tag to read, e.g. retained")
    parser.add_argument("--pattern", action="append", required=True,
                        help="a glob against image paths without a leading slash; repeatable")
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--flatten", action="store_true",
                        help="write basenames into the destination rather than the tree")
    parser.add_argument("--require", type=int, default=0,
                        help="exit 2 unless at least this many paths were extracted")
    args = parser.parse_args()

    if not (args.layout / "index.json").is_file():
        raise SystemExit(f"BLOCKED: {args.layout} is not an OCI layout: no index.json")

    manifest = select_manifest(args.layout, args.reference)
    found = extract(args.layout, manifest, args.pattern)

    args.destination.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(found.items()):
        target = args.destination / (posixpath.basename(name) if args.flatten else name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"    {name}  {hashlib.sha256(content).hexdigest()}  {len(content)} bytes")

    if len(found) < args.require:
        raise SystemExit(
            f"BLOCKED: {len(found)} of at least {args.require} required paths matched "
            + ", ".join(args.pattern)
            + f" in {args.layout}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract named paths out of an OCI archive, with whiteout semantics applied.

Diagnosing a file that differs between two builds means holding that file, not a
digest of it. Podman can do this by loading the image and running a container,
but that puts the container store between the archive and the diagnosis: a store
that deduplicates, recompresses or normalises would hide the very thing being
looked for.

This reads the archive with ``tarfile`` and nothing else, applying layers in
manifest order so the extracted bytes are the file *the image would have* rather
than whichever layer happened to mention it last:

    .wh.<name>      deletes <name> from the accumulated tree
    .wh..wh..opq    deletes everything accumulated under that directory

Metadata is recorded beside the content, because a database that matched byte
for byte but arrived with a different mode or owner is still a difference and the
finaliser is required to fail closed on it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import posixpath
import sys
import tarfile
from typing import Any

REFUSED = 2


def _normalise(name: str) -> str:
    return posixpath.normpath(name.lstrip("./")).lstrip("/")


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "dir"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    if member.ischr():
        return "chardev"
    if member.isblk():
        return "blockdev"
    if member.isfifo():
        return "fifo"
    return "file"


def extract(archive: Path, wanted: set[str]) -> dict[str, dict[str, Any]]:
    """Return, for each wanted path present in the image, its bytes and metadata.

    ``wanted`` is matched against fully normalised paths without a leading
    slash, so ``usr/share/rpm/rpmdb.sqlite`` and ``/usr/share/rpm/rpmdb.sqlite``
    both find the same entry.
    """
    wanted = {_normalise(name) for name in wanted}
    found: dict[str, dict[str, Any]] = {}

    with tarfile.open(archive, "r:*") as outer:
        names = {_normalise(m.name): m for m in outer.getmembers()}
        index_member = names.get("index.json")
        if index_member is None:
            raise SystemExit(f"{archive} has no index.json; not an OCI archive")
        index = json.load(outer.extractfile(index_member))

        def blob(digest: str):
            member = names.get("blobs/" + digest.replace(":", "/"))
            if member is None:
                raise SystemExit(f"{archive} is missing blob {digest}")
            return outer.extractfile(member)

        manifest = json.load(blob(index["manifests"][0]["digest"]))

        for position, layer in enumerate(manifest["layers"]):
            payload = blob(layer["digest"]).read()
            if layer["mediaType"].endswith("gzip") or payload[:2] == b"\x1f\x8b":
                payload = gzip.decompress(payload)
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as inner:
                for member in inner:
                    name = _normalise(member.name)
                    if not name or name == ".":
                        continue
                    base = posixpath.basename(name)
                    parent = posixpath.dirname(name)

                    if base == ".wh..wh..opq":
                        for existing in [
                            entry for entry in found
                            if entry.startswith(parent + "/") or entry == parent
                        ]:
                            found.pop(existing, None)
                        continue
                    if base.startswith(".wh."):
                        target = posixpath.join(parent, base[4:]) if parent else base[4:]
                        found.pop(target, None)
                        continue

                    if name not in wanted:
                        continue

                    record: dict[str, Any] = {
                        "path": name,
                        "layerIndex": position,
                        "layerDigest": layer["digest"],
                        "type": _member_type(member),
                        "mode": f"{member.mode:04o}",
                        "uid": member.uid,
                        "gid": member.gid,
                        "uname": member.uname,
                        "gname": member.gname,
                        "size": member.size,
                        # Recorded because a layer's tar bytes depend on it even
                        # though the dimension collector does not compare it. A
                        # file whose content matches and whose mtime does not
                        # still changes the layer digest, and that difference
                        # would otherwise be attributed to content.
                        "mtime": member.mtime,
                    }
                    if member.linkname:
                        record["link"] = member.linkname
                    if member.isreg():
                        handle = inner.extractfile(member)
                        record["content"] = handle.read() if handle else b""
                        record["sha256"] = hashlib.sha256(record["content"]).hexdigest()
                    found[name] = record

    return found


def main() -> int:
    parser = argparse.ArgumentParser(prog="extract_archive_paths")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        required=True,
        help="an image path to extract; repeatable",
    )
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="where to write the metadata record; defaults to <destination>/extraction.json",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="exit 2 when any requested path is absent from the image",
    )
    args = parser.parse_args()

    if not args.archive.is_file():
        raise SystemExit(f"archive does not exist: {args.archive}")

    found = extract(args.archive, set(args.paths))

    missing = sorted({_normalise(name) for name in args.paths} - set(found))
    if missing and args.require_all:
        raise SystemExit(
            "BLOCKED: these paths are not present in the image after applying every layer: "
            + ", ".join(missing)
        )

    args.destination.mkdir(parents=True, exist_ok=True)
    records = []
    for name, record in sorted(found.items()):
        # Flatten the image path into a filename so two databases with the same
        # basename cannot land on top of each other.
        target = args.destination / name.replace("/", "__")
        content = record.pop("content", None)
        if content is not None:
            target.write_bytes(content)
            record["extractedTo"] = str(target)
        records.append(record)

    manifest = args.manifest or (args.destination / "extraction.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "archive": args.archive.name,
                "archiveSha256": hashlib.sha256(args.archive.read_bytes()).hexdigest()
                if args.archive.stat().st_size < (256 * 1024 * 1024)
                else _stream_digest(args.archive),
                "requested": sorted(_normalise(name) for name in args.paths),
                "missing": missing,
                "extracted": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    for record in records:
        print(f"{record['path']}  {record.get('sha256', record['type'])}  {record.get('size', 0)} bytes")
    if missing:
        print(f"absent from image: {', '.join(missing)}", file=sys.stderr)
    print(f"wrote {manifest}")
    return 0


def _stream_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

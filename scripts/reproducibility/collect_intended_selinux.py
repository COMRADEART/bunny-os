#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compute the intended SELinux context of every path in an OCI archive.

A bootc container image carries no ``security.selinux`` xattrs in its layers.
Measured on this project's artifact: 164,962 entries, nine with
``security.capability``, **zero** with ``security.selinux``. ``bootc install``
applies contexts on the target from the policy the image ships, so an
archive-only build cannot observe an applied label at all — and reporting two
empty sets as a match would claim a comparison that did not happen.

What an archive *can* answer is the other half of the question: given the policy
this image ships and the paths this image contains, what context is each path
*supposed* to get? That is a deterministic function of two things both builders
have, so two builders shipping the same policy and the same tree must produce
the same manifest, and a difference is a real difference.

The computation uses the policy's own file-context specifications through
``matchpathcon``, not a reimplementation of the matching rules. Regular
expression precedence, stem optimisation and the ``<<none>>`` sentinel are
subtle, and a hand-rolled matcher that got any of them wrong would produce a
manifest that agreed with itself on both builders and with the policy on
neither.

File type is passed explicitly with ``-m`` because the paths are inside an
archive rather than on a filesystem, and the policy distinguishes a directory
from a regular file at the same path.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402

REFUSED = 2

#: Where a Fedora policy keeps its file-context specifications. The first that
#: exists wins; `.bin` is the compiled form and is preferred because it is what
#: the running system actually consults.
SPEC_CANDIDATES = (
    "etc/selinux/targeted/contexts/files/file_contexts",
    "etc/selinux/targeted/contexts/files/file_contexts.local",
    "etc/selinux/targeted/contexts/files/file_contexts.subs_dist",
)

#: matchpathcon's `-m` values, keyed by the archive member type.
MODE_FOR_TYPE = {
    "file": "file",
    "dir": "dir",
    "symlink": "lnk",
    "hardlink": "file",
    "chardev": "chr",
    "blockdev": "blk",
    "fifo": "fifo",
    "socket": "sock",
}

BATCH = 500


def _normalise(name: str) -> str:
    return posixpath.normpath(name.lstrip("./")).lstrip("/")


def read_archive(archive: Path, destination: Path) -> dict[str, str]:
    """Return path -> member type, and extract the policy specs to ``destination``."""
    entries: dict[str, str] = {}
    wanted = set(SPEC_CANDIDATES)

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

        removed: set[str] = set()
        for layer in manifest["layers"]:
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
                        for existing in [e for e in entries if e.startswith(parent + "/")]:
                            entries.pop(existing, None)
                        continue
                    if base.startswith(".wh."):
                        target = posixpath.join(parent, base[4:]) if parent else base[4:]
                        entries.pop(target, None)
                        removed.add(target)
                        continue
                    if member.isdir():
                        kind = "dir"
                    elif member.issym():
                        kind = "symlink"
                    elif member.islnk():
                        kind = "hardlink"
                    elif member.ischr():
                        kind = "chardev"
                    elif member.isblk():
                        kind = "blockdev"
                    elif member.isfifo():
                        kind = "fifo"
                    else:
                        kind = "file"
                    entries[name] = kind

                    if name in wanted:
                        handle = inner.extractfile(member)
                        if handle is not None:
                            target = destination / posixpath.basename(name)
                            target.write_bytes(handle.read())
    return entries


def match_contexts(spec: Path, paths: list[tuple[str, str]]) -> dict[str, str]:
    """Resolve each (path, mode) through the policy's own matcher."""
    contexts: dict[str, str] = {}
    by_mode: dict[str, list[str]] = {}
    for path, kind in paths:
        mode = MODE_FOR_TYPE.get(kind)
        if mode is None:
            continue
        by_mode.setdefault(mode, []).append("/" + path)

    for mode, group in sorted(by_mode.items()):
        for start in range(0, len(group), BATCH):
            chunk = group[start : start + BATCH]
            result = subprocess.run(
                ["matchpathcon", "-f", str(spec), "-m", mode, "-N", *chunk],
                capture_output=True,
                text=True,
            )
            # matchpathcon exits non-zero when *any* path has no match, which is
            # normal — the policy does not label every path. The unmatched lines
            # are reported as such rather than dropped, because a silently
            # missing path is indistinguishable from a path the policy declined
            # to label, and only one of those is interesting.
            for line in result.stdout.splitlines():
                path, separator, context = line.partition("\t")
                if not separator:
                    path, separator, context = line.rpartition("  ")
                    path = path.strip()
                    context = context.strip()
                if not path:
                    continue
                contexts[path.lstrip("/")] = context.strip() or "<<none>>"
            if result.returncode not in (0, 1) and not result.stdout:
                raise SystemExit(
                    f"BLOCKED: matchpathcon failed for mode {mode}: {result.stderr.strip()}"
                )
    return contexts


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_intended_selinux")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not args.archive.is_file():
        raise SystemExit(f"archive does not exist: {args.archive}")
    if shutil.which("matchpathcon") is None:
        raise SystemExit(
            "BLOCKED: matchpathcon is not available. The intended SELinux context manifest is a "
            "required dimension and cannot be produced without the policy matcher; reporting it "
            "as not collected while a tool was simply missing would hide an environment defect "
            "as an evidence gap."
        )

    with tempfile.TemporaryDirectory() as scratch:
        workdir = Path(scratch)
        entries = read_archive(args.archive, workdir)

        spec = next(
            (workdir / posixpath.basename(name) for name in SPEC_CANDIDATES
             if (workdir / posixpath.basename(name)).is_file()),
            None,
        )
        if spec is None:
            raise SystemExit(
                "BLOCKED: the archive ships no SELinux file-context specification. Without the "
                "policy there is nothing to compute an intended context from, and this image "
                "could not label a target system either."
            )

        contexts = match_contexts(spec, sorted(entries.items()))

    labelled = {path: context for path, context in contexts.items() if context != "<<none>>"}
    payload = {
        "schemaVersion": 1,
        "archive": args.archive.name,
        "specification": spec.name,
        "entryCount": len(entries),
        "resolvedCount": len(contexts),
        "labelledCount": len(labelled),
        "unlabelledCount": len(contexts) - len(labelled),
        "intendedSelinuxContexts": dict(sorted(contexts.items())),
        "note": (
            "The context each path is intended to receive, computed from the SELinux policy this "
            "image ships, through the policy's own matcher. This is the archive-stage SELinux "
            "subcheck. It does not establish what an installed system is actually labelled with: "
            "that is the applied-context subcheck and it requires a booted installed system."
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{len(entries)} entries, {len(contexts)} resolved, {len(labelled)} labelled")
    print(f"wrote {display_path(args.output, Path.cwd())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

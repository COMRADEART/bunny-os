#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect all seventeen comparison dimensions from an OCI archive.

The reproducibility comparison defines seventeen dimensions. A dimension that
one builder collected and the other did not is `NOT_COLLECTED`, and an
incomplete comparison cannot support a reproducibility claim — so the answer to
"the local builder never collected xattrs" is to collect them, not to drop the
dimension or assume the two agree.

Everything here is read out of the archive itself with `tarfile`. No root, no
podman, no mount: the same collector runs over the local builder's archive and
over the hosted builder's, so a difference in the report is a difference in the
images and not a difference in how they were measured.

Layers are applied in manifest order with OCI whiteout semantics, which is what
makes the result the *image's* filesystem rather than the union of its layers:

    .wh.<name>      deletes <name> from the accumulated tree
    .wh..wh..opq    deletes everything accumulated under that directory

Usage::

    collect_comparison_dimensions.py --archive bunny-os.oci.tar \\
        --sbom sbom.spdx.json --normalisation normalisation.json \\
        --output dimensions.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import sys
import tarfile
from typing import Any

CHUNK = 1024 * 1024

#: Paths whose content is a build timestamp rather than a build output. They are
#: still reported, in their own dimension-free section, so that a difference is
#: visible without being attributed to the image.
VOLATILE = re.compile(
    r"^(etc/machine-id|var/log/|var/cache/|var/tmp/|tmp/|run/)"
)


def _digest_stream(handle) -> str:
    value = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK), b""):
        value.update(chunk)
    return value.hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return _digest_stream(handle)


def _normalise(name: str) -> str:
    return posixpath.normpath(name.lstrip("./")).lstrip("/")


class Rootfs:
    """The accumulated filesystem after applying every layer in order."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}

    def apply_layer(self, stream: tarfile.TarFile) -> None:
        removed: set[str] = set()
        opaque: set[str] = set()
        additions: dict[str, dict[str, Any]] = {}

        for member in stream:
            name = _normalise(member.name)
            if not name or name == ".":
                continue
            base = posixpath.basename(name)
            parent = posixpath.dirname(name)

            if base == ".wh..wh..opq":
                opaque.add(parent)
                continue
            if base.startswith(".wh."):
                removed.add(posixpath.join(parent, base[4:]) if parent else base[4:])
                continue

            record: dict[str, Any] = {
                "mode": f"{member.mode:04o}",
                "uid": member.uid,
                "gid": member.gid,
                "type": _member_type(member),
                # Not a dimension, and deliberately so — the seventeen are fixed
                # by policy. It is carried because a layer's tar bytes depend on
                # it: measured on two builds, usr/share/bunny-os/finalisation.json
                # had identical content and mtimes 203 seconds apart, so
                # ociLayers and rawArchive differed while every dimension that
                # looks at content matched. Without this the report can say the
                # archives differ and cannot say which file made them differ.
                "mtime": member.mtime,
            }
            if member.linkname:
                record["link"] = member.linkname
            xattrs = _xattrs(member)
            if xattrs:
                record["xattrs"] = xattrs
            if member.isreg():
                handle = stream.extractfile(member)
                record["sha256"] = _digest_stream(handle) if handle else ""
                record["size"] = member.size
            additions[name] = record

        for name in list(self.entries):
            if name in removed or any(
                name == directory or name.startswith(directory + "/") for directory in opaque
            ):
                del self.entries[name]
        self.entries.update(additions)


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


def _xattrs(member: tarfile.TarInfo) -> dict[str, str]:
    """Extended attributes, from PAX SCHILY headers and tarfile's own mapping."""
    found: dict[str, str] = {}
    for key, value in (member.pax_headers or {}).items():
        if key.startswith("SCHILY.xattr."):
            found[key[len("SCHILY.xattr."):]] = value
    for key, value in (getattr(member, "pax_headers", {}) or {}).items():
        if key.startswith("RHT.security."):
            found[key[len("RHT."):]] = value
    return dict(sorted(found.items()))


def read_image(archive: Path) -> tuple[Rootfs, list[str], dict[str, Any]]:
    """Unpack an OCI archive into a rootfs, its layer list, and its config."""
    with tarfile.open(archive, "r:*") as outer:
        names = {_normalise(m.name): m for m in outer.getmembers()}

        index_member = names.get("index.json")
        if index_member is None:
            raise SystemExit(f"{archive} has no index.json; not an OCI archive")
        index = json.load(outer.extractfile(index_member))

        def blob(digest: str):
            key = "blobs/" + digest.replace(":", "/")
            member = names.get(key)
            if member is None:
                raise SystemExit(f"{archive} is missing blob {digest}")
            return outer.extractfile(member)

        manifest_digest = index["manifests"][0]["digest"]
        manifest = json.load(blob(manifest_digest))
        config = json.load(blob(manifest["config"]["digest"]))

        layers = [layer["digest"] for layer in manifest["layers"]]
        rootfs = Rootfs()
        for layer in manifest["layers"]:
            handle = blob(layer["digest"])
            payload = handle.read()
            if layer["mediaType"].endswith("gzip") or payload[:2] == b"\x1f\x8b":
                payload = gzip.decompress(payload)
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as inner:
                rootfs.apply_layer(inner)

    return rootfs, layers, config


def collect(
    archive: Path,
    *,
    sbom: Path | None,
    normalisation: Path | None,
    epoch: int | None = None,
) -> dict[str, Any]:
    rootfs, layers, config = read_image(archive)
    entries = rootfs.entries

    def under(*prefixes: str) -> dict[str, dict[str, Any]]:
        return {
            name: record
            for name, record in entries.items()
            if name.startswith(prefixes)
        }

    def digests_of(selection: dict[str, dict[str, Any]]) -> dict[str, str]:
        return {
            name: record.get("sha256", record.get("link", record["type"]))
            for name, record in sorted(selection.items())
        }

    stable = {name: record for name, record in entries.items() if not VOLATILE.match(name)}

    dimensions: dict[str, Any] = {}

    dimensions["filesystemTree"] = sorted(stable)
    dimensions["fileDigests"] = {
        name: record["sha256"]
        for name, record in sorted(stable.items())
        if record["type"] == "file" and "sha256" in record
    }
    dimensions["permissions"] = {
        name: record["mode"] for name, record in sorted(stable.items())
    }
    dimensions["ownership"] = {
        name: f"{record['uid']}:{record['gid']}" for name, record in sorted(stable.items())
    }
    dimensions["extendedAttributes"] = {
        name: record["xattrs"]
        for name, record in sorted(stable.items())
        if record.get("xattrs")
    }

    # An empty result here must not be reported as an empty *set*, because two
    # empty sets compare equal and the dimension would silently MATCH on both
    # builders having measured nothing. A bootc image carries no SELinux
    # contexts in its layers — `bootc install` applies them on the target from
    # the policy shipped in the image — so an archive-only build cannot observe
    # this dimension at all. `None` makes it NOT_COLLECTED, which makes the
    # comparison INCONCLUSIVE, which is the truth.
    labels = {
        name: record["xattrs"]["security.selinux"]
        for name, record in sorted(stable.items())
        if record.get("xattrs", {}).get("security.selinux")
    }
    dimensions["selinuxLabels"] = labels or None

    dimensions["systemdUnits"] = digests_of(
        under("usr/lib/systemd/", "etc/systemd/", "usr/share/systemd/")
    )
    dimensions["desktopEntries"] = digests_of(
        {
            name: record
            for name, record in entries.items()
            if name.endswith(".desktop")
        }
    )
    dimensions["schemas"] = digests_of(
        under("usr/share/glib-2.0/schemas/", "usr/share/bunny-os/schemas/")
    )
    dimensions["bootConfiguration"] = digests_of(
        under("boot/", "usr/lib/bootc/", "usr/lib/ostree-boot/", "usr/lib/bootupd/")
    )

    kernel = {
        name: record.get("sha256", "")
        for name, record in sorted(entries.items())
        if re.match(r"^usr/lib/modules/[^/]+/vmlinuz$", name)
    }
    dimensions["kernel"] = {
        "versions": sorted(
            {
                match.group(1)
                for name in entries
                if (match := re.match(r"^usr/lib/modules/([^/]+)/", name))
            }
        ),
        "vmlinuz": kernel,
    }

    initramfs = {
        name: record.get("sha256", "")
        for name, record in sorted(entries.items())
        if re.match(r"^usr/lib/modules/[^/]+/initramfs\.img$", name)
    }
    dimensions["initramfs"] = initramfs if initramfs else {
        "notPresent": "no initramfs is built into the container image; it is generated on the "
                      "installed system by bootc, so there is nothing to compare here"
    }

    dimensions["ociLayers"] = layers

    if sbom and sbom.is_file():
        document = json.loads(sbom.read_text(encoding="utf-8"))
        # The SPDX document root describes the artifact that was scanned, not a
        # component of the image:
        #
        #   "SPDXID": "SPDXRef-DocumentRoot-Image-build-out-beta-bunny-os.oci.tar"
        #   "name":   "build/out/beta/bunny-os.oci.tar"
        #   "versionInfo": "sha256:4e6f0ff7…"
        #
        # Its version is the archive's own digest, so leaving it in makes the
        # package inventory self-referential: it could only ever match when the
        # two archives are byte-identical, which `rawArchive` already measures.
        # Two builds with identical package sets would report a package
        # difference. Excluded here, and only here — every real package stays.
        components = [
            item for item in document.get("packages", [])
            if not str(item.get("SPDXID", "")).startswith("SPDXRef-DocumentRoot-")
        ]
        packages = sorted(
            f"{item.get('name')}@{item.get('versionInfo', 'UNKNOWN')}"
            for item in components
        )
        dimensions["packageInventory"] = packages
        # Excluding document identity: the SPDX document name and namespace
        # carry a generation-time UUID and describe the document, not the image.
        dimensions["sbom"] = sorted(
            json.dumps(
                {k: v for k, v in item.items() if k not in {"SPDXID", "documentNamespace"}},
                sort_keys=True,
            )
            for item in components
        )
    else:
        dimensions["packageInventory"] = None
        dimensions["sbom"] = None

    raw = file_digest(archive)
    normalised = None
    if normalisation and normalisation.is_file():
        record = json.loads(normalisation.read_text(encoding="utf-8"))
        normalised = record.get("normalisedDigest")
        recorded_raw = record.get("rawDigest")
        # Both recorded digests describe the shipped archive: normalisation runs
        # in place, so the file on disk is the normalised one and `rawDigest` is
        # its digest, not podman's. A manifest that disagreed with the file
        # beside it would mean one of them belongs to a different build, which is
        # worth stopping for.
        for field, value in (("rawDigest", recorded_raw), ("normalisedDigest", normalised)):
            if value and value != raw:
                raise SystemExit(
                    f"normalisation.json records {field} {value} but the archive on disk digests "
                    f"to {raw}; the manifest and the archive are not from the same build"
                )
    dimensions["rawArchive"] = raw
    dimensions["normalisedArchive"] = normalised

    volatile = sorted(name for name in entries if VOLATILE.match(name))

    # The excluded paths, digested rather than only listed.
    #
    # Excluding /var/cache and friends from the compared *dimensions* is right:
    # they are runtime state, not build output. Excluding them from the *layers*
    # is not possible — the tar contains them — so a volatile path that differs
    # changes ociLayers and rawArchive while every content dimension matches, and
    # the comparison has nothing to point at.
    #
    # That is not hypothetical: /var/cache/ldconfig/aux-cache stores an inode
    # number per shared object, and inode numbers belong to the filesystem the
    # build ran on. It differed between two builds and was invisible here.
    volatile_digests = {
        name: record.get("sha256", record.get("link", record["type"]))
        for name, record in sorted(entries.items())
        if VOLATILE.match(name)
    }

    # Entry modification times, as a diagnostic rather than as a dimension.
    #
    # The seventeen dimensions are fixed by policy and this is not one of them.
    # It is collected because when every content dimension matches and
    # `rawArchive` does not, this is where the answer is, and a comparison that
    # cannot answer "which file?" sends the next person back to `cmp` on a
    # 1.8 GB archive.
    mtimes = {name: record.get("mtime", 0) for name, record in sorted(stable.items())}
    later_than_epoch = (
        sorted(name for name, value in mtimes.items() if epoch is not None and value > epoch)
        if epoch is not None
        else None
    )

    return {
        "schemaVersion": 1,
        "archive": archive.name,
        "archiveSha256": raw,
        "imageConfigDigest": hashlib.sha256(
            json.dumps(config, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "entryCount": len(entries),
        "comparedEntryCount": len(stable),
        "volatilePathsExcluded": volatile,
        "notCollected": {
            name: reason
            for name, reason in (
                (
                    "selinuxLabels",
                    "no path in this archive carries a security.selinux xattr. A bootc container "
                    "image does not store SELinux contexts in its layers; bootc install applies "
                    "them on the target from the policy shipped in the image. This dimension "
                    "cannot be observed from an archive-only build, and reporting two empty sets "
                    "as a match would claim a comparison that did not happen.",
                ),
            )
            if dimensions.get(name) is None
        },
        "entryMtimes": {
            "note": (
                "Not one of the seventeen dimensions. A layer's tar bytes include entry mtimes, "
                "so a file whose content matches and whose mtime does not still changes ociLayers "
                "and rawArchive. Collected so that difference has a name instead of being "
                "attributed to whichever content difference happens to be nearby."
            ),
            "digest": hashlib.sha256(
                json.dumps(mtimes, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "declaredEpoch": epoch,
            "laterThanEpochCount": len(later_than_epoch) if later_than_epoch is not None else None,
            "laterThanEpoch": later_than_epoch[:200] if later_than_epoch else later_than_epoch,
            "byPath": mtimes,
        },
        "volatilePathDigests": {
            "note": (
                "Not one of the seventeen dimensions. These paths are excluded from the compared "
                "set because they are runtime state, and they are still inside the layer tars — "
                "so one that differs changes ociLayers and rawArchive while every content "
                "dimension matches. Digested here so that difference has a name."
            ),
            "count": len(volatile_digests),
            "digest": hashlib.sha256(
                json.dumps(volatile_digests, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "byPath": volatile_digests,
        },
        "volatileNote": (
            "Paths under /var/log, /var/cache, /var/tmp, /tmp and /run, and /etc/machine-id, are "
            "excluded from the compared set: they are runtime state, not build output. They are "
            "listed here so the exclusion is visible rather than silent."
        ),
        "dimensions": dimensions,
    }


#: Dimensions an archive-stage build is required to collect. `selinuxLabels` is
#: absent because no archive can carry an applied context — that subcheck belongs
#: to the installed-system stage, and the archive-stage half is collected
#: separately by collect_intended_selinux.py.
REQUIRED_IN_QUALIFICATION = (
    "bootConfiguration",
    "desktopEntries",
    "extendedAttributes",
    "fileDigests",
    "filesystemTree",
    "initramfs",
    "kernel",
    "normalisedArchive",
    "ociLayers",
    "ownership",
    "packageInventory",
    "permissions",
    "rawArchive",
    "sbom",
    "schemas",
    "systemdUnits",
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_comparison_dimensions")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--normalisation", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--epoch",
        type=int,
        help="the declared build epoch, so entry mtimes later than it can be named",
    )
    parser.add_argument(
        "--mode",
        choices=("qualification", "diagnostic"),
        default="diagnostic",
        help=(
            "qualification refuses to write an incomplete collection; diagnostic records what is "
            "missing as NOT_COLLECTED. Only qualification-mode evidence may reach a gate."
        ),
    )
    args = parser.parse_args()

    if not args.archive.is_file():
        raise SystemExit(f"archive does not exist: {args.archive}")

    payload = collect(
        args.archive, sbom=args.sbom, normalisation=args.normalisation, epoch=args.epoch
    )
    payload["collectionMode"] = args.mode

    # A comparison missing a dimension cannot support a reproducibility claim,
    # and the previous local run proved that a collector invoked without --sbom
    # and --normalisation will happily produce one and say so in a line nobody
    # reads. In qualification mode the omission is a refusal instead.
    absent_required = sorted(
        name
        for name in REQUIRED_IN_QUALIFICATION
        if payload["dimensions"].get(name) is None
    )
    payload["requiredDimensions"] = list(REQUIRED_IN_QUALIFICATION)
    payload["missingRequiredDimensions"] = absent_required

    if args.mode == "qualification" and absent_required:
        raise SystemExit(
            "BLOCKED: qualification mode requires every archive-stage dimension and these were "
            "not collected: "
            + ", ".join(absent_required)
            + ".\nPass --sbom and --normalisation, or run with --mode diagnostic and do not "
            "submit the result as qualification evidence."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    collected = [
        name for name, value in payload["dimensions"].items()
        if value is not None and value != {} and value != []
    ]
    print(f"{payload['entryCount']} entries, {payload['comparedEntryCount']} compared")
    print(f"mode: {args.mode}")
    print(f"collected {len(collected)} of 17 dimensions: {', '.join(sorted(collected))}")
    absent = sorted(set(payload["dimensions"]) - set(collected))
    if absent:
        print(f"not collected: {', '.join(absent)}")
    later = payload["entryMtimes"]["laterThanEpochCount"]
    if later:
        print(f"entry mtimes later than the declared epoch: {later}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2) from None
        raise

#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qualify an initramfs against the live-boot mechanism the medium depends on.

## Why this exists

The Bunny installer ISO reached a GRUB menu in every run that was ever
recorded, and never once reached userspace. The reason was in the initramfs:
`root=live:CDLABEL=…` is parsed by dracut's dmsquash-live module, the shipped
initramfs did not contain it, and so nothing consumed the argument, no root was
assembled, and `initrd-switch-root.service` failed. Two command-line changes
were made and rejected before anyone looked inside the artifact.

Nothing in the build would have caught that, because every intermediate step
succeeded: the ISO was generated, GRUB was drawn, the kernel loaded and
`initrd.img` was present and 116 MB. This is the check that turns "an initramfs
file exists" into "the initramfs contains the capability the kernel command line
depends on".

## Why it does not simply run dracut and trust the exit code

Measured, inside the build container, with the stock configuration:

    dracut-install: ERROR: installing '/root'
    dracut[E]: FAILED: /usr/lib/dracut/dracut-install -D … -f /root
    exit=0

dracut reports a failed install and returns success. It does return 1 for a
module it cannot find, so its exit code is worth checking — but it is not
sufficient, and the artifact has to be opened.

## Why it does not shell out to lsinitrd

lsinitrd is a shell script that unpacks to a temporary directory and is not
present off a Fedora host, which would make this check unavailable exactly where
it is most useful: a test suite, a CI runner, a developer's machine. The reader
below walks the cpio directly, so the same code qualifies the artifact inside
the build container, on the ISO after assembly, and against fixtures in tests.

## What "structural" means here

Not a grep for a string. Three independent layers, each of which can fail on its
own:

  1. dracut's own manifest. dracut writes the list of modules it included to
     `usr/lib/dracut/modules.txt` inside the image. That is the generator's
     record of what it did, and membership in it is checked exactly.
  2. The files each module installs. A module name in a manifest is a claim; the
     hook script that parses the kernel command line is the thing that runs.
  3. The kernel objects the mechanism loads. dmsquash-live's installkernel()
     asks for squashfs, loop, iso9660 and erofs; without squashfs.ko the module
     is present and the medium still does not boot.

Layer 2 and 3 are what make this more than a name check, and layer 1 is what
makes it more than a guess about file paths.

Usage:
    check-live-initramfs.py --initramfs PATH [--expect-kver KVER]
                            [--require MODULE ...] [--json REPORT]

Exit status: 0 pass, 1 usage/read error, 2 qualification failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

# The modules the Bunny installation medium's boot depends on.
#
# `dmsquash-live`, `livenet` and `ostree` are image-builder's stated requirement
# for a bootc container initramfs and are what installer/config/bunny-live-dracut.conf
# requests. `overlayfs` is required and is *not* requested there: dracut pulls it
# in as a dmsquash-live dependency, and the branch of dmsquash-live-root.sh that
# this ISO layout takes sets `overlayfs="required"` explicitly —
#
#     elif [ -d /run/initramfs/squashfs/usr ]; then
#         FSIMG=$SQUASHED
#         overlayfs="required"
#
# — because the squashfs on this medium is the root filesystem itself rather
# than a wrapper around LiveOS/rootfs.img. A dependency that the mechanism needs
# is worth asserting even when nothing asks for it by name, precisely because
# nothing asks for it by name.
DEFAULT_REQUIRED_MODULES = ("dmsquash-live", "livenet", "ostree", "overlayfs")

# Files each module installs, keyed by module name. Every path was read out of a
# generated artifact rather than guessed; a module whose files moved should fail
# this check loudly rather than pass on the strength of its name still being in
# a manifest.
MODULE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "dmsquash-live": (
        # The hook that parses `root=live:CDLABEL=…`. If exactly one path in
        # this file were kept, it would be this one: its absence is the whole
        # failure this check exists to prevent.
        "var/lib/dracut/hooks/cmdline/30-parse-dmsquash-live.sh",
        # The program that mounts the squashfs and assembles the root.
        "usr/bin/dmsquash-live-root",
        "usr/lib/systemd/system-generators/dracut-dmsquash-generator",
        "var/lib/dracut/hooks/pre-udev/30-dmsquash-live-genrules.sh",
    ),
    "livenet": (
        "var/lib/dracut/hooks/cmdline/29-parse-livenet.sh",
        "usr/bin/livenetroot",
        "usr/lib/systemd/system-generators/dracut-livenet-generator",
    ),
    "ostree": (
        "usr/lib/ostree/ostree-prepare-root",
        "usr/lib/systemd/system/ostree-prepare-root.service",
    ),
    "overlayfs": (
        "var/lib/dracut/hooks/pre-pivot/10-mount-overlayfs.sh",
        "var/lib/dracut/hooks/pre-mount/01-prepare-overlayfs.sh",
    ),
}

# Kernel objects the live root cannot be assembled without, as relative paths
# below usr/lib/modules/<kver>/. dmsquash-live's installkernel() is
# `instmods squashfs loop iso9660 erofs`; iso9660 builds as isofs.ko. The
# compression suffix is not part of the match because it is a packaging choice.
REQUIRED_KERNEL_OBJECTS = (
    "kernel/fs/squashfs/squashfs.ko",
    "kernel/fs/isofs/isofs.ko",
    "kernel/fs/overlayfs/overlay.ko",
    "kernel/drivers/block/loop.ko",
)

DRACUT_MODULE_MANIFEST = "usr/lib/dracut/modules.txt"
DRACUT_BUILD_PARAMETERS = "usr/lib/dracut/build-parameter.txt"

CPIO_MAGIC = b"070701"
CPIO_HEADER_LENGTH = 110
CPIO_TRAILER = "TRAILER!!!"


class QualificationError(Exception):
    """A problem reading the artifact, as distinct from a failed assertion."""


class Entry(NamedTuple):
    name: str
    mode: int
    size: int
    data_offset: int


# --------------------------------------------------------------------------
# Reading the artifact
# --------------------------------------------------------------------------


# An initramfs is not one archive. It is a chain of cpio archives concatenated
# end to end, each independently compressed or not, separated by zero padding;
# the kernel unpacks them in order and a later archive overwrites a file an
# earlier one placed. Measured on the artifact that shipped on the failing ISO:
#
#   offset          0  plain cpio, 8 entries, 17,084,144 bytes  (CPU microcode)
#   offset 17,084,416  zstd, one frame, 168,001,536 bytes       (the initramfs)
#   offset       +177  gzip, 171 bytes                          (appended later)
#
# A reader that decompresses "the part after the early cpio" and stops sees the
# middle archive only. That is not a hypothetical: the first version of this
# file did exactly that, and it failed outright on the shipped artifact while
# passing on the regenerated one, which happened to have no third segment. Had
# the required modules lived in an appended segment, it would have reported them
# missing from an image that contained them.
_COMPRESSION_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x1f\x8b", "gzip"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"\x5d\x00\x00", "lzma"),
    (b"BZh", "bzip2"),
    (b"\x04\x22\x4d\x18", "lz4"),
    (b"\x89LZO", "lzop"),
)


def _sniff(chunk: bytes) -> str | None:
    for magic, name in _COMPRESSION_MAGICS:
        if chunk.startswith(magic):
            return name
    return None


def _incremental_decompressor(kind: str):
    """An incremental decoder exposing .decompress(), .eof and .unused_data.

    Incremental rather than one-shot because `unused_data` is the only thing
    that says where one segment ends and the next begins. Every stdlib decoder
    below exposes it; lz4 and lzop have no stdlib decoder and are handled by
    the subprocess path, which cannot report a boundary and therefore treats
    its segment as the last one.
    """
    if kind == "zstd":
        try:  # Python 3.14+
            from compression.zstd import ZstdDecompressor

            return ZstdDecompressor()
        except ImportError:
            pass
        try:
            import zstandard

            return zstandard.ZstdDecompressor().decompressobj()
        except ImportError:
            return None
    if kind == "gzip":
        import zlib

        return zlib.decompressobj(wbits=31)
    if kind == "xz":
        import lzma

        return lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    if kind == "lzma":
        import lzma

        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    if kind == "bzip2":
        import bz2

        return bz2.BZ2Decompressor()
    return None


def _external_decompress(kind: str, data: bytes) -> bytes:
    command = {"zstd": ["zstd", "-dc"], "lz4": ["lz4", "-dc"],
               "lzop": ["lzop", "-dc"]}[kind]
    if shutil.which(command[0]) is None:
        raise QualificationError(
            f"the initramfs contains a {kind} segment and neither a Python "
            f"decoder nor the {command[0]} command is available to read it"
        )
    finished = subprocess.run(command, input=data, capture_output=True, check=False)
    # Trailing bytes past the final frame make these tools exit nonzero while
    # still having produced everything up to that point, which is what is wanted.
    if finished.returncode != 0 and not finished.stdout:
        raise QualificationError(
            f"{command[0]} could not decompress a segment of the initramfs: "
            f"{finished.stderr.decode('utf-8', 'replace').strip()}"
        )
    return finished.stdout


def _walk_cpio(blob: bytes, start: int = 0) -> Iterator[Entry]:
    """Yield newc entries from `blob`, beginning at `start`.

    Stops at the TRAILER!!! entry, and raises if it never arrives. Both halves
    matter: a malformed header and a truncated archive each produce a partial
    file table, and a partial file table read as a complete one is exactly how
    a check reports a module missing from an image that contains it.
    """
    offset = start
    saw_trailer = False
    while offset + CPIO_HEADER_LENGTH <= len(blob):
        if blob[offset : offset + 6] != CPIO_MAGIC:
            raise QualificationError(
                f"expected a newc cpio header at offset {offset}, found "
                f"{blob[offset:offset + 6]!r}"
            )
        try:
            fields = [
                int(blob[offset + 6 + index * 8 : offset + 14 + index * 8], 16)
                for index in range(13)
            ]
        except ValueError as error:
            raise QualificationError(
                f"malformed cpio header at offset {offset}: {error}"
            ) from error
        mode, size, name_size = fields[1], fields[6], fields[11]
        name_start = offset + CPIO_HEADER_LENGTH
        name = blob[name_start : name_start + name_size - 1].decode("utf-8", "replace")
        if name == CPIO_TRAILER:
            saw_trailer = True
            break
        data_start = _align4(name_start + name_size)
        yield Entry(name=name.lstrip("./") or ".", mode=mode, size=size,
                    data_offset=data_start)
        offset = _align4(data_start + size)
    if not saw_trailer:
        raise QualificationError(
            f"a cpio archive ended after {offset} of {len(blob)} bytes without a "
            f"{CPIO_TRAILER} entry; it is truncated or malformed"
        )


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _plain_cpio_length(blob: bytes) -> int:
    """Bytes consumed by the plain cpio archive starting at offset 0."""
    offset = 0
    while offset + CPIO_HEADER_LENGTH <= len(blob):
        if blob[offset : offset + 6] != CPIO_MAGIC:
            break
        fields = [
            int(blob[offset + 6 + index * 8 : offset + 14 + index * 8], 16)
            for index in range(13)
        ]
        size, name_size = fields[6], fields[11]
        name_start = offset + CPIO_HEADER_LENGTH
        name = blob[name_start : name_start + name_size - 1].decode("utf-8", "replace")
        offset = _align4(_align4(name_start + name_size) + size)
        if name == CPIO_TRAILER:
            break
    return offset


class Segment(NamedTuple):
    encoding: str
    offset: int
    compressed_bytes: int | None
    decoded_bytes: int
    entries: int


class Initramfs:
    """The file table and selected contents of one initramfs.

    Segments are read in order and their entries merged in order, so a file
    replaced by a later segment reads as the later one — the same precedence the
    kernel applies when it unpacks them.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = path.read_bytes()
        if not raw:
            raise QualificationError(f"{path} is empty")
        self.size = len(raw)
        self.sha256 = hashlib.sha256(raw).hexdigest()

        self.segments: list[Segment] = []
        self._blobs: list[bytes] = []
        self._entries: dict[str, tuple[int, Entry]] = {}

        offset = 0
        while offset < len(raw):
            while offset < len(raw) and raw[offset] == 0:
                offset += 1
            if offset >= len(raw):
                break
            chunk = raw[offset:]
            start = offset

            if chunk.startswith(CPIO_MAGIC):
                consumed = _plain_cpio_length(chunk)
                if consumed == 0:
                    raise QualificationError(
                        f"a cpio segment at offset {start} has no readable entries"
                    )
                blob, advance, encoding = chunk[:consumed], consumed, "cpio"
            else:
                encoding = _sniff(chunk)
                if encoding is None:
                    raise QualificationError(
                        f"unrecognised data at offset {start}; leading bytes were "
                        f"{chunk[:8]!r}. An initramfs is a chain of cpio archives, "
                        "each plain or compressed with a format this reader knows."
                    )
                decoder = _incremental_decompressor(encoding)
                if decoder is None:
                    # lz4 and lzop have no stdlib decoder, so the subprocess
                    # cannot say where the stream ended and this has to be the
                    # last segment. Distinct from the truncation case below,
                    # which is a corrupt artifact rather than a reader limit.
                    blob, advance = _external_decompress(encoding, chunk), None
                else:
                    try:
                        blob = decoder.decompress(chunk)
                    except Exception as error:  # decoder-specific exception types
                        raise QualificationError(
                            f"could not decompress the {encoding} segment at offset "
                            f"{start}: {error}"
                        ) from error
                    if not getattr(decoder, "eof", True):
                        raise QualificationError(
                            f"the {encoding} segment at offset {start} does not end "
                            f"within the file; {len(raw) - start} byte(s) were "
                            "available, so the initramfs is truncated"
                        )
                    unused = getattr(decoder, "unused_data", b"")
                    advance = len(chunk) - len(unused)

            index = len(self._blobs)
            self._blobs.append(blob)
            count = 0
            for entry in _walk_cpio(blob):
                self._entries[entry.name] = (index, entry)
                count += 1
            self.segments.append(
                Segment(encoding=encoding, offset=start, compressed_bytes=advance,
                        decoded_bytes=len(blob), entries=count)
            )
            if advance is None:
                # A decoder that cannot say where its stream ended; treat this
                # as the final segment rather than guess at a boundary.
                break
            offset = start + advance

        if not self._entries:
            raise QualificationError(
                f"{path} contains no cpio entries in any of its "
                f"{len(self.segments)} segment(s)"
            )

    @property
    def has_early_cpio(self) -> bool:
        return bool(self.segments) and self.segments[0].encoding == "cpio"

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._entries)

    def read(self, name: str) -> bytes | None:
        found = self._entries.get(name)
        if found is None:
            return None
        index, entry = found
        blob = self._blobs[index]
        return blob[entry.data_offset : entry.data_offset + entry.size]

    def read_text(self, name: str) -> str | None:
        data = self.read(name)
        return None if data is None else data.decode("utf-8", "replace")

    def names_at_or_after(self, offset: int) -> tuple[str, ...]:
        """Entries that came from a segment starting at or after `offset`."""
        return tuple(sorted(
            name for name, (index, _) in self._entries.items()
            if self.segments[index].offset >= offset
        ))

    def module_manifest(self) -> tuple[str, ...]:
        """The module list dracut recorded inside the image."""
        text = self.read_text(DRACUT_MODULE_MANIFEST)
        if text is None:
            raise QualificationError(
                f"{self.path} contains no {DRACUT_MODULE_MANIFEST}. dracut writes "
                "that file into every image it builds, so either this is not a "
                "dracut initramfs or it was assembled by something else."
            )
        return tuple(line.strip() for line in text.split() if line.strip())

    def kernel_releases(self) -> tuple[str, ...]:
        """Kernel releases the image carries modules for.

        Not every directory under usr/lib/modules/ is a kernel release:
        `usr/lib/modules/keys/` holds signing certificates and is a sibling of
        the release directories, not one of them. Naming every child a release
        made a correct artifact report two kernels and fail the mapping check —
        so a directory qualifies only by containing something a kernel release
        directory contains.
        """
        marker_files = {"modules.dep", "modules.alias", "modules.builtin",
                        "modules.order", "modules.symbols"}
        found = set()
        for name in self._entries:
            for prefix in ("usr/lib/modules/", "lib/modules/"):
                if not name.startswith(prefix):
                    continue
                remainder = name[len(prefix) :]
                release, _, tail = remainder.partition("/")
                if not release or not tail:
                    continue
                if tail.startswith("kernel/") or tail in marker_files:
                    found.add(release)
        return tuple(sorted(found))


# --------------------------------------------------------------------------
# The assertions
# --------------------------------------------------------------------------


def qualify(
    path: Path,
    required_modules: tuple[str, ...],
    expect_kver: str | None,
) -> dict:
    image = Initramfs(path)
    manifest = image.module_manifest()
    present = set(manifest)
    names = image.names
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "detail": detail})

    # Layer 1 — dracut's own record of the modules it included.
    for module in required_modules:
        record(
            f"module/{module}",
            module in present,
            f"{module} {'is' if module in present else 'is NOT'} in "
            f"{DRACUT_MODULE_MANIFEST}",
        )

    # Layer 2 — the files those modules install. Checked for every required
    # module, including ones the manifest already denied, because "the name is
    # missing and so are the files" and "the name is missing but the files are
    # there" are different faults and the second one should not be hidden.
    for module in required_modules:
        for evidence in MODULE_EVIDENCE.get(module, ()):
            record(
                f"file/{evidence}",
                evidence in names,
                f"{evidence} {'present' if evidence in names else 'absent'} "
                f"(installed by {module})",
            )

    # Layer 3 — the kernel objects the mechanism loads.
    releases = image.kernel_releases()
    for obj in REQUIRED_KERNEL_OBJECTS:
        matches = [
            name for name in names
            if name.endswith(obj) or any(
                name.startswith(f"{prefix}{release}/{obj}")
                for release in releases
                for prefix in ("usr/lib/modules/", "lib/modules/")
            )
        ]
        record(
            f"kernel-object/{obj}",
            bool(matches),
            f"{obj} {'present as ' + matches[0] if matches else 'absent'}",
        )

    # Kernel association. An initramfs carrying modules for two releases, or for
    # a release other than the one GRUB will boot, is the "wrong kernel/initrd
    # mapping" fault; it cannot be seen from the file name.
    record(
        "kernel-release/single",
        len(releases) == 1,
        f"carries modules for {len(releases)} kernel release(s): "
        f"{', '.join(releases) or 'none'}",
    )
    if expect_kver is not None:
        record(
            "kernel-release/expected",
            releases == (expect_kver,),
            f"expected exactly {expect_kver}, carries {', '.join(releases) or 'none'}",
        )

    failures = [check for check in checks if check["status"] == "FAIL"]
    return {
        "schemaVersion": 1,
        "artifact": str(path),
        "sizeBytes": image.size,
        "sha256": image.sha256,
        "hasEarlyCpio": image.has_early_cpio,
        "segments": [
            {"encoding": segment.encoding, "offset": segment.offset,
             "compressedBytes": segment.compressed_bytes,
             "decodedBytes": segment.decoded_bytes, "entries": segment.entries}
            for segment in image.segments
        ],
        "kernelReleases": list(releases),
        "expectedKernelRelease": expect_kver,
        "requiredModules": list(required_modules),
        "dracutModules": list(manifest),
        "dracutBuildParameters": (
            image.read_text(DRACUT_BUILD_PARAMETERS) or ""
        ).strip(),
        "checks": checks,
        "failures": len(failures),
        "status": "PASS" if not failures else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify an initramfs against the Bunny live-boot mechanism.",
    )
    parser.add_argument("--initramfs", required=True, type=Path,
                        help="the exact artifact to inspect")
    parser.add_argument("--expect-kver", default=None,
                        help="fail unless the image carries modules for exactly "
                             "this kernel release")
    parser.add_argument("--require", action="append", default=None,
                        metavar="MODULE",
                        help="dracut module that must be present; repeatable. "
                             f"Default: {' '.join(DEFAULT_REQUIRED_MODULES)}")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the structured report here as well")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the verdict line")
    arguments = parser.parse_args(argv)

    path: Path = arguments.initramfs
    if not path.exists():
        print(f"FAIL: no such initramfs: {path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"FAIL: not a regular file: {path}", file=sys.stderr)
        return 2
    try:
        path.open("rb").close()
    except OSError as error:
        print(f"FAIL: cannot read {path}: {error}", file=sys.stderr)
        return 2

    required = tuple(arguments.require) if arguments.require else DEFAULT_REQUIRED_MODULES
    try:
        report = qualify(path, required, arguments.expect_kver)
    except QualificationError as error:
        print(f"FAIL: {path}: {error}", file=sys.stderr)
        if arguments.json:
            arguments.json.parent.mkdir(parents=True, exist_ok=True)
            arguments.json.write_text(
                json.dumps({"schemaVersion": 1, "artifact": str(path),
                            "status": "FAIL", "error": str(error)}, indent=1),
                encoding="utf-8",
            )
        return 2

    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    if not arguments.quiet:
        print(f"initramfs: {path}")
        print(f"  sha256:  {report['sha256']}")
        print(f"  size:    {report['sizeBytes']} bytes")
        print(f"  kernel:  {', '.join(report['kernelReleases']) or '(none)'}")
        print(f"  dracut:  {len(report['dracutModules'])} modules")
        for check in report["checks"]:
            print(f"  [{check['status']}] {check['check']}: {check['detail']}")

    if report["status"] == "PASS":
        print(f"PASS: {path} supports the Bunny live-boot mechanism "
              f"({', '.join(required)})")
        return 0
    print(
        f"FAIL: {path} does not support the Bunny live-boot mechanism; "
        f"{report['failures']} check(s) failed",
        file=sys.stderr,
    )
    for check in report["checks"]:
        if check["status"] == "FAIL":
            print(f"  {check['check']}: {check['detail']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

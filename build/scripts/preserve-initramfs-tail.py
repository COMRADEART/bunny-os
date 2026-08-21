#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Carry an initramfs's appended segments across a regeneration.

An initramfs is a chain of cpio archives concatenated end to end, each plain or
independently compressed; the kernel unpacks them in order and later archives
overwrite earlier ones. dracut writes the leading plain archives (CPU microcode)
and one compressed archive. Anything after that was appended by something else,
and a regeneration silently loses it.

fedora-bootc:44 ships exactly such an addition — measured on the artifact that
reached the failing ISO:

    offset          0  plain cpio  17,084,144 bytes   7 entries   microcode
    offset 17,084,416  zstd       103,925,142 bytes   3621 entries the initramfs
    offset 121,009,564  gzip              171 bytes   4 entries   dev/random,
                                                                  dev/urandom

The regenerated image has the first two segments and not the third. Those two
character devices are shadowed by devtmpfs the moment systemd mounts it, so
dropping them would very likely have changed nothing — but the change this build
step set out to make is "add the missing dracut modules", and quietly removing
two device nodes on the way is a second, undeclared change. This restores them,
so the only difference between the old artifact and the new one is the one that
was intended.

Exit status: 0 on success (including "there was no tail"), 2 on failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from importlib.machinery import SourceFileLoader  # noqa: E402
from importlib.util import module_from_spec, spec_from_loader  # noqa: E402

# check-live-initramfs.py is not an importable module name, and the segment
# reader in it is the only correct one in the tree; loading it by path is better
# than a second implementation that can drift from the first.
_loader = SourceFileLoader(
    "bunny_check_live_initramfs",
    str(Path(__file__).resolve().parent / "check-live-initramfs.py"),
)
_spec = spec_from_loader(_loader.name, _loader)
assert _spec is not None
_reader = module_from_spec(_spec)
_loader.exec_module(_reader)

Initramfs = _reader.Initramfs
QualificationError = _reader.QualificationError


def appended_offset(image) -> int | None:
    """Byte offset where the segments dracut did not write begin.

    dracut writes zero or more plain leading archives followed by exactly one
    compressed archive. The first compressed segment is therefore the last one
    dracut is responsible for, and everything past its end was appended.
    Returns None when there is nothing after it.
    """
    for index, segment in enumerate(image.segments):
        if segment.encoding == "cpio":
            continue
        if segment.compressed_bytes is None:
            # The decoder could not report where the stream ended, so there is
            # no trustworthy boundary to cut at.
            return None
        end = segment.offset + segment.compressed_bytes
        if index + 1 >= len(image.segments):
            return None
        return end
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path,
                        help="the initramfs that was replaced")
    parser.add_argument("--regenerated", required=True, type=Path,
                        help="the new initramfs, appended to in place")
    parser.add_argument("--report", type=Path, default=None)
    arguments = parser.parse_args(argv)

    try:
        original = Initramfs(arguments.original)
        regenerated = Initramfs(arguments.regenerated)
    except QualificationError as error:
        print(f"BLOCKED: cannot read an initramfs: {error}", file=sys.stderr)
        return 2

    cut = appended_offset(original)
    result: dict = {
        "originalSegments": [s.encoding for s in original.segments],
        "regeneratedSegments": [s.encoding for s in regenerated.segments],
        "appendedBytes": 0,
        "restoredEntries": [],
    }

    if cut is None:
        print("    the previous initramfs had no appended segment; nothing to carry over")
    else:
        tail = arguments.original.read_bytes()[cut:]
        carried = list(original.names_at_or_after(cut))
        if not tail.strip(b"\0"):
            print("    the bytes after the dracut segment are padding only; "
                  "nothing to carry over")
        else:
            with arguments.regenerated.open("ab") as handle:
                handle.write(tail)
            result["appendedBytes"] = len(tail)
            result["restoredEntries"] = carried
            print(f"    carried {len(tail)} byte(s) of appended segment(s) forward: "
                  f"{', '.join(carried) or '(entries unnamed)'}")

            # An append that produced an unreadable artifact is worse than no
            # append at all, so the result is read back before anything uses it.
            try:
                after = Initramfs(arguments.regenerated)
            except QualificationError as error:
                print(f"BLOCKED: the initramfs became unreadable after restoring "
                      f"its appended segment: {error}", file=sys.stderr)
                return 2
            result["regeneratedSegments"] = [s.encoding for s in after.segments]
            absent = [name for name in carried if name not in after.names]
            if absent:
                print("BLOCKED: entries were carried forward but are not readable "
                      f"in the result: {', '.join(absent)}", file=sys.stderr)
                return 2

    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

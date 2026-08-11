#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refuse a source copy that is far larger than a source tree should be.

Written after an operations script copied the whole repository — including
tens of gigabytes of generated images under ``build/out`` — into a work
directory, three times, and filled the WSL virtual disk until the distribution
remounted read-only and every subsequent command failed with an I/O error. The
build itself was innocent: ``.containerignore`` already excludes those trees.
What went wrong was a ``cp -a`` in a qualification script, and nothing objected.

So this objects. It measures what a copy would actually transfer, compares it
against what a *source* tree plausibly weighs, and exits non-zero with the
directories responsible. It is deliberately dumb: no allowlist to keep current,
no guess about intent, just a size and a list of the biggest offenders — because
the failure mode is somebody adding a new generated directory nobody thought to
exclude, and an allowlist would not have known about that one either.

Usage::

    check-copy-size.py <source> [--limit-mb N] [--exclude DIR ...]

Exits 0 if the copy is within the limit, 2 if it is not, 3 if the source does
not exist. The message names what to exclude.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

#: What a source checkout of this repository plausibly weighs, in megabytes.
#: Generous: the working tree with its assets and evidence is well under this,
#: and the point is to catch a copy that is an order of magnitude wrong rather
#: than to police growth.
DEFAULT_LIMIT_MB = 4096

#: Directories a qualification copy never needs, and which are large. Excluded
#: by default so that a caller gets the right answer without having to know the
#: history that put each one here.
DEFAULT_EXCLUDES = (
    ".git",
    "build/out",
    "node_modules",
    "target",
    "desktop/src-tauri/target",
    "__pycache__",
)


def _tree_size(root: Path, excludes: frozenset[str]) -> tuple[int, dict[str, int]]:
    """Bytes the copy would move, and the per-top-level-directory breakdown."""
    total = 0
    by_directory: dict[str, int] = {}
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
        except ValueError:  # pragma: no cover - defensive
            continue
        parts = relative.parts
        if any(
            excluded in ("/".join(parts[: index + 1]), parts[index])
            for index in range(len(parts))
            for excluded in excludes
        ):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total += size
        by_directory[parts[0] if parts else "."] = (
            by_directory.get(parts[0] if parts else ".", 0) + size
        )
    return total, by_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-copy-size.py", description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--limit-mb", type=int, default=DEFAULT_LIMIT_MB)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument(
        "--quiet", action="store_true", help="print only when the copy is refused"
    )
    arguments = parser.parse_args(argv)

    root = Path(arguments.source)
    if not root.is_dir():
        print(f"check-copy-size: {root} is not a directory", file=sys.stderr)
        return 3

    excludes = frozenset(DEFAULT_EXCLUDES) | frozenset(arguments.exclude)
    total, by_directory = _tree_size(root, excludes)
    megabytes = total / (1024 * 1024)
    if not arguments.quiet:
        print(f"check-copy-size: {megabytes:,.0f} MB would be copied from {root}")

    if megabytes <= arguments.limit_mb:
        return 0

    biggest = sorted(by_directory.items(), key=lambda item: item[1], reverse=True)[:5]
    print(
        f"check-copy-size: refusing — {megabytes:,.0f} MB exceeds the "
        f"{arguments.limit_mb:,} MB limit for a source copy.",
        file=sys.stderr,
    )
    print("  largest directories:", file=sys.stderr)
    for name, size in biggest:
        print(f"    {name:<28} {size / (1024 * 1024):>10,.0f} MB", file=sys.stderr)
    print(
        "  exclude the generated ones, or raise --limit-mb if this is genuinely source.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

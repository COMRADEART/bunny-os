#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy exactly the locked packages into the snapshot, and nothing else.

Two failures matter equally and are reported separately, because they have
different causes and different fixes:

* a locked package that is **missing** from the source — the snapshot would be
  incomplete and the build would discover it at install time;
* a package present in the source that is **not in the lock** — the snapshot
  would contain something nobody decided to include, and a later build could
  resolve to it.

Checksums are recomputed rather than trusted. The lock records what resolution
saw; this records what materialisation copied, and the point of a
content-addressed snapshot is that the two are checked against each other rather
than assumed to agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402

CHUNK = 1024 * 1024


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect-snapshot-packages")
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    locked = {str(entry["fileName"]): entry for entry in lock["packages"]}

    available = {path.name: path for path in args.source.rglob("*.rpm")}

    missing = sorted(set(locked) - set(available))
    if missing:
        raise SystemExit(
            f"BLOCKED: {len(missing)} locked packages are not in {args.source}:\n  "
            + "\n  ".join(missing[:20])
            + "\nThe snapshot would be incomplete, and the build would find out at install time."
        )

    extra = sorted(set(available) - set(locked))
    if extra:
        raise SystemExit(
            f"BLOCKED: {len(extra)} packages are present but not in the lock:\n  "
            + "\n  ".join(extra[:20])
            + "\nA snapshot containing a package nobody decided to include is a snapshot a later "
            "build could resolve against."
        )

    args.destination.mkdir(parents=True, exist_ok=True)
    mismatched: list[str] = []
    copied = 0
    for name, entry in sorted(locked.items()):
        source = available[name]
        actual = digest(source)
        if actual != entry["checksum"]:
            mismatched.append(f"{name}: lock {entry['checksum'][:16]} vs file {actual[:16]}")
            continue
        shutil.copy2(source, args.destination / name)
        copied += 1

    if mismatched:
        raise SystemExit(
            f"BLOCKED: {len(mismatched)} packages do not match their locked checksum:\n  "
            + "\n  ".join(mismatched[:20])
            + "\nThe bytes on disk are not the bytes resolution recorded."
        )

    print(f"    {copied} packages copied, every checksum matched")
    print(f"    into {display_path(args.destination, Path.cwd())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2) from None
        raise

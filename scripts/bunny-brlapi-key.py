#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the BrlAPI authorisation key on the installed device.

`brlapi-0.8.7-8.fc44` mints this key in its `%post` scriptlet with `mcookie`,
and RPM marks the path `%ghost` — the package ships no content, the scriptlet
creates it. In a container build that scriptlet runs *at image build time*, so
the key ends up in the image, which means:

* every device installed from one image shares one BrlAPI authorisation key;
* anyone holding the image holds that key;
* and the file differs between two builds of the same commit, which is how it
  came to attention — it was one of fifteen files that differed between two
  independent builders.

BrlAPI is the interface a screen reader uses to reach the braille display. The
key authorises a client to connect to `brltty`. A key shared across every
installation is a weak authorisation boundary, and the fix must not weaken the
accessibility path to strengthen it: a device whose braille display stops
working because a reproducibility check wanted a matching digest would be a bad
trade, and this project's users are the ones who would pay for it.

So the generation moves to the device and nothing else changes. Same source of
randomness the packaging uses (the kernel CSPRNG, via `os.urandom`), same
format, same ownership, same mode. A missing key is regenerated rather than
reported, because the failure mode of *no key* is *no braille output*.

Deterministic generation is refused outright. A per-device secret derived from
anything reproducible is not a secret, and making this file match between two
builds by generating it deterministically would satisfy the comparison while
destroying the property the file exists for.
"""

from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import sys

#: brltty's own scriptlet uses `mcookie`, which emits 128 bits as 32 lowercase
#: hex characters followed by a newline. Matching the format exactly means
#: nothing downstream has to care which of the two produced the file.
KEY_BYTES = 16
DEFAULT_PATH = Path("/etc/brlapi.key")
DEFAULT_GROUP = "brlapi"
MODE = 0o640


def resolve_group(name: str) -> int:
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        return -1


def generate(path: Path, *, group: str = DEFAULT_GROUP, force: bool = False) -> int:
    if path.exists() and path.stat().st_size > 0 and not force:
        # Not an error, and deliberately not a regeneration. Rotating the key on
        # every boot would invalidate any client that had already been
        # authorised, and the service is ordered before brltty precisely so that
        # the key is stable for the life of the installation.
        print(f"{path} already exists and is not empty; leaving it alone")
        return 0

    # os.urandom is the kernel CSPRNG. It is the same source mcookie draws from,
    # and it blocks until the pool is initialised, which matters on a first boot
    # where entropy is scarce.
    value = os.urandom(KEY_BYTES).hex()

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Written through a temporary file with the final mode set *before* any
    # content reaches it, so the key is never briefly world-readable. The
    # rename is atomic, so a crash leaves either the old key or the new one and
    # never a truncated file.
    temporary = parent / f".{path.name}.new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(value + "\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    gid = resolve_group(group)
    if gid >= 0:
        os.chown(temporary, 0, gid)
    else:
        # The group is created by the brlapi package. If it is absent the
        # package is absent, and a key nobody can read is worse than no key:
        # say so rather than shipping a file with surprising ownership.
        print(
            f"warning: group {group!r} does not exist; the key is owned by root:root and "
            "brltty clients will not be able to read it. Is the brlapi package installed?",
            file=sys.stderr,
        )
    os.chmod(temporary, MODE)
    os.replace(temporary, path)

    # The value itself is never printed. A secret in a journal is a secret in
    # every log shipper, crash report and support bundle downstream of it.
    print(f"generated {path} ({KEY_BYTES * 8}-bit key, mode {MODE:04o}, group {group})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="bunny-brlapi-key")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--group", default=DEFAULT_GROUP)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing key; used by recovery, not by the boot service",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether a usable key exists, without creating one",
    )
    args = parser.parse_args()

    if args.check:
        if not args.path.exists():
            print(f"{args.path}: absent")
            return 1
        info = args.path.stat()
        mode = info.st_mode & 0o777
        problems = []
        if info.st_size == 0:
            problems.append("empty")
        if mode != MODE:
            problems.append(f"mode {mode:04o} (expected {MODE:04o})")
        if info.st_uid != 0:
            problems.append(f"owner uid {info.st_uid} (expected 0)")
        if problems:
            print(f"{args.path}: " + ", ".join(problems))
            return 1
        print(f"{args.path}: present, {info.st_size} bytes, mode {mode:04o}")
        return 0

    return generate(args.path, group=args.group, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

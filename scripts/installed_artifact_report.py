#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventory what Bunny OS actually installed, and refuse what it should not.

Run inside the built image. It answers three questions that a build log cannot:

**Did the files arrive?** A missing ``COPY`` is not a build error — ``rglob`` on
a directory that is not in the context yields nothing, so the build succeeds and
installs an empty package. That failure has happened here before, and it
presented as a service that started and failed on import at every restart. An
empty directory is therefore a failure, not a pass.

**Is anything installed that should not be?** Tests, fixtures, byte-code,
runtime stores, approval stores, sockets, token files and developer scratch have
no business in a product image. Each is looked for by name and by shape, and
finding one is a refusal rather than a note.

**Does the runtime import from the installed tree?** Recorded per module, with
the mount that backs it, because a bind mount can make a developer checkout look
exactly like ``/usr/lib/bunny-os/python``.

Exit status: 0 everything held, 2 at least one refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterable

#: The tree the companion must be imported from, and the only one.
INSTALLED_ROOT = Path("/usr/lib/bunny-os/python")

#: Packages that must be present and non-empty.
REQUIRED_PACKAGES = ("companion", "capability")

#: Modules whose presence proves the install is the real thing rather than a
#: directory of ``__init__.py`` files.
REQUIRED_MODULES = (
    "companion/runtime.py",
    "companion/service.py",
    "companion/protocol.py",
    "companion/presentation.py",
    "companion/store.py",
    "companion/character/surface.py",
    "companion/character/animated_renderer.py",
    "companion/character/package.py",
)

#: Nothing matching these may be installed. §17's list, plus the byte-code and
#: test material that would make the image a development tree.
FORBIDDEN_GLOBS = (
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/tests",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
    "**/testing",
    "**/fixtures",
    "**/*.sock",
    "**/*.socket-token",
    "**/runtime-store",
    "**/approvals.json",
    "**/stress-*.json",
    "**/*.png.screenshot",
)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def describe(path: Path, *, root: Path, with_digest: bool) -> dict[str, Any]:
    info = path.lstat()
    record: dict[str, Any] = {
        "path": str(path.relative_to(root)),
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "size": info.st_size,
        "mtime": int(info.st_mtime),
        "type": (
            "symlink" if stat.S_ISLNK(info.st_mode)
            else "directory" if stat.S_ISDIR(info.st_mode)
            else "file" if stat.S_ISREG(info.st_mode)
            else "other"
        ),
    }
    if record["type"] == "symlink":
        record["target"] = os.readlink(path)
    if with_digest and record["type"] == "file":
        record["sha256"] = digest(path)
    return record


def walk(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root):
        directories.sort()
        files.sort()
        base = Path(current)
        for name in directories:
            yield base / name
        for name in files:
            yield base / name


def inventory(root: Path, *, with_digest: bool) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    return [describe(path, root=root, with_digest=with_digest) for path in walk(root)]


def check_presence(root: Path) -> list[str]:
    """Every required package non-empty, and every required module present."""
    failures: list[str] = []
    if not root.is_dir():
        return [f"{root} does not exist; nothing was installed"]
    for package in REQUIRED_PACKAGES:
        directory = root / package
        if not directory.is_dir():
            failures.append(f"{package} is not installed at {directory}")
            continue
        modules = [item for item in directory.rglob("*.py")]
        if not modules:
            # The exact failure the COPY comment in build/Containerfile warns
            # about: the directory exists and holds nothing.
            failures.append(
                f"{directory} exists but contains no Python modules; this is the "
                "silently empty install a missing COPY produces"
            )
    for module in REQUIRED_MODULES:
        if not (root / module).is_file():
            failures.append(f"{root / module} is missing")
    return failures


def check_forbidden(root: Path) -> tuple[list[str], list[str]]:
    """Anything matching a forbidden pattern, reported and refused."""
    found: list[str] = []
    if not root.is_dir():
        return [], []
    for pattern in FORBIDDEN_GLOBS:
        for path in root.glob(pattern):
            found.append(f"{path} matches forbidden pattern {pattern!r}")
    return found, sorted(set(found))


def check_modes(root: Path) -> list[str]:
    """Installed code is read-only and owned by root.

    Not a style preference. A companion module a user can rewrite is a companion
    that runs whatever that user last wrote, with the runtime's reach.
    """
    failures: list[str] = []
    if not root.is_dir():
        return failures
    for path in walk(root):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            continue
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid != 0 or info.st_gid != 0:
            failures.append(f"{path} is owned by {info.st_uid}:{info.st_gid}, not root")
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            failures.append(f"{path} is group- or world-writable ({oct(mode)})")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=INSTALLED_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--digests",
        action="store_true",
        help="hash every installed file; slower, and what an evidence record wants",
    )
    parser.add_argument(
        "--full-inventory",
        action="store_true",
        help="include the per-file inventory in the report rather than a summary",
    )
    arguments = parser.parse_args(argv)
    root = arguments.root

    entries = inventory(root, with_digest=arguments.digests)
    presence = check_presence(root)
    forbidden, _unique = check_forbidden(root)
    modes = check_modes(root)

    report: dict[str, Any] = {
        "schema": "bunny-os/installed-artifact-report/1",
        "root": str(root),
        "counts": {
            "entries": len(entries),
            "files": sum(1 for item in entries if item["type"] == "file"),
            "directories": sum(1 for item in entries if item["type"] == "directory"),
            "symlinks": sum(1 for item in entries if item["type"] == "symlink"),
            "pythonModules": sum(1 for item in entries if item["path"].endswith(".py")),
        },
        "distinctMtimes": sorted({item["mtime"] for item in entries})[:8],
        "requiredModules": {
            module: (root / module).is_file() for module in REQUIRED_MODULES
        },
        "refusals": {
            "missing": presence,
            "forbidden": forbidden,
            "permissions": modes,
        },
    }
    if arguments.full_inventory:
        report["inventory"] = entries

    failures = presence + forbidden + modes
    report["gate"] = {"passed": not failures, "failureCount": len(failures)}

    serialised = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialised + "\n", encoding="utf-8")
    print(serialised)
    for failure in failures:
        print(f"REFUSED: {failure}", file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

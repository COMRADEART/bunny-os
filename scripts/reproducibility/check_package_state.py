#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that the specific state which differed between two builders no longer does.

Four of the five differing dimensions were driven by fifteen files, and those
fifteen fall into four groups with four different causes. A single "did the
comparison pass" check would tell you they are fixed without telling you which
one regressed when one of them comes back.

So each group is checked by name against a collected artifact:

``fontconfig``
    the seven caches. Each embeds the mtime of the directory it indexes, and
    font-directory mtimes were wall-clock install times.
``rpmdb``
    ``/usr/share/rpm/rpmdb.sqlite``, plus the libdnf5 databases and the
    ``system.toml`` cookie derived from the rpmdb.
``countme``
    the two dnf telemetry counters, which must not be present at all.
``sbom``
    the SBOM's self-reference: the SPDX document root names the scanned
    archive and carries its digest, so leaving it in makes the package
    inventory match only when the archives are byte-identical.

Run against one collection it reports what is present. Run against two it
reports whether the group differs, which is the question that matters.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402

REFUSED = 2

GROUPS = {
    "fontconfig": {
        "pattern": re.compile(r"^usr/lib/fontconfig/cache/.*\.cache-\d+$"),
        "mustBeAbsent": False,
        "reason": (
            "each cache embeds the mtime of the directory it indexes; those mtimes are wall-clock "
            "install times unless the finaliser pins them to the build epoch"
        ),
    },
    "rpmdb": {
        "pattern": re.compile(
            r"^(usr/share/rpm/rpmdb\.sqlite|usr/lib/sysimage/libdnf5/"
            r"(system\.toml|transaction_history\.sqlite))$"
        ),
        "mustBeAbsent": False,
        "reason": (
            "rpm stamps every header with INSTALLTIME from the system clock; the libdnf5 "
            "system.toml cookie is derived from the rpmdb and follows it"
        ),
    },
    "countme": {
        "pattern": re.compile(r"^var/lib/dnf/repos/.*/countme$"),
        "mustBeAbsent": True,
        "reason": (
            "Fedora's per-installation usage counter. It is telemetry and must not be in an "
            "immutable artifact at all"
        ),
    },
    "sqlite-residue": {
        "pattern": re.compile(r"\.sqlite-(wal|shm)$"),
        "mustBeAbsent": True,
        "reason": "write-ahead-log residue is transaction state, not content; checkpoint it",
    },
    "sbom": {
        "pattern": None,
        "mustBeAbsent": False,
        "reason": "the SPDX document root names the scanned archive and carries its own digest",
    },
}


def collect(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(
            f"BLOCKED: no collected artifact at {path}. This check reads a dimension collection; "
            "with none there is nothing to check, and an absent input is not a pass."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def members(document: dict, pattern: re.Pattern[str] | None) -> dict[str, str]:
    digests = (document.get("dimensions") or {}).get("fileDigests") or {}
    if pattern is None:
        return {}
    return {name: value for name, value in digests.items() if pattern.match(name)}


def check_sbom(document: dict) -> tuple[bool, str]:
    """The SBOM must not describe the archive that contains it."""
    inventory = (document.get("dimensions") or {}).get("packageInventory") or []
    offenders = [
        entry
        for entry in inventory
        if isinstance(entry, str)
        and ("sha256:" in entry or entry.startswith("build/") or ".oci.tar" in entry)
    ]
    if offenders:
        return False, (
            f"{len(offenders)} inventory entries are self-referential: "
            + ", ".join(offenders[:5])
            + ". The document root names the scanned archive and carries its digest, so the "
            "inventory could only match when the archives are byte-identical — which rawArchive "
            "already measures"
        )
    return True, f"{len(inventory)} package entries, none self-referential"


def main() -> int:
    parser = argparse.ArgumentParser(prog="check_package_state")
    parser.add_argument("--dimensions", required=True, type=Path)
    parser.add_argument("--against", type=Path, help="a second collection, to compare against")
    parser.add_argument("--kind", required=True, choices=sorted(GROUPS))
    args = parser.parse_args()

    group = GROUPS[args.kind]
    first = collect(args.dimensions)

    if args.kind == "sbom":
        ok, detail = check_sbom(first)
        print(f"{'ok  ' if ok else 'FAIL'}  sbom: {detail}")
        return 0 if ok else REFUSED

    present = members(first, group["pattern"])

    if group["mustBeAbsent"]:
        if present:
            print(f"FAIL  {args.kind}: {len(present)} present and none may be", file=sys.stderr)
            for name in sorted(present)[:10]:
                print(f"        {name}", file=sys.stderr)
            print(f"      {group['reason']}", file=sys.stderr)
            return REFUSED
        print(f"ok    {args.kind}: absent, as required")
        return 0

    if not args.against:
        print(f"{args.kind}: {len(present)} files present in {display_path(args.dimensions, Path.cwd())}")
        for name in sorted(present)[:10]:
            print(f"  {name}")
        print(
            "  no second collection given, so this reports presence rather than determinism. "
            "Pass --against to compare two builders."
        )
        return 0

    second = collect(args.against)
    other = members(second, group["pattern"])
    differing = sorted(
        name for name in set(present) | set(other) if present.get(name) != other.get(name)
    )
    if differing:
        print(f"FAIL  {args.kind}: {len(differing)} of {len(present)} files differ", file=sys.stderr)
        for name in differing[:10]:
            print(f"        {name}", file=sys.stderr)
        print(f"      {group['reason']}", file=sys.stderr)
        return REFUSED

    print(f"ok    {args.kind}: {len(present)} files, identical between the two builders")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assert that a commit is the qualification target it claims to be.

``qualification-target.json`` cannot name the commit that contains it — writing
that hash into the file would change the hash. It names its parent instead, and
the target is the child.

That relationship is checkable and this is what checks it, so "Commit C" is a
fact about a commit rather than a convention somebody has to remember. A hosted
builder runs this before building, which is the only place the question matters:
a runner pointed at the wrong commit would otherwise produce a perfectly good
artifact of something nobody asked for.

Exit codes:
    0   the commit is the target its own file describes
    2   it is not, or there is no target file
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REFUSED = 2


def git(*arguments: str) -> tuple[int, str]:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True)
    return result.returncode, result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(prog="assert-target-commit")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--target", type=Path,
                        default=Path("build/inputs/qualification-target.json"))
    args = parser.parse_args()

    code, commit = git("rev-parse", args.commit)
    if code != 0 or len(commit) != 40:
        print(f"BLOCKED: cannot resolve {args.commit}", file=sys.stderr)
        return REFUSED

    code, parent = git("rev-parse", f"{args.commit}^")
    if code != 0 or len(parent) != 40:
        print(f"BLOCKED: {commit[:12]} has no single parent", file=sys.stderr)
        return REFUSED

    code, blob = git("show", f"{args.commit}:{args.target.as_posix()}")
    if code != 0:
        print(
            f"BLOCKED: {commit[:12]} does not contain {args.target}. A qualification target is a "
            "commit that carries its own target description; a commit without one is not a target, "
            "whatever a workflow input says.",
            file=sys.stderr,
        )
        return REFUSED

    target = json.loads(blob)
    named = str(target.get("parentCommit", ""))
    if named != parent:
        print(
            f"BLOCKED: {commit[:12]} carries a target naming parent {named[:12]}, and its actual "
            f"parent is {parent[:12]}.\n"
            "The target file was written against a different commit and then moved, so what a "
            "builder would reproduce is not what the target describes.",
            file=sys.stderr,
        )
        return REFUSED

    print(f"{commit[:12]} is the qualification target")
    print(f"  parent        {parent[:12]}")
    print(f"  epoch         {target.get('buildEpoch')}")
    print(f"  base          {target.get('retainedBaseDigest')}")
    print(f"  builder       {target.get('builderImageDigest')}")
    print(f"  snapshot      {target.get('packageSnapshotDigest')}")
    for kind, reference in sorted((target.get("publishedInputs") or {}).items()):
        print(f"  published {kind:9} {reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

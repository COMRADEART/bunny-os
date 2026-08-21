#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut the Phase 7 frozen-evidence record.

Phase 6 measured what the evidence-immutability guard actually covers and
found that everything declared after ``fa49380`` — phases 4, 5 and 6 included
— is pinned by nothing. This script cuts the successor record: every tracked
file under ``qualification/`` except the trees that are not frozen evidence,
with byte count and SHA-256 for each.

Run only from a clean working tree, and only deliberately: the record is cut
once at a named commit and then never regenerated. Regenerating it to make a
failure go away is the move the guard exists to catch; the script refuses a
dirty tree so the record can never describe bytes that no commit contains.

``qualification/**`` is ``-text``, so the checked-out bytes equal the
committed blob on every host, and hashing the working tree hashes the record
of record.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECORD = Path(__file__).resolve().parent / "frozen-evidence.json"

#: Not frozen evidence, so not pinned. The *policy* comments live in
#: tests/release/test_frozen_evidence.py; this list must match its
#: ``EXEMPT_PREFIXES`` exactly, and the test asserts that it does.
EXEMPT_PREFIXES = (
    "qualification/phase7/",
    "qualification/grader/",
)

#: Maintained tooling inside frozen trees, named singly so a file appearing
#: beside one still fails the added-files check. Must match the test's
#: ``MAINTAINED_TOOLING``.
MAINTAINED_TOOLING = frozenset({
    "qualification/installed-system/scripts/import_matrix_results.py",
    "qualification/__init__.py",
})


def main() -> int:
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "qualification"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    # A change under an exempt prefix cannot alter what gets pinned; the tree
    # this script lives in is itself exempt and is being written to right now.
    dirty = "\n".join(
        line for line in status
        if not line[3:].startswith(EXEMPT_PREFIXES)
    ).strip()
    if dirty:
        print("REFUSED: the qualification tree is not clean:", file=sys.stderr)
        print(dirty, file=sys.stderr)
        return 2

    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "qualification"],
        capture_output=True, text=True, check=True,
    ).stdout
    names = sorted(n for n in tracked.split("\0") if n)

    frozen: dict[str, dict[str, object]] = {}
    for name in names:
        if name.startswith(EXEMPT_PREFIXES) or name in MAINTAINED_TOOLING:
            continue
        raw = (ROOT / name).read_bytes()
        frozen[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    RECORD.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "phase": "phase7",
                "recordCommit": commit,
                "exemptPrefixes": list(EXEMPT_PREFIXES),
                "maintainedTooling": sorted(MAINTAINED_TOOLING),
                "frozenEvidence": frozen,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"pinned {len(frozen)} files at {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Move bulky raw evidence out of the committable tree, digest-first.

Screendumps (~3 MB of PPM each) and level-5 swtpm command traces
(~350 KB per boot) belong to the evidence record but not to Git: across a
seventy-boot matrix they are more than a gigabyte of bytes that re-derive
nothing. This tool moves them to the trace root and writes each run's
``retention-manifest.json``, but only after re-deriving every file's digest
and matching it against the record — a file that no longer digests to what
the record claims is not retained, it is reported, because relocating it
would launder the mismatch.

The importer accepts a missing evidence file only when the retention
manifest names it with the record's own digest, so the digest chain is
unbroken end to end: record → manifest → retained bytes on the builder.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys

RETAIN_PATTERNS = ("screenshots/", "swtpm.log")


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="retain_bulky_evidence")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--trace-root", type=Path, required=True)
    args = parser.parse_args()

    problems: list[str] = []
    moved_total = 0
    for entry in sorted(args.evidence_root.iterdir()):
        record_path = entry / "record.json"
        if not entry.is_dir() or not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        manifest_path = entry / "retention-manifest.json"
        existing: list[dict] = []
        if manifest_path.is_file():
            existing = json.loads(
                manifest_path.read_text(encoding="utf-8")).get("files", [])
        retained: list[dict] = list(existing)
        for entry_file in record.get("evidenceFiles", []):
            rel = str(entry_file["path"])
            if not any(rel.startswith(p) or rel == p for p in RETAIN_PATTERNS):
                continue
            source = entry / rel
            if not source.is_file():
                continue
            actual = sha256_file(source)
            if actual != entry_file.get("sha256"):
                problems.append(f"{entry.name}: {rel} digests to {actual[:12]} but "
                                f"the record says {str(entry_file.get('sha256'))[:12]}; "
                                "not retained, not deleted — investigate")
                continue
            target = args.trace_root / entry.name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            retained.append({
                "path": rel,
                "sha256": entry_file["sha256"],
                "sizeBytes": entry_file.get("sizeBytes"),
                "retainedAt": str(target),
                "host": socket.gethostname(),
                "lifecycle": "raw evidence retained outside git on the builder",
                "movedAt": datetime.datetime.now(datetime.timezone.utc)
                .isoformat(timespec="seconds"),
            })
            moved_total += 1
        if (entry / "screenshots").is_dir() and \
                not any((entry / "screenshots").iterdir()):
            (entry / "screenshots").rmdir()
        if retained != existing:
            manifest_path.write_text(json.dumps({
                "schemaVersion": 1,
                "evidenceId": record.get("evidenceId", entry.name),
                "files": retained,
            }, indent=2) + "\n", encoding="utf-8")
    print(f"retained {moved_total} files under {args.trace_root}")
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

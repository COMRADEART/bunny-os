#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Move bulky raw evidence out of the committable tree, digest-first.

Same discipline as the TPM pass: screendumps (~2.3 MB of PPM each) belong
to the evidence record but not to Git — across this matrix they are
~2.5 GB that re-derive nothing. Each file's digest is re-derived and
matched against the run's own evidence manifest *before* the move; a file
that no longer digests to what the record claims is not retained, it is
reported, because relocating it would launder the mismatch. The importer
accepts a missing evidence file only when the run's
``retention-manifest.json`` names it with the record's own digest."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import socket

RETAIN_PATTERNS = ("screenshots/",)


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def retain_run(run_dir: Path, trace_root: Path, problems: list[str],
               subtree: str = "") -> int:
    record_path = run_dir / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    manifest_entries = {e["path"]: e for e in
                        record.get("evidenceManifest", [])}
    manifest_path = run_dir / "retention-manifest.json"
    retained: list[dict] = []
    if manifest_path.is_file():
        retained = json.loads(
            manifest_path.read_text(encoding="utf-8")).get("files", [])
    moved = 0
    for rel, entry in sorted(manifest_entries.items()):
        if not any(rel.startswith(p) or rel == p.rstrip("/")
                   for p in RETAIN_PATTERNS):
            continue
        source = run_dir / rel
        if not source.is_file():
            continue
        actual = sha256_file(source)
        if actual != entry["sha256"]:
            problems.append(f"{run_dir.name}/{rel}: digests to "
                            f"{actual[:12]}, record says "
                            f"{entry['sha256'][:12]} — not retained")
            continue
        # the destination preserves the run's position in the evidence
        # tree: an invalidated run shares its run ID with its rerun, and a
        # flat layout let one overwrite the other's retained bytes
        destination = trace_root / subtree / run_dir.name / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        retained.append({"path": rel, "sha256": entry["sha256"],
                         "sizeBytes": entry["sizeBytes"],
                         "retainedAt": str(destination)})
        moved += 1
    if moved:
        manifest_path.write_text(json.dumps({
            "retainedOn": socket.gethostname(),
            "retainedTime": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "files": retained,
        }, indent=2) + "\n", encoding="utf-8")
        for sub in sorted(run_dir.rglob("*"), reverse=True):
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(prog="retain_bulky_evidence")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--trace-root", type=Path, required=True)
    args = parser.parse_args()
    problems: list[str] = []
    moved_total = 0
    roots: list[tuple[Path, str]] = [(args.evidence_root, "")]
    invalidated = args.evidence_root / "invalidated"
    if invalidated.is_dir():
        roots += [(d, f"invalidated/{d.name}")
                  for d in sorted(invalidated.iterdir()) if d.is_dir()]
    for root, subtree in roots:
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "record.json").is_file():
                moved_total += retain_run(entry, args.trace_root, problems,
                                          subtree)
    for problem in problems:
        print(f"  problem: {problem}")
    print(f"retained {moved_total} file(s) under {args.trace_root}")
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

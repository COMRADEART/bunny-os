#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the retention manifest for a qualification run.

Evidence lives outside the repository — VM disks, serial logs, captures — and
committed records reference it by digest. The manifest is what makes that
reference checkable later: it says which bytes were retained, where, and under
what class.

It also refuses to be a place where a passphrase quietly ends up. Program E
injects passphrases ephemerally, and the failure mode is not someone committing
one deliberately but a serial log capturing a prompt echo. So every retained file
is scanned, anything matching is marked, and the manifest exits non-zero rather
than describing a secret-bearing artifact as retained.

    python retention-manifest.py --run ENC-20260803-01 \\
        --root /var/lib/bunny-qualification --output manifest.json

Exit 0 when the manifest is clean, 2 when a retained artifact appears to contain
a secret or the run directory is missing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from hashlib import sha256
from pathlib import Path

# Classes from STORAGE_POLICY.md. A file with no explicit class is diagnostic:
# retained while a finding is open, which is the conservative default.
RETENTION_CLASSES = ("authority", "diagnostic", "disposable")

SECRET_PATTERNS = (
    re.compile(rb"passphrase\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(rb"password\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"tpm[_-]?owner[_-]?auth\s*[:=]\s*\S+", re.IGNORECASE),
)

# Scanning a 40 GiB disk image byte-for-byte is not useful; the head and tail
# hold the console output and metadata where an echoed prompt would land.
SCAN_WINDOW = 4 * 1024 * 1024


def classify(path: Path, classes: dict[str, str]) -> str:
    for prefix, retention in classes.items():
        if prefix in path.as_posix():
            return retention
    return "diagnostic"


def contains_secret(path: Path) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(SCAN_WINDOW)
            if size > SCAN_WINDOW * 2:
                handle.seek(-SCAN_WINDOW, 2)
                tail = handle.read(SCAN_WINDOW)
            else:
                tail = b""
    except OSError:
        # Unreadable is not clean. A file that cannot be scanned is marked.
        return True
    return any(pattern.search(head) or pattern.search(tail) for pattern in SECRET_PATTERNS)


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build(run: str, root: Path, classes: dict[str, str], *, now: str) -> dict:
    run_root = root / "evidence" / run
    if not run_root.is_dir():
        raise FileNotFoundError(run_root)

    entries = []
    for path in sorted(p for p in run_root.rglob("*") if p.is_file()):
        stat = path.stat()
        secret = contains_secret(path)
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "size": stat.st_size,
            "sha256": digest(path),
            "createdTime": datetime.datetime.fromtimestamp(
                stat.st_mtime, datetime.timezone.utc
            ).isoformat(),
            "sourceRun": run,
            "retentionClass": classify(path, classes),
            "containsSecrets": secret,
            # Nothing here is redacted automatically. A secret-bearing artifact is
            # reported so a human removes it, not quietly rewritten.
            "redactionStatus": "REVIEW_REQUIRED" if secret else "NOT_REQUIRED",
        })

    flagged = [e for e in entries if e["containsSecrets"]]
    return {
        "schemaVersion": 1,
        "sourceRun": run,
        "root": root.as_posix(),
        "generatedAt": now,
        "fileCount": len(entries),
        "totalBytes": sum(e["size"] for e in entries),
        "secretBearingCount": len(flagged),
        "clean": not flagged,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run identifier, e.g. ENC-20260803-01")
    parser.add_argument("--root", type=Path, default=Path("/var/lib/bunny-qualification"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--authority", action="append", default=[],
        help="path fragment whose files are retention class 'authority' (repeatable)",
    )
    parser.add_argument(
        "--disposable", action="append", default=[],
        help="path fragment whose files are retention class 'disposable' (repeatable)",
    )
    args = parser.parse_args()

    classes = {fragment: "authority" for fragment in args.authority}
    classes.update({fragment: "disposable" for fragment in args.disposable})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        manifest = build(args.run, args.root, classes, now=now)
    except FileNotFoundError as exc:
        print(f"BLOCKED: run directory {exc} does not exist")
        return 2

    print(f"retention manifest: {args.run}")
    print(f"  files: {manifest['fileCount']}  bytes: {manifest['totalBytes']}")
    for retention in RETENTION_CLASSES:
        count = sum(1 for e in manifest["entries"] if e["retentionClass"] == retention)
        print(f"  {retention:12} {count}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")
        print(f"  wrote {args.output}")

    if not manifest["clean"]:
        print(f"\nBLOCKED: {manifest['secretBearingCount']} retained artifact(s) match a "
              "secret pattern. Plaintext passphrases are never retained; remove them and "
              "rebuild the manifest.")
        for entry in manifest["entries"]:
            if entry["containsSecrets"]:
                print(f"  {entry['path']}")
        return 2

    print("\nNo retained artifact matched a secret pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

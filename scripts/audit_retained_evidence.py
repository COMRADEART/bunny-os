#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit every retained evidence digest against the bytes now in the tree.

Evidence records attest their own files by sha256. Nothing outside the record
re-checks those digests before a new pass starts building on them, so a
checkout that silently rewrote bytes — a content filter, `core.autocrlf`, a
`.gitattributes` regression — would be discovered only as an unexplainable
gate failure much later, if at all.

This audit is the check that runs first. For every record in every evidence
tree it re-hashes the attested files and reports:

  ok        bytes match the recorded digest
  eol       bytes differ, but a line-ending conversion of them matches — the
            file was damaged by a filter, not by a re-run
  mismatch  bytes differ for some other reason
  retained  the file is not in the tree and a retention manifest carries its
            digest (bulky or sensitive artifacts are stored outside git)
  missing   the file is not in the tree and nothing carries its digest

`eol` is called out separately because it is the failure this pass was told
to look for and because its remedy is different: the bytes are recoverable
from git with the filter corrected, whereas a `mismatch` means the evidence
no longer describes what is on disk.

Two exit codes, because the two findings mean different things:

  2  a filter damaged attested bytes (eol/mismatch), or an attested file is
     missing and is not on the known-gap list. This is the Stage 0 gate.
  3  only known pre-existing gaps remain — files attested by an older
     scenario that were never committed and never retention-recorded. Those
     records are frozen evidence about a superseded archive and may not be
     rewritten, so the gap is carried on an explicit list instead of being
     silently tolerated. A gap that is *not* on the list still exits 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

# The three evidence trees name their manifests differently: display-stack
# writes `evidenceManifest`, the TPM and installed-system scenarios write
# `evidenceFiles`. Both are lists of {path, sha256}.
MANIFEST_KEYS = ("evidenceManifest", "evidenceFiles")

EVIDENCE_ROOTS = (
    "qualification/display-stack/evidence",
    "qualification/tpm/evidence",
    "qualification/installed-system/evidence",
    "qualification/hardware",
)

# Attested-but-absent files carried from a superseded scenario.
#
# The installed-system run_scenario.py of the Commit I/J pass wrote the
# per-run writable disks into `evidenceFiles` with retentionClass
# "evidence", but the disks were never committed (they are large and carry
# guest state) and that pass had no retention manifest to record them in.
# The digests are therefore attested with nothing behind them.
#
# Those records are frozen evidence about the b9c317d archive and this pass
# is forbidden from editing them, so the gap is named here rather than
# repaired. It is scoped to the exact two basenames in the exact tree: a
# newly missing evidence file, or a missing file anywhere else, still fails.
KNOWN_UNRETAINED = {
    ("qualification/installed-system/evidence", "work/OVMF_VARS.qcow2"),
    ("qualification/installed-system/evidence", "work/target-disk.qcow2"),
}


def is_known_gap(record_rel: str, file_rel: str) -> bool:
    return any(record_rel.startswith(root) and file_rel == path
               for root, path in KNOWN_UNRETAINED)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def eol_variants(data: bytes) -> dict[str, bytes]:
    """The two conversions a Windows checkout can apply, in both directions.

    A file that arrived here CRLF-damaged matches its recorded digest once
    the CRLFs are undone; a file recorded on a CRLF checkout matches once
    they are applied. Naming which direction happened tells us whether the
    damage is in the working tree or in what git stores.
    """
    unix = data.replace(b"\r\n", b"\n")
    return {"crlf-to-lf": unix, "lf-to-crlf": unix.replace(b"\n", b"\r\n")}


def classify(record_dir: Path, entry: dict, retention: dict) -> dict:
    rel = entry["path"]
    expected = entry["sha256"]
    path = record_dir / rel
    result = {"path": rel, "expected": expected}

    if not path.is_file():
        kept = retention.get(rel)
        if kept is None:
            result["status"] = "missing"
            return result
        if kept.get("sha256") != expected:
            result["status"] = "missing"
            result["note"] = ("retention manifest names this file with a "
                              "different digest")
            return result
        if kept.get("lost"):
            result["status"] = "recorded-loss"
            result["note"] = kept["lost"]
            return result
        result["status"] = "retained"
        result["retainedAt"] = kept.get("retainedAt")
        # A retained copy is verified when this host is the retaining host.
        retained_path = Path(kept.get("retainedAt", ""))
        if retained_path.is_file():
            actual = sha256_file(retained_path)
            if actual != expected:
                result["status"] = "mismatch"
                result["actual"] = actual
                result["note"] = "retained copy does not match its digest"
        return result

    data = path.read_bytes()
    actual = sha256_bytes(data)
    if actual == expected:
        result["status"] = "ok"
        return result

    for direction, converted in eol_variants(data).items():
        if sha256_bytes(converted) == expected:
            result["status"] = "eol"
            result["actual"] = actual
            result["note"] = (f"bytes match after {direction} — a content "
                              "filter rewrote this file")
            return result

    result["status"] = "mismatch"
    result["actual"] = actual
    return result


def load_retention(record_dir: Path) -> dict:
    path = record_dir / "retention-manifest.json"
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {entry["path"]: entry for entry in manifest.get("files", [])}


def audit_record(record_path: Path) -> dict | None:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"record": str(record_path.relative_to(REPO_ROOT)),
                "unreadable": str(exc), "files": []}
    manifest = None
    for key in MANIFEST_KEYS:
        if isinstance(record.get(key), list):
            manifest = record[key]
            break
    if manifest is None:
        return None
    record_dir = record_path.parent
    retention = load_retention(record_dir)
    files = [classify(record_dir, entry, retention)
             for entry in manifest
             if isinstance(entry, dict) and "path" in entry
             and "sha256" in entry and entry["path"] != "record.json"]
    return {"record": str(record_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "files": files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path,
                        help="write the full audit as JSON here")
    parser.add_argument("--quiet", action="store_true",
                        help="print the summary only")
    args = parser.parse_args()

    audits = []
    for root_rel in EVIDENCE_ROOTS:
        root = args.repo_root / root_rel
        if not root.is_dir():
            continue
        for record_path in sorted(root.rglob("record.json")):
            audit = audit_record(record_path)
            if audit is not None:
                audits.append(audit)

    tally = {"ok": 0, "retained": 0, "recorded-loss": 0,
             "eol": 0, "mismatch": 0, "missing": 0}
    failures = []
    known_gaps = []
    for audit in audits:
        if audit.get("unreadable"):
            failures.append(f"{audit['record']}: unreadable — "
                            f"{audit['unreadable']}")
            continue
        for entry in audit["files"]:
            tally[entry["status"]] = tally.get(entry["status"], 0) + 1
            if entry["status"] not in ("eol", "mismatch", "missing"):
                continue
            note = f" ({entry['note']})" if entry.get("note") else ""
            line = f"{audit['record']}: {entry['path']} — {entry['status']}{note}"
            if entry["status"] == "missing" and is_known_gap(audit["record"],
                                                             entry["path"]):
                entry["status"] = "known-gap"
                tally["missing"] -= 1
                tally["known-gap"] = tally.get("known-gap", 0) + 1
                known_gaps.append(line)
            else:
                failures.append(line)

    if not args.quiet:
        for failure in failures:
            print(f"  problem: {failure}")
        for gap in known_gaps:
            print(f"  known gap: {gap}")

    summary = {
        "recordsAudited": len(audits),
        "filesAttested": sum(tally.values()),
        "byStatus": tally,
        "problems": len(failures),
        "knownGaps": len(known_gaps),
        "filterDamage": tally["eol"] + tally["mismatch"],
    }
    print(json.dumps(summary, indent=2))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps({"summary": summary, "problems": failures,
                        "knownGaps": known_gaps, "records": audits},
                       indent=2) + "\n",
            encoding="utf-8")
        print(f"audit written to {args.report}")

    if failures:
        return 2
    return 3 if known_gaps else 0


if __name__ == "__main__":
    sys.exit(main())

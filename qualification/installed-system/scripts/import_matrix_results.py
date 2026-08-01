#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import installed-system evidence into the qualification matrices.

The gate counts matrix rows; this is the only path by which a scenario run
becomes one. Each mapping names the evidence record it rests on, the record
is re-verified against the evidence context before anything is written, and
the row's method is ``virtual-machine`` — never more than the evidence is.

A scenario the harness did not run is not written at all: the existing
NOT_RUN row stays, because absence of evidence is already recorded honestly
and overwriting it with a fresher NOT_RUN would only disguise how long the
gap has stood.

The mapping between harness scenarios and matrix rows is explicit and small,
and refuses ambiguity: one matrix row rests on one or more named evidence
records, each of which must be a PASS for the row to become PASS. A FAIL
anywhere makes the row FAIL — a matrix that averages is a matrix that hides.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from release.installed import resolve_context, verify_record_binding  # noqa: E402
from release.matrix import parse_result  # noqa: E402

#: matrix -> row -> list of (record kind, evidence file names) that support it.
#: "scenario:<name>" is a run_scenario verdict; "collection:<file>" is an
#: offline collection verdict (its JSON carries its own result field).
ROW_EVIDENCE: dict[str, dict[str, list[str]]] = {
    "installation": {
        "empty-uefi-disk": ["install:blank", "scenario:first-boot"],
        "unencrypted-installation": ["install:blank", "scenario:first-boot"],
        "offline-installation": ["install:offline", "scenario:first-boot-offline-installed"],
        "encrypted-uefi-installation": ["install:encrypted", "scenario:encrypted-first-boot"],
        "interrupted-installation": ["install:interrupted", "collection:interrupted-disk-state.json"],
        "existing-linux-replacement": ["install:existing-data-protected", "install:existing-data-authorized"],
        "nvme-like-virtual-disk": ["scenario:first-boot-nvme"],
        "sata-like-virtual-disk": ["scenario:first-boot-sata"],
    },
    "encryption": {
        "luks-password-unlock": ["scenario:encrypted-first-boot"],
        "incorrect-password": ["scenario:encrypted-wrong-credential"],
        "tpm-fallback": ["scenario:tpm-absent"],
    },
    "update": {
        "current-to-next-candidate": ["collection:update-to-next.json"],
        "invalid-signature": ["collection:update-invalid-signature.json"],
        "manual-rollback": ["collection:rollback.json"],
    },
    "rollback": {
        "manual-rollback": ["collection:rollback.json"],
        "rollback-preserves-user-data": ["collection:rollback-preservation.json"],
    },
    "recovery-media": {
        "boots-independently": ["scenario:recovery-boots"],
    },
    "preservation": {
        "home": ["collection:rollback-preservation.json"],
    },
}


def load_verdict(evidence_root: Path, reference: str) -> tuple[str, str] | None:
    """Resolve one evidence reference to (result, relative path), or None if absent."""
    kind, _, name = reference.partition(":")
    if kind == "scenario":
        candidates = sorted(evidence_root.glob(f"ISQ-*-{name}-*/record.json"))
        if not candidates:
            return None
        record = json.loads(candidates[-1].read_text(encoding="utf-8"))
        return record.get("result", "FAIL"), str(candidates[-1].relative_to(ROOT))
    if kind == "install":
        path = evidence_root / "installs" / f"{name}.json"
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        good = {"INSTALLED", "REFUSED_AS_EXPECTED", "PROTECTED", "INTERRUPTED"}
        return ("PASS" if record.get("outcome") in good else "FAIL",
                str(path.relative_to(ROOT)))
    if kind == "collection":
        path = evidence_root / "collections" / name
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return record.get("result", "FAIL"), str(path.relative_to(ROOT))
    raise SystemExit(f"BLOCKED: unknown evidence reference kind {kind!r}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="import_matrix_results")
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/installed-system/evidence")
    parser.add_argument("--matrices", type=Path,
                        default=ROOT / "operations/data/qualification-matrices.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    context = resolve_context(ROOT)

    # Scenario verdicts must bind to the context before they can support rows.
    for record_path in sorted(args.evidence_root.glob("ISQ-*/record.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        reasons = verify_record_binding(record, context)
        if reasons:
            print(f"BLOCKED: {record_path.parent.name} does not bind to the context:",
                  file=sys.stderr)
            for reason in reasons:
                print(f"  - {reason}", file=sys.stderr)
            return 2

    document = json.loads(args.matrices.read_text(encoding="utf-8"))
    matrices = document["matrices"]
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

    written = 0
    for matrix, rows in ROW_EVIDENCE.items():
        for scenario, references in rows.items():
            verdicts = [load_verdict(args.evidence_root, ref) for ref in references]
            if any(v is None for v in verdicts):
                continue  # evidence absent: the standing NOT_RUN row remains
            outcome = "PASS" if all(v[0] == "PASS" for v in verdicts) else "FAIL"
            reference = verdicts[0][1]
            row = {
                "scenario": scenario,
                "outcome": outcome,
                "method": "virtual-machine",
                "evidenceReference": reference,
                "recordedAt": stamp,
                "notes": (
                    f"QEMU/KVM evidence bound to archive {context.sourceArchiveDigest[:12]} "
                    f"(commit {context.sourceCommit[:12]}); supporting records: "
                    + ", ".join(v[1] for v in verdicts)
                ),
            }
            parse_result(matrix, row, root=ROOT)  # refuse malformed rows before writing
            existing = matrices.get(matrix, [])
            matrices[matrix] = [r for r in existing if r.get("scenario") != scenario] + [row]
            written += 1
            print(f"  {outcome:4} {matrix}/{scenario} <- {reference}")

    if written == 0:
        print("BLOCKED: no evidence resolved to any matrix row; nothing was written. "
              "An import that writes nothing must say so rather than exit green.",
              file=sys.stderr)
        return 2

    document["recordedOn"] = stamp
    if not args.dry_run:
        args.matrices.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                                 encoding="utf-8")
        print(f"wrote {written} row(s) to {args.matrices.relative_to(ROOT)}")
    else:
        print(f"dry run: {written} row(s) would be written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

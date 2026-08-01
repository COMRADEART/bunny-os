#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import TPM boot records into the one qualification verdict, refusing fraud.

Every record is validated four ways before it counts:

1. authority binding — the record names exactly the context's artifact,
   firmware, emulator and scenario digests (stale records are refused);
2. internal consistency — the record's claims match the recorded QEMU
   invocation and each other (a no-TPM run labelled TPM, CRB labelled TIS,
   reused state labelled fresh, TCG labelled KVM, a timeout labelled a
   reset are all refused here);
3. evidence integrity — every listed evidence file exists and re-digests to
   its recorded hash;
4. schema shape — when jsonschema is available, full validation.

The verdict is calculated, never asserted. Software-TPM boot passes only
when the no-TPM control passes its full repetition count AND every
supported TPM cell passes its full count with every reset classified.
An UNKNOWN classification anywhere is blocking. Diagnostic records are
reported but can never satisfy a supported-path requirement. Physical TPM
is emitted as NOT_RUN unconditionally: nothing this importer reads can move
it, which is the structural fix for the relabelling fraud.

Exit codes: 0 — verdict computed and software-TPM boot PASS;
2 — blocked (validation failures, missing repetitions, UNKNOWN
classifications, or software-TPM boot not passing).
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))

from tpm_context import (  # noqa: E402
    ContextError,
    resolve_context,
    sha256_file,
    verify_internal_consistency,
    verify_record_binding,
)

try:
    import jsonschema  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]

#: The supported regression cells and the repetition count each one owes.
#: A cell missing runs is missing evidence, not a smaller sample.
SUPPORTED_CELLS = {
    "no-tpm-cold": 5,
    "crb-fresh-cold": 5,
    "tis-fresh-cold": 5,
    "crb-reused-cold": 5,
    "tis-reused-cold": 5,
    "crb-qemu-reset": 5,
    "tis-qemu-reset": 5,
}

#: What the supported cells do NOT cover, stated here so the verdict carries
#: it rather than leaving a reader to assume full coverage. A limitation in
#: the gate's own output is harder to lose than one in a report.
COVERAGE_LIMITATIONS = [
    "Guest-initiated reset with a TPM attached is covered by the fresh-variable "
    "cells (shim's in-guest ResetSystem followed by a complete boot) and "
    "platform reset by the qemu-reset cells. OS-level `reboot` from a "
    "logged-in session is NOT covered: the harness has no login injection, "
    "ctrl-alt-del does not reach PID 1 through the graphical session, and "
    "Fedora masks sysrq reboot. No cell claims it.",
]

#: What each supported cell must look like, beyond passing: the interface it
#: must have attached and the vars state it must declare. This is the
#: structural refusal of "CRB evidence labelled TIS" and "reused labelled
#: fresh" at the aggregation layer, on top of the per-record consistency.
#: Every supported cell demands `expectation: "target"` — the run had to be
#: judged against actually booting. Without that pin, five records carrying
#: `expectation: "stable"` and nothing past `grub-menu` fill a boot cell and
#: the gate reports PASS: measured, and the runner itself produces exactly
#: such a record if invoked with `--expect stable` under a boot cell's name.
#: The reset cells additionally demand that the second boot was reached.
CELL_SHAPE = {
    "no-tpm-cold": {"tpmInterface": "none", "expectation": "target",
                    "bootType": "cold"},
    "crb-fresh-cold": {"tpmInterface": "crb", "ovmfVarsState": "fresh",
                       "tpmState": "fresh", "expectation": "target",
                       "bootType": "cold"},
    "tis-fresh-cold": {"tpmInterface": "tis", "ovmfVarsState": "fresh",
                       "tpmState": "fresh", "expectation": "target",
                       "bootType": "cold"},
    "crb-reused-cold": {"tpmInterface": "crb", "ovmfVarsState": "reused",
                        "tpmState": "reused", "expectation": "target",
                        "bootType": "cold"},
    "tis-reused-cold": {"tpmInterface": "tis", "ovmfVarsState": "reused",
                        "tpmState": "reused", "expectation": "target",
                        "bootType": "cold"},
    "crb-qemu-reset": {"tpmInterface": "crb", "bootType": "qemu-reset",
                       "expectation": "target", "secondBootTargetReached": "True"},
    "tis-qemu-reset": {"tpmInterface": "tis", "bootType": "qemu-reset",
                       "expectation": "target", "secondBootTargetReached": "True"},
}


def cell_of(evidence_id: str) -> str | None:
    """TPMQ-YYYYMMDD-<cell>-NNN → <cell>, or None if the id is malformed.

    A malformed id is already reported as a binding problem; returning None
    here keeps the aggregation from raising on it, because a traceback loses
    the very diagnostic output the gate exists to produce.
    """
    parts = evidence_id.split("-")
    if len(parts) < 4 or parts[0] != "TPMQ":
        return None
    return "-".join(parts[2:-1]) or None


def sequence_of(evidence_id: str) -> int | None:
    parts = evidence_id.rsplit("-", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def main() -> int:
    parser = argparse.ArgumentParser(prog="import_tpm_results")
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="repository root holding qualification/tpm; overridable "
                             "so the adversarial tests can run the real importer "
                             "against synthetic trees")
    parser.add_argument("--evidence-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="validate records and print the verdict without writing")
    parser.add_argument("--skip-file-hashes", action="store_true",
                        help="skip re-digesting evidence files (fast structural check)")
    args = parser.parse_args()

    root = args.root
    if args.evidence_root is None:
        args.evidence_root = root / "qualification/tpm/evidence"
    if args.output is None:
        args.output = root / "qualification/tpm/evidence/tpm-qualification.json"
    try:
        context = resolve_context(root)
    except ContextError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    schema = None
    schema_path = root / "qualification/tpm/schemas/tpm-boot-record.schema.json"
    if not schema_path.is_file():
        schema_path = ROOT / "qualification/tpm/schemas/tpm-boot-record.schema.json"
    if jsonschema is not None and schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

    problems: list[str] = []
    records: list[dict] = []
    seen_ids: dict[str, str] = {}
    verified_retained = 0
    unverified_retained: list[str] = []
    entries = sorted(args.evidence_root.iterdir()) if args.evidence_root.is_dir() else []
    for entry in entries:
        record_path = entry / "record.json"
        if not entry.is_dir() or not record_path.is_file():
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{entry.name}: record.json is not valid JSON: {exc}")
            continue
        if not isinstance(record, dict):
            problems.append(f"{entry.name}: record.json is not an object")
            continue
        rid = str(record.get("evidenceId", "")) or entry.name

        # Identity. A record must be the record of the directory it sits in,
        # and no two runs may share an id. Without both rules a single
        # passing run copied into four more directories fills a five-boot
        # cell — measured, and it produced softwareTpmBoot PASS. Counting
        # directories is not counting boots unless each directory is a
        # distinct run.
        if str(record.get("evidenceId", "")) != entry.name:
            problems.append(
                f"{entry.name}: record claims evidenceId "
                f"{record.get('evidenceId')!r}; a record must be the record of "
                "the directory it sits in, or copies of one run would count as "
                "several")
        if rid in seen_ids:
            problems.append(
                f"{rid}: duplicate evidence id, also in {seen_ids[rid]}; two "
                "directories describing one run are one boot, not two")
        else:
            seen_ids[rid] = entry.name

        for reason in verify_record_binding(record, context):
            problems.append(f"{rid}: {reason}")
        argv = None
        command_path = entry / "qemu-command.json"
        if command_path.is_file():
            argv = json.loads(command_path.read_text(encoding="utf-8")).get("argv")
        else:
            problems.append(f"{rid}: no qemu-command.json; the invocation is part "
                            "of the evidence")
        for reason in verify_internal_consistency(record, argv):
            problems.append(f"{rid}: {reason}")
        if schema is not None:
            try:
                jsonschema.validate(record, schema)
            except jsonschema.ValidationError as exc:
                problems.append(f"{rid}: schema: {exc.message}")
        if not args.skip_file_hashes:
            # Bulky raw evidence (screendumps, verbose TPM command traces) may
            # be retained outside git on the builder. A missing file is only
            # acceptable when the run's retention manifest names it with the
            # SAME digest the record claims — the digest chain stays unbroken,
            # only the storage location moves. Anything else is a problem.
            retention: dict[str, dict] = {}
            retention_path = entry / "retention-manifest.json"
            if retention_path.is_file():
                manifest_doc = json.loads(retention_path.read_text(encoding="utf-8"))
                retention = {str(f["path"]): f for f in manifest_doc.get("files", [])}
            for entry_file in record.get("evidenceFiles", []):
                rel = str(entry_file["path"])
                path = entry / rel
                if not path.is_file():
                    retained = retention.get(rel)
                    if retained is None:
                        problems.append(f"{rid}: evidence file missing: {rel}")
                    elif retained.get("sha256") != entry_file.get("sha256"):
                        problems.append(
                            f"{rid}: retention manifest digest for {rel} does not "
                            "match the record; a swapped retained file is refused")
                    else:
                        # A manifest that merely echoes the record's digests
                        # would waive the existence check for bytes that exist
                        # nowhere. When the retained path is reachable, verify
                        # it; when it is not, say so rather than imply it was
                        # checked.
                        target = Path(str(retained.get("retainedAt", "")))
                        if target.is_file():
                            actual = sha256_file(target)
                            if actual != entry_file.get("sha256"):
                                problems.append(
                                    f"{rid}: retained file {target} digests to "
                                    f"{actual[:12]}, record says "
                                    f"{str(entry_file.get('sha256'))[:12]}")
                            else:
                                verified_retained += 1
                        else:
                            unverified_retained.append(
                                f"{rid}:{rel} retained on "
                                f"{retained.get('host', 'an unnamed host')} at "
                                f"{retained.get('retainedAt')}, not reachable here")
                    continue
                actual = sha256_file(path)
                if actual != entry_file.get("sha256"):
                    problems.append(f"{rid}: evidence file {rel} digests "
                                    f"to {actual[:12]}, record says "
                                    f"{str(entry_file.get('sha256'))[:12]}")
        records.append(record)

    unknowns = [str(r.get("evidenceId", "?")) for r in records
                if r.get("resetClassification") == "UNKNOWN"]
    for rid in unknowns:
        problems.append(f"{rid}: resetClassification UNKNOWN is blocking; an "
                        "unexplained reset cannot be qualified around")

    # One artifact per matrix: every non-diagnostic record must be about the
    # pinned disk. (Diagnostic alt-disk records carry their own digest and
    # are excluded from supported cells by the shape rules below.)
    for r in records:
        if not r.get("diagnostic") and r.get("diskAttached") \
                and r.get("altDiskSha256"):
            problems.append(f"{str(r.get('evidenceId', '?'))}: an alternative "
                            "disk in a non-diagnostic record")

    cells: dict[str, dict] = {}
    for r in records:
        name = cell_of(str(r.get("evidenceId", "")))
        if name is None:
            problems.append(f"{str(r.get('evidenceId', '?'))}: cannot be "
                            "attributed to a cell; it fills nothing")
            continue
        cells.setdefault(name, {"records": []})["records"].append(r)

    # Sequence contiguity. Evidence ids carry a sequence number precisely so
    # a deleted run leaves a hole. Without this check the cheapest fraud in
    # the system is: run a cell ten times, delete the five that failed, and
    # present a clean 5/5.
    for name, data in cells.items():
        numbers = sorted(n for n in (sequence_of(str(r.get("evidenceId", "")))
                                     for r in data["records"]) if n is not None)
        if not numbers:
            continue
        expected = list(range(1, max(numbers) + 1))
        gaps = sorted(set(expected) - set(numbers))
        if gaps:
            problems.append(
                f"{name}: sequence gaps at {gaps} (highest present is "
                f"{max(numbers)}); a missing run in the middle of a cell is a "
                "deleted result until it is explained")

    cell_reports: dict[str, dict] = {}
    supported_ok = True
    for name, needed in SUPPORTED_CELLS.items():
        cell_records = [r for r in cells.get(name, {}).get("records", [])
                        if not r.get("diagnostic")]
        shape = CELL_SHAPE[name]
        shaped = [r for r in cell_records
                  if all(str(r.get(k)) == v for k, v in shape.items())]
        for r in cell_records:
            if r not in shaped:
                mismatched = {k: r.get(k) for k, v in shape.items()
                              if str(r.get(k)) != v}
                problems.append(f"{str(r.get('evidenceId', '?'))}: does not match "
                                f"the declared shape of cell {name} — {mismatched} "
                                f"against {shape}; a mislabelled record cannot "
                                "fill a cell")
        passes = [r for r in shaped if r.get("result") == "PASS"]
        report = {
            "required": needed,
            "present": len(shaped),
            "pass": len(passes),
            "fail": sum(r.get("result") == "FAIL" for r in shaped),
            "inconclusive": sum(r.get("result") == "INCONCLUSIVE" for r in shaped),
            "resets": sum(int(r.get("guestResetCount", 0)) for r in shaped),
            "classifications": sorted({r["resetClassification"] for r in shaped
                                       if r.get("resetClassification")}),
            "failedUnitsPerBoot": {str(r.get("evidenceId", "?")):
                                   r.get("failedUnits", []) for r in shaped},
        }
        report["satisfied"] = report["present"] >= needed and \
            report["pass"] == report["present"]
        if not report["satisfied"]:
            supported_ok = False
        cell_reports[name] = report

    # The paired-control rule: TPM evidence only counts while the no-TPM
    # control passes. A TPM pass over a failing control is one of the exact
    # frauds the battery names.
    control = cell_reports.get("no-tpm-cold", {})
    if not control.get("satisfied"):
        supported_ok = False
        problems.append("no-TPM control cell is not satisfied; TPM cells cannot "
                        "count against a failing or missing control")

    diagnostics = {name: {
        "runs": len(data["records"]),
        "pass": sum(r.get("result") == "PASS" for r in data["records"]),
        "diagnostic": True,
    } for name, data in cells.items()
        if name not in SUPPORTED_CELLS
        and any(r.get("diagnostic") for r in data["records"])}
    controls = {name: {
        "runs": len(data["records"]),
        "pass": sum(r.get("result") == "PASS" for r in data["records"]),
    } for name, data in cells.items()
        if name not in SUPPORTED_CELLS
        and not any(r.get("diagnostic") for r in data["records"])}

    verdict = {
        "schemaVersion": 1,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds"),
        "context": context.as_dict(),
        "recordCount": len(records),
        "problems": problems,
        "supportedCells": cell_reports,
        "investigationControls": controls,
        "diagnosticCells": diagnostics,
        "softwareTpmBoot": "PASS" if (supported_ok and not problems) else "BLOCKED",
        "qemuKvmTpmIntegration": "PASS" if (supported_ok and not problems) else "BLOCKED",
        "retainedEvidenceVerified": verified_retained,
        "retainedEvidenceUnverifiable": unverified_retained,
        "physicalTpm": "NOT_RUN",
        "productionSecureBoot": "NOT_QUALIFIED",
        "tpmBoundDiskUnlock": "NOT_QUALIFIED",
        "limitations": [
            "Every record is qemu-kvm or qemu-tcg evidence; nothing here counts "
            "toward physical TPM hardware, OEM firmware compatibility, production "
            "Secure Boot, TPM-bound disk unlock, TPM recovery behaviour or global "
            "hardware qualification.",
        ] + COVERAGE_LIMITATIONS,
    }

    print(json.dumps({k: verdict[k] for k in
                      ("recordCount", "softwareTpmBoot", "physicalTpm")}, indent=2))
    for problem in problems[:40]:
        print(f"  problem: {problem}", file=sys.stderr)
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
    if not args.dry_run:
        args.output.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
        print(f"verdict written to {args.output}")
    return 0 if verdict["softwareTpmBoot"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

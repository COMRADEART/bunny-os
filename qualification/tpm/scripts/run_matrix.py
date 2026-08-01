#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the TPM boot matrix: every cell, every repetition, one summary.

The matrix definition owns what runs; this driver owns only sequencing,
seed-state plumbing and occurrence counting. Results are counts, never a
bare PASS/FAIL: how many boots were attempted, how many reached GRUB, how
many left it, how many reached the target, how many reset, which units
failed on which boots. A cell that needed five boots and got one is a
failure of the driver, and the summary says so.

Seed cells: a cell naming ``seedFrom`` copies the retained OVMF variable
store and/or swtpm state directory of the FIRST completed run of the named
cell. Copies, never shares — two experiments writing one variable store
would contaminate each other, which is exactly the failure mode the
fresh/reused axis exists to measure.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]

STAGE_ORDER = ["firmware-bds", "boot-option-started", "restoration-dialog",
               "reset-announced", "grub-menu", "kernel-loaded", "initramfs",
               "multi-user", "graphical", "health-check"]


def next_sequence(evidence_root: Path, name: str, date: str) -> int:
    pattern = re.compile(rf"^TPMQ-{date}-{re.escape(name)}-(\d{{3}})$")
    highest = 0
    if evidence_root.is_dir():
        for entry in evidence_root.iterdir():
            match = pattern.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def find_seed_state(evidence_root: Path, cell_name: str, date: str) -> Path | None:
    pattern = re.compile(rf"^TPMQ-{date}-{re.escape(cell_name)}-(\d{{3}})$")
    candidates = sorted(e for e in evidence_root.iterdir() if pattern.match(e.name))
    for candidate in candidates:
        record = candidate / "record.json"
        state = candidate / "state"
        if record.is_file() and state.is_dir():
            data = json.loads(record.read_text(encoding="utf-8"))
            if data.get("result") == "PASS":
                return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_matrix")
    parser.add_argument("--matrix", type=Path,
                        default=ROOT / "qualification/tpm/scenarios/tpm-matrix.json")
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/tpm/evidence")
    parser.add_argument("--only", action="append", default=[],
                        help="run only the named cells (repeatable)")
    parser.add_argument("--summary-out", type=Path, default=None)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    date = datetime.date.today().strftime("%Y%m%d")
    runner = SCRIPT_DIR / "run_tpm_experiment.py"
    summary: dict = {"matrixVersion": matrix.get("matrixVersion"),
                     "startedAt": datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds"),
                     "cells": {}}

    for cell in matrix["cells"]:
        name = cell["name"]
        if args.only and name not in args.only:
            continue
        cell_runs: list[dict] = []
        extra: list[str] = []
        if cell.get("seedFrom"):
            seed = find_seed_state(args.evidence_root, cell["seedFrom"], date)
            if seed is None:
                summary["cells"][name] = {
                    "skipped": f"no completed PASS run of {cell['seedFrom']} with retained "
                               "state to seed from"}
                print(f"[matrix] SKIP {name}: seed {cell['seedFrom']} unavailable")
                continue
            wants = cell.get("seed", [])
            if "vars" in wants:
                extra += ["--vars", f"reuse:{seed / 'state' / 'OVMF_VARS.qcow2'}"]
            if "tpm-state" in wants:
                extra += ["--tpm-state", f"reuse:{seed / 'state' / 'tpm-state'}"]
        for _ in range(int(cell.get("runs", 3))):
            sequence = next_sequence(args.evidence_root, name, date)
            cmd = [sys.executable, str(runner), "--name", name,
                   "--sequence", str(sequence),
                   "--evidence-root", str(args.evidence_root)] \
                + cell.get("args", []) + extra
            print(f"[matrix] run {name} seq {sequence}", flush=True)
            proc = subprocess.run(cmd)
            record_path = args.evidence_root / f"TPMQ-{date}-{name}-{sequence:03d}" \
                / "record.json"
            if record_path.is_file():
                record = json.loads(record_path.read_text(encoding="utf-8"))
                cell_runs.append(record)
            else:
                cell_runs.append({"evidenceId": f"TPMQ-{date}-{name}-{sequence:03d}",
                                  "result": "MISSING", "exit": proc.returncode})
        counts = {
            "bootsAttempted": len(cell_runs),
            "reachedGrub": sum("grub-menu" in r.get("stagesReached", []) for r in cell_runs),
            "loadedKernel": sum("kernel-loaded" in r.get("stagesReached", [])
                                for r in cell_runs),
            "reachedInitramfs": sum("initramfs" in r.get("stagesReached", [])
                                    for r in cell_runs),
            "reachedMultiUser": sum("multi-user" in r.get("stagesReached", [])
                                    for r in cell_runs),
            "reachedGraphical": sum("graphical" in r.get("stagesReached", [])
                                    for r in cell_runs),
            "healthCheck": sum("health-check" in r.get("stagesReached", [])
                               for r in cell_runs),
            "resets": sum(int(r.get("guestResetCount", 0)) for r in cell_runs),
            "timeouts": sum(r.get("resetClassification") == "HARNESS_TIMEOUT"
                            for r in cell_runs),
            "pass": sum(r.get("result") == "PASS" for r in cell_runs),
            "fail": sum(r.get("result") == "FAIL" for r in cell_runs),
            "inconclusive": sum(r.get("result") == "INCONCLUSIVE" for r in cell_runs),
            "failedUnitsPerBoot": {r.get("evidenceId", "?"): r.get("failedUnits", [])
                                   for r in cell_runs},
            "classifications": sorted({r["resetClassification"] for r in cell_runs
                                       if r.get("resetClassification")}),
            "runs": [r.get("evidenceId") for r in cell_runs],
        }
        summary["cells"][name] = counts
        print(f"[matrix] {name}: {json.dumps({k: counts[k] for k in ('bootsAttempted', 'pass', 'fail', 'resets')})}",
              flush=True)

    summary["completedAt"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds")
    out = args.summary_out or (args.evidence_root / "matrix-summary.json")
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[matrix] summary written to {out}")
    any_missing = any(c.get("skipped") or c.get("inconclusive")
                      for c in summary["cells"].values() if isinstance(c, dict))
    return 1 if any_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

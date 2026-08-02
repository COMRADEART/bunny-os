#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the Stage 5 repeated-boot matrix: cells A(20) B(10) C(10) D(10) E(10).

Sequences are contiguous from 001. A run directory that already exists is
never overwritten and never deleted: rerunning the matrix continues at the
first missing sequence of each cell. A run whose collection failed keeps its
directory and its status — superseding it means adding runs, not editing
history."""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]

PLAN = [("A", 20), ("B", 10), ("C", 10), ("D", 10), ("E", 10)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/display-stack/evidence")
    parser.add_argument("--date-tag",
                        default=datetime.date.today().strftime("%Y%m%d"))
    parser.add_argument("--cells", default="ABCDE")
    args = parser.parse_args()

    for cell, count in PLAN:
        if cell not in args.cells:
            continue
        # fill the cell's quota with COLLECTED runs: existing directories
        # are never touched (an abandoned or failed run keeps its sequence
        # number and its record), new runs continue the sequence
        collected = 0
        sequence = 0
        while collected < count and sequence < count * 3:
            sequence += 1
            run_id = f"DSQ-{args.date_tag}-cell{cell}-{sequence:03d}"
            run_dir = args.evidence_root / run_id
            if run_dir.exists():
                status = "?"
                record = run_dir / "record.json"
                if record.exists():
                    try:
                        status = json.loads(
                            record.read_text(encoding="utf-8"))["status"]
                    except (json.JSONDecodeError, KeyError):
                        status = "unreadable"
                if status == "COLLECTED":
                    collected += 1
                print(f"skip {run_id} (exists, {status})", flush=True)
                continue
            print(f"run  {run_id}", flush=True)
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "run_boot.py"),
                 "--cell", cell, "--sequence", str(sequence),
                 "--evidence-root", str(args.evidence_root),
                 "--date-tag", args.date_tag])
            if result.returncode == 0:
                collected += 1
            elif result.returncode not in (0, 1):
                # 2 is a refusal (bad artifact digest, missing seed):
                # continuing would produce a matrix about a different input.
                print(f"REFUSED at {run_id}; stopping", flush=True)
                return 2
        if collected < count:
            print(f"cell {cell}: only {collected}/{count} collected "
                  "within the sequence cap", flush=True)
            return 2
    print("matrix complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

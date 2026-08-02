#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the dsq-2 first-login matrix: cells A(20) B(10) C(10) D(10) E(10).

Same continuation rules as dsq-1's matrix, for the same reasons. Sequences are
contiguous from 001; an existing run directory is never overwritten and never
deleted; a rerun continues at the first missing sequence of each cell. The date
tag defaults to the newest already present rather than to today, so a run that
crosses midnight continues its own matrix instead of starting a parallel one —
the bug a1af19d fixed in dsq-1.

Second logins are allocated to the lowest sequence numbers of the cells that
require them (A:10, D:5, E:5). Allocating by sequence rather than at random
means a partially filled matrix has a known second-login count, so a rerun
cannot quietly satisfy the quota with a different set of runs than the one the
first attempt started.
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

PLAN = [("A", 20), ("B", 10), ("C", 10), ("D", 10), ("E", 10)]
SECOND_LOGIN_PLAN = {"A": 10, "B": 0, "C": 0, "D": 5, "E": 5}
RUN_RE = re.compile(r"FLQ-(?P<date>\d{8})-cell[A-E]-\d{3}$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/first-login/evidence")
    parser.add_argument("--disk-source", type=Path, required=True)
    parser.add_argument("--date-tag", default=None)
    parser.add_argument("--cells", default="ABCDE")
    parser.add_argument("--observe", type=int, default=75)
    args = parser.parse_args()

    args.evidence_root.mkdir(parents=True, exist_ok=True)
    if args.date_tag is None:
        existing = sorted({match.group("date")
                           for entry in args.evidence_root.iterdir()
                           if (match := RUN_RE.match(entry.name))})
        args.date_tag = (existing[-1] if existing
                         else datetime.date.today().strftime("%Y%m%d"))
    print(f"matrix date tag: {args.date_tag}", flush=True)

    for cell, count in PLAN:
        if cell not in args.cells:
            continue
        collected = 0
        sequence = 0
        while collected < count and sequence < count * 3:
            sequence += 1
            run_id = f"FLQ-{args.date_tag}-cell{cell}-{sequence:03d}"
            run_dir = args.evidence_root / run_id
            second_login = sequence <= SECOND_LOGIN_PLAN[cell]

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

            label = " +second-login" if second_login else ""
            print(f"run  {run_id}{label}", flush=True)
            argv = [sys.executable, str(SCRIPT_DIR / "run_first_login_boot.py"),
                    "--cell", cell, "--sequence", str(sequence),
                    "--disk-source", str(args.disk_source),
                    "--evidence-root", str(args.evidence_root),
                    "--observe", str(args.observe),
                    "--date-tag", args.date_tag]
            if second_login:
                argv.append("--second-login")
            result = subprocess.run(argv)
            if result.returncode == 0:
                collected += 1
            elif result.returncode not in (0, 1):
                # 2 is a refusal — a wrong artifact digest, a missing seed, a
                # scenario mismatch. Continuing would build a matrix about a
                # different input than the one it claims.
                print(f"REFUSED at {run_id}; stopping", flush=True)
                return 2
        if collected < count:
            print(f"cell {cell}: only {collected}/{count} collected within "
                  "the sequence cap", flush=True)
            return 2
    print("matrix complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

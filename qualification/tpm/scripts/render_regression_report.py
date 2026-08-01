#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fill the generated sections of TPM_BOOT_REGRESSION_REPORT.md from the
evidence, so the counts in the report are never typed by hand.

Each generated block is delimited by HTML comments; everything outside them
is prose a human wrote and this tool must not touch. Running it twice on the
same evidence produces the same file.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import re
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent

BLOCKS = {
    "MATRIX TABLE": "table",
    "FAILED UNITS": "units",
    "CLASSIFICATIONS": "classifications",
}


def split_summary(text: str) -> dict[str, str]:
    """Split summarise_matrix output into its three sections."""
    parts = re.split(r"^### (.+)$", text, flags=re.MULTILINE)
    sections = {"table": parts[0].strip()}
    for index in range(1, len(parts) - 1, 2):
        heading = parts[index].lower()
        body = parts[index + 1].strip()
        if "unit" in heading:
            sections["units"] = body
        elif "classification" in heading:
            sections["classifications"] = body
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(prog="render_regression_report")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "summarise_matrix.py"),
         "--evidence-root", str(args.evidence_root)],
        capture_output=True, text=True, check=True)
    sections = split_summary(proc.stdout)

    report = args.report.read_text(encoding="utf-8")
    for marker, key in BLOCKS.items():
        body = sections.get(key, "_no data_")
        pattern = re.compile(
            rf"(<!-- BEGIN {marker} -->\n).*?(<!-- END {marker} -->)",
            re.DOTALL)
        if not pattern.search(report):
            print(f"BLOCKED: no {marker} block in {args.report}", file=sys.stderr)
            return 2
        report = pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2),
                             report)
    args.report.write_text(report, encoding="utf-8")
    print(f"rendered {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render DISPLAY_STACK_BOOT_MATRIX_REPORT.md from the imported verdict.

Occurrence counts are printed per unit per cell in full — an intermittent
result is never reduced to one PASS line. The report is generated from
display-stack-qualification.json so it can never disagree with the gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]

CELL_TITLES = {
    "A": "ordinary no-TPM cold boot",
    "B": "CRB TPM, restored NVRAM",
    "C": "first TPM fallback boot",
    "D": "reduced resources (2 vCPU / 4 GiB)",
    "E": "network unavailable",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/display-stack/evidence")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "DISPLAY_STACK_BOOT_MATRIX_REPORT.md")
    args = parser.parse_args()
    verdict = json.loads(
        (args.evidence_root / "display-stack-qualification.json")
        .read_text(encoding="utf-8"))

    lines = [
        "# Display-Stack Repeated-Boot Matrix Report (dsq-1)",
        "",
        "Generated from `qualification/display-stack/evidence/"
        "display-stack-qualification.json`; the numbers below are the "
        "gate's own input, not a summary of it.",
        "",
        "## Cells",
        "",
        "| Cell | Scenario | Planned | Attempted | Collected | GDM-ready "
        "boots | Complete |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell, data in sorted(verdict["cells"].items()):
        lines.append(
            f"| {cell} | {CELL_TITLES[cell]} | {data['planned']} | "
            f"{data['attempted']} | {data['collected']} | "
            f"{data['gdmReady']}/{data['collected']} | "
            f"{'yes' if data['complete'] else 'NO'} |")
    not_ready = [(cell, entry) for cell, data in verdict["cells"].items()
                 for entry in data["gdmNotReady"]]
    lines += ["", "## Boots failing a GDM readiness assertion", ""]
    if not_ready:
        for cell, entry in not_ready:
            lines.append(f"- `{entry['run']}` (cell {cell}): "
                         + "; ".join(entry["reasons"]))
    else:
        lines.append("None. Every collected boot passed every readiness "
                     "assertion, observation window included.")
    lines += ["", "## Per-unit occurrence counts", ""]
    for unit, cells in sorted(verdict["unitOccurrences"].items()):
        total_failed = sum(c["failed"] for c in cells.values())
        total_shutdown = sum(c["failedDuringShutdown"] for c in cells.values())
        total_recovered = sum(c["failedAndRecovered"] for c in cells.values())
        if not (total_failed or total_shutdown or total_recovered):
            continue
        lines.append(f"### `{unit}`")
        lines.append("")
        lines.append("| Cell | attempted | reached graphical | activated | "
                     "succeeded | failed (boot phase) | failed during "
                     "shutdown | failed+recovered | skipped | n/a | "
                     "collection failed |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | "
                     "--- | --- | --- |")
        for cell, c in sorted(cells.items()):
            lines.append(
                f"| {cell} | {c['bootsAttempted']} | "
                f"{c['bootsReachingGraphical']} | {c['activated']} | "
                f"{c['succeeded']} | {c['failed']} | "
                f"{c['failedDuringShutdown']} | {c['failedAndRecovered']} | "
                f"{c['skipped']} | {c['notApplicable']} | "
                f"{c['collectionFailed']} |")
        lines.append("")
    lines += [
        "## Units with no failure in any cell",
        "",
        "Watched throughout, zero failures in any phase: " + ", ".join(
            f"`{unit}`" for unit, cells in sorted(
                verdict["unitOccurrences"].items())
            if not any(c["failed"] or c["failedDuringShutdown"] or
                       c["failedAndRecovered"] for c in cells.values())),
        "",
        "## Disposition verdicts",
        "",
    ]
    for unit, status in sorted(verdict["dispositionVerdicts"].items()):
        lines.append(f"- `{unit}`: {status}")
    lines += [
        "",
        "## Gate result",
        "",
        f"- GDM reliability: **{verdict['gdmReliability']}**",
        f"- Display-stack reliability: "
        f"**{verdict['displayStackReliability']}**",
        "",
    ]
    if verdict["problems"]:
        lines += ["## Evidence problems", ""]
        lines += [f"- {p}" for p in verdict["problems"]]
        lines.append("")
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

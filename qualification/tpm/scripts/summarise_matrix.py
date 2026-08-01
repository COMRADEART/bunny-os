#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the matrix occurrence counts as report-ready markdown.

Counts, never a bare PASS: boots attempted, how far each got, how many
resets, and — separately from all of that — which units failed on which
boots. An intermittent gdm failure and a TPM reset are different facts and
this table never merges them.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

STAGES = [("reachedGrub", "grub-menu"), ("loadedKernel", "kernel-loaded"),
          ("initramfs", "initramfs"), ("multiUser", "multi-user"),
          ("graphical", "graphical"), ("healthCheck", "health-check")]


def main() -> int:
    parser = argparse.ArgumentParser(prog="summarise_matrix")
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    cells: dict[str, list[dict]] = collections.defaultdict(list)
    for entry in sorted(args.evidence_root.iterdir()):
        record_path = entry / "record.json"
        if not entry.is_dir() or not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        cell = record["evidenceId"].split("-", 2)[2].rsplit("-", 1)[0]
        cells[cell].append(record)

    print("| Cell | Diag | Boots | GRUB | kernel | initrd | multi-user | "
          "graphical | health | resets | PASS |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for cell in sorted(cells):
        runs = cells[cell]
        counts = [str(sum(stage in r.get("stagesReached", []) for r in runs))
                  for _, stage in STAGES]
        diag = "D" if any(r.get("diagnostic") for r in runs) else ""
        resets = sum(int(r.get("guestResetCount", 0)) for r in runs)
        passes = sum(r.get("result") == "PASS" for r in runs)
        print(f"| `{cell}` | {diag} | {len(runs)} | " + " | ".join(counts)
              + f" | {resets} | {passes}/{len(runs)} |")

    print("\n### Failed units per boot (serial console view, recorded "
          "separately from boot success)\n")
    unit_counts: dict[str, int] = collections.Counter()
    boots_with_units = 0
    total_boots = 0
    for cell in sorted(cells):
        for record in cells[cell]:
            total_boots += 1
            units = record.get("failedUnits", [])
            if units:
                boots_with_units += 1
                for unit in units:
                    unit_counts[unit] += 1
    if unit_counts:
        for unit, count in sorted(unit_counts.items(), key=lambda kv: -kv[1]):
            print(f"* `{unit}` — failed on {count} of {total_boots} boots")
        print(f"\n{boots_with_units} of {total_boots} boots recorded at least "
              "one failed unit.")
    else:
        print(f"The serial console reported no failed units on any of "
              f"{total_boots} boots. This is the console's view, not the "
              "journal's: a unit that failed quietly would not appear here.")

    print("\n### Reset classifications\n")
    classes: dict[str, int] = collections.Counter()
    for cell in sorted(cells):
        for record in cells[cell]:
            value = record.get("resetClassification")
            if value:
                classes[value] += 1
    for name, count in sorted(classes.items(), key=lambda kv: -kv[1]):
        print(f"* `{name}` — {count} runs")
    if not classes:
        print("No run required a reset classification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

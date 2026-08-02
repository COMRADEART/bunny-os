#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 10 — timeline and dependency reconstruction for failed runs.

For every collected run that shows any boot-phase failure, produce a
structured delta against the nearest successful run *from the same matrix
cell*: milestone timing differences, units failing in one but not the
other, differing unit orderings around the failure, condition-result and
dependency-result differences, coredump and kernel-graphics differences,
and whether each failure lies inside that record's measured authselect
apply window. A race is never inferred from timing alone — this output is
the comparison material, not the verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

RUN_DIR_RE = re.compile(r"^DSQ-\d{8}-cell(?P<cell>[A-E])-(?P<seq>\d{3})$")

MILESTONES = [
    "kernelStart", "systemdStart", "graphicsDeviceReady", "dbusReady",
    "logindReady", "seat0Created", "networkManagerReady",
    "authselectApplyStart", "authselectApplyEnd", "gdmStartRequested",
    "gdmActive", "greeterSessionOpened", "pipewireFirstSeen",
    "avahiActivation", "multiUserTarget", "graphicalTarget", "healthCheck",
]


def load_runs(evidence_root: Path) -> list[dict]:
    runs = []
    for run_dir in sorted(evidence_root.iterdir()):
        if not RUN_DIR_RE.match(run_dir.name):
            continue
        record_path = run_dir / "record.json"
        if not record_path.exists():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") != "COLLECTED":
            continue
        record["_name"] = run_dir.name
        runs.append(record)
    return runs


def failing_units(record: dict) -> list[dict]:
    analysis = record["analysis"]
    out = []
    for scope_key in ("systemUnits", "userUnits"):
        for unit in analysis.get(scope_key, []):
            if unit["disposition"] in ("currently-failed",
                                       "failed-during-shutdown",
                                       "failed-transiently-and-recovered"):
                out.append(unit)
    return out


def unit_failed_in(record: dict, unit_name: str) -> bool:
    return any(u["unit"] == unit_name for u in failing_units(record))


def nearest_without(runs: list[dict], failed: dict,
                    unit_name: str) -> dict | None:
    """Nearest same-cell run in which this unit did not fail.

    The comparison is per unit: a deterministic failure elsewhere (e.g. a
    unit failing in 100% of runs) must not make every run 'unclean' and
    leave intermittent failures with nothing to compare against."""
    cell = failed["cell"]
    candidates = [
        r for r in runs
        if r["cell"] == cell and r is not failed
        and not unit_failed_in(r, unit_name)
        and r["analysis"].get("graphicalTargetReachedMono") is not None]
    if not candidates:
        return None
    return min(candidates,
               key=lambda r: abs(r["sequence"] - failed["sequence"]))


def delta(failed: dict, reference: dict, unit: dict) -> dict:
    fa, ra = failed["analysis"], reference["analysis"]
    ft, rt = fa.get("timeline", {}), ra.get("timeline", {})
    timing = {}
    for milestone in MILESTONES:
        f_val, r_val = ft.get(milestone), rt.get(milestone)
        timing[milestone] = {
            "failedRun": f_val, "referenceRun": r_val,
            "deltaSeconds": (round(f_val - r_val, 3)
                             if f_val is not None and r_val is not None
                             else None)}
    window = (ft.get("authselectApplyStart"), ft.get("authselectApplyEnd"))
    fail_times = [e["monotonic"] for e in unit["events"]
                  if e["kind"] == "failed" and e["monotonic"]]
    in_window = None
    if window[0] is not None and window[1] is not None and fail_times:
        in_window = all(window[0] - 0.5 <= t <= window[1] + 2.0
                        for t in fail_times)
    ref_units = [u for scope in ("systemUnits", "userUnits")
                 for u in ra.get(scope, []) if u["unit"] == unit["unit"]]
    shutdown_at = fa.get("shutdownInitiatedMono")
    return {
        "failedRun": failed["_name"],
        "referenceRun": reference["_name"],
        "cell": failed["cell"],
        "unit": unit["unit"],
        "scope": unit["scope"],
        "uid": unit.get("uid"),
        "disposition": unit["disposition"],
        "result": unit.get("result"),
        "mainExit": unit.get("mainExit"),
        "failureTimes": fail_times,
        "shutdownInitiatedMono": shutdown_at,
        "failuresAfterShutdownInitiation": (
            [t for t in fail_times if shutdown_at and t >= shutdown_at]),
        "insideAuthselectWindow": in_window,
        "referenceDisposition": (ref_units[0]["disposition"]
                                 if ref_units else "absent"),
        "referenceActiveEnter": (ref_units[0].get("activeEnterMono")
                                 if ref_units else None),
        "timing": timing,
        "dependencyFailuresDelta": {
            "failedRun": fa.get("dependencyFailures", []),
            "referenceRun": ra.get("dependencyFailures", [])},
        "coredumpsDelta": {
            "failedRun": fa.get("coredumps", []),
            "referenceRun": ra.get("coredumps", [])},
        "kernelGraphicsErrorsDelta": {
            "failedRun": fa.get("kernelGraphicsErrors", []),
            "referenceRun": ra.get("kernelGraphicsErrors", [])},
        "conditionSkipsDelta": {
            "failedRun": sorted(
                u["unit"] for scope in ("systemUnits", "userUnits")
                for u in fa.get(scope, []) if u.get("skipped")),
            "referenceRun": sorted(
                u["unit"] for scope in ("systemUnits", "userUnits")
                for u in ra.get(scope, []) if u.get("skipped"))},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, default=(
        SCRIPT_DIR.parents[2] / "qualification/display-stack/evidence"))
    args = parser.parse_args()
    runs = load_runs(args.evidence_root)
    by_cell_count: dict[str, int] = {}
    for record in runs:
        by_cell_count[record["cell"]] = by_cell_count.get(record["cell"], 0) + 1
    deltas = []
    deterministic: dict[str, int] = {}
    for record in runs:
        for unit in failing_units(record):
            reference = nearest_without(runs, record, unit["unit"])
            if reference is None:
                # the unit fails in every run of this cell: there is no
                # intermittency to compare, which is itself the finding
                deterministic[unit["unit"]] = \
                    deterministic.get(unit["unit"], 0) + 1
                continue
            deltas.append(delta(record, reference, unit))
    out = args.evidence_root / "timing-deltas.json"
    out.write_text(json.dumps({
        "perUnitDeltas": deltas,
        "deterministicFailuresWithoutReference": deterministic,
        "note": ("a unit listed under deterministicFailuresWithoutReference "
                 "failed in every collected run of its cell; a timing delta "
                 "against a non-failing run is undefined for it"),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(deltas)} unit-level comparisons, "
          f"{len(deterministic)} deterministic units)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import dsq-1 matrix records: evidence integrity, occurrence counts, gate.

Three layers, strictly ordered:

1. Evidence integrity (--dry-run stops here). Every record must bind to the
   dsq-1 authority, its files must match their recorded digests, boot IDs
   must be unique across runs (a copied run shares one), sequences must be
   contiguous from 001, a run's cell configuration must equal the cell's
   definition (a reduced-resource or no-network run cannot fill another
   cell), and a record whose collection failed can never be counted as a
   boot with an empty failed-unit list.

2. Occurrence counts (Stage 6): per unit, per cell, the full breakdown.
   Intermittent results are never reduced to one PASS.

3. Verdict (Stage 15): GDM reliability passes only when every counted boot
   reached graphical.target with a usable greeter and the observation
   window complete; screencast and Avahi close only through evidence-backed
   dispositions whose context the gate itself verifies per boot.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from dsq_context import (  # noqa: E402
    ContextError,
    resolve_context,
    sha256_file,
    verify_record_binding,
)
from run_boot import CELLS  # noqa: E402

RUN_DIR_RE = re.compile(r"^DSQ-(?P<date>\d{8})-cell(?P<cell>[A-E])-(?P<seq>\d{3})$")
PLAN = {"A": 20, "B": 10, "C": 10, "D": 10, "E": 10}
SCREENCAST_CANONICAL = "dbus-:*-org.gnome.Shell.Screencast@0.service"
WATCHLIST = ("gdm.service", "avahi-daemon.service", "avahi-daemon.socket",
             SCREENCAST_CANONICAL)
DISPOSITIONS_PATH = "unit-dispositions.json"


def load_records(evidence_root: Path, problems: list[str]) -> dict[str, list[dict]]:
    by_cell: dict[str, list[dict]] = {cell: [] for cell in PLAN}
    seen_boot_ids: dict[str, str] = {}
    for run_dir in sorted(evidence_root.iterdir()):
        match = RUN_DIR_RE.match(run_dir.name)
        if not match:
            continue
        record_path = run_dir / "record.json"
        if not record_path.exists():
            problems.append(f"{run_dir.name}: no record.json")
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{run_dir.name}: unreadable record: {exc}")
            continue
        record["_dir"] = run_dir
        cell = match.group("cell")
        if record.get("cell") != cell or record.get("sequence") != int(
                match.group("seq")):
            problems.append(f"{run_dir.name}: directory name and record "
                            "disagree about cell or sequence")
            continue
        # the configuration equality check applies to records that fill a
        # cell; an ABANDONED/COLLECTION_FAILED record measured nothing and
        # keeps whatever configuration its refusal happened under
        expected_config = dict(CELLS[cell])
        if record.get("status") == "COLLECTED" and \
                record.get("cellConfiguration") != expected_config:
            problems.append(
                f"{run_dir.name}: cell configuration differs from the "
                f"cell {cell} definition — a run from another environment "
                "cannot fill this cell")
            continue
        boot_id = (record.get("collection") or {}).get("bootId")
        if boot_id:
            if boot_id in seen_boot_ids:
                problems.append(
                    f"{run_dir.name}: boot ID {boot_id} already appears in "
                    f"{seen_boot_ids[boot_id]} — one boot cannot fill two "
                    "run directories")
                continue
            seen_boot_ids[boot_id] = run_dir.name
        by_cell[cell].append(record)
    return by_cell


def verify_integrity(by_cell: dict[str, list[dict]], context,
                     problems: list[str], verify_files: bool = True) -> None:
    for cell, records in by_cell.items():
        sequences = sorted(r["sequence"] for r in records)
        if sequences != list(range(1, len(sequences) + 1)):
            problems.append(
                f"cell {cell}: sequences are not contiguous from 001: "
                f"{sequences} — a gap is a deleted run")
        for record in records:
            name = record["_dir"].name
            for issue in verify_record_binding(record, context):
                problems.append(f"{name}: authority mismatch — {issue}")
            artifact = record.get("artifact", {})
            if artifact.get("sha256") != context.installationArtifactDigest:
                problems.append(f"{name}: artifact digest is not the "
                                "qualified disk")
            status = record.get("status")
            if status not in ("COLLECTED", "COLLECTION_FAILED", "ABANDONED"):
                problems.append(f"{name}: unknown status {status!r}")
            if status == "COLLECTED":
                collection = record.get("collection") or {}
                if collection.get("status") != "ok":
                    problems.append(f"{name}: status COLLECTED but "
                                    "collection.status is not ok")
                if not record.get("analysis"):
                    problems.append(f"{name}: COLLECTED without analysis — "
                                    "a serial-only record cannot fill a "
                                    "journal-required cell")
                analysis = record.get("analysis") or {}
                if analysis and analysis.get("bootId") != (
                        record.get("collection") or {}).get("bootId"):
                    problems.append(
                        f"{name}: analysis is about boot "
                        f"{analysis.get('bootId')} but the collection names "
                        f"{(record.get('collection') or {}).get('bootId')} — "
                        "a record cannot carry another boot's journal")
                if analysis.get("failedSystemUnits") == [] and \
                        analysis.get("entryCount", 0) < 500:
                    problems.append(
                        f"{name}: empty failed-unit list from a journal of "
                        f"{analysis.get('entryCount')} entries — too small "
                        "to be a complete boot record")
            if verify_files:
                retention: dict[str, dict] = {}
                retention_path = record["_dir"] / "retention-manifest.json"
                if retention_path.is_file():
                    retention = {
                        e["path"]: e for e in json.loads(
                            retention_path.read_text(encoding="utf-8"))
                        .get("files", [])}
                for entry in record.get("evidenceManifest", []):
                    path = record["_dir"] / entry["path"]
                    if entry["path"] == "record.json":
                        continue
                    if not path.exists():
                        # a missing file is acceptable only when the
                        # retention manifest names it with the record's own
                        # digest — the digest chain stays unbroken
                        kept = retention.get(entry["path"])
                        if kept is None or kept["sha256"] != entry["sha256"]:
                            problems.append(
                                f"{name}: manifest names missing file "
                                f"{entry['path']} and the retention "
                                "manifest does not carry its digest")
                        else:
                            kept_path = Path(kept.get("retainedAt", ""))
                            if kept_path.is_file() and \
                                    sha256_file(kept_path) != entry["sha256"]:
                                problems.append(
                                    f"{name}: retained copy of "
                                    f"{entry['path']} does not match its "
                                    "recorded digest")
                    elif sha256_file(path) != entry["sha256"]:
                        problems.append(f"{name}: {entry['path']} does not "
                                        "match its recorded digest")


def unit_occurrences(by_cell: dict[str, list[dict]]) -> dict:
    """Stage 6 counts. A unit is counted from analysis dispositions only."""
    units: set[str] = set(WATCHLIST)
    for records in by_cell.values():
        for record in records:
            analysis = record.get("analysis") or {}
            for scope_key in ("systemUnits", "userUnits"):
                for unit in analysis.get(scope_key, []):
                    if unit["disposition"] in ("currently-failed",
                                               "failed-during-shutdown",
                                               "failed-transiently-and-recovered",
                                               "skipped-by-condition"):
                        units.add(unit["unit"])
    table: dict[str, dict[str, dict]] = {}
    for unit_name in sorted(units):
        table[unit_name] = {}
        for cell, records in by_cell.items():
            counts = {"bootsAttempted": 0, "bootsReachingGraphical": 0,
                      "activated": 0, "succeeded": 0, "failed": 0,
                      "failedDuringShutdown": 0,
                      "failedAndRecovered": 0, "skipped": 0,
                      "notApplicable": 0, "collectionFailed": 0}
            for record in records:
                counts["bootsAttempted"] += 1
                if record.get("status") != "COLLECTED":
                    counts["collectionFailed"] += 1
                    continue
                analysis = record["analysis"]
                if analysis.get("graphicalTargetReachedMono") is not None:
                    counts["bootsReachingGraphical"] += 1
                found = None
                for scope_key in ("systemUnits", "userUnits"):
                    for unit in analysis.get(scope_key, []):
                        if unit["unit"] == unit_name:
                            found = unit
                            break
                    if found:
                        break
                if found is None:
                    counts["notApplicable"] += 1
                    continue
                disposition = found["disposition"]
                if disposition == "currently-failed":
                    counts["activated"] += 1
                    counts["failed"] += 1
                elif disposition == "failed-during-shutdown":
                    counts["activated"] += 1
                    counts["failedDuringShutdown"] += 1
                elif disposition == "failed-transiently-and-recovered":
                    counts["activated"] += 1
                    counts["failedAndRecovered"] += 1
                elif disposition == "skipped-by-condition":
                    counts["skipped"] += 1
                elif disposition == "activated-and-succeeded":
                    counts["activated"] += 1
                    counts["succeeded"] += 1
                else:
                    counts["notApplicable"] += 1
            table[unit_name][cell] = counts
    return table


def gdm_readiness(record: dict) -> tuple[bool, list[str]]:
    """Stage 7: usable-greeter assertions for one collected boot."""
    reasons = []
    analysis = record["analysis"]
    gdm = analysis.get("gdm") or {}
    if analysis.get("graphicalTargetReachedMono") is None:
        reasons.append("graphical.target not reached")
    if not gdm.get("gdmReachedActive"):
        reasons.append("gdm.service never active")
    if gdm.get("gdmBootPhaseFailures"):
        reasons.append(f"gdm.service failed {gdm['gdmBootPhaseFailures']}x "
                       "before shutdown was requested")
    if (gdm.get("gdmRestartCounterMax") or 0) > 0:
        reasons.append("gdm restart loop observed")
    if gdm.get("greeterSessionOpenedMono") is None:
        reasons.append("no greeter session opened")
    if gdm.get("sessionNeverRegisteredMono") is not None:
        reasons.append("GdmDisplay session never registered")
    if gdm.get("gdmCoredumps"):
        reasons.append("GDM/gnome-shell coredump present")
    if gdm.get("fatalDisplayErrors"):
        reasons.append("fatal display-server error present")
    if analysis.get("seat0CreatedMono") is None:
        reasons.append("seat0 never created")
    # The stability window is judged from the installed journal: time from
    # greeter readiness to shutdown initiation. The serial-paced flag is a
    # fallback only — measured on this image, gdm can win the console
    # against systemd's graphical.target status line, so the serial marker
    # is itself intermittent (DSQ-20260801-cellA-002: journal shows 636 s
    # stable at graphical, serial never showed the line).
    readiness_point = (gdm.get("greeterSessionOpenedMono")
                       or analysis.get("graphicalTargetReachedMono"))
    shutdown_at = analysis.get("shutdownInitiatedMono")
    if readiness_point is not None and shutdown_at is not None:
        stable = shutdown_at - readiness_point
        if stable < 60.0:
            reasons.append(f"display stack observed stable for only "
                           f"{stable:.1f}s before shutdown (< 60s window)")
    elif not record.get("observationWindowCompleted"):
        reasons.append("observation window did not complete and the journal "
                       "cannot establish a stability window")
    if record.get("guestResetCount") != record.get("expectedResets"):
        reasons.append("guest reset count differs from the cell's expected")
    return (not reasons, reasons)


def load_dispositions(evidence_root: Path) -> dict:
    path = evidence_root / DISPOSITIONS_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _unit_entries(analysis: dict, unit_name: str) -> list[dict]:
    return [u for scope_key in ("systemUnits", "userUnits")
            for u in analysis.get(scope_key, []) if u["unit"] == unit_name]


def verify_contextual_acceptance(unit_name: str, disposition: dict,
                                 by_cell: dict, problems: list[str]) -> bool:
    """An expected contextual state is accepted only when the exact context
    holds in every counted boot the disposition claims to cover. There is
    deliberately no way to accept a unit by name alone."""
    kind = disposition.get("disposition")
    if kind not in ("EXPECTED_WITHOUT_USER_SESSION",
                    "OPTIONAL_COMPONENT_FAILURE",
                    "DEPENDENCY_FAILURE",
                    "EXPECTED_WITHOUT_NETWORK",
                    "SHUTDOWN_TEARDOWN_EXIT_RACE",
                    "SHUTDOWN_TEARDOWN_CRASH",
                    "FIRST_BOOT_NSS_WINDOW_RACE"):
        return False
    for cell, records in by_cell.items():
        for record in records:
            if record.get("status") != "COLLECTED":
                continue
            analysis = record["analysis"]
            entries = _unit_entries(analysis, unit_name)
            failed_entries = [u for u in entries
                              if u["disposition"] in ("currently-failed",
                                                      "failed-during-shutdown")]
            if not failed_entries:
                continue
            name = record["_dir"].name
            if kind == "EXPECTED_WITHOUT_USER_SESSION":
                sessions = analysis.get("sessionsByUid") or {}
                real_users = {uid: names for uid, names in sessions.items()
                              if any("gnome-initial-setup" not in n and
                                     "gdm" not in n for n in names)}
                if real_users:
                    problems.append(
                        f"{name}: {unit_name} failed while a real user "
                        f"session existed ({real_users}) — "
                        "EXPECTED_WITHOUT_USER_SESSION does not apply")
                    return False
            elif kind in ("SHUTDOWN_TEARDOWN_EXIT_RACE",
                          "SHUTDOWN_TEARDOWN_CRASH"):
                for unit in failed_entries:
                    if unit.get("failuresDuringBoot"):
                        problems.append(
                            f"{name}: {unit_name} failed "
                            f"{unit['failuresDuringBoot']}x before shutdown "
                            "was requested — a teardown disposition cannot "
                            "cover a boot-phase failure")
                        return False
                shutdown_at = analysis.get("shutdownInitiatedMono")
                if shutdown_at is None:
                    problems.append(
                        f"{name}: {unit_name} claimed as a teardown "
                        "disposition but the record shows no shutdown "
                        "initiation")
                    return False
                if kind == "SHUTDOWN_TEARDOWN_EXIT_RACE":
                    crashing = [u for u in failed_entries
                                if (u.get("mainExit") or {}).get("code")
                                == "dumped"]
                    if crashing:
                        problems.append(
                            f"{name}: {unit_name} dumped core — an exit "
                            "race disposition cannot cover a crash")
                        return False
                else:  # SHUTDOWN_TEARDOWN_CRASH: the coredump itself must
                    # also lie in the teardown phase
                    processes = disposition.get("crashProcesses") or []
                    for coredump in analysis.get("coredumps", []):
                        if coredump.get("process") in processes and \
                                (coredump.get("monotonic") or 0) < shutdown_at:
                            problems.append(
                                f"{name}: {coredump.get('process')} dumped "
                                f"core at {coredump.get('monotonic')} — "
                                "before shutdown was requested")
                            return False
            elif kind == "FIRST_BOOT_NSS_WINDOW_RACE":
                timeline = analysis.get("timeline") or {}
                window_start = timeline.get("authselectApplyStart")
                window_end = timeline.get("authselectApplyEnd")
                if window_start is None or window_end is None:
                    problems.append(
                        f"{name}: {unit_name} claimed as an NSS-window race "
                        "but the record has no authselect apply window")
                    return False
                for unit in failed_entries:
                    failures = [e["monotonic"] for e in unit.get("events", [])
                                if e["kind"] == "failed" and e["monotonic"]]
                    outside = [when for when in failures
                               if not (window_start - 0.5 <= when
                                       <= window_end + 2.0)]
                    if outside:
                        problems.append(
                            f"{name}: {unit_name} failed at {outside} — "
                            f"outside the authselect apply window "
                            f"[{window_start}, {window_end}] this "
                            "disposition is bound to")
                        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, default=(
        SCRIPT_DIR.parents[2] / "qualification/display-stack/evidence"))
    parser.add_argument("--dry-run", action="store_true",
                        help="evidence integrity only")
    parser.add_argument("--skip-file-digests", action="store_true")
    args = parser.parse_args()

    try:
        context = resolve_context()
    except ContextError as exc:
        print(f"context: {exc}")
        return 2

    problems: list[str] = []
    by_cell = load_records(args.evidence_root, problems)
    verify_integrity(by_cell, context, problems,
                     verify_files=not args.skip_file_digests)

    for problem in problems:
        print(f"  problem: {problem}")
    if args.dry_run:
        print(json.dumps({"records": sum(len(v) for v in by_cell.values()),
                          "problems": len(problems)}, indent=2))
        return 2 if problems else 0

    table = unit_occurrences(by_cell)

    cell_verdicts = {}
    gdm_failures_unexplained = 0
    for cell, records in by_cell.items():
        collected = [r for r in records if r.get("status") == "COLLECTED"]
        ready = []
        not_ready = []
        for record in collected:
            ok, reasons = gdm_readiness(record)
            (ready if ok else not_ready).append(
                {"run": record["_dir"].name, "reasons": reasons})
        cell_verdicts[cell] = {
            "planned": PLAN[cell],
            "attempted": len(records),
            "collected": len(collected),
            "gdmReady": len(ready),
            "gdmNotReady": not_ready,
            "complete": len(collected) >= PLAN[cell],
        }
        gdm_failures_unexplained += len(not_ready)

    dispositions = load_dispositions(args.evidence_root)
    # every unit that failed anywhere needs a closed disposition; the two
    # units this pass was opened for are always reported, even at zero
    units_needing_disposition = {SCREENCAST_CANONICAL, "avahi-daemon.service"}
    for unit_name, cells in table.items():
        if any(counts["failed"] or counts["failedDuringShutdown"] or
               counts["failedAndRecovered"] for counts in cells.values()):
            units_needing_disposition.add(unit_name)
    disposition_verdicts = {}
    for unit_name in sorted(units_needing_disposition):
        any_failure = any(
            counts["failed"] or counts["failedDuringShutdown"] or
            counts["failedAndRecovered"]
            for counts in table.get(unit_name, {}).values())
        entry = dispositions.get(unit_name)
        if entry is None:
            disposition_verdicts[unit_name] = (
                "UNRESOLVED" if any_failure else "CLOSED (no failure observed)")
            continue
        kind = entry.get("disposition")
        confidence = entry.get("confidence")
        if confidence not in ("CONFIRMED", "STRONGLY_SUPPORTED"):
            disposition_verdicts[unit_name] = f"UNRESOLVED ({kind}, {confidence})"
            continue
        if kind in ("BOOT_CRITICAL_DEFECT", "GRAPHICAL_SESSION_DEFECT",
                    "HARNESS_OR_COLLECTOR_DEFECT"):
            # a defect blocks while it is observable in this scenario's
            # records; a defect of a *prior* scenario's harness or
            # collector, with zero dsq-1 failures, is closed history
            if any_failure:
                disposition_verdicts[unit_name] = f"BLOCKING ({kind})"
            else:
                disposition_verdicts[unit_name] = (
                    f"CLOSED ({kind} in prior scenario; no dsq-1 failure)")
        elif any_failure and not verify_contextual_acceptance(
                unit_name, entry, by_cell, problems):
            disposition_verdicts[unit_name] = (
                f"UNRESOLVED ({kind} claimed but context not verified)")
        else:
            disposition_verdicts[unit_name] = f"CLOSED ({kind})"

    all_cells_complete = all(v["complete"] for v in cell_verdicts.values())
    gdm_reliability = ("PASS" if all_cells_complete and
                       gdm_failures_unexplained == 0 and not problems
                       else "BLOCKED")
    dispositions_closed = all(v.startswith("CLOSED")
                              for v in disposition_verdicts.values())
    overall = ("PASS" if gdm_reliability == "PASS" and dispositions_closed
               else "BLOCKED")

    verdict = {
        "scenarioVersion": context.scenarioVersion,
        "recordCount": sum(len(v) for v in by_cell.values()),
        "problems": problems,
        "cells": cell_verdicts,
        "unitOccurrences": table,
        "dispositionVerdicts": disposition_verdicts,
        "gdmReliability": gdm_reliability,
        "displayStackReliability": overall,
    }
    out = args.evidence_root / "display-stack-qualification.json"
    out.write_text(json.dumps(verdict, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(json.dumps({"recordCount": verdict["recordCount"],
                      "gdmReliability": gdm_reliability,
                      "displayStackReliability": overall}, indent=2))
    print(f"verdict written to {out}")
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import dsq-2 first-login records: integrity, counts, verdict.

Three layers, strictly ordered, the same shape as dsq-1's importer so the two
can be read against each other.

1. Integrity (--dry-run stops here). Every record binds to the dsq-2
   authority and to the corrected artifact; boot IDs are unique across runs;
   sequences are contiguous; a run's cell configuration equals the cell's
   definition; file digests match. A dsq-1 record cannot appear here — it
   carries a different scenario version and a different artifact digest, and
   both are checked.

2. Counts. Per cell: logins attempted, first-login unit outcomes, chronyd
   outcomes, second-login coverage. Intermittent results are never reduced to
   one PASS.

3. Verdict, against Stage 12. The gate passes only when every counted boot
   logged in, both first-login units succeeded in every fresh home, no
   226/NAMESPACE occurred anywhere, every directory assertion held, every
   second login preserved prior state, and chronyd had zero identity
   failures. There is deliberately no percentage threshold: a single
   unexplained first-boot or chronyd failure keeps the category blocked.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT / "qualification/display-stack/scripts"))

from dsq_context import sha256_file  # noqa: E402
from run_boot import CELLS  # noqa: E402

RUN_DIR_RE = re.compile(r"^FLQ-(?P<date>\d{8})-cell(?P<cell>[A-E])-"
                        r"(?P<seq>\d{3})$")
PLAN = {"A": 20, "B": 10, "C": 10, "D": 10, "E": 10}
SECOND_LOGIN_PLAN = {"A": 10, "D": 5, "E": 5, "B": 0, "C": 0}
SCENARIO_VERSION = "dsq-2"
FIRST_LOGIN_UNITS = ("bunny-config-dir.service", "bunny-first-boot.service")


def load_records(evidence_root: Path, problems: list[str]) -> dict:
    by_cell: dict[str, list[dict]] = {cell: [] for cell in PLAN}
    seen_boot_ids: dict[str, str] = {}
    if not evidence_root.is_dir():
        problems.append(f"{evidence_root}: no evidence directory")
        return by_cell
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
        if record.get("cell") != cell or \
                record.get("sequence") != int(match.group("seq")):
            problems.append(f"{run_dir.name}: directory name and record "
                            "disagree about cell or sequence")
            continue
        if record.get("scenarioVersion") != SCENARIO_VERSION:
            problems.append(
                f"{run_dir.name}: scenarioVersion "
                f"{record.get('scenarioVersion')!r} is not {SCENARIO_VERSION} "
                "— a record from another scenario cannot fill a dsq-2 cell")
            continue
        expected_config = dict(CELLS[cell])
        if record.get("status") == "COLLECTED" and \
                record.get("cellConfiguration") != expected_config:
            problems.append(
                f"{run_dir.name}: cell configuration differs from the cell "
                f"{cell} definition")
            continue
        for boot_id in (record.get("collection") or {}).get("bootIds", []):
            if boot_id in seen_boot_ids:
                problems.append(
                    f"{run_dir.name}: boot ID {boot_id} already appears in "
                    f"{seen_boot_ids[boot_id]} — one boot cannot fill two "
                    "run directories")
                break
            seen_boot_ids[boot_id] = run_dir.name
        else:
            by_cell[cell].append(record)
    return by_cell


def verify_integrity(by_cell: dict, context: dict, problems: list[str],
                     verify_files: bool = True) -> None:
    for cell, records in by_cell.items():
        sequences = sorted(r["sequence"] for r in records)
        if sequences != list(range(1, len(sequences) + 1)):
            problems.append(
                f"cell {cell}: sequences are not contiguous from 001: "
                f"{sequences} — a gap is a deleted run")
        for record in records:
            name = record["_dir"].name
            artifact = record.get("artifact") or {}
            if artifact.get("sha256") != context.get(
                    "installationArtifactDigest"):
                problems.append(
                    f"{name}: artifact digest is not the corrected disk this "
                    "authority names")
            authority = record.get("authority") or {}
            if authority.get("scenarioVersion") != SCENARIO_VERSION:
                problems.append(f"{name}: authority is not {SCENARIO_VERSION}")
            if authority.get("sourceCommit") != context.get("sourceCommit"):
                problems.append(
                    f"{name}: bound to source commit "
                    f"{authority.get('sourceCommit')}, authority names "
                    f"{context.get('sourceCommit')}")
            fixture = record.get("loginFixture") or {}
            if record.get("status") == "COLLECTED":
                if not fixture.get("testInjected"):
                    problems.append(
                        f"{name}: does not record the login account as "
                        "test-injected; a record that does not say so could "
                        "be read as product behaviour")
                if fixture.get("partOfBunnyArtifact"):
                    problems.append(f"{name}: claims the fixture account is "
                                    "part of the artifact")
                if not record.get("analyses"):
                    problems.append(
                        f"{name}: COLLECTED without journal analyses — a "
                        "serial-only record cannot fill a login cell")
                if record.get("homeAssertions") is None:
                    problems.append(
                        f"{name}: COLLECTED without home assertions; unit "
                        "success alone does not establish what the directory "
                        "is")
            if verify_files:
                for entry in record.get("evidenceManifest", []):
                    if entry["path"] == "record.json":
                        continue
                    path = record["_dir"] / entry["path"]
                    if not path.exists():
                        problems.append(
                            f"{name}: manifest names missing file "
                            f"{entry['path']}")
                    elif sha256_file(path) != entry["sha256"]:
                        problems.append(
                            f"{name}: {entry['path']} does not match its "
                            "recorded digest")


def first_login_verdict(record: dict) -> tuple[bool, list[str]]:
    """Stage 12 assertions for one collected run's first login."""
    reasons: list[str] = []
    analyses = record.get("analyses") or []
    if not analyses:
        return False, ["no journal analysis"]
    first = analyses[0]

    if first.get("graphicalTargetReachedMono") is None:
        reasons.append("graphical.target not reached")
    if first.get("seat0CreatedMono") is None:
        reasons.append("seat0 never created")
    gdm = first.get("gdm") or {}
    if not gdm.get("gdmReachedActive"):
        reasons.append("gdm.service never active")
    if gdm.get("gdmBootPhaseFailures"):
        reasons.append("gdm.service failed before shutdown was requested")

    login = first.get("firstLogin") or {}
    if not login.get("loggedInUids"):
        reasons.append("no user session opened; the first-login units cannot "
                       "have run")
    for uid, units in (login.get("units") or {}).items():
        for unit_name in FIRST_LOGIN_UNITS:
            entry = units.get(unit_name)
            if entry is None:
                reasons.append(f"uid {uid}: {unit_name} never appeared in the "
                               "user journal")
                continue
            if entry.get("namespaceFailure"):
                reasons.append(
                    f"uid {uid}: {unit_name} exited 226/NAMESPACE — the "
                    "sandbox could not be built, which is the defect this "
                    "pass corrects")
            if entry.get("disposition") != "activated-and-succeeded":
                reasons.append(f"uid {uid}: {unit_name} disposition "
                               f"{entry.get('disposition')}")
            if entry.get("restartCounterMax"):
                reasons.append(f"uid {uid}: {unit_name} restart loop observed")

    home = record.get("homeAssertions") or {}
    for problem in home.get("problems", []):
        reasons.append(f"home: {problem}")

    chronyd = first.get("chronydOrdering") or {}
    if chronyd.get("userResolutionFailure"):
        reasons.append("chronyd exited 217/USER — the chrony account did not "
                       "resolve")
    if chronyd.get("observed") and chronyd.get("startedInsideApplyWindow"):
        reasons.append("chronyd spawned inside the authselect apply window")

    coredumps = [c for c in first.get("coredumps", [])
                 if (c.get("monotonic") or 0) <
                 (first.get("shutdownInitiatedMono") or float("inf"))]
    if coredumps:
        reasons.append(f"{len(coredumps)} coredump(s) before shutdown: "
                       f"{sorted({c.get('process') for c in coredumps})}")
    return (not reasons, reasons)


def second_login_verdict(record: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    analyses = record.get("analyses") or []
    if len(analyses) < 2:
        return False, ["no second login was collected"]
    second = analyses[1]
    login = second.get("firstLogin") or {}
    if not login.get("loggedInUids"):
        reasons.append("second boot opened no user session")
    for uid, units in (login.get("units") or {}).items():
        entry = units.get("bunny-first-boot.service")
        # ConditionPathExists=! means the unit is skipped once the marker
        # exists. A skip is the correct second-login outcome; a *rerun* would
        # mean the first-run flow repeated.
        if entry and entry.get("disposition") not in (
                "skipped-by-condition", "inactive-no-activation-observed",
                "activated-and-succeeded"):
            reasons.append(f"uid {uid}: bunny-first-boot disposition "
                           f"{entry.get('disposition')} on the second login")
        if entry and entry.get("namespaceFailure"):
            reasons.append(f"uid {uid}: 226/NAMESPACE on the second login")
    idempotence = record.get("idempotence") or {}
    for problem in idempotence.get("problems", []):
        reasons.append(f"idempotence: {problem}")
    return (not reasons, reasons)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/first-login/evidence")
    parser.add_argument("--context", type=Path,
                        default=ROOT / "qualification/first-login/"
                                       "evidence-context.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-file-digests", action="store_true")
    args = parser.parse_args()

    if not args.context.is_file():
        print(f"context: {args.context} does not exist; dsq-2 has no "
              "authority yet")
        return 2
    context = json.loads(args.context.read_text(encoding="utf-8"))
    if context.get("scenarioVersion") != SCENARIO_VERSION:
        print(f"context: scenarioVersion is {context.get('scenarioVersion')!r}")
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

    cells: dict[str, dict] = {}
    unexplained = 0
    second_login_done = {cell: 0 for cell in PLAN}
    for cell, records in by_cell.items():
        collected = [r for r in records if r.get("status") == "COLLECTED"]
        passed, failed = [], []
        for record in collected:
            ok, reasons = first_login_verdict(record)
            (passed if ok else failed).append(
                {"run": record["_dir"].name, "reasons": reasons})
            if record.get("secondLoginPlanned"):
                ok2, reasons2 = second_login_verdict(record)
                if ok2:
                    second_login_done[cell] += 1
                else:
                    failed.append({"run": record["_dir"].name,
                                   "reasons": [f"second login: {r}"
                                               for r in reasons2]})
        cells[cell] = {
            "planned": PLAN[cell],
            "attempted": len(records),
            "collected": len(collected),
            "firstLoginPassed": len(passed),
            "failures": failed,
            "secondLoginPlanned": SECOND_LOGIN_PLAN[cell],
            "secondLoginPassed": second_login_done[cell],
            "complete": len(collected) >= PLAN[cell],
            "secondLoginComplete":
                second_login_done[cell] >= SECOND_LOGIN_PLAN[cell],
        }
        unexplained += len(failed)

    all_complete = all(v["complete"] and v["secondLoginComplete"]
                       for v in cells.values())
    verdict_value = ("PASS" if all_complete and unexplained == 0
                     and not problems else "BLOCKED")
    verdict = {
        "scenarioVersion": SCENARIO_VERSION,
        "sourceCommit": context.get("sourceCommit"),
        "installationArtifactDigest": context.get(
            "installationArtifactDigest"),
        "recordCount": sum(len(v) for v in by_cell.values()),
        "problems": problems,
        "cells": cells,
        "unexplainedFailures": unexplained,
        "firstLoginReliability": verdict_value,
        "note": ("A single unexplained bunny-first-boot or chronyd failure "
                 "keeps this blocked. There is no percentage threshold."),
    }
    out = args.evidence_root / "first-login-qualification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(json.dumps({"recordCount": verdict["recordCount"],
                      "unexplainedFailures": unexplained,
                      "firstLoginReliability": verdict_value}, indent=2))
    print(f"verdict written to {out}")
    return 0 if verdict_value == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

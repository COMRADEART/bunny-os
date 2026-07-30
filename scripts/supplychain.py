#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Supply-chain and reproducibility gates.

Exit codes are the contract, and they are three rather than two:

    0   evaluated and satisfied
    2   evaluated and refused
    1   failed to evaluate

CI asserts the exact code at every call site. A job that accepts any non-zero
status as "the gate correctly refused" goes green when the tool crashes, which
is the F8 defect recorded in ``docs/CI_PORTABILITY_BASELINE.md``: a Python
traceback exits 1, and so does a missing file, an import error and a syntax
error. None of those is a refusal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from release.comparison import evaluate_comparison, evaluate_selinux_evidence  # noqa: E402
from release.mutablestate import (  # noqa: E402
    MutableStateError,
    audit_machine_identity,
    evaluate_identity,
    parse_policy,
    policy_paths_are_not_excluded,
)
from release.paths import display_path  # noqa: E402
from release.supplychain import (  # noqa: E402
    SupplyChainError,
    evaluate_input_locks,
    load_optional,
    parse_base_image_lock,
    parse_builder_image_lock,
    parse_package_snapshot_lock,
    parse_reproducibility_lock,
    toolchain_mismatches,
)

SATISFIED, CRASHED, REFUSED = 0, 1, 2

INPUTS = ROOT / "build" / "inputs"
OUT = ROOT / "build" / "out" / "qualification"


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / name
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return destination


def _load(parser_fn, path: Path, label: str):
    document = load_optional(path)
    if document is None:
        return None, f"{label}: absent at {display_path(path, ROOT)}"
    try:
        return parser_fn(document), ""
    except SupplyChainError as exc:
        return None, f"{label}: {exc}"


def verify_input_locks(_: argparse.Namespace) -> int:
    problems: list[str] = []
    base, message = _load(parse_base_image_lock, INPUTS / "base-image-lock.json", "base-image-lock")
    problems += [message] if message else []
    builder, message = _load(
        parse_builder_image_lock, INPUTS / "builder-image-lock.json", "builder-image-lock"
    )
    problems += [message] if message else []
    snapshot, message = _load(
        parse_package_snapshot_lock, INPUTS / "package-snapshot-lock.json", "package-snapshot-lock"
    )
    problems += [message] if message else []
    epoch, message = _load(
        parse_reproducibility_lock, INPUTS / "reproducibility-lock.json", "reproducibility-lock"
    )
    problems += [message] if message else []

    verdict = evaluate_input_locks(
        base=base, builder=builder, snapshot=snapshot, reproducibility=epoch
    )
    payload = verdict.as_dict()
    payload["parseErrors"] = problems
    destination = _write("input-locks.json", payload)

    print(f"input locks: {verdict.result}")
    for name, ok, detail in verdict.checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {detail}")
    for problem in problems:
        print(f"  FAIL  {problem}")
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if verdict.passed and not problems else REFUSED


def machine_identity_check(args: argparse.Namespace) -> int:
    collection = Path(args.dimensions)
    if not collection.is_file():
        print(
            f"BLOCKED: no collected artifact at {collection}. The machine-identity audit reads a "
            "dimension collection produced by collect_comparison_dimensions.py; with none, there "
            "is nothing to audit and an absent input is not a pass.",
            file=sys.stderr,
        )
        return REFUSED

    document = json.loads(collection.read_text(encoding="utf-8"))
    dimensions = document.get("dimensions") or {}

    # The audit runs over the *whole* entry set, so it deliberately reassembles
    # the volatile paths the comparison drops. /etc/machine-id is excluded from
    # every dimension, which is exactly where a leaked identity would hide.
    entries: dict[str, dict[str, object]] = {}
    for path, mode in (dimensions.get("permissions") or {}).items():
        entries[path] = {"type": "file", "mode": mode}
    for path, value in (dimensions.get("fileDigests") or {}).items():
        entries.setdefault(path, {"type": "file"})["sha256"] = value
    for path in document.get("volatilePathsExcluded") or []:
        entries.setdefault(path, {"type": "file"})
    for path, size in (document.get("entrySizes") or {}).items():
        entries.setdefault(path, {"type": "file"})["size"] = size

    findings = audit_machine_identity(entries)
    report = evaluate_identity(findings)
    report["source"] = str(collection)
    report["note"] += (
        " Sizes are read from the collection's entrySizes map when present; a collection without "
        "it cannot settle the empty-placeholder checks and those report as failures rather than "
        "as passes."
    )
    destination = _write("machine-identity.json", report)

    print(f"machine identity: {report['result']}")
    for finding in report["findings"]:
        print(
            f"  {'ok  ' if finding['ok'] else 'FAIL'}  {finding['path']}: "
            f"expected {finding['expected']}, observed {finding['observed']}"
        )
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if report["result"] == "PASS" else REFUSED


def mutable_state_check(args: argparse.Namespace) -> int:
    policy_path = Path(args.policy)
    if not policy_path.is_file():
        print(f"BLOCKED: no mutable-state policy at {policy_path}", file=sys.stderr)
        return REFUSED
    try:
        entries = parse_policy(json.loads(policy_path.read_text(encoding="utf-8")))
    except MutableStateError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return REFUSED

    excluded: list[str] = []
    collection = Path(args.dimensions)
    if collection.is_file():
        document = json.loads(collection.read_text(encoding="utf-8"))
        excluded = list(document.get("volatilePathsExcluded") or [])

    overlap = policy_paths_are_not_excluded(entries, excluded)

    report = {
        "schemaVersion": 1,
        "policyPaths": len(entries),
        "categories": sorted({entry.category for entry in entries}),
        "dispositions": sorted({entry.disposition for entry in entries}),
        "excludedOverlap": list(overlap),
        "entries": [entry.as_dict() for entry in entries],
        "result": "BLOCKED" if overlap else "PASS",
        "note": (
            "The mutable-state policy is not an exclusion list for the reproducibility "
            "comparison. A path it names must be absent from the artifact, which the comparison "
            "can see. Any path that is both in the policy and in the comparison's exclusion list "
            "is invisible to the comparison, so the policy would be enforcing nothing."
        ),
    }
    destination = _write("mutable-state.json", report)

    print(f"mutable state policy: {report['result']}")
    print(f"  {len(entries)} paths across {len(report['categories'])} categories")
    if overlap:
        print("  FAIL these paths are also excluded from the comparison, so nothing enforces them:")
        for path in overlap:
            print(f"    {path}")
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if not overlap else REFUSED


def toolchain_independence(args: argparse.Namespace) -> int:
    builder, message = _load(
        parse_builder_image_lock, INPUTS / "builder-image-lock.json", "builder-image-lock"
    )
    if builder is None:
        print(f"BLOCKED: {message}", file=sys.stderr)
        return REFUSED

    builders = json.loads(Path(args.builders).read_text(encoding="utf-8"))
    records = builders.get("builderRecords") or []
    if len(records) < 2:
        print(
            "BLOCKED: fewer than two builder records; toolchain independence is a property of a "
            "pair and cannot be decided from one record.",
            file=sys.stderr,
        )
        return REFUSED

    classifications = {tool.name: tool.classification for tool in builder.tools}
    for name in builder.as_dict().get("absentTools", {}) or {}:
        classifications.setdefault(name, "unavailable-but-unused")

    results = []
    blocked = False
    for first in range(len(records)):
        for second in range(first + 1, len(records)):
            left, right = records[first], records[second]
            blocking, recorded, unclassified = toolchain_mismatches(
                left.get("toolchain") or {},
                right.get("toolchain") or {},
                classifications=classifications,
            )
            ok = not blocking and not unclassified
            blocked = blocked or not ok
            results.append(
                {
                    "first": left.get("builderId"),
                    "second": right.get("builderId"),
                    "blocking": list(blocking),
                    "recordedOnly": list(recorded),
                    "unclassified": list(unclassified),
                    "result": "PASS" if ok else "BLOCKED",
                }
            )

    report = {
        "schemaVersion": 1,
        "builderImageDigest": builder.builderDigest,
        "pairs": results,
        "result": "BLOCKED" if blocked else "PASS",
        "note": (
            "A tool-version difference blocks unless it is classified evidence-generation-only or "
            "unavailable-but-unused, with a reason and a test. 'unknown' always blocks: a tool "
            "whose effect on the artifact nobody has established cannot be assumed to have none."
        ),
    }
    destination = _write("toolchain-independence.json", report)

    print(f"toolchain independence: {report['result']}")
    for entry in results:
        print(f"  {entry['result']:<8} {entry['first']} + {entry['second']}")
        for label, key in (
            ("blocking", "blocking"),
            ("recorded only", "recordedOnly"),
            ("UNCLASSIFIED", "unclassified"),
        ):
            if entry[key]:
                print(f"      {label}: {', '.join(entry[key])}")
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if not blocked else REFUSED


def reproducibility_gate(args: argparse.Namespace) -> int:
    comparison_path = Path(args.comparison)
    if not comparison_path.is_file():
        print(
            f"BLOCKED: no comparison at {comparison_path}. A reproducibility gate with no "
            "comparison to read is not a passing gate.",
            file=sys.stderr,
        )
        return REFUSED

    document = json.loads(comparison_path.read_text(encoding="utf-8"))
    report = evaluate_comparison(
        document,
        independent=bool(args.independent),
        selinuxStage=args.selinux_stage,
    )
    payload = report.as_dict()
    payload["acceptedOutcome"] = "REPRODUCIBLE"
    payload["policyNote"] = (
        "The production reproducibility prerequisite requires REPRODUCIBLE. "
        "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE is not accepted for the stable gate unless the "
        "release policy is changed through a separate reviewed decision, and no such decision "
        "exists."
    )
    destination = _write("reproducibility-gate.json", payload)

    print(f"reproducibility: {report.outcome}")
    for state in ("MATCH", "DIFFER", "NOT_COLLECTED"):
        names = payload["dimensionsByState"][state]
        if names:
            print(f"  {state:<14} {len(names):>2}: {', '.join(names)}")
    for reason in report.reasons:
        print(f"  - {reason}")
    if report.selinux:
        print(f"  SELinux composite ({report.selinux['stage']} stage): "
              f"{report.selinux['compositeState']}")
        for entry in report.selinux["subchecks"]:
            marker = "required" if entry["requiredAtThisStage"] else "later stage"
            print(f"    {entry['state']:<14} {entry['subcheck']} ({marker})")
    print(f"  independent builders: {'yes' if report.independent else 'no'}")
    print(f"  satisfies production gate: {'yes' if report.satisfiesProductionGate else 'no'}")
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if report.satisfiesProductionGate else REFUSED


def compare_three_builds(args: argparse.Namespace) -> int:
    """Require H1 vs H2, L vs H1 and L vs H2 to agree.

    One hosted run compared against a local build is one comparison, and a
    favourable one can be an accident: two hosted runs an hour apart on the same
    commit previously disagreed with each other. Requiring the two hosted builds
    to match each other first removes that reading.
    """
    paths = {
        "H1 vs H2": Path(args.hosted_pair),
        "L vs H1": Path(args.local_hosted_one),
        "L vs H2": Path(args.local_hosted_two),
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        print(
            "BLOCKED: these comparisons have not been produced: "
            + ", ".join(missing)
            + ".\nAll three are required. A single local-versus-hosted comparison cannot "
            "distinguish reproducibility from one accidentally favourable hosted run.",
            file=sys.stderr,
        )
        return REFUSED

    results = {}
    satisfied = True
    for name, path in paths.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        report = evaluate_comparison(document, independent=True, selinuxStage="archive")
        results[name] = {
            "outcome": report.outcome,
            "reasons": list(report.reasons),
            "differing": report.as_dict()["dimensionsByState"]["DIFFER"],
            "notCollected": report.as_dict()["dimensionsByState"]["NOT_COLLECTED"],
        }
        satisfied = satisfied and report.outcome == "REPRODUCIBLE"

    payload = {
        "schemaVersion": 1,
        "comparisons": results,
        "result": "PASS" if satisfied else "BLOCKED",
        "note": (
            "Three comparisons, all required to be REPRODUCIBLE: the two hosted builds against "
            "each other, and the local build against each of them. Two hosted runs of one commit "
            "an hour apart previously produced different results because the runner image "
            "rotated, so a single hosted comparison cannot establish reproducibility."
        ),
    }
    destination = _write("three-builder-comparison.json", payload)

    print(f"three-builder comparison: {payload['result']}")
    for name, entry in results.items():
        print(f"  {entry['outcome']:<40} {name}")
        if entry["differing"]:
            print(f"      differing: {', '.join(entry['differing'])}")
        if entry["notCollected"]:
            print(f"      not collected: {', '.join(entry['notCollected'])}")
    print(f"wrote {display_path(destination, ROOT)}")
    return SATISFIED if satisfied else REFUSED


def main() -> int:
    parser = argparse.ArgumentParser(prog="supplychain")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("verify-input-locks")

    identity = commands.add_parser("machine-identity-check")
    identity.add_argument("--dimensions", default=str(OUT / "dimensions.json"))

    mutable = commands.add_parser("mutable-state-check")
    mutable.add_argument("--policy", default=str(INPUTS / "mutable-state-policy.json"))
    mutable.add_argument("--dimensions", default=str(OUT / "dimensions.json"))

    independence = commands.add_parser("toolchain-independence")
    independence.add_argument(
        "--builders", default=str(ROOT / "operations" / "data" / "builders.json")
    )

    gate = commands.add_parser("reproducibility-gate")
    gate.add_argument("--comparison", default=str(ROOT / "operations" / "data" / "build-comparison.json"))
    gate.add_argument("--independent", action="store_true")
    gate.add_argument("--selinux-stage", default="archive", choices=("archive", "installed-system"))

    three = commands.add_parser("compare-three-builds")
    three.add_argument("--hosted-pair", default=str(OUT / "comparison-h1-h2.json"))
    three.add_argument("--local-hosted-one", default=str(OUT / "comparison-l-h1.json"))
    three.add_argument("--local-hosted-two", default=str(OUT / "comparison-l-h2.json"))

    args = parser.parse_args()
    handlers = {
        "verify-input-locks": verify_input_locks,
        "machine-identity-check": machine_identity_check,
        "mutable-state-check": mutable_state_check,
        "toolchain-independence": toolchain_independence,
        "reproducibility-gate": reproducibility_gate,
        "compare-three-builds": compare_three_builds,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

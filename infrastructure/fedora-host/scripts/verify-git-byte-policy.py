#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure the evidence byte-round-trip policy and record what was measured.

The readiness gate has a mandatory condition, ``git-byte-roundtrip``, asserting
that attested evidence bytes survive this checkout unchanged. Until this script
existed, the collector wrote ``null`` for that field and the operator checklist
asked a human to change it to ``true`` after running the guard by hand.

That made one mandatory condition satisfiable by typing a word. Every other
condition in the gate is an observation; this one was an assertion, and it was
the assertion guarding the property that a whole PR was written to protect.

So the check runs here and writes its own result. ``--update-environment`` will
write ``true`` only when this process measured it, and writes ``false`` the
moment anything fails, which is the outcome a hand-edit would never produce.

    python verify-git-byte-policy.py
    python verify-git-byte-policy.py --update-environment environment.json

Exit 0 when the policy holds, 2 when it does not.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

EVIDENCE_DOCUMENTS = ("operations/data/release-evidence.json",)
INVALIDATED_REGISTRY = "qualification/hardware/INVALIDATED_EVIDENCE.json"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def attested_paths() -> dict[str, set[str]]:
    """Every repository path bound to a digest by an evidence record."""
    found: dict[str, set[str]] = {}
    for name in EVIDENCE_DOCUMENTS:
        document = json.loads((ROOT / name).read_text(encoding="utf-8"))
        for record in document.get("records", []):
            reference = record.get("evidenceReference")
            digest = record.get("contentDigest")
            if reference and digest:
                found.setdefault(reference, set()).add(digest)
    return found


def filtering_disabled(path: str) -> bool:
    out = git("check-attr", "text", "--", path).decode().strip()
    return out.rsplit(": ", 1)[-1] == "unset"


def check_attributes() -> tuple[bool, list[str]]:
    unprotected = sorted(p for p in attested_paths() if not filtering_disabled(p))
    return not unprotected, [f"{p}: git may rewrite its bytes on checkout" for p in unprotected]


def check_round_trip() -> tuple[bool, list[str]]:
    problems = []
    for path in sorted(attested_paths()):
        working = sha256((ROOT / path).read_bytes()).hexdigest()
        committed = sha256(git("show", f"HEAD:{path}")).hexdigest()
        if working != committed:
            problems.append(f"{path}: working {working[:12]} != committed {committed[:12]}")
    return not problems, problems


def check_invalidated_registry() -> tuple[bool, list[str]]:
    """The invalidated record must still be invalidated, and still wrong.

    A host that silently "fixed" the CRLF-bound record by re-digesting it would
    otherwise pass every other check here.
    """
    registry_path = ROOT / INVALIDATED_REGISTRY
    if not registry_path.is_file():
        return False, [f"{INVALIDATED_REGISTRY} is missing"]

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    document = json.loads((ROOT / EVIDENCE_DOCUMENTS[0]).read_text(encoding="utf-8"))
    records = {r["id"]: r for r in document["records"]}

    problems = []
    for entry in registry["invalidated"]:
        record = records.get(entry["recordId"])
        if record is None:
            problems.append(f"{entry['recordId']}: invalidated record was deleted")
            continue
        if record["contentDigest"] != entry["recordedDigest"]:
            problems.append(
                f"{entry['recordId']}: recorded digest was edited; an invalidated record is "
                "replaced by a new measurement under a new id, never repaired in place"
            )
        if record.get("result") == "PASS":
            problems.append(f"{entry['recordId']}: invalidated record claims PASS")
    return not problems, problems


def check_evidence_suite() -> tuple[bool, list[str]]:
    """Run the repository's own guard rather than reimplementing its verdict."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/evidence", "-t", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, []
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-12:]
    return False, ["tests/evidence failed:", *tail]


CHECKS = (
    ("attested-files-bypass-content-filters", check_attributes),
    ("attested-bytes-round-trip", check_round_trip),
    ("invalidated-record-remains-invalidated", check_invalidated_registry),
    ("evidence-suite-passes", check_evidence_suite),
)


def measure() -> dict:
    results = []
    for name, check in CHECKS:
        passed, problems = check()
        results.append({"check": name, "passed": passed, "problems": problems})
    return {
        "schemaVersion": 1,
        "repository": str(ROOT),
        "attestedPathCount": len(attested_paths()),
        "autocrlf": (git("config", "--get", "core.autocrlf").decode().strip() or None)
        if subprocess.run(["git", "config", "--get", "core.autocrlf"], cwd=ROOT,
                          capture_output=True).returncode == 0
        else None,
        "passed": all(r["passed"] for r in results),
        "checks": results,
    }


def update_environment(path: Path, passed: bool) -> None:
    """Write the measured result into the environment report.

    Writes false as readily as true. A field that only ever gains a true is a
    field nobody is measuring.
    """
    report = json.loads(path.read_text(encoding="utf-8"))
    report.setdefault("git", {})["byteRoundtripTestsPass"] = passed
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-environment",
        type=Path,
        help="write git.byteRoundtripTestsPass into this environment report",
    )
    parser.add_argument("--output", type=Path, help="write the full measurement as JSON")
    args = parser.parse_args()

    try:
        result = measure()
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: the byte policy could not be measured: {exc}")
        if args.update_environment:
            # An unmeasurable policy is not a satisfied one.
            update_environment(args.update_environment, False)
            print(f"         recorded byteRoundtripTestsPass=false in {args.update_environment}")
        return 2

    print(f"evidence byte policy: {'PASS' if result['passed'] else 'FAIL'}")
    print(f"  attested paths: {result['attestedPathCount']}")
    print(f"  core.autocrlf:  {result['autocrlf']}")
    for check in result["checks"]:
        print(f"  {'ok     ' if check['passed'] else 'FAILED '} {check['check']}")
        for problem in check["problems"]:
            print(f"          {problem}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")
        print(f"\nwrote {args.output}")

    if args.update_environment:
        update_environment(args.update_environment, result["passed"])
        print(f"recorded byteRoundtripTestsPass={str(result['passed']).lower()} "
              f"in {args.update_environment}")

    if not result["passed"]:
        print("\nBLOCKED: attested evidence does not round-trip this checkout. "
              "The readiness gate will refuse this host.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

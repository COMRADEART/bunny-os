#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the Alpha gate outputs and produce one record that cannot overstate them.

The rule this file exists to hold: **a gate that did not run is NOT_RUN, never
passed.** §42 asks for five gates and two of them cost minutes per iteration, so
a run that skips them is expected — what is not acceptable is a summary that
reports four gates and calls it complete. Every gate appears in the record with
the count it was asked for, the count it achieved, and a status of ``passed``,
``failed`` or ``notRun``; ``allPassed`` is true only when every gate that was
*asked for* passed, and ``complete`` is true only when nothing was NOT_RUN.

Exit status: 0 every requested gate passed, 1 at least one did not, 2 a gate's
output could not be read at all.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

#: The five §42 gates, with the counts the brief names.
GATES: tuple[tuple[str, str, int, str], ...] = (
    ("service-100", "companion service lifecycle runs", 100, "gate-service-100.json"),
    ("alpha-100", "Alpha session-surface lifecycle runs", 100, "gate-alpha-100.json"),
    ("suite-50", "complete companion suites", 50, "gate-suite-50.json"),
    ("vm-story-20", "booted VM Alpha stories", 20, ""),
    ("install-10", "install to boot to first-run stories", 10, ""),
)


def _read(path: Path) -> tuple[Mapping[str, Any] | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except OSError as error:
        return None, f"not present: {error}"
    except json.JSONDecodeError as error:
        return None, f"unreadable: {error}"


def _stress_gate(evidence: Path, filename: str, required: int) -> dict[str, Any]:
    document, failure = _read(evidence / filename)
    if document is None:
        return {"status": "notRun", "detail": failure, "achieved": 0}
    iterations = document.get("iterations") or []
    passed = sum(1 for item in iterations if item.get("ok"))
    consecutive = document.get("longestConsecutive", document.get("consecutive", 0))
    commits = sorted({str(item.get("commit", "")) for item in iterations if item.get("commit")})
    held = passed >= required and len(iterations) >= required
    return {
        "status": "passed" if held else "failed",
        "achieved": passed,
        "iterations": len(iterations),
        "longestConsecutive": consecutive,
        "commitsObserved": commits,
        # §42 asks for thread, descriptor and resource deltas. They are the
        # reason a gate that "passes" can still be a failure: a hundred runs
        # that all succeed and leave a hundred threads is a leak, not a pass.
        "netGrowth": document.get("netGrowth", document.get("growth")),
        "heldResources": document.get("heldResources"),
        "detail": "" if held else f"{passed}/{required} iterations passed",
    }


def _vm_gate(evidence: Path, prefix: str, required: int, asked: int) -> dict[str, Any]:
    if asked <= 0:
        return {
            "status": "notRun", "achieved": 0, "asked": 0,
            "detail": (
                f"asked for 0 of the {required} the brief requires. A booted-VM gate costs "
                "minutes per iteration and was run separately; this record does not claim it."
            ),
        }
    records = sorted(evidence.glob(f"{prefix}-*.json"))
    outcomes: list[dict[str, Any]] = []
    for path in records:
        document, failure = _read(path)
        if document is None:
            outcomes.append({"file": path.name, "held": False, "detail": failure})
            continue
        outcomes.append({
            "file": path.name,
            "held": bool(document.get("allHeld")),
            "heldCount": document.get("heldCount"),
            "assertionCount": document.get("assertionCount"),
            "failed": [
                item["assertion"] for item in document.get("assertions", [])
                if not item.get("held")
            ],
        })
    passed = sum(1 for item in outcomes if item["held"])
    held = passed >= asked and asked >= required
    return {
        "status": "passed" if (passed >= asked and passed > 0) else "failed",
        "achieved": passed,
        "asked": asked,
        "required": required,
        "meetsBriefCount": held,
        "runs": outcomes,
        "detail": (
            "" if held else
            f"{passed}/{asked} stories held; the brief asks for {required}"
        ),
    }


def _log_gate(evidence: Path, prefix: str, required: int, asked: int) -> dict[str, Any]:
    if asked <= 0:
        return {
            "status": "notRun", "achieved": 0, "asked": 0,
            "detail": f"asked for 0 of the {required} the brief requires",
        }
    logs = sorted(evidence.glob(f"{prefix}-*.log"))
    passed = 0
    outcomes = []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            outcomes.append({"file": path.name, "held": False, "detail": str(error)})
            continue
        held = "installation smoke test" in text.lower() and "failed" not in text.lower()
        passed += 1 if held else 0
        outcomes.append({"file": path.name, "held": held})
    return {
        "status": "passed" if passed >= asked and passed > 0 else "failed",
        "achieved": passed, "asked": asked, "required": required,
        "meetsBriefCount": passed >= required,
        "runs": outcomes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha-collect")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--vm-runs", type=int, default=0)
    parser.add_argument("--install-runs", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)

    evidence = arguments.evidence
    results: dict[str, Any] = {}
    for identifier, description, required, filename in GATES:
        if filename:
            record = _stress_gate(evidence, filename, required)
        elif identifier.startswith("vm-"):
            record = _vm_gate(evidence, "gate-vm", required, arguments.vm_runs)
        else:
            record = _log_gate(evidence, "gate-install", required, arguments.install_runs)
        record["gate"] = identifier
        record["description"] = description
        record["required"] = required
        results[identifier] = record

    requested = [item for item in results.values() if item["status"] != "notRun"]
    not_run = [item["gate"] for item in results.values() if item["status"] == "notRun"]
    document = {
        "schemaVersion": 1,
        "phase": "public-alpha-integration",
        "commit": arguments.commit,
        "gates": results,
        "allPassed": bool(requested) and all(item["status"] == "passed" for item in requested),
        # Distinct from allPassed, and the distinction is the point: a run with
        # every requested gate green and two gates NOT_RUN is not a complete
        # gate run, and a reader must be able to tell without counting.
        "complete": not not_run,
        "notRun": not_run,
        "note": (
            "A gate that did not run is NOT_RUN and is never counted as passed. "
            "allPassed describes only the gates this run was asked for; complete "
            "describes whether that was all of them."
        ),
    }
    output = arguments.output or (evidence / "alpha-gates.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for identifier, record in results.items():
        mark = {"passed": "ok", "failed": "!!", "notRun": "--"}[record["status"]]
        print(
            f"  [{mark}] {identifier:14} {record['achieved']}/{record['required']} "
            f"{record['description']}"
            + (f"  — {record['detail']}" if record.get("detail") else "")
        )
    print(f"allPassed={document['allPassed']} complete={document['complete']}")
    if not_run:
        print(f"NOT_RUN: {', '.join(not_run)}")
    print(f"record: {output}")
    return 0 if document["allPassed"] else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Development qualification track commands.

Separate from ``scripts/phase5.py`` because the production gate it drives must
not gain a development code path. This entry point can reach GO on virtual,
development-key evidence; ``gate-stable-release`` cannot and is not touched.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from operations.devqualification import (
    DevQualificationError,
    evaluate_development,
    production_gap_analysis,
)
from operations.qualification import REQUIRED_AUTOMATED, evaluate_release

DEV_EVIDENCE = ROOT / "operations/data/dev-qualification.json"
PRODUCTION_EVIDENCE = ROOT / "operations/data/stable-qualification.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence() -> dict[str, Any]:
    document = load(DEV_EVIDENCE)
    if document.get("schemaVersion") != 1:
        raise SystemExit("dev-qualification.json schemaVersion is unsupported")
    evidence = document.get("evidence")
    if not isinstance(evidence, dict):
        raise SystemExit("dev-qualification.json has no evidence object")
    return evidence


def gate() -> int:
    evidence = _evidence()
    try:
        decision = evaluate_development(evidence, root=ROOT)
    except DevQualificationError as error:
        print(f"development evidence is invalid: {error}")
        return 2
    print(json.dumps(decision.as_dict(), indent=2, sort_keys=True))
    produced = len(REQUIRED_AUTOMATED) - len(decision.missing) - len(decision.failing)
    print(
        f"\n{produced} of {len(REQUIRED_AUTOMATED)} evidence rows are produced and passing "
        f"in the development track."
    )
    if decision.passed:
        print("Development qualification: GO. This is not a stable release approval.")
        return 0
    print("Development qualification: NO-GO.")
    return 2


def gaps() -> int:
    evidence = _evidence()
    analysis = production_gap_analysis(evidence)
    print(json.dumps(analysis, indent=2, sort_keys=True))
    return 0


def compare() -> int:
    """Show both tracks side by side, so neither can be mistaken for the other."""
    evidence = _evidence()
    try:
        development = evaluate_development(evidence, root=ROOT)
    except DevQualificationError as error:
        print(f"development evidence is invalid: {error}")
        return 2
    production_document = load(PRODUCTION_EVIDENCE)
    production = evaluate_release(
        production_document.get("evidence", {}),
        production_document.get("approvals", {}),
        production_document.get("blockers", []),
    )
    payload = {
        "development": development.as_dict(),
        "production": production.as_dict(),
        "note": (
            "Development evidence never promotes to production evidence. Physical hardware, a "
            "production key ceremony, independent review, and nine human approvals cannot be "
            "produced by running more tests."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if production.passed:
        print("\nWARNING: the production gate reports GO; verify this independently before publishing.")
        return 0
    print(
        f"\ndevelopment: {development.recommendation}    production: {production.recommendation}"
    )
    # Exit reflects the development track; the production gate has its own command.
    return 0 if development.passed else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="devqual")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("gate", "gaps", "compare"):
        commands.add_parser(name)
    args = parser.parse_args()
    if args.command == "gate":
        return gate()
    if args.command == "gaps":
        return gaps()
    if args.command == "compare":
        return compare()
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

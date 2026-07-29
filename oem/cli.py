"""``bunny-oem`` command-line interface.

Validation, evaluation, and reporting are implemented here and run anywhere.
Anything that would write to a real device — installing an image, creating a
device identity, erasing factory state — is deliberately *not* implemented in a
source-only build and exits 78 (``EX_CONFIG``), matching
``installer/bin/bunny-installer-backend``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from oem.validation.finalize import describe_checks, evaluate_finalisation
from oem.validation.overlay import validate_overlay
from oem.validation.profile import validate_profile
from oem.qualification import evaluate_qualification

EXIT_OK = 0
EXIT_REJECTED = 2
EXIT_UNAVAILABLE = 78

_UNAVAILABLE_REASON = (
    "The reviewed factory provisioning executor is not installed in this source-only build. "
    "No device was read, written, provisioned, or sealed."
)


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            if isinstance(item, list):
                print(f"{key}:")
                for entry in item:
                    print(f"  - {entry}")
            else:
                print(f"{key}: {item}")
        return
    print(value)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"file not found: {path}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid JSON in {path}: {error}")


def _unavailable(operation: str, as_json: bool) -> int:
    _emit(
        {
            "operation": operation,
            "available": False,
            "reason": _UNAVAILABLE_REASON,
            "devicesModified": 0,
            "writesPerformed": False,
        },
        as_json,
    )
    return EXIT_UNAVAILABLE


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bunny-oem", description="Bunny OS OEM customisation and factory tooling")
    root.add_argument("--json", action="store_true", help="emit JSON")
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-profile", help="validate a signed OEM profile")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--qualification", type=Path, help="signed hardware qualification report")

    overlay = commands.add_parser("validate-overlay", help="validate an OEM overlay manifest")
    overlay.add_argument("--overlay", type=Path, required=True)

    qualify = commands.add_parser("qualify", help="evaluate a hardware qualification report")
    qualify.add_argument("--report", type=Path, required=True)

    finalize = commands.add_parser("finalize", help="evaluate factory finalisation and refuse handoff if state remains")
    finalize.add_argument("--record", type=Path, required=True)

    commands.add_parser("describe-checks", help="list the factory finalisation check catalogue")

    for name, helptext in (
        ("provision", "run factory provisioning against a connected device"),
        ("seal", "erase factory state on a connected device"),
        ("build-image", "build an OEM image from a validated profile"),
    ):
        unavailable = commands.add_parser(name, help=helptext)
        unavailable.add_argument("--profile", type=Path)
        unavailable.add_argument("--device", type=str)
    return root


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in raw
    args = parser().parse_args([value for value in raw if value != "--json"])

    if args.command == "validate-profile":
        qualification = _load(args.qualification) if args.qualification else None
        verdict = validate_profile(_load(args.profile), qualification=qualification)
        _emit(verdict.as_dict(), as_json)
        return EXIT_OK if verdict.accepted else EXIT_REJECTED

    if args.command == "validate-overlay":
        verdict = validate_overlay(_load(args.overlay))
        _emit(verdict.as_dict(), as_json)
        return EXIT_OK if verdict.accepted else EXIT_REJECTED

    if args.command == "qualify":
        verdict = evaluate_qualification(_load(args.report))
        _emit(verdict.as_dict(), as_json)
        return EXIT_OK if verdict.passed else EXIT_REJECTED

    if args.command == "finalize":
        verdict = evaluate_finalisation(_load(args.record))
        payload = verdict.as_dict()
        payload["handoffPermitted"] = verdict.sealed
        if not verdict.sealed:
            payload["message"] = (
                "Customer handoff refused: temporary factory state remains or could not be verified."
            )
        _emit(payload, as_json)
        return EXIT_OK if verdict.sealed else EXIT_REJECTED

    if args.command == "describe-checks":
        _emit({"checks": describe_checks()} if as_json else {"checks": [item["checkId"] for item in describe_checks()]}, as_json)
        return EXIT_OK

    if args.command in {"provision", "seal", "build-image"}:
        return _unavailable(args.command, as_json)

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

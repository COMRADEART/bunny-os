# SPDX-License-Identifier: GPL-3.0-or-later
"""Non-destructive installer developer CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from installer.frontend.app import run as run_frontend
from installer.hardware.probe import probe as hardware_probe
from installer.plans.validation import validate_plan
from installer.storage.models import parse_lsblk
from installer.storage.planning import automatic_plan
from installer.storage.probe import discover


def _json_file(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return value


def _probe_file(path: str, fixture_name: str | None) -> dict[str, object]:
    value = _json_file(path)
    if fixture_name is None:
        return value
    fixtures = value.get("fixtures")
    if not isinstance(fixtures, dict) or fixture_name not in fixtures or not isinstance(fixtures[fixture_name], dict):
        raise ValueError("unknown storage fixture")
    return fixtures[fixture_name]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bunny-installer", description="Bunny OS safe installer planning tools")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("gui")
    probe = sub.add_parser("probe", help="run the fixed read-only lsblk probe")
    probe.add_argument("--installation-source")
    hardware = sub.add_parser("hardware", help="run read-only installation hardware preflight")
    hardware.add_argument("--storage-bytes", type=int, required=True)
    plan = sub.add_parser("plan", help="build a plan from a captured lsblk document")
    plan.add_argument("--probe-json", required=True)
    plan.add_argument("--fixture-name")
    plan.add_argument("--disk-id", required=True)
    plan.add_argument("--mode", choices=("erase_disk", "install_alongside", "oem"), required=True)
    plan.add_argument("--encrypted", action="store_true")
    plan.add_argument("--free-start-bytes", type=int)
    plan.add_argument("--free-size-bytes", type=int)
    validate = sub.add_parser("validate", help="validate a complete protocol plan without writing")
    validate.add_argument("--probe-json", required=True)
    validate.add_argument("--fixture-name")
    validate.add_argument("--plan", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "gui":
        return run_frontend()
    if args.command == "probe":
        value = {"schemaVersion": 1, "disks": [disk.to_dict() for disk in discover(installation_source=args.installation_source)]}
    elif args.command == "hardware":
        value = hardware_probe(storage_bytes=args.storage_bytes)
    elif args.command == "plan":
        disks = parse_lsblk(_probe_file(args.probe_json, args.fixture_name))
        disk = next((item for item in disks if item.id == args.disk_id), None)
        if disk is None:
            raise ValueError("selected disk id is absent")
        value = automatic_plan(
            disk,
            mode=args.mode,
            encryption=args.encrypted,
            free_start_bytes=args.free_start_bytes,
            free_size_bytes=args.free_size_bytes,
        )
        value["notice"] = "Planning only: no disk writes were performed."
    else:
        disks = parse_lsblk(_probe_file(args.probe_json, args.fixture_name))
        errors = validate_plan(_json_file(args.plan), disks)
        value = {"schemaVersion": 1, "valid": not errors, "errors": list(errors), "writesPerformed": False}
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0 if not isinstance(value, dict) or value.get("valid", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())

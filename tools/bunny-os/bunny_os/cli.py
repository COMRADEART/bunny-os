"""Implementation of the `bunny-os` conventional management CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import BrokerClientError, request
from .info import human as hardware_human, inventory


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item if not isinstance(item, (dict, list)) else json.dumps(item, sort_keys=True)}")
    else:
        print(value)


def _version() -> dict[str, Any]:
    try:
        return json.loads(Path("/usr/lib/bunny-os/release.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"osVersion": "0.1.0", "imageVersion": "development-uninstalled", "contractVersion": "1.0.0"}


def _doctor() -> dict[str, Any]:
    artifact_status = "absent"
    try:
        artifact_status = json.loads(Path("/usr/share/bunny-os/bunny-artifact.json").read_text(encoding="utf-8")).get("status", "invalid")
    except (OSError, json.JSONDecodeError):
        pass
    checks = {
        "releaseMetadata": Path("/usr/lib/bunny-os/release.json").is_file(),
        "brokerSocket": Path("/run/bunny/broker.sock").exists(),
        "updateState": Path("/var/lib/bunny-os/update").is_dir(),
        "recoveryTarget": Path("/usr/lib/systemd/system/bunny-recovery.target").is_file(),
        "bunnyArtifactStatus": artifact_status,
        "telemetryEnabled": False,
    }
    required = ("releaseMetadata", "brokerSocket", "updateState", "recoveryTarget")
    return {"healthy": all(bool(checks[key]) for key in required), "bunnyRuntimeReady": artifact_status == "verified", "checks": checks}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bunny-os")
    root.add_argument("--json", action="store_true", help="emit JSON")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("version")
    sub.add_parser("hardware")
    sub.add_parser("doctor")
    update = sub.add_parser("update").add_subparsers(dest="update_command", required=True)
    for name in ("status", "check", "stage", "install"):
        update.add_parser(name)
    preference = update.add_parser("preference")
    preference.add_argument("value", choices=("enable", "disable"))
    rollback = sub.add_parser("rollback").add_subparsers(dest="rollback_command", required=True)
    rollback.add_parser("list")
    rollback.add_parser("select")
    recovery = sub.add_parser("recovery").add_subparsers(dest="recovery_command", required=True)
    recovery.add_parser("status")
    schedule = recovery.add_parser("schedule")
    schedule.add_argument("mode", choices=("recovery", "safe-graphics"), default="recovery", nargs="?")
    logs = sub.add_parser("logs").add_subparsers(dest="logs_command", required=True)
    export = logs.add_parser("export")
    export.add_argument("--since-minutes", type=int, default=60)
    power = sub.add_parser("power").add_subparsers(dest="power_command", required=True)
    for name in ("shutdown", "reboot", "suspend"):
        power.add_parser(name)
    media = sub.add_parser("media").add_subparsers(dest="media_command", required=True)
    verify = media.add_parser("verify")
    verify.add_argument("--root", type=Path, default=Path("/run/initramfs/live"))
    verify.add_argument("--manifest", type=Path, default=Path("/run/initramfs/live/BUNNY-MANIFEST.json"))
    verify.add_argument("--signature", type=Path, default=Path("/run/initramfs/live/BUNNY-MANIFEST.json.sig"))
    verify.add_argument("--public-key", type=Path, default=Path("/usr/share/bunny-os/media-keys/release.pem"))
    return root


def main() -> int:
    argv = sys.argv[1:]
    as_json = "--json" in argv
    args = parser().parse_args([value for value in argv if value != "--json"])
    args.json = as_json
    try:
        if args.command == "version":
            value = _version()
        elif args.command == "hardware":
            value = inventory()
            if not args.json:
                print(hardware_human(value))
                return 0
        elif args.command == "doctor":
            value = _doctor()
        elif args.command == "status":
            value = request("system.status.read")
        elif args.command == "update":
            if args.update_command == "preference":
                value = request("update.preference.set", {"enabled": args.value == "enable"})
            else:
                method = {"status": "update.status.read", "check": "update.check", "stage": "update.stage", "install": "update.install"}[args.update_command]
                value = request(method)
        elif args.command == "rollback":
            value = request("rollback.list" if args.rollback_command == "list" else "rollback.select")
        elif args.command == "recovery":
            if args.recovery_command == "status":
                value = request("recovery.status.read")
            else:
                value = request("recovery.schedule", {"mode": args.mode})
        elif args.command == "logs":
            value = request("logs.export", {"sinceMinutes": args.since_minutes})
        elif args.command == "power":
            value = request(f"power.{args.power_command}")
        elif args.command == "media":
            from installer.validation.media import MediaVerificationError, verify_manifest

            try:
                value = verify_manifest(args.root, args.manifest, signature_path=args.signature, public_key=args.public_key)
            except MediaVerificationError as exc:
                raise BrokerClientError("media_verification_failed", str(exc)) from exc
        else:
            raise RuntimeError("unhandled command")
        _emit(value, args.json)
        return 0
    except BrokerClientError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, sort_keys=True))
        else:
            print(f"bunny-os: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

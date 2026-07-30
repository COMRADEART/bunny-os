# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""On-device qualification evidence collection for physical hardware.

Runs on an installed Bunny OS. Backs ``bunny-os qualification``.

The collector is an allow-list. It reads seventeen named facts and emits exactly
those; there is no code path that walks the system and reports what it finds,
because that is how a serial number ends up in an evidence file. Everything it
reads is a *class* rather than an identity: the CPU vendor and family rather than
the model string a vendor might make unique, a RAM size band rather than a byte
count, a Wi-Fi driver name rather than an interface or a network.

Twelve categories are excluded by name — serial numbers, MAC and IP addresses,
hostname, username, Wi-Fi network name, personal paths and files, Bunny prompts
and memory, browser history, asset tags. None of them is needed to qualify a
machine, and the collector has no function that reads any of them.

This module deliberately does not import from ``release/``: it is installed onto
a device and the release tooling is not. The field lists are duplicated, and
``tests/hardware_evidence`` asserts the two copies agree, so drift is a test
failure rather than a silent divergence.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
from pathlib import Path
import platform
import re
from typing import Any

COLLECTOR_VERSION = 1

#: Mirrors release.hardware.COLLECTOR_FIELDS. Asserted equal by the test suite.
COLLECTOR_FIELDS = (
    "bunnyOsVersion",
    "sourceCommit",
    "imageDigest",
    "architecture",
    "firmwareMode",
    "secureBootState",
    "tpmAvailable",
    "cpuFamily",
    "gpuFamily",
    "ramSizeCategory",
    "storageType",
    "wifiChipset",
    "bluetoothChipset",
    "kernel",
    "driverVersions",
    "testResults",
    "recoveryMediaDigest",
)

#: Mirrors release.hardware.EXCLUDED_CATEGORIES.
EXCLUDED_CATEGORIES = (
    "serialNumber",
    "macAddress",
    "ipAddress",
    "hostname",
    "username",
    "wifiNetworkName",
    "personalPaths",
    "personalFiles",
    "bunnyPrompts",
    "bunnyMemory",
    "browserHistory",
    "assetTag",
)

#: Mirrors release.hardware.GUIDED_TESTS.
GUIDED_TESTS = (
    "boot",
    "installation",
    "encrypted-installation",
    "secure-boot",
    "tpm",
    "graphics",
    "display",
    "wifi",
    "bluetooth",
    "audio",
    "microphone",
    "camera",
    "suspend",
    "resume",
    "battery-reporting",
    "update",
    "rollback",
    "recovery",
    "bunny-disabled-mode",
    "local-only-mode",
    "accessibility",
)

OUTCOMES = ("PASS", "FAIL", "NOT_APPLICABLE", "NOT_RUN")
UNKNOWN = "unknown"

#: Where guided test results accumulate on the device under test.
STATE_PATH = Path("/var/lib/bunny-os/qualification/guided-tests.json")

_RAM_BANDS = (
    (4 * 1024 * 1024, "under-4GB"),
    (8 * 1024 * 1024, "4-8GB"),
    (16 * 1024 * 1024, "8-16GB"),
    (32 * 1024 * 1024, "16-32GB"),
)


class QualificationError(RuntimeError):
    """Raised when collection or recording is refused."""


def _read(path: str | Path, *, limit: int = 65536) -> str:
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _release_metadata() -> dict[str, Any]:
    try:
        return json.loads(Path("/usr/lib/bunny-os/release.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _firmware_mode() -> str:
    if Path("/sys/firmware/efi").is_dir():
        return "uefi-secure-boot" if _secure_boot_state() == "enabled" else "uefi"
    return "legacy-bios"


def _secure_boot_state() -> str:
    # The EFI variable's fifth byte is the flag; the first four are attributes.
    for candidate in sorted(Path("/sys/firmware/efi/efivars").glob("SecureBoot-*")):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        if len(data) >= 5:
            return "enabled" if data[4] else "disabled"
    if not Path("/sys/firmware/efi").is_dir():
        return "unsupported"
    return UNKNOWN


def _tpm_available() -> bool:
    return Path("/dev/tpm0").exists() or any(Path("/sys/class/tpm").glob("tpm*"))


def _cpu_family() -> str:
    """Vendor and family/model numbers, not the marketing string.

    A model name is a product class and would usually be safe, but some vendors
    embed a stepping or an OEM suffix that narrows a device. The numbers are
    sufficient to describe a CPU class and cannot narrow further.
    """
    fields: dict[str, str] = {}
    for line in _read("/proc/cpuinfo").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in {"vendor_id", "cpu family", "model", "CPU implementer", "CPU part"} and key not in fields:
            fields[key] = value.strip()
    if "vendor_id" in fields:
        return f"{fields['vendor_id']} family {fields.get('cpu family', UNKNOWN)} model {fields.get('model', UNKNOWN)}"
    if "CPU implementer" in fields:
        return f"arm implementer {fields['CPU implementer']} part {fields.get('CPU part', UNKNOWN)}"
    return UNKNOWN


def _driver_of(device: Path) -> str:
    uevent = _read(device / "uevent")
    match = re.search(r"^DRIVER=(.+)$", uevent, re.MULTILINE)
    return match.group(1).strip() if match else UNKNOWN


def _gpu_family() -> str:
    drivers = sorted(
        {
            _driver_of(card / "device")
            for card in Path("/sys/class/drm").glob("card[0-9]")
            if (card / "device").exists()
        }
        - {UNKNOWN}
    )
    return ", ".join(drivers) if drivers else UNKNOWN


def _ram_size_category() -> str:
    match = re.search(r"^MemTotal:\s+(\d+) kB$", _read("/proc/meminfo"), re.MULTILINE)
    if not match:
        return UNKNOWN
    kilobytes = int(match.group(1))
    for threshold, name in _RAM_BANDS:
        if kilobytes < threshold:
            return name
    return "32GB-or-more"


def _storage_type() -> str:
    for block in sorted(Path("/sys/block").iterdir()) if Path("/sys/block").is_dir() else []:
        name = block.name
        if name.startswith(("loop", "ram", "zram", "dm-", "sr")):
            continue
        if name.startswith("nvme"):
            return "nvme"
        if name.startswith("mmcblk"):
            return "emmc"
        if name.startswith("vd"):
            return "virtual"
        if name.startswith("sd"):
            rotational = _read(block / "queue/rotational").strip()
            return "sata-hdd" if rotational == "1" else "sata-ssd"
    return UNKNOWN


def _network_chipset(kind: str) -> str:
    """The driver behind a wireless or Bluetooth device.

    Reads the driver name only. Interface names, hardware addresses and network
    names are never touched: nothing here opens the per-interface hardware
    address file, and nothing here asks the network daemon what it is connected
    to.
    """
    if kind == "wifi":
        drivers = set()
        for interface in sorted(Path("/sys/class/net").iterdir()) if Path("/sys/class/net").is_dir() else []:
            if not (interface / "wireless").exists() and not (interface / "phy80211").exists():
                continue
            drivers.add(_driver_of(interface / "device"))
        drivers.discard(UNKNOWN)
        return ", ".join(sorted(drivers)) if drivers else UNKNOWN
    drivers = {
        _driver_of(device / "device")
        for device in sorted(Path("/sys/class/bluetooth").glob("hci*"))
        if (device / "device").exists()
    }
    drivers.discard(UNKNOWN)
    return ", ".join(sorted(drivers)) if drivers else UNKNOWN


def _driver_versions(names: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in sorted({part.strip() for value in names for part in value.split(",") if part.strip()}):
        if name == UNKNOWN:
            continue
        version = _read(f"/sys/module/{name.replace('-', '_')}/version").strip()
        versions[name] = version or "in-tree"
    return versions


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": 1, "tests": {}}


def save_state(state: dict[str, Any], *, path: Path | None = None) -> Path:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def collect(*, recoveryMedia: Path | None = None, statePath: Path | None = None) -> dict[str, Any]:
    """Gather the seventeen approved facts. Emits nothing else."""
    release = _release_metadata()
    gpu = _gpu_family()
    wifi = _network_chipset("wifi")
    bluetooth = _network_chipset("bluetooth")

    state = json.loads(statePath.read_text(encoding="utf-8")) if statePath and statePath.is_file() else load_state()
    results = {
        name: state.get("tests", {}).get(name, {}).get("outcome", "NOT_RUN") for name in GUIDED_TESTS
    }

    collected = {
        "bunnyOsVersion": str(release.get("osVersion", UNKNOWN)),
        "sourceCommit": str(release.get("sourceCommit", UNKNOWN)),
        "imageDigest": str(release.get("imageDigest", release.get("imageVersion", UNKNOWN))),
        "architecture": platform.machine() or UNKNOWN,
        "firmwareMode": _firmware_mode(),
        "secureBootState": _secure_boot_state(),
        "tpmAvailable": _tpm_available(),
        "cpuFamily": _cpu_family(),
        "gpuFamily": gpu,
        "ramSizeCategory": _ram_size_category(),
        "storageType": _storage_type(),
        "wifiChipset": wifi,
        "bluetoothChipset": bluetooth,
        "kernel": platform.release() or UNKNOWN,
        "driverVersions": _driver_versions([gpu, wifi, bluetooth]),
        "testResults": results,
        "recoveryMediaDigest": _digest(recoveryMedia) if recoveryMedia and recoveryMedia.is_file() else UNKNOWN,
    }

    extraneous = sorted(set(collected) - set(COLLECTOR_FIELDS))
    if extraneous:  # pragma: no cover - guards the collector against drift
        raise QualificationError(
            f"collector produced fields outside the allow-list: {', '.join(extraneous)}"
        )

    return {
        "schemaVersion": 1,
        "collectorVersion": COLLECTOR_VERSION,
        "collectedAt": _now(),
        "collected": collected,
        "excludedCategories": list(EXCLUDED_CATEGORIES),
        "note": (
            "Seventeen approved facts, recorded as classes rather than identities. No serial "
            "number, MAC or IP address, hostname, username, network name, personal path or file, "
            "Bunny prompt or memory, or browser history is read by this collector."
        ),
    }


def record_test(
    *,
    test: str,
    outcome: str,
    operator: str,
    expected: str,
    actual: str,
    evidence: str | None,
    notes: str,
    logs: list[str],
    redaction: str,
    startedAt: str | None,
    statePath: Path | None = None,
) -> dict[str, Any]:
    """Record one guided test result. Refuses to fabricate a pass."""
    if test not in GUIDED_TESTS:
        raise QualificationError(f"test must be one of {', '.join(GUIDED_TESTS)}")
    if outcome not in OUTCOMES:
        raise QualificationError(f"outcome must be one of {', '.join(OUTCOMES)}")
    if outcome in {"PASS", "FAIL"}:
        if not actual.strip():
            raise QualificationError(f"{test}: outcome {outcome} requires the observed result")
        if not evidence:
            raise QualificationError(
                f"{test}: outcome {outcome} requires an evidence artifact. A claimed result with no "
                "artifact is an assertion"
            )
        if not operator.strip():
            raise QualificationError(f"{test}: outcome {outcome} requires the operator's name")
    if outcome == "NOT_RUN" and (actual.strip() or evidence):
        raise QualificationError(
            f"{test}: NOT_RUN cannot carry a result or an artifact. A test that produced a result "
            "was run"
        )
    for value, where in ((notes, "notes"), (actual, "actual"), (expected, "expected")):
        if any(term in value.casefold() for term in ("certified", "certification", "certify")):
            raise QualificationError(
                f"{test}: {where} uses a certification claim. Use 'tested', 'qualified for pilot' "
                "or 'supported based on evidence'"
            )

    state = json.loads(statePath.read_text(encoding="utf-8")) if statePath and statePath.is_file() else load_state()
    state.setdefault("tests", {})[test] = {
        "test": test,
        "startedAt": startedAt or _now(),
        "completedAt": _now(),
        "operator": operator,
        "expectedResult": expected,
        "actualResult": actual,
        "outcome": outcome,
        "evidenceReference": evidence,
        "notes": notes,
        "logs": logs,
        "redactionState": redaction,
    }
    save_state(state, path=statePath)
    return state["tests"][test]


def build_report(
    *,
    operator: str,
    recoveryMedia: Path | None = None,
    statePath: Path | None = None,
) -> dict[str, Any]:
    """Assemble a submittable collection, with the digest a signature covers."""
    collection = collect(recoveryMedia=recoveryMedia, statePath=statePath)
    state = json.loads(statePath.read_text(encoding="utf-8")) if statePath and statePath.is_file() else load_state()
    tests = [state.get("tests", {}).get(name) for name in GUIDED_TESTS]
    guided = [
        item if item else {"test": name, "outcome": "NOT_RUN", "redactionState": "not-required"}
        for name, item in zip(GUIDED_TESTS, tests)
    ]
    body = {
        "schemaVersion": 1,
        "collectionId": f"collection-{collection['collectedAt'].replace(':', '').replace('-', '')}",
        "submittedBy": operator,
        "collected": collection["collected"],
        "guidedTests": guided,
    }
    serialised = json.dumps(body, indent=2, sort_keys=True)
    body["reportDigest"] = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
    not_run = [item["test"] for item in guided if item.get("outcome") == "NOT_RUN"]
    body["notRunTests"] = not_run
    body["complete"] = not not_run
    return body


def add_arguments(subparsers: Any) -> None:
    """Attach the ``qualification`` command group to the bunny-os CLI."""
    group = subparsers.add_parser("qualification")
    commands = group.add_subparsers(dest="qualification_command", required=True)

    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--recovery-media", type=Path)
    collect_parser.add_argument("--state", type=Path)
    collect_parser.add_argument("--output", type=Path)

    commands.add_parser("tests")

    record = commands.add_parser("record")
    record.add_argument("--test", required=True, choices=GUIDED_TESTS)
    record.add_argument("--outcome", required=True, choices=OUTCOMES)
    record.add_argument("--operator", default="")
    record.add_argument("--expected", default="")
    record.add_argument("--actual", default="")
    record.add_argument("--evidence")
    record.add_argument("--notes", default="")
    record.add_argument("--log", action="append", default=[])
    record.add_argument("--redaction", choices=("not-required", "completed", "pending"), default="not-required")
    record.add_argument("--started-at")
    record.add_argument("--state", type=Path)

    report = commands.add_parser("report")
    report.add_argument("--operator", required=True)
    report.add_argument("--recovery-media", type=Path)
    report.add_argument("--state", type=Path)
    report.add_argument("--output", type=Path)


def dispatch(args: argparse.Namespace) -> Any:
    """Handle a ``qualification`` subcommand, returning the value to emit."""
    if args.qualification_command == "collect":
        value = collect(recoveryMedia=args.recovery_media, statePath=args.state)
    elif args.qualification_command == "tests":
        value = {
            "guidedTests": list(GUIDED_TESTS),
            "outcomes": list(OUTCOMES),
            "note": "NOT_RUN is never converted to PASS. A test with no artifact cannot be PASS.",
        }
    elif args.qualification_command == "record":
        value = record_test(
            test=args.test,
            outcome=args.outcome,
            operator=args.operator,
            expected=args.expected,
            actual=args.actual,
            evidence=args.evidence,
            notes=args.notes,
            logs=list(args.log),
            redaction=args.redaction,
            startedAt=args.started_at,
            statePath=args.state,
        )
    elif args.qualification_command == "report":
        value = build_report(
            operator=args.operator, recoveryMedia=args.recovery_media, statePath=args.state
        )
    else:  # pragma: no cover
        raise QualificationError(f"unhandled qualification command {args.qualification_command!r}")

    output = getattr(args, "output", None)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


__all__ = [
    "COLLECTOR_FIELDS",
    "COLLECTOR_VERSION",
    "EXCLUDED_CATEGORIES",
    "GUIDED_TESTS",
    "OUTCOMES",
    "QualificationError",
    "add_arguments",
    "build_report",
    "collect",
    "dispatch",
    "record_test",
]

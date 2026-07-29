#!/usr/bin/python3
"""Host-only microbenchmarks for deterministic installer planning code."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer.plans.validation import validate_plan
from installer.storage.models import parse_lsblk
from installer.storage.planning import automatic_plan


FIXTURE = json.loads((ROOT / "tests/installer/fixtures/storage-fixtures.json").read_text(encoding="utf-8"))["fixtures"]["windows_uefi"]


def measure(function, iterations: int = 500) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    ordered = sorted(samples)
    return {"medianMs": round(statistics.median(ordered), 4), "p95Ms": round(ordered[int(len(ordered) * 0.95) - 1], 4), "maxMs": round(max(ordered), 4)}


def main() -> int:
    disk = parse_lsblk(FIXTURE)[0]
    compact = automatic_plan(disk, mode="install_alongside", encryption=True, free_start_bytes=180 * 1024**3, free_size_bytes=70 * 1024**3)
    full_plan = {
        "schemaVersion": 1,
        "installationId": "install-performance",
        "mode": compact["mode"],
        "targetDisk": {key: compact["targetDisk"][key] for key in ("id", "devicePath", "expectedSizeBytes")},
        "partitions": compact["partitions"],
        "encryption": {**compact["encryption"], "tpm2": False},
        "boot": compact["boot"],
        "user": {"username": "alice", "displayName": "Alice", "administrator": True, "passwordSecretRef": "installer-secret:abcdefghijklmnop", "autologin": False, "groups": []},
        "locale": {"language": "en_US.UTF-8", "keyboard": "us", "timezone": "America/New_York"},
        "network": {"required": False, "migrateLiveConnection": False},
        "recovery": {"installDeployment": True, "recoveryKeyAcknowledged": True},
        "applicationProfile": "offline-essential",
    }
    result = {
        "schemaVersion": 1,
        "scope": "Windows host deterministic source only; no disk, GTK, Anaconda, deployment, boot, application install, or update timing",
        "diskParse": measure(lambda: parse_lsblk(FIXTURE)),
        "partitionPlan": measure(lambda: automatic_plan(disk, mode="install_alongside", encryption=True, free_start_bytes=180 * 1024**3, free_size_bytes=70 * 1024**3)),
        "protocolPlanValidation": measure(lambda: validate_plan(full_plan, [disk])),
        "unmeasured": ["live boot", "installer startup", "real disk probe", "deployment", "first installed boot", "first-run launch", "Bunny Shell login", "application install", "update staging"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

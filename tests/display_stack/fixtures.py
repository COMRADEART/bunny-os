# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic dsq-1 evidence for the adversarial tests.

Every fixture builds a *valid* evidence tree first and then applies exactly
one fraud. A test that starts from an invalid tree proves nothing about the
check it targets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "qualification" / "display-stack" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dsq_context  # noqa: E402
from run_boot import CELLS  # noqa: E402

AUTHORITY = {name: f"test-{name}" for name in dsq_context.AUTHORITY_FIELDS}
AUTHORITY["scenarioVersion"] = "dsq-1"
ARTIFACT_DIGEST = "a" * 64
AUTHORITY["installationArtifactDigest"] = ARTIFACT_DIGEST


class FakeContext:
    raw = dict(AUTHORITY)
    scenarioVersion = "dsq-1"
    installationArtifactDigest = ARTIFACT_DIGEST


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def healthy_analysis(boot_id: str, *, gdm_ok: bool = True,
                     screencast_failed: bool = False,
                     sessions: dict | None = None) -> dict:
    system_units = [{
        "unit": "gdm.service", "scope": "system", "uid": None,
        "uidHadSession": None, "rawNames": ["gdm.service"],
        "disposition": "activated-and-succeeded" if gdm_ok
                       else "currently-failed",
        "failures": 0 if gdm_ok else 1,
        "failuresDuringBoot": 0 if gdm_ok else 1,
        "failuresDuringShutdown": 0,
        "started": 1 if gdm_ok else 0,
        "result": None if gdm_ok else "exit-code",
        "mainExit": None, "restartCounterMax": 0, "skipped": [],
        "activeEnterMono": 7.4, "inactiveEnterMono": None,
        "events": [] if gdm_ok else [
            {"kind": "failed", "monotonic": 10.2, "detail": "exit-code"}],
    }]
    user_units = []
    if screencast_failed:
        user_units.append({
            "unit": "dbus-:*-org.gnome.Shell.Screencast@0.service",
            "scope": "user", "uid": "60578", "uidHadSession": True,
            "rawNames": ["dbus-:1.2-org.gnome.Shell.Screencast@0.service"],
            "disposition": "currently-failed", "failures": 1,
            "failuresDuringBoot": 1, "failuresDuringShutdown": 0,
            "started": 1, "result": "exit-code",
            "mainExit": {"code": "exited", "status": "1"},
            "restartCounterMax": 0, "skipped": [], "activeEnterMono": 11.3,
            "inactiveEnterMono": 11.9,
            "events": [{"kind": "failed", "monotonic": 11.9,
                        "detail": "exit-code"}],
        })
    return {
        "failedUnitCollectorVersion": AUTHORITY["failedUnitCollectorVersion"],
        "bootId": boot_id,
        "entryCount": 4200,
        "parseErrors": 0,
        "wallClock": {"first": 1e9, "last": 1e9 + 120},
        "graphicalTargetReachedMono": 7.56,
        "shutdownInitiatedMono": 84.0,
        "seat0CreatedMono": 7.33,
        "healthCheckFinishedMono": 7.55,
        "timeline": {"gdmActive": 7.47, "authselectApplyStart": 7.1,
                     "authselectApplyEnd": 7.3},
        "sessionsByUid": sessions if sessions is not None
                         else {"60578": ["pam:gnome-initial-setup"]},
        "systemUnits": system_units,
        "userUnits": user_units,
        "failedSystemUnits": [] if gdm_ok else ["gdm.service"],
        "shutdownFailedSystemUnits": [],
        "recoveredSystemUnits": [],
        "failedUserUnits": (
            ["uid=60578:dbus-:*-org.gnome.Shell.Screencast@0.service"]
            if screencast_failed else []),
        "shutdownFailedUserUnits": [],
        "dependencyFailures": [],
        "coredumps": [],
        "kernelGraphicsErrors": [],
        "gdm": {
            "gdmReachedActive": gdm_ok,
            "gdmFailures": 0 if gdm_ok else 1,
            "gdmBootPhaseFailures": 0 if gdm_ok else 1,
            "gdmShutdownPhaseFailures": 0,
            "gdmRestartCounterMax": 0,
            "greeterSessionOpenedMono": 7.72 if gdm_ok else None,
            "sessionNeverRegisteredMono": None if gdm_ok else 10.2,
            "fatalDisplayErrors": [],
            "gdmCoredumps": [],
        },
    }


def write_run(evidence_root: Path, cell: str, sequence: int,
              boot_id: str, **analysis_kwargs) -> Path:
    run_dir = evidence_root / f"DSQ-20260801-cell{cell}-{sequence:03d}"
    run_dir.mkdir(parents=True)
    serial = b"Reached target graphical.target - Graphical Interface.\n"
    (run_dir / "serial.log").write_bytes(serial)
    record = {
        "schemaVersion": 1,
        "runId": run_dir.name,
        "cell": cell,
        "seeding": False,
        "sequence": sequence,
        "cellConfiguration": dict(CELLS[cell]),
        "authority": dict(AUTHORITY),
        "artifact": {"name": "bunny-os-test.qcow2", "sha256": ARTIFACT_DIGEST},
        "status": "COLLECTED",
        "liveOutcome": "observed",
        "observationWindowCompleted": True,
        "guestResetCount": CELLS[cell]["expectedResets"],
        "expectedResets": CELLS[cell]["expectedResets"],
        "shutdownMethod": "acpi-powerdown",
        "collection": {"status": "ok", "bootId": boot_id,
                       "bootsInJournal": 1},
        "analysis": healthy_analysis(boot_id, **analysis_kwargs),
        "limitations": [],
        "evidenceManifest": [{"path": "serial.log",
                              "sha256": sha256_bytes(serial),
                              "sizeBytes": len(serial)}],
    }
    (run_dir / "record.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return run_dir


def edit_record(run_dir: Path, mutate) -> None:
    record_path = run_dir / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutate(record)
    record_path.write_text(json.dumps(record, indent=2) + "\n",
                           encoding="utf-8")


def full_tree(evidence_root: Path, per_cell: dict[str, int] | None = None) -> None:
    per_cell = per_cell or {"A": 3, "B": 2, "C": 2, "D": 2, "E": 2}
    boot = 0
    for cell, count in per_cell.items():
        for sequence in range(1, count + 1):
            boot += 1
            write_run(evidence_root, cell, sequence, f"boot{boot:032d}"[-32:])

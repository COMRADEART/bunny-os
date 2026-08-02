#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create qualification/display-stack/evidence-context.json — Commit M's
diagnostic authority. Every digest is measured here, on the machine the
matrix will run on, from the exact artifacts it will use."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from dsq_context import (  # noqa: E402
    CONTEXT_PATH,
    FAILED_UNIT_COLLECTOR_VERSION,
    JOURNAL_COLLECTOR_VERSION,
    ROOT,
    SCENARIO_VERSION,
    sha256_file,
)

ARTIFACT = Path("/var/tmp/bunny-installables-g/bunny-os-b9c317d35b85.qcow2")
TPM_CONTEXT = ROOT / "qualification/tpm/evidence-context.json"


def rpm_of(binary: str) -> str:
    path = shutil.which(binary)
    result = subprocess.run(["rpm", "-qf", path], capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def main() -> int:
    tpm = json.loads(TPM_CONTEXT.read_text(encoding="utf-8"))
    qemu = Path(shutil.which("qemu-system-x86_64"))
    swtpm = Path(shutil.which("swtpm"))
    ovmf_code = Path(tpm["ovmfCodePath"])
    ovmf_vars = Path(tpm["ovmfVarsTemplatePath"])
    context = {
        "schemaVersion": 1,
        "scenarioVersion": SCENARIO_VERSION,
        "sourceCommit": tpm["sourceCommit"],
        "sourceArchiveDigest": tpm["sourceArchiveDigest"],
        "installationArtifactDigest": sha256_file(ARTIFACT),
        "installationArtifactName": ARTIFACT.name,
        "qemuDigest": sha256_file(qemu),
        "qemuVersion": subprocess.run(
            ["qemu-system-x86_64", "--version"], capture_output=True,
            text=True, check=True).stdout.splitlines()[0],
        "qemuPackage": rpm_of("qemu-system-x86_64"),
        "ovmfCodeDigest": sha256_file(ovmf_code),
        "ovmfCodePath": str(ovmf_code),
        "ovmfVarsTemplateDigest": sha256_file(ovmf_vars),
        "ovmfVarsTemplatePath": str(ovmf_vars),
        "ovmfPackage": tpm["ovmfPackage"],
        "swtpmDigest": sha256_file(swtpm),
        "swtpmVersion": tpm["swtpmVersion"],
        "swtpmPackage": tpm["swtpmPackage"],
        "machineType": tpm["machineType"],
        "cpuMode": tpm["cpuMode"],
        "resourceAllocation": {"vcpus": 4, "memoryMiB": 8192},
        "reducedResourceAllocation": {"vcpus": 2, "memoryMiB": 4096},
        "tpmConfiguration": {
            "cellA": "absent", "cellB": "crb, state reused, vars reused",
            "cellC": "crb, state fresh, vars fresh", "cellD": "absent",
            "cellE": "absent"},
        "networkConfiguration": {
            "default": "user-mode virtio-net-pci",
            "cellE": "-nic none (disconnected at the VM boundary)"},
        "bootTimeoutSeconds": 600,
        "observationWindowSeconds": 75,
        "failedUnitCollectorVersion": FAILED_UNIT_COLLECTOR_VERSION,
        "journalCollectorVersion": JOURNAL_COLLECTOR_VERSION,
        "notes": ("Authority for every display-stack reliability record. "
                  "Records from tpmq-1 or installed-system scenarios may "
                  "inform hypotheses but cannot fill a dsq-1 matrix cell. "
                  "A record naming any other artifact, firmware, emulator "
                  "or collector version is stale and must be refused."),
    }
    CONTEXT_PATH.write_text(json.dumps(context, indent=2) + "\n",
                            encoding="utf-8")
    print(f"wrote {CONTEXT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

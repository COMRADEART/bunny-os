#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The display-stack reliability evidence context: one resolver, one authority.

Same discipline as tpm_context, for scenario dsq-1: every boot record binds
to exactly which disk was booted, under which firmware, on which emulator,
observed by which collector versions. ``resolve_context()`` re-derives every
digest whose subject is present on this system and refuses a mismatch; the
installation artifact digest is verified by the runner against the file it
is told to boot, before every single run.

Collector versions are part of the authority: a record produced by an older
failed-unit or journal collector is evidence about that collector's view,
not this one's, and cannot fill a dsq-1 matrix cell.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

__all__ = [
    "CONTEXT_PATH",
    "AUTHORITY_FIELDS",
    "SCENARIO_VERSION",
    "FAILED_UNIT_COLLECTOR_VERSION",
    "JOURNAL_COLLECTOR_VERSION",
    "DsqContext",
    "ContextError",
    "resolve_context",
    "verify_record_binding",
    "sha256_file",
]

ROOT = Path(__file__).resolve().parents[3]
CONTEXT_PATH = ROOT / "qualification/display-stack/evidence-context.json"

SCENARIO_VERSION = "dsq-1"
#: Version of the per-boot unit-disposition logic in journal_analysis.py.
#: Bump on any change to how a unit's state is classified. v1 read only
#: UNIT and missed every user-manager unit; its records are retained under
#: evidence/invalidated/ and can fill no dsq-1 cell.
FAILED_UNIT_COLLECTOR_VERSION = "dsq-failed-units-2"
#: Version of the offline journal extraction in run_boot.py. Bump on any
#: change to what is collected or how the boot is selected.
JOURNAL_COLLECTOR_VERSION = "dsq-journal-1"

AUTHORITY_FIELDS = (
    "scenarioVersion",
    "sourceCommit",
    "sourceArchiveDigest",
    "installationArtifactDigest",
    "qemuDigest",
    "ovmfCodeDigest",
    "ovmfVarsTemplateDigest",
    "swtpmDigest",
    "machineType",
    "cpuMode",
    "failedUnitCollectorVersion",
    "journalCollectorVersion",
)


class ContextError(RuntimeError):
    """The evidence context does not describe this machine."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DsqContext:
    raw: Mapping[str, Any]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.raw[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def resolve_context(verify: bool = True) -> DsqContext:
    if not CONTEXT_PATH.exists():
        raise ContextError(f"{CONTEXT_PATH} does not exist")
    raw = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    context = DsqContext(raw)
    if not verify:
        return context
    problems: list[str] = []
    qemu = shutil.which("qemu-system-x86_64")
    if qemu is None:
        problems.append("qemu-system-x86_64 not on PATH")
    elif sha256_file(Path(qemu)) != raw["qemuDigest"]:
        problems.append(f"qemu binary digest differs from context "
                        f"({sha256_file(Path(qemu))[:12]})")
    swtpm = shutil.which("swtpm")
    if swtpm is None:
        problems.append("swtpm not on PATH")
    elif sha256_file(Path(swtpm)) != raw["swtpmDigest"]:
        problems.append("swtpm binary digest differs from context")
    for key, path_key in (("ovmfCodeDigest", "ovmfCodePath"),
                          ("ovmfVarsTemplateDigest", "ovmfVarsTemplatePath")):
        path = Path(raw[path_key])
        if not path.exists():
            problems.append(f"{path} does not exist")
        elif sha256_file(path) != raw[key]:
            problems.append(f"{path} digest differs from context")
    if problems:
        raise ContextError("; ".join(problems))
    return context


def verify_record_binding(record: Mapping[str, Any],
                          context: DsqContext) -> list[str]:
    """Every authority field a record carries must match the context."""
    problems = []
    binding = record.get("authority", {})
    for field_name in AUTHORITY_FIELDS:
        expected = context.raw.get(field_name)
        actual = binding.get(field_name)
        if actual != expected:
            problems.append(
                f"{field_name}: record has {actual!r}, context has {expected!r}")
    return problems


def qemu_version() -> str:
    return subprocess.run(["qemu-system-x86_64", "--version"],
                          capture_output=True, text=True,
                          check=True).stdout.splitlines()[0]

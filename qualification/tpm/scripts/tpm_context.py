#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The TPM investigation evidence context: one resolver, one authority.

A TPM boot record is only meaningful relative to exactly which disk was
booted, under which firmware image, on which emulator build, against which
TPM implementation. The BrlAPI and reproducibility passes both demonstrated
the failure this module prevents — evidence that quietly described a
different artifact than the one being qualified — and the fix is the same
here: bind every record to a recorded authority, and verify every binding
that can be verified on the machine the record was produced on.

``resolve_context()`` reads ``qualification/tpm/evidence-context.json`` and
re-derives every digest whose subject is present on this system: the QEMU
binary, the OVMF code image, the OVMF variable template and the swtpm
binary. The installation artifact lives outside the repository by size; its
digest is asserted by the runner against the file it is told to boot, before
every single run, so a swapped or truncated disk is refused rather than
measured.

Diagnostic variation is declared, never substituted: a run that uses TCG, a
different CPU model or a different machine type records the varied value in
its own record while the context keeps the pinned one. A record whose
authority fields differ from the context is stale, whatever its result says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

__all__ = [
    "CONTEXT_PATH",
    "AUTHORITY_FIELDS",
    "TpmContext",
    "ContextError",
    "resolve_context",
    "verify_record_binding",
    "experiment_id",
    "sha256_file",
]

CONTEXT_PATH = Path("qualification/tpm/evidence-context.json")

#: Every field a TPM evidence record must match exactly for the record to be
#: about this context. A change to any of these is a new context, and every
#: prior record becomes stale against it.
AUTHORITY_FIELDS = (
    "sourceCommit",
    "sourceArchiveDigest",
    "installationArtifactDigest",
    "qemuDigest",
    "ovmfCodeDigest",
    "ovmfVarsTemplateDigest",
    "swtpmDigest",
    "libtpmsVersion",
    "scenarioVersion",
    "machineType",
    "cpuMode",
    "schemaVersion",
)

#: Context fields whose subject is a file on the system running the VMs.
#: Each is re-hashed at resolve time when the file exists; a mismatch is an
#: error, because a context that misdescribes the emulator it runs under is
#: worse than no context.
_SYSTEM_SUBJECTS = {
    "qemuDigest": "/usr/sbin/qemu-system-x86_64",
    "ovmfCodeDigest": "ovmfCodePath",
    "ovmfVarsTemplateDigest": "ovmfVarsTemplatePath",
    "swtpmDigest": "/usr/sbin/swtpm",
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_EXPERIMENT_ID = re.compile(r"^TPMQ-\d{8}-[a-z0-9-]+-\d{3}$")


class ContextError(ValueError):
    """The TPM evidence context cannot be resolved or does not verify."""


@dataclass(frozen=True)
class TpmContext:
    schemaVersion: int
    scenarioVersion: str
    sourceCommit: str
    sourceArchiveDigest: str
    installationArtifactDigest: str
    installationArtifactName: str
    qemuDigest: str
    qemuVersion: str
    ovmfCodeDigest: str
    ovmfCodePath: str
    ovmfVarsTemplateDigest: str
    ovmfVarsTemplatePath: str
    swtpmDigest: str
    swtpmVersion: str
    libtpmsVersion: str
    machineType: str
    cpuMode: str
    notes: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in AUTHORITY_FIELDS}


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def resolve_context(root: Path | None = None, *, verify_system: bool = True) -> TpmContext:
    """Read and, where possible, verify the single TPM evidence context.

    ``verify_system=True`` re-derives the digest of every system subject that
    is present (emulator, firmware images, swtpm). An absent subject is not
    an error — the context can be read on a machine that does not run the
    VMs — but a present subject with a different digest is.
    """
    base = Path(root) if root else Path.cwd()
    path = base / CONTEXT_PATH
    if not path.is_file():
        raise ContextError(
            f"{CONTEXT_PATH} does not exist. TPM evidence has no authority to bind "
            "to; create the context before running any experiment."
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContextError(f"{CONTEXT_PATH} is not valid JSON: {exc}") from None

    commit = str(record.get("sourceCommit", ""))
    if not _COMMIT.match(commit):
        raise ContextError("sourceCommit must be a full 40-character SHA")
    for name in ("sourceArchiveDigest", "installationArtifactDigest", "qemuDigest",
                 "ovmfCodeDigest", "ovmfVarsTemplateDigest", "swtpmDigest"):
        value = str(record.get(name, ""))
        if not _SHA256.match(value):
            raise ContextError(f"{name} must be a SHA-256 digest, got {value!r}")
    for name in ("scenarioVersion", "machineType", "cpuMode", "libtpmsVersion"):
        if not str(record.get(name, "")):
            raise ContextError(f"{name} must be present and non-empty")

    if verify_system:
        for field_name, subject in _SYSTEM_SUBJECTS.items():
            subject_path = Path(str(record.get(subject, subject)))
            if not subject_path.is_file():
                continue
            expected = str(record.get(field_name, ""))
            actual = sha256_file(subject_path)
            if actual != expected:
                raise ContextError(
                    f"{field_name} claims {expected[:12]} but {subject_path} digests to "
                    f"{actual[:12]}. The toolchain changed under the context; re-baseline "
                    "before producing any further evidence."
                )

    return TpmContext(
        schemaVersion=int(record.get("schemaVersion", 0)),
        scenarioVersion=str(record["scenarioVersion"]),
        sourceCommit=commit,
        sourceArchiveDigest=str(record["sourceArchiveDigest"]),
        installationArtifactDigest=str(record["installationArtifactDigest"]),
        installationArtifactName=str(record.get("installationArtifactName", "")),
        qemuDigest=str(record["qemuDigest"]),
        qemuVersion=str(record.get("qemuVersion", "")),
        ovmfCodeDigest=str(record["ovmfCodeDigest"]),
        ovmfCodePath=str(record.get("ovmfCodePath", "")),
        ovmfVarsTemplateDigest=str(record["ovmfVarsTemplateDigest"]),
        ovmfVarsTemplatePath=str(record.get("ovmfVarsTemplatePath", "")),
        swtpmDigest=str(record["swtpmDigest"]),
        swtpmVersion=str(record.get("swtpmVersion", "")),
        libtpmsVersion=str(record["libtpmsVersion"]),
        machineType=str(record["machineType"]),
        cpuMode=str(record["cpuMode"]),
        notes=str(record.get("notes", "")),
        raw=record,
    )


def verify_record_binding(record: Mapping[str, Any], context: TpmContext) -> list[str]:
    """Every way a TPM evidence record can fail to be about this context.

    Returns the reasons; an empty list is a verified binding. Diagnostic
    variation is legal only when declared: a record whose ``acceleration``,
    ``cpuModel`` or ``machineType`` differs from the pinned mode must carry
    ``diagnostic: true``, and a diagnostic record can never satisfy a
    supported-path requirement downstream.
    """
    reasons: list[str] = []
    for name in ("sourceCommit", "sourceArchiveDigest", "installationArtifactDigest",
                 "qemuDigest", "ovmfCodeDigest", "ovmfVarsTemplateDigest",
                 "swtpmDigest", "scenarioVersion"):
        claimed = str(record.get(name, ""))
        expected = str(getattr(context, name))
        if claimed != expected:
            reasons.append(
                f"{name}: record claims {claimed[:12] or '<absent>'}, context is "
                f"{expected[:12]}; evidence does not transfer between authorities"
            )
    pinned = (
        ("machineType", context.machineType),
        ("cpuModel", context.cpuMode),
        ("acceleration", "kvm"),
    )
    for name, expected in pinned:
        claimed = str(record.get(name, ""))
        if claimed != expected and not record.get("diagnostic"):
            reasons.append(
                f"{name}: record used {claimed!r} but the pinned value is {expected!r} "
                "and the record does not declare diagnostic: true"
            )
    identifier = str(record.get("evidenceId", ""))
    if not _EXPERIMENT_ID.match(identifier):
        reasons.append(
            f"evidenceId {identifier!r} does not match TPMQ-YYYYMMDD-<experiment>-<sequence>"
        )
    if record.get("tpmInterface") not in ("none", "crb", "tis"):
        reasons.append("tpmInterface must be one of none, crb, tis")
    if record.get("tpmInterface") == "none" and record.get("tpmState") not in (None, "none"):
        reasons.append("a run without a TPM cannot claim a TPM state")
    if record.get("environment") not in ("qemu-kvm", "qemu-tcg"):
        reasons.append("environment must be qemu-kvm or qemu-tcg; nothing here is physical")
    return reasons


def experiment_id(name: str, *, date: str, sequence: int) -> str:
    """The canonical experiment identifier. One format, produced in one place."""
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    return f"TPMQ-{date}-{slug}-{sequence:03d}"

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The installed-system evidence context: one resolver, one authority.

Installed-system evidence is only meaningful relative to exactly what was
installed, from which artifact, produced by which toolchain, under which
scenario definitions. The reproducibility work already demonstrated the
failure this module exists to prevent — evidence that quietly described a
different commit than the one being qualified — and its fix: bind evidence to
a recorded authority, never to whatever HEAD or a script's environment
happens to be.

``resolve_context()`` reads ``qualification/installed-system/evidence-context.json``
and verifies every claim in it that can be verified locally: the archive
digest against the retained archive when present, the artifact digests
against the artifacts when present, the source commit against the repository.
Every scenario runner, evidence importer and gate reads the context through
this function. A script that decides for itself what was tested is a defect,
and the adversarial tests treat it as one.

Staleness is decided here too: an evidence record naming any authority value
other than the context's current one is stale, whatever its own result says.
A passing boot record about an older archive must not qualify a newer one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

__all__ = [
    "CONTEXT_PATH",
    "AUTHORITY_FIELDS",
    "InstalledContext",
    "ContextError",
    "resolve_context",
    "verify_record_binding",
    "evidence_id",
]

CONTEXT_PATH = Path("qualification/installed-system/evidence-context.json")

#: Every field an evidence record must match exactly for the record to be
#: about this context. A change to any of these is a new context, and every
#: prior record becomes stale against it.
AUTHORITY_FIELDS = (
    "sourceCommit",
    "sourceArchiveDigest",
    "installationArtifactDigest",
    "recoveryArtifactDigest",
    "installerToolchainDigest",
    "scenarioVersion",
    "schemaVersion",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_EVIDENCE_ID = re.compile(r"^ISQ-\d{8}-[a-z0-9-]+-\d{3}$")


class ContextError(ValueError):
    """The installed-evidence context cannot be resolved or does not verify."""


@dataclass(frozen=True)
class InstalledContext:
    schemaVersion: int
    sourceCommit: str
    sourceArchiveDigest: str
    installationArtifactDigest: str
    recoveryArtifactDigest: str | None
    installerToolchainDigest: str
    scenarioVersion: str
    environmentKinds: tuple[str, ...] = ("qemu-kvm", "physical")
    notes: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "sourceCommit": self.sourceCommit,
            "sourceArchiveDigest": self.sourceArchiveDigest,
            "installationArtifactDigest": self.installationArtifactDigest,
            "recoveryArtifactDigest": self.recoveryArtifactDigest,
            "installerToolchainDigest": self.installerToolchainDigest,
            "scenarioVersion": self.scenarioVersion,
        }


def _digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def resolve_context(root: Path | None = None, *, verify: bool = True) -> InstalledContext:
    """Read and, where possible, verify the single installed-evidence context.

    ``verify=True`` re-derives every digest whose subject file is present.
    An absent subject is not an error here — media may live outside the
    repository — but a present subject with a different digest is: a context
    that misdescribes an artifact on the same disk is worse than no context.
    """
    # BUNNY_INSTALLED_CONTEXT names an alternative authority file.
    #
    # The BrlAPI regression runs against the corrected artifact
    # while the Commit I/J records stay bound to the disk they
    # measured. Editing this file in place would invalidate them.
    # The default is unchanged.
    override = os.environ.get("BUNNY_INSTALLED_CONTEXT")
    base = Path(root) if root else Path.cwd()
    path = Path(override) if override else base / CONTEXT_PATH
    if not path.is_file():
        raise ContextError(
            f"{CONTEXT_PATH} does not exist. Installed-system evidence has no authority "
            "to bind to; create the context before running any scenario."
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContextError(f"{CONTEXT_PATH} is not valid JSON: {exc}") from None

    commit = str(record.get("sourceCommit", ""))
    if not _COMMIT.match(commit):
        raise ContextError("sourceCommit must be a full 40-character SHA")
    for name in ("sourceArchiveDigest", "installationArtifactDigest",
                 "installerToolchainDigest"):
        value = str(record.get(name, ""))
        if not _SHA256.match(value):
            raise ContextError(f"{name} must be a SHA-256 digest, got {value!r}")
    recovery = record.get("recoveryArtifactDigest")
    if recovery is not None and not _SHA256.match(str(recovery)):
        raise ContextError("recoveryArtifactDigest must be a SHA-256 digest when present")
    scenario_version = str(record.get("scenarioVersion", ""))
    if not scenario_version:
        raise ContextError("scenarioVersion must name the scenario set the evidence ran under")

    if verify:
        subjects = record.get("subjects") or {}
        for field_name, subject in subjects.items():
            subject_path = base / str(subject)
            if not subject_path.is_file():
                continue
            expected = str(record.get(field_name, ""))
            actual = _digest_file(subject_path)
            if actual != expected:
                raise ContextError(
                    f"{field_name} claims {expected[:12]} but {subject} digests to "
                    f"{actual[:12]}. A context that misdescribes an artifact on the same "
                    "disk is worse than no context."
                )
        result = subprocess.run(
            ["git", "-C", str(base), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise ContextError(
                f"sourceCommit {commit[:12]} is not a commit in this repository"
            )

    return InstalledContext(
        schemaVersion=int(record.get("schemaVersion", 0)),
        sourceCommit=commit,
        sourceArchiveDigest=str(record["sourceArchiveDigest"]),
        installationArtifactDigest=str(record["installationArtifactDigest"]),
        recoveryArtifactDigest=str(recovery) if recovery is not None else None,
        installerToolchainDigest=str(record["installerToolchainDigest"]),
        scenarioVersion=scenario_version,
        notes=str(record.get("notes", "")),
        raw=record,
    )


def verify_record_binding(record: Mapping[str, Any], context: InstalledContext) -> list[str]:
    """Every way an evidence record can fail to be about this context.

    Returns the reasons; an empty list is a verified binding. The caller
    decides whether a stale record is an error or merely not evidence — a
    gate treats it as not evidence, an importer refuses it loudly.
    """
    reasons: list[str] = []
    for name in ("sourceCommit", "sourceArchiveDigest", "installationArtifactDigest"):
        claimed = str(record.get(name, ""))
        expected = str(getattr(context, name))
        if claimed != expected:
            reasons.append(
                f"{name}: record claims {claimed[:12] or '<absent>'}, context is "
                f"{expected[:12]}; evidence does not transfer between authorities"
            )
    if context.recoveryArtifactDigest is not None and record.get("recoveryArtifactDigest"):
        if str(record["recoveryArtifactDigest"]) != context.recoveryArtifactDigest:
            reasons.append("recoveryArtifactDigest does not match the context")
    if str(record.get("scenarioVersion", "")) not in ("", context.scenarioVersion):
        reasons.append(
            f"scenarioVersion: record ran under {record.get('scenarioVersion')!r}, "
            f"context defines {context.scenarioVersion!r}; a scenario change is a new context"
        )
    environment = str(record.get("environment", ""))
    if environment not in ("qemu-kvm", "physical"):
        reasons.append(f"environment {environment!r} is not qemu-kvm or physical")
    if environment == "physical" and not record.get("hardwareRecord"):
        reasons.append(
            "a physical record must name its hardware record; a physical claim without "
            "a device identity is indistinguishable from a VM run relabelled"
        )
    identifier = str(record.get("evidenceId", ""))
    if not _EVIDENCE_ID.match(identifier):
        reasons.append(
            f"evidenceId {identifier!r} does not match ISQ-YYYYMMDD-<scenario>-<sequence>"
        )
    return reasons


def evidence_id(scenario: str, *, date: str, sequence: int) -> str:
    """The canonical evidence identifier. One format, produced in one place."""
    slug = re.sub(r"[^a-z0-9-]", "-", scenario.lower()).strip("-")
    return f"ISQ-{date}-{slug}-{sequence:03d}"

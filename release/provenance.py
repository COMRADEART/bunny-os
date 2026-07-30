# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verification of build provenance downloaded from a CI system.

The failure this module exists to prevent is short: *trusting an artifact because
it came from GitHub Actions*. A downloaded artifact bundle is a tarball someone
uploaded. It carries whatever its uploader put in it, including a provenance file
claiming any commit, any base image and any digest.

So nothing in a provenance record is believed on its own. Every claim is either
recomputed from the files on disk, or checked against a value the verifier
already holds:

============================  ==============================================
Claim                         How it is checked
============================  ==============================================
artifact digests              recomputed from the downloaded bytes
source commit                 compared with the commit being qualified
base image digest             compared with the pinned digest, and must be pinned
repository and workflow       compared with the expected repository and path
run identity                  must be present, and must not be reused
freshness                     ``expiresAt`` in the past is rejected
verification environment      must differ from the builder's environment
============================  ==============================================

The last row matters more than it looks. Verifying a bundle inside the job that
produced it proves nothing about the bundle: the same compromised runner writes
the artifact and the verdict. So the verifier records where it ran, and refuses
when that is the environment that built the artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The repository whose workflows may produce qualification evidence.
EXPECTED_REPOSITORY = "COMRADEART/bunny-os"

#: The workflow that produces an independent builder record.
EXPECTED_WORKFLOW = ".github/workflows/independent-builder.yml"

_REQUIRED_FIELDS = (
    "schemaVersion",
    "repository",
    "workflow",
    "workflowRunId",
    "workflowRunAttempt",
    "runnerImage",
    "runnerArchitecture",
    "kernelVersion",
    "containerRuntime",
    "imageBuilderVersion",
    "sourceCommit",
    "baseImageDigest",
    "generatedAt",
    "artifacts",
)

_DIGEST_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_CHUNK = 1024 * 1024


class ProvenanceError(ValueError):
    """Raised when a provenance record is malformed."""


def _parse_time(value: Any, *, field: str) -> _datetime.datetime:
    try:
        stamp = _datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ProvenanceError(f"{field} must be an RFC 3339 timestamp") from None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_datetime.timezone.utc)
    return stamp


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ProvenanceRecord:
    schemaVersion: int
    repository: str
    workflow: str
    workflowRunId: str
    workflowRunAttempt: int
    runnerImage: str
    runnerArchitecture: str
    kernelVersion: str
    containerRuntime: str
    imageBuilderVersion: str
    sourceCommit: str
    baseImageDigest: str
    generatedAt: str
    artifacts: Mapping[str, str]
    dependencyLockHashes: Mapping[str, str]
    expiresAt: str | None = None
    workflowRef: str | None = None
    cacheDisabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "repository": self.repository,
            "workflow": self.workflow,
            "workflowRef": self.workflowRef,
            "workflowRunId": self.workflowRunId,
            "workflowRunAttempt": self.workflowRunAttempt,
            "runnerImage": self.runnerImage,
            "runnerArchitecture": self.runnerArchitecture,
            "kernelVersion": self.kernelVersion,
            "containerRuntime": self.containerRuntime,
            "imageBuilderVersion": self.imageBuilderVersion,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
            "generatedAt": self.generatedAt,
            "expiresAt": self.expiresAt,
            "cacheDisabled": self.cacheDisabled,
            "artifacts": dict(self.artifacts),
            "dependencyLockHashes": dict(self.dependencyLockHashes),
        }


def parse_provenance(record: Mapping[str, Any]) -> ProvenanceRecord:
    """Validate the shape of a provenance record. Says nothing about truth."""
    if not isinstance(record, Mapping):
        raise ProvenanceError("provenance record must be an object")
    missing = [name for name in _REQUIRED_FIELDS if record.get(name) in (None, "", {})]
    if missing:
        raise ProvenanceError(f"provenance record missing fields: {', '.join(sorted(missing))}")
    if int(record["schemaVersion"]) != SCHEMA_VERSION:
        raise ProvenanceError(f"provenance schemaVersion must be {SCHEMA_VERSION}")

    artifacts = record["artifacts"]
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ProvenanceError("provenance must list at least one artifact with its digest")
    for name, digest in artifacts.items():
        if not _SHA256.match(str(digest)):
            raise ProvenanceError(f"artifact {name!r} digest is not a SHA-256 hex string")

    if not _COMMIT.match(str(record["sourceCommit"])):
        raise ProvenanceError("provenance sourceCommit must be a full 40-character SHA")
    if not _DIGEST_PINNED.search(str(record["baseImageDigest"])):
        raise ProvenanceError(
            f"provenance baseImageDigest {record['baseImageDigest']!r} is not digest-pinned; a "
            "mutable tag does not identify the base a build consumed"
        )

    _parse_time(record["generatedAt"], field="generatedAt")
    if record.get("expiresAt"):
        _parse_time(record["expiresAt"], field="expiresAt")

    try:
        attempt = int(record["workflowRunAttempt"])
    except (TypeError, ValueError):
        raise ProvenanceError("workflowRunAttempt must be an integer") from None

    locks = record.get("dependencyLockHashes") or {}
    if not isinstance(locks, Mapping):
        raise ProvenanceError("dependencyLockHashes must be an object")

    return ProvenanceRecord(
        schemaVersion=SCHEMA_VERSION,
        repository=str(record["repository"]),
        workflow=str(record["workflow"]),
        workflowRunId=str(record["workflowRunId"]),
        workflowRunAttempt=attempt,
        runnerImage=str(record["runnerImage"]),
        runnerArchitecture=str(record["runnerArchitecture"]),
        kernelVersion=str(record["kernelVersion"]),
        containerRuntime=str(record["containerRuntime"]),
        imageBuilderVersion=str(record["imageBuilderVersion"]),
        sourceCommit=str(record["sourceCommit"]),
        baseImageDigest=str(record["baseImageDigest"]),
        generatedAt=str(record["generatedAt"]),
        artifacts={str(k): str(v) for k, v in artifacts.items()},
        dependencyLockHashes={str(k): str(v) for k, v in locks.items()},
        expiresAt=str(record["expiresAt"]) if record.get("expiresAt") else None,
        workflowRef=str(record["workflowRef"]) if record.get("workflowRef") else None,
        cacheDisabled=bool(record.get("cacheDisabled", False)),
    )


def verify_provenance(
    record: ProvenanceRecord,
    *,
    artifactRoot: Path,
    expectedCommit: str,
    expectedBaseDigest: str,
    verificationEnvironmentId: str,
    builderEnvironmentId: str,
    now: _datetime.datetime,
    consumedRunIds: Iterable[str] = (),
    expectedRepository: str = EXPECTED_REPOSITORY,
    expectedWorkflow: str = EXPECTED_WORKFLOW,
) -> dict[str, Any]:
    """Verify a provenance record against the bytes it describes.

    ``consumedRunIds`` names runs already accepted as evidence. Re-presenting one
    is the ``same CI run represented twice`` case: a single run cannot be both
    halves of a two-builder comparison.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "outcome": "PASS" if ok else "FAIL", "detail": detail})

    check(
        "repository",
        record.repository == expectedRepository,
        f"provenance names {record.repository!r}; expected {expectedRepository!r}",
    )
    check(
        "workflow",
        record.workflow == expectedWorkflow,
        f"provenance names {record.workflow!r}; expected {expectedWorkflow!r}",
    )
    check(
        "source-commit",
        record.sourceCommit == expectedCommit,
        f"provenance built {record.sourceCommit[:12]}; qualifying {expectedCommit[:12]}",
    )
    check(
        "base-image-digest",
        record.baseImageDigest == expectedBaseDigest,
        f"provenance base {record.baseImageDigest}; expected {expectedBaseDigest}",
    )
    check(
        "run-identity",
        bool(record.workflowRunId),
        f"workflow run {record.workflowRunId!r}, attempt {record.workflowRunAttempt}",
    )
    reused = record.workflowRunId in set(consumedRunIds)
    check(
        "run-not-reused",
        not reused,
        (
            f"run {record.workflowRunId} has already been accepted as evidence; one run cannot be "
            "two builders"
        )
        if reused
        else f"run {record.workflowRunId} has not been accepted before",
    )
    check(
        "mutable-cache-disabled",
        record.cacheDisabled,
        "the workflow declares mutable caches disabled"
        if record.cacheDisabled
        else "the workflow does not declare mutable caches disabled; a warm cache is an unrecorded build input",
    )

    independent_environment = (
        bool(verificationEnvironmentId)
        and verificationEnvironmentId != builderEnvironmentId
    )
    check(
        "separate-verification-environment",
        independent_environment,
        (
            f"verified in {verificationEnvironmentId!r}, built in {builderEnvironmentId!r}"
            if independent_environment
            else "verification ran in the environment that produced the artifact; the same host "
            "cannot both build and attest"
        ),
    )

    if record.expiresAt:
        expiry = _parse_time(record.expiresAt, field="expiresAt")
        fresh = expiry > now
        check(
            "not-expired",
            fresh,
            f"expired at {record.expiresAt}" if not fresh else f"valid until {record.expiresAt}",
        )
    else:
        check(
            "not-expired",
            False,
            "provenance carries no expiresAt; evidence without an expiry cannot be shown to be fresh",
        )

    # Checksums, recomputed. This is the only check that reads the artifacts.
    absent: list[str] = []
    mismatched: list[str] = []
    verified: list[str] = []
    root = Path(artifactRoot)
    for name, expected in sorted(record.artifacts.items()):
        target = (root / name).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            mismatched.append(f"{name}: path escapes the artifact root")
            continue
        if not target.is_file():
            absent.append(name)
            continue
        actual = file_digest(target)
        if actual != expected:
            mismatched.append(f"{name}: {actual[:12]} != {expected[:12]}")
        else:
            verified.append(name)

    check(
        "artifacts-present",
        not absent,
        "absent: " + ", ".join(absent) if absent else f"all {len(record.artifacts)} artifacts present",
    )
    check(
        "artifact-checksums",
        not mismatched,
        "; ".join(mismatched) if mismatched else f"{len(verified)} artifact digest(s) recomputed and matched",
    )

    failing = [item["check"] for item in checks if item["outcome"] != "PASS"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": record.as_dict(),
        "checks": checks,
        "failingChecks": failing,
        "verifiedArtifacts": verified,
        "absentArtifacts": absent,
        "digestMismatches": mismatched,
        "accepted": not failing,
        "result": "PASS" if not failing else "BLOCKED",
        "note": (
            "An artifact is not trustworthy because it came from a CI provider. Every claim above "
            "was recomputed from the downloaded bytes or checked against a value held locally."
        ),
    }


__all__ = [
    "EXPECTED_REPOSITORY",
    "EXPECTED_WORKFLOW",
    "ProvenanceError",
    "ProvenanceRecord",
    "file_digest",
    "parse_provenance",
    "verify_provenance",
]

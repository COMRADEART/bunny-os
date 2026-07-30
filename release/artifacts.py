"""Candidate release artifacts: naming discipline and per-artifact metadata.

Twelve artifacts make up a candidate. Each carries version, architecture, source
commit, base digest, size, SHA-256, signature status, SBOM reference and
provenance reference — nine fields, none optional, because a release artifact
whose provenance is partially recorded is not verifiable.

The naming rule is enforced rather than advised: a candidate must be named
``stable-rc`` or ``qualification-candidate``. The word ``stable`` on its own is
refused until ``gate-stable-release`` has passed, so an artifact cannot acquire
the authority of a release by being labelled like one.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: Names a candidate may carry before the stable gate passes.
CANDIDATE_NAMES = ("stable-rc", "qualification-candidate")

#: The twelve expected artifacts.
EXPECTED_ARTIFACTS = (
    "iso",
    "raw",
    "qcow2",
    "recovery-iso",
    "checksums",
    "detached-signatures",
    "sbom",
    "package-manifest",
    "build-provenance",
    "release-notes",
    "known-issues",
    "third-party-notices",
)

#: Artifacts that are bootable media and therefore must be signed.
SIGNED_ARTIFACTS = frozenset({"iso", "raw", "qcow2", "recovery-iso"})

SIGNATURE_STATES = ("signed", "unsigned", "signature-invalid", "not-applicable")

REQUIRED_ARTIFACT_FIELDS = (
    "artifact",
    "filename",
    "version",
    "architecture",
    "sourceCommit",
    "baseImageDigest",
    "sizeBytes",
    "sha256",
    "signatureStatus",
    "sbomReference",
    "provenanceReference",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ArtifactError(ValueError):
    """Raised when a candidate manifest is malformed or overclaims stability."""


@dataclass(frozen=True)
class ArtifactRecord:
    artifact: str
    filename: str
    version: str
    architecture: str
    sourceCommit: str
    baseImageDigest: str
    sizeBytes: int
    sha256: str
    signatureStatus: str
    sbomReference: str
    provenanceReference: str
    signingKeyId: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "filename": self.filename,
            "version": self.version,
            "architecture": self.architecture,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
            "sizeBytes": self.sizeBytes,
            "sha256": self.sha256,
            "signatureStatus": self.signatureStatus,
            "sbomReference": self.sbomReference,
            "provenanceReference": self.provenanceReference,
            "signingKeyId": self.signingKeyId,
        }


def parse_artifact(record: Mapping[str, Any]) -> ArtifactRecord:
    if not isinstance(record, Mapping):
        raise ArtifactError("artifact record must be an object")
    missing = [name for name in REQUIRED_ARTIFACT_FIELDS if name not in record]
    if missing:
        raise ArtifactError(f"artifact record missing fields: {', '.join(missing)}")

    kind = record["artifact"]
    if kind not in EXPECTED_ARTIFACTS:
        raise ArtifactError(f"unknown artifact kind {kind!r}")
    if not _COMMIT.match(str(record["sourceCommit"])):
        raise ArtifactError(f"{kind}: sourceCommit must be a full 40-character commit sha")
    if not _SHA256.match(str(record["sha256"])):
        raise ArtifactError(f"{kind}: sha256 must be a lowercase hex digest")
    if not isinstance(record["sizeBytes"], int) or record["sizeBytes"] < 0:
        raise ArtifactError(f"{kind}: sizeBytes must be a non-negative integer")
    if record["signatureStatus"] not in SIGNATURE_STATES:
        raise ArtifactError(f"{kind}: signatureStatus must be one of {', '.join(SIGNATURE_STATES)}")
    for name in ("filename", "version", "architecture", "baseImageDigest", "sbomReference", "provenanceReference"):
        if not str(record[name]).strip():
            raise ArtifactError(f"{kind}: {name} must not be empty")

    return ArtifactRecord(
        artifact=kind,
        filename=str(record["filename"]),
        version=str(record["version"]),
        architecture=str(record["architecture"]),
        sourceCommit=str(record["sourceCommit"]),
        baseImageDigest=str(record["baseImageDigest"]),
        sizeBytes=int(record["sizeBytes"]),
        sha256=str(record["sha256"]),
        signatureStatus=str(record["signatureStatus"]),
        sbomReference=str(record["sbomReference"]),
        provenanceReference=str(record["provenanceReference"]),
        signingKeyId=record.get("signingKeyId"),
    )


@dataclass(frozen=True)
class CandidateManifest:
    candidateName: str
    version: str
    sourceCommit: str
    baseImageDigest: str
    builtAt: str
    artifacts: tuple[ArtifactRecord, ...]

    @property
    def missingArtifacts(self) -> tuple[str, ...]:
        present = {record.artifact for record in self.artifacts}
        return tuple(name for name in EXPECTED_ARTIFACTS if name not in present)

    @property
    def unsignedArtifacts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                record.artifact
                for record in self.artifacts
                if record.artifact in SIGNED_ARTIFACTS and record.signatureStatus != "signed"
            )
        )

    @property
    def complete(self) -> bool:
        return not self.missingArtifacts

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "candidateName": self.candidateName,
            "version": self.version,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
            "builtAt": self.builtAt,
            "artifacts": [record.as_dict() for record in self.artifacts],
            "artifactCount": len(self.artifacts),
            "missingArtifacts": list(self.missingArtifacts),
            "unsignedArtifacts": list(self.unsignedArtifacts),
            "complete": self.complete,
            "isStableRelease": False,
            "note": (
                "A candidate is not a release. This manifest describes artifacts built for "
                "qualification; only gate-stable-release can authorise calling them stable."
            ),
        }


def parse_manifest(
    document: Mapping[str, Any],
    *,
    stableGatePassed: bool = False,
) -> CandidateManifest:
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise ArtifactError("candidate manifest schemaVersion is invalid")

    name = document.get("candidateName")
    if not name:
        raise ArtifactError("candidate manifest must carry a candidateName")
    if name not in CANDIDATE_NAMES and not stableGatePassed:
        raise ArtifactError(
            f"candidateName {name!r} is not one of {', '.join(CANDIDATE_NAMES)}; an artifact may "
            "not be named as a stable release until gate-stable-release passes"
        )

    for field in ("version", "sourceCommit", "baseImageDigest", "builtAt"):
        if not document.get(field):
            raise ArtifactError(f"candidate manifest missing {field}")

    raw = document.get("artifacts")
    if not isinstance(raw, list):
        raise ArtifactError("candidate manifest must carry an artifacts array")
    artifacts = tuple(parse_artifact(item) for item in raw)

    kinds = [record.artifact for record in artifacts]
    duplicates = sorted({name for name in kinds if kinds.count(name) > 1})
    if duplicates:
        raise ArtifactError("duplicate artifact kinds: " + ", ".join(duplicates))

    commit = str(document["sourceCommit"])
    inconsistent = sorted({record.artifact for record in artifacts if record.sourceCommit != commit})
    if inconsistent:
        raise ArtifactError(
            "artifacts were built from a different commit than the manifest declares: "
            + ", ".join(inconsistent)
        )

    return CandidateManifest(
        candidateName=str(name),
        version=str(document["version"]),
        sourceCommit=commit,
        baseImageDigest=str(document["baseImageDigest"]),
        builtAt=str(document["builtAt"]),
        artifacts=artifacts,
    )


def verify_against_disk(manifest: CandidateManifest, *, root: Path) -> dict[str, Any]:
    """Check that every artifact named in a manifest exists with the recorded digest."""
    from release.evidence import file_digest

    present: list[str] = []
    absent: list[str] = []
    mismatched: list[str] = []
    for record in manifest.artifacts:
        target = root / record.filename
        if not target.is_file():
            absent.append(record.filename)
            continue
        actual = file_digest(target)
        if actual != record.sha256:
            mismatched.append(f"{record.filename}: recorded {record.sha256[:12]}, actual {actual[:12]}")
        else:
            present.append(record.filename)
    return {
        "verifiedArtifacts": present,
        "absentArtifacts": absent,
        "digestMismatches": mismatched,
        "result": "PASS" if not absent and not mismatched else "FAIL",
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CANDIDATE_NAMES",
    "EXPECTED_ARTIFACTS",
    "REQUIRED_ARTIFACT_FIELDS",
    "SIGNED_ARTIFACTS",
    "ArtifactError",
    "ArtifactRecord",
    "CandidateManifest",
    "parse_artifact",
    "parse_manifest",
    "verify_against_disk",
]

"""Stable release-candidate manifest structural qualification."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Mapping


REQUIRED_ARTIFACT_KINDS = frozenset({
    "stable-iso", "stable-raw", "stable-qcow2", "recovery-iso", "checksums", "detached-signatures",
    "sbom", "package-manifest", "provenance", "release-notes", "known-issues", "third-party-notices",
})
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-stable-rc[1-9][0-9]*\Z")


def validate_candidate(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "candidateVersion", "sourceCommit", "immutable", "artifacts", "signedUpdateMetadata", "reviewEvidence", "soak"}
    if set(raw) != required or raw.get("schemaVersion") != 1:
        raise ValueError("candidate manifest fields do not match schema version 1")
    if not isinstance(raw.get("candidateVersion"), str) or not VERSION.fullmatch(str(raw["candidateVersion"])):
        raise ValueError("candidate version is invalid")
    if not isinstance(raw.get("sourceCommit"), str) or not COMMIT.fullmatch(str(raw["sourceCommit"])):
        raise ValueError("source commit must be immutable SHA-1 commit evidence")
    if raw.get("immutable") is not True or raw.get("signedUpdateMetadata") is not True:
        raise ValueError("candidate and update metadata must be immutable and signed")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("candidate artifacts must be an array")
    kinds = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or set(artifact) != {"kind", "path", "sha256", "signatureVerified"}:
            raise ValueError("candidate artifact entry is invalid")
        if artifact["kind"] in kinds or artifact["kind"] not in REQUIRED_ARTIFACT_KINDS:
            raise ValueError("candidate artifact kind is duplicate or unsupported")
        path = artifact["path"]
        if not isinstance(path, str) or not path or "\\" in path:
            raise ValueError("candidate artifact path is invalid")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            raise ValueError("candidate artifact path must be a safe relative path")
        if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
            raise ValueError("candidate artifact checksum is invalid")
        if artifact["signatureVerified"] is not True:
            raise ValueError("every candidate artifact must have verified signature evidence")
        kinds.add(str(artifact["kind"]))
    missing = REQUIRED_ARTIFACT_KINDS - kinds
    if missing:
        raise ValueError("candidate artifact set is incomplete: " + ", ".join(sorted(missing)))
    reviews = raw.get("reviewEvidence")
    if not isinstance(reviews, Mapping) or set(reviews) != {"security", "privacy", "accessibility"} or any(value != "PASS" for value in reviews.values()):
        raise ValueError("candidate reviews must all pass")
    soak = raw.get("soak")
    if not isinstance(soak, Mapping) or soak.get("completed") is not True or not isinstance(soak.get("hours"), int) or soak["hours"] < 0:
        raise ValueError("candidate soak evidence is incomplete")
    return dict(raw)

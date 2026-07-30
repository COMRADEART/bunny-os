# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Importing evidence produced somewhere this repository does not control.

A hosted builder is only useful as independent evidence if its record cannot be
written by hand. Every field a hosted build claims about itself is checked
against another file in the same bundle that would have to be edited
consistently for the claim to survive:

    builder-record.json      what the builder says it is
    ci-provenance.json       what the workflow says it produced
    runner-environment.txt   what the runner reported, written before the build
    normalisation.json       the raw and normalised archive digests
    sbom.spdx.json           the package set
    package-inventory.txt    the same set, flattened
    artifact-manifest.sha256 the artifact digests, from sha256sum

The checks are cross-references, not signatures. A determined forger who edits
every file consistently is not stopped by this; someone who edits the builder
record to claim a different commit, a different base, a different runner or a
different run is. That is the failure this is for, and the distinction is stated
rather than left implied — an unsigned bundle is not proof of provenance and is
recorded as `unsigned`.

An imported record is evidence for one thing: whether a *pair* of builders is
independent. It is never on its own a reproducibility result, and an archive-only
record can never be a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from release.builders import BuilderError, BuilderRecord, parse_builder_record
from release.provenance import ProvenanceError, ProvenanceRecord, parse_provenance

__all__ = [
    "REQUIRED_ARTIFACTS",
    "HostedEvidence",
    "HostedImportError",
    "import_hosted_evidence",
]

#: Every file the hosted workflow uploads. A bundle missing any of them is not a
#: complete record of that build and is refused rather than partially imported.
REQUIRED_ARTIFACTS = (
    "builder-record.json",
    "ci-provenance.json",
    "artifact-manifest.sha256",
    "normalisation.json",
    "sbom.spdx.json",
    "package-inventory.txt",
    "runner-environment.txt",
    "build.log",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^\d+(\.\d+)?$")


class HostedImportError(ValueError):
    """The bundle cannot be imported as hosted-builder evidence."""


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _read_environment(path: Path) -> dict[str, str]:
    """The runner's own report, written before the build ran."""
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    return fields


@dataclass
class HostedEvidence:
    builder: BuilderRecord
    provenance: ProvenanceRecord
    runnerEnvironment: Mapping[str, str]
    rawArchiveDigest: str
    normalisedArchiveDigest: str
    bundleDigests: Mapping[str, str]
    packageCount: int
    signed: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejectionReasons": list(self.reasons),
            "builderRecord": self.builder.as_dict(),
            "workflowRunId": self.builder.workflowRunId,
            "workflowRunAttempt": self.provenance.workflowRunAttempt,
            "runnerImage": self.provenance.runnerImage,
            "runnerArchitecture": self.provenance.runnerArchitecture,
            "runnerEnvironment": dict(self.runnerEnvironment),
            "sourceCommit": self.builder.sourceCommit,
            "baseImageDigest": self.builder.baseImageDigest,
            "rawArchiveDigest": self.rawArchiveDigest,
            "normalisedArchiveDigest": self.normalisedArchiveDigest,
            "bundleDigests": dict(self.bundleDigests),
            "packageCount": self.packageCount,
            "signed": self.signed,
            "provenanceClaim": "unsigned" if not self.signed else "signed",
            "note": (
                "Cross-referenced, not signed. This detects a record edited in one place; it is "
                "not proof against a consistently forged bundle, and the record says so rather "
                "than implying more than it establishes."
            ),
        }


def import_hosted_evidence(
    artifactDir: Path,
    *,
    candidateCommit: str,
    expectedBaseDigest: str | None = None,
    knownRunIds: Iterable[str] = (),
    expectedRunId: str | None = None,
) -> HostedEvidence:
    """Read and check a downloaded hosted-builder artifact bundle.

    Returns the evidence with every rejection reason attached rather than raising
    on the first, so an operator sees all of what is wrong at once. `accepted` is
    false if there is any reason at all.
    """
    directory = Path(artifactDir)
    if not directory.is_dir():
        raise HostedImportError(f"artifact directory does not exist: {directory}")

    missing = [name for name in REQUIRED_ARTIFACTS if not (directory / name).is_file()]
    if missing:
        raise HostedImportError(
            f"bundle is incomplete, missing: {', '.join(missing)}. A partial bundle is not a "
            "record of a build and is not imported."
        )

    reasons: list[str] = []

    def load(name: str) -> Any:
        try:
            return json.loads((directory / name).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HostedImportError(f"{name} is not valid JSON: {exc}") from None

    try:
        builder = parse_builder_record(load("builder-record.json"))
    except BuilderError as exc:
        raise HostedImportError(f"builder record is invalid: {exc}") from None
    try:
        provenance = parse_provenance(load("ci-provenance.json"))
    except ProvenanceError as exc:
        raise HostedImportError(f"CI provenance is invalid: {exc}") from None

    environment = _read_environment(directory / "runner-environment.txt")
    normalisation = load("normalisation.json")

    # --- workflow identity ----------------------------------------------------
    if not builder.workflowRunId:
        reasons.append(
            "builder record carries no workflowRunId; a hosted-ci record with no workflow "
            "identity cannot be traced to a run and is indistinguishable from a local build "
            "declaring itself hosted"
        )
    elif not _RUN_ID.match(builder.workflowRunId):
        reasons.append(f"workflowRunId {builder.workflowRunId!r} is not a run id")

    if builder.builderType != "hosted-ci":
        reasons.append(
            f"builderType is {builder.builderType!r}; only a hosted-ci record establishes the "
            "hosted administrator boundary"
        )

    run = builder.workflowRunId or ""
    if run and run in set(knownRunIds):
        reasons.append(
            f"workflow run {run} is already recorded; a reused run id would count one build "
            "twice and cannot establish a second builder"
        )
    if expectedRunId and run and run.split(".")[0] != expectedRunId.split(".")[0]:
        reasons.append(f"workflow run {run} is not the expected run {expectedRunId}")

    # --- the record must agree with the runner's own report -------------------
    # A record edited in one place fails here; this is the manual-edit check.
    reported_run = environment.get("workflowRunId")
    if reported_run and run and reported_run != run:
        reasons.append(
            f"builder record claims run {run} but the runner reported {reported_run}; "
            "the record does not describe the run that produced this bundle"
        )
    if provenance.workflowRunId and run and provenance.workflowRunId != run:
        reasons.append(
            f"builder record claims run {run} but the CI provenance records "
            f"{provenance.workflowRunId}"
        )
    reported_kernel = environment.get("kernel")
    if reported_kernel and builder.kernelVersion != reported_kernel:
        reasons.append(
            f"builder record claims kernel {builder.kernelVersion} but the runner reported "
            f"{reported_kernel}"
        )
    reported_os = environment.get("os")
    if reported_os and builder.operatingSystem != reported_os:
        reasons.append(
            f"builder record claims OS {builder.operatingSystem} but the runner reported "
            f"{reported_os}"
        )
    if environment.get("runnerEnvironment") not in (None, "", "github-hosted"):
        reasons.append(
            f"runner environment is {environment.get('runnerEnvironment')!r}, not github-hosted; "
            "a self-hosted runner shares an administrator with this project"
        )

    # --- source and base ------------------------------------------------------
    if builder.sourceCommit != candidateCommit:
        reasons.append(
            f"builder built {builder.sourceCommit[:12]} but the candidate is "
            f"{candidateCommit[:12]}; evidence does not transfer between commits"
        )
    if provenance.sourceCommit != candidateCommit:
        reasons.append(
            f"CI provenance describes {provenance.sourceCommit[:12]} but the candidate is "
            f"{candidateCommit[:12]}"
        )
    if expectedBaseDigest:
        if builder.baseImageDigest != expectedBaseDigest:
            reasons.append(
                f"builder used base {builder.baseImageDigest} but {expectedBaseDigest} was "
                "expected; two builders on different bases are not comparable"
            )
        if provenance.baseImageDigest != expectedBaseDigest:
            reasons.append(
                f"CI provenance records base {provenance.baseImageDigest}, expected "
                f"{expectedBaseDigest}"
            )
    if builder.baseImageDigest != provenance.baseImageDigest:
        reasons.append(
            "builder record and CI provenance disagree about the base image digest"
        )

    # --- artifact digests -----------------------------------------------------
    raw = str(normalisation.get("rawDigest", ""))
    normalised = str(normalisation.get("normalisedDigest", ""))
    for label, value in (("rawDigest", raw), ("normalisedDigest", normalised)):
        if not _SHA256.match(value):
            reasons.append(f"normalisation.json {label} is not a SHA-256 digest: {value!r}")

    manifest = _parse_sha256sums(directory / "artifact-manifest.sha256")
    archive_digest = manifest.get("bunny-os.oci.tar")
    if archive_digest is None:
        reasons.append("artifact manifest does not list bunny-os.oci.tar")
    elif raw and archive_digest != raw:
        reasons.append(
            f"artifact manifest records the archive as {archive_digest[:12]} but "
            f"normalisation.json recorded the raw archive as {raw[:12]}"
        )

    # Digests over the bundle as downloaded, so a later edit is detectable.
    bundle = {name: _digest(directory / name) for name in REQUIRED_ARTIFACTS}

    inventory = (directory / "package-inventory.txt").read_text(encoding="utf-8").splitlines()
    packages = [line for line in inventory if line.strip()]
    if not packages:
        reasons.append("package inventory is empty; nothing was measured")

    sbom = load("sbom.spdx.json")
    sbom_packages = sbom.get("packages", [])
    if len(sbom_packages) != len(packages):
        reasons.append(
            f"SBOM lists {len(sbom_packages)} packages but the inventory has {len(packages)}; "
            "the two describe different builds"
        )

    # --- what the bundle may not claim ---------------------------------------
    signed = bool(sbom.get("signature")) or bool(normalisation.get("signature"))
    if not signed and str(normalisation.get("provenanceClaim", "")).lower() == "production":
        reasons.append(
            "bundle claims production provenance without a signature; an unsigned artifact "
            "cannot carry a production claim"
        )

    if _claims_candidate(normalisation) or _claims_candidate(sbom):
        reasons.append(
            "an archive-only bundle claims candidate status; an archive-only build produces no "
            "disk image and qualifies no installation, recovery or hardware evidence"
        )

    # Whether the build was archive-only is stated by the build's own provenance.
    # An earlier version inferred it from imageBuilderVersion, which records
    # whether the tool is *installed* rather than whether it *ran* — the local
    # Fedora builder has image-builder installed and correctly did not use it, and
    # the check rejected it for that. Availability is not use.
    build_provenance = None
    for name in ("provenance.json", "build-provenance.json"):
        if (directory / name).is_file():
            build_provenance = load(name)
            break
    if build_provenance is not None:
        if build_provenance.get("archiveOnly") is not True:
            reasons.append(
                "the build provenance does not declare archiveOnly=true; this bundle is not an "
                "archive-only build and the hosted builder runs in archive-only mode"
            )
        disks = build_provenance.get("diskImages")
        if disks:
            reasons.append(
                f"the build provenance lists disk images {disks}; an archive-only build produces "
                "none, so the record and the artifacts disagree"
            )
        if build_provenance.get("sourceCommit") != candidateCommit:
            reasons.append(
                f"the build provenance describes {str(build_provenance.get('sourceCommit'))[:12]} "
                f"but the candidate is {candidateCommit[:12]}"
            )

    return HostedEvidence(
        builder=builder,
        provenance=provenance,
        runnerEnvironment=environment,
        rawArchiveDigest=raw,
        normalisedArchiveDigest=normalised,
        bundleDigests=bundle,
        packageCount=len(packages),
        signed=signed,
        reasons=reasons,
    )


def _parse_sha256sums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and _SHA256.match(parts[0]):
            entries[parts[1].strip().lstrip("*")] = parts[0]
    return entries


def _claims_candidate(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    for key in ("candidate", "releaseCandidate", "qualified", "candidateStatus"):
        value = document.get(key)
        if value in (True, "true", "yes", "qualified", "candidate"):
            return True
    return False

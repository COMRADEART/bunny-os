"""Independent-builder reproducibility, with four distinct claims kept apart.

The repository has previously conflated two very different results: "the same
host produced the same bytes twice" and "two independent builders produced the
same bytes". Only the second is supply-chain evidence, and the first is
routinely mistaken for it. This module makes the confusion impossible to encode.

Four claims, each recorded separately:

``same-host-repeatability``
    One builder, two runs, same output. Establishes the build is deterministic.
``independent-builder``
    Two builders differing in at least one meaningful dimension, same output.
    The only claim that satisfies the production gate.
``filesystem-content``
    Every file inside the two images is byte-identical, regardless of how the
    archive that wraps them is packed.
``archive-byte``
    The archive files themselves are byte-identical.

A comparison between two builders that differ in *no* dimension cannot be
recorded as ``independent-builder``. :func:`independent_dimensions` returns the
differing dimensions and :func:`compare_builds` refuses the claim when it is
empty, which is the ``same-host builds marked independent`` failure the
adversarial tests exercise.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

REPRODUCIBILITY_CLAIMS = (
    "same-host-repeatability",
    "independent-builder",
    "filesystem-content",
    "archive-byte",
)

#: The dimensions along which two builders may meaningfully differ.
INDEPENDENCE_DIMENSIONS = (
    "machineId",
    "virtualisationInstance",
    "cloudRunner",
    "administrator",
    "environmentId",
)

#: Differing in one of these is what makes two builders *independent* rather
#: than merely *separate*. A second VM, container or workspace on the same
#: physical machine shares its kernel, its storage, its clock and its operator,
#: so a compromise or a defect in any of those reproduces identically in both —
#: which is exactly what the comparison is supposed to detect. The brief is
#: explicit that two builds on one host do not satisfy the requirement, so
#: environment separation alone cannot carry the claim.
STRONG_DIMENSIONS = ("machineId", "cloudRunner", "administrator")

_REQUIRED_BUILDER_FIELDS = (
    "builderId",
    "machineId",
    "virtualisationInstance",
    "cloudRunner",
    "administrator",
    "environmentId",
    "operatingSystem",
    "toolchain",
    "workspace",
    "sourceCommit",
    "baseImageDigest",
)


class ReproducibilityError(ValueError):
    """Raised when a builder record or comparison is malformed or overclaims."""


@dataclass(frozen=True)
class BuilderRecord:
    builderId: str
    machineId: str
    virtualisationInstance: str
    cloudRunner: str | None
    administrator: str
    environmentId: str
    operatingSystem: str
    toolchain: Mapping[str, str]
    workspace: str
    sourceCommit: str
    baseImageDigest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "builderId": self.builderId,
            "machineId": self.machineId,
            "virtualisationInstance": self.virtualisationInstance,
            "cloudRunner": self.cloudRunner,
            "administrator": self.administrator,
            "environmentId": self.environmentId,
            "operatingSystem": self.operatingSystem,
            "toolchain": dict(self.toolchain),
            "workspace": self.workspace,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
        }


def parse_builder(record: Mapping[str, Any]) -> BuilderRecord:
    if not isinstance(record, Mapping):
        raise ReproducibilityError("builder record must be an object")
    missing = [name for name in _REQUIRED_BUILDER_FIELDS if name not in record]
    if missing:
        raise ReproducibilityError(f"builder record missing fields: {', '.join(missing)}")
    toolchain = record["toolchain"]
    if not isinstance(toolchain, Mapping) or not toolchain:
        raise ReproducibilityError(f"{record['builderId']}: toolchain must record tool versions")
    return BuilderRecord(
        builderId=str(record["builderId"]),
        machineId=str(record["machineId"]),
        virtualisationInstance=str(record["virtualisationInstance"]),
        cloudRunner=record["cloudRunner"],
        administrator=str(record["administrator"]),
        environmentId=str(record["environmentId"]),
        operatingSystem=str(record["operatingSystem"]),
        toolchain={str(k): str(v) for k, v in toolchain.items()},
        workspace=str(record["workspace"]),
        sourceCommit=str(record["sourceCommit"]),
        baseImageDigest=str(record["baseImageDigest"]),
    )


def independent_dimensions(first: BuilderRecord, second: BuilderRecord) -> tuple[str, ...]:
    """Return the dimensions along which the two builders genuinely differ."""
    differing: list[str] = []
    for dimension in INDEPENDENCE_DIMENSIONS:
        left = getattr(first, dimension)
        right = getattr(second, dimension)
        if left is None and right is None:
            continue
        if left != right:
            differing.append(dimension)
    return tuple(differing)


def shared_inputs(first: BuilderRecord, second: BuilderRecord) -> tuple[str, ...]:
    """Return the inputs that must be identical but are not."""
    mismatched: list[str] = []
    if first.sourceCommit != second.sourceCommit:
        mismatched.append("sourceCommit")
    if first.baseImageDigest != second.baseImageDigest:
        mismatched.append("baseImageDigest")
    shared_tools = set(first.toolchain) & set(second.toolchain)
    for tool in sorted(shared_tools):
        if first.toolchain[tool] != second.toolchain[tool]:
            mismatched.append(f"toolchain.{tool}")
    return tuple(mismatched)


@dataclass(frozen=True)
class ComparisonResult:
    claim: str
    first: BuilderRecord
    second: BuilderRecord
    differingDimensions: tuple[str, ...]
    mismatchedInputs: tuple[str, ...]
    archiveDigestsMatch: bool
    fileContentsMatch: bool
    sbomMatch: bool
    packageManifestMatch: bool
    differingFiles: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def satisfied(self) -> bool:
        return not self.reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "claim": self.claim,
            "builders": [self.first.as_dict(), self.second.as_dict()],
            "differingDimensions": list(self.differingDimensions),
            "mismatchedInputs": list(self.mismatchedInputs),
            "archiveDigestsMatch": self.archiveDigestsMatch,
            "fileContentsMatch": self.fileContentsMatch,
            "sbomMatch": self.sbomMatch,
            "packageManifestMatch": self.packageManifestMatch,
            "differingFiles": list(self.differingFiles),
            "satisfied": self.satisfied,
            "reasons": list(self.reasons),
            "result": "PASS" if self.satisfied else "FAIL",
        }


def compare_builds(
    first: BuilderRecord,
    second: BuilderRecord,
    *,
    claim: str,
    archiveDigests: tuple[str, str],
    fileDigests: tuple[Mapping[str, str], Mapping[str, str]],
    sbomDigests: tuple[str, str],
    packageManifests: tuple[Iterable[str], Iterable[str]],
) -> ComparisonResult:
    """Compare two builds and decide whether the named claim is supported."""
    if claim not in REPRODUCIBILITY_CLAIMS:
        raise ReproducibilityError(f"claim must be one of {', '.join(REPRODUCIBILITY_CLAIMS)}")

    reasons: list[str] = []
    differing = independent_dimensions(first, second)
    mismatched = shared_inputs(first, second)

    if mismatched:
        reasons.append(
            "builders did not share identical inputs: " + ", ".join(mismatched)
        )

    if claim == "independent-builder":
        if not differing:
            reasons.append(
                "the two builders differ in no meaningful dimension; two builds on one host are "
                "same-host repeatability, not independent-builder reproducibility"
            )
        elif not any(dimension in differing for dimension in STRONG_DIMENSIONS):
            reasons.append(
                "the builders differ only in "
                + ", ".join(differing)
                + ", which is environment separation on one machine. Independent-builder "
                "reproducibility requires a different machine, cloud runner or administrator; "
                "otherwise a defect in the shared kernel, storage or clock reproduces in both "
                "builds and the comparison cannot detect it"
            )
    if claim == "same-host-repeatability" and any(
        dimension in differing for dimension in STRONG_DIMENSIONS
    ):
        reasons.append(
            "builders differ in "
            + ", ".join(dimension for dimension in differing if dimension in STRONG_DIMENSIONS)
            + "; this is stronger than same-host repeatability and should be recorded as "
            "independent-builder"
        )

    left_files, right_files = fileDigests
    differing_files = tuple(
        sorted(
            name
            for name in set(left_files) | set(right_files)
            if left_files.get(name) != right_files.get(name)
        )
    )
    file_match = not differing_files
    archive_match = archiveDigests[0] == archiveDigests[1]
    sbom_match = sbomDigests[0] == sbomDigests[1]
    left_packages = sorted(packageManifests[0])
    right_packages = sorted(packageManifests[1])
    package_match = left_packages == right_packages

    if claim in {"independent-builder", "same-host-repeatability", "archive-byte"} and not archive_match:
        reasons.append(f"archive digests differ: {archiveDigests[0][:12]} vs {archiveDigests[1][:12]}")
    if claim in {"independent-builder", "same-host-repeatability", "filesystem-content"} and not file_match:
        reasons.append(f"{len(differing_files)} file(s) differ inside the images")
    # An SBOM *file* digest mismatch is not by itself a reproducibility failure.
    # Syft stamps each document with a fresh UUID namespace, a creation
    # timestamp, and a root entry named after the input file's path, so two
    # scans of byte-identical archives never produce identical bytes. What must
    # match is the package manifest, which is compared separately and is fatal.
    if not sbom_match and not package_match:
        reasons.append("SBOM digests and package manifests both differ")
    if not package_match:
        reasons.append("package manifests differ")

    return ComparisonResult(
        claim=claim,
        first=first,
        second=second,
        differingDimensions=differing,
        mismatchedInputs=mismatched,
        archiveDigestsMatch=archive_match,
        fileContentsMatch=file_match,
        sbomMatch=sbom_match,
        packageManifestMatch=package_match,
        differingFiles=differing_files,
        reasons=tuple(reasons),
    )


def summarise_claims(results: Iterable[ComparisonResult]) -> dict[str, Any]:
    """Report which of the four claims are established."""
    established: dict[str, bool] = {name: False for name in REPRODUCIBILITY_CLAIMS}
    for result in results:
        if result.satisfied:
            established[result.claim] = True
        # The content-level claims are measurements, not judgements about how
        # independent the builders were. A comparison that failed only on
        # independence still established, or failed to establish, whether the
        # bytes matched — and that fact should not be discarded. Mismatched
        # *inputs* are the exception: nothing is established by comparing builds
        # of different commits.
        if not result.mismatchedInputs:
            established["filesystem-content"] = established["filesystem-content"] or result.fileContentsMatch
            established["archive-byte"] = established["archive-byte"] or result.archiveDigestsMatch
    return {
        "schemaVersion": SCHEMA_VERSION,
        "claims": established,
        "productionRequirementMet": established["independent-builder"],
        "note": (
            "Only independent-builder reproducibility satisfies the production gate. Same-host "
            "repeatability establishes determinism and nothing more."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "INDEPENDENCE_DIMENSIONS",
    "REPRODUCIBILITY_CLAIMS",
    "STRONG_DIMENSIONS",
    "BuilderRecord",
    "ComparisonResult",
    "ReproducibilityError",
    "compare_builds",
    "independent_dimensions",
    "parse_builder",
    "shared_inputs",
    "summarise_claims",
]

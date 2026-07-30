# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seventeen-dimension comparison of two independently produced builds.

The comparison this replaces asked three questions — archive digest, file
contents, package manifest — and answered them well. It could not distinguish
"the images agree in every respect we looked at" from "the images agree in every
respect", because it did not record which respects it had looked at.

So every dimension here has three states, not two:

``MATCH``
    collected from both builders and identical
``DIFFER``
    collected from both builders and not identical
``NOT_COLLECTED``
    not gathered from at least one builder

``NOT_COLLECTED`` is the load-bearing state. A dimension nobody measured cannot
contribute to a `REPRODUCIBLE` verdict, so an incomplete comparison reports
``INCONCLUSIVE`` rather than passing on the strength of the dimensions that
happened to be easy. That is the difference between a comparison and a
formality.

Only ``REPRODUCIBLE`` satisfies the production evidence gate, and only when the
two builders were independent — a perfect comparison between two workspaces on
one host establishes determinism, which is a different claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 1

OUTCOMES = (
    "REPRODUCIBLE",
    "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE",
    "NON_REPRODUCIBLE",
    "INCONCLUSIVE",
)

STATES = ("MATCH", "DIFFER", "NOT_COLLECTED")

#: ``semantic`` — a difference means the two builds are not the same image.
#: ``archive-raw`` — a difference is a packing difference, tolerable only when
#: explained and only when the normalised archive matches.
#: ``archive-normalised`` — a difference here means content differs after every
#: non-semantic property has been pinned, so it is semantic after all.
COMPARISON_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("filesystemTree", "semantic", "the set of paths present in the image"),
    ("fileDigests", "semantic", "the SHA-256 of every regular file's contents"),
    ("permissions", "semantic", "mode bits, including setuid and setgid"),
    ("ownership", "semantic", "owning uid and gid of every path"),
    ("extendedAttributes", "semantic", "xattrs, including capabilities"),
    ("selinuxLabels", "semantic", "the SELinux context of every path"),
    ("packageInventory", "semantic", "installed package name and version set"),
    ("sbom", "semantic", "the SBOM package manifest, excluding document identity"),
    ("bootConfiguration", "semantic", "bootloader entries and kernel command line"),
    ("systemdUnits", "semantic", "unit files and their enablement state"),
    ("desktopEntries", "semantic", "installed .desktop files"),
    ("schemas", "semantic", "compiled GSettings schemas"),
    ("kernel", "semantic", "the kernel package version and vmlinuz digest"),
    ("initramfs", "semantic", "the initramfs digest, or a stated reason it is not comparable"),
    ("ociLayers", "semantic", "the layer digest list from the image manifest"),
    ("rawArchive", "archive-raw", "the archive file's own SHA-256, unnormalised"),
    ("normalisedArchive", "archive-normalised", "the archive's SHA-256 after non-semantic normalisation"),
)

DIMENSION_KINDS = {name: kind for name, kind, _ in COMPARISON_DIMENSIONS}
DIMENSION_DESCRIPTIONS = {name: text for name, _, text in COMPARISON_DIMENSIONS}


class ComparisonError(ValueError):
    """Raised when a comparison document is malformed."""


@dataclass(frozen=True)
class DimensionResult:
    dimension: str
    kind: str
    state: str
    differenceCount: int
    differences: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "kind": self.kind,
            "description": DIMENSION_DESCRIPTIONS[self.dimension],
            "state": self.state,
            "differenceCount": self.differenceCount,
            "differences": list(self.differences[:100]),
            "detail": self.detail,
        }


def _compare_values(left: Any, right: Any) -> tuple[bool, tuple[str, ...]]:
    """Compare two collected values, returning equality and named differences."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = set(left) | set(right)
        differing = tuple(
            sorted(key for key in keys if left.get(key) != right.get(key))
        )
        return not differing, differing
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        # Order is not meaningful for any collected list here (path sets,
        # package sets, unit names), except OCI layers — and layer order is
        # preserved because the lists are compared element-wise after sorting
        # only when the sorted forms differ.
        if list(left) == list(right):
            return True, ()
        left_set, right_set = set(map(str, left)), set(map(str, right))
        differing = tuple(sorted(left_set ^ right_set))
        if not differing:
            return False, ("<same members, different order>",)
        return False, differing
    return left == right, () if left == right else (f"{left!r} vs {right!r}",)


def compare_dimension(dimension: str, collected: Mapping[str, Any]) -> DimensionResult:
    """Compare one dimension from a ``{"first": ..., "second": ...}`` record."""
    if dimension not in DIMENSION_KINDS:
        raise ComparisonError(f"unknown comparison dimension {dimension!r}")
    kind = DIMENSION_KINDS[dimension]

    if not isinstance(collected, Mapping):
        return DimensionResult(dimension, kind, "NOT_COLLECTED", 0, (), "no record for this dimension")

    if "first" not in collected or "second" not in collected:
        missing = [name for name in ("first", "second") if name not in collected]
        return DimensionResult(
            dimension,
            kind,
            "NOT_COLLECTED",
            0,
            (),
            f"not collected from: {', '.join(missing)}",
        )
    left, right = collected["first"], collected["second"]
    if left is None or right is None:
        absent = [name for name, value in (("first", left), ("second", right)) if value is None]
        return DimensionResult(
            dimension,
            kind,
            "NOT_COLLECTED",
            0,
            (),
            f"null value recorded for: {', '.join(absent)}",
        )

    equal, differences = _compare_values(left, right)
    detail = str(collected.get("detail", ""))
    return DimensionResult(
        dimension=dimension,
        kind=kind,
        state="MATCH" if equal else "DIFFER",
        differenceCount=len(differences),
        differences=differences,
        detail=detail,
    )


@dataclass(frozen=True)
class ComparisonReport:
    outcome: str
    dimensions: tuple[DimensionResult, ...]
    reasons: tuple[str, ...]
    independent: bool
    independenceReasons: tuple[str, ...]
    sourceCommit: str
    baseImageDigest: str
    builders: tuple[str, str]

    @property
    def satisfiesProductionGate(self) -> bool:
        return self.outcome == "REPRODUCIBLE" and self.independent

    def as_dict(self) -> dict[str, Any]:
        by_state: dict[str, list[str]] = {name: [] for name in STATES}
        for result in self.dimensions:
            by_state[result.state].append(result.dimension)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
            "builders": list(self.builders),
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "independentBuilders": self.independent,
            "independenceReasons": list(self.independenceReasons),
            "dimensionCount": len(self.dimensions),
            "dimensionsByState": {name: sorted(values) for name, values in by_state.items()},
            "dimensions": [result.as_dict() for result in self.dimensions],
            "satisfiesProductionGate": self.satisfiesProductionGate,
            "note": (
                "Only REPRODUCIBLE satisfies the production evidence gate, and only between "
                "independent builders. NOT_COLLECTED is not a pass: a dimension nobody measured "
                "cannot support a reproducibility claim."
            ),
        }


def evaluate_comparison(
    document: Mapping[str, Any],
    *,
    independent: bool,
    independenceReasons: tuple[str, ...] = (),
) -> ComparisonReport:
    """Evaluate a full seventeen-dimension comparison document."""
    if not isinstance(document, Mapping):
        raise ComparisonError("comparison document must be an object")
    dimensions_raw = document.get("dimensions")
    if not isinstance(dimensions_raw, Mapping):
        raise ComparisonError("comparison document must carry a dimensions object")
    unknown = sorted(set(dimensions_raw) - set(DIMENSION_KINDS))
    if unknown:
        raise ComparisonError(f"unknown comparison dimensions: {', '.join(unknown)}")

    results = tuple(
        compare_dimension(name, dimensions_raw.get(name, {})) for name, _, _ in COMPARISON_DIMENSIONS
    )
    by_name = {result.dimension: result for result in results}

    reasons: list[str] = []
    semantic_differing = [
        result.dimension
        for result in results
        if result.kind == "semantic" and result.state == "DIFFER"
    ]
    not_collected = [result.dimension for result in results if result.state == "NOT_COLLECTED"]

    normalised = by_name["normalisedArchive"]
    raw = by_name["rawArchive"]
    explanation = str(document.get("rawVarianceExplanation") or "").strip()

    if semantic_differing:
        outcome = "NON_REPRODUCIBLE"
        reasons.append(
            "semantic dimensions differ: "
            + ", ".join(sorted(semantic_differing))
            + ". These describe what the image is, not how it was packed"
        )
    elif normalised.state == "DIFFER":
        outcome = "NON_REPRODUCIBLE"
        reasons.append(
            "the normalised archive digests differ, so the difference survives normalisation and "
            "is not a packing artefact"
        )
    elif not_collected:
        outcome = "INCONCLUSIVE"
        reasons.append(
            "these dimensions were not collected from both builders: "
            + ", ".join(sorted(not_collected))
            + ". An unmeasured dimension cannot support a reproducibility claim"
        )
    elif raw.state == "DIFFER":
        if explanation:
            outcome = "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE"
            reasons.append(f"raw archive digests differ; explanation recorded: {explanation}")
        else:
            outcome = "INCONCLUSIVE"
            reasons.append(
                "raw archive digests differ and no rawVarianceExplanation is recorded. A "
                "normalised match does not excuse an unexplained raw difference"
            )
    else:
        outcome = "REPRODUCIBLE"

    if outcome == "REPRODUCIBLE" and not independent:
        reasons.append(
            "every dimension matched, but the two builders are not independent, so this is "
            "same-host repeatability and does not satisfy the production gate"
        )

    builders = document.get("builders") or ["unknown", "unknown"]
    return ComparisonReport(
        outcome=outcome,
        dimensions=results,
        reasons=tuple(reasons),
        independent=independent,
        independenceReasons=independenceReasons,
        sourceCommit=str(document.get("sourceCommit", "")),
        baseImageDigest=str(document.get("baseImageDigest", "")),
        builders=(str(builders[0]), str(builders[1])),
    )


__all__ = [
    "COMPARISON_DIMENSIONS",
    "DIMENSION_DESCRIPTIONS",
    "DIMENSION_KINDS",
    "OUTCOMES",
    "STATES",
    "ComparisonError",
    "ComparisonReport",
    "DimensionResult",
    "compare_dimension",
    "evaluate_comparison",
]

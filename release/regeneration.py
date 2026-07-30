# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does a committed record still follow from the committed evidence?

The CI step that asked this reported one line:

    security/reachability/findings/CVE-2020-27815.json does not regenerate from
    committed evidence

which is true of a record that drifted by one timestamp and equally true of one
whose conclusion was edited by hand. It also stripped ``generatedAt`` from both
sides before comparing and stopped at the first file, so nobody could see that
all 25 records differed, or that they differed in ``sourceCommit`` for a reason
that had nothing to do with the evidence.

The rule this module implements is that a field must be *classified* before it
may be excluded, and only one classification may be excluded:

``Semantic evidence``
    What was measured and what it means. Must match exactly.
``Commit identity``
    Which commit the record describes. Must match — resolved through
    ``candidateCommit`` rather than deleted from the comparison.
``Environment metadata``
    Where the generator ran. Must match; a record that changes with the host is
    describing the host.
``Generation metadata``
    Facts about the act of generating, which cannot affect a conclusion. The only
    excludable class, and the exclusion list is enumerated, not inferred.
``Unstable ordering``
    Same members, different order. Tolerated in comparison and canonicalised at
    generation, so it should never appear.
``Bug``
    A type changed, or a field appeared or vanished. Never tolerated.

See ``docs/CVE_REGENERATION_INVARIANTS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "CLASSIFICATIONS",
    "EXCLUDABLE_CLASSIFICATIONS",
    "GENERATION_METADATA_FIELDS",
    "FieldDifference",
    "RegenerationReport",
    "classify_field",
    "diff_documents",
    "evaluate_regeneration",
    "render_differences",
]

CLASSIFICATIONS = (
    "Semantic evidence",
    "Environment metadata",
    "Generation metadata",
    "Commit identity",
    "Unstable ordering",
    "Bug",
)

#: The only classes a difference may fall into without failing.
EXCLUDABLE_CLASSIFICATIONS = frozenset({"Generation metadata", "Unstable ordering"})

#: Enumerated, not pattern-matched. Adding a field here is a decision that has to
#: be made deliberately and justified in the invariants document.
GENERATION_METADATA_FIELDS = frozenset({
    "generatedAt",
})

#: Fields that identify the commit a record describes. These must match. They are
#: listed so that a diff can *name* them rather than lumping them in with the
#: measurements.
COMMIT_IDENTITY_FIELDS = frozenset({
    "sourceCommit",
    "candidateCommit",
    "scopeCommit",
    "commit",
})

#: Fields describing the machine the generator ran on. None of the CVE records
#: carry these today; they are named so that adding one is visible.
ENVIRONMENT_METADATA_FIELDS = frozenset({
    "hostname",
    "generatorHost",
    "runnerImage",
    "runnerArch",
})

ABSENT = "<absent>"


def _leaf(path: str) -> str:
    """The field name, with any list indices and parent path removed."""
    tail = path.split(".")[-1]
    return tail.split("[")[0]


def classify_field(path: str, *, committed: Any = None, regenerated: Any = None) -> str:
    """Which class a differing field belongs to.

    ``path`` is a dotted field path such as ``mapping.privilegeRequired`` or
    ``carrierObjects[0]``.
    """
    if committed is ABSENT or regenerated is ABSENT:
        return "Bug"
    if (
        committed is not None
        and regenerated is not None
        and type(committed) is not type(regenerated)
    ):
        return "Bug"

    name = _leaf(path)
    if name in GENERATION_METADATA_FIELDS:
        return "Generation metadata"
    if name in COMMIT_IDENTITY_FIELDS:
        return "Commit identity"
    if name in ENVIRONMENT_METADATA_FIELDS:
        return "Environment metadata"
    return "Semantic evidence"


@dataclass(frozen=True)
class FieldDifference:
    document: str
    path: str
    committed: Any
    regenerated: Any
    classification: str

    @property
    def excludable(self) -> bool:
        return self.classification in EXCLUDABLE_CLASSIFICATIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "fieldPath": self.path,
            "committedValue": self.committed,
            "regeneratedValue": self.regenerated,
            "classification": self.classification,
            "excludable": self.excludable,
        }


def _same_members(left: Sequence[Any], right: Sequence[Any]) -> bool:
    """Whether two sequences hold the same members, ignoring order."""
    try:
        return sorted(left, key=repr) == sorted(right, key=repr)
    except TypeError:  # pragma: no cover - unorderable mixed types
        return False


def diff_documents(
    committed: Mapping[str, Any],
    regenerated: Mapping[str, Any],
    *,
    document: str = "",
) -> list[FieldDifference]:
    """Every differing field path between two records, each classified."""
    differences: list[FieldDifference] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right)):
                walk(
                    left.get(key, ABSENT),
                    right.get(key, ABSENT),
                    f"{path}.{key}" if path else str(key),
                )
            return

        if isinstance(left, list) and isinstance(right, list):
            if left == right:
                return
            if _same_members(left, right):
                # Same set, different order. Reported so canonicalisation can be
                # added at generation time, but not a semantic difference.
                differences.append(
                    FieldDifference(document, path, left, right, "Unstable ordering")
                )
                return
            if len(left) != len(right):
                differences.append(
                    FieldDifference(
                        document, path, f"{len(left)} item(s)", f"{len(right)} item(s)",
                        "Semantic evidence",
                    )
                )
                return
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, f"{path}[{index}]")
            return

        if left == right and type(left) is type(right):
            return

        differences.append(
            FieldDifference(
                document, path, left, right,
                classify_field(path, committed=left, regenerated=right),
            )
        )

    walk(committed, regenerated, "")
    return differences


@dataclass
class RegenerationReport:
    """The verdict, and every difference that produced it."""

    documents: int = 0
    differences: list[FieldDifference] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[FieldDifference]:
        return [item for item in self.differences if not item.excludable]

    @property
    def deterministic(self) -> bool:
        return not self.blocking and not self.missing and not self.unexpected

    def counts(self) -> dict[str, int]:
        counts = {name: 0 for name in CLASSIFICATIONS}
        for item in self.differences:
            counts[item.classification] += 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "deterministic": self.deterministic,
            "counts": self.counts(),
            "missingDocuments": sorted(self.missing),
            "unexpectedDocuments": sorted(self.unexpected),
            "differences": [item.as_dict() for item in self.differences],
            "excludableClassifications": sorted(EXCLUDABLE_CLASSIFICATIONS),
            "generationMetadataFields": sorted(GENERATION_METADATA_FIELDS),
        }


def evaluate_regeneration(
    committed: Mapping[str, Mapping[str, Any]],
    regenerated: Mapping[str, Mapping[str, Any]],
) -> RegenerationReport:
    """Compare two sets of records keyed by document name."""
    report = RegenerationReport(documents=len(set(committed) | set(regenerated)))
    report.missing = [name for name in committed if name not in regenerated]
    report.unexpected = [name for name in regenerated if name not in committed]
    for name in sorted(set(committed) & set(regenerated)):
        report.differences.extend(
            diff_documents(committed[name], regenerated[name], document=name)
        )
    return report


def render_differences(differences: Iterable[FieldDifference], *, limit: int = 40) -> str:
    """A structured diff a reader can act on."""
    items = list(differences)
    if not items:
        return "no differences"

    def truncate(value: Any, width: int = 160) -> str:
        text = value if isinstance(value, str) else repr(value)
        return text if len(text) <= width else text[: width - 1] + "…"

    lines: list[str] = []
    current = None
    for item in items[:limit]:
        if item.document != current:
            current = item.document
            lines.append(f"\n{current}")
        lines.append(f"  field path:   {item.path}")
        lines.append(f"  committed:    {truncate(item.committed)}")
        lines.append(f"  regenerated:  {truncate(item.regenerated)}")
        lines.append(f"  classification: {item.classification}"
                     f"{'  (excludable)' if item.excludable else '  (BLOCKING)'}")
        lines.append("")
    if len(items) > limit:
        lines.append(f"... and {len(items) - limit} further difference(s)")
    return "\n".join(lines)

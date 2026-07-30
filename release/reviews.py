"""Independent review packages and the self-review wall.

Four reviews are required — security architecture, encrypted-sync cryptography,
accessibility, and licensing/trademark — and each needs a package containing
eight things before it can be sent, then an identified reviewer and a delivered
report before it can be called complete.

The rule that does the work: a reviewer affiliated with the project is not an
independent reviewer. ``PROJECT_PRINCIPALS`` names the people and organisations
that make up the project, and a review naming any of them as the reviewer is
rejected outright rather than recorded with a caveat. Self-assessment is useful
and this repository contains a lot of it; it is simply not the same artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

REVIEW_KINDS = ("security", "cryptography", "accessibility", "legal")

#: Directory under ``reviews/`` for each kind.
REVIEW_DIRECTORIES: dict[str, str] = {
    "security": "reviews/security",
    "cryptography": "reviews/cryptography",
    "accessibility": "reviews/accessibility",
    "legal": "reviews/legal",
}

#: The eight things a review package must contain before it is sendable.
PACKAGE_SECTIONS = (
    "scope",
    "sourceCommit",
    "threatModel",
    "designDocuments",
    "testResults",
    "knownLimitations",
    "explicitQuestions",
    "expectedDeliverables",
)

REVIEW_STATES = ("not-commissioned", "package-prepared", "commissioned", "in-progress", "delivered", "withdrawn")

#: Identities that are the project. A review naming one of these as reviewer is
#: a self-review. Kept as lowercase substrings so a variation in spelling does
#: not slip past.
PROJECT_PRINCIPALS = frozenset(
    {
        "comradeart",
        "bunny os",
        "bunny-os",
        "bunny os project",
        "project maintainer",
        "maintainer",
        "self",
        "internal",
        "in-house",
    }
)


class ReviewError(ValueError):
    """Raised when a review package or result is malformed or is a self-review."""


def is_self_review(reviewer: str, organisation: str) -> bool:
    """Return whether the named reviewer is the project reviewing itself."""
    haystack = f"{reviewer} {organisation}".casefold()
    return any(principal in haystack for principal in PROJECT_PRINCIPALS)


@dataclass(frozen=True)
class ReviewPackage:
    kind: str
    sections: Mapping[str, Any]

    @property
    def missingSections(self) -> tuple[str, ...]:
        missing = []
        for name in PACKAGE_SECTIONS:
            value = self.sections.get(name)
            if value is None:
                missing.append(name)
            elif isinstance(value, str) and not value.strip():
                missing.append(name)
            elif isinstance(value, (list, tuple)) and not value:
                missing.append(name)
        return tuple(missing)

    @property
    def prepared(self) -> bool:
        return not self.missingSections

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "sections": {name: self.sections.get(name) for name in PACKAGE_SECTIONS},
            "missingSections": list(self.missingSections),
            "prepared": self.prepared,
        }


@dataclass(frozen=True)
class ReviewStatus:
    kind: str
    state: str
    reviewer: str | None
    organisation: str | None
    commissionedAt: str | None
    deliveredAt: str | None
    reportReference: str | None
    findingsSummary: str
    package: ReviewPackage

    @property
    def complete(self) -> bool:
        return (
            self.state == "delivered"
            and bool(self.reviewer)
            and bool(self.reportReference)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "state": self.state,
            "reviewer": self.reviewer,
            "organisation": self.organisation,
            "commissionedAt": self.commissionedAt,
            "deliveredAt": self.deliveredAt,
            "reportReference": self.reportReference,
            "findingsSummary": self.findingsSummary,
            "package": self.package.as_dict(),
            "complete": self.complete,
        }


def parse_review(record: Mapping[str, Any], *, root: Path | None = None) -> ReviewStatus:
    if not isinstance(record, Mapping):
        raise ReviewError("review record must be an object")
    kind = record.get("kind")
    if kind not in REVIEW_KINDS:
        raise ReviewError(f"kind must be one of {', '.join(REVIEW_KINDS)}")
    state = record.get("state")
    if state not in REVIEW_STATES:
        raise ReviewError(f"{kind}: state must be one of {', '.join(REVIEW_STATES)}")

    package = ReviewPackage(kind=kind, sections=record.get("package") or {})

    reviewer = record.get("reviewer")
    organisation = record.get("organisation")
    report_reference = record.get("reportReference")

    if state in {"commissioned", "in-progress", "delivered"}:
        if not reviewer or not organisation:
            raise ReviewError(
                f"{kind}: a commissioned review must name an identifiable reviewer and organisation"
            )
        if is_self_review(str(reviewer), str(organisation)):
            raise ReviewError(
                f"{kind}: reviewer {reviewer!r} of {organisation!r} is affiliated with the project; "
                "a self-review cannot be recorded as an independent review"
            )

    if state == "delivered":
        if not report_reference:
            raise ReviewError(f"{kind}: a delivered review must reference the delivered report")
        if root is not None:
            target = (root / str(report_reference)).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                raise ReviewError(f"{kind}: reportReference escapes the repository") from None
            if not target.is_file():
                raise ReviewError(
                    f"{kind}: reportReference {report_reference} does not exist; a review is not "
                    "delivered until its report is"
                )
        if not package.prepared:
            raise ReviewError(
                f"{kind}: recorded as delivered while the review package is incomplete: "
                + ", ".join(package.missingSections)
            )

    return ReviewStatus(
        kind=kind,
        state=state,
        reviewer=str(reviewer) if reviewer else None,
        organisation=str(organisation) if organisation else None,
        commissionedAt=record.get("commissionedAt"),
        deliveredAt=record.get("deliveredAt"),
        reportReference=str(report_reference) if report_reference else None,
        findingsSummary=str(record.get("findingsSummary", "")),
        package=package,
    )


def evaluate_reviews(document: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise ReviewError("independent review document schemaVersion is invalid")
    raw = document.get("reviews")
    if not isinstance(raw, list):
        raise ReviewError("independent review document must carry a reviews array")

    statuses = [parse_review(item, root=root) for item in raw]
    by_kind = {status.kind: status for status in statuses}
    missing_kinds = sorted(set(REVIEW_KINDS) - set(by_kind))
    complete = sorted(kind for kind, status in by_kind.items() if status.complete)
    outstanding = sorted(set(REVIEW_KINDS) - set(complete))
    packages_ready = sorted(kind for kind, status in by_kind.items() if status.package.prepared)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "reviews": [status.as_dict() for status in statuses],
        "missingKinds": missing_kinds,
        "packagesPrepared": packages_ready,
        "completeReviews": complete,
        "outstandingReviews": outstanding,
        "allComplete": not outstanding and not missing_kinds,
        "result": "PASS" if not outstanding and not missing_kinds else "BLOCKED",
        "note": (
            "A review is complete only with an identifiable independent reviewer and a delivered "
            "report. Preparing a package is progress, not a result."
        ),
    }


def completed_review_identifiers(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Identifiers usable as ``independentReviewReference`` elsewhere.

    Only delivered reviews appear. This is the set that
    ``release.vulnerability`` consults before permitting a severity reduction or
    a non-blocking Critical disposition.
    """
    identifiers: list[str] = []
    for item in document.get("reviews", []):
        if not isinstance(item, Mapping):
            continue
        if item.get("state") != "delivered":
            continue
        identifier = item.get("reviewId") or item.get("reportReference")
        if identifier:
            identifiers.append(str(identifier))
    return tuple(sorted(identifiers))


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "PACKAGE_SECTIONS",
    "PROJECT_PRINCIPALS",
    "REVIEW_DIRECTORIES",
    "REVIEW_KINDS",
    "ReviewError",
    "ReviewPackage",
    "ReviewStatus",
    "completed_review_identifiers",
    "evaluate_reviews",
    "is_self_review",
    "parse_review",
]

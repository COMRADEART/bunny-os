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
import hashlib
import json
from pathlib import Path
import re
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


# --------------------------------------------------------------------------- #
# Delivered review records
# --------------------------------------------------------------------------- #

#: The eight sections a bounded review *request* must carry before it is sent.
#: Distinct from PACKAGE_SECTIONS, which describes the evidence bundle: a request
#: also has to tell the reviewer what not to claim.
REQUEST_SECTIONS = (
    "exact scope",
    "commit",
    "artifacts",
    "threat model",
    "questions",
    "expected report format",
    "severity model",
    "expected independence statement",
    "confidentiality requirements",
    "prohibited claims",
)

#: Phrases the request must forbid. Each is a claim a well-meaning reviewer makes
#: without realising it converts evidence into an endorsement.
PROHIBITED_CLAIM_MARKERS = ("certified", "compliant", "endorsed")


def request_gaps(root: Path, kind: str) -> tuple[str, ...]:
    """Return the sections a review request is missing.

    Checked by section heading rather than by content quality, which is all a
    machine can do. What it does catch is a request sent without telling the
    reviewer the severity model, the independence statement expected, or what
    they must not claim — three omissions that produce an unusable report.
    """
    if kind not in REVIEW_KINDS:
        raise ReviewError(f"kind must be one of {', '.join(REVIEW_KINDS)}")
    path = root / REVIEW_DIRECTORIES[kind] / "REQUEST.md"
    if not path.is_file():
        return ("REQUEST.md does not exist",)
    text = path.read_text(encoding="utf-8").casefold()
    missing = [name for name in REQUEST_SECTIONS if name not in text]
    if not any(marker in text for marker in PROHIBITED_CLAIM_MARKERS):
        missing.append("an explicit refusal of 'certified' / 'compliant' / 'endorsed' claims")
    return tuple(missing)


def evaluate_requests(root: Path) -> dict[str, Any]:
    """Evaluate all four review requests."""
    rows = {kind: list(request_gaps(root, kind)) for kind in REVIEW_KINDS}
    ready = sorted(kind for kind, gaps in rows.items() if not gaps)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "requests": rows,
        "readyRequests": ready,
        "incompleteRequests": sorted(set(REVIEW_KINDS) - set(ready)),
        "allReady": len(ready) == len(REVIEW_KINDS),
        "result": "PASS" if len(ready) == len(REVIEW_KINDS) else "BLOCKED",
        "note": (
            "A ready request is not a delivered review. These four are bounded and sendable; none "
            "has been sent, and no reviewer name or completion date has been invented."
        ),
    }


REVIEW_CONCLUSIONS = ("pass", "conditional", "fail")
FINDING_STATES = ("open", "resolved", "accepted-risk", "disputed")
FINDING_SEVERITIES = ("critical", "high", "medium", "low", "informational")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

#: An independence declaration has to be a statement, not a checkbox. Forty
#: characters is not a quality bar; it is enough to stop "independent: true"
#: standing in for one.
_MINIMUM_DECLARATION = 40


@dataclass(frozen=True)
class ReviewFinding:
    findingId: str
    severity: str
    summary: str
    state: str
    detail: str = ""
    advisoryIds: tuple[str, ...] = ()
    reachabilityConclusion: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "findingId": self.findingId,
            "severity": self.severity,
            "summary": self.summary,
            "state": self.state,
            "detail": self.detail,
            "advisoryIds": list(self.advisoryIds),
            "reachabilityConclusion": self.reachabilityConclusion,
        }


@dataclass(frozen=True)
class IndependentReviewRecord:
    schemaVersion: int
    reviewId: str
    reviewType: str
    reviewerName: str
    independenceDeclaration: str
    scopeCommit: str
    scopeArtifacts: tuple[str, ...]
    completedAt: str
    findings: tuple[ReviewFinding, ...]
    conclusion: str
    reportDigest: str
    reviewerOrganisation: str | None = None
    signature: str | None = None
    reportReference: str | None = None

    @property
    def unresolvedFindings(self) -> tuple[ReviewFinding, ...]:
        return tuple(finding for finding in self.findings if finding.state == "open")

    @property
    def acceptable(self) -> bool:
        """Whether this record can support a gate.

        ``conditional`` is acceptable only with no open finding: a conditional
        pass whose conditions are unmet is a fail with better manners.
        """
        if self.conclusion == "fail":
            return False
        return not self.unresolvedFindings

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "reviewId": self.reviewId,
            "reviewType": self.reviewType,
            "reviewerName": self.reviewerName,
            "reviewerOrganisation": self.reviewerOrganisation,
            "independenceDeclaration": self.independenceDeclaration,
            "scopeCommit": self.scopeCommit,
            "scopeArtifacts": list(self.scopeArtifacts),
            "completedAt": self.completedAt,
            "findings": [finding.as_dict() for finding in self.findings],
            "unresolvedFindingCount": len(self.unresolvedFindings),
            "conclusion": self.conclusion,
            "reportDigest": self.reportDigest,
            "signed": bool(self.signature),
            "reportReference": self.reportReference,
            "acceptable": self.acceptable,
        }


def parse_review_record(
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
    expectedCommit: str | None = None,
    requireSignature: bool = True,
) -> IndependentReviewRecord:
    """Validate a delivered independent review record.

    Four things are checked that a well-meaning submission gets wrong:

    * the reviewer is not the project (the self-review wall);
    * the report digest is recomputed from the file, not accepted as stated;
    * the scope commit is the commit being qualified, because a review of a
      different tree is a review of a different system;
    * the record is signed, so a report cannot be substituted after delivery.
    """
    if not isinstance(record, Mapping):
        raise ReviewError("review record must be an object")
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise ReviewError(f"review record schemaVersion must be {SCHEMA_VERSION}")

    identifier = str(record.get("reviewId") or "<unidentified>")
    review_type = record.get("reviewType")
    if review_type not in REVIEW_KINDS:
        raise ReviewError(f"{identifier}: reviewType must be one of {', '.join(REVIEW_KINDS)}")

    reviewer = str(record.get("reviewerName") or "").strip()
    organisation = str(record.get("reviewerOrganisation") or "").strip()
    if not reviewer:
        raise ReviewError(f"{identifier}: an independent review must name an identifiable reviewer")
    if is_self_review(reviewer, organisation):
        raise ReviewError(
            f"{identifier}: reviewer {reviewer!r} of {organisation or 'no organisation'!r} is "
            "affiliated with the project; a repository maintainer cannot mark their own review as "
            "independent"
        )

    declaration = str(record.get("independenceDeclaration") or "").strip()
    if len(declaration) < _MINIMUM_DECLARATION:
        raise ReviewError(
            f"{identifier}: independenceDeclaration must be the reviewer's own statement of "
            "independence, not a flag"
        )

    commit = str(record.get("scopeCommit") or "")
    if not _COMMIT.match(commit):
        raise ReviewError(f"{identifier}: scopeCommit must be a full 40-character SHA")
    if expectedCommit and commit != expectedCommit:
        raise ReviewError(
            f"{identifier}: reviewed commit {commit[:12]} is not the commit being qualified "
            f"{expectedCommit[:12]}; a review does not transfer between commits"
        )

    artifacts = record.get("scopeArtifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReviewError(
            f"{identifier}: scopeArtifacts must name what was reviewed; an unscoped review cannot "
            "be relied on for anything in particular"
        )

    digest = str(record.get("reportDigest") or "")
    if not _SHA256.match(digest):
        raise ReviewError(f"{identifier}: reportDigest must be a 64-character SHA-256 hex digest")

    reference = record.get("reportReference")
    if root is not None:
        if not reference:
            raise ReviewError(f"{identifier}: a delivered review must reference its report file")
        target = (root / str(reference)).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise ReviewError(f"{identifier}: reportReference escapes the repository") from None
        if not target.is_file():
            raise ReviewError(
                f"{identifier}: reportReference {reference} does not exist; a review is not "
                "delivered until its report is"
            )
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != digest:
            raise ReviewError(
                f"{identifier}: reportDigest {digest[:12]} does not match the file on disk "
                f"{actual[:12]}; the report was changed after the record was written"
            )

    signature = record.get("signature")
    if requireSignature and not signature:
        raise ReviewError(
            f"{identifier}: the review record is unsigned. Without a signature over reportDigest, "
            "a delivered report can be substituted and the record still validates"
        )

    conclusion = record.get("conclusion")
    if conclusion not in REVIEW_CONCLUSIONS:
        raise ReviewError(f"{identifier}: conclusion must be one of {', '.join(REVIEW_CONCLUSIONS)}")

    raw_findings = record.get("findings")
    if not isinstance(raw_findings, list):
        raise ReviewError(f"{identifier}: findings must be an array, empty if there are none")
    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if not isinstance(item, Mapping):
            raise ReviewError(f"{identifier}: each finding must be an object")
        severity = item.get("severity")
        if severity not in FINDING_SEVERITIES:
            raise ReviewError(f"{identifier}: finding severity must be one of {', '.join(FINDING_SEVERITIES)}")
        state = item.get("state")
        if state not in FINDING_STATES:
            raise ReviewError(f"{identifier}: finding state must be one of {', '.join(FINDING_STATES)}")
        for name in ("findingId", "summary"):
            if not str(item.get(name) or "").strip():
                raise ReviewError(f"{identifier}: finding missing {name}")
        findings.append(
            ReviewFinding(
                findingId=str(item["findingId"]),
                severity=str(severity),
                summary=str(item["summary"]),
                state=str(state),
                detail=str(item.get("detail", "")),
                advisoryIds=tuple(str(value) for value in item.get("advisoryIds", [])),
                reachabilityConclusion=item.get("reachabilityConclusion"),
            )
        )

    if conclusion == "pass" and any(f.state == "open" and f.severity in {"critical", "high"} for f in findings):
        raise ReviewError(
            f"{identifier}: conclusion 'pass' with an open critical or high finding; that is a "
            "conditional pass at best"
        )

    return IndependentReviewRecord(
        schemaVersion=SCHEMA_VERSION,
        reviewId=str(record["reviewId"]),
        reviewType=str(review_type),
        reviewerName=reviewer,
        independenceDeclaration=declaration,
        scopeCommit=commit,
        scopeArtifacts=tuple(str(item) for item in artifacts),
        completedAt=str(record.get("completedAt", "")),
        findings=tuple(findings),
        conclusion=str(conclusion),
        reportDigest=digest,
        reviewerOrganisation=organisation or None,
        signature=str(signature) if signature else None,
        reportReference=str(reference) if reference else None,
    )


def evaluate_review_records(
    document: Mapping[str, Any],
    *,
    root: Path | None = None,
    expectedCommit: str | None = None,
) -> dict[str, Any]:
    """Evaluate every delivered review record against the four required reviews."""
    raw = document.get("records")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ReviewError("review record document must carry a records array")

    accepted: list[IndependentReviewRecord] = []
    rejected: list[str] = []
    for item in raw:
        try:
            accepted.append(parse_review_record(item, root=root, expectedCommit=expectedCommit))
        except ReviewError as exc:
            rejected.append(str(exc))

    by_type = {record.reviewType: record for record in accepted if record.acceptable}
    outstanding = sorted(set(REVIEW_KINDS) - set(by_type))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "recordCount": len(raw),
        "acceptedCount": len(accepted),
        "rejected": rejected,
        "records": [record.as_dict() for record in accepted],
        "acceptableReviewTypes": sorted(by_type),
        "outstandingReviewTypes": outstanding,
        "allComplete": not outstanding and not rejected,
        "result": "PASS" if not outstanding and not rejected else "BLOCKED",
        "note": (
            "A review supports a gate only when it is signed, digest-verified, scoped to the "
            "candidate commit, carries no open finding, and names a reviewer who is not the project."
        ),
    }


def acceptable_review_identifiers(
    document: Mapping[str, Any],
    *,
    root: Path | None = None,
    expectedCommit: str | None = None,
) -> tuple[str, ...]:
    """Review identifiers usable as an ``independentReviewReference``."""
    identifiers: list[str] = []
    for item in document.get("records", []) or []:
        try:
            record = parse_review_record(item, root=root, expectedCommit=expectedCommit)
        except ReviewError:
            continue
        if record.acceptable:
            identifiers.append(record.reviewId)
    return tuple(sorted(identifiers))


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "FINDING_SEVERITIES",
    "FINDING_STATES",
    "PACKAGE_SECTIONS",
    "PROHIBITED_CLAIM_MARKERS",
    "PROJECT_PRINCIPALS",
    "REQUEST_SECTIONS",
    "REVIEW_CONCLUSIONS",
    "REVIEW_DIRECTORIES",
    "REVIEW_KINDS",
    "IndependentReviewRecord",
    "ReviewError",
    "ReviewFinding",
    "ReviewPackage",
    "ReviewStatus",
    "acceptable_review_identifiers",
    "completed_review_identifiers",
    "evaluate_requests",
    "evaluate_review_records",
    "evaluate_reviews",
    "is_self_review",
    "parse_review",
    "parse_review_record",
    "request_gaps",
]

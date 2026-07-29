"""Structured, privacy-preserving beta feedback ingestion and duplicate hints."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping

from .redaction import redact
from .taxonomy import is_high_severity, validate_component, validate_severity


REQUIRED_FIELDS = frozenset({
    "source", "sourceId", "affectedVersion", "component", "severity", "reproducibility",
    "environment", "owner", "targetRelease", "workaround", "verificationStatus", "closureEvidence",
    "symptomText", "affectedWorkflow",
})
ALLOWED_FIELDS = REQUIRED_FIELDS | frozenset({"errorSignature", "stackSignature", "hardwareClass", "kernelVersion", "imageVersion", "evidenceLinks"})
VERIFICATION_STATES = frozenset({"unverified", "reproduced", "fix_pending", "fixed_unverified", "verified", "closed"})
REPRODUCIBILITY = frozenset({"always", "intermittent", "once", "not_reproduced", "unknown"})


def stable_issue_id(source: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{source}\0{source_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"BETA-{digest}"


@dataclass(frozen=True)
class FeedbackIssue:
    issue_id: str
    data: dict[str, Any]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "FeedbackIssue":
        if set(raw) - ALLOWED_FIELDS or not REQUIRED_FIELDS.issubset(raw):
            raise ValueError("feedback fields do not match schema version 1")
        source = raw.get("source")
        source_id = raw.get("sourceId")
        if not isinstance(source, str) or not source or len(source) > 64:
            raise ValueError("feedback source is invalid")
        if not isinstance(source_id, str) or not source_id or len(source_id) > 128:
            raise ValueError("feedback source ID is invalid")
        validate_component(raw.get("component"))
        validate_severity(raw.get("severity"))
        if raw.get("reproducibility") not in REPRODUCIBILITY:
            raise ValueError("reproducibility is invalid")
        if raw.get("verificationStatus") not in VERIFICATION_STATES:
            raise ValueError("verification status is invalid")
        if not isinstance(raw.get("environment"), Mapping):
            raise ValueError("environment must be an object")
        links = raw.get("evidenceLinks", [])
        if not isinstance(links, list) or not all(isinstance(item, str) and item.startswith("https://") for item in links):
            raise ValueError("evidence links must use HTTPS")
        clean = redact(dict(raw))
        if not isinstance(clean, dict):
            raise AssertionError("redaction changed the document type")
        clean["severityStatus"] = "human-confirmation-required"
        clean["mergeStatus"] = "unmerged"
        return cls(stable_issue_id(source, source_id), clean)

    def export(self) -> dict[str, Any]:
        return {"schemaVersion": 1, "issueId": self.issue_id, **self.data}


def ingest_documents(documents: Iterable[Mapping[str, Any]]) -> list[FeedbackIssue]:
    issues: dict[str, FeedbackIssue] = {}
    for document in documents:
        issue = FeedbackIssue.parse(document)
        if issue.issue_id in issues:
            raise ValueError("duplicate source/sourceId in feedback import")
        issues[issue.issue_id] = issue
    return [issues[key] for key in sorted(issues)]


def _tokens(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {token for token in value.casefold().replace("/", " ").replace("-", " ").split() if len(token) >= 3}


def suggest_duplicates(issues: Iterable[FeedbackIssue], minimum_score: int = 4) -> list[dict[str, Any]]:
    values = list(issues)
    suggestions: list[dict[str, Any]] = []
    exact_fields = ("component", "errorSignature", "stackSignature", "hardwareClass", "kernelVersion", "imageVersion", "affectedWorkflow")
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            score = sum(1 for field in exact_fields if left.data.get(field) and left.data.get(field) == right.data.get(field))
            overlap = _tokens(left.data.get("symptomText")) & _tokens(right.data.get("symptomText"))
            score += min(3, len(overlap))
            if score < minimum_score:
                continue
            high = is_high_severity(str(left.data["severity"])) or is_high_severity(str(right.data["severity"]))
            suggestions.append({
                "left": left.issue_id,
                "right": right.issue_id,
                "score": score,
                "sharedSymptomTokens": sorted(overlap),
                "action": "suggest-only",
                "humanConfirmationRequired": high,
            })
    return sorted(suggestions, key=lambda item: (-int(item["score"]), str(item["left"]), str(item["right"])))

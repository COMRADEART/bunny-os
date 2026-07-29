"""Stable qualification decision engine with mandatory fail-closed evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "UNKNOWN", "NOT_RUN"})
REQUIRED_AUTOMATED = (
    "source_integrity", "reproducible_build", "dependency_validation", "unit_tests", "integration_tests",
    "installer", "encryption", "updates", "rollback", "recovery", "migration", "multi_user",
    "bunny_disabled", "local_only", "security", "privacy", "network", "accessibility", "hardware",
    "image_inspection", "signature_verification", "sbom", "licensing", "malware_scan", "documentation",
)
REQUIRED_APPROVALS = (
    "Engineering", "Release", "Security", "Privacy", "Accessibility", "Installer", "Hardware", "Documentation", "Maintenance",
)
HARD_BLOCKERS = frozenset({
    "unresolved-blocker", "unresolved-critical", "common-installer-high", "encryption-failure", "key-leakage",
    "wrong-disk", "signature-bypass", "rollback-failure", "recovery-media-failure", "cross-user-exposure",
    "public-bunny-listener", "unexpected-network", "inaccessible-essential-workflow", "unsigned-artifact",
    "missing-checksum", "broken-supported-migration", "license-violation", "missing-security-process", "untested-release-rollback",
})


@dataclass(frozen=True)
class GateDecision:
    recommendation: str
    missing: tuple[str, ...]
    failing: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.recommendation == "GO"

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "missingEvidence": list(self.missing),
            "failingEvidence": list(self.failing),
            "blockers": list(self.blockers),
            "stable": self.passed,
        }


def evaluate_release(evidence: Mapping[str, Any], approvals: Mapping[str, Any], blockers: Iterable[str]) -> GateDecision:
    unknown = []
    failing = []
    for requirement in REQUIRED_AUTOMATED:
        status = evidence.get(requirement, "UNKNOWN")
        if status not in STATUSES:
            raise ValueError(f"invalid evidence status for {requirement}")
        if status in {"UNKNOWN", "NOT_RUN", "BLOCKED"}:
            unknown.append(requirement)
        elif status == "FAIL":
            failing.append(requirement)
    for owner in REQUIRED_APPROVALS:
        if approvals.get(owner) != "APPROVED":
            unknown.append(f"approval:{owner}")
    blocker_values = sorted(set(blockers))
    unsupported = [value for value in blocker_values if value not in HARD_BLOCKERS]
    if unsupported:
        raise ValueError("unknown stable release blocker code")
    recommendation = "GO" if not unknown and not failing and not blocker_values else "NO-GO"
    return GateDecision(recommendation, tuple(sorted(unknown)), tuple(sorted(failing)), tuple(blocker_values))

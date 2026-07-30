"""Separated release and pilot gates.

Four gates, deliberately not nested into one another's success:

``stable-release``
    The complete evidence record plus the nine protected approvals plus an empty
    blocker list. This is the only gate that authorises calling anything stable.

``oem-pilot``, ``enterprise-pilot``, ``sync-pilot``
    Each requires the stable gate *plus* its own additional requirements. A
    passing source gate contributes nothing here: source completeness was never
    evidence that a device may be manufactured, a fleet deployed, or a hosted
    service launched.

Each pilot gate names its additional requirements explicitly rather than
inheriting a generic list, because the three pilots fail for different reasons
and a merged list would hide which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

GATES = ("stable-release", "oem-pilot", "enterprise-pilot", "sync-pilot")

#: Additional requirements per pilot, over and above a passing stable gate.
OEM_PILOT_REQUIREMENTS: dict[str, str] = {
    "qualifiedHardwareModel": "at least one hardware model qualified end to end on physical hardware",
    "oemRecoveryValidation": "OEM recovery media built, booted, and validated on that model",
    "signedOemProfile": "an OEM profile signed with a key in the oem- namespace",
    "factoryFinalisationOnHardware": "factory finalisation executed on real hardware, not a supplied record",
    "brandingAndLicensingApproval": "branding and licensing approved for OEM distribution",
    "namedSupportOwner": "a named person accountable for supporting the pilot devices",
}

ENTERPRISE_PILOT_REQUIREMENTS: dict[str, str] = {
    "fleetControlPlaneImplemented": "a fleet control plane exists and is implemented, not merely designed",
    "tenantIsolationPenetrationTest": "an adversarial multi-tenant isolation test performed by someone other than the author",
    "enrolmentServiceDeployed": "an enrolment service deployed and reachable",
    "consoleRoleTesting": "each console role exercised against the deployed service",
    "incidentResponseOwner": "a named incident-response owner",
    "supportCapacity": "confirmed capacity to support enrolled organisations",
}

SYNC_PILOT_REQUIREMENTS: dict[str, str] = {
    "independentCryptographicReview": "an independent cryptographic review, delivered",
    "operatedSyncService": "a sync service actually operated, not designed",
    "keyRecoveryDrill": "a key-recovery drill performed and evidenced",
    "deletionDrill": "a deletion drill performed and evidenced across the disclosed retention bounds",
    "servicePrivacyReview": "a privacy review of the operated service",
    "dataResidencyDisclosure": "a published data-residency disclosure",
    "incidentResponseOwner": "a named incident-response owner",
}

PILOT_REQUIREMENTS: dict[str, dict[str, str]] = {
    "oem-pilot": OEM_PILOT_REQUIREMENTS,
    "enterprise-pilot": ENTERPRISE_PILOT_REQUIREMENTS,
    "sync-pilot": SYNC_PILOT_REQUIREMENTS,
}


class GateError(ValueError):
    """Raised when gate input is malformed."""


@dataclass(frozen=True)
class GateResult:
    gate: str
    recommendation: str
    unmet: tuple[str, ...]
    satisfied: tuple[str, ...]
    detail: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.recommendation == "GO"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "gate": self.gate,
            "recommendation": self.recommendation,
            "unmetRequirements": list(self.unmet),
            "satisfiedRequirements": list(self.satisfied),
            "detail": dict(self.detail),
            "note": (
                "A source gate never implies a pilot approval. Each pilot requires a passing stable "
                "release gate plus its own additional requirements."
            ),
        }


@dataclass(frozen=True)
class StableInputs:
    """Everything the stable gate consults, gathered by the caller."""

    evidenceComplete: bool
    evidenceDetail: Mapping[str, Any]
    approvals: Mapping[str, str]
    blockers: tuple[str, ...]
    vulnerabilityBlocked: bool
    vulnerabilityDetail: Mapping[str, Any]
    licenceGatePassed: bool
    licenceDetail: Mapping[str, Any]
    reproducibilityIndependent: bool
    signingProductionReady: bool
    candidateComplete: bool
    minimisationComplete: bool
    hardwareQualified: bool
    reviewsComplete: bool
    matricesComplete: bool


REQUIRED_APPROVALS = (
    "Engineering",
    "Release",
    "Security",
    "Privacy",
    "Accessibility",
    "Installer",
    "Hardware",
    "Documentation",
    "Maintenance",
)


def evaluate_stable_gate(inputs: StableInputs) -> GateResult:
    """The stable release gate. Every condition must hold."""
    unmet: list[str] = []
    satisfied: list[str] = []

    def check(name: str, ok: bool, why: str) -> None:
        if ok:
            satisfied.append(name)
        else:
            unmet.append(f"{name}: {why}")

    check("evidence-record", inputs.evidenceComplete, "the stable evidence record is incomplete or blocking")
    check("vulnerability-position", not inputs.vulnerabilityBlocked, "unresolved Critical or High findings block the release")
    check("licence", inputs.licenceGatePassed, "the licence gate has not passed")
    check("package-minimisation", inputs.minimisationComplete, "package minimisation is not complete")
    check("independent-builder-reproducibility", inputs.reproducibilityIndependent, "no two-builder reproducibility evidence exists")
    check("production-signing", inputs.signingProductionReady, "no production signing keys exist; development keys cannot satisfy a release gate")
    check("candidate-artifacts", inputs.candidateComplete, "the candidate artifact set is incomplete or unverified")
    check("qualification-matrices", inputs.matricesComplete, "installation, encryption, update, rollback or recovery matrices are incomplete")
    check("physical-hardware", inputs.hardwareQualified, "no physical machine has been qualified")
    check("independent-reviews", inputs.reviewsComplete, "one or more independent reviews are outstanding")

    pending = [owner for owner in REQUIRED_APPROVALS if inputs.approvals.get(owner) != "APPROVED"]
    check("approvals", not pending, "approvals pending: " + ", ".join(pending) if pending else "")

    blockers = tuple(sorted(set(inputs.blockers)))
    check("blockers", not blockers, "open blocker codes: " + ", ".join(blockers) if blockers else "")

    recommendation = "GO" if not unmet else "NO-GO"
    return GateResult(
        gate="stable-release",
        recommendation=recommendation,
        unmet=tuple(unmet),
        satisfied=tuple(satisfied),
        detail={
            "evidence": dict(inputs.evidenceDetail),
            "vulnerability": dict(inputs.vulnerabilityDetail),
            "licence": dict(inputs.licenceDetail),
            "approvalsPending": pending,
            "blockers": list(blockers),
        },
    )


def evaluate_pilot_gate(
    gate: str,
    *,
    stable: GateResult,
    requirements: Mapping[str, Any],
) -> GateResult:
    """A pilot gate: the stable gate, plus this pilot's own requirements."""
    if gate not in PILOT_REQUIREMENTS:
        raise GateError(f"unknown pilot gate {gate!r}")

    definitions = PILOT_REQUIREMENTS[gate]
    unknown = sorted(set(requirements) - set(definitions))
    if unknown:
        raise GateError(f"{gate}: unknown requirements declared: {', '.join(unknown)}")

    unmet: list[str] = []
    satisfied: list[str] = []

    if not stable.passed:
        unmet.append(
            "stable-release: the stable release gate reports "
            f"{stable.recommendation}; no pilot may begin without a published, signed stable release"
        )
    else:
        satisfied.append("stable-release")

    for name, description in sorted(definitions.items()):
        value = requirements.get(name)
        if value is True:
            satisfied.append(name)
        else:
            unmet.append(f"{name}: {description}")

    recommendation = "GO" if not unmet else "BLOCKED"
    return GateResult(
        gate=gate,
        recommendation=recommendation,
        unmet=tuple(unmet),
        satisfied=tuple(satisfied),
        detail={
            "stableRecommendation": stable.recommendation,
            "additionalRequirementCount": len(definitions),
        },
    )


def assert_no_unprotected_go(results: Iterable[GateResult], *, protectedEvidencePresent: bool) -> None:
    """CI backstop: a GO without protected evidence is a defect, not a result.

    Called by the pilot-gate closure assertion in CI. If any gate reports GO
    while the protected evidence that would justify it is absent, raise — a
    green pipeline that authorises a pilot is worse than a red one.
    """
    for result in results:
        if result.passed and not protectedEvidencePresent:
            raise GateError(
                f"{result.gate} reports GO but no protected evidence is present in this environment; "
                "pull-request CI has no production signing access and cannot legitimately reach GO"
            )


__all__ = [
    "ENTERPRISE_PILOT_REQUIREMENTS",
    "GATES",
    "OEM_PILOT_REQUIREMENTS",
    "PILOT_REQUIREMENTS",
    "REQUIRED_APPROVALS",
    "SYNC_PILOT_REQUIREMENTS",
    "GateError",
    "GateResult",
    "StableInputs",
    "assert_no_unprotected_go",
    "evaluate_pilot_gate",
    "evaluate_stable_gate",
]

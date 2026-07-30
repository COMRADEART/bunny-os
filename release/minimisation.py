"""Package minimisation with protected categories.

Removing packages is a legitimate way to shrink an attack surface and an
illegitimate way to shrink a scan report. The difference is visible in *which*
packages get removed, so five categories are protected outright:

recovery tools, accessibility tools, required firmware, installer dependencies,
and security tooling.

A removal touching any of them is rejected, not warned about. A user who cannot
run a screen reader, or who cannot boot recovery media, is worse off than a user
whose scan report has a higher number in it.

Every accepted removal must also carry the five verification steps the brief
requires — rebuild, boot, tests, SBOM regeneration, rescan — each with evidence.
A removal recorded without them is incomplete, not merely undocumented.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

PACKAGE_CATEGORIES = (
    "recovery-tool",
    "accessibility-tool",
    "required-firmware",
    "installer-dependency",
    "security-tooling",
    "developer-tooling",
    "desktop-application",
    "documentation",
    "optional-runtime",
    "transitive-dependency",
)

#: Categories that may never be removed to reduce a vulnerability count.
PROTECTED_CATEGORIES = frozenset(
    {
        "recovery-tool",
        "accessibility-tool",
        "required-firmware",
        "installer-dependency",
        "security-tooling",
    }
)

#: The five verification steps every removal must evidence.
VERIFICATION_STEPS = (
    "rebuilt",
    "booted",
    "testsRun",
    "sbomRegenerated",
    "vulnerabilityScanRerun",
)

PROFILES = ("developer", "desktop", "beta", "stable", "minimal", "recovery", "live", "shell")


class MinimisationError(ValueError):
    """Raised when a removal record is malformed or touches a protected category."""


@dataclass(frozen=True)
class Removal:
    package: str
    profiles: tuple[str, ...]
    category: str
    whyPresent: str
    dependentsChecked: bool
    dependents: tuple[str, ...]
    rationale: str
    verification: Mapping[str, bool]
    evidenceReference: str
    recordedAt: str

    @property
    def missingVerification(self) -> tuple[str, ...]:
        return tuple(name for name in VERIFICATION_STEPS if not self.verification.get(name))

    @property
    def complete(self) -> bool:
        return self.dependentsChecked and not self.dependents and not self.missingVerification

    def as_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "profiles": list(self.profiles),
            "category": self.category,
            "whyPresent": self.whyPresent,
            "dependentsChecked": self.dependentsChecked,
            "dependents": list(self.dependents),
            "rationale": self.rationale,
            "verification": dict(self.verification),
            "missingVerification": list(self.missingVerification),
            "evidenceReference": self.evidenceReference,
            "recordedAt": self.recordedAt,
            "complete": self.complete,
        }


def parse_removal(record: Mapping[str, Any]) -> Removal:
    if not isinstance(record, Mapping):
        raise MinimisationError("removal record must be an object")
    required = (
        "package",
        "profiles",
        "category",
        "whyPresent",
        "dependentsChecked",
        "rationale",
        "verification",
        "evidenceReference",
        "recordedAt",
    )
    missing = [name for name in required if name not in record]
    if missing:
        raise MinimisationError(f"removal record missing fields: {', '.join(missing)}")

    package = str(record["package"])
    category = record["category"]
    if category not in PACKAGE_CATEGORIES:
        raise MinimisationError(f"{package}: category must be one of {', '.join(PACKAGE_CATEGORIES)}")
    if category in PROTECTED_CATEGORIES:
        raise MinimisationError(
            f"{package}: {category} is a protected category and may not be removed; reducing a "
            "vulnerability count is not a reason to remove recovery, accessibility, firmware, "
            "installer or security functionality"
        )

    profiles = record["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise MinimisationError(f"{package}: profiles must be a non-empty list")
    unknown = sorted(set(map(str, profiles)) - set(PROFILES))
    if unknown:
        raise MinimisationError(f"{package}: unknown profiles: {', '.join(unknown)}")

    if not isinstance(record["dependentsChecked"], bool):
        raise MinimisationError(f"{package}: dependentsChecked must be a boolean")
    dependents = tuple(str(name) for name in record.get("dependents", []))
    if dependents:
        raise MinimisationError(
            f"{package}: cannot be removed while these required features depend on it: "
            + ", ".join(dependents)
        )

    verification = record["verification"]
    if not isinstance(verification, Mapping):
        raise MinimisationError(f"{package}: verification must be an object")
    unknown_steps = sorted(set(verification) - set(VERIFICATION_STEPS))
    if unknown_steps:
        raise MinimisationError(f"{package}: unknown verification steps: {', '.join(unknown_steps)}")
    for name, value in verification.items():
        if not isinstance(value, bool):
            raise MinimisationError(f"{package}: verification step {name} must be a boolean")

    for name in ("whyPresent", "rationale", "evidenceReference"):
        if not str(record[name]).strip():
            raise MinimisationError(f"{package}: {name} must not be empty")

    return Removal(
        package=package,
        profiles=tuple(str(name) for name in profiles),
        category=str(category),
        whyPresent=str(record["whyPresent"]),
        dependentsChecked=bool(record["dependentsChecked"]),
        dependents=dependents,
        rationale=str(record["rationale"]),
        verification={str(k): bool(v) for k, v in verification.items()},
        evidenceReference=str(record["evidenceReference"]),
        recordedAt=str(record["recordedAt"]),
    )


@dataclass(frozen=True)
class RetentionDecision:
    package: str
    category: str
    reason: str
    profiles: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "category": self.category,
            "reason": self.reason,
            "profiles": list(self.profiles),
        }


def parse_retention(record: Mapping[str, Any]) -> RetentionDecision:
    for name in ("package", "category", "reason", "profiles"):
        if name not in record:
            raise MinimisationError(f"retention record missing {name}")
    if record["category"] not in PACKAGE_CATEGORIES:
        raise MinimisationError(f"{record['package']}: unknown category {record['category']!r}")
    return RetentionDecision(
        package=str(record["package"]),
        category=str(record["category"]),
        reason=str(record["reason"]),
        profiles=tuple(str(name) for name in record["profiles"]),
    )


def evaluate_minimisation(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise MinimisationError("package minimisation document schemaVersion is invalid")

    removals = [parse_removal(item) for item in document.get("removals", [])]
    retentions = [parse_retention(item) for item in document.get("retained", [])]
    reviewed = document.get("reviewedProfiles")
    if not isinstance(reviewed, list) or not reviewed:
        raise MinimisationError("package minimisation must record which profiles were reviewed")
    unknown = sorted(set(map(str, reviewed)) - set(PROFILES))
    if unknown:
        raise MinimisationError("unknown reviewed profiles: " + ", ".join(unknown))

    incomplete = [removal.package for removal in removals if not removal.complete]
    protected_retained = sorted(
        {retention.package for retention in retentions if retention.category in PROTECTED_CATEGORIES}
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reviewedProfiles": sorted(str(name) for name in reviewed),
        "removals": [removal.as_dict() for removal in removals],
        "retained": [retention.as_dict() for retention in retentions],
        "removalCount": len(removals),
        "retainedCount": len(retentions),
        "protectedPackagesRetained": protected_retained,
        "incompleteRemovals": incomplete,
        "complete": not incomplete,
        "result": "PASS" if not incomplete else "BLOCKED",
        "note": (
            "Protected categories — recovery, accessibility, firmware, installer and security — are "
            "retained by rule. Every removal carries rebuild, boot, test, SBOM and rescan evidence."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "PACKAGE_CATEGORIES",
    "PROTECTED_CATEGORIES",
    "VERIFICATION_STEPS",
    "MinimisationError",
    "Removal",
    "RetentionDecision",
    "evaluate_minimisation",
    "parse_removal",
    "parse_retention",
]

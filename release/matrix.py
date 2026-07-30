"""Qualification matrices: installation, encryption, update, rollback, recovery,
data preservation and accessibility.

One mechanism serves all of them because they share the same failure mode: a
scenario gets marked ``PASS`` on the strength of having read the code that would
handle it. Every result therefore records *how* it was produced, and two
matrices refuse ``source-inspection`` as a basis for passing at all:

* recovery media, because the brief says no recovery claim may rest on source
  inspection, and a recovery tool that has never booted is a hypothesis;
* accessibility, because the brief says static tests are not sufficient, and
  this is the gap that risks harm rather than merely missing evidence.

A matrix is complete only when every scenario resolves. ``NOT_APPLICABLE``
requires a reason, so "we skipped it" and "it cannot apply here" stay distinct.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: How a result was produced, weakest to strongest.
METHODS = (
    "source-inspection",
    "unit-test",
    "virtual-machine",
    "physical-hardware",
    "manual-procedure",
)

OUTCOMES = ("PASS", "FAIL", "NOT_APPLICABLE", "NOT_RUN", "BLOCKED")

#: Matrices where source inspection can never establish a pass.
RUNTIME_ONLY_MATRICES = frozenset({"recovery-media", "accessibility"})

MATRICES: dict[str, tuple[str, ...]] = {
    "installation": (
        "empty-uefi-disk",
        "encrypted-uefi-installation",
        "unencrypted-installation",
        "offline-installation",
        "multiple-disks",
        "nvme-like-virtual-disk",
        "sata-like-virtual-disk",
        "existing-linux-replacement",
        "supported-free-space-installation",
        "interrupted-installation",
        "bootloader-failure",
        "recovery-installation",
    ),
    "encryption": (
        "luks-password-unlock",
        "recovery-key",
        "incorrect-password",
        "missing-recovery-key",
        "tpm-fallback",
        "secure-boot-interaction",
        "update-after-encryption",
        "rollback-after-encryption",
        "recovery-media-access",
    ),
    "update": (
        "current-to-next-candidate",
        "interrupted-download",
        "interrupted-staging",
        "insufficient-disk",
        "invalid-signature",
        "expired-metadata",
        "wrong-architecture",
        "failed-service-health",
        "failed-graphical-session",
        "failed-bunny-contract",
        "automatic-rollback-recommendation",
        "manual-rollback",
        "recovery-assisted-rollback",
    ),
    "rollback": (
        "manual-rollback",
        "automatic-rollback-recommendation",
        "recovery-assisted-rollback",
        "rollback-after-encryption",
        "rollback-preserves-user-data",
    ),
    "recovery-media": (
        "boots-independently",
        "verifies-own-signature",
        "encrypted-access-requires-credentials",
        "mounts-user-data-read-only-by-default",
        "inspects-deployments",
        "selects-previous-deployment",
        "repairs-boot-entries",
        "disables-bunny",
        "disables-plugins",
        "enters-safe-graphics",
        "exports-redacted-diagnostics",
    ),
    "preservation": (
        "home",
        "bunny-database",
        "bunny-memory",
        "provider-aliases",
        "local-models",
        "plugins",
        "workspaces",
        "applications",
        "settings",
        "checkpoints",
    ),
    "accessibility": (
        "installer-keyboard-navigation",
        "installer-screen-reader",
        "encryption-prompt",
        "first-run",
        "login",
        "bunny-launcher",
        "bunny-approvals",
        "update-ui",
        "rollback-ui",
        "recovery-ui",
        "diagnostics-export",
        "high-contrast",
        "text-scaling",
        "reduced-motion",
    ),
}


class MatrixError(ValueError):
    """Raised when a matrix result is malformed or rests on an insufficient method."""


@dataclass(frozen=True)
class MatrixResult:
    scenario: str
    outcome: str
    method: str
    evidenceReference: str | None
    recordedAt: str
    notes: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome,
            "method": self.method,
            "evidenceReference": self.evidenceReference,
            "recordedAt": self.recordedAt,
            "notes": self.notes,
            "reason": self.reason,
        }


def parse_result(matrix: str, record: Mapping[str, Any], *, root: Path | None = None) -> MatrixResult:
    if matrix not in MATRICES:
        raise MatrixError(f"unknown matrix {matrix!r}")
    if not isinstance(record, Mapping):
        raise MatrixError(f"{matrix}: result must be an object")

    scenario = record.get("scenario")
    if scenario not in MATRICES[matrix]:
        raise MatrixError(f"{matrix}: unknown scenario {scenario!r}")
    outcome = record.get("outcome")
    if outcome not in OUTCOMES:
        raise MatrixError(f"{matrix}/{scenario}: outcome must be one of {', '.join(OUTCOMES)}")
    method = record.get("method")
    if method not in METHODS:
        raise MatrixError(f"{matrix}/{scenario}: method must be one of {', '.join(METHODS)}")
    recorded_at = record.get("recordedAt")
    if not recorded_at:
        raise MatrixError(f"{matrix}/{scenario}: recordedAt is required")

    evidence = record.get("evidenceReference")

    if outcome in {"PASS", "FAIL"}:
        if not evidence:
            raise MatrixError(
                f"{matrix}/{scenario}: a {outcome} result must reference the evidence that produced it"
            )
        if root is not None:
            target = (root / str(evidence)).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                raise MatrixError(f"{matrix}/{scenario}: evidenceReference escapes the repository") from None
            if not target.exists():
                raise MatrixError(
                    f"{matrix}/{scenario}: evidence artifact {evidence} does not exist"
                )

    if outcome == "PASS" and matrix in RUNTIME_ONLY_MATRICES and method == "source-inspection":
        raise MatrixError(
            f"{matrix}/{scenario}: source inspection cannot establish a pass in this matrix; "
            "the behaviour must be observed at runtime"
        )

    if outcome == "NOT_APPLICABLE" and not record.get("reason"):
        raise MatrixError(
            f"{matrix}/{scenario}: NOT_APPLICABLE requires a reason so it stays distinguishable "
            "from an untested scenario"
        )

    return MatrixResult(
        scenario=str(scenario),
        outcome=str(outcome),
        method=str(method),
        evidenceReference=str(evidence) if evidence else None,
        recordedAt=str(recorded_at),
        notes=str(record.get("notes", "")),
        reason=str(record.get("reason", "")),
    )


@dataclass(frozen=True)
class MatrixVerdict:
    matrix: str
    results: tuple[MatrixResult, ...]
    missing: tuple[str, ...]
    failing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing and not self.failing

    def as_dict(self) -> dict[str, Any]:
        by_method: dict[str, int] = {}
        for result in self.results:
            by_method[result.method] = by_method.get(result.method, 0) + 1
        return {
            "schemaVersion": SCHEMA_VERSION,
            "matrix": self.matrix,
            "scenarioCount": len(MATRICES[self.matrix]),
            "results": [result.as_dict() for result in self.results],
            "missingScenarios": list(self.missing),
            "failingScenarios": list(self.failing),
            "methodCounts": by_method,
            "complete": self.complete,
            "result": "PASS" if self.complete else "BLOCKED",
        }


def evaluate_matrix(
    matrix: str,
    records: Iterable[Mapping[str, Any]],
    *,
    root: Path | None = None,
) -> MatrixVerdict:
    if matrix not in MATRICES:
        raise MatrixError(f"unknown matrix {matrix!r}")
    results = tuple(parse_result(matrix, record, root=root) for record in records)

    seen = [result.scenario for result in results]
    duplicates = sorted({name for name in seen if seen.count(name) > 1})
    if duplicates:
        raise MatrixError(f"{matrix}: duplicate scenarios: {', '.join(duplicates)}")

    resolved = {
        result.scenario for result in results if result.outcome in {"PASS", "NOT_APPLICABLE"}
    }
    missing = tuple(name for name in MATRICES[matrix] if name not in resolved)
    failing = tuple(
        sorted(result.scenario for result in results if result.outcome in {"FAIL", "BLOCKED"})
    )
    return MatrixVerdict(matrix=matrix, results=results, missing=missing, failing=failing)


def evaluate_document(document: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Evaluate a document holding several matrices at once."""
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise MatrixError("qualification matrix document schemaVersion is invalid")
    matrices = document.get("matrices")
    if not isinstance(matrices, Mapping):
        raise MatrixError("document must carry a matrices object")
    unknown = sorted(set(matrices) - set(MATRICES))
    if unknown:
        raise MatrixError("unknown matrices: " + ", ".join(unknown))

    verdicts = {
        name: evaluate_matrix(name, matrices.get(name, []), root=root) for name in sorted(matrices)
    }
    blocked = sorted(name for name, verdict in verdicts.items() if not verdict.complete)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "matrices": {name: verdict.as_dict() for name, verdict in verdicts.items()},
        "incompleteMatrices": blocked,
        "result": "PASS" if not blocked else "BLOCKED",
        "note": (
            "A matrix is complete only when every scenario resolves to PASS or a reasoned "
            "NOT_APPLICABLE. Recovery-media and accessibility results cannot pass on source "
            "inspection."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "MATRICES",
    "METHODS",
    "OUTCOMES",
    "RUNTIME_ONLY_MATRICES",
    "MatrixError",
    "MatrixResult",
    "MatrixVerdict",
    "evaluate_document",
    "evaluate_matrix",
    "parse_result",
]

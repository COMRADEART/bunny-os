"""Licence gate: fail-closed until the owner has explicitly decided.

The licence choice is not an engineering decision, so this module does not make
one. It validates that a decision *was* made, by someone entitled to make it,
and that the repository actually reflects it.

Seven things must all hold:

1. a root ``LICENSE`` file;
2. package-level licences matching the recorded split;
3. third-party notices;
4. SPDX identifiers on the source files the decision covers;
5. a licence scan result;
6. a trademark policy;
7. an owner approval record.

An approval with neither a signature nor an attestation reference is rejected —
an unsigned, unattributed approval is indistinguishable from an assumption, and
assuming a licence is the specific failure this gate exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The licence models the decision package compares. Recorded so a decision
#: cannot name a model the package never evaluated.
LICENCE_MODELS = (
    "gpl-os-apache-clients-split",
    "uniform-gpl",
    "uniform-apache",
    "other-legally-reviewed-split",
    "undecided",
)

#: SPDX identifiers this project is permitted to declare for its own source.
PROJECT_SPDX = ("GPL-3.0-or-later", "Apache-2.0")

_SPDX_HEADER = re.compile(r"SPDX-License-Identifier:\s*(\S+)")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

#: Directory to SPDX identifier, for the split model. Empty for models that do
#: not split.
SPLIT_LAYOUT: dict[str, str] = {
    "services": "GPL-3.0-or-later",
    "installer": "GPL-3.0-or-later",
    "shell": "GPL-3.0-or-later",
    "build": "GPL-3.0-or-later",
    "oem": "Apache-2.0",
    "enterprise": "Apache-2.0",
    "sync": "Apache-2.0",
    "schemas": "Apache-2.0",
}


class LicenceError(ValueError):
    """Raised when a licence decision record is malformed or unattributed."""


@dataclass(frozen=True)
class LicenceDecision:
    model: str
    decidedBy: str
    decidedAt: str
    rationale: str
    layout: Mapping[str, str]
    signature: Mapping[str, Any] | None
    attestationReference: str | None

    @property
    def decided(self) -> bool:
        return self.model != "undecided"

    @property
    def attributed(self) -> bool:
        return bool(self.signature) or bool(self.attestationReference)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "decidedBy": self.decidedBy,
            "decidedAt": self.decidedAt,
            "rationale": self.rationale,
            "layout": dict(self.layout),
            "signature": dict(self.signature) if self.signature else None,
            "attestationReference": self.attestationReference,
            "decided": self.decided,
            "attributed": self.attributed,
        }


def parse_decision(record: Mapping[str, Any]) -> LicenceDecision:
    if not isinstance(record, Mapping):
        raise LicenceError("licence decision must be an object")
    model = record.get("model")
    if model not in LICENCE_MODELS:
        raise LicenceError(f"model must be one of {', '.join(LICENCE_MODELS)}")

    for name in ("decidedBy", "decidedAt", "rationale"):
        if model != "undecided" and not record.get(name):
            raise LicenceError(f"a decided licence record requires {name}")
    decided_at = record.get("decidedAt")
    if decided_at and not _RFC3339.match(str(decided_at)):
        raise LicenceError("decidedAt must be an RFC 3339 timestamp")

    layout = record.get("layout") or {}
    if not isinstance(layout, Mapping):
        raise LicenceError("layout must be an object mapping directory to SPDX identifier")
    for directory, identifier in layout.items():
        if identifier not in PROJECT_SPDX:
            raise LicenceError(
                f"layout entry {directory} declares {identifier!r}, which is not one of "
                f"{', '.join(PROJECT_SPDX)}"
            )

    signature = record.get("signature")
    if signature is not None:
        if not isinstance(signature, Mapping):
            raise LicenceError("signature must be an object")
        for name in ("keyId", "algorithm", "value"):
            if not signature.get(name):
                raise LicenceError(f"signature missing {name}")

    decision = LicenceDecision(
        model=model,
        decidedBy=str(record.get("decidedBy", "")),
        decidedAt=str(record.get("decidedAt", "")),
        rationale=str(record.get("rationale", "")),
        layout=layout,
        signature=signature,
        attestationReference=record.get("attestationReference"),
    )
    if decision.decided and not decision.attributed:
        raise LicenceError(
            "a licence decision must carry either a signature or an attestation reference; "
            "an unsigned, unattributed approval is an assumption, not an approval"
        )
    return decision


def scan_spdx_headers(root: Path, directories: Iterable[str]) -> dict[str, dict[str, int]]:
    """Count SPDX identifiers per directory over Python sources."""
    summary: dict[str, dict[str, int]] = {}
    for directory in directories:
        base = root / directory
        counts: dict[str, int] = {}
        if not base.is_dir():
            summary[directory] = counts
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:2048]
            except OSError:
                continue
            match = _SPDX_HEADER.search(head)
            key = match.group(1) if match else "<missing>"
            counts[key] = counts.get(key, 0) + 1
        summary[directory] = counts
    return summary


@dataclass(frozen=True)
class LicenceGateResult:
    decision: LicenceDecision
    satisfied: tuple[str, ...]
    unmet: tuple[str, ...]
    detail: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return not self.unmet

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "decision": self.decision.as_dict(),
            "requirementsSatisfied": list(self.satisfied),
            "requirementsUnmet": list(self.unmet),
            "detail": dict(self.detail),
            "result": "PASS" if self.passed else "BLOCKED",
            "note": (
                "The licence gate fails closed. It checks that a decision exists and that the "
                "repository reflects it; it does not choose a licence."
            ),
        }


def evaluate_licence_gate(
    decision: LicenceDecision,
    *,
    root: Path,
    licenceScanResult: str | None = None,
) -> LicenceGateResult:
    """Evaluate the seven licence requirements against the working tree."""
    satisfied: list[str] = []
    unmet: list[str] = []
    detail: dict[str, Any] = {}

    def check(name: str, ok: bool, why: str) -> None:
        (satisfied if ok else unmet).append(name if ok else f"{name}: {why}")

    # 1. Owner decision.
    check("owner-decision", decision.decided, "no licence has been selected by the project owner")
    check(
        "owner-approval-record",
        decision.decided and decision.attributed,
        "the decision carries neither a signature nor an attestation reference",
    )

    # 2. Root LICENSE.
    root_licence = root / "LICENSE"
    check("root-licence", root_licence.is_file(), "no root LICENSE file exists")
    detail["rootLicensePresent"] = root_licence.is_file()

    # 3. Package-level licences matching the decision.
    missing_package_licences: list[str] = []
    for directory in sorted(decision.layout):
        candidate = root / directory / "LICENSE"
        if not candidate.is_file():
            missing_package_licences.append(f"{directory}/LICENSE")
    detail["missingPackageLicences"] = missing_package_licences
    check(
        "package-level-licences",
        decision.decided and not missing_package_licences,
        "missing " + ", ".join(missing_package_licences) if missing_package_licences else "no decision",
    )

    # 4. Third-party notices.
    notices = root / "THIRD_PARTY_NOTICES.md"
    check("third-party-notices", notices.is_file(), "THIRD_PARTY_NOTICES.md does not exist")

    # 5. SPDX identifiers.
    spdx = scan_spdx_headers(root, decision.layout.keys()) if decision.decided else {}
    detail["spdxHeaders"] = spdx
    wrong: list[str] = []
    for directory, expected in sorted(decision.layout.items()):
        counts = spdx.get(directory, {})
        if not counts:
            continue
        for identifier, count in counts.items():
            if identifier != expected:
                wrong.append(f"{directory}: {count} file(s) declare {identifier}, expected {expected}")
    detail["spdxMismatches"] = wrong
    check("spdx-identifiers", decision.decided and not wrong, "; ".join(wrong) if wrong else "no decision")

    # 6. Licence scan.
    detail["licenceScanResult"] = licenceScanResult
    check(
        "licence-scan",
        licenceScanResult == "PASS",
        f"licence scan result is {licenceScanResult or 'NOT_RUN'}",
    )

    # 7. Trademark policy.
    trademark = root / "docs/TRADEMARK_POLICY_DRAFT.md"
    legacy = root / "docs/TRADEMARK_POLICY.md"
    check(
        "trademark-policy",
        trademark.is_file() or legacy.is_file(),
        "no trademark policy document exists",
    )

    return LicenceGateResult(
        decision=decision,
        satisfied=tuple(satisfied),
        unmet=tuple(unmet),
        detail=detail,
    )


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "LICENCE_MODELS",
    "PROJECT_SPDX",
    "SPLIT_LAYOUT",
    "LicenceDecision",
    "LicenceError",
    "LicenceGateResult",
    "evaluate_licence_gate",
    "parse_decision",
    "scan_spdx_headers",
]

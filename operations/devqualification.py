"""Development qualification: a second, clearly-labelled evidence track.

``operations/qualification.py`` is untouched and stays strict. It is the
production gate: only ``PASS`` counts, all nine approvals must be literally
``APPROVED``, blockers must be empty, and there is no waiver mechanism.

This module exists because most of that gate's 25 evidence rows were sitting at
``NOT_RUN`` not because the work is impossible but because nobody had run it.
Real images can be built, really booted under KVM, really scanned, and really
signed. What cannot be produced is *physical hardware* results, *production key
ceremony* signatures, *independent third-party review*, and *human approvals*.

So every development row carries provenance, and the provenance is checked
rather than trusted:

* ``environment: physical`` requires a hardware report id that resolves in
  ``operations/data/hardware-evidence.json``. That file is empty, so a physical
  claim currently fails — which is the point.
* ``keyClass: production`` requires a key-ceremony reference. None exists, so a
  production-key claim currently fails too.

A development GO therefore means exactly "everything measurable in a virtual
environment with development keys passed", and it can never be mistaken for,
or promoted into, a production GO.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from operations.qualification import REQUIRED_APPROVALS, REQUIRED_AUTOMATED, STATUSES

SCHEMA_VERSION = 1

ENVIRONMENTS = ("virtual", "physical", "host", "not-applicable")
KEY_CLASSES = ("development", "production", "none")

#: A row may only be counted as passing in the development track with this
#: status. Same rule as production: unknown evidence is blocking.
ACCEPTABLE = "PASS"

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

_REQUIRED_ROW_FIELDS = ("status", "environment", "keyClass", "method", "command", "recordedAt")

#: What each row would additionally need before it could count on the
#: production track. Generated into the gap analysis so the difference between
#: the two tracks is explicit and reviewable rather than folklore.
PRODUCTION_REQUIREMENTS: dict[str, str] = {
    "source_integrity": "no additional requirement; already production-grade",
    "reproducible_build": "a second independent builder on different hardware, not two runs on one host",
    "dependency_validation": "a reviewed immutable package snapshot and a resolved vulnerability position",
    "unit_tests": "no additional requirement; already production-grade",
    "integration_tests": "execution against an installed system, not a booted image",
    "installer": "a destructive install onto real storage with wrong-disk protection exercised",
    "encryption": "a LUKS install booted on hardware with the recovery-key flow exercised",
    "updates": "a signed manifest published to a real channel and installed by a device",
    "rollback": "a live bootc deployment switch after a staged update",
    "recovery": "recovery media booted on physical hardware with interactive repair exercised",
    "migration": "a supported migration executed between two real releases",
    "multi_user": "cross-user isolation verified on an installed multi-user system",
    "bunny_disabled": "an installed system operated with Bunny disabled",
    "local_only": "an installed system operated offline with a local model",
    "security": "an independent third-party security assessment",
    "privacy": "a traffic capture on an installed system plus independent privacy review",
    "network": "a quiet-capture and per-feature capture on an installed system",
    "accessibility": "an independent accessibility audit of every essential workflow",
    "hardware": "physical hardware submissions in operations/data/hardware-evidence.json",
    "image_inspection": "inspection of a production-signed release artifact",
    "signature_verification": "verification against a production release key from a key ceremony",
    "sbom": "an SBOM generated from the production release artifact",
    "licensing": "a release licence report plus a root LICENSE file and trademark policy",
    "malware_scan": "a pinned scanner configuration run against the release artifact",
    "documentation": "release-specific notes, known issues, and third-party notices",
}


class DevQualificationError(ValueError):
    """Raised when a development evidence record is malformed or overclaims."""


@dataclass(frozen=True)
class DevGateDecision:
    recommendation: str
    missing: tuple[str, ...]
    failing: tuple[str, ...]
    overclaimed: tuple[str, ...]
    virtualRows: tuple[str, ...]
    developmentKeyRows: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.recommendation == "GO"

    def as_dict(self) -> dict[str, Any]:
        return {
            "track": "development",
            "recommendation": self.recommendation,
            "missingEvidence": list(self.missing),
            "failingEvidence": list(self.failing),
            "overclaimedProvenance": list(self.overclaimed),
            "virtualRows": list(self.virtualRows),
            "developmentKeyRows": list(self.developmentKeyRows),
            "isProductionApproval": False,
            "note": (
                "A development GO means every measurable row passed in a virtual environment "
                "with development keys. It is not a stable release approval and does not "
                "satisfy any pilot gate."
            ),
        }


def _hardware_report_ids(root: Path) -> set[str]:
    path = root / "operations/data/hardware-evidence.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    reports = document.get("reports")
    if not isinstance(reports, list):
        return set()
    return {
        str(item.get("reportId"))
        for item in reports
        if isinstance(item, Mapping) and item.get("reportId")
    }


def _validate_row(
    name: str,
    row: Any,
    *,
    hardware_reports: set[str],
    key_ceremonies: set[str],
) -> tuple[str, list[str]]:
    """Return ``(status, overclaims)`` for one evidence row."""
    if not isinstance(row, Mapping):
        raise DevQualificationError(f"{name}: evidence row must be an object")
    unexpected = sorted(
        set(row) - set(_REQUIRED_ROW_FIELDS) - {"hardwareReportId", "keyCeremonyRef", "detail"}
    )
    if unexpected:
        raise DevQualificationError(f"{name}: unknown evidence fields: {', '.join(unexpected)}")
    missing = [field for field in _REQUIRED_ROW_FIELDS if field not in row]
    if missing:
        raise DevQualificationError(f"{name}: missing evidence fields: {', '.join(missing)}")

    status = row["status"]
    if status not in STATUSES:
        raise DevQualificationError(f"{name}: invalid evidence status {status!r}")

    environment = row["environment"]
    if environment not in ENVIRONMENTS:
        raise DevQualificationError(f"{name}: environment must be one of {', '.join(ENVIRONMENTS)}")

    key_class = row["keyClass"]
    if key_class not in KEY_CLASSES:
        raise DevQualificationError(f"{name}: keyClass must be one of {', '.join(KEY_CLASSES)}")

    for field in ("method", "command"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise DevQualificationError(f"{name}: {field} must describe how the result was produced")

    if not isinstance(row["recordedAt"], str) or not _RFC3339.match(row["recordedAt"]):
        raise DevQualificationError(f"{name}: recordedAt must be an RFC 3339 timestamp")

    overclaims: list[str] = []
    if environment == "physical":
        report_id = row.get("hardwareReportId")
        if not report_id or str(report_id) not in hardware_reports:
            overclaims.append(
                f"{name}: claims physical hardware but no matching report exists in "
                "operations/data/hardware-evidence.json"
            )
    if key_class == "production":
        ceremony = row.get("keyCeremonyRef")
        if not ceremony or str(ceremony) not in key_ceremonies:
            overclaims.append(
                f"{name}: claims a production key but no key ceremony is recorded"
            )
    return status, overclaims


def evaluate_development(
    evidence: Mapping[str, Any],
    *,
    root: Path | None = None,
    required: Iterable[str] | None = None,
) -> DevGateDecision:
    """Evaluate the development evidence record.

    Deliberately takes no approvals argument. The nine protected approvals are
    human sign-offs on a production release; a development track has no
    business collecting or simulating them.
    """
    if not isinstance(evidence, Mapping):
        raise DevQualificationError("evidence must be a mapping")

    repo_root = root or Path(__file__).resolve().parents[1]
    hardware_reports = _hardware_report_ids(repo_root)
    key_ceremonies: set[str] = set()  # No key ceremony has been performed.

    requirements = tuple(required) if required is not None else REQUIRED_AUTOMATED
    unknown = sorted(set(evidence) - set(REQUIRED_AUTOMATED))
    if unknown:
        raise DevQualificationError("unknown evidence rows: " + ", ".join(unknown))

    missing: list[str] = []
    failing: list[str] = []
    overclaimed: list[str] = []
    virtual_rows: list[str] = []
    development_key_rows: list[str] = []

    for name in requirements:
        row = evidence.get(name)
        if row is None:
            missing.append(name)
            continue
        status, overclaims = _validate_row(
            name, row, hardware_reports=hardware_reports, key_ceremonies=key_ceremonies
        )
        overclaimed.extend(overclaims)
        if row["environment"] == "virtual":
            virtual_rows.append(name)
        if row["keyClass"] == "development":
            development_key_rows.append(name)
        if status == "FAIL":
            failing.append(name)
        elif status != ACCEPTABLE:
            missing.append(name)

    recommendation = "GO" if not missing and not failing and not overclaimed else "NO-GO"
    return DevGateDecision(
        recommendation=recommendation,
        missing=tuple(sorted(missing)),
        failing=tuple(sorted(failing)),
        overclaimed=tuple(sorted(overclaimed)),
        virtualRows=tuple(sorted(virtual_rows)),
        developmentKeyRows=tuple(sorted(development_key_rows)),
    )


def production_gap_analysis(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Name exactly what each row still needs for the production track.

    Generated from the development record rather than hand-maintained, so the
    two tracks cannot drift into disagreeing about what is missing.
    """
    rows: list[dict[str, Any]] = []
    for name in REQUIRED_AUTOMATED:
        row = evidence.get(name)
        environment = row.get("environment") if isinstance(row, Mapping) else None
        key_class = row.get("keyClass") if isinstance(row, Mapping) else None
        status = row.get("status") if isinstance(row, Mapping) else "NOT_RUN"
        requirement = PRODUCTION_REQUIREMENTS[name]
        satisfied = requirement.startswith("no additional requirement") and status == ACCEPTABLE
        rows.append(
            {
                "evidence": name,
                "developmentStatus": status,
                "developmentEnvironment": environment,
                "developmentKeyClass": key_class,
                "productionRequirement": requirement,
                "productionSatisfied": satisfied,
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "rows": rows,
        "productionApprovalsOutstanding": list(REQUIRED_APPROVALS),
        "summary": {
            "rowsSatisfyingProduction": sum(1 for row in rows if row["productionSatisfied"]),
            "rowsRequiringMoreForProduction": sum(1 for row in rows if not row["productionSatisfied"]),
            "humanApprovalsOutstanding": len(REQUIRED_APPROVALS),
        },
        "note": (
            "Development evidence never promotes to production evidence. Physical hardware, a "
            "production key ceremony, independent review, and nine human approvals cannot be "
            "produced by running more tests."
        ),
    }

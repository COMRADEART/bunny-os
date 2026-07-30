"""Physical hardware evidence intake, with mandatory redaction.

A hardware qualification report is the one piece of evidence this repository
cannot generate for itself, which makes it the one most worth checking. Two
things are enforced:

**Redaction.** Reports must not carry serial numbers, MAC addresses, usernames
or personal hostnames. The scan runs over every string in the submission, not
just the fields a submitter remembered to clean, because the risk is precisely
the field nobody thought about.

**Substantiation.** A report claims fifteen test outcomes. Each claimed outcome
must name an evidence artifact that actually exists in ``hardware/evidence/``.
A report full of ``PASS`` values and no artifacts is the ``fake physical-hardware
report`` case, and it fails.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The fifteen tests a physical qualification must cover.
HARDWARE_TESTS = (
    "install",
    "encryption",
    "boot",
    "secure-boot",
    "tpm",
    "network",
    "audio",
    "camera",
    "suspend",
    "resume",
    "update",
    "rollback",
    "recovery",
    "bunny-disabled",
    "local-only",
)

#: Characteristics recorded per machine. Absent ones are recorded as absent
#: rather than omitted, so "no TPM" and "nobody checked" stay distinguishable.
HARDWARE_CHARACTERISTICS = (
    "secureBoot",
    "tpm20",
    "nvme",
    "wifi",
    "bluetooth",
    "audio",
    "microphone",
    "camera",
    "suspendResume",
    "integratedGraphics",
)

TEST_OUTCOMES = ("PASS", "FAIL", "NOT_APPLICABLE", "NOT_RUN")
ARCHITECTURES = ("x86-64",)
FIRMWARE_MODES = ("uefi", "uefi-secure-boot", "legacy-bios")

#: A MAC address in the usual colon or hyphen form.
_MAC = re.compile(r"\b[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}\b")
#: A run of 8+ alphanumerics containing both letters and digits, which is what
#: most serial numbers look like. Deliberately noisy: a false positive costs a
#: submitter one edit, a false negative leaks a device identifier.
_SERIAL_LIKE = re.compile(r"\b(?=[A-Za-z0-9-]{8,})(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{8,}\b")
#: Explicit labels that should never appear with a value attached.
_LABELLED_IDENTIFIER = re.compile(
    r"\b(serial|serial[_\s-]?number|sn|uuid|mac|mac[_\s-]?address|hostname|username|user|owner|asset[_\s-]?tag)\b\s*[:=]\s*\S+",
    re.IGNORECASE,
)

#: Fields whose values are allowed to look serial-like because they are digests,
#: timestamps or version strings rather than device identifiers.
_DIGEST_FIELDS = frozenset(
    {
        "sourceCommit",
        "imageDigest",
        "baseImageDigest",
        "contentDigest",
        "reportId",
        "artifactDigest",
        "submittedAt",
        "recordedAt",
        "reviewedAt",
        "generatedAt",
        "firmwareVersion",
    }
)

#: An RFC 3339 timestamp trips the serial-like heuristic — it is long, mixed
#: alphanumeric and hyphenated — but is never a device identifier.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class HardwareEvidenceError(ValueError):
    """Raised when a hardware report is malformed, unsubstantiated, or leaks identifiers."""


def _walk_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def redaction_findings(document: Mapping[str, Any]) -> list[str]:
    """Return every place the submission appears to carry a personal identifier."""
    findings: list[str] = []
    for path, text in _walk_strings(document):
        leaf = path.rsplit(".", 1)[-1].split("[")[0]
        if _MAC.search(text):
            findings.append(f"{path}: contains what looks like a MAC address")
        if _LABELLED_IDENTIFIER.search(text):
            findings.append(f"{path}: contains a labelled identifier (serial, MAC, hostname or username)")
        if leaf not in _DIGEST_FIELDS and not path.startswith("evidence") and not _TIMESTAMP.search(text):
            for candidate in _SERIAL_LIKE.findall(text):
                if candidate.lower() in _ALLOWED_TOKENS:
                    continue
                findings.append(f"{path}: {candidate!r} looks like a serial number or asset tag")
                break
    return findings


#: Tokens that trip the serial-like heuristic but are ordinary vocabulary here.
_ALLOWED_TOKENS = frozenset(
    {
        "x86-64",
        "uefi-secure-boot",
        "legacy-bios",
        "bunny-disabled",
        "local-only",
        "secure-boot",
        "tpm20",
        "not-run",
        "not-applicable",
        "qualification-candidate",
        "stable-rc",
        "sha256",
        "fedora-bootc-44",
        "gpl-3",
        "apache-2",
    }
)


@dataclass(frozen=True)
class HardwareReport:
    reportId: str
    submittedBy: str
    submittedAt: str
    architecture: str
    firmwareMode: str
    formFactor: str
    chipsetClass: str
    firmwareVendor: str
    firmwareVersion: str
    characteristics: Mapping[str, bool]
    results: Mapping[str, str]
    evidence: Mapping[str, str]
    imageDigest: str
    sourceCommit: str
    notes: str = ""

    @property
    def passingTests(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.results.items() if value == "PASS"))

    @property
    def failingTests(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.results.items() if value == "FAIL"))

    @property
    def untestedTests(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in HARDWARE_TESTS if self.results.get(name, "NOT_RUN") == "NOT_RUN"))

    @property
    def qualified(self) -> bool:
        """A machine is qualified only when every test resolved and none failed."""
        return not self.failingTests and not self.untestedTests

    def as_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.reportId,
            "submittedBy": self.submittedBy,
            "submittedAt": self.submittedAt,
            "architecture": self.architecture,
            "firmwareMode": self.firmwareMode,
            "formFactor": self.formFactor,
            "chipsetClass": self.chipsetClass,
            "firmwareVendor": self.firmwareVendor,
            "firmwareVersion": self.firmwareVersion,
            "characteristics": dict(self.characteristics),
            "results": dict(self.results),
            "evidence": dict(self.evidence),
            "imageDigest": self.imageDigest,
            "sourceCommit": self.sourceCommit,
            "notes": self.notes,
            "passingTests": list(self.passingTests),
            "failingTests": list(self.failingTests),
            "untestedTests": list(self.untestedTests),
            "qualified": self.qualified,
        }


def parse_report(record: Mapping[str, Any], *, evidenceRoot: Path | None = None) -> HardwareReport:
    """Validate one physical hardware report."""
    if not isinstance(record, Mapping):
        raise HardwareEvidenceError("hardware report must be an object")

    required = (
        "reportId",
        "submittedBy",
        "submittedAt",
        "architecture",
        "firmwareMode",
        "formFactor",
        "chipsetClass",
        "firmwareVendor",
        "firmwareVersion",
        "characteristics",
        "results",
        "evidence",
        "imageDigest",
        "sourceCommit",
    )
    missing = [name for name in required if name not in record]
    if missing:
        raise HardwareEvidenceError(f"hardware report missing fields: {', '.join(missing)}")

    report_id = str(record["reportId"])

    leaks = redaction_findings(record)
    if leaks:
        raise HardwareEvidenceError(
            f"{report_id}: submission carries personal or device identifiers and cannot be stored: "
            + "; ".join(leaks[:5])
        )

    if record["architecture"] not in ARCHITECTURES:
        raise HardwareEvidenceError(f"{report_id}: architecture must be one of {', '.join(ARCHITECTURES)}")
    if record["firmwareMode"] not in FIRMWARE_MODES:
        raise HardwareEvidenceError(f"{report_id}: firmwareMode must be one of {', '.join(FIRMWARE_MODES)}")

    characteristics = record["characteristics"]
    if not isinstance(characteristics, Mapping):
        raise HardwareEvidenceError(f"{report_id}: characteristics must be an object")
    unknown = sorted(set(characteristics) - set(HARDWARE_CHARACTERISTICS))
    if unknown:
        raise HardwareEvidenceError(f"{report_id}: unknown characteristics: {', '.join(unknown)}")
    for name, value in characteristics.items():
        if not isinstance(value, bool):
            raise HardwareEvidenceError(f"{report_id}: characteristic {name} must be a boolean")

    results = record["results"]
    if not isinstance(results, Mapping):
        raise HardwareEvidenceError(f"{report_id}: results must be an object")
    unknown_tests = sorted(set(results) - set(HARDWARE_TESTS))
    if unknown_tests:
        raise HardwareEvidenceError(f"{report_id}: unknown tests: {', '.join(unknown_tests)}")
    for name, value in results.items():
        if value not in TEST_OUTCOMES:
            raise HardwareEvidenceError(
                f"{report_id}: result for {name} must be one of {', '.join(TEST_OUTCOMES)}"
            )

    evidence = record["evidence"]
    if not isinstance(evidence, Mapping):
        raise HardwareEvidenceError(f"{report_id}: evidence must be an object")

    # Substantiation: a claimed outcome needs an artifact that exists.
    unsubstantiated: list[str] = []
    for name, value in results.items():
        if value not in {"PASS", "FAIL"}:
            continue
        reference = evidence.get(name)
        if not reference:
            unsubstantiated.append(f"{name}: no evidence artifact named")
            continue
        if evidenceRoot is not None:
            target = (evidenceRoot / reference).resolve()
            try:
                target.relative_to(evidenceRoot.resolve())
            except ValueError:
                unsubstantiated.append(f"{name}: evidence path escapes hardware/evidence/")
                continue
            if not target.exists():
                unsubstantiated.append(f"{name}: evidence artifact {reference} does not exist")
    if unsubstantiated:
        raise HardwareEvidenceError(
            f"{report_id}: claimed results are unsubstantiated: " + "; ".join(unsubstantiated)
        )

    return HardwareReport(
        reportId=report_id,
        submittedBy=str(record["submittedBy"]),
        submittedAt=str(record["submittedAt"]),
        architecture=str(record["architecture"]),
        firmwareMode=str(record["firmwareMode"]),
        formFactor=str(record["formFactor"]),
        chipsetClass=str(record["chipsetClass"]),
        firmwareVendor=str(record["firmwareVendor"]),
        firmwareVersion=str(record["firmwareVersion"]),
        characteristics={str(k): bool(v) for k, v in characteristics.items()},
        results={str(k): str(v) for k, v in results.items()},
        evidence={str(k): str(v) for k, v in evidence.items()},
        imageDigest=str(record["imageDigest"]),
        sourceCommit=str(record["sourceCommit"]),
        notes=str(record.get("notes", "")),
    )


def evaluate_intake(
    document: Mapping[str, Any],
    *,
    evidenceRoot: Path | None = None,
) -> dict[str, Any]:
    """Evaluate the whole hardware evidence file."""
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise HardwareEvidenceError("hardware evidence schemaVersion is invalid")
    raw = document.get("reports")
    if not isinstance(raw, list):
        raise HardwareEvidenceError("hardware evidence must carry a reports array")

    reports: list[HardwareReport] = []
    errors: list[str] = []
    for item in raw:
        try:
            reports.append(parse_report(item, evidenceRoot=evidenceRoot))
        except HardwareEvidenceError as exc:
            errors.append(str(exc))

    qualified = [report for report in reports if report.qualified]
    uefi_qualified = [
        report
        for report in qualified
        if report.architecture == "x86-64" and report.firmwareMode.startswith("uefi")
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "submitted": len(raw),
        "accepted": len(reports),
        "rejected": errors,
        "qualifiedMachines": [report.reportId for report in qualified],
        "qualifiedX86UefiMachines": [report.reportId for report in uefi_qualified],
        "requirementMet": bool(uefi_qualified),
        "reports": [report.as_dict() for report in reports],
        "result": "PASS" if uefi_qualified and not errors else "BLOCKED",
        "note": (
            "At least one x86-64 UEFI physical machine must be fully qualified. A report with any "
            "NOT_RUN test does not qualify a machine, and no claim may rest on source inspection."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "HARDWARE_CHARACTERISTICS",
    "HARDWARE_TESTS",
    "HardwareEvidenceError",
    "HardwareReport",
    "evaluate_intake",
    "parse_report",
    "redaction_findings",
]

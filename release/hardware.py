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


# --------------------------------------------------------------------------- #
# The on-device collector
# --------------------------------------------------------------------------- #

#: The only fields ``bunny-os qualification collect`` may emit. An allow-list
#: rather than a deny-list: adding a field requires editing this tuple, which is
#: a reviewable act, whereas forgetting to exclude one is an accident.
COLLECTOR_FIELDS = (
    "bunnyOsVersion",
    "sourceCommit",
    "imageDigest",
    "architecture",
    "firmwareMode",
    "secureBootState",
    "tpmAvailable",
    "cpuFamily",
    "gpuFamily",
    "ramSizeCategory",
    "storageType",
    "wifiChipset",
    "bluetoothChipset",
    "kernel",
    "driverVersions",
    "testResults",
    "recoveryMediaDigest",
)

#: What the collector must never emit, named so the exclusion is testable rather
#: than aspirational. Every one of these is either a device identifier or
#: personal content, and a hardware qualification needs none of them.
EXCLUDED_CATEGORIES = (
    "serialNumber",
    "macAddress",
    "ipAddress",
    "hostname",
    "username",
    "wifiNetworkName",
    "personalPaths",
    "personalFiles",
    "bunnyPrompts",
    "bunnyMemory",
    "browserHistory",
    "assetTag",
)

#: RAM is recorded by category, not by size in bytes: an exact byte count plus a
#: chipset class narrows a device more than the qualification needs.
RAM_SIZE_CATEGORIES = ("under-4GB", "4-8GB", "8-16GB", "16-32GB", "32GB-or-more", "unknown")
STORAGE_TYPES = ("nvme", "sata-ssd", "sata-hdd", "emmc", "virtual", "unknown")
SECURE_BOOT_STATES = ("enabled", "disabled", "setup-mode", "unsupported", "unknown")

#: The twenty-one guided tests an operator drives on a physical machine. A
#: superset of HARDWARE_TESTS, which remains the fifteen the intake gate scores.
GUIDED_TESTS = (
    "boot",
    "installation",
    "encrypted-installation",
    "secure-boot",
    "tpm",
    "graphics",
    "display",
    "wifi",
    "bluetooth",
    "audio",
    "microphone",
    "camera",
    "suspend",
    "resume",
    "battery-reporting",
    "update",
    "rollback",
    "recovery",
    "bunny-disabled-mode",
    "local-only-mode",
    "accessibility",
)

#: Who may sign a hardware evidence report, and what the signature means.
SIGNER_ROLES = {
    "test-operator": "the person who ran the tests, attesting the report describes what they saw",
    "approved-laboratory": "a laboratory attesting it ran the tests under its own procedures",
    "project-maintainer-after-verification": (
        "a maintainer attesting they independently verified the submitted evidence; not that they "
        "ran the tests"
    ),
}

#: Language a hardware result may not use. A signature proves report integrity;
#: it does not certify hardware, and this project has no certification authority.
FORBIDDEN_TERMS = ("certified", "certification", "certifies", "certify")

#: What may be said instead.
PERMITTED_CLAIMS = ("tested", "qualified for pilot", "supported based on evidence")


class HardwareCollectionError(ValueError):
    """Raised when collected evidence is out of scope or a claim is overstated."""


def assert_collector_scope(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Refuse a collection carrying a field outside the allow-list."""
    if not isinstance(payload, Mapping):
        raise HardwareCollectionError("collected evidence must be an object")
    extraneous = sorted(set(payload) - set(COLLECTOR_FIELDS) - {"schemaVersion", "collectedAt", "collectorVersion"})
    if extraneous:
        excluded = [name for name in extraneous if name in EXCLUDED_CATEGORIES]
        if excluded:
            raise HardwareCollectionError(
                "collected evidence carries excluded categories: "
                + ", ".join(excluded)
                + ". A hardware qualification needs no device identifier and no personal content"
            )
        raise HardwareCollectionError(
            "collected evidence carries fields outside the allow-list: "
            + ", ".join(extraneous)
            + f". Permitted: {', '.join(COLLECTOR_FIELDS)}"
        )
    missing = sorted(set(COLLECTOR_FIELDS) - set(payload))
    return tuple(missing)


def assert_no_certification_claim(text: str, *, where: str = "report") -> None:
    """Refuse the word 'certified' and its family."""
    haystack = text.casefold()
    for term in FORBIDDEN_TERMS:
        if term in haystack:
            raise HardwareCollectionError(
                f"{where} uses {term!r}. A signature proves report integrity, not hardware "
                f"certification. Use one of: {', '.join(PERMITTED_CLAIMS)}"
            )


@dataclass(frozen=True)
class GuidedTestRecord:
    test: str
    startedAt: str
    completedAt: str
    operator: str
    expectedResult: str
    actualResult: str
    outcome: str
    evidenceReference: str | None
    notes: str
    logs: tuple[str, ...]
    redactionState: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "test": self.test,
            "startedAt": self.startedAt,
            "completedAt": self.completedAt,
            "operator": self.operator,
            "expectedResult": self.expectedResult,
            "actualResult": self.actualResult,
            "outcome": self.outcome,
            "evidenceReference": self.evidenceReference,
            "notes": self.notes,
            "logs": list(self.logs),
            "redactionState": self.redactionState,
        }


def parse_guided_test(record: Mapping[str, Any], *, evidenceRoot: Path | None = None) -> GuidedTestRecord:
    """Validate one guided physical test."""
    if not isinstance(record, Mapping):
        raise HardwareCollectionError("guided test record must be an object")
    test = record.get("test")
    if test not in GUIDED_TESTS:
        raise HardwareCollectionError(f"test must be one of {', '.join(GUIDED_TESTS)}")
    outcome = record.get("outcome")
    if outcome not in TEST_OUTCOMES:
        raise HardwareCollectionError(f"{test}: outcome must be one of {', '.join(TEST_OUTCOMES)}")

    redaction = record.get("redactionState", "not-required")
    if redaction not in ("not-required", "completed", "pending"):
        raise HardwareCollectionError(f"{test}: redactionState is invalid")

    if outcome == "NOT_RUN":
        # The one conversion this whole module exists to prevent.
        for name in ("actualResult", "evidenceReference"):
            if str(record.get(name) or "").strip():
                raise HardwareCollectionError(
                    f"{test}: recorded NOT_RUN but carries {name}. A test that produced a result "
                    "was run; NOT_RUN must never be converted to PASS"
                )
    else:
        for name in ("startedAt", "completedAt", "operator", "expectedResult", "actualResult"):
            if not str(record.get(name) or "").strip():
                raise HardwareCollectionError(f"{test}: {name} is required for outcome {outcome}")
        if outcome in {"PASS", "FAIL"}:
            reference = record.get("evidenceReference")
            if not reference:
                raise HardwareCollectionError(
                    f"{test}: outcome {outcome} must name an evidence artifact; a claimed result "
                    "with no artifact is an assertion"
                )
            if evidenceRoot is not None:
                target = (evidenceRoot / str(reference)).resolve()
                try:
                    target.relative_to(evidenceRoot.resolve())
                except ValueError:
                    raise HardwareCollectionError(
                        f"{test}: evidenceReference escapes hardware/evidence/"
                    ) from None
                if not target.exists():
                    raise HardwareCollectionError(
                        f"{test}: evidence artifact {reference} does not exist"
                    )
        if redaction == "pending" and record.get("logs"):
            raise HardwareCollectionError(
                f"{test}: logs are attached with redaction pending; logs carry hostnames and paths"
            )

    for field_name in ("notes", "expectedResult", "actualResult"):
        assert_no_certification_claim(str(record.get(field_name) or ""), where=f"{test}.{field_name}")

    return GuidedTestRecord(
        test=str(test),
        startedAt=str(record.get("startedAt", "")),
        completedAt=str(record.get("completedAt", "")),
        operator=str(record.get("operator", "")),
        expectedResult=str(record.get("expectedResult", "")),
        actualResult=str(record.get("actualResult", "")),
        outcome=str(outcome),
        evidenceReference=str(record["evidenceReference"]) if record.get("evidenceReference") else None,
        notes=str(record.get("notes", "")),
        logs=tuple(str(item) for item in record.get("logs", [])),
        redactionState=str(redaction),
    )


def parse_evidence_signature(record: Mapping[str, Any], *, reportDigest: str) -> dict[str, Any]:
    """Validate a hardware evidence signature.

    The signature binds a signer to a report digest. It says the report has not
    changed since that person saw it. It does not say the hardware is fit for
    anything, and the wording is checked because that distinction erodes the
    moment someone writes "certified" in a summary.
    """
    if not isinstance(record, Mapping):
        raise HardwareCollectionError("signature must be an object")
    role = record.get("role")
    if role not in SIGNER_ROLES:
        raise HardwareCollectionError(f"signature role must be one of {', '.join(SIGNER_ROLES)}")
    for name in ("signerName", "signedAt", "signature", "publicKey", "reportDigest"):
        if not str(record.get(name) or "").strip():
            raise HardwareCollectionError(f"signature missing {name}")
    if str(record["reportDigest"]) != reportDigest:
        raise HardwareCollectionError(
            f"signature covers digest {str(record['reportDigest'])[:12]} but the report is "
            f"{reportDigest[:12]}; the report changed after it was signed"
        )
    statement = str(record.get("statement", ""))
    assert_no_certification_claim(statement, where="signature.statement")
    if role == "project-maintainer-after-verification" and not str(record.get("verificationNotes") or "").strip():
        raise HardwareCollectionError(
            "a maintainer signature must record how the submitted evidence was independently "
            "verified; otherwise it attests only that a file was read"
        )
    return {
        "role": str(role),
        "roleMeaning": SIGNER_ROLES[str(role)],
        "signerName": str(record["signerName"]),
        "signerOrganisation": record.get("signerOrganisation"),
        "signedAt": str(record["signedAt"]),
        "reportDigest": reportDigest,
        "statement": statement,
        "verificationNotes": record.get("verificationNotes"),
        "proves": "report integrity",
        "doesNotProve": "hardware certification, fitness for purpose, or a supported configuration",
    }


def evaluate_collection(
    document: Mapping[str, Any],
    *,
    evidenceRoot: Path | None = None,
) -> dict[str, Any]:
    """Evaluate a collected-evidence submission: scope, tests, and signature."""
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise HardwareCollectionError("collected evidence schemaVersion is invalid")

    submissions = document.get("collections")
    if not isinstance(submissions, list):
        raise HardwareCollectionError("collected evidence must carry a collections array")

    rows: list[dict[str, Any]] = []
    rejected: list[str] = []
    for submission in submissions:
        if not isinstance(submission, Mapping):
            rejected.append("collection must be an object")
            continue
        identifier = str(submission.get("collectionId") or "<unnamed>")
        try:
            leaks = redaction_findings(submission)
            if leaks:
                raise HardwareCollectionError(
                    f"{identifier}: submission carries personal or device identifiers: "
                    + "; ".join(leaks[:5])
                )
            missing_fields = assert_collector_scope(submission.get("collected") or {})
            tests = [
                parse_guided_test(item, evidenceRoot=evidenceRoot)
                for item in submission.get("guidedTests", [])
            ]
        except HardwareCollectionError as exc:
            rejected.append(str(exc))
            continue

        by_test = {record.test: record for record in tests}
        not_run = sorted(set(GUIDED_TESTS) - {name for name, r in by_test.items() if r.outcome != "NOT_RUN"})
        failing = sorted(name for name, r in by_test.items() if r.outcome == "FAIL")
        passing = sorted(name for name, r in by_test.items() if r.outcome == "PASS")

        signature = submission.get("signature")
        signature_detail: Any = None
        if signature:
            digest = str(submission.get("reportDigest") or "")
            try:
                signature_detail = parse_evidence_signature(signature, reportDigest=digest)
            except HardwareCollectionError as exc:
                rejected.append(str(exc))
                continue

        rows.append(
            {
                "collectionId": identifier,
                "missingCollectorFields": list(missing_fields),
                "testCount": len(tests),
                "passingTests": passing,
                "failingTests": failing,
                "notRunTests": not_run,
                "complete": not not_run and not failing and len(passing) == len(GUIDED_TESTS),
                "signature": signature_detail,
                "signed": signature_detail is not None,
                "guidedTests": [record.as_dict() for record in tests],
            }
        )

    complete = [row for row in rows if row["complete"] and row["signed"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "guidedTestCount": len(GUIDED_TESTS),
        "collectorFieldCount": len(COLLECTOR_FIELDS),
        "excludedCategories": list(EXCLUDED_CATEGORIES),
        "submitted": len(submissions),
        "accepted": len(rows),
        "rejected": rejected,
        "collections": rows,
        "completeCollections": [row["collectionId"] for row in complete],
        "requirementMet": bool(complete),
        "result": "PASS" if complete and not rejected else "BLOCKED",
        "note": (
            "A signature proves report integrity, not hardware certification. NOT_RUN is never "
            "converted to PASS: a record claiming NOT_RUN while carrying a result is rejected."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "COLLECTOR_FIELDS",
    "EXCLUDED_CATEGORIES",
    "FORBIDDEN_TERMS",
    "GUIDED_TESTS",
    "HARDWARE_CHARACTERISTICS",
    "HARDWARE_TESTS",
    "PERMITTED_CLAIMS",
    "RAM_SIZE_CATEGORIES",
    "SECURE_BOOT_STATES",
    "SIGNER_ROLES",
    "STORAGE_TYPES",
    "GuidedTestRecord",
    "HardwareCollectionError",
    "HardwareEvidenceError",
    "HardwareReport",
    "assert_collector_scope",
    "assert_no_certification_claim",
    "evaluate_collection",
    "evaluate_intake",
    "parse_evidence_signature",
    "parse_guided_test",
    "parse_report",
    "redaction_findings",
]

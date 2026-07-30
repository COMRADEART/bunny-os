# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility evidence from real assistive-technology sessions.

The accessibility matrix already refuses a source-inspection pass, which stops a
static test being recorded as a runtime result. This module is the other half:
the shape of a *real* runtime result, so that when one arrives it can be checked
rather than believed.

Seventeen flows, of which the first five are load-bearing. A user who cannot
complete a keyboard-only installation, cannot hear the disk they are about to
erase, cannot enter and confirm a passphrase, or cannot record a recovery key,
does not own the machine. Those five are marked ``critical`` and no other flow's
success compensates for one of them failing.

Three rules the record enforces:

**A run needs steps.** A record with a result and no attempted steps is an
assertion. ``NOT_RUN`` is the correct value for a flow nobody drove, and
:func:`parse_flow_result` refuses to accept ``PASS`` without recorded steps.

**Screenshots need consent.** Media involving a person is only accepted with
explicit consent *and* a completed redaction pass, because an accessibility
recording shows someone using a computer and often shows their face.

**The assistive technology must be named with a version.** "Tested with a screen
reader" is not a finding. "Orca 50.2 on GNOME 50 announces the disk-selection
list but not the disk size" is.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The seventeen flows, with the severity of a failure in each.
ACCESSIBILITY_FLOWS: dict[str, str] = {
    "keyboard-only-installation": "critical",
    "screen-reader-installation": "critical",
    "disk-selection": "critical",
    "encryption": "critical",
    "recovery-key-display": "critical",
    "first-run-setup": "high",
    "login": "critical",
    "launcher": "high",
    "settings": "high",
    "approval-centre": "high",
    "update": "high",
    "rollback": "high",
    "recovery": "critical",
    "diagnostics-export": "medium",
    "high-contrast": "medium",
    "text-scaling": "medium",
    "reduced-motion": "medium",
}

#: Flows whose failure blocks a release outright: each is required to own or
#: recover the machine.
CRITICAL_FLOWS = tuple(name for name, severity in ACCESSIBILITY_FLOWS.items() if severity == "critical")

RESULTS = ("PASS", "FAIL", "PARTIAL", "NOT_RUN")
FAILURE_SEVERITIES = ("critical", "high", "medium", "low", "informational", "none")

#: Environments a flow may be driven in. ``source-inspection`` is deliberately
#: absent: it is not an environment, and the matrix already refuses it.
ENVIRONMENTS = ("physical-hardware", "virtual-machine", "installed-system", "live-image")

#: The two flows that happen before an installed system exists. Both need an
#: installer ISO and either hardware or an interactive VM session.
PRE_INSTALL_FLOWS = ("screen-reader-installation", "keyboard-only-installation")

REDACTION_STATES = ("not-required", "completed", "pending")

_VERSIONED = re.compile(r"\d")


class AccessibilityEvidenceError(ValueError):
    """Raised when an accessibility record is malformed or overclaims."""


@dataclass(frozen=True)
class FlowResult:
    flow: str
    assistiveTechnology: str
    assistiveTechnologyVersion: str
    environment: str
    imageDigest: str
    operator: str
    operatorIsDailyUser: bool
    startedAt: str
    completedAt: str
    steps: tuple[str, ...]
    result: str
    failureSeverity: str
    notes: str
    evidenceReference: str | None
    screenshotConsent: bool
    redactionState: str

    @property
    def blocking(self) -> bool:
        if self.result == "PASS":
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "declaredSeverity": ACCESSIBILITY_FLOWS[self.flow],
            "assistiveTechnology": self.assistiveTechnology,
            "assistiveTechnologyVersion": self.assistiveTechnologyVersion,
            "environment": self.environment,
            "imageDigest": self.imageDigest,
            "operator": self.operator,
            "operatorIsDailyUser": self.operatorIsDailyUser,
            "startedAt": self.startedAt,
            "completedAt": self.completedAt,
            "stepCount": len(self.steps),
            "steps": list(self.steps),
            "result": self.result,
            "failureSeverity": self.failureSeverity,
            "notes": self.notes,
            "evidenceReference": self.evidenceReference,
            "screenshotConsent": self.screenshotConsent,
            "redactionState": self.redactionState,
            "blocking": self.blocking,
        }


def parse_flow_result(
    record: Mapping[str, Any],
    *,
    evidenceRoot: Path | None = None,
) -> FlowResult:
    """Validate one flow result."""
    if not isinstance(record, Mapping):
        raise AccessibilityEvidenceError("flow result must be an object")

    flow = record.get("flow")
    if flow not in ACCESSIBILITY_FLOWS:
        raise AccessibilityEvidenceError(
            f"flow must be one of {', '.join(sorted(ACCESSIBILITY_FLOWS))}"
        )

    result = record.get("result")
    if result not in RESULTS:
        raise AccessibilityEvidenceError(f"{flow}: result must be one of {', '.join(RESULTS)}")

    severity = record.get("failureSeverity", "none")
    if severity not in FAILURE_SEVERITIES:
        raise AccessibilityEvidenceError(
            f"{flow}: failureSeverity must be one of {', '.join(FAILURE_SEVERITIES)}"
        )

    steps = record.get("steps") or []
    if not isinstance(steps, list):
        raise AccessibilityEvidenceError(f"{flow}: steps must be an array")

    if result == "NOT_RUN":
        # A not-run flow needs nothing else, and must not carry a result that
        # implies it was driven.
        if steps:
            raise AccessibilityEvidenceError(
                f"{flow}: recorded NOT_RUN but carries {len(steps)} attempted step(s); a flow that "
                "was partly driven is PARTIAL, not NOT_RUN"
            )
        if severity not in {"none", "informational"}:
            raise AccessibilityEvidenceError(
                f"{flow}: recorded NOT_RUN with failureSeverity {severity!r}; a flow nobody drove "
                "has no observed failure"
            )
    else:
        if not steps:
            raise AccessibilityEvidenceError(
                f"{flow}: result {result!r} with no recorded steps. A result without steps is an "
                "assertion; a flow nobody drove is NOT_RUN"
            )
        for name in ("assistiveTechnology", "assistiveTechnologyVersion", "operator", "startedAt", "completedAt"):
            if not str(record.get(name) or "").strip():
                raise AccessibilityEvidenceError(f"{flow}: {name} is required for a driven flow")
        version = str(record["assistiveTechnologyVersion"])
        if not _VERSIONED.search(version):
            raise AccessibilityEvidenceError(
                f"{flow}: assistiveTechnologyVersion {version!r} carries no version number. "
                "'Tested with a screen reader' is not a finding"
            )
        environment = record.get("environment")
        if environment not in ENVIRONMENTS:
            raise AccessibilityEvidenceError(
                f"{flow}: environment must be one of {', '.join(ENVIRONMENTS)}; a static reading of "
                "the source is not an environment"
            )
        if not str(record.get("imageDigest") or "").strip():
            raise AccessibilityEvidenceError(
                f"{flow}: imageDigest is required; a result that does not name what it tested "
                "cannot be attributed to a build"
            )

    if result == "PASS" and severity not in {"none", "informational"}:
        raise AccessibilityEvidenceError(
            f"{flow}: recorded PASS with failureSeverity {severity!r}; a pass with a failure is a "
            "partial"
        )
    if result in {"FAIL", "PARTIAL"} and severity in {"none"}:
        raise AccessibilityEvidenceError(
            f"{flow}: recorded {result} without a failureSeverity; an unrated failure cannot be "
            "triaged"
        )

    reference = record.get("evidenceReference")
    consent = bool(record.get("screenshotConsent", False))
    redaction = record.get("redactionState", "not-required")
    if redaction not in REDACTION_STATES:
        raise AccessibilityEvidenceError(
            f"{flow}: redactionState must be one of {', '.join(REDACTION_STATES)}"
        )

    if reference:
        if not consent:
            raise AccessibilityEvidenceError(
                f"{flow}: evidence media is referenced without recorded operator consent. An "
                "accessibility recording shows a person using a computer"
            )
        if redaction != "completed":
            raise AccessibilityEvidenceError(
                f"{flow}: evidence media is referenced with redactionState {redaction!r}; faces, "
                "names, hostnames and personal paths must be removed before delivery"
            )
        if evidenceRoot is not None:
            target = (evidenceRoot / str(reference)).resolve()
            try:
                target.relative_to(evidenceRoot.resolve())
            except ValueError:
                raise AccessibilityEvidenceError(
                    f"{flow}: evidenceReference escapes the evidence root"
                ) from None
            if not target.exists():
                raise AccessibilityEvidenceError(
                    f"{flow}: evidenceReference {reference} does not exist"
                )

    return FlowResult(
        flow=str(flow),
        assistiveTechnology=str(record.get("assistiveTechnology", "")),
        assistiveTechnologyVersion=str(record.get("assistiveTechnologyVersion", "")),
        environment=str(record.get("environment", "")),
        imageDigest=str(record.get("imageDigest", "")),
        operator=str(record.get("operator", "")),
        operatorIsDailyUser=bool(record.get("operatorIsDailyUser", False)),
        startedAt=str(record.get("startedAt", "")),
        completedAt=str(record.get("completedAt", "")),
        steps=tuple(str(step) for step in steps),
        result=str(result),
        failureSeverity=str(severity),
        notes=str(record.get("notes", "")),
        evidenceReference=str(reference) if reference else None,
        screenshotConsent=consent,
        redactionState=str(redaction),
    )


def evaluate_evidence(
    document: Mapping[str, Any],
    *,
    evidenceRoot: Path | None = None,
    independentReviewComplete: bool = False,
) -> dict[str, Any]:
    """Evaluate the accessibility evidence record.

    ``independentReviewComplete`` is required for the requirement to be met even
    when every flow passes. The project can drive its own flows and should; it
    cannot be the party that decides its own interfaces are usable by people whose
    needs it does not share.
    """
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise AccessibilityEvidenceError("accessibility evidence schemaVersion is invalid")
    raw = document.get("results")
    if not isinstance(raw, list):
        raise AccessibilityEvidenceError("accessibility evidence must carry a results array")

    results: list[FlowResult] = []
    rejected: list[str] = []
    for item in raw:
        try:
            results.append(parse_flow_result(item, evidenceRoot=evidenceRoot))
        except AccessibilityEvidenceError as exc:
            rejected.append(str(exc))

    by_flow: dict[str, FlowResult] = {}
    for result in results:
        existing = by_flow.get(result.flow)
        # Where a flow was driven more than once, the worst result stands. A
        # later pass does not erase an earlier failure with a different
        # assistive technology.
        if existing is None or RESULTS.index(result.result) > RESULTS.index(existing.result):
            by_flow[result.flow] = result

    missing = sorted(set(ACCESSIBILITY_FLOWS) - set(by_flow))
    not_run = sorted(
        name for name, result in by_flow.items() if result.result == "NOT_RUN"
    ) + missing
    failing = sorted(name for name, result in by_flow.items() if result.result in {"FAIL", "PARTIAL"})
    passing = sorted(name for name, result in by_flow.items() if result.result == "PASS")
    critical_unresolved = sorted(set(CRITICAL_FLOWS) & (set(not_run) | set(failing)))

    technologies = sorted(
        {
            f"{result.assistiveTechnology} {result.assistiveTechnologyVersion}".strip()
            for result in results
            if result.assistiveTechnology
        }
    )

    requirement_met = (
        not rejected
        and not not_run
        and not failing
        and len(passing) == len(ACCESSIBILITY_FLOWS)
        and independentReviewComplete
    )

    reasons: list[str] = []
    if rejected:
        reasons.append(f"{len(rejected)} record(s) rejected")
    if not_run:
        reasons.append(f"{len(not_run)} flow(s) not run: {', '.join(not_run)}")
    if failing:
        reasons.append(f"{len(failing)} flow(s) failing or partial: {', '.join(failing)}")
    if critical_unresolved:
        reasons.append(
            "critical flows unresolved: "
            + ", ".join(critical_unresolved)
            + ". Each is required to own or recover the machine"
        )
    if not independentReviewComplete:
        reasons.append(
            "no independent accessibility review is delivered; the project cannot be the party "
            "that decides its own interfaces are usable"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "flowCount": len(ACCESSIBILITY_FLOWS),
        "recordCount": len(raw),
        "rejected": rejected,
        "passingFlows": passing,
        "failingFlows": failing,
        "notRunFlows": not_run,
        "missingFlows": missing,
        "criticalUnresolvedFlows": critical_unresolved,
        "assistiveTechnologies": technologies,
        "preInstallFlows": list(PRE_INSTALL_FLOWS),
        "independentReviewComplete": independentReviewComplete,
        "requirementMet": requirement_met,
        "reasons": reasons,
        "results": [result.as_dict() for result in sorted(by_flow.values(), key=lambda r: r.flow)],
        "result": "PASS" if requirement_met else "BLOCKED",
        "note": (
            "Static accessibility tests remain useful and cannot satisfy installed-flow evidence. "
            "NOT_RUN is never converted to PASS, and a flow driven twice keeps its worst result."
        ),
    }


def evidence_plan() -> dict[str, Any]:
    """The flows, in priority order, with what each run must record."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "flows": [
            {
                "flow": name,
                "failureSeverity": severity,
                "requiresPreInstallEnvironment": name in PRE_INSTALL_FLOWS,
                "blocksRelease": severity == "critical",
            }
            for name, severity in ACCESSIBILITY_FLOWS.items()
        ],
        "requiredPerRun": [
            "assistiveTechnology and its exact version",
            "environment: physical-hardware, virtual-machine, installed-system or live-image",
            "imageDigest of what was tested",
            "operator, and whether they are a daily user of that technology",
            "startedAt and completedAt",
            "the steps actually attempted",
            "result: PASS, FAIL, PARTIAL or NOT_RUN",
            "failureSeverity for any FAIL or PARTIAL",
            "evidence media only with operator consent and a completed redaction pass",
        ],
        "refusals": [
            "source-inspection is not an environment",
            "a PASS with no recorded steps is refused",
            "a NOT_RUN carrying steps is refused; that is a PARTIAL",
            "media without consent or with pending redaction is refused",
            "an unversioned assistive technology is refused",
        ],
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "ACCESSIBILITY_FLOWS",
    "CRITICAL_FLOWS",
    "ENVIRONMENTS",
    "FAILURE_SEVERITIES",
    "PRE_INSTALL_FLOWS",
    "REDACTION_STATES",
    "RESULTS",
    "AccessibilityEvidenceError",
    "FlowResult",
    "evaluate_evidence",
    "evidence_plan",
    "parse_flow_result",
]

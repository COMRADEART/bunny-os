#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 11 independent-security-review operations.

Phase 8 wrote the review package; Phase 9 built the door evidence enters
through; Phase 10 built candidate operations behind that door. Phase 11
operationalizes the one review those phases have been waiting on, without
performing it: the review stays external, and this module makes it

* requestable — the commissioning package under ``security-review/`` is
  complete, canonical, and names the exact artifact;
* reproducible — the finding baseline derives deterministically from the
  Phase 8 package and is pinned to its bytes, so "the baseline" can never
  quietly become a different document;
* bound — a submission binds to a digest the reviewer computed themselves,
  and evidence for other bytes moves nothing;
* auditable — scope is frozen (``SCOPE-1``) before any response exists,
  and the repository may not remove questions afterwards;
* intake-compatible — submissions enter only through the Phase 9 intake;
  this module prepares, validates, reconciles, and derives, and appends
  nothing to the ledger;
* actionable — accepted evidence reconciles against the baseline into a
  derived finding register with a closed state vocabulary whose closures
  require evidence bound to the right artifact.

The refusals are structural, not prose: a finding cannot close because
code changed; a confirmed Critical cannot be dispositioned by silence; a
conflict between reviewers is recorded, classified, and resolved
fail-closed — never averaged, never auto-resolved in the favorable
direction; and the gate can reach SATISFIED only through an accepted,
contract-valid, approving submission that exists in the ledger.

Determinism: no clocks. Dates come from records or the operator; the
commit is the tamper-evident time.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE11 = ROOT / "qualification" / "phase11"
PACKAGE_DIR = PHASE11 / "security-review"
FIXTURES_DIR = PHASE11 / "fixtures"
REGISTER_PATH = PHASE11 / "security-findings.json"

BASELINE_PATH = PACKAGE_DIR / "FINDINGS_BASELINE.json"
IDENTITY_PATH = PACKAGE_DIR / "ARTIFACT_IDENTITY.json"
SCHEMA_PATH = PACKAGE_DIR / "SUBMISSION_SCHEMA.json"
SCOPE_PATH = PACKAGE_DIR / "REVIEW_SCOPE.md"
VERIFIER_PATH = PACKAGE_DIR / "VERIFY_SUBMISSION.py"

PHASE8_PACKAGE = (
    ROOT / "qualification" / "phase8" / "security-review" / "review-package.json"
)
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE9_TRIAGE = ROOT / "qualification" / "phase9" / "triage" / "findings.json"
PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE10_TOOL = (
    ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
)
PHASE10_GRAPH = (
    ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json"
)

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: The §2 commissioning package, by name. verify fails if any is absent.
PACKAGE_FILES = (
    "REQUEST.md", "REVIEW_SCOPE.md", "ARTIFACT_IDENTITY.json",
    "FINDINGS_BASELINE.json", "REVIEWER_INSTRUCTIONS.md",
    "SUBMISSION_SCHEMA.json", "VERIFY_SUBMISSION.py",
)

SCOPE_VERSION = "SCOPE-1"
FROZEN_QUESTIONS = ("SQ-1", "SQ-2", "SQ-3", "SQ-4",
                    "SQ-5", "SQ-6", "SQ-7", "SQ-8")

#: JSON Schema keywords VERIFY_SUBMISSION.py actually enforces. A schema
#: keyword outside this set would be silently unenforced, so verify()
#: refuses a schema that uses one.
ENFORCED_SCHEMA_KEYWORDS = frozenset({
    "type", "required", "enum", "const", "pattern", "minLength",
    "properties", "items",
})
DESCRIPTIVE_SCHEMA_KEYWORDS = frozenset({
    "$schema", "$id", "title", "description", "x-aliases",
})

#: §9 states. BASELINE is where every Phase 8 finding starts; everything
#: after BASELINE exists only downstream of accepted external evidence.
SECURITY_FINDING_STATES = (
    "BASELINE", "UNDER_REVIEW", "CONFIRMED", "NOT_APPLICABLE",
    "REMEDIATION_REQUIRED", "ACCEPTED_RISK", "DEFERRED",
    "FIXED_PENDING_REQUALIFICATION", "CLOSED",
)

#: Absence is refusal. CONFIRMED → CLOSED is deliberately not here: closure
#: runs through remediation-and-requalification, accepted risk, or
#: evidence-established non-applicability, never directly.
SECURITY_FINDING_TRANSITIONS = {
    "BASELINE": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"CONFIRMED", "NOT_APPLICABLE"},
    "CONFIRMED": {"REMEDIATION_REQUIRED", "ACCEPTED_RISK", "DEFERRED",
                  "NOT_APPLICABLE"},
    "NOT_APPLICABLE": {"CLOSED", "UNDER_REVIEW"},
    "REMEDIATION_REQUIRED": {"FIXED_PENDING_REQUALIFICATION"},
    "ACCEPTED_RISK": {"CLOSED", "REMEDIATION_REQUIRED"},
    "DEFERRED": {"REMEDIATION_REQUIRED", "UNDER_REVIEW"},
    "FIXED_PENDING_REQUALIFICATION": {"CLOSED"},
    "CLOSED": set(),
}

#: §10: the only dispositions a confirmed Critical admits.
CRITICAL_DISPOSITIONS = ("FIX_BEFORE_ALPHA", "ACCEPTED_RISK", "NOT_APPLICABLE")

#: §10: what ACCEPTED_RISK must record. reviewBy is the expiration/review
#: date — an accepted risk without an expiry is a permanent waiver nobody
#: decided to grant.
ACCEPTED_RISK_FIELDS = (
    "decisionAuthority", "rationale", "affectedArtifact",
    "alphaScopeImpact", "reviewBy",
)

#: §7 reconciliation vocabulary.
RECONCILIATION_CLASSES = (
    "CONFIRMED", "NOT_APPLICABLE", "NEW_FINDING", "SEVERITY_CHANGED",
    "SCOPE_CHANGED", "EVIDENCE_CONFLICT", "REQUIRES_FURTHER_ANALYSIS",
)

#: Fail-closed ordering over review outcomes: when accepted submissions
#: disagree, the effective assessment is the most blocking one, pending an
#: explicit resolution — never the most favorable, never an average.
ASSESSMENT_SEVERITY = {
    "APPROVED": 0, "APPROVED_WITH_CONDITIONS": 1,
    "MORE_EVIDENCE_REQUIRED": 2, "BLOCKED": 3,
}

#: §15: the outcomes a recorded reviewer conflict may resolve to.
CONFLICT_OUTCOMES = (
    "RESOLUTION_REQUIRED", "ADDITIONAL_REVIEW_REQUIRED",
    "REMEDIATION_REQUIRED", "BLOCKED",
)

#: §18 gate states, derived. SATISFIED is reachable only through accepted
#: external evidence; AWAITING_EXTERNAL_EVIDENCE is the zero-evidence
#: truth and blocks (it never approves).
GATE_STATES = (
    "AWAITING_EXTERNAL_EVIDENCE", "UNDER_ANALYSIS",
    "REMEDIATION_REQUIRED", "BLOCKED", "SATISFIED",
)

#: §12: what a successor artifact created for a security finding owes
#: before its gate rows can move. Recorded once, cited by the planner
#: outputs; none of these is satisfiable by inheritance.
SECURITY_REQUALIFICATION_REQUIREMENTS = (
    "new artifact identity",
    "artifact digest verification",
    "security rescan",
    "affected functional qualification",
    "regression suite",
    "release gate recomputation",
)

BASELINE_ID = re.compile(r"^SEC-BL-\d{3}$")


class BoundaryViolation(ValueError):
    """A refused transition, closure, derivation, or record."""


# ---------------------------------------------------------------- shared I/O

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verifier():
    return _load_module("phase11_verify_submission", VERIFIER_PATH)


def _phase9():
    return _load_module("phase9_intake_for_phase11", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase11", PHASE10_TOOL)


def is_fixture(record) -> bool:
    return isinstance(record, dict) and record.get(
        "fixtureClass") == FIXTURE_MARKER


def _refuse_fixture(record, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: the record declares fixtureClass %s — a fixture is never "
            "evidence" % (where, FIXTURE_MARKER))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------ baseline (§2)

def build_baseline(package: dict, package_sha256: str) -> dict:
    """FINDINGS_BASELINE.json from the Phase 8 package, deterministically.

    Identifiers SEC-BL-001… are assigned in the package's committed order
    (Critical first, then advisory ascending — the order the deterministic
    builder wrote). The baseline pins the package by sha256: if the Phase 8
    bytes ever change, derivation refuses instead of silently renumbering —
    the baseline is historical evidence, never replaced (§7).
    """
    findings = package["findings"]
    criticals = sum(1 for f in findings if f["severity"] == "Critical")
    highs = sum(1 for f in findings if f["severity"] == "High")
    if criticals != 8 or highs != 36:
        raise BoundaryViolation(
            "refusing to build a baseline of %d Critical + %d High; the "
            "committed Phase 8 record says 8 + 36, and a changed baseline "
            "is a new document, not a silent replacement" % (criticals, highs))
    rows = []
    for index, finding in enumerate(findings, start=1):
        rows.append({
            "internal_id": "SEC-BL-%03d" % index,
            "advisory": finding["advisory"],
            "severity": finding["severity"],
            "affectedPackages": finding.get("affectedPackages") or [],
            "artifactTypes": finding.get("artifactTypes") or [],
            "fixedVersions": finding.get("fixedVersions"),
            "baselineDisposition": finding["disposition"],
        })
    advisories = [row["advisory"] for row in rows]
    if len(advisories) != len(set(advisories)):
        raise BoundaryViolation("advisory identifiers are not unique; the "
                                "baseline cannot key on them")
    return {
        "schemaVersion": 1,
        "purpose": "the finding baseline the independent review answers; "
                   "derived deterministically from the pinned Phase 8 "
                   "package and never edited by hand",
        "subjectArtifact": {
            "identifier": package["artifact"]["identifier"],
            "imageDigest": package["artifact"]["imageDigest"],
        },
        "scopeVersion": SCOPE_VERSION,
        "counts": {"critical": criticals, "high": highs},
        "sourcePackage": {
            "path": "qualification/phase8/security-review/review-package.json",
            "sha256": package_sha256,
        },
        "idPolicy": "SEC-BL-NNN identifies a baseline row in this package "
                    "and is assigned by committed package order. It is not "
                    "a triage identifier: a finding that enters triage "
                    "through accepted evidence receives its (SEC)-(P9|EXT) "
                    "identifier there, and the register records the "
                    "mapping. Reviewers are never required to use either — "
                    "they reference the public advisory identifier.",
        "findings": rows,
    }


def baseline_from_disk() -> tuple[dict, list[str]]:
    """(rebuilt baseline, problems). Refuses drift instead of absorbing it."""
    problems: list[str] = []
    package_bytes = PHASE8_PACKAGE.read_bytes()
    rebuilt = build_baseline(
        json.loads(package_bytes.decode("utf-8")), _sha256(package_bytes))
    if BASELINE_PATH.is_file():
        committed = load_json(BASELINE_PATH)
        if committed.get("sourcePackage", {}).get("sha256") != _sha256(package_bytes):
            problems.append(
                "the Phase 8 package bytes changed under the committed "
                "baseline pin; the baseline is historical evidence and is "
                "never silently replaced — cut a new baseline version "
                "deliberately if the change is real")
        elif committed != rebuilt:
            problems.append(
                "FINDINGS_BASELINE.json does not reproduce from the pinned "
                "Phase 8 package; run build-baseline and review the diff")
    else:
        problems.append("FINDINGS_BASELINE.json is absent; run build-baseline")
    return rebuilt, problems


# ----------------------------------------------------- submissions (§5, §6)

def validate_submission(record) -> list[str]:
    """The §5 contract, enforced from the committed schema; empty == valid."""
    verifier = _verifier()
    return verifier.validate_submission(
        record, verifier.load_schema(SCHEMA_PATH),
        verifier.load_identity(IDENTITY_PATH))


def _established(finding: dict) -> bool:
    """Mechanical floor for an applicability conclusion: evidence and
    rationale both present. Sufficiency of the analysis stays a human
    judgment; its absence is machine-checkable and fails closed."""
    return bool(str(finding.get("evidence") or "").strip()) \
        and bool(str(finding.get("rationale") or "").strip())


def _component_named(component: str, baseline_row: dict) -> bool:
    """Whether the reviewer's affected_component names the baseline row's
    affected set. Substring either way, case-insensitive, against package
    names and full entries; a baseline row with no recorded packages
    cannot be mechanically disputed."""
    packages = baseline_row.get("affectedPackages") or []
    if not packages:
        return True
    wanted = component.strip().lower()
    for entry in packages:
        entry_l = str(entry).lower()
        name = entry_l.split(" ")[0]
        if wanted in entry_l or entry_l in wanted \
                or wanted in name or name in wanted:
            return True
    return False


def reconcile_submission(record: dict, baseline: dict) -> dict:
    """§7: classify one contract-valid submission against the baseline.

    Per reviewer finding, exactly one class. Precedence inside a matched
    pair: an undetermined or unestablished conclusion outranks everything
    (REQUIRES_FURTHER_ANALYSIS), then SEVERITY_CHANGED, then SCOPE_CHANGED,
    then the clean CONFIRMED / NOT_APPLICABLE. Cross-submission
    EVIDENCE_CONFLICT is derived at register level, where every accepted
    submission is visible at once.
    """
    _refuse_fixture(record, "reconciliation")
    by_advisory = {row["advisory"]: row for row in baseline["findings"]}
    classifications = []
    addressed: set[str] = set()
    for finding in record.get("findings") or []:
        advisory = finding.get("baseline_advisory")
        row = by_advisory.get(advisory) if advisory else None
        entry = {
            "reviewer_finding_id": finding.get("reviewer_finding_id"),
            "baseline_advisory": advisory if row else None,
            "internal_id": row["internal_id"] if row else None,
            "applicability": finding.get("applicability"),
            "severity": finding.get("severity"),
        }
        if row is None:
            entry["classification"] = "NEW_FINDING"
            entry["reasoning"] = (
                "no baseline row carries advisory %r; the reviewer may add "
                "findings, and a new finding enters triage for its own "
                "identifier" % (advisory,))
        else:
            addressed.add(advisory)
            applicability = finding.get("applicability")
            severity_agrees = str(finding.get("severity", "")).lower() \
                == row["severity"].lower()
            component_agrees = _component_named(
                str(finding.get("affected_component") or ""), row)
            if applicability == "UNDETERMINED" or not _established(finding):
                entry["classification"] = "REQUIRES_FURTHER_ANALYSIS"
                entry["reasoning"] = (
                    "the conclusion is undetermined or carries no "
                    "establishing analysis; an unestablished answer moves "
                    "no finding")
            elif applicability == "NOT_APPLICABLE":
                entry["classification"] = "NOT_APPLICABLE"
                entry["reasoning"] = "reviewer establishes non-applicability; " \
                                     "the evidence text is recorded verbatim"
            elif not severity_agrees:
                entry["classification"] = "SEVERITY_CHANGED"
                entry["reasoning"] = "baseline says %s, reviewer says %s" % (
                    row["severity"], finding.get("severity"))
            elif not component_agrees:
                entry["classification"] = "SCOPE_CHANGED"
                entry["reasoning"] = (
                    "the reviewer's affected component %r is not in the "
                    "baseline row's affected set"
                    % finding.get("affected_component"))
            else:
                entry["classification"] = "CONFIRMED"
                entry["reasoning"] = "applicable, same severity, same scope"
        classifications.append(entry)
    unaddressed = sorted(set(by_advisory) - addressed)
    return {
        "classifications": classifications,
        "unaddressedBaseline": unaddressed,
        "note": "unaddressed baseline rows stay in their prior state; "
                "silence about a finding never dispositions it",
    }


# ------------------------------------------------------------ conflicts (§15)

def classify_conflict(assessments: list[tuple[str, str]]) -> dict | None:
    """Submission-level disagreement between accepted reviews, or None.

    ``assessments`` is [(intakeId, overall_assessment), …]. Disagreement is
    recorded and classified, never averaged; the effective assessment
    pending resolution is the most blocking one.
    """
    for intake_id, assessment in assessments:
        if assessment not in ASSESSMENT_SEVERITY:
            raise BoundaryViolation(
                "%s: %r is not a review outcome" % (intake_id, assessment))
    distinct = {assessment for _, assessment in assessments}
    if len(assessments) < 2 or len(distinct) < 2:
        return None
    approving = {"APPROVED", "APPROVED_WITH_CONDITIONS"} & distinct
    blocking = {"BLOCKED"} & distinct
    effective = max(distinct, key=ASSESSMENT_SEVERITY.__getitem__)
    return {
        "classification": "CONTRADICTORY_CONCLUSIONS"
        if approving and blocking else "DIVERGENT_ASSESSMENTS",
        "submissions": [
            {"intakeId": intake_id, "assessment": assessment}
            for intake_id, assessment in assessments
        ],
        "effectiveAssessment": effective,
        "resolution": "RESOLUTION_REQUIRED",
        "allowedOutcomes": list(CONFLICT_OUTCOMES),
        "note": "both submissions are preserved; the effective assessment "
                "is the most blocking pending an explicit recorded "
                "resolution — the repository never selects the favorable "
                "interpretation",
    }


def validate_conflict_resolution(resolution: str) -> str:
    if resolution not in CONFLICT_OUTCOMES:
        raise BoundaryViolation(
            "%r is not a conflict outcome; allowed: %s"
            % (resolution, ", ".join(CONFLICT_OUTCOMES)))
    return resolution


# ------------------------------------------------- finding lifecycle (§9)

def _acceptance_missing(acceptance: dict | None) -> list[str]:
    acceptance = acceptance or {}
    return [f for f in ACCEPTED_RISK_FIELDS if not acceptance.get(f)]


def security_finding_transition(finding: dict, target: str,
                                context: dict | None = None) -> str:
    """Advance one register finding; refusal is the default.

    Closure requires evidence bound to the right artifact: a code change
    closes nothing, a requalified successor closes only what its own
    evidence covers, and approval never transfers between artifacts.
    """
    current = finding.get("status")
    if current not in SECURITY_FINDING_STATES:
        raise BoundaryViolation("unknown security finding state %r" % current)
    if target not in SECURITY_FINDING_STATES:
        raise BoundaryViolation("unknown security finding state %r" % target)
    if target not in SECURITY_FINDING_TRANSITIONS[current]:
        raise BoundaryViolation(
            "security finding transition %s -> %s is not allowed; the "
            "allowed set from %s is {%s}"
            % (current, target, current,
               ", ".join(sorted(SECURITY_FINDING_TRANSITIONS[current]))
               or "nothing"))
    context = context or {}

    if target in ("UNDER_REVIEW", "CONFIRMED"):
        if not context.get("sourceEvidence"):
            raise BoundaryViolation(
                "%s requires sourceEvidence (the accepted intake ID); "
                "review states exist only downstream of external evidence"
                % target)

    if target == "NOT_APPLICABLE":
        evidence = context.get("applicabilityEvidence") or {}
        if not evidence.get("reference") or not str(
                evidence.get("analysis") or "").strip():
            raise BoundaryViolation(
                "NOT_APPLICABLE requires the establishing evidence "
                "(reference + analysis); 'not exploitable' without "
                "supporting analysis is not sufficient")

    if target == "ACCEPTED_RISK":
        missing = _acceptance_missing(context.get("acceptance"))
        if missing:
            raise BoundaryViolation(
                "ACCEPTED_RISK requires %s; missing: %s — there is no "
                "silent acceptance"
                % ("/".join(ACCEPTED_RISK_FIELDS), ", ".join(missing)))

    if target == "FIXED_PENDING_REQUALIFICATION":
        successor = context.get("remediationArtifact")
        if not successor:
            raise BoundaryViolation(
                "FIXED_PENDING_REQUALIFICATION requires the successor "
                "artifact identity; a fix that produced no new artifact "
                "changed nothing shipped")
        if successor == finding.get("artifact"):
            raise BoundaryViolation(
                "the remediation artifact equals the finding's artifact; "
                "the frozen artifact is never modified — a fix is a new "
                "artifact with its own qualification boundary")

    if target == "CLOSED":
        closure = context.get("closureEvidence") or {}
        if not closure.get("reference") or not closure.get("artifact"):
            raise BoundaryViolation(
                "CLOSED requires closure evidence (reference + artifact); "
                "a finding is never closed by silence or by a code change")
        if current == "FIXED_PENDING_REQUALIFICATION":
            successor = context.get("remediationArtifact") \
                or finding.get("remediation_artifact")
            if not successor:
                raise BoundaryViolation(
                    "closing a fixed finding requires its recorded "
                    "remediation artifact")
            if closure["artifact"] != successor:
                raise BoundaryViolation(
                    "closure evidence binds to %s but the remediation "
                    "artifact is %s; requalification belongs to the "
                    "artifact that was actually tested — approval does "
                    "not transfer" % (closure["artifact"], successor))
        if current == "ACCEPTED_RISK":
            missing = _acceptance_missing(
                context.get("acceptance") or finding.get("acceptance"))
            if missing:
                raise BoundaryViolation(
                    "closing an accepted risk requires the full acceptance "
                    "record; missing: %s" % ", ".join(missing))
        if current == "NOT_APPLICABLE":
            evidence = context.get("applicabilityEvidence") \
                or finding.get("applicability_evidence") or {}
            if not evidence.get("reference"):
                raise BoundaryViolation(
                    "closing a non-applicable finding requires the "
                    "evidence that established non-applicability")
    return target


def critical_disposition_gaps(rows: list[dict]) -> list[str]:
    """§10: confirmed Criticals still awaiting an explicit disposition.

    A gap is not an invariant violation — the disposition is a human
    decision that follows confirmation — but the gate cannot be SATISFIED
    while one exists, and the list is the work queue."""
    return sorted(
        row.get("internal_id") or "<unnamed>" for row in rows
        if str(row.get("severity", "")).lower() == "critical"
        and row.get("status") == "CONFIRMED"
        and row.get("disposition") not in CRITICAL_DISPOSITIONS)


def validate_register_row(row: dict) -> list[str]:
    """§9/§10 as state invariants over one committed register row.

    The transition guard refuses illegal steps as they happen; this
    validates the standing record, so a row written by any other route
    still cannot claim a state without the evidence that state requires.
    """
    issues: list[str] = []
    status = row.get("status")
    if status not in SECURITY_FINDING_STATES:
        issues.append("%s: status %r is not in the vocabulary"
                      % (row.get("internal_id"), status))
        return issues
    rid = row.get("internal_id") or "<unnamed>"
    if not row.get("artifact"):
        issues.append("%s: a finding without an artifact binds to nothing" % rid)
    if status not in ("BASELINE",) and not row.get("source_evidence_id"):
        issues.append(
            "%s: state %s claims external evidence but names none — review "
            "states exist only downstream of accepted intake" % (rid, status))
    if status == "NOT_APPLICABLE" and not (
            row.get("applicability_evidence") or {}).get("reference"):
        issues.append(
            "%s: NOT_APPLICABLE without establishing evidence; 'not "
            "exploitable' alone is not sufficient" % rid)
    if status == "ACCEPTED_RISK":
        missing = _acceptance_missing(row.get("acceptance"))
        if missing:
            issues.append("%s: ACCEPTED_RISK missing %s"
                          % (rid, ", ".join(missing)))
    if status == "FIXED_PENDING_REQUALIFICATION":
        if not row.get("remediation_artifact"):
            issues.append("%s: fixed without a successor artifact" % rid)
        elif row["remediation_artifact"] == row.get("artifact"):
            issues.append("%s: the 'fix' claims the frozen artifact itself"
                          % rid)
    if status == "CLOSED":
        closure = row.get("closure_evidence") or {}
        if not closure.get("reference") or not closure.get("artifact"):
            issues.append("%s: CLOSED without closure evidence" % rid)
        elif row.get("remediation_artifact") \
                and closure["artifact"] != row["remediation_artifact"]:
            issues.append(
                "%s: closure evidence binds to %s, not the remediation "
                "artifact %s — approval does not transfer"
                % (rid, closure["artifact"], row["remediation_artifact"]))
    if str(row.get("severity", "")).lower() == "critical" \
            and row.get("disposition") is not None \
            and row["disposition"] not in CRITICAL_DISPOSITIONS:
        issues.append(
            "%s: %r is not a Critical disposition; allowed: %s"
            % (rid, row["disposition"], "/".join(CRITICAL_DISPOSITIONS)))
    if row.get("disposition") == "ACCEPTED_RISK":
        missing = _acceptance_missing(row.get("acceptance"))
        if missing:
            issues.append("%s: disposition ACCEPTED_RISK missing %s"
                          % (rid, ", ".join(missing)))
    if row.get("disposition") == "NOT_APPLICABLE" and not (
            row.get("applicability_evidence") or {}).get("reference"):
        issues.append("%s: disposition NOT_APPLICABLE without the evidence "
                      "establishing it" % rid)
    return issues


# ------------------------------------------------- remediation path (§11/12)

def validate_successor_entry(entry: dict, parent_id: str) -> list[str]:
    """What a security-remediation successor must look like at birth."""
    issues = []
    if entry.get("relationship") != "REMEDIATES":
        issues.append("a security fix produces a REMEDIATES successor; "
                      "%r is recorded" % entry.get("relationship"))
    if entry.get("parent_artifact") != parent_id:
        issues.append("the successor's parent must be the finding's "
                      "artifact %s" % parent_id)
    if entry.get("qualification_state") != "REQUALIFICATION_REQUIRED":
        issues.append(
            "a successor begins REQUALIFICATION_REQUIRED, not %r — it "
            "inherits no PASS" % entry.get("qualification_state"))
    if not entry.get("digest"):
        issues.append("a successor without its own digest is not a new "
                      "artifact")
    return issues


def validate_security_requalification_plan(plan: dict) -> list[str]:
    """§12: the plan for a security successor, checked against the Phase 10
    planner's own rules — SECURITY and RELEASE stay REQUIRED, and no plan
    row may smuggle a PASS."""
    ops10 = _phase10()
    issues = list(ops10.validate_plan(plan))
    for domain in ("SECURITY", "RELEASE"):
        row = plan.get(domain) or {}
        if row.get("status") != "REQUIRED":
            issues.append(
                "%s must be REQUIRED for a security successor; evidence "
                "binds to exact bytes and never transfers by default"
                % domain)
    return issues


# --------------------------------------------------- register derivation (§8)

def _accepted_security_submissions(ledger: dict, intake_root: Path) -> list[dict]:
    """Gate-eligible ACCEPTED security-review intakes with their records.

    Reads the intake tree; never writes it. A ledger entry carrying the
    fixture marker is refused outright.
    """
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    submissions = []
    for entry in ledger.get("entries", []):
        if is_fixture(entry):
            raise BoundaryViolation(
                "ledger entry %s carries the fixture marker; fixtures "
                "never enter the intake ledger" % entry.get("intakeId"))
        if entry.get("source") != "security-review":
            continue
        if not entry.get("gateEligible"):
            continue
        if effective.get(entry["intakeId"]) != "ACCEPTED":
            continue
        record_path = (intake_root / "security-review"
                       / entry["intakeId"] / "record.json")
        submissions.append({
            "intakeId": entry["intakeId"],
            "record": json.loads(record_path.read_text(encoding="utf-8")),
        })
    return submissions


def _evidence_states(reconciled: list[dict]) -> dict[str, dict]:
    """advisory → the evidence-derived row overlay, conflicts detected.

    ``reconciled`` is [{intakeId, reconciliation}, …] over every accepted,
    contract-valid submission. When two submissions classify the same
    advisory incompatibly (one applicable-ish, one NOT_APPLICABLE), the
    overlay is EVIDENCE_CONFLICT and the row goes no further than
    UNDER_REVIEW until a recorded resolution exists.
    """
    overlay: dict[str, dict] = {}
    for item in reconciled:
        for entry in item["reconciliation"]["classifications"]:
            advisory = entry.get("baseline_advisory")
            if not advisory:
                continue
            record = overlay.setdefault(advisory, {"evidence": []})
            record["evidence"].append({
                "intakeId": item["intakeId"],
                "reviewer_finding_id": entry.get("reviewer_finding_id"),
                "classification": entry["classification"],
                "reasoning": entry.get("reasoning", ""),
            })
    for advisory, record in overlay.items():
        classes = {e["classification"] for e in record["evidence"]}
        applicable_ish = classes & {"CONFIRMED", "SEVERITY_CHANGED",
                                    "SCOPE_CHANGED"}
        if applicable_ish and "NOT_APPLICABLE" in classes:
            record["class"] = "EVIDENCE_CONFLICT"
            record["status"] = "UNDER_REVIEW"
        elif classes == {"CONFIRMED"}:
            record["class"] = "CONFIRMED"
            record["status"] = "CONFIRMED"
        elif classes == {"NOT_APPLICABLE"}:
            record["class"] = "NOT_APPLICABLE"
            record["status"] = "NOT_APPLICABLE"
        else:
            record["class"] = sorted(classes)[0] if len(classes) == 1 \
                else "REQUIRES_FURTHER_ANALYSIS"
            record["status"] = "UNDER_REVIEW"
    return overlay


def derive_security_gate(submissions: list[dict], rows: list[dict],
                         conflict: dict | None) -> dict:
    """§18: one gate state, fail-closed, from the evidence actually held."""
    valid = [s for s in submissions if not s["contractProblems"]]
    if not submissions:
        return {
            "status": "AWAITING_EXTERNAL_EVIDENCE",
            "basis": "zero gate-eligible accepted security-review intakes "
                     "exist; absence blocks, it does not authorize",
        }
    if not valid:
        return {
            "status": "UNDER_ANALYSIS",
            "basis": "accepted intake(s) exist but none satisfies the "
                     "submission contract; usable when revised — "
                     "%s" % "; ".join(
                         "%s: %d problem(s)" % (s["intakeId"],
                                                len(s["contractProblems"]))
                         for s in submissions),
        }
    remediation = [r["internal_id"] for r in rows
                   if r.get("status") == "REMEDIATION_REQUIRED"
                   or r.get("disposition") == "FIX_BEFORE_ALPHA"]
    if remediation:
        return {
            "status": "REMEDIATION_REQUIRED",
            "basis": "finding(s) %s require a fix; the fix is a new "
                     "artifact with its own qualification boundary"
                     % ", ".join(sorted(remediation)),
        }
    effective = conflict["effectiveAssessment"] if conflict else \
        valid[0]["record"]["overall_assessment"]
    if conflict:
        return {
            "status": "BLOCKED" if effective == "BLOCKED" else "UNDER_ANALYSIS",
            "basis": "accepted reviews conflict (%s); the effective "
                     "assessment pending resolution is the most blocking: %s"
                     % (conflict["classification"], effective),
        }
    if effective == "BLOCKED":
        return {"status": "BLOCKED",
                "basis": "the accepted independent review returns BLOCKED"}
    if effective == "MORE_EVIDENCE_REQUIRED":
        return {"status": "UNDER_ANALYSIS",
                "basis": "the accepted independent review requires more "
                         "evidence"}
    # A NEW_FINDING row carries no internal_id (the register never mints
    # triage identifiers), so a new Critical is named by the reviewer's
    # own finding identifier here. Found by Phase 15's new-Critical
    # scenario: sorting bare internal_ids raised TypeError on None, so a
    # new Critical crashed the derivation instead of holding the gate.
    open_criticals = sorted(
        r.get("internal_id") or r.get("source_finding_id") or "<unnamed>"
        for r in rows
        if str(r.get("severity", "")).lower() == "critical"
        and r.get("status") not in ("NOT_APPLICABLE", "CLOSED")
        and r.get("disposition") not in CRITICAL_DISPOSITIONS)
    unresolved = sorted(
        r.get("internal_id") or r.get("source_finding_id") or "<unnamed>"
        for r in rows
        if r.get("reconciliation") in ("REQUIRES_FURTHER_ANALYSIS",
                                       "EVIDENCE_CONFLICT")
        or (r.get("reconciliation") == "NEW_FINDING"
            and r.get("status") == "UNDER_REVIEW"))
    if open_criticals or unresolved:
        return {
            "status": "UNDER_ANALYSIS",
            "basis": "an approving review exists but %s"
                     % "; ".join(filter(None, [
                         "Critical finding(s) %s lack an accepted "
                         "disposition" % ", ".join(open_criticals)
                         if open_criticals else "",
                         "finding(s) %s remain unresolved"
                         % ", ".join(unresolved) if unresolved else ""])),
        }
    return {
        "status": "SATISFIED",
        "basis": "accepted independent review %s (%s) with every Critical "
                 "dispositioned and nothing unresolved"
                 % (valid[0]["intakeId"], effective),
    }


def derive_register(baseline: dict, ledger: dict, graph: dict,
                    intake_root: Path) -> dict:
    """qualification/phase11/security-findings.json, reproducibly.

    Inputs: the pinned baseline, the Phase 9 ledger (read, never written),
    the artifact graph. With zero accepted evidence this is the baseline
    verbatim, every row BASELINE, and the gate AWAITING_EXTERNAL_EVIDENCE —
    zero recorded as zero, never as clean.
    """
    ops10 = _phase10()
    graph_issues = ops10.validate_graph(graph)
    if graph_issues:
        raise BoundaryViolation("artifact graph invalid: %s"
                                % "; ".join(graph_issues))
    candidate = ops10._active_candidate(graph)

    subject = baseline["subjectArtifact"]["identifier"]
    if candidate["artifact_id"] != subject:
        raise BoundaryViolation(
            "the active candidate %s is not the baseline's subject %s; a "
            "successor artifact starts its own review, it does not inherit "
            "this one" % (candidate["artifact_id"], subject))

    submissions = []
    for item in _accepted_security_submissions(ledger, intake_root):
        record = item["record"]
        problems = validate_submission(record)
        submissions.append({
            "intakeId": item["intakeId"],
            "record": record,
            "contractProblems": problems,
            "reconciliation": None if problems
            else reconcile_submission(record, baseline),
        })

    valid = [s for s in submissions if not s["contractProblems"]]
    overlay = _evidence_states(
        [{"intakeId": s["intakeId"], "reconciliation": s["reconciliation"]}
         for s in valid])
    conflict = classify_conflict(
        [(s["intakeId"], s["record"]["overall_assessment"]) for s in valid])

    rows = []
    for base_row in baseline["findings"]:
        advisory = base_row["advisory"]
        evidence = overlay.get(advisory)
        row = {
            "internal_id": base_row["internal_id"],
            "source_finding_id": advisory,
            "source_evidence_id": None,
            "artifact": subject,
            "severity": base_row["severity"],
            "status": "BASELINE",
            "applicability": base_row["baselineDisposition"],
            "reconciliation": None,
            "disposition": None,
            "remediation_artifact": None,
            "closure_evidence": None,
            "reviewerEvidence": [],
        }
        if evidence:
            row["status"] = evidence["status"]
            row["reconciliation"] = evidence["class"]
            row["reviewerEvidence"] = evidence["evidence"]
            row["source_evidence_id"] = ",".join(sorted(
                {e["intakeId"] for e in evidence["evidence"]}))
            if evidence["class"] == "NOT_APPLICABLE":
                row["applicability"] = "NOT_APPLICABLE"
                row["applicability_evidence"] = {
                    "reference": row["source_evidence_id"],
                    "analysis": "; ".join(
                        e["reasoning"] for e in evidence["evidence"]),
                }
            elif evidence["class"] == "CONFIRMED":
                row["applicability"] = "APPLICABLE"
        rows.append(row)

    new_findings = []
    for submission in valid:
        for entry in submission["reconciliation"]["classifications"]:
            if entry["classification"] != "NEW_FINDING":
                continue
            new_findings.append({
                "internal_id": None,
                "internalIdNote": "assigned at first triage in the Phase "
                                  "9/10 registries ((SEC)-(P9|EXT)-NNN); "
                                  "the register never mints triage "
                                  "identifiers",
                "source_finding_id": entry.get("reviewer_finding_id"),
                "source_evidence_id": submission["intakeId"],
                "artifact": subject,
                "severity": entry.get("severity"),
                "status": "UNDER_REVIEW",
                "applicability": entry.get("applicability"),
                "reconciliation": "NEW_FINDING",
                "disposition": None,
                "remediation_artifact": None,
                "closure_evidence": None,
            })

    all_rows = rows + new_findings
    invariant_issues = [issue for row in all_rows
                        for issue in validate_register_row(row)]
    if invariant_issues:
        raise BoundaryViolation("register invariants violated: %s"
                                % "; ".join(invariant_issues))

    gate = derive_security_gate(submissions, all_rows, conflict)

    return {
        "schemaVersion": 1,
        "subjectArtifact": subject,
        "scopeVersion": SCOPE_VERSION,
        "stateVocabulary": list(SECURITY_FINDING_STATES),
        "transitionAuthority": "qualification/phase11/tools/"
                               "security_review_ops.py "
                               "SECURITY_FINDING_TRANSITIONS",
        "reconciliationVocabulary": list(RECONCILIATION_CLASSES),
        "criticalDispositionVocabulary": list(CRITICAL_DISPOSITIONS),
        "acceptedRiskFields": list(ACCEPTED_RISK_FIELDS),
        "counts": {
            "baseline": len(rows),
            "fromEvidence": len(new_findings),
            "acceptedSubmissions": len(submissions),
            "contractValidSubmissions": len(valid),
        },
        "securityGate": gate,
        "reviewConflict": conflict,
        "acceptedSubmissions": [
            {"intakeId": s["intakeId"],
             "overallAssessment": s["record"].get("overall_assessment"),
             "contractProblems": s["contractProblems"]}
            for s in submissions
        ],
        "findings": all_rows,
        "derivedFrom": {
            "baseline": "qualification/phase11/security-review/"
                        "FINDINGS_BASELINE.json (pinned to the Phase 8 "
                        "package by sha256)",
            "intakeLedger": "qualification/phase9/intake/LEDGER.json "
                            "(read-only)",
            "artifactGraph": "qualification/phase10/artifacts/"
                             "artifact-graph.json",
            "note": "derived, not intake evidence: recomputable from these "
                    "inputs on every run; tested by tests/release/"
                    "test_phase11_security_review.py",
        },
        "note": "An empty evidence overlay means no independent review has "
                "arrived — it is never APPROVED, NO FINDINGS, CLEAN, or "
                "PASS, and the absence remains a blocking condition.",
    }


def sync_register(write: bool = True) -> tuple[dict, list[str]]:
    """Recompute security-findings.json from its inputs; refuse drift."""
    _, problems = baseline_from_disk()
    if problems:
        return {}, problems
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    derived = derive_register(
        load_json(BASELINE_PATH),
        json.loads(ledger_bytes.decode("utf-8")),
        load_json(PHASE10_GRAPH),
        PHASE9_LEDGER.parent,
    )
    if PHASE9_LEDGER.read_bytes() != ledger_bytes:
        return derived, ["the Phase 9 ledger changed underfoot; refusing"]
    if write:
        dump_json(REGISTER_PATH, derived)
    return derived, []


# ---------------------------------------------------------------- verify

def _scope_problems() -> list[str]:
    text = SCOPE_PATH.read_text(encoding="utf-8")
    problems = []
    if SCOPE_VERSION not in text:
        problems.append("REVIEW_SCOPE.md does not carry version %s"
                        % SCOPE_VERSION)
    for question in FROZEN_QUESTIONS:
        if question not in text:
            problems.append(
                "REVIEW_SCOPE.md lost frozen question %s; questions are "
                "never removed after the review is commissioned" % question)
    return problems


def _schema_problems() -> list[str]:
    """The schema must (a) use only keywords the validator enforces, and
    (b) still require the aliases the Phase 9 boundary reads."""
    problems: list[str] = []

    def walk(node, where: str):
        if isinstance(node, dict):
            for key, value in node.items():
                if where == "schema" and key in DESCRIPTIVE_SCHEMA_KEYWORDS:
                    continue
                if key in ("description", "title"):
                    continue
                if key not in ENFORCED_SCHEMA_KEYWORDS:
                    problems.append(
                        "%s: schema keyword %r is not enforced by "
                        "VERIFY_SUBMISSION.py; an unenforced constraint is "
                        "a fiction" % (where, key))
                    continue
                if key in ("properties",):
                    for name, sub in value.items():
                        walk(sub, "%s.%s" % (where, name))
                elif key == "items":
                    walk(value, "%s[]" % where)

    schema = load_json(SCHEMA_PATH)
    walk(schema, "schema")
    required = set(schema.get("required", []))
    scope_versions = (schema.get("properties", {})
                      .get("review_scope_version", {}).get("enum", []))
    if SCOPE_VERSION not in scope_versions:
        problems.append("the schema does not accept scope version %s"
                        % SCOPE_VERSION)
    for alias, canonical in schema.get("x-aliases", []):
        if alias not in required or canonical not in required:
            problems.append(
                "alias pair (%s, %s) is not required by the schema; the "
                "Phase 9 boundary reads %s and this contract reads %s — "
                "both must exist" % (alias, canonical, alias, canonical))
    return problems


def _identity_problems() -> list[str]:
    """The commissioning package must agree with the intake boundary."""
    identity = load_json(IDENTITY_PATH)["subjectArtifact"]
    ledger = load_json(PHASE9_LEDGER)["subjectArtifact"]
    problems = []
    for key in ("identifier", "imageDigest", "isoSha256", "qcow2Sha256",
                "ociTarSha256", "rawSha256", "sourceCommit", "signingStatus"):
        if identity.get(key) != ledger.get(key):
            problems.append(
                "ARTIFACT_IDENTITY.json %s disagrees with the intake "
                "ledger's subject artifact; the reviewer must not be handed "
                "an identity the boundary will refuse" % key)
    return problems


def verify_fixtures() -> list[str]:
    """Every fixture is structurally marked; the marker never appears in
    the commissioning package itself."""
    issues = []
    if FIXTURES_DIR.is_dir():
        for path in sorted(FIXTURES_DIR.glob("*.json")):
            try:
                record = load_json(path)
            except json.JSONDecodeError:
                issues.append("%s: unparseable fixture" % path.name)
                continue
            if not is_fixture(record):
                issues.append(
                    "%s: a fixture without fixtureClass %s is structurally "
                    "indistinguishable from evidence"
                    % (path.name, FIXTURE_MARKER))
    for name in ("ARTIFACT_IDENTITY.json", "FINDINGS_BASELINE.json",
                 "SUBMISSION_SCHEMA.json"):
        try:
            if is_fixture(load_json(PACKAGE_DIR / name)):
                issues.append("%s carries the fixture marker" % name)
        except (OSError, json.JSONDecodeError):
            pass
    return issues


def verify_all() -> list[str]:
    issues: list[str] = []
    for name in PACKAGE_FILES:
        if not (PACKAGE_DIR / name).is_file():
            issues.append("package: %s is missing from the commissioning "
                          "package" % name)
    if not issues:
        issues += ["scope: %s" % p for p in _scope_problems()]
        issues += ["schema: %s" % p for p in _schema_problems()]
        issues += ["identity: %s" % p for p in _identity_problems()]
        _, baseline_problems = baseline_from_disk()
        issues += ["baseline: %s" % p for p in baseline_problems]
    issues += ["fixtures: %s" % p for p in verify_fixtures()]
    if not issues:
        derived, problems = sync_register(write=False)
        issues += ["register: %s" % p for p in problems]
        if not problems:
            if REGISTER_PATH.is_file():
                if load_json(REGISTER_PATH) != derived:
                    issues.append(
                        "register: committed security-findings.json does "
                        "not reproduce from its inputs; run sync and "
                        "review the diff")
            else:
                issues.append("register: security-findings.json is absent; "
                              "run sync")
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 11 security-review operations verify clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_build_baseline(_args) -> int:
    rebuilt, _problems = baseline_from_disk()
    committed = load_json(BASELINE_PATH) if BASELINE_PATH.is_file() else None
    if committed is not None and committed != rebuilt:
        committed_pin = committed.get("sourcePackage", {}).get("sha256")
        if committed_pin != rebuilt["sourcePackage"]["sha256"]:
            print("REFUSED: the committed baseline pins different Phase 8 "
                  "bytes; the baseline is historical evidence — a changed "
                  "package needs a deliberate new baseline version, not an "
                  "overwrite")
            return 2
    dump_json(BASELINE_PATH, rebuilt)
    counts = rebuilt["counts"]
    print("baseline written: %d Critical + %d High, pinned to %s"
          % (counts["critical"], counts["high"],
             rebuilt["sourcePackage"]["sha256"][:12]))
    return 0


def _cmd_sync(_args) -> int:
    derived, problems = sync_register(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    gate = derived["securityGate"]
    print("security-findings.json derived; %d finding(s); gate %s"
          % (len(derived["findings"]), gate["status"]))
    return 0


def _cmd_validate_submission(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    problems = validate_submission(record)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("record satisfies the submission contract (validation is not "
          "acceptance; the Phase 9 intake is the only door)")
    return 0


def _cmd_reconcile(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    problems = validate_submission(record)
    if problems:
        for problem in problems:
            print(problem)
        print("refusing to reconcile a record that fails the contract")
        return 2
    result = reconcile_submission(record, load_json(BASELINE_PATH))
    for entry in result["classifications"]:
        print("%-24s %-28s %s" % (entry.get("reviewer_finding_id"),
                                  entry["classification"],
                                  entry.get("baseline_advisory") or "-"))
    print("unaddressed baseline rows: %d" % len(result["unaddressedBaseline"]))
    print("(analysis only; nothing was appended anywhere)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser(
        "verify", help="package, scope freeze, baseline pin, register "
                       "reproducibility; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    base = commands.add_parser(
        "build-baseline", help="derive FINDINGS_BASELINE.json from the "
                               "pinned Phase 8 package")
    base.set_defaults(func=_cmd_build_baseline)

    sync = commands.add_parser(
        "sync", help="derive security-findings.json from its inputs")
    sync.set_defaults(func=_cmd_sync)

    val = commands.add_parser(
        "validate-submission", help="check one record.json against the "
                                    "submission contract")
    val.add_argument("record")
    val.set_defaults(func=_cmd_validate_submission)

    rec = commands.add_parser(
        "reconcile", help="classify one contract-valid record against the "
                          "baseline (analysis only; appends nothing)")
    rec.add_argument("record")
    rec.set_defaults(func=_cmd_reconcile)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

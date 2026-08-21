#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 12 Alpha tester program operations.

Phase 8 designed the Alpha program; Phase 9 built the door its evidence
enters through; Phases 10 and 11 built candidate and security operations
behind that door. Phase 12 operationalizes the tester program itself,
without inventing a single tester: the actual testing stays external, and
this module makes the process

* invitable — the canonical package under ``alpha/`` is complete, pins the
  Phase 7/8 sources it reuses by sha256, and fails closed if a pinned
  source changes;
* digest-bound — a report records the digest the tester observed (or an
  honest MISSING), and an unbound report is preserved as
  USER_EVIDENCE_UNBOUND without ever being silently upgraded;
* privacy-minimized — testers are T-NNN, machines are tester-chosen
  labels, and the intake's credential scan refuses likely secrets before
  a byte is ingested;
* reproducible — reproduction attempts are recorded beside the report
  they investigate, and NOT_REPRODUCED is never INVALID;
* auditable — every derived finding names its source reports, every
  dedup relationship is a recorded, reversible decision, and the tester's
  words are copied verbatim, never rewritten into stronger claims;
* actionable — the derived register carries one program state and one
  sufficiency determination, computed fail-closed: silence advances
  nothing, one success is one observation, and zero reports derive zero.

Evidence enters only through the Phase 9 intake; this module prepares,
validates, joins, and derives, and appends nothing to the ledger. Finding
lifecycle authority stays with Phase 10 (``candidate_ops.py``); artifact
applicability stays with Phase 10; the security review stays with
Phase 11 — an Alpha tester's security observation is surfaced to that
workflow and can never impersonate it.

Determinism: no clocks. Dates come from records or the operator; the
commit is the tamper-evident time.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE12 = ROOT / "qualification" / "phase12"
PACKAGE_DIR = PHASE12 / "alpha"
FIXTURES_DIR = PHASE12 / "fixtures"
REGISTER_PATH = PHASE12 / "alpha-findings.json"
DEDUP_PATH = PHASE12 / "dedup-decisions.json"
REPRO_PATH = PHASE12 / "reproductions.json"
POLICY_PATH = PHASE12 / "sufficiency-policy.json"

PINS_PATH = PACKAGE_DIR / "PHASE8_PINS.json"
IDENTITY_PATH = PACKAGE_DIR / "ARTIFACT_IDENTITY.json"
SCHEMA_PATH = PACKAGE_DIR / "TESTER_REPORT_SCHEMA.json"
VERIFIER_PATH = PACKAGE_DIR / "VERIFY_TESTER_REPORT.py"

PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE9_TRIAGE = ROOT / "qualification" / "phase9" / "triage" / "findings.json"
PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE10_TOOL = ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
PHASE10_GRAPH = (
    ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json"
)

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: The §3 canonical package plus the two files it needs to be self-honest
#: (the identity the tester verifies against, and the pins that keep the
#: reused Phase 7/8 sources from drifting underneath it).
PACKAGE_FILES = (
    "PROGRAM.md", "TESTER_SCOPE.md", "TESTER_LIMITATIONS.md",
    "GETTING_STARTED.md", "REPORTING.md", "ARTIFACT_VERIFICATION.md",
    "TESTER_REPORT_SCHEMA.json", "REPRODUCTION_PROTOCOL.md",
    "TRIAGE_POLICY.md", "PRIVACY_POLICY.md", "VERIFY_TESTER_REPORT.py",
    "ARTIFACT_IDENTITY.json", "PHASE8_PINS.json",
)

#: Reused Phase 7/8 sources, pinned by sha256 in PHASE8_PINS.json. A pinned
#: source changing fails derivation closed — the tester-facing restatements
#: must never silently diverge from the committed record they restate.
PINNED_SOURCES = (
    "qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md",
    "qualification/phase8/alpha/OPERATIONS.md",
    "qualification/phase8/alpha/RELEASE_SCOPE.md",
    "qualification/phase8/alpha/ALPHA_KNOWN_LIMITATIONS.md",
    "qualification/phase8/alpha/REPORT_TEMPLATE.json",
    "qualification/phase8/hardware-matrix.json",
    "qualification/phase8/hardware/PROTOCOL.md",
)

REPORT_TYPES = (
    "SUCCESS", "FAILURE", "BUG", "PERFORMANCE", "COMPATIBILITY",
    "USABILITY", "ACCESSIBILITY", "SECURITY_OBSERVATION", "GENERAL_FEEDBACK",
)

#: Report types that describe an issue: with an empty findings[] they still
#: derive one finding row, categorized through this committed map with
#: classificationSource DERIVED — the tester is never forced to classify,
#: and the tester's own words ride along verbatim.
REPORT_TYPE_CATEGORY = {
    "FAILURE": "FUNCTIONAL", "BUG": "FUNCTIONAL",
    "PERFORMANCE": "PERFORMANCE", "COMPATIBILITY": "HARDWARE",
    "USABILITY": "UX", "ACCESSIBILITY": "ACCESSIBILITY",
    "SECURITY_OBSERVATION": "SECURITY",
}

IDENTITY_STATES = ("VERIFIED", "OBSERVED_UNVERIFIED", "MISSING", "MISMATCH")

EVIDENCE_CLASSES = ("USER_REPORTED", "MEASURED", "REPRODUCED", "DERIVED")

#: §23 intake classifications, derived over Phase 9 entries. QUARANTINED is
#: a REJECTED entry whose refusal was credential hygiene (nothing ingested;
#: the decision is the record); USER_EVIDENCE_UNBOUND is ACCEPTED without
#: artifact binding. The Phase 9 stored vocabulary itself is unchanged.
INTAKE_CLASSIFICATIONS = (
    "ACCEPTED", "INCOMPLETE", "USER_EVIDENCE_UNBOUND", "REJECTED",
    "QUARANTINED", "ARTIFACT_MISMATCH", "UNVERIFIABLE", "SUPERSEDED",
)

DEDUP_RELATIONSHIPS = ("DISTINCT", "POSSIBLE_DUPLICATE", "DUPLICATE_OF",
                       "RELATED")
DEDUP_DECISION_FIELDS = ("findingA", "findingB", "relationship",
                         "rationale", "decidedBy", "date")

REPRODUCTION_STATES = (
    "NOT_ATTEMPTED", "REPRODUCTION_QUEUED", "REPRODUCED", "NOT_REPRODUCED",
    "INSUFFICIENT_INFORMATION", "ENVIRONMENT_DEPENDENT",
)
ATTEMPT_RESULTS = ("REPRODUCED", "NOT_REPRODUCED",
                   "INSUFFICIENT_INFORMATION", "ENVIRONMENT_DEPENDENT")
ATTEMPT_FIELDS = ("attemptId", "sourceReport", "artifactTested",
                  "environment", "hypothesis", "method", "result", "date",
                  "operator")

#: Precedence when several same-artifact attempts exist: the strongest
#: positive knowledge wins, and NOT_REPRODUCED outranks only
#: INSUFFICIENT_INFORMATION — it is a statement about attempts, never
#: about validity.
_RESULT_PRECEDENCE = ("REPRODUCED", "ENVIRONMENT_DEPENDENT",
                      "NOT_REPRODUCED", "INSUFFICIENT_INFORMATION")

HARDWARE_CLASSES = ("HARDWARE_OBSERVED", "HARDWARE_MEASURED",
                    "HARDWARE_QUALIFIED")

#: The four Companion render modes, exactly as the pinned hardware matrix
#: dimensions spell them. Never merged into one generic "graphics".
RENDER_MODES = ("companion-prerendered", "companion-2d",
                "companion-3d-native", "companion-3d-fallback")

USER_IMPACTS = ("BLOCKS_USE", "MAJOR_DEGRADATION", "MINOR_DEGRADATION",
                "CONFUSING", "COSMETIC", "UNKNOWN")
DERIVED_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL")

PROGRAM_STATES = (
    "NOT_STARTED", "READY_FOR_TESTERS", "EVIDENCE_RECEIVED",
    "TRIAGE_IN_PROGRESS", "REMEDIATION_REQUIRED",
    "REQUALIFICATION_REQUIRED", "ALPHA_EVIDENCE_SUFFICIENT", "BLOCKED",
)

#: Absence is refusal. READY_FOR_TESTERS → ALPHA_EVIDENCE_SUFFICIENT is
#: deliberately not here: sufficiency is reachable only through received,
#: triaged evidence, never through silence.
PROGRAM_TRANSITIONS = {
    "NOT_STARTED": {"READY_FOR_TESTERS"},
    "READY_FOR_TESTERS": {"EVIDENCE_RECEIVED", "BLOCKED"},
    "EVIDENCE_RECEIVED": {"TRIAGE_IN_PROGRESS", "BLOCKED"},
    "TRIAGE_IN_PROGRESS": {"REMEDIATION_REQUIRED",
                           "ALPHA_EVIDENCE_SUFFICIENT",
                           "EVIDENCE_RECEIVED", "BLOCKED"},
    "REMEDIATION_REQUIRED": {"REQUALIFICATION_REQUIRED", "BLOCKED"},
    "REQUALIFICATION_REQUIRED": {"READY_FOR_TESTERS", "BLOCKED"},
    "ALPHA_EVIDENCE_SUFFICIENT": {"EVIDENCE_RECEIVED", "BLOCKED"},
    "BLOCKED": {"READY_FOR_TESTERS", "EVIDENCE_RECEIVED"},
}

SUFFICIENCY_DETERMINATIONS = (
    "SUFFICIENCY_UNDETERMINED", "INSUFFICIENT_EVIDENCE",
    "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS", "SUFFICIENT",
)

#: JSON Schema keywords VERIFY_TESTER_REPORT.py actually enforces; a schema
#: keyword outside this set would be silently unenforced, so verify()
#: refuses a schema that uses one.
ENFORCED_SCHEMA_KEYWORDS = frozenset({
    "type", "required", "enum", "const", "pattern", "minLength",
    "properties", "items",
})
DESCRIPTIVE_SCHEMA_KEYWORDS = frozenset({
    "$schema", "$id", "title", "description", "x-aliases",
})


class BoundaryViolation(ValueError):
    """A refused transition, decision, derivation, or record."""


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
    return _load_module("phase12_verify_report", VERIFIER_PATH)


def _phase9():
    return _load_module("phase9_intake_for_phase12", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase12", PHASE10_TOOL)


def is_fixture(record) -> bool:
    return isinstance(record, dict) and record.get(
        "fixtureClass") == FIXTURE_MARKER


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- pins (§3)

def build_pins() -> dict:
    """PHASE8_PINS.json: the reused Phase 7/8 sources, by content."""
    pins = {}
    for name in PINNED_SOURCES:
        raw = (ROOT / name).read_bytes()
        pins[name] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return {
        "schemaVersion": 1,
        "purpose": "The Phase 7/8 sources the Phase 12 tester package "
                   "reuses and restates, pinned by content. If a pinned "
                   "source changes, derivation refuses instead of letting "
                   "the tester-facing restatement silently diverge from "
                   "the record it restates — updating a restatement is a "
                   "deliberate act that re-pins here.",
        "pinnedSources": pins,
    }


def pins_problems() -> list[str]:
    if not PINS_PATH.is_file():
        return ["PHASE8_PINS.json is absent; run build-pins"]
    committed = load_json(PINS_PATH)
    rebuilt = build_pins()
    problems = []
    for name, expected in committed.get("pinnedSources", {}).items():
        actual = rebuilt["pinnedSources"].get(name)
        if actual is None:
            problems.append("pinned source %s no longer exists" % name)
        elif actual != expected:
            problems.append(
                "pinned source %s changed under the Phase 12 package; the "
                "tester-facing restatement may now diverge from the record "
                "— review and re-pin deliberately" % name)
    if set(rebuilt["pinnedSources"]) - set(committed.get("pinnedSources", {})):
        problems.append("PHASE8_PINS.json does not cover every declared "
                        "pinned source; run build-pins")
    return problems


# ------------------------------------------------------------ reports (§5–7)

def validate_report(record) -> list[str]:
    """The tester-report contract, enforced from the committed schema."""
    verifier = _verifier()
    return verifier.validate_report(
        record, verifier.load_schema(SCHEMA_PATH),
        verifier.load_identity(IDENTITY_PATH))


def intake_classification(entry: dict) -> str:
    """The §23 derived classification of one Phase 9 entry."""
    status = entry.get("effectiveStatus") or entry.get("status")
    if status == "REJECTED" and "credential material" in (
            entry.get("statusReason") or ""):
        return "QUARANTINED"
    if status == "ACCEPTED" and entry.get("binding") == "USER_EVIDENCE_UNBOUND":
        return "USER_EVIDENCE_UNBOUND"
    if status in INTAKE_CLASSIFICATIONS:
        return status
    raise BoundaryViolation("entry %s has unclassifiable status %r"
                            % (entry.get("intakeId"), status))


# ------------------------------------------------------------ dedup (§12)

def validate_dedup_decision(decision: dict) -> list[str]:
    issues = [
        "decision missing %s" % field
        for field in DEDUP_DECISION_FIELDS if not decision.get(field)
    ]
    relationship = decision.get("relationship")
    if relationship and relationship not in DEDUP_RELATIONSHIPS:
        issues.append("relationship %r is not in the vocabulary"
                      % relationship)
    if decision.get("findingA") and \
            decision.get("findingA") == decision.get("findingB"):
        issues.append("a finding cannot be deduplicated against itself")
    return issues


def effective_dedup(decisions: list[dict]) -> dict[tuple[str, str], dict]:
    """Last decision per unordered pair wins; every decision validated.

    Reversibility is this function: a later decision about the same pair
    supersedes the earlier one, and both stay in the committed list.
    """
    effective: dict[tuple[str, str], dict] = {}
    for decision in decisions:
        issues = validate_dedup_decision(decision)
        if issues:
            raise BoundaryViolation(
                "dedup decision invalid: %s — a relationship without its "
                "rationale, decider, and date is an automatic merge in "
                "disguise" % "; ".join(issues))
        pair = tuple(sorted((decision["findingA"], decision["findingB"])))
        effective[pair] = decision
    return effective


# ------------------------------------------------------ reproduction (§13/14)

def validate_reproduction_attempt(attempt: dict) -> list[str]:
    issues = [
        "attempt missing %s" % field
        for field in ATTEMPT_FIELDS if not attempt.get(field)
    ]
    result = attempt.get("result")
    if result and result not in ATTEMPT_RESULTS:
        issues.append("result %r is not in the vocabulary (an attempt "
                      "records what happened; NOT_ATTEMPTED and "
                      "REPRODUCTION_QUEUED are derived states, never "
                      "recorded results)" % result)
    return issues


def _attempt_moves_finding(attempt: dict, finding_artifact: str,
                           graph: dict) -> bool:
    """Whether one attempt moves one finding's reproducibility.

    Same artifact: yes. Different artifact: only through an explicitly
    recorded transfer decision riding on a recorded graph relationship —
    a reproduction on a successor proves nothing about the subject by
    default (§14).
    """
    tested = attempt.get("artifactTested")
    if tested == finding_artifact:
        return True
    ops10 = _phase10()
    for decision in graph.get("transferDecisions", []):
        if (decision.get("fromArtifact") == tested
                and decision.get("toArtifact") == finding_artifact
                and decision.get("evidenceScope") in ("reproduction",
                                                      "alpha-feedback")
                and all(decision.get(f) for f in ("reasoning", "decidedBy",
                                                  "date"))
                and decision.get("result") in ("APPLIES", "PARTIALLY_APPLIES")
                and ops10._related(graph, tested, finding_artifact)):
            return True
    return False


def reproducibility_for(finding: dict, attempts: list[dict],
                        graph: dict) -> tuple[str, list[dict]]:
    """(status, otherArtifactAttempts) for one finding.

    Only attempts naming one of the finding's source reports count at
    all; of those, only artifact-applicable ones move the status. The
    rest are preserved beside the finding without moving it.
    """
    relevant = [a for a in attempts
                if a.get("sourceReport") in finding.get("source_report_ids", [])]
    moving, other = [], []
    for attempt in relevant:
        if finding.get("artifact") and _attempt_moves_finding(
                attempt, finding["artifact"], graph):
            moving.append(attempt)
        else:
            other.append({
                "attemptId": attempt.get("attemptId"),
                "artifactTested": attempt.get("artifactTested"),
                "result": attempt.get("result"),
                "note": "does not move this finding: no recorded "
                        "applicability relationship to %s"
                        % finding.get("artifact"),
            })
    if not moving:
        return "NOT_ATTEMPTED", other
    for result in _RESULT_PRECEDENCE:
        if any(a.get("result") == result for a in moving):
            return result, other
    return "NOT_ATTEMPTED", other


# ------------------------------------------------------- sufficiency (§25)

def evaluate_sufficiency(policy: dict, bound_reports: int,
                         accepted_reports: int,
                         open_blockers: list[str]) -> dict:
    """One determination, fail-closed, never a guess.

    Any owner-undefined (null) threshold forces
    SUFFICIENCY_UNDETERMINED; the evidence level is reported beside it so
    "no evidence" and "insufficient evidence" stay distinguishable.
    """
    thresholds = policy.get("thresholds", {})
    undefined = sorted(name for name, value in thresholds.items()
                       if value is None)
    evidence_level = "NO_EVIDENCE" if accepted_reports == 0 \
        else "EVIDENCE_PRESENT"
    if undefined:
        return {
            "determination": "SUFFICIENCY_UNDETERMINED",
            "evidenceLevel": evidence_level,
            "basis": "owner-undefined threshold(s): %s — nothing is "
                     "guessed in their place" % ", ".join(undefined),
            "openBlockers": sorted(open_blockers),
        }
    if bound_reports < thresholds.get("minimumBoundReports", 0):
        return {
            "determination": "INSUFFICIENT_EVIDENCE",
            "evidenceLevel": evidence_level,
            "basis": "%d bound report(s) against a minimum of %d"
                     % (bound_reports, thresholds["minimumBoundReports"]),
            "openBlockers": sorted(open_blockers),
        }
    if open_blockers:
        return {
            "determination": "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS",
            "evidenceLevel": evidence_level,
            "basis": "coverage thresholds met but blocker(s) remain open: "
                     "%s" % ", ".join(sorted(open_blockers)),
            "openBlockers": sorted(open_blockers),
        }
    return {
        "determination": "SUFFICIENT",
        "evidenceLevel": evidence_level,
        "basis": "every owner-defined threshold met with no open blockers",
        "openBlockers": [],
    }


# -------------------------------------------------- program machine (§24)

def program_transition(current: str, target: str,
                       context: dict | None = None) -> str:
    """Advance the program state; refusal is the default, and silence
    satisfies no guard."""
    if current not in PROGRAM_STATES:
        raise BoundaryViolation("unknown program state %r" % current)
    if target not in PROGRAM_STATES:
        raise BoundaryViolation("unknown program state %r" % target)
    if target not in PROGRAM_TRANSITIONS[current]:
        raise BoundaryViolation(
            "program transition %s -> %s is not allowed; the allowed set "
            "from %s is {%s}"
            % (current, target, current,
               ", ".join(sorted(PROGRAM_TRANSITIONS[current])) or "nothing"))
    context = context or {}
    if target == "READY_FOR_TESTERS" and current == "NOT_STARTED" \
            and not context.get("packageComplete"):
        raise BoundaryViolation(
            "READY_FOR_TESTERS requires the complete canonical package")
    if target == "EVIDENCE_RECEIVED" and not context.get("acceptedReports"):
        raise BoundaryViolation(
            "EVIDENCE_RECEIVED requires at least one accepted tester "
            "report; silence never advances the state")
    if target == "TRIAGE_IN_PROGRESS" and not context.get("acceptedReports"):
        raise BoundaryViolation(
            "TRIAGE_IN_PROGRESS requires accepted evidence to triage")
    if target == "REMEDIATION_REQUIRED" and not context.get("findingRequiringFix"):
        raise BoundaryViolation(
            "REMEDIATION_REQUIRED requires the finding that requires it")
    if target == "REQUALIFICATION_REQUIRED" and not context.get("successorArtifact"):
        raise BoundaryViolation(
            "REQUALIFICATION_REQUIRED requires the successor artifact "
            "that needs requalifying")
    if target == "ALPHA_EVIDENCE_SUFFICIENT":
        sufficiency = context.get("sufficiency") or {}
        if sufficiency.get("determination") != "SUFFICIENT":
            raise BoundaryViolation(
                "ALPHA_EVIDENCE_SUFFICIENT requires a SUFFICIENT "
                "determination under the committed policy; %r does not "
                "qualify and is never rounded up"
                % sufficiency.get("determination"))
    if target == "BLOCKED" and not context.get("reason"):
        raise BoundaryViolation("BLOCKED requires its recorded reason")
    return target


def derive_program_state(accepted_reports: int, triage_open: int,
                         findings_requiring_fix: list[str]) -> dict:
    """The evidence-supported state, deterministically, fail-closed.

    ALPHA_EVIDENCE_SUFFICIENT, REQUALIFICATION_REQUIRED, and BLOCKED are
    reachable only through guarded transitions with their evidence in
    hand — never through this ladder, which reports the most-advanced
    state the standing evidence supports.
    """
    if findings_requiring_fix:
        return {"state": "REMEDIATION_REQUIRED",
                "basis": "finding(s) %s require a fix; the fix is a new "
                         "artifact with its own qualification boundary"
                         % ", ".join(sorted(findings_requiring_fix))}
    if accepted_reports and triage_open:
        return {"state": "TRIAGE_IN_PROGRESS",
                "basis": "%d accepted report(s) with triage rows open"
                         % accepted_reports}
    if accepted_reports:
        return {"state": "EVIDENCE_RECEIVED",
                "basis": "%d accepted tester report(s) await triage"
                         % accepted_reports}
    return {"state": "READY_FOR_TESTERS",
            "basis": "the canonical package is committed and zero tester "
                     "reports exist; zero is recorded as zero, and "
                     "silence advances nothing"}


# --------------------------------------------------- register derivation

def _alpha_entries(ledger: dict) -> list[dict]:
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    entries = []
    for entry in ledger.get("entries", []):
        if is_fixture(entry):
            raise BoundaryViolation(
                "ledger entry %s carries the fixture marker; fixtures "
                "never enter the intake ledger" % entry.get("intakeId"))
        if entry.get("source") != "alpha-feedback":
            continue
        annotated = dict(entry)
        annotated["effectiveStatus"] = effective[entry["intakeId"]]
        entries.append(annotated)
    return entries


def _verbatim(record: dict) -> dict:
    """The tester's words, copied — the only transformation is selection."""
    return {
        "userObservation": record.get("user_observation"),
        "expectedBehavior": record.get("expected_behavior"),
        "actualBehavior": record.get("actual_behavior"),
    }


def validate_alpha_row(row: dict, finding_states: tuple[str, ...]) -> list[str]:
    """Standing invariants over one derived finding row."""
    issues: list[str] = []
    rid = row.get("finding_id") or "<unnamed>"
    lifecycle = row.get("lifecycle_status")
    if lifecycle not in finding_states:
        issues.append("%s: lifecycle %r is not in the Phase 10 vocabulary"
                      % (rid, lifecycle))
        return issues
    if not row.get("source_report_ids"):
        issues.append("%s: a finding without source reports derives from "
                      "nothing" % rid)
    if row.get("artifact") is None and lifecycle in (
            "CONFIRMED", "FIXED", "REQUALIFIED", "CLOSED"):
        issues.append(
            "%s: unbound user evidence cannot reach artifact-specific "
            "state %s — a later revision may bind it first" % (rid, lifecycle))
    if row.get("user_impact") not in USER_IMPACTS:
        issues.append("%s: user impact %r is not in the vocabulary"
                      % (rid, row.get("user_impact")))
    severity = row.get("derived_severity")
    if severity is not None and severity not in DERIVED_SEVERITIES:
        issues.append("%s: derived severity %r is not in the vocabulary"
                      % (rid, severity))
    if lifecycle == "CLOSED":
        closure = row.get("closure_evidence") or {}
        required = row.get("remediation_artifact") or row.get("artifact")
        if not closure.get("reference") or not closure.get("artifact"):
            issues.append("%s: CLOSED without closure evidence — a failed "
                          "reproduction or a code change closes nothing"
                          % rid)
        elif closure["artifact"] != required:
            issues.append(
                "%s: closure evidence binds to %s, not %s — qualification "
                "belongs to the artifact that was actually tested"
                % (rid, closure["artifact"], required))
    if row.get("reproducibility_status") not in REPRODUCTION_STATES:
        issues.append("%s: reproducibility %r is not in the vocabulary"
                      % (rid, row.get("reproducibility_status")))
    return issues


def derive_register(ledger: dict, graph: dict, dedup: dict, repro: dict,
                    policy: dict, intake_root: Path,
                    triage: dict | None = None) -> dict:
    """qualification/phase12/alpha-findings.json, reproducibly.

    Inputs: the Phase 9 ledger (read, never written), the artifact graph,
    the recorded dedup decisions, the recorded reproduction attempts, and
    the committed sufficiency policy. With zero accepted evidence this is
    an empty register around a READY_FOR_TESTERS program state — zero
    recorded as zero, never as favorable silence.
    """
    ops10 = _phase10()
    graph_issues = ops10.validate_graph(graph)
    if graph_issues:
        raise BoundaryViolation("artifact graph invalid: %s"
                                % "; ".join(graph_issues))
    candidate = ops10._active_candidate(graph)
    ledger_subject = ledger["subjectArtifact"]["identifier"]
    if candidate["artifact_id"] != ledger_subject:
        raise BoundaryViolation(
            "the active candidate %s is not the intake subject %s; a "
            "successor artifact runs its own Alpha program — tester "
            "evidence does not transfer" % (candidate["artifact_id"],
                                            ledger_subject))
    subject = ledger_subject

    attempts = list(repro.get("attempts", []))
    for attempt in attempts:
        issues = validate_reproduction_attempt(attempt)
        if issues:
            raise BoundaryViolation("reproduction attempt invalid: %s"
                                    % "; ".join(issues))
    decisions = effective_dedup(list(dedup.get("decisions", [])))

    reports = []
    findings: list[dict] = []
    success_evidence, unbound_evidence = [], []
    security_observations, accessibility_observations = [], []
    hardware_observations = []
    performance = {"subjective": [], "testerMeasurements": [],
                   "projectMeasured": []}
    accepted = bound = 0

    for entry in _alpha_entries(ledger):
        intake_id = entry["intakeId"]
        classification = intake_classification(entry)
        row = {
            "intakeId": intake_id,
            "classification": classification,
            "binding": entry.get("binding"),
            "contractProblems": [],
        }
        if classification in ("ACCEPTED", "USER_EVIDENCE_UNBOUND"):
            record_path = (intake_root / "alpha-feedback" / intake_id
                           / "record.json")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            problems = validate_report(record)
            row["contractProblems"] = problems
            row["testerId"] = record.get("testerId") or record.get("tester_id")
            row["reportType"] = record.get("report_type")
            row["journey"] = record.get("journey")
            row["identityStatus"] = record.get("artifact_identity_status")
            accepted += 1
            is_bound = entry.get("binding") == "BOUND"
            if is_bound:
                bound += 1
            if problems:
                row["note"] = ("accepted by the intake but outside the "
                               "Phase 12 contract; preserved, derives no "
                               "rows until revised")
                reports.append(row)
                continue
            artifact = subject if is_bound else None
            words = _verbatim(record)
            report_type = record.get("report_type")

            hardware_observations.append({
                "source": intake_id,
                "class": "HARDWARE_OBSERVED",
                "environment": record.get("environment_summary"),
                "machineLabel": record.get("machine_label"),
                "note": "an observation, not a matrix result: PASS still "
                        "requires the committed hardware protocol",
            })

            if report_type == "SUCCESS":
                success_evidence.append({
                    "source": intake_id,
                    "tester": row["testerId"],
                    "artifact": artifact,
                    "binding": entry.get("binding"),
                    "environment": record.get("environment_summary"),
                    "observation": words["userObservation"],
                    "verificationLevel": row["identityStatus"],
                    "evidenceClass": "USER_REPORTED",
                    "limit": "one successful observed run on one machine; "
                             "never SUPPORTED ON PCS",
                })
            if not is_bound:
                unbound_evidence.append({
                    "source": intake_id,
                    "observation": words["userObservation"],
                    "gateNote": "USER_EVIDENCE_UNBOUND: may identify an "
                                "issue and initiate investigation; moves "
                                "no artifact-specific gate until a "
                                "revision binds it",
                })
            if report_type == "SECURITY_OBSERVATION":
                security_observations.append({
                    "source": intake_id,
                    "observation": words["userObservation"],
                    "assessment": None,
                    "note": "surfaced to the Phase 11 security workflow; "
                            "tester evidence never impersonates the "
                            "independent review, and NOT_A_SECURITY_ISSUE "
                            "requires a recorded assessment",
                })
            if report_type == "ACCESSIBILITY" or record.get(
                    "accessibility_technology"):
                accessibility_observations.append({
                    "source": intake_id,
                    "technology": record.get("accessibility_technology"),
                    "observation": words["userObservation"],
                    "evidenceClass": "USER_REPORTED",
                })
            if report_type == "PERFORMANCE":
                performance["subjective"].append({
                    "source": intake_id,
                    "observation": words["userObservation"],
                    "evidenceClass": "USER_REPORTED",
                    "note": "initiates investigation; never a regression "
                            "by itself",
                })
            if record.get("performance_measurement"):
                measurement = dict(record["performance_measurement"])
                measurement["source"] = intake_id
                measurement["evidenceClass"] = "USER_REPORTED"
                measurement["note"] = ("tester-provided measurement, "
                                       "preserved in full; MEASURED only "
                                       "when independently validated")
                performance["testerMeasurements"].append(measurement)

            tester_findings = record.get("findings") or []
            derived_rows = []
            for index, item in enumerate(tester_findings, start=1):
                derived_rows.append({
                    "finding_id": "AF-%s-F%d" % (intake_id, index),
                    "category": item.get("category"),
                    "classificationSource": "TESTER",
                    "description": item.get("description"),
                    "reproductionConfidence": item.get("reproductionConfidence"),
                    "technical_evidence": [{
                        "evidenceClass": "USER_REPORTED",
                        "reference": "%s findings[%d]" % (intake_id, index - 1),
                        "detail": item.get("evidence") or "",
                    }],
                })
            if not derived_rows and report_type in REPORT_TYPE_CATEGORY:
                derived_rows.append({
                    "finding_id": "AF-%s-T" % intake_id,
                    "category": REPORT_TYPE_CATEGORY[report_type],
                    "classificationSource": "DERIVED",
                    "description": words["userObservation"],
                    "reproductionConfidence": "REPORTED",
                    "technical_evidence": [{
                        "evidenceClass": "USER_REPORTED",
                        "reference": intake_id,
                        "detail": "report-level observation; category from "
                                  "the committed report-type map",
                    }],
                })
            for derived in derived_rows:
                derived.update({
                    "source_report_ids": [intake_id],
                    "artifact": artifact,
                    "evidenceBinding": entry.get("binding"),
                    "severity_or_impact": {
                        "derived_severity": None,
                        "user_impact": "UNKNOWN",
                    },
                    "derived_severity": None,
                    "user_impact": "UNKNOWN",
                    "lifecycle_status": "RECEIVED",
                    "lifecycleAuthority": "qualification/phase10/tools/"
                                          "candidate_ops.py "
                                          "FINDING_TRANSITIONS",
                    "triageId": None,
                    "remediation_artifact": None,
                    "closure_evidence": None,
                    "relationship": {"kind": "DISTINCT",
                                     "basis": "no recorded decision"},
                    **words,
                })
                findings.append(derived)
        else:
            reports.append(row)
            continue
        reports.append(row)

    # Recorded dedup decisions, applied — never invented.
    by_id = {f["finding_id"]: f for f in findings}
    for pair, decision in decisions.items():
        missing = [fid for fid in pair if fid not in by_id]
        if missing:
            raise BoundaryViolation(
                "dedup decision names unknown finding(s) %s; decisions "
                "bind to derived findings, and a dangling decision fails "
                "closed" % ", ".join(missing))
        for fid, other in (pair, pair[::-1]):
            by_id[fid]["relationship"] = {
                "kind": decision["relationship"],
                "with": other,
                "rationale": decision["rationale"],
                "decidedBy": decision["decidedBy"],
                "date": decision["date"],
                "reversible": "a later recorded decision supersedes this "
                              "one; no report is deleted",
            }

    triage_rows = (triage or {}).get("findings", [])
    finding_states = tuple(_phase10().FINDING_STATES)
    for finding in findings:
        status, other = reproducibility_for(finding, attempts, graph)
        finding["reproducibility_status"] = status
        if other:
            finding["otherArtifactAttempts"] = other
        for row in triage_rows:
            if row.get("intakeId") in finding["source_report_ids"] \
                    and row.get("findingId"):
                finding["triageId"] = row["findingId"]

    invariant_issues = [
        issue for finding in findings
        for issue in validate_alpha_row(finding, finding_states)
    ]
    if invariant_issues:
        raise BoundaryViolation("register invariants violated: %s"
                                % "; ".join(invariant_issues))

    fix_required = sorted(
        f["finding_id"] for f in findings
        if f.get("lifecycle_status") == "FIX_REQUIRED")
    open_blockers = sorted(
        f["finding_id"] for f in findings
        if f.get("category") == "RELEASE_BLOCKER"
        and f.get("lifecycle_status") != "CLOSED") + fix_required
    program = derive_program_state(accepted, len(triage_rows), fix_required)
    sufficiency = evaluate_sufficiency(policy, bound, accepted,
                                       open_blockers)

    counts = {
        "alphaIntakes": len(reports),
        "acceptedReports": accepted,
        "boundReports": bound,
        "unboundReports": len(unbound_evidence),
        "quarantined": sum(1 for r in reports
                           if r["classification"] == "QUARANTINED"),
        "rejected": sum(1 for r in reports
                        if r["classification"] == "REJECTED"),
        "findings": len(findings),
        "successReports": len(success_evidence),
        "reproductionAttempts": len(attempts),
        "dedupDecisions": len(dedup.get("decisions", [])),
    }

    return {
        "schemaVersion": 1,
        "subjectArtifact": subject,
        "program": program,
        "sufficiency": sufficiency,
        "counts": counts,
        "vocabularies": {
            "reportTypes": list(REPORT_TYPES),
            "identityStates": list(IDENTITY_STATES),
            "evidenceClasses": list(EVIDENCE_CLASSES),
            "intakeClassifications": list(INTAKE_CLASSIFICATIONS),
            "dedupRelationships": list(DEDUP_RELATIONSHIPS),
            "reproductionStates": list(REPRODUCTION_STATES),
            "hardwareClasses": list(HARDWARE_CLASSES),
            "renderModes": list(RENDER_MODES),
            "userImpacts": list(USER_IMPACTS),
            "derivedSeverities": list(DERIVED_SEVERITIES),
            "programStates": list(PROGRAM_STATES),
            "lifecycleAuthority": "qualification/phase10/tools/"
                                  "candidate_ops.py FINDING_TRANSITIONS",
        },
        "reports": reports,
        "findings": findings,
        "successEvidence": success_evidence,
        "unboundEvidence": unbound_evidence,
        "securityObservations": security_observations,
        "hardwareObservations": hardware_observations,
        "performance": performance,
        "accessibilityObservations": accessibility_observations,
        "derivedFrom": {
            "intakeLedger": "qualification/phase9/intake/LEDGER.json "
                            "(read-only)",
            "artifactGraph": "qualification/phase10/artifacts/"
                             "artifact-graph.json",
            "dedupDecisions": "qualification/phase12/dedup-decisions.json",
            "reproductions": "qualification/phase12/reproductions.json",
            "sufficiencyPolicy": "qualification/phase12/"
                                 "sufficiency-policy.json",
            "triageRegistry": "qualification/phase9/triage/findings.json",
            "note": "derived, not primary evidence: recomputable from "
                    "these inputs on every run; tested by tests/release/"
                    "test_phase12_alpha_operations.py",
        },
        "note": "Zero tester reports derive an empty register and "
                "READY_FOR_TESTERS — never SUCCESS, COMPATIBILITY PASS, "
                "ALPHA READY, or USER APPROVED. Silence is not evidence.",
    }


def sync_register(write: bool = True) -> tuple[dict, list[str]]:
    """Recompute alpha-findings.json from its inputs; refuse drift."""
    problems = pins_problems()
    if problems:
        return {}, problems
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    derived = derive_register(
        json.loads(ledger_bytes.decode("utf-8")),
        load_json(PHASE10_GRAPH), load_json(DEDUP_PATH),
        load_json(REPRO_PATH), load_json(POLICY_PATH),
        PHASE9_LEDGER.parent,
        load_json(PHASE9_TRIAGE) if PHASE9_TRIAGE.is_file() else None,
    )
    if PHASE9_LEDGER.read_bytes() != ledger_bytes:
        return derived, ["the Phase 9 ledger changed underfoot; refusing"]
    if write:
        dump_json(REGISTER_PATH, derived)
    return derived, []


# ---------------------------------------------------------------- verify

def _schema_problems() -> list[str]:
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
                        "VERIFY_TESTER_REPORT.py; an unenforced constraint "
                        "is a fiction" % (where, key))
                    continue
                if key == "properties":
                    for name, sub in value.items():
                        walk(sub, "%s.%s" % (where, name))
                elif key == "items":
                    walk(value, "%s[]" % where)

    schema = load_json(SCHEMA_PATH)
    walk(schema, "schema")
    required = set(schema.get("required", []))
    for alias, canonical in schema.get("x-aliases", []):
        if canonical not in required:
            problems.append(
                "alias pair (%s, %s): the canonical field must be "
                "required" % (alias, canonical))
        if alias != "artifactDigest" and alias not in required:
            problems.append(
                "alias pair (%s, %s): the intake spelling must be "
                "required (artifactDigest alone is conditional on an "
                "observed digest)" % (alias, canonical))
    return problems


def _identity_problems() -> list[str]:
    identity = load_json(IDENTITY_PATH)["subjectArtifact"]
    ledger = load_json(PHASE9_LEDGER)["subjectArtifact"]
    problems = []
    for key in ("identifier", "imageDigest", "isoSha256", "qcow2Sha256",
                "ociTarSha256", "rawSha256", "sourceCommit", "signingStatus"):
        if identity.get(key) != ledger.get(key):
            problems.append(
                "ARTIFACT_IDENTITY.json %s disagrees with the intake "
                "ledger's subject artifact; a tester must not be handed "
                "an identity the boundary will refuse" % key)
    return problems


def _secret_pattern_problems() -> list[str]:
    intake = _phase9()
    verifier = _verifier()
    if tuple(intake.SECRET_CLASS_PATTERNS) != tuple(
            verifier.SECRET_CLASS_PATTERNS):
        return ["the courtesy secret scan in VERIFY_TESTER_REPORT.py has "
                "drifted from the intake boundary's SECRET_CLASS_PATTERNS; "
                "the two tables must be identical"]
    return []


def verify_fixtures() -> list[str]:
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
    for name in ("ARTIFACT_IDENTITY.json", "TESTER_REPORT_SCHEMA.json",
                 "PHASE8_PINS.json"):
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
            issues.append("package: %s is missing from the canonical "
                          "package" % name)
    if not issues:
        issues += ["pins: %s" % p for p in pins_problems()]
        issues += ["schema: %s" % p for p in _schema_problems()]
        issues += ["identity: %s" % p for p in _identity_problems()]
        issues += ["secrets: %s" % p for p in _secret_pattern_problems()]
    issues += ["fixtures: %s" % p for p in verify_fixtures()]
    for decision in load_json(DEDUP_PATH).get("decisions", []):
        issues += ["dedup: %s" % p for p in validate_dedup_decision(decision)]
    for attempt in load_json(REPRO_PATH).get("attempts", []):
        issues += ["reproduction: %s" % p
                   for p in validate_reproduction_attempt(attempt)]
    if not issues:
        derived, problems = sync_register(write=False)
        issues += ["register: %s" % p for p in problems]
        if not problems:
            if REGISTER_PATH.is_file():
                if load_json(REGISTER_PATH) != derived:
                    issues.append(
                        "register: committed alpha-findings.json does not "
                        "reproduce from its inputs; run sync and review "
                        "the diff")
            else:
                issues.append("register: alpha-findings.json is absent; "
                              "run sync")
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 12 alpha operations verify clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_build_pins(_args) -> int:
    dump_json(PINS_PATH, build_pins())
    print("pinned %d Phase 7/8 sources" % len(PINNED_SOURCES))
    return 0


def _cmd_sync(_args) -> int:
    derived, problems = sync_register(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("alpha-findings.json derived; %d report(s), %d finding(s); "
          "program %s; sufficiency %s"
          % (derived["counts"]["alphaIntakes"],
             derived["counts"]["findings"],
             derived["program"]["state"],
             derived["sufficiency"]["determination"]))
    return 0


def _cmd_validate_report(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    problems = validate_report(record)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("report satisfies the contract (validation is not acceptance; "
          "the Phase 9 intake is the only door)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser(
        "verify", help="package, pins, schema, identity, register "
                       "reproducibility; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    pins = commands.add_parser(
        "build-pins", help="pin the reused Phase 7/8 sources by sha256")
    pins.set_defaults(func=_cmd_build_pins)

    sync = commands.add_parser(
        "sync", help="derive alpha-findings.json from its inputs")
    sync.set_defaults(func=_cmd_sync)

    val = commands.add_parser(
        "validate-report", help="check one tester report against the "
                                "contract")
    val.add_argument("record")
    val.set_defaults(func=_cmd_validate_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

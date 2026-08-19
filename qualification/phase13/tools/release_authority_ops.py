#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 13 release authority, sufficiency thresholds, and decision governance.

Phase 9 built the door evidence enters through; Phases 10-12 built candidate,
security, and Alpha operations behind it. Phase 13 is the last internal layer:
it makes the release decision *governable* without making the decision. The
principle, mechanically enforced everywhere below:

    The repository may evaluate whether authorization requirements are
    satisfied. It may never create the authority that satisfies them.

What this module provides:

* an authority model — seven roles with stable identifiers, where a role
  existing in a JSON file (ROLE_DEFINED) is distinct from a recorded
  assignment (AUTHORITY_ASSIGNED) and both are distinct from evidence that
  the authority acted (AUTHORITY_ACTED);
* separation of duties — incompatible role pairs fail closed on one
  identity, and overlap exists only through a recorded policy decision,
  never through matching strings;
* sufficiency thresholds — an owner-controlled, versioned, sealed policy
  registry that starts SUFFICIENCY_POLICY_UNDEFINED; while no active,
  artifact-applicable policy exists, no quantity of evidence becomes
  SUFFICIENT, and an activated policy is immutable (a change is a new
  version that supersedes, preserving the old policy and old evaluations);
* a blocking-condition registry — the ten Phase 8 conditions imported with
  their source pinned by sha256 and their titles verbatim; reclassification
  away from BLOCKING requires a recorded, sealed decision;
* conflict handling — contradictory external evidence defaults to
  CONFLICT -> REQUIRES_HUMAN_DECISION with the unfavorable assessment
  effective; nothing is averaged, nothing resolves favorably by silence;
* risk acceptance — explicit, scoped, expiring, artifact-bound records
  that never close the underlying finding, never mean NOT_AFFECTED, and
  never transfer to a successor artifact;
* authorization records — bound to exact bytes, expiring by construction
  (a record without an expiry is invalid), revocable but never un-revocable,
  and AUTHORIZED is *checkable* here yet only reachable through accepted
  external evidence crossing the Phase 9 intake plus a recorded, assigned
  release authority; the repository itself derives at most NOT_AUTHORIZED,
  BLOCKED, or REQUIRES_MORE_EVIDENCE;
* a candidate authorization state machine whose most restrictive state wins,
  with every forbidden transition refused by an explicit table.

Everything here reads the Phase 9 ledger, the Phase 10 graph, and the
Phase 11/12 registers; nothing here writes any of them. Derived outputs are
``blocking/blocking-conditions.json`` and ``authorization-status.json``,
recomputable from immutable inputs on every run.

Determinism: no clocks. Expiry is evaluated against an operator-stated
evaluation date (like Phase 9's ``--received-on``), recorded in the derived
output so verification reproduces it; the commit is the tamper-evident time.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE13 = ROOT / "qualification" / "phase13"
GOVERNANCE_DIR = PHASE13 / "governance"
SUFFICIENCY_DIR = PHASE13 / "sufficiency"
BLOCKING_DIR = PHASE13 / "blocking"
DECISIONS_DIR = PHASE13 / "decisions"
FIXTURES_DIR = PHASE13 / "fixtures"
STATUS_PATH = PHASE13 / "authorization-status.json"

AUTHORITIES_PATH = GOVERNANCE_DIR / "authorities.json"
ASSIGNMENTS_PATH = GOVERNANCE_DIR / "assignments.json"
SEPARATION_PATH = GOVERNANCE_DIR / "separation-policy.json"
POLICIES_PATH = SUFFICIENCY_DIR / "threshold-policies.json"
BLOCKING_PATH = BLOCKING_DIR / "blocking-conditions.json"
RECLASSIFICATION_PATH = BLOCKING_DIR / "reclassification-decisions.json"
RISKS_PATH = DECISIONS_DIR / "risk-acceptances.json"
AUTHORIZATIONS_PATH = DECISIONS_DIR / "authorizations.json"
REVOCATIONS_PATH = DECISIONS_DIR / "revocations.json"
RESOLUTIONS_PATH = DECISIONS_DIR / "conflict-resolutions.json"

PHASE8_CONDITIONS = (ROOT / "qualification" / "phase8" / "conditions"
                     / "ALPHA_RELEASE_BLOCKING_CONDITIONS.md")
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE9_DECISION = (ROOT / "qualification" / "phase9" / "decision"
                   / "alpha-release-decision.json")
PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE10_TOOL = (ROOT / "qualification" / "phase10" / "tools"
                / "candidate_ops.py")
PHASE10_GRAPH = (ROOT / "qualification" / "phase10" / "artifacts"
                 / "artifact-graph.json")
PHASE11_REGISTER = ROOT / "qualification" / "phase11" / "security-findings.json"
PHASE12_REGISTER = ROOT / "qualification" / "phase12" / "alpha-findings.json"

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

# ------------------------------------------------------- authority model (§4)

#: The seven authorities, with stable identifiers. No real person is named
#: here: naming one is an assignment record, and an assignment record is
#: still not an authority action.
AUTHORITIES = (
    ("AUTH-SECURITY-REVIEWER", "SECURITY_REVIEWER",
     "Produces independent review evidence"),
    ("AUTH-SECURITY-OWNER", "SECURITY_OWNER",
     "Resolves security disposition and accepted risk"),
    ("AUTH-ALPHA-PROGRAM", "ALPHA_PROGRAM_OWNER",
     "Defines Alpha sufficiency thresholds"),
    ("AUTH-RELEASE", "RELEASE_AUTHORITY",
     "Makes final artifact authorization decision"),
    ("AUTH-KEY", "KEY_AUTHORITY", "Controls production signing"),
    ("AUTH-SECOND-APPROVER", "SECOND_APPROVER",
     "Independently verifies and approves"),
    ("AUTH-HARDWARE", "HARDWARE_VALIDATION_OWNER",
     "Owns interpretation of physical hardware evidence"),
)
AUTHORITY_IDS = tuple(a[0] for a in AUTHORITIES)
ROLE_BY_AUTHORITY = {a[0]: a[1] for a in AUTHORITIES}
AUTHORITY_BY_ROLE = {a[1]: a[0] for a in AUTHORITIES}

AUTHORITY_LEVELS = ("ROLE_DEFINED", "AUTHORITY_ASSIGNED", "AUTHORITY_ACTED")

#: Incompatible role pairs (§3): one identity may not silently occupy both
#: sides of any pair. Overlap exists only through a recorded policy decision
#: in separation-policy.json naming the identity and both roles.
INCOMPATIBLE_ROLES = (
    ("AUTH-SECURITY-REVIEWER", "AUTH-SECURITY-OWNER"),
    ("AUTH-SECURITY-REVIEWER", "AUTH-RELEASE"),
    ("AUTH-SECURITY-OWNER", "AUTH-RELEASE"),
    ("AUTH-ALPHA-PROGRAM", "AUTH-RELEASE"),
    ("AUTH-RELEASE", "AUTH-KEY"),
    ("AUTH-RELEASE", "AUTH-SECOND-APPROVER"),
    ("AUTH-KEY", "AUTH-SECOND-APPROVER"),
)

ASSIGNMENT_FIELDS = ("assignmentId", "authorityId", "identity", "assignedBy",
                     "date", "basis")
OVERLAP_DECISION_FIELDS = ("decisionId", "identity", "roles", "reason",
                           "authority", "date")

#: Which intake source is, by itself, evidence that an authority ACTED. The
#: decision-making authorities are absent deliberately: their acts are
#: recorded Phase 13 decisions, which validate only against an assignment.
ACTED_BY_INTAKE_SOURCE = {
    "AUTH-SECURITY-REVIEWER": "security-review",
    "AUTH-KEY": "signing",
    "AUTH-SECOND-APPROVER": "second-approval",
    "AUTH-HARDWARE": "hardware",
}

# ------------------------------------------------ sufficiency thresholds (§5)

#: The threshold dimensions an Alpha sufficiency policy must define, every
#: one explicitly. No production value is invented anywhere in this module:
#: the registry starts with zero policies (SUFFICIENCY_POLICY_UNDEFINED) and
#: only its owner's recorded, sealed policy can change that.
THRESHOLD_DIMENSIONS = (
    "minimumAcceptedTesterReports",
    "minimumDistinctTesters",
    "minimumDistinctMachineIdentities",
    "minimumSuccessfulInstallationReports",
    "minimumCompletedCoreJourneys",
    "minimumEvidencePeriodDays",
    "maximumUnresolvedBlockerFindings",
    "maximumUnresolvedCriticalFindings",
    "performanceEvidenceRequired",
    "accessibilityEvidenceRequired",
    "minimumDistinctHardwareMachines",
)
_MAXIMUM_DIMENSIONS = ("maximumUnresolvedBlockerFindings",
                       "maximumUnresolvedCriticalFindings")
_BOOLEAN_DIMENSIONS = ("performanceEvidenceRequired",
                       "accessibilityEvidenceRequired")

POLICY_FIELDS = ("policy_id", "artifact_digest", "thresholds", "effective_at",
                 "authority", "status", "supersedes")
POLICY_STATUSES = ("PROPOSED", "ACTIVE")
POLICY_LIFECYCLE = (
    "SUFFICIENCY_POLICY_UNDEFINED", "SUFFICIENCY_POLICY_PROPOSED",
    "SUFFICIENCY_POLICY_ACTIVE",
)

#: Aligned with the Phase 12 vocabulary; nothing new is invented here.
SUFFICIENCY_DETERMINATIONS = (
    "SUFFICIENCY_UNDETERMINED", "INSUFFICIENT_EVIDENCE",
    "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS", "SUFFICIENT",
)

# ------------------------------------------------- blocking conditions (§8)

BLOCKING_CLASSES = ("BLOCKING", "NON_BLOCKING", "REQUIRES_HUMAN_DECISION",
                    "NOT_APPLICABLE")

#: How a TRUE condition earned its truth, derived from the evidence actually
#: held. A condition true because evidence is absent keeps the candidate
#: pending; a condition true on adverse evidence blocks it. Neither
#: authorizes anything.
CONDITION_CHARACTERS = ("CLEARED", "UNDETERMINED", "ABSENCE_OF_EVIDENCE",
                        "ADVERSE_EVIDENCE")

#: Which intake source answers whether a TRUE condition is true on absence
#: or on evidence. Condition 6 derives from the artifact identity itself.
CONDITION_EVIDENCE_SOURCE = {
    1: "security-review", 2: "security-review", 3: "alpha-feedback",
    4: "alpha-feedback", 5: "alpha-feedback", 6: None, 7: "signing",
    8: "second-approval", 9: "hardware", 10: "alpha-feedback",
}

RECLASSIFICATION_FIELDS = ("decisionId", "condition", "fromClass", "toClass",
                           "reason", "authority", "artifact", "timestamp",
                           "policyBasis", "evidenceReferences")

# --------------------------------------------------------- conflicts (§9)

#: Which authority a conflict in each evidence domain escalates to.
CONFLICT_DOMAIN_AUTHORITY = {
    "security": "AUTH-SECURITY-OWNER",
    "hardware": "AUTH-HARDWARE",
    "alpha": "AUTH-ALPHA-PROGRAM",
    "release": "AUTH-RELEASE",
}
RESOLUTION_FIELDS = ("resolutionId", "domain", "evidenceReferences",
                     "resolvedAssessment", "reason", "authority", "date")

# ----------------------------------------------------- risk acceptance (§10)

RISK_FIELDS = ("risk_id", "artifact_digest", "finding_ids", "scope",
               "reason", "authority", "evidence", "accepted_at",
               "expires_at", "revocation_conditions")

# ------------------------------------------------------ authorization (§11)

AUTHORIZATION_FIELDS = (
    "authorization_id", "artifact_digest", "artifact_identity", "decision",
    "authority", "authority_role", "decision_timestamp", "evidence_cut",
    "security_status", "alpha_status", "hardware_status", "signing_status",
    "second_approval_status", "blocking_conditions", "accepted_risks",
    "policy_versions", "issued_at", "expires_at",
)
#: Fields that may legitimately be empty lists; presence of the key is what
#: is required.
_AUTHORIZATION_LIST_FIELDS = ("blocking_conditions", "accepted_risks",
                              "policy_versions")

AUTHORIZATION_DECISIONS = ("AUTHORIZED", "NOT_AUTHORIZED", "BLOCKED",
                           "REQUIRES_MORE_EVIDENCE", "REVOKED", "EXPIRED")
#: The repository may derive these three. AUTHORIZED, REVOKED, and EXPIRED
#: describe (the effect of) recorded external authority actions.
DERIVABLE_DECISIONS = ("NOT_AUTHORIZED", "BLOCKED", "REQUIRES_MORE_EVIDENCE")

#: What AUTHORIZED minimally requires from the Phase 9 ledger: a
#: gate-eligible ACCEPTED intake in every external gate's source. This
#: extends the Phase 9 floor (three sources) to all five for the release
#: decision itself.
AUTHORIZATION_FLOOR_SOURCES = ("security-review", "hardware", "signing",
                               "second-approval", "alpha-feedback")

EVIDENCE_CUT_FIELDS = ("ledgerSha256", "ledgerEntries", "intakeIds")

REVOCATION_FIELDS = ("revocation_id", "target_authorization",
                     "artifact_digest", "reason", "authority", "timestamp",
                     "evidence")

# ------------------------------------------------------ state machine (§17)

AUTHORIZATION_STATES = (
    "EVIDENCE_PENDING", "SECURITY_REVIEW_PENDING", "ALPHA_EVIDENCE_PENDING",
    "SUFFICIENCY_UNDEFINED", "SUFFICIENCY_UNDETERMINED",
    "REQUIRES_MORE_EVIDENCE", "READY_FOR_AUTHORIZATION", "AUTHORIZED",
    "BLOCKED", "REMEDIATION_REQUIRED", "EXPIRED", "REVOKED",
)

#: Absence is refusal. AUTHORIZED is reachable from exactly one state, and
#: REVOKED never reaches it again — a new authorization is a new record
#: evaluated from READY_FOR_AUTHORIZATION, never a resurrection.
AUTHORIZATION_TRANSITIONS = {
    "EVIDENCE_PENDING": {"SECURITY_REVIEW_PENDING", "ALPHA_EVIDENCE_PENDING",
                         "REQUIRES_MORE_EVIDENCE", "BLOCKED",
                         "REMEDIATION_REQUIRED"},
    "SECURITY_REVIEW_PENDING": {"EVIDENCE_PENDING", "ALPHA_EVIDENCE_PENDING",
                                "REQUIRES_MORE_EVIDENCE", "BLOCKED",
                                "REMEDIATION_REQUIRED"},
    "ALPHA_EVIDENCE_PENDING": {"SECURITY_REVIEW_PENDING",
                               "SUFFICIENCY_UNDEFINED",
                               "SUFFICIENCY_UNDETERMINED",
                               "REQUIRES_MORE_EVIDENCE", "BLOCKED",
                               "REMEDIATION_REQUIRED"},
    "SUFFICIENCY_UNDEFINED": {"SUFFICIENCY_UNDETERMINED",
                              "ALPHA_EVIDENCE_PENDING",
                              "REQUIRES_MORE_EVIDENCE", "BLOCKED",
                              "REMEDIATION_REQUIRED"},
    "SUFFICIENCY_UNDETERMINED": {"SUFFICIENCY_UNDEFINED",
                                 "REQUIRES_MORE_EVIDENCE", "BLOCKED",
                                 "REMEDIATION_REQUIRED"},
    "REQUIRES_MORE_EVIDENCE": {"EVIDENCE_PENDING", "SECURITY_REVIEW_PENDING",
                               "ALPHA_EVIDENCE_PENDING",
                               "SUFFICIENCY_UNDEFINED",
                               "SUFFICIENCY_UNDETERMINED",
                               "READY_FOR_AUTHORIZATION", "BLOCKED",
                               "REMEDIATION_REQUIRED"},
    "READY_FOR_AUTHORIZATION": {"AUTHORIZED", "REQUIRES_MORE_EVIDENCE",
                                "BLOCKED", "REMEDIATION_REQUIRED"},
    "AUTHORIZED": {"EXPIRED", "REVOKED", "BLOCKED", "REMEDIATION_REQUIRED"},
    "EXPIRED": {"READY_FOR_AUTHORIZATION", "REQUIRES_MORE_EVIDENCE",
                "REVOKED", "BLOCKED", "REMEDIATION_REQUIRED"},
    "REVOKED": {"READY_FOR_AUTHORIZATION", "REQUIRES_MORE_EVIDENCE",
                "BLOCKED", "REMEDIATION_REQUIRED"},
    "BLOCKED": {"EVIDENCE_PENDING", "REQUIRES_MORE_EVIDENCE",
                "REMEDIATION_REQUIRED"},
    "REMEDIATION_REQUIRED": {"BLOCKED"},
}

#: §18 decision priority, most restrictive first. The derivation ladder
#: walks this order; a later (more permissive) state is reachable only when
#: every earlier state's condition is absent. Documented here, tested by
#: tests/release/test_phase13_release_authority.py.
DECISION_PRIORITY = (
    "REVOKED", "EXPIRED", "REMEDIATION_REQUIRED", "BLOCKED",
    "EVIDENCE_PENDING", "SECURITY_REVIEW_PENDING", "ALPHA_EVIDENCE_PENDING",
    "SUFFICIENCY_UNDEFINED", "SUFFICIENCY_UNDETERMINED",
    "REQUIRES_MORE_EVIDENCE", "READY_FOR_AUTHORIZATION", "AUTHORIZED",
)

#: The §11 decision the repository may report for each derived state. Only
#: a validated external authority record produces AUTHORIZED here.
CANDIDATE_DECISION_BY_STATE = {
    "REVOKED": "REVOKED",
    "EXPIRED": "EXPIRED",
    "REMEDIATION_REQUIRED": "BLOCKED",
    "BLOCKED": "BLOCKED",
    "EVIDENCE_PENDING": "REQUIRES_MORE_EVIDENCE",
    "SECURITY_REVIEW_PENDING": "REQUIRES_MORE_EVIDENCE",
    "ALPHA_EVIDENCE_PENDING": "REQUIRES_MORE_EVIDENCE",
    "SUFFICIENCY_UNDEFINED": "REQUIRES_MORE_EVIDENCE",
    "SUFFICIENCY_UNDETERMINED": "REQUIRES_MORE_EVIDENCE",
    "REQUIRES_MORE_EVIDENCE": "REQUIRES_MORE_EVIDENCE",
    "READY_FOR_AUTHORIZATION": "NOT_AUTHORIZED",
    "AUTHORIZED": "AUTHORIZED",
}

ASSIGNMENT_ID = re.compile(r"^ASSIGNMENT-\d{3}$")
POLICY_ID = re.compile(r"^SUFFICIENCY-POLICY-\d{3}$")
RISK_ID = re.compile(r"^RISK-\d{3}$")
AUTHORIZATION_ID = re.compile(r"^AUTHORIZATION-\d{3}$")
REVOCATION_ID = re.compile(r"^REVOCATION-\d{3}$")
RESOLUTION_ID = re.compile(r"^RESOLUTION-\d{3}$")
RECLASSIFICATION_ID = re.compile(r"^RECLASSIFY-\d{3}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


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


def _phase9():
    return _load_module("phase9_intake_for_phase13", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase13", PHASE10_TOOL)


def is_fixture(record) -> bool:
    """Any of the three fixture markers makes a record a fixture (§19)."""
    return isinstance(record, dict) and (
        record.get("fixtureClass") == FIXTURE_MARKER
        or record.get("test_fixture_only") is True
        or record.get("fixture") is True)


def _refuse_fixture(record, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: the record declares a fixture marker — a fixture is never "
            "evidence and never a decision" % where)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalize_digest(value: str) -> str:
    value = str(value).strip().lower()
    return value[7:] if value.startswith("sha256:") else value


def _missing(record: dict, fields: tuple[str, ...],
             list_fields: tuple[str, ...] = ()) -> list[str]:
    out = []
    for field in fields:
        if field in list_fields:
            if field not in record or not isinstance(record[field], list):
                out.append(field)
            continue
        value = record.get(field)
        if field == "supersedes":
            if field not in record:
                out.append(field)
            continue
        if value is None or value == "" or value == {}:
            out.append(field)
    return out


def _date(value) -> datetime.date:
    """Parse an ISO date from a record; never a clock read."""
    return datetime.date.fromisoformat(str(value)[:10])


# ---------------------------------------------------------------- seals

def seal_record(record: dict) -> str:
    """sha256 over canonical JSON minus the seal — the Phase 9 algorithm.

    The guard suite asserts this stays identical to
    ``intake.seal_entry`` so the two spellings cannot drift.
    """
    unsealed = {k: v for k, v in record.items() if k != "seal"}
    canonical = json.dumps(unsealed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sealed_records(container: dict, id_key: str, where: str) -> list[dict]:
    """The container's records, every seal recomputed. A broken seal is an
    edit, and sealed records are never edited — a change is a new record."""
    records = list(container.get("records", []))
    for record in records:
        if seal_record(record) != record.get("seal"):
            raise BoundaryViolation(
                "%s: record %s fails its seal; sealed records are immutable "
                "— IMMUTABILITY FAIL, a change is a new record, never an "
                "edit" % (where, record.get(id_key, "<unnamed>")))
    return records


# ------------------------------------------------------- governance (§3, §4)

def validate_assignment(record: dict) -> list[str]:
    issues = ["assignment missing %s" % f
              for f in _missing(record, ASSIGNMENT_FIELDS)]
    if is_fixture(record):
        issues.append("a fixture is never an assignment")
    aid = record.get("assignmentId")
    if aid and not ASSIGNMENT_ID.match(aid):
        issues.append("assignmentId must match ASSIGNMENT-NNN")
    if record.get("authorityId") and \
            record["authorityId"] not in AUTHORITY_IDS:
        issues.append("authorityId %r is not a defined authority"
                      % record["authorityId"])
    date = record.get("date")
    if date and not ISO_DATE.match(str(date)):
        issues.append("date must be ISO 8601")
    return issues


def assigned_identities(assignments: list[dict]) -> dict[str, set]:
    """authorityId -> the identities holding it, from validated records."""
    held: dict[str, set] = {aid: set() for aid in AUTHORITY_IDS}
    for record in assignments:
        issues = validate_assignment(record)
        if issues:
            raise BoundaryViolation("assignment invalid: %s"
                                    % "; ".join(issues))
        held[record["authorityId"]].add(record["identity"])
    return held


def validate_overlap_decision(record: dict) -> list[str]:
    issues = ["overlap decision missing %s" % f
              for f in _missing(record, OVERLAP_DECISION_FIELDS)]
    if is_fixture(record):
        issues.append("a fixture is never a policy decision")
    roles = record.get("roles")
    if isinstance(roles, list):
        for role in roles:
            if role not in AUTHORITY_IDS:
                issues.append("overlap role %r is not a defined authority"
                              % role)
        if len(roles) < 2:
            issues.append("an overlap decision names at least two roles")
    elif roles is not None:
        issues.append("roles must be a list of authority identifiers")
    return issues


def _overlap_permitted(identity: str, pair: tuple[str, str],
                       overlap_decisions: list[dict]) -> bool:
    """Whether a complete recorded decision permits this identity to hold
    both roles. Matching strings never permit anything by themselves."""
    for decision in overlap_decisions:
        if validate_overlap_decision(decision):
            continue
        if decision.get("identity") == identity and \
                set(pair) <= set(decision.get("roles", [])):
            return True
    return False


def separation_violations(assignments: list[dict],
                          overlap_decisions: list[dict]) -> list[dict]:
    """§3: incompatible pairs held by one identity, minus recorded overlap
    decisions. Empty means separation holds."""
    held = assigned_identities(assignments)
    violations = []
    for first, second in INCOMPATIBLE_ROLES:
        for identity in sorted(held[first] & held[second]):
            if _overlap_permitted(identity, (first, second),
                                  overlap_decisions):
                continue
            violations.append({
                "identity": identity,
                "roles": [first, second],
                "problem": "one identity holds incompatible roles %s and %s "
                           "with no recorded overlap decision; role overlap "
                           "is a recorded policy decision, never an "
                           "inference from matching strings"
                           % (first, second),
            })
    return violations


def _acted_evidence(ledger: dict) -> dict[str, str | None]:
    """authorityId -> the intake evidence that the authority acted, from
    gate-eligible ACCEPTED entries only."""
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    acted: dict[str, str | None] = {aid: None for aid in AUTHORITY_IDS}
    for entry in ledger.get("entries", []):
        if is_fixture(entry):
            raise BoundaryViolation(
                "ledger entry %s carries a fixture marker; fixtures never "
                "enter the intake ledger" % entry.get("intakeId"))
        if not entry.get("gateEligible"):
            continue
        if effective.get(entry["intakeId"]) != "ACCEPTED":
            continue
        for authority_id, source in ACTED_BY_INTAKE_SOURCE.items():
            if entry.get("source") == source and acted[authority_id] is None:
                acted[authority_id] = entry["intakeId"]
    return acted


def authority_levels(assignments: list[dict], ledger: dict,
                     policies: list[dict], authorizations: list[dict],
                     risks: list[dict],
                     resolutions: list[dict]) -> dict[str, dict]:
    """§4: ROLE_DEFINED / AUTHORITY_ASSIGNED / AUTHORITY_ACTED per authority.

    A role existing in a JSON file is ROLE_DEFINED and nothing more. An
    assignment record raises it to AUTHORITY_ASSIGNED. AUTHORITY_ACTED
    requires the act itself: accepted intake evidence for the
    evidence-producing roles, a recorded sealed decision for the
    decision-making roles.
    """
    held = assigned_identities(assignments)
    acted = _acted_evidence(ledger)
    decision_acts = {
        "AUTH-ALPHA-PROGRAM": next(
            (p["policy_id"] for p in policies if p.get("status") == "ACTIVE"),
            None),
        "AUTH-RELEASE": next(
            (a["authorization_id"] for a in authorizations), None),
        "AUTH-SECURITY-OWNER": next(
            (r["risk_id"] for r in risks), None) or next(
            (r["resolutionId"] for r in resolutions
             if r.get("authority") in held["AUTH-SECURITY-OWNER"]), None),
    }
    levels = {}
    for authority_id, role, responsibility in AUTHORITIES:
        act = acted.get(authority_id) or decision_acts.get(authority_id)
        if act:
            level, basis = "AUTHORITY_ACTED", "recorded act: %s" % act
        elif held[authority_id]:
            level = "AUTHORITY_ASSIGNED"
            basis = "assigned to %d identit(ies); no act recorded" \
                % len(held[authority_id])
        else:
            level = "ROLE_DEFINED"
            basis = ("the role exists in the model and nothing more; a role "
                     "in a JSON file is not an authority action")
        levels[authority_id] = {
            "role": role, "responsibility": responsibility,
            "level": level, "basis": basis,
        }
    return levels


# --------------------------------------------- threshold policies (§5, §6)

def validate_policy(record: dict, assignments: list[dict],
                    require_assignment: bool = True) -> list[str]:
    issues = ["policy missing %s" % f
              for f in _missing(record, POLICY_FIELDS)]
    if is_fixture(record):
        issues.append("a fixture is never a threshold policy")
    pid = record.get("policy_id")
    if pid and not POLICY_ID.match(pid):
        issues.append("policy_id must match SUFFICIENCY-POLICY-NNN")
    if record.get("status") not in POLICY_STATUSES:
        issues.append("status %r is not in the vocabulary (%s)"
                      % (record.get("status"), "/".join(POLICY_STATUSES)))
    digest = record.get("artifact_digest")
    if digest and not SHA256_HEX.match(_normalize_digest(digest)):
        issues.append("artifact_digest is malformed")
    thresholds = record.get("thresholds")
    if isinstance(thresholds, dict):
        for dimension in THRESHOLD_DIMENSIONS:
            if dimension not in thresholds:
                issues.append("thresholds must define %s explicitly; an "
                              "absent dimension is an unenforced fiction"
                              % dimension)
            elif record.get("status") == "ACTIVE" \
                    and thresholds[dimension] is None:
                issues.append("an ACTIVE policy may not leave %s null; "
                              "null means the owner has not decided, and "
                              "an undecided policy cannot be active"
                              % dimension)
        for dimension in thresholds:
            if dimension not in THRESHOLD_DIMENSIONS:
                issues.append("threshold dimension %r is not in the "
                              "vocabulary" % dimension)
    elif thresholds is not None:
        issues.append("thresholds must be an object")
    if record.get("status") == "ACTIVE" and require_assignment:
        held = assigned_identities(assignments)
        if record.get("authority") not in held["AUTH-ALPHA-PROGRAM"]:
            issues.append(
                "an ACTIVE policy requires its authority to be an assigned "
                "AUTH-ALPHA-PROGRAM identity; a role in a JSON file is not "
                "an authority action")
    return issues


def policy_chain_problems(policies: list[dict]) -> list[str]:
    """Versioning invariants: unique ids, supersedes chains resolve, and at
    most one ACTIVE policy stands unsuperseded."""
    problems = []
    ids = [p.get("policy_id") for p in policies]
    if len(ids) != len(set(ids)):
        problems.append("policy_id values are not unique")
    known = set(ids)
    superseded = set()
    for policy in policies:
        target = policy.get("supersedes")
        if target is not None:
            if target not in known:
                problems.append("%s supersedes unknown policy %r"
                                % (policy.get("policy_id"), target))
            elif target == policy.get("policy_id"):
                problems.append("%s supersedes itself"
                                % policy.get("policy_id"))
            else:
                superseded.add(target)
    standing_active = [p for p in policies
                       if p.get("status") == "ACTIVE"
                       and p.get("policy_id") not in superseded]
    if len(standing_active) > 1:
        problems.append(
            "more than one ACTIVE policy stands unsuperseded (%s); a later "
            "threshold is a new version that supersedes, never a parallel "
            "truth" % ", ".join(sorted(p["policy_id"]
                                       for p in standing_active)))
    return problems


def active_policy(policies: list[dict],
                  subject_digests: set[str]) -> dict | None:
    """The one standing ACTIVE policy applicable to the subject artifact,
    or None. A policy for other bytes activates nothing here."""
    problems = policy_chain_problems(policies)
    if problems:
        raise BoundaryViolation("policy chain invalid: %s"
                                % "; ".join(problems))
    superseded = {p.get("supersedes") for p in policies if p.get("supersedes")}
    for policy in policies:
        if policy.get("status") != "ACTIVE":
            continue
        if policy.get("policy_id") in superseded:
            continue
        if _normalize_digest(policy.get("artifact_digest", "")) \
                in subject_digests:
            return policy
    return None


def policy_registry_state(policies: list[dict],
                          subject_digests: set[str]) -> str:
    """The registry state for THIS artifact. A policy bound to other bytes
    defines nothing here — the state stays UNDEFINED for the subject."""
    if active_policy(policies, subject_digests) is not None:
        return "SUFFICIENCY_POLICY_ACTIVE"
    applicable = [
        p for p in policies
        if _normalize_digest(p.get("artifact_digest") or "")
        in subject_digests
    ]
    if any(not validate_policy(p, [], require_assignment=False)
           for p in applicable):
        return "SUFFICIENCY_POLICY_PROPOSED"
    return "SUFFICIENCY_POLICY_UNDEFINED"


def sufficiency_measures(alpha_register: dict, security_register: dict,
                         ledger: dict) -> dict:
    """The measured values the thresholds compare against, derived from the
    committed Phase 11/12 registers and the ledger. Zero is measured as
    zero; nothing is estimated."""
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    accepted_rows = [
        r for r in alpha_register.get("reports", [])
        if r.get("classification") in ("ACCEPTED", "USER_EVIDENCE_UNBOUND")
    ]
    counts = alpha_register.get("counts", {})
    testers = {r.get("testerId") for r in accepted_rows if r.get("testerId")}
    machines = {
        h.get("machineLabel")
        for h in alpha_register.get("hardwareObservations", [])
        if h.get("machineLabel")
    }
    success_installs = sum(
        1 for r in accepted_rows
        if r.get("reportType") == "SUCCESS" and r.get("journey") == "A")
    journeys = {
        r.get("journey") for r in accepted_rows
        if r.get("reportType") == "SUCCESS"
        and r.get("journey") in ("A", "B", "C", "D", "E")
    }
    alpha_dates = sorted(
        e.get("receivedOn") for e in ledger.get("entries", [])
        if e.get("source") == "alpha-feedback"
        and effective.get(e["intakeId"]) == "ACCEPTED"
        and e.get("receivedOn"))
    period = 0
    if alpha_dates:
        period = (_date(alpha_dates[-1]) - _date(alpha_dates[0])).days + 1
    open_blockers = sorted(
        f.get("finding_id") for f in alpha_register.get("findings", [])
        if f.get("category") == "RELEASE_BLOCKER"
        and f.get("lifecycle_status") != "CLOSED")
    open_criticals = sorted(filter(None, (
        [f.get("finding_id") for f in alpha_register.get("findings", [])
         if f.get("derived_severity") == "CRITICAL"
         and f.get("lifecycle_status") != "CLOSED"]
        + [r.get("internal_id")
           for r in security_register.get("findings", [])
           if str(r.get("severity", "")).lower() == "critical"
           and r.get("status") not in ("NOT_APPLICABLE", "CLOSED")
           and r.get("status") != "BASELINE"])))
    hardware_machines = {
        e["intakeId"] for e in ledger.get("entries", [])
        if e.get("source") == "hardware" and e.get("gateEligible")
        and effective.get(e["intakeId"]) == "ACCEPTED"
    }
    performance = alpha_register.get("performance", {})
    return {
        "acceptedTesterReports": counts.get("acceptedReports", 0),
        "boundTesterReports": counts.get("boundReports", 0),
        "distinctTesters": len(testers),
        "distinctMachineIdentities": len(machines),
        "successfulInstallationReports": success_installs,
        "completedCoreJourneys": len(journeys),
        "evidencePeriodDays": period,
        "unresolvedBlockerFindings": open_blockers,
        "unresolvedCriticalFindings": open_criticals,
        "performanceEvidencePresent": bool(
            performance.get("subjective")
            or performance.get("testerMeasurements")
            or performance.get("projectMeasured")),
        "accessibilityEvidencePresent": bool(
            alpha_register.get("accessibilityObservations")),
        "distinctHardwareMachines": len(hardware_machines),
    }


_MEASURE_BY_DIMENSION = {
    "minimumAcceptedTesterReports": "acceptedTesterReports",
    "minimumDistinctTesters": "distinctTesters",
    "minimumDistinctMachineIdentities": "distinctMachineIdentities",
    "minimumSuccessfulInstallationReports": "successfulInstallationReports",
    "minimumCompletedCoreJourneys": "completedCoreJourneys",
    "minimumEvidencePeriodDays": "evidencePeriodDays",
    "maximumUnresolvedBlockerFindings": "unresolvedBlockerFindings",
    "maximumUnresolvedCriticalFindings": "unresolvedCriticalFindings",
    "performanceEvidenceRequired": "performanceEvidencePresent",
    "accessibilityEvidenceRequired": "accessibilityEvidencePresent",
    "minimumDistinctHardwareMachines": "distinctHardwareMachines",
}


def evaluate_sufficiency(policies: list[dict], alpha_register: dict,
                         security_register: dict, ledger: dict,
                         subject_digests: set[str]) -> dict:
    """One determination, fail-closed, never a guess.

    Without an active, artifact-applicable policy, any quantity of evidence
    — including a hundred accepted reports — stays SUFFICIENCY_UNDETERMINED;
    READY_FOR_TESTERS never becomes SUFFICIENT through silence or volume.
    """
    measures = sufficiency_measures(alpha_register, security_register, ledger)
    state = policy_registry_state(policies, subject_digests)
    if state != "SUFFICIENCY_POLICY_ACTIVE":
        return {
            "determination": "SUFFICIENCY_UNDETERMINED",
            "policyState": state,
            "activePolicy": None,
            "measures": measures,
            "shortfalls": [],
            "basis": "no active, artifact-applicable threshold policy "
                     "exists; measures are recorded but nothing is "
                     "concluded — the owner defines thresholds, the "
                     "repository never invents them",
        }
    policy = active_policy(policies, subject_digests)
    thresholds = policy["thresholds"]
    shortfalls = []
    for dimension in THRESHOLD_DIMENSIONS:
        threshold = thresholds[dimension]
        measure = measures[_MEASURE_BY_DIMENSION[dimension]]
        if dimension in _BOOLEAN_DIMENSIONS:
            if threshold and not measure:
                shortfalls.append("%s: required but absent" % dimension)
        elif dimension in _MAXIMUM_DIMENSIONS:
            if len(measure) > threshold:
                shortfalls.append("%s: %d against a maximum of %d (%s)"
                                  % (dimension, len(measure), threshold,
                                     ", ".join(measure)))
        elif measure < threshold:
            shortfalls.append("%s: %s against a minimum of %s"
                              % (dimension, measure, threshold))
    open_blockers = measures["unresolvedBlockerFindings"]
    if shortfalls:
        determination = "INSUFFICIENT_EVIDENCE"
        basis = "threshold shortfall(s) under %s: %s" \
            % (policy["policy_id"], "; ".join(shortfalls))
    elif open_blockers:
        determination = "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS"
        basis = "thresholds met under %s but blocker(s) remain open: %s" \
            % (policy["policy_id"], ", ".join(open_blockers))
    else:
        determination = "SUFFICIENT"
        basis = "every owner-defined threshold of %s met with no open " \
                "blockers" % policy["policy_id"]
    return {
        "determination": determination,
        "policyState": "SUFFICIENCY_POLICY_ACTIVE",
        "activePolicy": policy["policy_id"],
        "measures": measures,
        "shortfalls": shortfalls,
        "basis": basis,
    }


# ------------------------------------------------- blocking registry (§8)

def validate_reclassification(record: dict, assignments: list[dict],
                              subject_id: str) -> list[str]:
    issues = ["reclassification missing %s" % f
              for f in _missing(record, RECLASSIFICATION_FIELDS,
                                list_fields=("evidenceReferences",))]
    if is_fixture(record):
        issues.append("a fixture is never a reclassification decision")
    rid = record.get("decisionId")
    if rid and not RECLASSIFICATION_ID.match(rid):
        issues.append("decisionId must match RECLASSIFY-NNN")
    if record.get("toClass") not in BLOCKING_CLASSES:
        issues.append("toClass %r is not in the vocabulary"
                      % record.get("toClass"))
    if record.get("fromClass") not in BLOCKING_CLASSES:
        issues.append("fromClass %r is not in the vocabulary"
                      % record.get("fromClass"))
    condition = record.get("condition")
    if condition is not None and condition not in range(1, 11):
        issues.append("condition must be one of the ten (1..10)")
    if record.get("artifact") not in (None, "", subject_id):
        issues.append("the decision binds to %r, not the subject artifact "
                      "%s; a reclassification for other bytes moves nothing"
                      % (record.get("artifact"), subject_id))
    if not issues:
        held = assigned_identities(assignments)
        deciders = held["AUTH-RELEASE"] | held["AUTH-SECURITY-OWNER"]
        if record.get("authority") not in deciders:
            issues.append(
                "the deciding authority must be an assigned AUTH-RELEASE "
                "or AUTH-SECURITY-OWNER identity; a role in a JSON file is "
                "not an authority action")
    return issues


def _condition_character(condition: dict, ledger: dict) -> str:
    """How a condition's current state relates to the evidence actually
    held. Derived, never asserted."""
    state = condition.get("state")
    if state == "FALSE":
        return "CLEARED"
    if state == "UNDETERMINED":
        return "UNDETERMINED"
    source = CONDITION_EVIDENCE_SOURCE.get(condition.get("condition"))
    if source is None:
        return "ADVERSE_EVIDENCE"
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    accepted = any(
        e.get("source") == source and e.get("gateEligible")
        and effective.get(e["intakeId"]) == "ACCEPTED"
        for e in ledger.get("entries", []))
    return "ADVERSE_EVIDENCE" if accepted else "ABSENCE_OF_EVIDENCE"


def build_blocking(decision: dict, ledger: dict,
                   reclassifications: list[dict], assignments: list[dict],
                   conditions_sha256: str, conditions_bytes: int) -> dict:
    """blocking/blocking-conditions.json, deterministically.

    The ten inherited conditions are imported — source pinned by sha256,
    titles verbatim from the committed decision record — never rewritten.
    Every condition classifies BLOCKING unless a recorded, sealed,
    validated reclassification decision says otherwise; classification
    never weakens an inherited blocker silently.
    """
    _refuse_fixture(decision, "blocking registry")
    conditions = decision.get("blocking_conditions", [])
    if len(conditions) != 10 or sorted(
            c.get("condition") for c in conditions) != list(range(1, 11)):
        raise BoundaryViolation(
            "the decision record must carry exactly the ten inherited "
            "conditions, numbered 1..10; the registry imports, it never "
            "invents or drops")
    subject_id = decision.get("artifact")
    effective_class: dict[int, dict] = {}
    for record in reclassifications:
        issues = validate_reclassification(record, assignments, subject_id)
        if issues:
            raise BoundaryViolation("reclassification invalid: %s — an "
                                    "unrecorded or incomplete decision "
                                    "weakens nothing" % "; ".join(issues))
        effective_class[record["condition"]] = record
    rows = []
    for condition in sorted(conditions, key=lambda c: c["condition"]):
        number = condition["condition"]
        decided = effective_class.get(number)
        if decided:
            klass = decided["toClass"]
            class_basis = ("recorded decision %s by %s (%s): %s"
                           % (decided["decisionId"], decided["authority"],
                              decided["timestamp"], decided["reason"]))
        else:
            klass = "BLOCKING"
            class_basis = ("inherited class; no recorded reclassification "
                           "decision exists, and absence never weakens a "
                           "blocker")
        rows.append({
            "condition": number,
            "title": condition["title"],
            "state": condition["state"],
            "stateBasis": condition["basis"],
            "class": klass,
            "classBasis": class_basis,
            "evidenceCharacter": _condition_character(condition, ledger),
            "evidenceSource": CONDITION_EVIDENCE_SOURCE[number],
        })
    return {
        "schemaVersion": 1,
        "subjectArtifact": subject_id,
        "purpose": "the canonical blocking-condition registry: the ten "
                   "Phase 8 conditions imported with their source pinned "
                   "and titles verbatim, classified, and evaluated against "
                   "the evidence actually held",
        "sourcePins": {
            "qualification/phase8/conditions/"
            "ALPHA_RELEASE_BLOCKING_CONDITIONS.md": {
                "bytes": conditions_bytes, "sha256": conditions_sha256},
        },
        "importedFrom": "qualification/phase9/decision/"
                        "alpha-release-decision.json blocking_conditions "
                        "(titles verbatim; committed before any external "
                        "evidence; none weakened)",
        "classVocabulary": list(BLOCKING_CLASSES),
        "characterVocabulary": list(CONDITION_CHARACTERS),
        "reclassificationRule": "BLOCKING -> NON_BLOCKING requires a "
                                "recorded decision with reason, authority, "
                                "artifact, timestamp, policy basis, and "
                                "evidence references; the decision is "
                                "sealed and the chain is preserved",
        "conditions": rows,
        "note": "AUTHORIZED requires every condition FALSE on evidence. A "
                "condition TRUE on absence keeps the candidate pending; a "
                "condition TRUE on adverse evidence blocks it; neither "
                "authorizes anything, and UNDETERMINED is not cleared.",
    }


def blocking_from_disk() -> tuple[dict, list[str]]:
    """(rebuilt registry, problems). Refuses drift instead of absorbing it."""
    conditions_raw = PHASE8_CONDITIONS.read_bytes()
    rebuilt = build_blocking(
        load_json(PHASE9_DECISION), load_json(PHASE9_LEDGER),
        sealed_records(load_json(RECLASSIFICATION_PATH), "decisionId",
                       "reclassification-decisions.json"),
        sealed_records(load_json(ASSIGNMENTS_PATH), "assignmentId",
                       "assignments.json"),
        _sha256(conditions_raw), len(conditions_raw))
    problems: list[str] = []
    if BLOCKING_PATH.is_file():
        committed = load_json(BLOCKING_PATH)
        pin = committed.get("sourcePins", {}).get(
            "qualification/phase8/conditions/"
            "ALPHA_RELEASE_BLOCKING_CONDITIONS.md", {})
        if pin.get("sha256") != _sha256(conditions_raw):
            problems.append(
                "the Phase 8 conditions document changed under the "
                "committed pin; the inherited conditions are historical "
                "record — review and rebuild the registry deliberately")
        elif committed != rebuilt:
            problems.append(
                "blocking-conditions.json does not reproduce from its "
                "inputs; run build-blocking and review the diff")
    else:
        problems.append("blocking-conditions.json is absent; run "
                        "build-blocking")
    return rebuilt, problems


# --------------------------------------------------------- conflicts (§9)

def classify_evidence_conflict(domain: str,
                               observations: list[dict]) -> dict:
    """Contradictory external evidence, resolved fail-closed.

    Each observation is {"reference", "assessment", "favorable"}. When
    favorable and unfavorable observations coexist, the default is
    CONFLICT -> REQUIRES_HUMAN_DECISION with the unfavorable assessment(s)
    effective. Nothing is averaged; the favorable interpretation is never
    chosen automatically.
    """
    if domain not in CONFLICT_DOMAIN_AUTHORITY:
        raise BoundaryViolation("unknown conflict domain %r" % domain)
    for observation in observations:
        for field in ("reference", "assessment"):
            if not observation.get(field):
                raise BoundaryViolation(
                    "an observation without its %s cannot be weighed"
                    % field)
        if "favorable" not in observation:
            raise BoundaryViolation(
                "an observation must state whether it is favorable; an "
                "unstated direction is not favorable by default")
    favorable = [o for o in observations if o["favorable"] is True]
    unfavorable = [o for o in observations if o["favorable"] is False]
    if favorable and unfavorable:
        effective = sorted(o["assessment"] for o in unfavorable)
        return {
            "conflictStatus": "CONFLICT",
            "resolution": "REQUIRES_HUMAN_DECISION",
            "effectiveAssessment": effective,
            "effectiveBasis": "conflicting external evidence is never "
                              "averaged and never resolved in the "
                              "favorable direction; the unfavorable "
                              "observation(s) stand until the named "
                              "authority decides",
            "decisionAuthorityRequired": CONFLICT_DOMAIN_AUTHORITY[domain],
            "evidence": list(observations),
        }
    effective = sorted(o["assessment"] for o in (unfavorable or observations))
    return {
        "conflictStatus": "NO_CONFLICT",
        "resolution": None,
        "effectiveAssessment": effective,
        "effectiveBasis": "the observations do not contradict each other",
        "decisionAuthorityRequired": None,
        "evidence": list(observations),
    }


def validate_conflict_resolution(record: dict,
                                 assignments: list[dict]) -> list[str]:
    issues = ["resolution missing %s" % f
              for f in _missing(record, RESOLUTION_FIELDS,
                                list_fields=("evidenceReferences",))]
    if is_fixture(record):
        issues.append("a fixture is never a conflict resolution")
    rid = record.get("resolutionId")
    if rid and not RESOLUTION_ID.match(rid):
        issues.append("resolutionId must match RESOLUTION-NNN")
    domain = record.get("domain")
    if domain and domain not in CONFLICT_DOMAIN_AUTHORITY:
        issues.append("domain %r is not in the vocabulary" % domain)
    if not issues:
        held = assigned_identities(assignments)
        required = CONFLICT_DOMAIN_AUTHORITY[domain]
        if record.get("authority") not in held[required]:
            issues.append(
                "a %s conflict resolves only under an assigned %s "
                "identity; %r is not one"
                % (domain, required, record.get("authority")))
    return issues


# --------------------------------------------------- risk acceptance (§10)

def validate_risk_acceptance(record: dict, assignments: list[dict],
                             subject_digests: set[str],
                             findings_severity: dict[str, str]) -> list[str]:
    """The §10 rules over one acceptance record; empty == valid.

    ``findings_severity`` maps known finding identifiers to severities so a
    Critical acceptance can require its authority class and a dangling
    finding reference can fail closed.
    """
    issues = ["risk acceptance missing %s" % f
              for f in _missing(record, RISK_FIELDS,
                                list_fields=("finding_ids",))]
    if is_fixture(record):
        issues.append("a fixture is never an accepted risk")
    rid = record.get("risk_id")
    if rid and not RISK_ID.match(rid):
        issues.append("risk_id must match RISK-NNN")
    if not record.get("finding_ids"):
        issues.append("an acceptance that accepts no finding accepts "
                      "nothing")
    digest = record.get("artifact_digest")
    if digest and _normalize_digest(digest) not in subject_digests:
        issues.append(
            "the acceptance binds to %s, not the subject artifact; "
            "accepted risk never silently transfers to another artifact"
            % _normalize_digest(digest)[:12])
    for key in ("applicability", "not_affected", "closes_finding"):
        if record.get(key):
            issues.append(
                "%r has no place in a risk acceptance: ACCEPTED_RISK is "
                "not NOT_AFFECTED and an acceptance never closes the "
                "underlying finding" % key)
    for date_field in ("accepted_at", "expires_at"):
        value = record.get(date_field)
        if value and not ISO_DATE.match(str(value)):
            issues.append("%s must be ISO 8601" % date_field)
    if record.get("accepted_at") and record.get("expires_at") \
            and not issues:
        if _date(record["expires_at"]) <= _date(record["accepted_at"]):
            issues.append("expires_at must be after accepted_at; an "
                          "acceptance that is born expired decided nothing")
    unknown = [f for f in record.get("finding_ids") or []
               if f not in findings_severity]
    if unknown:
        issues.append("finding_ids name unknown finding(s) %s; a dangling "
                      "acceptance fails closed" % ", ".join(sorted(unknown)))
    if not issues:
        held = assigned_identities(assignments)
        criticals = [f for f in record["finding_ids"]
                     if str(findings_severity.get(f, "")).lower()
                     == "critical"]
        if criticals and record.get("authority") \
                not in held["AUTH-SECURITY-OWNER"]:
            issues.append(
                "accepting Critical finding(s) %s requires an assigned "
                "AUTH-SECURITY-OWNER identity; %r is not one"
                % (", ".join(sorted(criticals)), record.get("authority")))
    return issues


def risk_acceptance_state(record: dict, as_of: str | None) -> str:
    """STANDING or EXPIRED, derived — nobody flips this by hand."""
    if as_of is None:
        raise BoundaryViolation(
            "an acceptance's expiry cannot be evaluated without an "
            "operator-stated evaluation date; silence does not keep a "
            "risk accepted")
    return "EXPIRED" if _date(as_of) > _date(record["expires_at"]) \
        else "STANDING"


def risk_acceptance_applies(record: dict,
                            artifact_digests: set[str]) -> dict:
    """Digest equality only. Successor artifacts inherit nothing — not
    even through a recorded evidence-transfer decision, which covers
    evidence, never acceptance."""
    _refuse_fixture(record, "risk applicability")
    if _normalize_digest(record.get("artifact_digest", "")) \
            in artifact_digests:
        return {"result": "APPLIES",
                "reasoning": "the acceptance binds to this artifact's "
                             "bytes"}
    return {
        "result": "REFUSED",
        "reasoning": "the acceptance binds to different bytes; accepted "
                     "risk never transfers to a successor artifact — the "
                     "successor's owner accepts its own risks or fixes "
                     "the finding",
    }


# --------------------------------------------- authorization records (§11)

def authorization_floor(ledger: dict) -> list[str]:
    """Violations that would make AUTHORIZED self-manufactured: for each of
    the five external-gate sources, a gate-eligible ACCEPTED intake must
    exist. This extends the Phase 9 three-source floor to the full release
    decision."""
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    violations = []
    for source in AUTHORIZATION_FLOOR_SOURCES:
        eligible = [
            e for e in ledger.get("entries", [])
            if e.get("source") == source and e.get("gateEligible")
            and effective.get(e["intakeId"]) == "ACCEPTED"
        ]
        if not eligible:
            violations.append(
                "%s: no gate-eligible ACCEPTED intake exists, so the "
                "authority that owns this gate has not acted" % source)
    return violations


def _accepted_record(ledger: dict, intake_root: Path, source: str) -> dict:
    """The first gate-eligible ACCEPTED record for a source, read from the
    intake tree. Read-only; the ledger is never written here."""
    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    for entry in ledger.get("entries", []):
        if entry.get("source") == source and entry.get("gateEligible") \
                and effective.get(entry["intakeId"]) == "ACCEPTED":
            path = intake_root / source / entry["intakeId"] / "record.json"
            return json.loads(path.read_text(encoding="utf-8"))
    raise BoundaryViolation("no gate-eligible ACCEPTED %s intake exists"
                            % source)


def validate_authorization(record: dict, *, ledger: dict,
                           ledger_sha256: str, intake_root: Path,
                           assignments: list[dict],
                           overlap_decisions: list[dict],
                           policies: list[dict], risks: list[dict],
                           blocking: dict, alpha_register: dict,
                           security_register: dict,
                           as_of: str | None) -> list[str]:
    """Every reason this record cannot stand; empty == valid.

    A record claiming AUTHORIZED is checked against everything: the
    extended Phase 9 floor, the assigned release authority, separation of
    duties, the security gate, active-policy sufficiency, the blocking
    registry, standing risk acceptances, and its own evidence cut. An
    internal JSON claiming AUTHORIZED with any of these absent is refused —
    the repository evaluates requirements, it never creates the authority
    that satisfies them.
    """
    issues: list[str] = []
    if is_fixture(record):
        return ["REJECTED: the record declares a fixture marker — a "
                "fixture is never an authorization"]
    issues += ["authorization missing %s" % f
               for f in _missing(record, AUTHORIZATION_FIELDS,
                                 list_fields=_AUTHORIZATION_LIST_FIELDS)]
    aid = record.get("authorization_id")
    if aid and not AUTHORIZATION_ID.match(aid):
        issues.append("authorization_id must match AUTHORIZATION-NNN")
    decision = record.get("decision")
    if decision not in AUTHORIZATION_DECISIONS:
        issues.append("decision %r is not in the vocabulary" % decision)
    if "revocation_status" in record:
        issues.append("revocation_status is derived from the revocation "
                      "registry, never stored on the record; a stored flag "
                      "is an editable flag, and revocation is not editable")
    for field in ("issued_at", "expires_at", "decision_timestamp"):
        value = record.get(field)
        if value and not ISO_DATE.match(str(value)):
            issues.append("%s must be ISO 8601" % field)
    if not record.get("expires_at"):
        issues.append("no infinite authorization by omission: a record "
                      "without expires_at is invalid")
    elif record.get("issued_at") \
            and _date(record["expires_at"]) <= _date(record["issued_at"]):
        issues.append("expires_at must be after issued_at")

    subject = ledger["subjectArtifact"]
    subject_digests = _phase9().subject_digests(ledger)
    digest = record.get("artifact_digest")
    if digest and _normalize_digest(digest) not in subject_digests:
        issues.append(
            "DOES_NOT_APPLY: the record binds to %s, not the subject "
            "artifact; an authorization for other bytes decides nothing "
            "here and never transfers" % _normalize_digest(digest)[:12])
    if record.get("artifact_identity") \
            and record["artifact_identity"] != subject.get("identifier"):
        issues.append("artifact_identity %r is not the subject %s"
                      % (record["artifact_identity"],
                         subject.get("identifier")))

    if decision != "AUTHORIZED" or issues:
        return issues

    # Everything below exists only for AUTHORIZED — the decision the
    # repository may check and may never make.
    if record.get("authority_role") != "RELEASE_AUTHORITY":
        issues.append("AUTHORIZED requires authority_role "
                      "RELEASE_AUTHORITY; %r decided nothing"
                      % record.get("authority_role"))
    held = assigned_identities(assignments)
    if record.get("authority") not in held["AUTH-RELEASE"]:
        issues.append(
            "the release authority is defined but %r is not an assigned "
            "AUTH-RELEASE identity; a role existing in a JSON file is not "
            "an authority action, and the repository cannot assign one to "
            "itself" % record.get("authority"))
    for violation in separation_violations(assignments, overlap_decisions):
        issues.append("separation of duties: %s" % violation["problem"])

    floor = authorization_floor(ledger)
    issues += ["authorization floor: %s" % v for v in floor]
    if floor:
        return issues

    signing_record = _accepted_record(ledger, intake_root, "signing")
    if signing_record.get("category") != "PRODUCTION ARTIFACT SIGNED":
        issues.append(
            "the signing evidence is %r; a signing drill presented as "
            "production signing satisfies nothing"
            % signing_record.get("category"))
    approval_record = _accepted_record(ledger, intake_root,
                                       "second-approval")
    signer = signing_record.get("signerIdentity")
    approvers = {
        (approval_record.get("firstApprover") or {}).get("name"),
        (approval_record.get("secondApprover") or {}).get("name"),
    } - {None}
    if signer in approvers and not _overlap_permitted(
            signer, ("AUTH-KEY", "AUTH-SECOND-APPROVER"),
            overlap_decisions):
        issues.append(
            "CONFLICT: the production signer %r also appears as an "
            "approver; signer and approver separate unless a recorded "
            "overlap decision permits this identity to hold both roles"
            % signer)

    gate = (security_register.get("securityGate") or {}).get("status")
    if gate != "SATISFIED":
        issues.append("the security gate is %s, not SATISFIED; an "
                      "authorization cannot outrun the review" % gate)
    if record.get("security_status") != gate:
        issues.append("the record claims security_status %r but the "
                      "derived gate is %r; a decision states what the "
                      "evidence states" % (record.get("security_status"),
                                           gate))

    sufficiency = evaluate_sufficiency(policies, alpha_register,
                                       security_register, ledger,
                                       subject_digests)
    if sufficiency["determination"] != "SUFFICIENT":
        issues.append(
            "Alpha sufficiency is %s (%s); undefined thresholds and "
            "insufficient evidence refuse alike — nothing is rounded up"
            % (sufficiency["determination"], sufficiency["basis"]))
    if record.get("alpha_status") != sufficiency["determination"]:
        issues.append("the record claims alpha_status %r but the derived "
                      "determination is %r"
                      % (record.get("alpha_status"),
                         sufficiency["determination"]))
    if sufficiency["activePolicy"] and sufficiency["activePolicy"] \
            not in (record.get("policy_versions") or []):
        issues.append("the record does not name the active sufficiency "
                      "policy %s in policy_versions; the policy version "
                      "is part of the evidence cut"
                      % sufficiency["activePolicy"])

    for row in blocking.get("conditions", []):
        if row["class"] in ("NON_BLOCKING", "NOT_APPLICABLE"):
            continue
        if row["class"] == "REQUIRES_HUMAN_DECISION":
            issues.append(
                "condition %d (%s) is classified REQUIRES_HUMAN_DECISION "
                "and no decision has resolved it" % (row["condition"],
                                                     row["title"]))
        elif row["state"] != "FALSE":
            issues.append(
                "blocking condition %d (%s) is %s — AUTHORIZED requires "
                "every condition FALSE on evidence, and %s is not FALSE"
                % (row["condition"], row["title"], row["state"],
                   row["state"]))

    standing_risk_ids = []
    for risk in risks:
        if _normalize_digest(risk.get("artifact_digest", "")) \
                not in subject_digests:
            continue
        state = risk_acceptance_state(risk, as_of)
        if state == "EXPIRED":
            issues.append(
                "accepted risk %s expired %s; an expired acceptance "
                "blocks authorization until renewed or the finding is "
                "fixed" % (risk.get("risk_id"), risk.get("expires_at")))
        else:
            standing_risk_ids.append(risk.get("risk_id"))
    for risk_id in standing_risk_ids:
        if risk_id not in (record.get("accepted_risks") or []):
            issues.append(
                "standing accepted risk %s is not named by the record; "
                "an authorization decides over every standing acceptance, "
                "not a selection" % risk_id)

    cut = record.get("evidence_cut") or {}
    for field in EVIDENCE_CUT_FIELDS:
        if field not in cut:
            issues.append("evidence_cut missing %s; a decision must be "
                          "reproducible from immutable inputs" % field)
    if cut.get("ledgerSha256") and cut["ledgerSha256"] != ledger_sha256:
        issues.append(
            "the evidence cut pins ledger %s… but the ledger presented is "
            "%s…; the decision was cut against different evidence"
            % (str(cut["ledgerSha256"])[:12], ledger_sha256[:12]))
    known_intakes = {e["intakeId"] for e in ledger.get("entries", [])}
    for intake_id in cut.get("intakeIds") or []:
        if intake_id not in known_intakes:
            issues.append("evidence_cut names unknown intake %s"
                          % intake_id)

    if as_of is None:
        issues.append("AUTHORIZED cannot be evaluated without an "
                      "operator-stated evaluation date; expiry is derived, "
                      "never assumed away")
    return issues


def authorization_state_of(record: dict, revocations: list[dict],
                           as_of: str | None) -> str:
    """AUTHORIZED, EXPIRED, or REVOKED for one standing record — derived,
    never flipped by hand. Revocation outranks expiry: a revoked record
    stays revoked whatever the calendar says."""
    for revocation in revocations:
        if revocation.get("target_authorization") \
                == record.get("authorization_id"):
            return "REVOKED"
    if as_of is None:
        raise BoundaryViolation(
            "an authorization's expiry cannot be evaluated without an "
            "operator-stated evaluation date")
    if _date(as_of) > _date(record["expires_at"]):
        return "EXPIRED"
    return record.get("decision", "NOT_AUTHORIZED")


def authorization_applies(record: dict, artifact: dict) -> dict:
    """§15: authorization binds to exact bytes and never crosses an
    artifact edge. Evidence applicability may be evaluated (Phase 10);
    authorization may not — there is deliberately no transfer-decision
    branch here."""
    _refuse_fixture(record, "authorization applicability")
    digests = {_normalize_digest(d)
               for d in (artifact.get("digests") or {}).values()}
    if artifact.get("digest"):
        digests.add(_normalize_digest(artifact["digest"]))
    if _normalize_digest(record.get("artifact_digest", "")) in digests:
        return {"result": "APPLIES",
                "reasoning": "the authorization binds to this artifact's "
                             "bytes"}
    return {
        "result": "REFUSED",
        "reasoning": "authorization for artifact bytes %s… does not apply "
                     "to %s; a successor artifact starts NOT_AUTHORIZED "
                     "regardless of its parent's authorization — evidence "
                     "applicability may be evaluated, authorization never "
                     "transfers" % (
                         _normalize_digest(
                             record.get("artifact_digest", ""))[:12],
                         artifact.get("artifact_id")),
    }


# --------------------------------------------------------- revocation (§13)

def validate_revocation(record: dict, authorizations: list[dict],
                        assignments: list[dict],
                        subject_digests: set[str]) -> list[str]:
    issues = ["revocation missing %s" % f
              for f in _missing(record, REVOCATION_FIELDS)]
    if is_fixture(record):
        issues.append("a fixture is never a revocation")
    rid = record.get("revocation_id")
    if rid and not REVOCATION_ID.match(rid):
        issues.append("revocation_id must match REVOCATION-NNN")
    target = record.get("target_authorization")
    target_record = next(
        (a for a in authorizations
         if a.get("authorization_id") == target), None)
    if target and target_record is None:
        issues.append("target authorization %r does not exist; a "
                      "revocation of nothing revokes nothing" % target)
    if target_record is not None and record.get("artifact_digest") and \
            _normalize_digest(record["artifact_digest"]) \
            != _normalize_digest(target_record.get("artifact_digest", "")):
        issues.append("the revocation names different bytes than its "
                      "target authorization")
    digest = record.get("artifact_digest")
    if digest and subject_digests and \
            _normalize_digest(digest) not in subject_digests:
        issues.append("the revocation binds to %s, not the subject "
                      "artifact" % _normalize_digest(digest)[:12])
    if not issues:
        held = assigned_identities(assignments)
        revokers = held["AUTH-RELEASE"] | held["AUTH-SECURITY-OWNER"]
        if record.get("authority") not in revokers:
            issues.append(
                "revocation requires an assigned AUTH-RELEASE or "
                "AUTH-SECURITY-OWNER identity; %r is not one"
                % record.get("authority"))
    return issues


# ------------------------------------------------------ state machine (§17)

def authorization_transition(current: str, target: str,
                             context: dict | None = None) -> str:
    """Advance the candidate authorization state; refusal is the default,
    and silence satisfies no guard."""
    if current not in AUTHORIZATION_STATES:
        raise BoundaryViolation("unknown authorization state %r" % current)
    if target not in AUTHORIZATION_STATES:
        raise BoundaryViolation("unknown authorization state %r" % target)
    if target not in AUTHORIZATION_TRANSITIONS[current]:
        raise BoundaryViolation(
            "authorization transition %s -> %s is not allowed; the "
            "allowed set from %s is {%s}"
            % (current, target, current,
               ", ".join(sorted(AUTHORIZATION_TRANSITIONS[current]))
               or "nothing"))
    context = context or {}
    if target == "AUTHORIZED":
        record = context.get("authorizationRecord")
        issues = context.get("validationIssues")
        if not isinstance(record, dict) or issues is None:
            raise BoundaryViolation(
                "AUTHORIZED requires the validated authorization record "
                "and its validation result in context; a transition "
                "without them is the repository authorizing itself")
        if record.get("decision") != "AUTHORIZED":
            raise BoundaryViolation(
                "the record decides %r, not AUTHORIZED"
                % record.get("decision"))
        if issues:
            raise BoundaryViolation(
                "the authorization record does not validate: %s"
                % "; ".join(issues))
    if target == "READY_FOR_AUTHORIZATION":
        sufficiency = context.get("sufficiency") or {}
        if not context.get("floorSatisfied") \
                or sufficiency.get("determination") != "SUFFICIENT" \
                or not context.get("blockingClear"):
            raise BoundaryViolation(
                "READY_FOR_AUTHORIZATION requires the satisfied "
                "authorization floor, a SUFFICIENT determination under an "
                "active policy, and every blocking condition FALSE; "
                "nothing here is rounded up")
    if target == "REVOKED":
        revocation = context.get("revocationRecord")
        if not isinstance(revocation, dict) or _missing(
                revocation, REVOCATION_FIELDS):
            raise BoundaryViolation(
                "REVOKED requires a complete revocation record; an "
                "authorization does not lapse into revocation")
    if target == "EXPIRED":
        as_of, expires = context.get("asOf"), context.get("expiresAt")
        if not as_of or not expires or _date(as_of) <= _date(expires):
            raise BoundaryViolation(
                "EXPIRED requires an evaluation date past expires_at; "
                "expiry is derived from dates, never asserted")
    if target == "BLOCKED" and not context.get("reason"):
        raise BoundaryViolation("BLOCKED requires its recorded reason")
    if target == "REMEDIATION_REQUIRED" and not context.get("findings"):
        raise BoundaryViolation(
            "REMEDIATION_REQUIRED requires the finding(s) that require it")
    return target


def derive_authorization_state(*, standing: dict | None, remediation: list,
                               adverse: list, evidence_total: int,
                               security_gate: str, alpha_accepted: int,
                               sufficiency: dict, floor_missing: list,
                               expired_risks: list) -> dict:
    """The §18 ladder: walk DECISION_PRIORITY, most restrictive first.

    A later state is reachable only when every earlier condition is
    absent; a human authority record changes conditions, never this
    ordering.
    """
    if standing and standing.get("state") == "REVOKED":
        return {"state": "REVOKED",
                "basis": "authorization %s is revoked; REVOKED never "
                         "returns to AUTHORIZED — a new authorization is "
                         "a new record" % standing.get("authorizationId")}
    if standing and standing.get("state") == "EXPIRED":
        return {"state": "EXPIRED",
                "basis": "authorization %s expired %s; expiry is derived, "
                         "and an expired authorization authorizes nothing"
                         % (standing.get("authorizationId"),
                            standing.get("expiresAt"))}
    if remediation:
        return {"state": "REMEDIATION_REQUIRED",
                "basis": "finding(s) %s require a fix; the fix is a new "
                         "artifact with its own qualification boundary"
                         % ", ".join(sorted(remediation))}
    if adverse:
        return {"state": "BLOCKED",
                "basis": "blocking condition(s) true on adverse evidence: "
                         "%s" % "; ".join(sorted(adverse))}
    if evidence_total == 0:
        return {"state": "EVIDENCE_PENDING",
                "basis": "zero gate-eligible accepted external intakes "
                         "exist; every gate awaits its owner, and absence "
                         "authorizes nothing"}
    if security_gate != "SATISFIED":
        return {"state": "SECURITY_REVIEW_PENDING",
                "basis": "the security gate is %s; the review completes "
                         "before anything else is weighed" % security_gate}
    if alpha_accepted == 0:
        return {"state": "ALPHA_EVIDENCE_PENDING",
                "basis": "zero accepted Alpha tester reports exist"}
    if sufficiency.get("policyState") != "SUFFICIENCY_POLICY_ACTIVE":
        return {"state": "SUFFICIENCY_UNDEFINED",
                "basis": "no active, artifact-applicable sufficiency "
                         "policy exists; evidence cannot become "
                         "sufficient against undefined thresholds"}
    if sufficiency.get("determination") == "SUFFICIENCY_UNDETERMINED":
        return {"state": "SUFFICIENCY_UNDETERMINED",
                "basis": sufficiency.get("basis", "")}
    if floor_missing or expired_risks \
            or sufficiency.get("determination") != "SUFFICIENT":
        gaps = list(floor_missing)
        if sufficiency.get("determination") != "SUFFICIENT":
            gaps.append("alpha sufficiency: %s"
                        % sufficiency.get("determination"))
        gaps += ["expired risk acceptance: %s" % r for r in expired_risks]
        return {"state": "REQUIRES_MORE_EVIDENCE",
                "basis": "; ".join(gaps)}
    if standing and standing.get("state") == "AUTHORIZED":
        return {"state": "AUTHORIZED",
                "basis": "validated authorization %s stands, unexpired "
                         "and unrevoked, over the satisfied floor"
                         % standing.get("authorizationId")}
    return {"state": "READY_FOR_AUTHORIZATION",
            "basis": "every requirement the repository can evaluate is "
                     "satisfied; the decision itself belongs to the "
                     "release authority, and the repository cannot make "
                     "it"}


# --------------------------------------------------- status derivation

def next_action(state: str, floor_missing: list[str],
                sufficiency: dict) -> str:
    """Exactly one highest-priority next action, deterministically, on the
    same ladder Phase 10 uses."""
    if state in ("REVOKED", "EXPIRED"):
        return ("A new authorization is required: the release authority "
                "re-decides over current evidence; nothing resurrects the "
                "old record")
    if state == "REMEDIATION_REQUIRED":
        return ("Remediate: the fix produces a new artifact with its own "
                "qualification boundary")
    if state == "BLOCKED":
        return ("Resolve the adverse blocking condition; authorization is "
                "impossible while it stands")
    if "security-review" in "; ".join(floor_missing) \
            or state in ("EVIDENCE_PENDING", "SECURITY_REVIEW_PENDING"):
        return ("Commission the independent security review — the "
                "canonical commissioning package is "
                "qualification/phase11/security-review/REQUEST.md, and "
                "conditions 1 and 2 stay true until its owner acts")
    if state == "ALPHA_EVIDENCE_PENDING":
        return ("Enroll Alpha testers under "
                "qualification/phase12/alpha/PROGRAM.md")
    if state in ("SUFFICIENCY_UNDEFINED", "SUFFICIENCY_UNDETERMINED"):
        return ("The Alpha program owner records a sufficiency threshold "
                "policy (SUFFICIENCY-POLICY-NNN) through "
                "qualification/phase13/tools/release_authority_ops.py "
                "record-policy; the repository never invents thresholds")
    if state == "REQUIRES_MORE_EVIDENCE":
        return ("Close the remaining evidence gaps: %s"
                % "; ".join(floor_missing) if floor_missing
                else "Close the remaining evidence gaps")
    if state == "READY_FOR_AUTHORIZATION":
        return ("Present the evidence cut to the assigned release "
                "authority for the authorization decision; the repository "
                "cannot make it")
    return ("Operate under the standing authorization; revoke it if the "
            "conditions that supported it change")


def derive_status(ledger: dict, ledger_sha256: str, graph: dict,
                  decision: dict, security_register: dict,
                  alpha_register: dict, governance: dict,
                  blocking: dict, previous: dict | None,
                  as_of: str | None) -> dict:
    """qualification/phase13/authorization-status.json, reproducibly.

    Inputs: the Phase 9 ledger (read, never written), the artifact graph,
    the decision record, the committed Phase 11/12 registers, and the
    Phase 13 governance registries. With zero external evidence this is an
    EVIDENCE_PENDING record around a NOT_AUTHORIZED candidate — zero
    recorded as zero, never as readiness.
    """
    ops10 = _phase10()
    graph_issues = ops10.validate_graph(graph)
    if graph_issues:
        raise BoundaryViolation("artifact graph invalid: %s"
                                % "; ".join(graph_issues))
    candidate = ops10._active_candidate(graph)
    subject_id = ledger["subjectArtifact"]["identifier"]
    if candidate["artifact_id"] != subject_id:
        raise BoundaryViolation(
            "the active candidate %s is not the intake subject %s; a "
            "successor artifact starts NOT_AUTHORIZED under its own "
            "boundary — authorization never transfers"
            % (candidate["artifact_id"], subject_id))
    subject_digests = _phase9().subject_digests(ledger)

    assignments = governance["assignments"]
    overlaps = governance["overlapDecisions"]
    policies = governance["policies"]
    risks = governance["risks"]
    authorizations = governance["authorizations"]
    revocations = governance["revocations"]
    resolutions = governance["resolutions"]

    for resolution in resolutions:
        issues = validate_conflict_resolution(resolution, assignments)
        if issues:
            raise BoundaryViolation("conflict resolution invalid: %s"
                                    % "; ".join(issues))
    for revocation in revocations:
        issues = validate_revocation(revocation, authorizations,
                                     assignments, subject_digests)
        if issues:
            raise BoundaryViolation("revocation invalid: %s"
                                    % "; ".join(issues))

    levels = authority_levels(assignments, ledger, policies,
                              authorizations, risks, resolutions)
    violations = separation_violations(assignments, overlaps)
    sufficiency = evaluate_sufficiency(policies, alpha_register,
                                       security_register, ledger,
                                       subject_digests)
    floor_missing = authorization_floor(ledger)

    findings_severity = _known_finding_severities(security_register,
                                                  alpha_register)
    risk_rows = []
    expired_risks = []
    for risk in risks:
        issues = validate_risk_acceptance(risk, assignments,
                                          subject_digests,
                                          findings_severity)
        if issues:
            raise BoundaryViolation("risk acceptance invalid: %s"
                                    % "; ".join(issues))
        state = risk_acceptance_state(risk, as_of)
        if state == "EXPIRED":
            expired_risks.append(risk["risk_id"])
        risk_rows.append({"riskId": risk["risk_id"], "state": state,
                          "expiresAt": risk["expires_at"],
                          "findingIds": sorted(risk["finding_ids"])})

    standing = None
    authorization_rows = []
    for record in authorizations:
        state = authorization_state_of(record, revocations, as_of) \
            if record.get("decision") == "AUTHORIZED" \
            else record.get("decision")
        authorization_rows.append({
            "authorizationId": record.get("authorization_id"),
            "decision": record.get("decision"),
            "derivedState": state,
            "expiresAt": record.get("expires_at"),
        })
        if record.get("decision") == "AUTHORIZED":
            standing = {"authorizationId": record.get("authorization_id"),
                        "state": state,
                        "expiresAt": record.get("expires_at")}

    remediation = sorted(
        [r["internal_id"] for r in security_register.get("findings", [])
         if r.get("status") == "REMEDIATION_REQUIRED"]
        + [f["finding_id"] for f in alpha_register.get("findings", [])
           if f.get("lifecycle_status") == "FIX_REQUIRED"])
    adverse = [
        "condition %d (%s): %s" % (row["condition"], row["title"],
                                   row["state"])
        for row in blocking.get("conditions", [])
        if row.get("evidenceCharacter") == "ADVERSE_EVIDENCE"
        and row.get("class") == "BLOCKING"
    ]

    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    evidence_total = sum(
        1 for e in ledger.get("entries", [])
        if e.get("gateEligible") and effective.get(e["intakeId"])
        == "ACCEPTED")
    alpha_accepted = alpha_register.get("counts", {}).get(
        "acceptedReports", 0)
    security_gate = (security_register.get("securityGate") or {}).get(
        "status", "AWAITING_EXTERNAL_EVIDENCE")

    derived_state = derive_authorization_state(
        standing=standing, remediation=remediation, adverse=adverse,
        evidence_total=evidence_total, security_gate=security_gate,
        alpha_accepted=alpha_accepted, sufficiency=sufficiency,
        floor_missing=floor_missing, expired_risks=expired_risks)

    history = list((previous or {}).get("stateHistory", []))
    if not history:
        raise BoundaryViolation(
            "no state history exists; seed the first record with an "
            "explicit operator entry rather than inventing one")
    if history[-1]["state"] != derived_state["state"]:
        history.append({"state": derived_state["state"],
                        "recordedOn": as_of,
                        "basis": derived_state["basis"]})

    candidate_decision = CANDIDATE_DECISION_BY_STATE[derived_state["state"]]

    return {
        "schemaVersion": 1,
        "subjectArtifact": subject_id,
        "artifactDigest": candidate["digest"],
        "evaluationDate": as_of,
        "authorizationState": derived_state["state"],
        "stateBasis": derived_state["basis"],
        "candidateDecision": candidate_decision,
        "decisionBasis": "the repository derives at most NOT_AUTHORIZED, "
                         "BLOCKED, or REQUIRES_MORE_EVIDENCE; AUTHORIZED "
                         "exists only as a validated external authority "
                         "record over the satisfied floor",
        "decisionPriority": list(DECISION_PRIORITY),
        "authorityModel": levels,
        "separationViolations": violations,
        "sufficiency": sufficiency,
        "blockingConditions": blocking.get("conditions", []),
        "authorizationFloor": {
            "satisfied": not floor_missing,
            "requiredSources": list(AUTHORIZATION_FLOOR_SOURCES),
            "missing": floor_missing,
        },
        "riskAcceptances": risk_rows,
        "authorizations": authorization_rows,
        "standingAuthorization": standing,
        "revocations": [r.get("revocation_id") for r in revocations],
        "evidenceCut": {
            "ledgerSha256": ledger_sha256,
            "ledgerEntries": len(ledger.get("entries", [])),
            "gateEligibleAccepted": evidence_total,
            "securityRegister": "qualification/phase11/"
                                "security-findings.json",
            "alphaRegister": "qualification/phase12/alpha-findings.json",
            "policyVersions": [p.get("policy_id") for p in policies],
        },
        "stateHistory": history,
        "derivedFrom": {
            "intakeLedger": "qualification/phase9/intake/LEDGER.json "
                            "(read-only)",
            "artifactGraph": "qualification/phase10/artifacts/"
                             "artifact-graph.json",
            "decisionRecord": "qualification/phase9/decision/"
                              "alpha-release-decision.json",
            "securityRegister": "qualification/phase11/"
                                "security-findings.json",
            "alphaRegister": "qualification/phase12/alpha-findings.json",
            "governance": "qualification/phase13/governance/, sufficiency/,"
                          " blocking/, decisions/",
            "note": "derived, not primary evidence: recomputable from "
                    "these inputs on every run; tested by tests/release/"
                    "test_phase13_release_authority.py",
        },
        "nextAction": next_action(derived_state["state"], floor_missing,
                                  sufficiency),
        "note": "PHASE 13 DOES NOT AUTHORIZE THE ARTIFACT. The machinery "
                "evaluates authorization requirements; the authority that "
                "satisfies them is human, external, and enters only "
                "through the Phase 9 intake and recorded, sealed "
                "decisions. Zero external evidence derives "
                "EVIDENCE_PENDING — never READY, never AUTHORIZED.",
    }


def _known_finding_severities(security_register: dict,
                              alpha_register: dict) -> dict[str, str]:
    severities = {}
    for row in security_register.get("findings", []):
        if row.get("internal_id"):
            severities[row["internal_id"]] = row.get("severity") or ""
    for row in alpha_register.get("findings", []):
        if row.get("finding_id"):
            severities[row["finding_id"]] = row.get("derived_severity") or ""
    return severities


def _load_governance() -> dict:
    return {
        "assignments": sealed_records(
            load_json(ASSIGNMENTS_PATH), "assignmentId",
            "assignments.json"),
        "overlapDecisions": sealed_records(
            load_json(SEPARATION_PATH), "decisionId",
            "separation-policy.json"),
        "policies": sealed_records(
            load_json(POLICIES_PATH), "policy_id",
            "threshold-policies.json"),
        "risks": sealed_records(
            load_json(RISKS_PATH), "risk_id", "risk-acceptances.json"),
        "authorizations": sealed_records(
            load_json(AUTHORIZATIONS_PATH), "authorization_id",
            "authorizations.json"),
        "revocations": sealed_records(
            load_json(REVOCATIONS_PATH), "revocation_id",
            "revocations.json"),
        "resolutions": sealed_records(
            load_json(RESOLUTIONS_PATH), "resolutionId",
            "conflict-resolutions.json"),
    }


def sync_status(write: bool = True,
                as_of: str | None = None) -> tuple[dict, list[str]]:
    """Recompute authorization-status.json from its inputs; refuse drift,
    refuse history loss, refuse a ledger changing underfoot."""
    blocking, problems = blocking_from_disk()
    if problems:
        return {}, ["blocking: %s" % p for p in problems]
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    previous = load_json(STATUS_PATH) if STATUS_PATH.is_file() else None
    if as_of is None and previous:
        as_of = previous.get("evaluationDate")
    if as_of is not None and not ISO_DATE.match(str(as_of)):
        return {}, ["--as-of must be ISO 8601"]
    derived = derive_status(
        json.loads(ledger_bytes.decode("utf-8")), _sha256(ledger_bytes),
        load_json(PHASE10_GRAPH), load_json(PHASE9_DECISION),
        load_json(PHASE11_REGISTER), load_json(PHASE12_REGISTER),
        _load_governance(), blocking, previous, as_of)
    problems = []
    if previous:
        old_history = previous.get("stateHistory", [])
        if derived["stateHistory"][: len(old_history)] != old_history:
            problems.append("state history would lose entries; refusing")
    if PHASE9_LEDGER.read_bytes() != ledger_bytes:
        problems.append("the Phase 9 ledger changed underfoot; refusing")
    if not problems and write:
        dump_json(STATUS_PATH, derived)
    return derived, problems


# ---------------------------------------------------------------- verify

def _governance_shape_problems() -> list[str]:
    problems = []
    authorities = load_json(AUTHORITIES_PATH)
    declared = {(a.get("authorityId"), a.get("role")): a
                for a in authorities.get("authorities", [])}
    for authority_id, role, responsibility in AUTHORITIES:
        row = declared.get((authority_id, role))
        if row is None:
            problems.append(
                "authorities.json does not declare %s as %s; the committed "
                "model and this module must agree" % (authority_id, role))
        elif row.get("responsibility") != responsibility:
            problems.append("%s: responsibility drifted from the model"
                            % authority_id)
    if len(authorities.get("authorities", [])) != len(AUTHORITIES):
        problems.append("authorities.json declares %d authorities; the "
                        "model defines %d"
                        % (len(authorities.get("authorities", [])),
                           len(AUTHORITIES)))
    if tuple(authorities.get("levels", [])) != AUTHORITY_LEVELS:
        problems.append("authorities.json levels drifted from the model")
    separation = load_json(SEPARATION_PATH)
    committed_pairs = {tuple(p) for p in separation.get(
        "incompatiblePairs", [])}
    if committed_pairs != {tuple(p) for p in INCOMPATIBLE_ROLES}:
        problems.append("separation-policy.json incompatiblePairs drifted "
                        "from the model")
    policies = load_json(POLICIES_PATH)
    if tuple(policies.get("dimensions", [])) != THRESHOLD_DIMENSIONS:
        problems.append("threshold-policies.json dimensions drifted from "
                        "the model")
    return problems


def _record_problems() -> list[str]:
    problems: list[str] = []
    try:
        governance = _load_governance()
    except BoundaryViolation as error:
        return [str(error)]
    subject_digests = _phase9().subject_digests(load_json(PHASE9_LEDGER))
    for record in governance["assignments"]:
        problems += ["assignment: %s" % p for p in
                     validate_assignment(record)]
    for record in governance["overlapDecisions"]:
        problems += ["overlap: %s" % p
                     for p in validate_overlap_decision(record)]
    for record in governance["policies"]:
        problems += ["policy: %s" % p for p in validate_policy(
            record, governance["assignments"])]
    problems += ["policy: %s" % p
                 for p in policy_chain_problems(governance["policies"])]
    severities = _known_finding_severities(load_json(PHASE11_REGISTER),
                                           load_json(PHASE12_REGISTER))
    for record in governance["risks"]:
        problems += ["risk: %s" % p for p in validate_risk_acceptance(
            record, governance["assignments"], subject_digests, severities)]
    for record in governance["revocations"]:
        problems += ["revocation: %s" % p for p in validate_revocation(
            record, governance["authorizations"],
            governance["assignments"], subject_digests)]
    for record in governance["resolutions"]:
        problems += ["resolution: %s" % p
                     for p in validate_conflict_resolution(
                         record, governance["assignments"])]
    return problems


def verify_fixtures() -> list[str]:
    """Every fixture is structurally marked; no committed governance record
    carries a fixture marker."""
    issues = []
    if FIXTURES_DIR.is_dir():
        for path in sorted(FIXTURES_DIR.glob("*.json")):
            try:
                record = load_json(path)
            except json.JSONDecodeError:
                issues.append("%s: unparseable fixture" % path.name)
                continue
            if not (record.get("fixtureClass") == FIXTURE_MARKER
                    and record.get("fixture") is True
                    and record.get("test_fixture_only") is True):
                issues.append(
                    "%s: a fixture must carry fixtureClass %s, fixture: "
                    "true, and test_fixture_only: true — anything less is "
                    "structurally indistinguishable from a record"
                    % (path.name, FIXTURE_MARKER))
    for path in (AUTHORITIES_PATH, ASSIGNMENTS_PATH, SEPARATION_PATH,
                 POLICIES_PATH, RECLASSIFICATION_PATH, RISKS_PATH,
                 AUTHORIZATIONS_PATH, REVOCATIONS_PATH, RESOLUTIONS_PATH):
        try:
            container = load_json(path)
        except (OSError, json.JSONDecodeError):
            issues.append("%s is unreadable" % path.name)
            continue
        if is_fixture(container):
            issues.append("%s carries a fixture marker" % path.name)
        for record in container.get("records", []):
            if is_fixture(record):
                issues.append("%s holds a record with a fixture marker; a "
                              "fixture is never a decision" % path.name)
    return issues


def verify_all() -> list[str]:
    issues: list[str] = []
    for path in (AUTHORITIES_PATH, ASSIGNMENTS_PATH, SEPARATION_PATH,
                 POLICIES_PATH, RECLASSIFICATION_PATH, RISKS_PATH,
                 AUTHORIZATIONS_PATH, REVOCATIONS_PATH, RESOLUTIONS_PATH):
        if not path.is_file():
            issues.append("governance: %s is missing"
                          % path.relative_to(PHASE13).as_posix())
    if issues:
        return issues
    issues += ["governance: %s" % p for p in _governance_shape_problems()]
    issues += ["records: %s" % p for p in _record_problems()]
    issues += ["fixtures: %s" % p for p in verify_fixtures()]
    _, blocking_problems = blocking_from_disk()
    issues += ["blocking: %s" % p for p in blocking_problems]
    if not issues:
        derived, problems = sync_status(write=False)
        issues += ["status: %s" % p for p in problems]
        if not problems:
            if STATUS_PATH.is_file():
                if load_json(STATUS_PATH) != derived:
                    issues.append(
                        "status: committed authorization-status.json does "
                        "not reproduce from its inputs; run sync and "
                        "review the diff")
            else:
                issues.append("status: authorization-status.json is "
                              "absent; run sync")
    return issues


# ---------------------------------------------------------- record append

_RECORD_REGISTRIES = {
    "assignment": (ASSIGNMENTS_PATH, "assignmentId"),
    "policy": (POLICIES_PATH, "policy_id"),
    "risk-acceptance": (RISKS_PATH, "risk_id"),
    "authorization": (AUTHORIZATIONS_PATH, "authorization_id"),
    "revocation": (REVOCATIONS_PATH, "revocation_id"),
    "conflict-resolution": (RESOLUTIONS_PATH, "resolutionId"),
    "reclassification": (RECLASSIFICATION_PATH, "decisionId"),
    "overlap-decision": (SEPARATION_PATH, "decisionId"),
}


def _validator_for(kind: str, as_of: str | None):
    """The full-context validator for one record kind, over the committed
    registries as they stand."""
    governance = _load_governance()
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    subject_digests = _phase9().subject_digests(ledger)
    severities = _known_finding_severities(load_json(PHASE11_REGISTER),
                                           load_json(PHASE12_REGISTER))
    if kind == "assignment":
        return validate_assignment
    if kind == "overlap-decision":
        return validate_overlap_decision
    if kind == "policy":
        return lambda r: validate_policy(r, governance["assignments"])
    if kind == "risk-acceptance":
        return lambda r: validate_risk_acceptance(
            r, governance["assignments"], subject_digests, severities)
    if kind == "revocation":
        return lambda r: validate_revocation(
            r, governance["authorizations"], governance["assignments"],
            subject_digests)
    if kind == "conflict-resolution":
        return lambda r: validate_conflict_resolution(
            r, governance["assignments"])
    if kind == "reclassification":
        return lambda r: validate_reclassification(
            r, governance["assignments"],
            ledger["subjectArtifact"]["identifier"])
    if kind == "authorization":
        blocking, problems = blocking_from_disk()
        if problems:
            raise BoundaryViolation("blocking registry not clean: %s"
                                    % "; ".join(problems))
        return lambda r: validate_authorization(
            r, ledger=ledger, ledger_sha256=_sha256(ledger_bytes),
            intake_root=PHASE9_LEDGER.parent,
            assignments=governance["assignments"],
            overlap_decisions=governance["overlapDecisions"],
            policies=governance["policies"], risks=governance["risks"],
            blocking=blocking,
            alpha_register=load_json(PHASE12_REGISTER),
            security_register=load_json(PHASE11_REGISTER), as_of=as_of)
    raise BoundaryViolation("unknown record kind %r" % kind)


def append_record(kind: str, record: dict,
                  as_of: str | None = None) -> dict:
    """Validate one record against everything, seal it, append it. This is
    the only append mechanism for the Phase 13 registries; a hand edit
    breaks a seal and fails every subsequent run closed."""
    if kind not in _RECORD_REGISTRIES:
        raise BoundaryViolation("unknown record kind %r" % kind)
    _refuse_fixture(record, "record-%s" % kind)
    path, id_key = _RECORD_REGISTRIES[kind]
    validator = _validator_for(kind, as_of)
    issues = validator(record)
    if issues:
        raise BoundaryViolation("REFUSED %s: %s" % (kind, "; ".join(issues)))
    container = load_json(path)
    records = sealed_records(container, id_key, path.name)
    if any(r.get(id_key) == record.get(id_key) for r in records):
        raise BoundaryViolation(
            "%s %s already exists; records are immutable — a change is a "
            "new record with a new identifier" % (kind, record.get(id_key)))
    sealed = dict(record)
    sealed["seal"] = seal_record(sealed)
    container["records"] = records + [sealed]
    dump_json(path, container)
    return sealed


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 13 release authority operations verify clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_sync(args) -> int:
    derived, problems = sync_status(write=True, as_of=args.as_of)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("authorization-status.json derived; state %s; candidate "
          "decision %s; next action: %s"
          % (derived["authorizationState"], derived["candidateDecision"],
             derived["nextAction"]))
    return 0


def _cmd_build_blocking(_args) -> int:
    rebuilt, problems = blocking_from_disk()
    for problem in problems:
        if "changed under the committed pin" in problem:
            print("REFUSED: %s" % problem)
            return 2
    dump_json(BLOCKING_PATH, rebuilt)
    print("blocking-conditions.json derived; %d conditions, all classes "
          "recorded" % len(rebuilt["conditions"]))
    return 0


def _cmd_validate_authorization(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    try:
        issues = _validator_for("authorization", args.as_of)(record)
    except BoundaryViolation as error:
        print(str(error))
        return 2
    if issues:
        for issue in issues:
            print(issue)
        return 2
    print("record validates (validation is not authorization; the "
          "decision belongs to the assigned release authority)")
    return 0


def _cmd_record(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    try:
        sealed = append_record(args.kind, record,
                               getattr(args, "as_of", None))
    except BoundaryViolation as error:
        print(str(error))
        return 2
    _, id_key = _RECORD_REGISTRIES[args.kind]
    print("%s %s recorded and sealed (%s…)"
          % (args.kind, sealed.get(id_key), sealed["seal"][:12]))
    print("run sync to re-derive authorization-status.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser(
        "verify", help="governance shape, seals, records, blocking pin, "
                       "status reproducibility; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    sync = commands.add_parser(
        "sync", help="derive authorization-status.json from its inputs")
    sync.add_argument("--as-of", default=None,
                      help="ISO 8601 evaluation date, stated by the "
                           "operator (required once expiring records "
                           "exist)")
    sync.set_defaults(func=_cmd_sync)

    blk = commands.add_parser(
        "build-blocking", help="derive blocking-conditions.json from the "
                               "pinned Phase 8 source and the decision "
                               "record")
    blk.set_defaults(func=_cmd_build_blocking)

    val = commands.add_parser(
        "validate-authorization", help="check one authorization record "
                                       "against everything (analysis "
                                       "only; appends nothing)")
    val.add_argument("record")
    val.add_argument("--as-of", default=None)
    val.set_defaults(func=_cmd_validate_authorization)

    rec = commands.add_parser(
        "record", help="validate, seal, and append one governance record")
    rec.add_argument("kind", choices=sorted(_RECORD_REGISTRIES))
    rec.add_argument("record")
    rec.add_argument("--as-of", default=None)
    rec.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

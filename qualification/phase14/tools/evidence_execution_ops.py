#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 14 external-evidence execution and decision rehearsal.

Phases 9-13 built the pipeline external evidence will one day travel:
the intake boundary, candidate operations, security-review
reconciliation, Alpha evidence operations, and release-authority
governance. None of it has ever carried a real record, because no real
record exists. Phase 14 proves the pipeline works — end to end, against
TEST_FIXTURE_ONLY material, in scratch universes — without pretending
any evidence arrived. The principle, mechanically enforced everywhere:

    A passing test of this machinery is not evidence about the subject
    artifact. The machinery being ready is the result; the evidence is
    still external.

What this module provides:

* an evidence router (Track A) — one classification per candidate
  record, fail-closed: ten evidence classes, each with its owning
  workstream, destination (Phase 9 intake source or Phase 13 registry),
  and validator; an unknown or ambiguous class refuses instead of
  becoming generic evidence;
* the evidence-cut contract (Track B) — a sealed, deterministic,
  reproducible identification of everything a decision may rely on
  (ledger bytes, intake IDs, graph, registers, policy versions,
  authority records, revocation state, operator-stated as-of); the same
  immutable inputs derive byte-identical cuts, evidence arriving after
  a cut is detected rather than silently absorbed, and a later decision
  supersedes an earlier one without rewriting it;
* one conflict policy (Track C) — composed from Phase 11 and Phase 13:
  nothing is averaged, "more PASS than FAIL" does not exist, the
  effective state is never more favorable because a conflict exists,
  and hardware results stay per-machine, per-dimension forever;
* rehearsal surfaces for the four external workstreams (Tracks D-G) —
  the real Phase 9 registration code, the real Phase 11 reconciliation,
  the real Phase 12 register derivation, and the real Phase 13
  validators, exercised in scratch intake trees over fixture records;
* a decision assembler (Track H) — gathers artifact identity, security
  state, hardware state, signing state, approval state, sufficiency,
  blocking conditions, authority, risks, revocations, and the evidence
  cut, then derives the candidate state through Phase 13's own ladder;
  it assembles, it never invents, and the real candidate's state comes
  out exactly as Phase 13 committed it;
* time semantics (Track I) — expiry and revocation between cuts,
  future-dated evidence, observation times that contradict intake
  ordering, ambiguous time bases, and the mandatory --as-of; every
  undeterminable time fails closed;
* the rehearsal matrix — ``qualification/phase14/MATRIX.json`` is
  derived by executing every scenario against scratch universes; every
  row is FIXTURE_DEMONSTRATION_ONLY, the real ledger is byte-compared
  before and after the run, and ``verify`` re-executes the whole matrix
  and refuses drift.

Everything here reads the real Phase 9 ledger, Phase 10 graph, Phase
11/12 registers, and Phase 13 registries; nothing here writes any of
them, ever. Scratch universes live in temporary directories and die
with the run.

Determinism: no clocks. Every rehearsal date is a fixed constant;
evaluation dates are operator-stated; the commit is the tamper-evident
time.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE14 = ROOT / "qualification" / "phase14"
FIXTURES_DIR = PHASE14 / "fixtures"
MATRIX_PATH = PHASE14 / "MATRIX.json"

PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE9_DECISION = (ROOT / "qualification" / "phase9" / "decision"
                   / "alpha-release-decision.json")
PHASE10_TOOL = (ROOT / "qualification" / "phase10" / "tools"
                / "candidate_ops.py")
PHASE10_GRAPH = (ROOT / "qualification" / "phase10" / "artifacts"
                 / "artifact-graph.json")
PHASE11_TOOL = (ROOT / "qualification" / "phase11" / "tools"
                / "security_review_ops.py")
PHASE11_BASELINE = (ROOT / "qualification" / "phase11" / "security-review"
                    / "FINDINGS_BASELINE.json")
PHASE11_REGISTER = ROOT / "qualification" / "phase11" / "security-findings.json"
PHASE12_TOOL = ROOT / "qualification" / "phase12" / "tools" / "alpha_ops.py"
PHASE12_REGISTER = ROOT / "qualification" / "phase12" / "alpha-findings.json"
PHASE12_POLICY = ROOT / "qualification" / "phase12" / "sufficiency-policy.json"
PHASE13_TOOL = (ROOT / "qualification" / "phase13" / "tools"
                / "release_authority_ops.py")
PHASE13_STATUS = (ROOT / "qualification" / "phase13"
                  / "authorization-status.json")
PHASE13_BLOCKING = (ROOT / "qualification" / "phase13" / "blocking"
                    / "blocking-conditions.json")

FIXTURES10 = ROOT / "qualification" / "phase10" / "fixtures"
FIXTURES11 = ROOT / "qualification" / "phase11" / "fixtures"
FIXTURES12 = ROOT / "qualification" / "phase12" / "fixtures"
FIXTURES13 = ROOT / "qualification" / "phase13" / "fixtures"

#: The real files every rehearsal must leave byte-identical. Never an
#: emptiness assertion: the comparison is bytes-before against
#: bytes-after, so the guarantee survives the day real evidence arrives.
REAL_IMMUTABLE_INPUTS = (
    PHASE9_LEDGER, PHASE9_DECISION, PHASE10_GRAPH, PHASE11_BASELINE,
    PHASE11_REGISTER, PHASE12_REGISTER, PHASE12_POLICY, PHASE13_STATUS,
    PHASE13_BLOCKING,
    ROOT / "qualification" / "phase13" / "governance" / "authorities.json",
    ROOT / "qualification" / "phase13" / "governance" / "assignments.json",
    ROOT / "qualification" / "phase13" / "governance"
         / "separation-policy.json",
    ROOT / "qualification" / "phase13" / "sufficiency"
         / "threshold-policies.json",
    ROOT / "qualification" / "phase13" / "blocking"
         / "reclassification-decisions.json",
    ROOT / "qualification" / "phase13" / "decisions" / "risk-acceptances.json",
    ROOT / "qualification" / "phase13" / "decisions" / "authorizations.json",
    ROOT / "qualification" / "phase13" / "decisions" / "revocations.json",
    ROOT / "qualification" / "phase13" / "decisions"
         / "conflict-resolutions.json",
)

#: The Phase 14 documents verify requires to exist. The tree is a
#: package: machinery without its contract documents is unreviewable.
PACKAGE_FILES = (
    "README.md", "EXTERNAL_EVIDENCE_EXECUTION.md", "EVIDENCE_ROUTING.md",
    "EVIDENCE_CUT_CONTRACT.md", "EXPIRY_AND_TIME.md", "CONFLICT_POLICY.md",
    "DECISION_ASSEMBLY.md", "FAILURE_MODES.md", "FIXTURE_BOUNDARY.md",
    "MATRIX.json",
)

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: Every rehearsal happens on these fixed dates. No clock is ever read.
REHEARSAL_DATE = "2026-08-19"
CUT_A_DATE = "2026-08-19"
CUT_B_DATE = "2026-12-01"

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}")


class BoundaryViolation(ValueError):
    """A refused route, cut, derivation, rehearsal, or record."""


# ---------------------------------------------------------------- shared I/O

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


_MODULE_CACHE: dict[str, object] = {}


def _load_module(name: str, path: Path):
    module = _MODULE_CACHE.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE_CACHE[name] = module
    return module


def _phase9():
    return _load_module("phase9_intake_for_phase14", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase14", PHASE10_TOOL)


def _phase11():
    return _load_module("phase11_ops_for_phase14", PHASE11_TOOL)


def _phase12():
    return _load_module("phase12_ops_for_phase14", PHASE12_TOOL)


def _phase13():
    return _load_module("phase13_ops_for_phase14", PHASE13_TOOL)


def is_fixture(record) -> bool:
    """Any one of the three markers makes a record a fixture — the
    Phase 13 rule, unchanged."""
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


def _date(value):
    import datetime
    text = str(value)
    if not ISO_DATE.fullmatch(text):
        raise BoundaryViolation(
            "%r is not an exact ISO 8601 calendar date" % text)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as error:
        raise BoundaryViolation(
            "%r is not a valid ISO 8601 calendar date: %s" %
            (text, error)) from error


def seal_record(record: dict) -> str:
    """The Phase 9/13 seal algorithm, verbatim: sha256 over canonical
    JSON minus the seal. The guard suite asserts the three spellings
    (intake.seal_entry, ops13.seal_record, this) never drift."""
    unsealed = {k: v for k, v in record.items() if k != "seal"}
    canonical = json.dumps(unsealed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fixture(name: str, root: Path = FIXTURES_DIR) -> dict:
    return load_json(root / name)


def _inner(name: str, root: Path = FIXTURES_DIR, key: str = "record") -> dict:
    """The wrapped record inside a fixture file, deep-copied. The wrapper
    (which carries the markers) never travels; the inner record is what a
    real submitter would send, and scratch registrations use exactly it."""
    return copy.deepcopy(_fixture(name, root)[key])


# ------------------------------------------------------ evidence router (§A)

#: The ten supported external evidence classes. Each names the workstream
#: owner (the authority whose act the evidence is), the destination (the
#: only door of that kind), and the validator that must process it. A
#: class not in this table does not exist, and the router refuses it.
EVIDENCE_CLASSES = {
    "SECURITY_REVIEW": {
        "workstreamOwner": "AUTH-SECURITY-REVIEWER",
        "routeKind": "PHASE9_INTAKE",
        "destination": "security-review",
        "validator": "qualification/phase9/tools/intake.py validate_record "
                     "+ qualification/phase11/security-review/"
                     "VERIFY_SUBMISSION.py validate_submission",
    },
    "HARDWARE_VALIDATION": {
        "workstreamOwner": "AUTH-HARDWARE",
        "routeKind": "PHASE9_INTAKE",
        "destination": "hardware",
        "validator": "qualification/phase9/tools/intake.py validate_record "
                     "+ qualification/phase14/tools/"
                     "evidence_execution_ops.py hardware_submission_review",
    },
    "SIGNING": {
        "workstreamOwner": "AUTH-KEY",
        "routeKind": "PHASE9_INTAKE",
        "destination": "signing",
        "validator": "qualification/phase9/tools/intake.py validate_record",
    },
    "SECOND_APPROVAL": {
        "workstreamOwner": "AUTH-SECOND-APPROVER",
        "routeKind": "PHASE9_INTAKE",
        "destination": "second-approval",
        "validator": "qualification/phase9/tools/intake.py validate_record",
    },
    "ALPHA_TESTER_REPORT": {
        "workstreamOwner": "AUTH-ALPHA-PROGRAM",
        "routeKind": "PHASE9_INTAKE",
        "destination": "alpha-feedback",
        "validator": "qualification/phase9/tools/intake.py validate_record "
                     "+ qualification/phase12/alpha/VERIFY_TESTER_REPORT.py "
                     "validate_report",
    },
    "AUTHORITY_ASSIGNMENT": {
        "workstreamOwner": "ORGANIZATION",
        "routeKind": "PHASE13_REGISTRY",
        "destination": "assignment",
        "validator": "qualification/phase13/tools/release_authority_ops.py "
                     "validate_assignment (via record assignment)",
    },
    "SUFFICIENCY_POLICY": {
        "workstreamOwner": "AUTH-ALPHA-PROGRAM",
        "routeKind": "PHASE13_REGISTRY",
        "destination": "policy",
        "validator": "qualification/phase13/tools/release_authority_ops.py "
                     "validate_policy (via record policy)",
    },
    "RISK_ACCEPTANCE": {
        "workstreamOwner": "AUTH-SECURITY-OWNER",
        "routeKind": "PHASE13_REGISTRY",
        "destination": "risk-acceptance",
        "validator": "qualification/phase13/tools/release_authority_ops.py "
                     "validate_risk_acceptance (via record risk-acceptance)",
    },
    "AUTHORIZATION": {
        "workstreamOwner": "AUTH-RELEASE",
        "routeKind": "PHASE13_REGISTRY",
        "destination": "authorization",
        "validator": "qualification/phase13/tools/release_authority_ops.py "
                     "validate_authorization (via record authorization)",
    },
    "REVOCATION": {
        "workstreamOwner": "AUTH-RELEASE",
        "routeKind": "PHASE13_REGISTRY",
        "destination": "revocation",
        "validator": "qualification/phase13/tools/release_authority_ops.py "
                     "validate_revocation (via record revocation)",
    },
}

#: Structural fingerprints, one per class. Every field group must be
#: present for a match; a tuple inside the group is a set of accepted
#: spellings (the Phase 11/12 contracts carry both layers). Two classes
#: matching at once is ambiguity, and ambiguity refuses.
_CLASS_FINGERPRINTS = (
    ("SECURITY_REVIEW", (("reviewer", "reviewer_id"), "findings",
                         ("disposition", "overall_assessment"))),
    ("HARDWARE_VALIDATION", ("hwId", "machine", "results")),
    ("SIGNING", ("signatureIdentifier", "signerIdentity")),
    ("SECOND_APPROVAL", ("firstApprover", "secondApprover")),
    ("ALPHA_TESTER_REPORT", (("testerId", "tester_id"),
                             ("report_type", "journey"))),
    ("AUTHORITY_ASSIGNMENT", ("assignmentId", "authorityId")),
    ("SUFFICIENCY_POLICY", ("policy_id", "thresholds")),
    ("RISK_ACCEPTANCE", ("risk_id", "finding_ids")),
    ("AUTHORIZATION", ("authorization_id", "decision")),
    ("REVOCATION", ("revocation_id", "target_authorization")),
)

ROUTER_DISPOSITIONS = (
    "ACCEPTABLE_FOR_INTAKE", "INCOMPLETE", "REJECTED", "DOES_NOT_APPLY",
    "REQUIRES_HUMAN_DECISION", "TEST_FIXTURE_ONLY",
)

#: Phase 9 stored statuses -> router dispositions, exhaustively. A status
#: outside this table refuses rather than becoming generic evidence.
_INTAKE_STATUS_DISPOSITION = {
    "ACCEPTED": "ACCEPTABLE_FOR_INTAKE",
    "INCOMPLETE": "INCOMPLETE",
    "REJECTED": "REJECTED",
    "ARTIFACT_MISMATCH": "DOES_NOT_APPLY",
}

#: Required-field tuples for the governance classes, imported from the
#: Phase 13 module at call time so the two can never drift.
_GOVERNANCE_FIELDS = {
    "AUTHORITY_ASSIGNMENT": ("ASSIGNMENT_FIELDS", ()),
    "SUFFICIENCY_POLICY": ("POLICY_FIELDS", ()),
    "RISK_ACCEPTANCE": ("RISK_FIELDS", ("finding_ids",)),
    "AUTHORIZATION": ("AUTHORIZATION_FIELDS",
                      ("blocking_conditions", "accepted_risks",
                       "policy_versions")),
    "REVOCATION": ("REVOCATION_FIELDS", ()),
}


def classify_evidence(record) -> str:
    """Exactly one evidence class, or a refusal. The router fails closed:
    an unknown class must not silently become generic evidence, and a
    record matching two classes is saying two things, which is saying
    nothing."""
    if not isinstance(record, dict):
        raise BoundaryViolation(
            "unroutable: a candidate evidence record must be a JSON object")
    matches = []
    for class_name, groups in _CLASS_FINGERPRINTS:
        satisfied = True
        for group in groups:
            names = group if isinstance(group, tuple) else (group,)
            if not any(name in record for name in names):
                satisfied = False
                break
        if satisfied:
            matches.append(class_name)
    if len(matches) > 1:
        raise BoundaryViolation(
            "ambiguous evidence record: it carries the fingerprints of %s "
            "at once; a record saying two things is saying nothing, and "
            "the router refuses instead of guessing" % " and ".join(matches))
    if not matches:
        raise BoundaryViolation(
            "unroutable evidence record: no supported evidence class "
            "matches its structure; unknown classes never become generic "
            "evidence — the supported classes are %s"
            % ", ".join(sorted(EVIDENCE_CLASSES)))
    return matches[0]


def _claimed_digests(class_name: str, record: dict) -> list[str]:
    """Every artifact digest the record claims, normalized. Empty means
    the record binds to nothing by itself."""
    digests = []
    if class_name == "SECURITY_REVIEW":
        value = record.get("artifact") or record.get("artifactDigest") \
            or record.get("artifact_digest")
        if isinstance(value, dict):
            value = value.get("digest")
        if value:
            digests.append(value)
    elif class_name in ("HARDWARE_VALIDATION", "SIGNING",
                        "ALPHA_TESTER_REPORT"):
        value = record.get("artifactDigest")
        if value:
            digests.append(value)
    elif class_name == "SECOND_APPROVAL":
        for who in ("firstApprover", "secondApprover"):
            value = (record.get(who) or {}).get("recomputedDigest")
            if value:
                digests.append(value)
    else:
        value = record.get("artifact_digest")
        if value:
            digests.append(value)
    return [_normalize_digest(d) for d in digests]


def route_evidence(record, subject_digests: set[str]) -> dict:
    """The routing decision for one candidate evidence record.

    The fixture check runs first and is terminal: a fixture routes
    nowhere, whatever it looks like. Everything else resolves exactly one
    class, one owner, one destination, one validator, one artifact claim,
    and one disposition — fail-closed at every step.
    """
    if is_fixture(record):
        try:
            class_name = classify_evidence(
                {k: v for k, v in record.items()
                 if k not in ("fixture", "fixtureClass",
                              "test_fixture_only")})
        except BoundaryViolation:
            class_name = None
        return {
            "evidenceClass": class_name,
            "workstreamOwner": None,
            "routeKind": None,
            "destination": "NONE — a fixture never routes to evidence",
            "validator": None,
            "claimedArtifact": sorted(set(
                _claimed_digests(class_name, record))) if class_name else [],
            "binding": "NOT_EXAMINED",
            "disposition": "TEST_FIXTURE_ONLY",
            "dispositionBasis": "the record carries a fixture marker; a "
                                "fixture is never evidence, and the router "
                                "refuses to forward it anywhere",
        }

    class_name = classify_evidence(record)
    route = EVIDENCE_CLASSES[class_name]
    claimed = sorted(set(_claimed_digests(class_name, record)))
    foreign = [d for d in claimed if d not in subject_digests]
    if not claimed:
        binding = "UNBOUND" if class_name == "ALPHA_TESTER_REPORT" \
            else "NOT_ARTIFACT_BOUND" \
            if class_name == "AUTHORITY_ASSIGNMENT" else "MISSING"
    elif foreign:
        binding = "MISMATCH"
    else:
        binding = "BOUND"

    if route["routeKind"] == "PHASE9_INTAKE":
        verdict = _phase9().validate_record(
            route["destination"], record, subject_digests)
        disposition = _INTAKE_STATUS_DISPOSITION.get(verdict["status"])
        if disposition is None:
            raise BoundaryViolation(
                "the intake validator resolved status %r, which the router "
                "has no disposition for; refusing rather than inventing "
                "one" % verdict["status"])
        basis = verdict["statusReason"] or (
            "the record answers the six intake questions for source %s"
            % route["destination"])
    else:
        fields_name, list_fields = _GOVERNANCE_FIELDS[class_name]
        ops13 = _phase13()
        missing = ops13._missing(record, getattr(ops13, fields_name),
                                 list_fields=tuple(list_fields))
        if class_name == "AUTHORITY_ASSIGNMENT":
            wrong_artifact = False
        else:
            wrong_artifact = bool(foreign)
        if wrong_artifact:
            disposition = "DOES_NOT_APPLY"
            basis = ("the record binds to %s, not the subject artifact; a "
                     "governance record for other bytes decides nothing "
                     "here and never transfers" % ", ".join(foreign))
        elif missing:
            disposition = "INCOMPLETE"
            basis = "missing: %s" % ", ".join(sorted(missing))
        else:
            disposition = "REQUIRES_HUMAN_DECISION"
            basis = ("recording this is an authority act: the operator "
                     "appends it through release_authority_ops.py record "
                     "%s, where it validates against the sealed "
                     "assignment registry — the router prepares, it never "
                     "decides" % route["destination"])

    return {
        "evidenceClass": class_name,
        "workstreamOwner": route["workstreamOwner"],
        "routeKind": route["routeKind"],
        "destination": route["destination"],
        "validator": route["validator"],
        "claimedArtifact": claimed,
        "binding": binding,
        "disposition": disposition,
        "dispositionBasis": basis,
    }


# ------------------------------------------------------- evidence cuts (§B)

#: Record kinds whose instances may carry an expiry. The moment one such
#: record exists anywhere in a decision's inputs, an operator-stated
#: as-of date becomes mandatory — silence never keeps anything valid.
def expiring_record_names(assignments: list[dict], risks: list[dict],
                          authorizations: list[dict]) -> list[str]:
    names = []
    for record in assignments:
        if record.get("expires_at"):
            names.append(record.get("assignmentId", "<assignment>"))
    for record in risks:
        if record.get("expires_at"):
            names.append(record.get("risk_id", "<risk>"))
    for record in authorizations:
        if record.get("expires_at"):
            names.append(record.get("authorization_id", "<authorization>"))
    return sorted(names)


ASSIGNMENT_REVOCATION_FIELDS = ("revocationId", "targetAssignment",
                                "reason", "authority", "timestamp")


def validate_assignment_revocation(record: dict,
                                   assignments: list[dict]) -> list[str]:
    """Phase 14's fixture-universe assignment-revocation shape. There is
    deliberately no real registry behind this: introducing one is an
    owner decision, and until it exists these records evaluate only
    inside isolated universes."""
    issues = ["assignment revocation missing %s" % f
              for f in ASSIGNMENT_REVOCATION_FIELDS if not record.get(f)]
    if is_fixture(record):
        issues.append("a fixture wrapper is never a revocation record")
    target = record.get("targetAssignment")
    if target and not any(a.get("assignmentId") == target
                          for a in assignments):
        issues.append("target assignment %r does not exist; a revocation "
                      "of nothing revokes nothing" % target)
    timestamp = record.get("timestamp")
    if timestamp:
        try:
            _date(timestamp)
        except BoundaryViolation:
            issues.append("timestamp must be an exact, valid ISO 8601 "
                          "calendar date")
    return issues


def standing_assignments(assignments: list[dict], as_of: str | None,
                         assignment_revocations: list[dict] = ()) -> list[dict]:
    """The assignments that still confer authority at the evaluation
    date. Records are never edited or dropped from their registry; this
    filters a *view*: an assignment past its stated expiry, or revoked at
    or before the evaluation date, contributes no authority to decisions
    made at this cut. Earlier cuts, evaluated at earlier dates, still see
    it standing — history is evaluated, never rewritten."""
    revocations = list(assignment_revocations or ())
    for record in revocations:
        issues = validate_assignment_revocation(record, assignments)
        if issues:
            raise BoundaryViolation("assignment revocation invalid: %s"
                                    % "; ".join(issues))
    expiring = [a for a in assignments if a.get("expires_at")]
    if (expiring or revocations) and as_of is None:
        raise BoundaryViolation(
            "assignment authority cannot be evaluated without an "
            "operator-stated evaluation date once an expiring or revoked "
            "assignment exists; silence does not keep authority standing")
    revoked_targets = {
        r["targetAssignment"] for r in revocations
        if as_of is not None and _date(r["timestamp"]) <= _date(as_of)}
    standing = []
    for record in assignments:
        if record.get("assignmentId") in revoked_targets:
            continue
        expires = record.get("expires_at")
        if expires and _date(as_of) > _date(expires):
            continue
        standing.append(record)
    return standing


def assignment_state(record: dict, as_of: str | None,
                     assignment_revocations: list[dict] = ()) -> str:
    """STANDING, EXPIRED, or REVOKED for one assignment — derived."""
    for revocation in assignment_revocations or ():
        if revocation.get("targetAssignment") == record.get("assignmentId"):
            if as_of is None or _date(revocation["timestamp"]) <= _date(as_of):
                return "REVOKED"
    if not record.get("expires_at"):
        return "STANDING"
    if as_of is None:
        raise BoundaryViolation(
            "an expiring assignment cannot be evaluated without an "
            "operator-stated evaluation date")
    return "EXPIRED" if _date(as_of) > _date(record["expires_at"]) \
        else "STANDING"


def build_evidence_cut(*, ledger_bytes: bytes, graph_bytes: bytes,
                       security_register_bytes: bytes,
                       alpha_register_bytes: bytes,
                       assignments: list[dict], policies: list[dict],
                       risks: list[dict], authorizations: list[dict],
                       revocations: list[dict], resolutions: list[dict],
                       assignment_revocations: list[dict] = (),
                       as_of: str | None = None) -> dict:
    """One sealed evidence cut: everything a decision may rely on,
    identified by content, reproducible byte-for-byte from the same
    immutable inputs.

    The cut refuses to exist without an as-of date the moment any input
    record carries an expiry — a decision that cannot say *when* it
    evaluated expiring records has not evaluated them.
    """
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    ops13 = _phase13()
    expiring = expiring_record_names(assignments, risks, authorizations)
    if expiring and as_of is None:
        raise BoundaryViolation(
            "--as-of is mandatory once an expiring record exists (%s); a "
            "cut without an evaluation date cannot answer what stood at "
            "the cut" % ", ".join(expiring))
    if as_of is not None:
        try:
            _date(as_of)
        except BoundaryViolation as error:
            raise BoundaryViolation(
                "as-of must be an exact, valid ISO 8601 calendar date: %s"
                % error) from error

    intake = _phase9()
    effective = intake.effective_statuses(ledger)
    gate_eligible = sorted(
        e["intakeId"] for e in ledger.get("entries", [])
        if e.get("gateEligible")
        and effective.get(e["intakeId"]) == "ACCEPTED")

    authority_rows = []
    for record in assignments:
        authority_rows.append({
            "assignmentId": record.get("assignmentId"),
            "authorityId": record.get("authorityId"),
            "state": assignment_state(record, as_of,
                                      assignment_revocations),
            "seal": record.get("seal") or seal_record(record),
        })
    risk_rows = []
    for record in risks:
        risk_rows.append({
            "riskId": record.get("risk_id"),
            "state": ops13.risk_acceptance_state(record, as_of)
            if record.get("expires_at") else "STANDING",
            "seal": record.get("seal") or seal_record(record),
        })
    authorization_rows = []
    for record in authorizations:
        state = record.get("decision")
        if state == "AUTHORIZED":
            state = ops13.authorization_state_of(record, revocations, as_of)
        authorization_rows.append({
            "authorizationId": record.get("authorization_id"),
            "state": state,
            "seal": record.get("seal") or seal_record(record),
        })

    cut = {
        "schemaVersion": 1,
        "subjectArtifact": ledger["subjectArtifact"]["identifier"],
        "artifactDigests": sorted(intake.subject_digests(ledger)),
        "ledgerSha256": _sha256(ledger_bytes),
        "ledgerEntries": len(ledger.get("entries", [])),
        "intakeIds": [e["intakeId"] for e in ledger.get("entries", [])],
        "gateEligibleAccepted": gate_eligible,
        "excludedLaterIntakeIds": [],
        "graphSha256": _sha256(graph_bytes),
        "securityRegisterSha256": _sha256(security_register_bytes),
        "alphaRegisterSha256": _sha256(alpha_register_bytes),
        "policyVersions": [
            {"policyId": p.get("policy_id"), "status": p.get("status"),
             "seal": p.get("seal") or seal_record(p)}
            for p in policies],
        "authorityRecords": authority_rows,
        "riskAcceptances": risk_rows,
        "authorizations": authorization_rows,
        "revocations": sorted(r.get("revocation_id") or ""
                              for r in revocations),
        "assignmentRevocations": sorted(r.get("revocationId") or ""
                                        for r in assignment_revocations
                                        or ()),
        "resolutions": sorted(r.get("resolutionId") or ""
                              for r in resolutions),
        "expiringRecords": expiring,
        "asOf": as_of,
        "timeBasis": "operator-stated evaluation date; no clock is read; "
                     "the commit is the tamper-evident time",
    }
    cut["seal"] = seal_record(cut)
    return cut


def verify_cut(cut: dict) -> list[str]:
    """Every reason this cut cannot be trusted; empty == intact."""
    issues = []
    if seal_record(cut) != cut.get("seal"):
        issues.append("the cut fails its seal; a sealed cut is immutable — "
                      "IMMUTABILITY FAIL, a change is a new cut, never an "
                      "edit")
    if cut.get("expiringRecords") and not cut.get("asOf"):
        issues.append("the cut names expiring records but no as-of date")
    return issues


def compare_cut_to_ledger(cut: dict, current_ledger_bytes: bytes) -> dict:
    """What changed since the cut was sealed. Evidence arriving after a
    cut is *detected and named*, never silently absorbed into the
    earlier decision; the earlier decision stands as recorded and a
    later decision over a later cut may supersede it."""
    current = json.loads(current_ledger_bytes.decode("utf-8"))
    current_ids = [e["intakeId"] for e in current.get("entries", [])]
    cut_ids = set(cut.get("intakeIds", []))
    post_cut = [i for i in current_ids if i not in cut_ids]
    missing = [i for i in cut.get("intakeIds", []) if i not in current_ids]
    return {
        "ledgerChanged": _sha256(current_ledger_bytes)
        != cut.get("ledgerSha256"),
        "postCutIntakeIds": post_cut,
        "missingIntakeIds": missing,
        "note": "post-cut evidence does not affect the decision sealed "
                "over this cut; a later decision over a later cut may "
                "supersede it, and a missing intake means the ledger was "
                "rewritten, which the intake guard refuses independently",
    }


def supersede_assembly(earlier: dict, later: dict) -> dict:
    """A later decision supersedes an earlier one without rewriting it.

    Returns a new record: the later assembly plus the supersession
    pointer. The earlier assembly is not modified — the caller's copy
    stays byte-identical, which the guard suite asserts."""
    for name, assembly in (("earlier", earlier), ("later", later)):
        cut = assembly.get("evidenceCut") or {}
        if not cut.get("seal"):
            raise BoundaryViolation(
                "the %s assembly carries no sealed evidence cut; an "
                "unsealed decision cannot participate in supersession"
                % name)
    if earlier["evidenceCut"]["seal"] == later["evidenceCut"]["seal"]:
        raise BoundaryViolation(
            "both assemblies seal the same evidence cut; re-running the "
            "same cut reproduces the same decision — supersession exists "
            "for a later cut, not for a rerun")
    superseding = copy.deepcopy(later)
    superseding["supersedes"] = {
        "cutSeal": earlier["evidenceCut"]["seal"],
        "authorizationState": earlier.get("authorizationState"),
        "note": "the earlier decision is superseded, not rewritten; its "
                "record stands exactly as sealed",
    }
    return superseding


# ------------------------------------------------- conflict handling (§C)

def most_blocking(observations: list[dict], domain: str) -> dict:
    """The single conflict policy, uniform across every workstream:
    Phase 13's classifier decides, nothing is averaged, and the
    effective state is never more favorable because a conflict exists.
    This is a thin composition — the authority table and the refusals
    live in Phase 13 and are not re-implemented here."""
    result = _phase13().classify_evidence_conflict(domain, observations)
    if result["conflictStatus"] == "CONFLICT":
        favorable = sorted(o["assessment"] for o in observations
                           if o.get("favorable") is True)
        for assessment in favorable:
            if assessment in result["effectiveAssessment"]:
                raise BoundaryViolation(
                    "the conflict resolved toward the favorable "
                    "assessment %r; the effective state must never become "
                    "more favorable because a conflict exists" % assessment)
    return result


def hardware_effective_state(machine_rows: list[dict]) -> dict:
    """Per-machine, per-dimension results, preserved forever.

    ``machine_rows`` is [{"hwId", "artifactBinding", "results"}, ...].
    Divergent machines are not averaged and not escalated — a machine
    result describes that machine. What this function will never emit is
    an aggregate support claim: no pre-existing policy defines one, and
    the repository does not invent policies.
    """
    intake = _phase9()
    dimensions: dict[str, dict[str, str]] = {}
    machines = []
    for row in machine_rows:
        hw_id = row.get("hwId")
        if not hw_id:
            raise BoundaryViolation(
                "a machine row without its machine identity moves "
                "nothing; hardware evidence preserves machine identity")
        machines.append(hw_id)
        for dimension, result in (row.get("results") or {}).items():
            if dimension not in intake.HARDWARE_DIMENSIONS:
                raise BoundaryViolation(
                    "unknown hardware dimension %r; the eighteen pinned "
                    "dimensions are the vocabulary, and native 3D versus "
                    "fallback 3D stay permanently separate" % dimension)
            status = result.get("status") if isinstance(result, dict) \
                else result
            dimensions.setdefault(dimension, {})[hw_id] = status
    per_dimension = []
    for dimension in sorted(dimensions):
        statuses = dimensions[dimension]
        per_dimension.append({
            "dimension": dimension,
            "byMachine": dict(sorted(statuses.items())),
            "divergent": len(set(statuses.values())) > 1,
            "claim": None,
        })
    return {
        "machines": sorted(machines),
        "perDimension": per_dimension,
        "aggregateClaim": {
            "claim": None,
            "basis": "no pre-existing policy defines an aggregate "
                     "hardware-support claim; per-machine, per-dimension "
                     "results are the only derivable statement — never "
                     "SUPPORTED ON PCS, never SUPPORTED ON ALL PCS",
        },
    }


def hardware_claims(effective: dict, claim: str) -> None:
    """The refusal, spelled out: asking this module for any finite-set
    aggregate claim raises. A support claim is a policy decision by the
    hardware validation owner, recorded through governance — not a
    derivation."""
    raise BoundaryViolation(
        "refusing to derive %r from %d machine result(s): no pre-existing "
        "policy defines an aggregate hardware-support claim, and a finite "
        "fixture set proves nothing about machines outside it"
        % (claim, len(effective.get("machines", []))))


# -------------------------------------------- hardware pipeline (§F)

def hardware_submission_review(record: dict,
                               subject_digests: set[str]) -> dict:
    """The Track F evaluator over one hardware protocol record: the
    Phase 9 six-question validation, machine identity preserved, the
    operator identity checked for PII leakage, and the 3D dimensions
    kept permanently separate."""
    _refuse_fixture(record, "hardware submission review")
    verdict = _phase9().validate_record("hardware", record, subject_digests)
    pii_problems = []
    for field in ("operator", "hwId"):
        value = str(record.get(field) or "")
        if EMAIL_RE.search(value):
            pii_problems.append(
                "%s contains an email address; the operator identity "
                "model is a role label or pseudonym, never contact "
                "details — PII is minimized before ingestion" % field)
    machine = record.get("machine") or {}
    results = record.get("results") or {}

    def _status(dimension: str):
        row = results.get(dimension)
        return row.get("status") if isinstance(row, dict) else row

    disposition = _INTAKE_STATUS_DISPOSITION.get(verdict["status"],
                                                 "REJECTED")
    if pii_problems and disposition == "ACCEPTABLE_FOR_INTAKE":
        disposition = "INCOMPLETE"
    return {
        "disposition": disposition,
        "statusReason": verdict["statusReason"],
        "binding": verdict["binding"],
        "machineIdentity": {
            "hwId": record.get("hwId"),
            "manufacturer": machine.get("manufacturer"),
            "model": machine.get("model"),
        },
        "renderModesSeparate": {
            "companion-3d-native": _status("companion-3d-native"),
            "companion-3d-fallback": _status("companion-3d-fallback"),
            "note": "two dimensions, permanently; a native PASS says "
                    "nothing about fallback and the reverse",
        },
        "piiProblems": pii_problems,
        "note": "one machine's protocol run; never a support claim for "
                "any other machine",
    }


# ---------------------------------------- signing and approval (§G)

def approval_ordering_problems(signing_record: dict,
                               approval_record: dict) -> list[str]:
    """An approval dated before the signing evidence it would approve
    cannot have verified that evidence. The flag is conservative: it
    derives REQUIRES_HUMAN_DECISION, never a favorable reading."""
    problems = []
    signed_on = signing_record.get("signingTimestamp")
    try:
        signed_date = _date(signed_on)
    except (BoundaryViolation, TypeError):
        problems.append("REQUIRES_HUMAN_DECISION: the signing evidence "
                        "carries no parseable timestamp; ordering cannot "
                        "be determined, and undeterminable time fails "
                        "closed")
        return problems
    for who in ("firstApprover", "secondApprover"):
        approver = approval_record.get(who) or {}
        approved_on = approver.get("date")
        try:
            approved_date = _date(approved_on)
        except (BoundaryViolation, TypeError):
            problems.append(
                "REQUIRES_HUMAN_DECISION: %s carries no parseable date; "
                "ordering cannot be determined" % who)
            continue
        if approved_date < signed_date:
            problems.append(
                "REQUIRES_HUMAN_DECISION: %s approved on %s, before the "
                "signing evidence dated %s existed; an approval cannot "
                "have verified evidence that postdates it"
                % (who, approved_on, signed_on))
    return problems


def subject_unsigned_problems() -> list[str]:
    """The durable facts, read from the real immutable inputs: the
    subject artifact is UNSIGNED and identified consistently everywhere.
    This is deliberately not an emptiness assertion about the ledger —
    the rehearsal guarantee that no test added signing evidence is the
    byte-comparison of the ledger before and after, which survives the
    day real evidence arrives."""
    problems = []
    ledger = load_json(PHASE9_LEDGER)
    subject = ledger["subjectArtifact"]
    if subject.get("signingStatus") != "UNSIGNED":
        problems.append(
            "the intake ledger's subject artifact reports signingStatus "
            "%r; Phase 14 must leave the subject UNSIGNED"
            % subject.get("signingStatus"))
    if not subject.get("frozen"):
        problems.append("the subject artifact is no longer marked frozen")
    graph = load_json(PHASE10_GRAPH)
    root_artifacts = [a for a in graph.get("artifacts", [])
                      if a.get("relationship") == "ROOT"]
    for artifact in root_artifacts:
        if artifact.get("artifact_id") != subject.get("identifier"):
            problems.append(
                "the graph ROOT %r is not the ledger subject %r"
                % (artifact.get("artifact_id"), subject.get("identifier")))
    return problems


# ------------------------------------------------- time semantics (§I)

def time_consistency_problems(*, record_dates: dict[str, str],
                              received_on: str | None,
                              revises_received_on: str | None = None
                              ) -> list[str]:
    """Every time-semantics problem with one record's claims; empty ==
    consistent. Undeterminable time fails closed: an unparseable date is
    a problem, a future-dated observation is a problem, a revision that
    predates its original is a problem, and two dates for one act that
    disagree are an ambiguous basis requiring a human decision."""
    problems = []
    parsed = {}
    for name, value in sorted(record_dates.items()):
        try:
            parsed[name] = _date(value)
        except (BoundaryViolation, TypeError):
            problems.append(
                "%s is not a parseable ISO 8601 date; time semantics "
                "cannot be determined, and undeterminable time fails "
                "closed" % name)
            continue
    if received_on is not None:
        try:
            received = _date(received_on)
        except (BoundaryViolation, TypeError):
            problems.append("the intake receipt date is unparseable")
        else:
            for name, value in sorted(parsed.items()):
                if value > received:
                    problems.append(
                        "REQUIRES_HUMAN_DECISION: %s (%s) postdates the "
                        "intake receipt (%s); evidence claiming to be "
                        "observed after it arrived conflicts with intake "
                        "ordering" % (name, value.isoformat(), received_on))
            if revises_received_on is not None:
                try:
                    original_received = _date(revises_received_on)
                except (BoundaryViolation, TypeError):
                    problems.append(
                        "the revised intake's original receipt date is "
                        "unparseable; revision ordering fails closed")
                else:
                    if received < original_received:
                        problems.append(
                            "REQUIRES_HUMAN_DECISION: the revision was "
                            "received %s, before the record it revises "
                            "(%s); a correction cannot precede what it "
                            "corrects" % (received_on,
                                          revises_received_on))
    if len(set(parsed.values())) > 1:
        problems.append(
            "REQUIRES_HUMAN_DECISION: the record states %s for the same "
            "act and they disagree — an ambiguous time basis is not "
            "resolved by choosing the convenient one"
            % " and ".join("%s=%s" % (n, v.isoformat())
                           for n, v in sorted(parsed.items())))
    return problems


# ------------------------------------------------ scratch universes

def empty_scratch_ledger() -> dict:
    """A zero-entry ledger carrying the real subject artifact identity,
    read from the real ledger and never written back. Every rehearsal
    universe starts here: same artifact, no evidence."""
    real = load_json(PHASE9_LEDGER)
    intake = _phase9()
    return {
        "schemaVersion": 1,
        "appendMechanism": real["appendMechanism"],
        "sources": list(intake.SOURCES),
        "statusVocabulary": list(intake.STATUSES),
        "sealAlgorithm": real["sealAlgorithm"],
        "subjectArtifact": copy.deepcopy(real["subjectArtifact"]),
        "entries": [],
    }


class RehearsalSpace:
    """One isolated rehearsal universe: its own intake tree, its own
    ledger, its own staging area, all under a temporary directory that
    dies with the run. The real intake tree is never touched — the only
    connection to reality is the subject artifact identity, copied
    read-only."""

    def __init__(self, base: Path):
        self.base = base
        self.intake_root = base / "qualification" / "phase9" / "intake"
        for source in _phase9().SOURCES:
            (self.intake_root / source).mkdir(parents=True)
        self.ledger_path = self.intake_root / "LEDGER.json"
        _phase9().dump_ledger(self.ledger_path, empty_scratch_ledger())
        self.staging = base / "staging"
        self.staging.mkdir()
        self._counter = 0

    def stage(self, payload) -> Path:
        self._counter += 1
        path = self.staging / ("record-%03d.json" % self._counter)
        path.write_text(json.dumps(payload, sort_keys=True),
                        encoding="utf-8", newline="\n")
        return path

    def register(self, source: str, record: dict,
                 received_on: str = REHEARSAL_DATE,
                 revises: str | None = None) -> dict:
        """Through the real Phase 9 registration code, into this
        universe's ledger. Intake behavior is real; the tree is not."""
        return _phase9().register(
            self.ledger_path, source, self.stage(record), [],
            received_on, "phase14 rehearsal", revises)

    def ledger(self) -> dict:
        return load_json(self.ledger_path)

    def ledger_bytes(self) -> bytes:
        return self.ledger_path.read_bytes()


def _seal13(record: dict) -> dict:
    sealed = dict(record)
    sealed["seal"] = seal_record(sealed)
    return sealed


def _fixture_assignments() -> list[dict]:
    return [_seal13(r) for r in
            _fixture("authority-assignments.json", FIXTURES13)["assignments"]]


def _cleared_blocking() -> dict:
    """The committed blocking registry with every condition FALSE on
    CLEARED — a constructed satisfied world for fixture universes. The
    committed registry itself is read-only and unchanged."""
    committed = load_json(PHASE13_BLOCKING)
    rows = []
    for row in committed["conditions"]:
        cleared = dict(row)
        cleared["state"] = "FALSE"
        cleared["evidenceCharacter"] = "CLEARED"
        rows.append(cleared)
    return {"conditions": rows}


def _empty_alpha_register() -> dict:
    return {"counts": {"acceptedReports": 0, "boundReports": 0},
            "reports": [], "findings": [], "hardwareObservations": [],
            "accessibilityObservations": [], "performance": {}}


def _sufficient_alpha_register() -> dict:
    return {
        "counts": {"acceptedReports": 1, "boundReports": 1},
        "reports": [{"classification": "ACCEPTED", "testerId": "T-001",
                     "reportType": "SUCCESS", "journey": "A"}],
        "findings": [],
        "hardwareObservations": [{"machineLabel": "machine-1"}],
        "accessibilityObservations": [],
        "performance": {},
    }


def _security_register(gate: str = "AWAITING_EXTERNAL_EVIDENCE") -> dict:
    """A minimal constructed security register: the gate status plus one
    BASELINE row so risk acceptances can resolve SEC-BL-001's severity.
    BASELINE rows are not open findings."""
    return {
        "securityGate": {"status": gate},
        "findings": [{"internal_id": "SEC-BL-001", "severity": "Critical",
                      "status": "BASELINE"}],
    }


def _register_full_evidence(space: RehearsalSpace) -> None:
    """Five gate-eligible ACCEPTED intakes through the real registration
    code, one per authorization-floor source — all fixture material, all
    inside the scratch universe."""
    checks = (
        ("security-review", _inner("review-valid-independent.json",
                                   FIXTURES11)),
        ("signing", _inner("signing-metadata-valid.json", FIXTURES10)),
        ("second-approval", _inner("second-approval-complete.json",
                                   FIXTURES13)),
        ("hardware", _inner("hardware-pass-machine.json", FIXTURES13)),
        ("alpha-feedback", _inner("tester-success-bound.json", FIXTURES12)),
    )
    for source, record in checks:
        entry = space.register(source, record)
        if not entry.get("gateEligible"):
            raise BoundaryViolation(
                "rehearsal intake %s (%s) is not gate-eligible: %s"
                % (entry["intakeId"], source, entry.get("statusReason")))


def build_universe(space: RehearsalSpace, **overrides) -> dict:
    """A decision universe over one rehearsal space. Every field can be
    overridden; the defaults are the empty world."""
    universe = {
        "ledger_bytes": space.ledger_bytes(),
        "intake_root": space.intake_root,
        "graph_bytes": PHASE10_GRAPH.read_bytes(),
        "security_register": _security_register(),
        "alpha_register": _empty_alpha_register(),
        "blocking": load_json(PHASE13_BLOCKING),
        "assignments": [], "overlap_decisions": [], "policies": [],
        "risks": [], "authorizations": [], "revocations": [],
        "resolutions": [], "assignment_revocations": [],
    }
    universe.update(overrides)
    return universe


def authorized_universe(space: RehearsalSpace) -> tuple[dict, dict]:
    """Everything AUTHORIZED mechanically requires, constructed inside
    the fixture universe: five accepted intakes, the seven assignments,
    an active fixture policy, a satisfied security gate, sufficient
    Alpha evidence, cleared blocking conditions, and a sealed fixture
    authorization whose evidence cut pins this universe's ledger.
    Returns (universe, authorization record)."""
    _register_full_evidence(space)
    ledger = space.ledger()
    record = _inner("authorization-internal-authorized.json", FIXTURES13)
    record["evidence_cut"] = {
        "ledgerSha256": _sha256(space.ledger_bytes()),
        "ledgerEntries": len(ledger["entries"]),
        "intakeIds": [e["intakeId"] for e in ledger["entries"]],
    }
    universe = build_universe(
        space,
        security_register=_security_register("SATISFIED"),
        alpha_register=_sufficient_alpha_register(),
        blocking=_cleared_blocking(),
        assignments=_fixture_assignments(),
        policies=[_seal13(_inner("sufficiency-policy-active.json",
                                 FIXTURES13))],
        authorizations=[_seal13(record)],
    )
    return universe, record


def real_universe() -> dict:
    """The real decision universe, every input read-only from its
    committed file. Assembling over it must reproduce exactly the state
    Phase 13 committed — the machinery agreeing with itself about
    reality is the zero-evidence control."""
    ops13 = _phase13()
    governance = ops13._load_governance()
    return {
        "ledger_bytes": PHASE9_LEDGER.read_bytes(),
        "intake_root": PHASE9_LEDGER.parent,
        "graph_bytes": PHASE10_GRAPH.read_bytes(),
        "security_register": load_json(PHASE11_REGISTER),
        "alpha_register": load_json(PHASE12_REGISTER),
        "blocking": load_json(PHASE13_BLOCKING),
        "assignments": governance["assignments"],
        "overlap_decisions": governance["overlapDecisions"],
        "policies": governance["policies"],
        "risks": governance["risks"],
        "authorizations": governance["authorizations"],
        "revocations": governance["revocations"],
        "resolutions": governance["resolutions"],
        "assignment_revocations": [],
    }


# --------------------------------------------- decision assembly (§H)

def assemble_decision(universe: dict, as_of: str | None) -> dict:
    """Assemble — never invent — the release decision over one universe.

    Every input is gathered and identified; the candidate state comes
    out of Phase 13's own most-restrictive-first ladder; a standing
    AUTHORIZED record is honored only after Phase 13's full validation
    (when it was cut against this ledger) or its derived
    revocation/expiry state (when it was cut earlier). There is no
    favorable shortcut in this function, and the only AUTHORIZED it can
    report is one a validated external authority record already made.
    """
    ops13 = _phase13()
    intake = _phase9()
    ledger = json.loads(universe["ledger_bytes"].decode("utf-8"))
    for entry in ledger.get("entries", []):
        if is_fixture(entry):
            raise BoundaryViolation(
                "ledger entry %s carries a fixture marker; fixtures never "
                "enter an intake ledger, scratch or real"
                % entry.get("intakeId"))
    subject_digests = intake.subject_digests(ledger)

    graph = json.loads(universe["graph_bytes"].decode("utf-8"))
    ops10 = _phase10()
    graph_issues = ops10.validate_graph(graph)
    if graph_issues:
        raise BoundaryViolation("artifact graph invalid: %s"
                                % "; ".join(graph_issues))
    candidate = ops10._active_candidate(graph)
    if candidate["artifact_id"] != ledger["subjectArtifact"]["identifier"]:
        raise BoundaryViolation(
            "CANDIDATE IDENTITY FAIL: the active candidate %s is not the "
            "ledger subject %s; an assembly over a mutated identity "
            "decides nothing — a successor artifact starts NOT_AUTHORIZED "
            "under its own boundary"
            % (candidate["artifact_id"],
               ledger["subjectArtifact"]["identifier"]))

    security_register = universe["security_register"]
    alpha_register = universe["alpha_register"]

    cut = build_evidence_cut(
        ledger_bytes=universe["ledger_bytes"],
        graph_bytes=universe["graph_bytes"],
        security_register_bytes=json.dumps(
            security_register, sort_keys=True).encode("utf-8"),
        alpha_register_bytes=json.dumps(
            alpha_register, sort_keys=True).encode("utf-8"),
        assignments=universe["assignments"],
        policies=universe["policies"], risks=universe["risks"],
        authorizations=universe["authorizations"],
        revocations=universe["revocations"],
        resolutions=universe["resolutions"],
        assignment_revocations=universe.get("assignment_revocations", []),
        as_of=as_of)

    standing_auth_records = standing_assignments(
        universe["assignments"], as_of,
        universe.get("assignment_revocations", []))
    violations = ops13.separation_violations(
        standing_auth_records, universe["overlap_decisions"])
    floor_missing = ops13.authorization_floor(ledger)
    security_gate = (security_register.get("securityGate") or {}).get(
        "status", "AWAITING_EXTERNAL_EVIDENCE")
    sufficiency = ops13.evaluate_sufficiency(
        universe["policies"], alpha_register, security_register, ledger,
        subject_digests)

    severities = ops13._known_finding_severities(security_register,
                                                 alpha_register)
    risk_rows, expired_risks = [], []
    for risk in universe["risks"]:
        issues = ops13.validate_risk_acceptance(
            risk, standing_auth_records, subject_digests, severities)
        if issues:
            raise BoundaryViolation("risk acceptance invalid at this "
                                    "cut: %s" % "; ".join(issues))
        state = ops13.risk_acceptance_state(risk, as_of)
        if state == "EXPIRED":
            expired_risks.append(risk["risk_id"])
        risk_rows.append({"riskId": risk["risk_id"], "state": state})

    for revocation in universe["revocations"]:
        issues = ops13.validate_revocation(
            revocation, universe["authorizations"], standing_auth_records,
            subject_digests)
        if issues:
            raise BoundaryViolation("revocation invalid at this cut: %s"
                                    % "; ".join(issues))

    ledger_sha = cut["ledgerSha256"]
    standing = None
    authorization_rows = []
    for record in universe["authorizations"]:
        _refuse_fixture(record, "decision assembly")
        row = {"authorizationId": record.get("authorization_id"),
               "decision": record.get("decision")}
        if record.get("decision") == "AUTHORIZED":
            born_here = (record.get("evidence_cut") or {}).get(
                "ledgerSha256") == ledger_sha
            if born_here:
                issues = ops13.validate_authorization(
                    record, ledger=ledger, ledger_sha256=ledger_sha,
                    intake_root=universe["intake_root"],
                    assignments=standing_auth_records,
                    overlap_decisions=universe["overlap_decisions"],
                    policies=universe["policies"],
                    risks=universe["risks"],
                    blocking=universe["blocking"],
                    alpha_register=alpha_register,
                    security_register=security_register, as_of=as_of)
                if issues:
                    row["state"] = "REFUSED"
                    row["refusal"] = issues
                    authorization_rows.append(row)
                    continue
            row["state"] = ops13.authorization_state_of(
                record, universe["revocations"], as_of)
            # A record that decided AUTHORIZED stands with whatever state
            # it derives now — AUTHORIZED, REVOKED, or EXPIRED — exactly
            # as Phase 13's derive_status treats it; the ladder then puts
            # REVOKED and EXPIRED first.
            standing = {"authorizationId": record.get("authorization_id"),
                        "state": row["state"],
                        "expiresAt": record.get("expires_at")}
        else:
            row["state"] = record.get("decision")
        authorization_rows.append(row)

    remediation = sorted(
        [r["internal_id"] for r in security_register.get("findings", [])
         if r.get("status") == "REMEDIATION_REQUIRED"]
        + [f["finding_id"] for f in alpha_register.get("findings", [])
           if f.get("lifecycle_status") == "FIX_REQUIRED"])
    adverse = [
        "condition %d (%s): %s" % (row["condition"], row["title"],
                                   row["state"])
        for row in universe["blocking"].get("conditions", [])
        if row.get("evidenceCharacter") == "ADVERSE_EVIDENCE"
        and row.get("class") == "BLOCKING"]

    effective = intake.effective_statuses(ledger)
    accepted_entries = [
        e for e in ledger.get("entries", [])
        if e.get("gateEligible")
        and effective.get(e["intakeId"]) == "ACCEPTED"]
    alpha_accepted = alpha_register.get("counts", {}).get(
        "acceptedReports", 0)

    time_flags = []
    accepted_records: dict[str, dict] = {}
    for entry in accepted_entries:
        record_path = (universe["intake_root"] / entry["source"]
                       / entry["intakeId"] / "record.json")
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time_flags.append("%s: record bytes unreadable; time "
                              "semantics cannot be determined"
                              % entry["intakeId"])
            continue
        accepted_records[entry["intakeId"]] = record
        dates = {}
        if record.get("date"):
            dates["date"] = record["date"]
        if record.get("signingTimestamp"):
            dates["signingTimestamp"] = record["signingTimestamp"]
        for problem in time_consistency_problems(
                record_dates=dates, received_on=entry.get("receivedOn")):
            time_flags.append("%s: %s" % (entry["intakeId"], problem))

    ordering_flags = []
    signing_records = [r for i, r in sorted(accepted_records.items())
                       if "signatureIdentifier" in r]
    approval_records = [r for i, r in sorted(accepted_records.items())
                        if "firstApprover" in r]
    if signing_records and approval_records:
        ordering_flags = approval_ordering_problems(signing_records[0],
                                                    approval_records[0])

    derived = ops13.derive_authorization_state(
        standing=standing, remediation=remediation, adverse=adverse,
        evidence_total=len(accepted_entries), security_gate=security_gate,
        alpha_accepted=alpha_accepted, sufficiency=sufficiency,
        floor_missing=floor_missing, expired_risks=expired_risks)

    favorable = []
    for entry in accepted_entries:
        favorable.append({
            "intakeId": entry["intakeId"],
            "source": entry["source"],
            "artifactDigest": ledger["subjectArtifact"]["imageDigest"],
            "validationResult": "ACCEPTED",
            "binding": entry.get("binding"),
            "policyVersions": [p.get("policy_id")
                               for p in universe["policies"]],
            "asOfCut": cut["seal"],
            "expiryStatus": "NOT_AN_EXPIRING_RECORD",
        })

    return {
        "schemaVersion": 1,
        "assembledFor": ledger["subjectArtifact"]["identifier"],
        "artifactDigest": ledger["subjectArtifact"]["imageDigest"],
        "evidenceCut": cut,
        "authorizationState": derived["state"],
        "stateBasis": derived["basis"],
        "candidateDecision":
            ops13.CANDIDATE_DECISION_BY_STATE[derived["state"]],
        "inputs": {
            "authorizationFloor": {"satisfied": not floor_missing,
                                   "missing": floor_missing},
            "securityGate": security_gate,
            "sufficiency": {
                "determination": sufficiency["determination"],
                "policyState": sufficiency["policyState"],
                "activePolicy": sufficiency["activePolicy"],
            },
            "blockingAdverse": adverse,
            "remediation": remediation,
            "riskAcceptances": risk_rows,
            "expiredRisks": expired_risks,
            "authorizations": authorization_rows,
            "revocations": sorted(r.get("revocation_id") or ""
                                  for r in universe["revocations"]),
            "separationViolations": violations,
            "timeFlags": time_flags,
            "orderingFlags": ordering_flags,
        },
        "favorableEvidence": favorable,
        "supersedes": None,
        "note": "assembled, never decided: the state comes from Phase "
                "13's most-restrictive-first ladder over identified "
                "immutable inputs, and the only AUTHORIZED this record "
                "can carry is a validated external authority decision "
                "that already exists",
    }


# ------------------------------------------------ rehearsal scenarios

def _expect(condition: bool, expected: str, detail: str = "") -> tuple[str, str]:
    """(expected, observed). Observed equals expected exactly when the
    scenario's checks all held; otherwise it names the divergence, and
    the matrix row records DIVERGED."""
    return expected, (expected if condition
                      else "DIVERGED: %s" % (detail or "a check failed"))


def _subject() -> set[str]:
    return _phase9().subject_digests(load_json(PHASE9_LEDGER))


# ---- Track A: routing

def _s_a1(space):
    samples = (
        ("SECURITY_REVIEW", _inner("review-valid-independent.json",
                                   FIXTURES11)),
        ("HARDWARE_VALIDATION", _inner("hardware-pass-machine.json",
                                       FIXTURES13)),
        ("SIGNING", _inner("signing-metadata-valid.json", FIXTURES10)),
        ("SECOND_APPROVAL", _inner("second-approval-complete.json",
                                   FIXTURES13)),
        ("ALPHA_TESTER_REPORT", _inner("tester-success-bound.json",
                                       FIXTURES12)),
        ("AUTHORITY_ASSIGNMENT",
         _fixture("authority-assignments.json", FIXTURES13)
         ["assignments"][0]),
        ("SUFFICIENCY_POLICY", _inner("sufficiency-policy-active.json",
                                      FIXTURES13)),
        ("RISK_ACCEPTANCE", _inner("risk-acceptance-critical.json",
                                   FIXTURES13)),
        ("AUTHORIZATION", _inner("authorization-internal-authorized.json",
                                 FIXTURES13)),
        ("REVOCATION", _inner("revocation-of-authorization.json",
                              FIXTURES13)),
    )
    subject = _subject()
    ok = True
    for expected_class, record in samples:
        route = route_evidence(record, subject)
        declared = EVIDENCE_CLASSES[expected_class]
        if route["evidenceClass"] != expected_class \
                or route["destination"] != declared["destination"] \
                or route["workstreamOwner"] != declared["workstreamOwner"]:
            ok = False
    return _expect(ok, "all ten evidence classes route to their declared "
                       "workstream, destination, and validator")


def _s_a2(space):
    try:
        classify_evidence({"something": "shapeless", "payload": True})
        return _expect(False, "", "an unroutable record was classified")
    except BoundaryViolation as error:
        return _expect("generic evidence" in str(error),
                       "an unknown evidence class refuses; it never "
                       "becomes generic evidence")


def _s_a3(space):
    ambiguous = dict(_inner("hardware-pass-machine.json", FIXTURES13))
    ambiguous.update({"reviewer": "REVIEWER-XXX", "findings": [],
                      "disposition": "APPROVED"})
    try:
        classify_evidence(ambiguous)
        return _expect(False, "", "an ambiguous record was classified")
    except BoundaryViolation as error:
        return _expect("saying nothing" in str(error),
                       "a record matching two classes refuses instead of "
                       "being guessed at")


def _s_a4(space):
    marked = dict(_inner("signing-metadata-valid.json", FIXTURES10),
                  fixture=True)
    route = route_evidence(marked, _subject())
    return _expect(route["disposition"] == "TEST_FIXTURE_ONLY"
                   and "never routes" in route["destination"],
                   "a fixture-marked record derives TEST_FIXTURE_ONLY and "
                   "routes nowhere",
                   route["disposition"])


def _s_a5(space):
    record = dict(_inner("signing-metadata-valid.json", FIXTURES10),
                  artifactDigest="b" * 64)
    route = route_evidence(record, _subject())
    return _expect(route["disposition"] == "DOES_NOT_APPLY"
                   and route["binding"] == "MISMATCH",
                   "evidence bound to other bytes derives DOES_NOT_APPLY",
                   route["disposition"])


def _s_a6(space):
    record = _inner("signing-metadata-valid.json", FIXTURES10)
    del record["verificationRunBy"]
    route = route_evidence(record, _subject())
    return _expect(route["disposition"] == "INCOMPLETE",
                   "a record missing required fields derives INCOMPLETE "
                   "with the gaps named", route["disposition"])


def _s_a7(space):
    record = dict(_inner("signing-metadata-valid.json", FIXTURES10),
                  category="SIGNING DRILL")
    route = route_evidence(record, _subject())
    return _expect(route["disposition"] == "REJECTED",
                   "a signing drill offered as production signing derives "
                   "REJECTED", route["disposition"])


def _s_a8(space):
    assignment = _fixture("authority-assignments.json",
                          FIXTURES13)["assignments"][0]
    authorization = _inner("authorization-internal-authorized.json",
                           FIXTURES13)
    route_a = route_evidence(assignment, _subject())
    route_b = route_evidence(authorization, _subject())
    ok = (route_a["disposition"] == "REQUIRES_HUMAN_DECISION"
          and route_a["destination"] == "assignment"
          and route_b["disposition"] == "REQUIRES_HUMAN_DECISION"
          and route_b["destination"] == "authorization"
          and "record authorization" in route_b["dispositionBasis"])
    return _expect(ok, "governance records derive REQUIRES_HUMAN_DECISION "
                       "naming their registry; the router prepares, it "
                       "never decides")


# ---- Track B: evidence cuts

def _cut_over(space, **overrides):
    defaults = dict(
        ledger_bytes=space.ledger_bytes(),
        graph_bytes=PHASE10_GRAPH.read_bytes(),
        security_register_bytes=b"{}", alpha_register_bytes=b"{}",
        assignments=[], policies=[], risks=[], authorizations=[],
        revocations=[], resolutions=[], as_of=None)
    defaults.update(overrides)
    return build_evidence_cut(**defaults)


def _s_b1(space):
    space.register("signing", _inner("signing-metadata-valid.json",
                                     FIXTURES10))
    first = _cut_over(space, as_of=CUT_A_DATE)
    second = _cut_over(space, as_of=CUT_A_DATE)
    identical = json.dumps(first, sort_keys=True) \
        == json.dumps(second, sort_keys=True)
    return _expect(identical and first["seal"] == second["seal"]
                   and verify_cut(first) == [],
                   "the same immutable inputs derive byte-identical "
                   "sealed cuts")


def _s_b2(space):
    space.register("signing", _inner("signing-metadata-valid.json",
                                     FIXTURES10))
    bytes_a = space.ledger_bytes()
    cut_a = _cut_over(space, ledger_bytes=bytes_a, as_of=CUT_A_DATE)
    space.register("second-approval", _inner(
        "second-approval-complete.json", FIXTURES13))
    delta = compare_cut_to_ledger(cut_a, space.ledger_bytes())
    replay = _cut_over(space, ledger_bytes=bytes_a, as_of=CUT_A_DATE)
    return _expect(delta["postCutIntakeIds"] == ["INTAKE-002"]
                   and delta["ledgerChanged"] is True
                   and replay["seal"] == cut_a["seal"],
                   "evidence arriving after a cut is detected and named; "
                   "the cut re-derives unchanged from its own inputs")


def _s_b3(space):
    _register_full_evidence(space)
    base = dict(security_register=_security_register("SATISFIED"),
                alpha_register=_sufficient_alpha_register(),
                blocking=_cleared_blocking(),
                assignments=_fixture_assignments())
    universe_a = build_universe(space, **base)
    assembly_a = assemble_decision(universe_a, REHEARSAL_DATE)
    universe_b = build_universe(space, policies=[_seal13(_inner(
        "sufficiency-policy-active.json", FIXTURES13))], **base)
    assembly_b = assemble_decision(universe_b, REHEARSAL_DATE)
    replay_a = assemble_decision(build_universe(space, **base),
                                 REHEARSAL_DATE)
    return _expect(
        assembly_a["authorizationState"] == "SUFFICIENCY_UNDEFINED"
        and assembly_b["authorizationState"] == "READY_FOR_AUTHORIZATION"
        and replay_a == assembly_a
        and assembly_a["evidenceCut"]["seal"]
        != assembly_b["evidenceCut"]["seal"],
        "a policy activated after a cut changes only later cuts; the "
        "earlier decision re-derives unchanged",
        "%s / %s" % (assembly_a["authorizationState"],
                     assembly_b["authorizationState"]))


def _s_b4(space):
    universe, record = authorized_universe(space)
    ledger = json.loads(universe["ledger_bytes"].decode("utf-8"))
    ops13 = _phase13()
    common = dict(
        ledger=ledger, ledger_sha256=_sha256(universe["ledger_bytes"]),
        intake_root=space.intake_root, overlap_decisions=[],
        policies=universe["policies"], risks=[],
        blocking=universe["blocking"],
        alpha_register=universe["alpha_register"],
        security_register=universe["security_register"],
        as_of=REHEARSAL_DATE)
    without = ops13.validate_authorization(record, assignments=[], **common)
    with_assignments = ops13.validate_authorization(
        record, assignments=universe["assignments"], **common)
    return _expect(
        any("not an assigned AUTH-RELEASE" in i for i in without)
        and with_assignments == []
        and any("not an assigned AUTH-RELEASE" in i
                for i in ops13.validate_authorization(
                    record, assignments=[], **common)),
        "authority assigned after a cut acts only at later cuts; the "
        "earlier refusal re-derives unchanged")


def _s_b5(space):
    risk = _seal13(_inner("risk-acceptance-critical.json", FIXTURES13))
    ops13 = _phase13()
    cut_a = _cut_over(space, risks=[risk], as_of="2026-09-01")
    cut_b = _cut_over(space, risks=[risk], as_of="2026-09-20")
    state_a = cut_a["riskAcceptances"][0]["state"]
    state_b = cut_b["riskAcceptances"][0]["state"]
    return _expect(state_a == "STANDING" and state_b == "EXPIRED"
                   and ops13.risk_acceptance_state(risk, "2026-09-01")
                   == "STANDING",
                   "a record standing at cut A is EXPIRED at cut B; "
                   "expiry is derived per cut, never edited in",
                   "%s / %s" % (state_a, state_b))


def _s_b6(space):
    universe, record = authorized_universe(space)
    assembly_a = assemble_decision(universe, REHEARSAL_DATE)
    snapshot = copy.deepcopy(assembly_a)
    revoked = dict(universe, revocations=[_seal13(_inner(
        "revocation-of-authorization.json", FIXTURES13))])
    assembly_b = assemble_decision(revoked, CUT_B_DATE)
    replay_a = assemble_decision(universe, REHEARSAL_DATE)
    return _expect(
        assembly_a["authorizationState"] == "AUTHORIZED"
        and assembly_b["authorizationState"] == "REVOKED"
        and replay_a == snapshot,
        "revocation after a cut revokes at later cuts; the earlier "
        "cut's decision re-derives exactly as recorded",
        "%s / %s" % (assembly_a["authorizationState"],
                     assembly_b["authorizationState"]))


def _s_b7(space):
    risk = _seal13(_inner("risk-acceptance-critical.json", FIXTURES13))
    try:
        _cut_over(space, risks=[risk], as_of=None)
        return _expect(False, "", "a cut over expiring records was built "
                                  "without as-of")
    except BoundaryViolation as error:
        return _expect("--as-of is mandatory" in str(error),
                       "once an expiring record exists, a cut without an "
                       "operator-stated as-of refuses")


def _s_b8(space):
    _register_full_evidence(space)
    base = dict(security_register=_security_register("SATISFIED"),
                alpha_register=_sufficient_alpha_register(),
                blocking=_cleared_blocking(),
                assignments=_fixture_assignments())
    assembly_a = assemble_decision(build_universe(space, **base),
                                   REHEARSAL_DATE)
    frozen_a = copy.deepcopy(assembly_a)
    assembly_b = assemble_decision(
        build_universe(space, policies=[_seal13(_inner(
            "sufficiency-policy-active.json", FIXTURES13))], **base),
        REHEARSAL_DATE)
    superseding = supersede_assembly(assembly_a, assembly_b)
    try:
        supersede_assembly(assembly_a, assembly_a)
        rerun_refused = False
    except BoundaryViolation:
        rerun_refused = True
    return _expect(
        superseding["supersedes"]["cutSeal"]
        == assembly_a["evidenceCut"]["seal"]
        and assembly_a == frozen_a and rerun_refused,
        "a later decision supersedes the earlier one without rewriting "
        "it; a rerun of the same cut is not a supersession")


# ---- Track C: conflict handling

def _s_c1(space):
    result = most_blocking([
        {"reference": "fixture-review-1", "assessment": "ACCEPTED_RISK",
         "favorable": True},
        {"reference": "fixture-review-2", "assessment": "UNRESOLVED",
         "favorable": False},
    ], "security")
    return _expect(
        result["conflictStatus"] == "CONFLICT"
        and result["effectiveAssessment"] == ["UNRESOLVED"]
        and result["resolution"] == "REQUIRES_HUMAN_DECISION"
        and result["decisionAuthorityRequired"] == "AUTH-SECURITY-OWNER",
        "ACCEPTED_RISK against UNRESOLVED leaves the more blocking state "
        "effective and requires the security owner's decision")


def _s_c2(space):
    machine_a = _inner("hardware-pass-machine.json", FIXTURES13)
    effective = hardware_effective_state([
        {"hwId": "HW-001", "results": machine_a["results"]},
        {"hwId": "HW-002", "results": {"installation": {"status": "FAIL"}}},
    ])
    install = next(r for r in effective["perDimension"]
                   if r["dimension"] == "installation")
    return _expect(
        install["byMachine"] == {"HW-001": "PASS", "HW-002": "FAIL"}
        and install["divergent"] is True and install["claim"] is None
        and effective["aggregateClaim"]["claim"] is None,
        "one machine passing and another failing preserves both; no "
        "SUPPORTED ON PCS conclusion exists")


def _s_c3(space):
    ops12 = _phase12()
    space.register("alpha-feedback", _inner("tester-success-bound.json",
                                            FIXTURES12))
    space.register("alpha-feedback", _inner("alpha-severe-unreproduced.json"))
    attempt = dict(_fixture("reproduction-attempts.json", FIXTURES12)
                   ["notReproduced"], sourceReport="INTAKE-002")
    register = ops12.derive_register(
        space.ledger(), load_json(PHASE10_GRAPH), {"decisions": []},
        {"attempts": [attempt]}, load_json(PHASE12_POLICY),
        space.intake_root)
    finding = register["findings"][-1]
    return _expect(
        finding["reproducibility_status"] == "NOT_REPRODUCED"
        and finding["lifecycle_status"] != "CLOSED"
        and finding["finding_id"] in register["sufficiency"]["openBlockers"],
        "an unreproduced severe issue stays open; NOT_REPRODUCED is a "
        "statement about attempts, never about validity")


def _s_c4(space):
    entry = space.register("signing", dict(
        _inner("signing-metadata-valid.json", FIXTURES10),
        artifactDigest="b" * 64))
    return _expect(entry["status"] == "ARTIFACT_MISMATCH"
                   and not entry["gateEligible"],
                   "valid signing evidence for other bytes derives "
                   "ARTIFACT_MISMATCH and moves no gate",
                   entry["status"])


def _s_c5(space):
    ops13 = _phase13()
    risk = _inner("risk-acceptance-critical.json", FIXTURES13)
    risk["authority"] = "Constructed Fixture Approver B"
    issues = ops13.validate_risk_acceptance(
        risk, _fixture_assignments(), _subject(),
        {"SEC-BL-001": "Critical"})
    resolution = dict(_fixture("conflicting-observations.json",
                               FIXTURES13)["resolution"],
                      authority="Constructed Fixture Approver B")
    resolution_issues = ops13.validate_conflict_resolution(
        resolution, _fixture_assignments())
    return _expect(
        any("AUTH-SECURITY-OWNER" in i for i in issues)
        and any("AUTH-HARDWARE" in i for i in resolution_issues),
        "a valid decision from an unauthorized role contributes nothing; "
        "the required authority is named in the refusal")


def _s_c6(space):
    for source, record in (
            ("security-review", _inner("review-valid-independent.json",
                                       FIXTURES11)),
            ("signing", _inner("signing-metadata-valid.json", FIXTURES10)),
            ("second-approval", _inner("second-approval-complete.json",
                                       FIXTURES13)),
            ("alpha-feedback", _inner("tester-success-bound.json",
                                      FIXTURES12))):
        space.register(source, record)
    ops13 = _phase13()
    ledger = space.ledger()
    record = _inner("authorization-internal-authorized.json", FIXTURES13)
    record["evidence_cut"] = {
        "ledgerSha256": _sha256(space.ledger_bytes()),
        "ledgerEntries": len(ledger["entries"]),
        "intakeIds": [e["intakeId"] for e in ledger["entries"]]}
    issues = ops13.validate_authorization(
        record, ledger=ledger, ledger_sha256=_sha256(space.ledger_bytes()),
        intake_root=space.intake_root, assignments=_fixture_assignments(),
        overlap_decisions=[], policies=[_seal13(_inner(
            "sufficiency-policy-active.json", FIXTURES13))],
        risks=[], blocking=_cleared_blocking(),
        alpha_register=_sufficient_alpha_register(),
        security_register=_security_register("SATISFIED"),
        as_of=REHEARSAL_DATE)
    return _expect(any("hardware" in i for i in issues),
                   "four of five floor sources present: AUTHORIZED stays "
                   "impossible and the refusal names the absent source")


def _s_c7(space):
    observations = _fixture("conflicting-observations.json",
                            FIXTURES13)["alphaObservations"]
    result = most_blocking(observations, "alpha")
    favorable = {o["assessment"] for o in observations
                 if o["favorable"] is True}
    return _expect(
        result["resolution"] == "REQUIRES_HUMAN_DECISION"
        and not favorable & set(result["effectiveAssessment"]),
        "a conflict never resolves toward the favorable observation; the "
        "unfavorable assessment stands until the named authority decides")


# ---- Track D: security review rehearsal

def _s_d1(space):
    ops11 = _phase11()
    entry = space.register("security-review", _inner(
        "review-valid-independent.json", FIXTURES11))
    record = _inner("review-valid-independent.json", FIXTURES11)
    problems = ops11.validate_submission(record)
    reconciliation = ops11.reconcile_submission(
        record, load_json(PHASE11_BASELINE))
    classes = {c["reviewer_finding_id"]: c["classification"]
               for c in reconciliation["classifications"]}
    register = ops11.derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)
    return _expect(
        entry["status"] == "ACCEPTED" and entry["gateEligible"]
        and problems == [] and classes["R1-F1"] == "CONFIRMED"
        and classes["R1-F2"] == "NOT_APPLICABLE"
        and register["securityGate"]["status"] == "UNDER_ANALYSIS",
        "a complete valid review is accepted and reconciled; the gate "
        "moves to UNDER_ANALYSIS while Criticals await disposition, "
        "never straight to SATISFIED")


def _s_d2(space):
    entry = space.register("security-review", _inner(
        "review-artifact-mismatch.json", FIXTURES11))
    return _expect(entry["status"] == "ARTIFACT_MISMATCH"
                   and not entry["gateEligible"],
                   "a review bound to the wrong artifact derives "
                   "ARTIFACT_MISMATCH; no transfer by default",
                   entry["status"])


def _s_d3(space):
    ops11 = _phase11()
    record = _inner("review-missing-independent-digest.json", FIXTURES11)
    entry = space.register("security-review", record)
    problems = ops11.validate_submission(record)
    register = ops11.derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)
    return _expect(
        entry["status"] == "ACCEPTED"
        and any("independently_computed_digest" in p for p in problems)
        and register["securityGate"]["status"] == "UNDER_ANALYSIS"
        and register["counts"]["contractValidSubmissions"] == 0,
        "intake ACCEPTED is not contract-valid: a review without an "
        "independently computed digest contributes nothing to the gate "
        "until revised")


def _s_d4(space):
    ops11 = _phase11()
    space.register("security-review", _inner("review-new-critical.json",
                                             FIXTURES11))
    register = ops11.derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)
    new_rows = [r for r in register["findings"]
                if r.get("reconciliation") == "NEW_FINDING"]
    return _expect(
        len(new_rows) >= 1 and register["counts"]["fromEvidence"] >= 1
        and all(r["internal_id"] is None for r in new_rows),
        "a finding outside SEC-BL-001..044 classifies NEW_FINDING and "
        "enters triage for its own identifier")


def _s_d5(space):
    ops11, ops13 = _phase11(), _phase13()
    risk = _inner("risk-acceptance-critical.json", FIXTURES13)
    unassigned = ops13.validate_risk_acceptance(
        risk, [], _subject(), {"SEC-BL-001": "Critical"})
    expired = ops13.risk_acceptance_state(risk, "2026-10-01")
    try:
        ops11.security_finding_transition(
            {"status": "UNDER_REVIEW"}, "NOT_APPLICABLE",
            {"applicabilityEvidence": {"reference": "INTAKE-001"}})
        na_refused = False
    except ops11.BoundaryViolation:
        na_refused = True
    return _expect(
        any("AUTH-SECURITY-OWNER" in i for i in unassigned)
        and expired == "EXPIRED" and na_refused,
        "a Critical acceptance without authority refuses, an expired "
        "acceptance derives EXPIRED, and NOT_APPLICABLE without analysis "
        "refuses")


def _s_d6(space):
    ops11 = _phase11()
    for record in _fixture("review-conflicting-conclusions.json",
                           FIXTURES11)["records"]:
        space.register("security-review", copy.deepcopy(record))
    register = ops11.derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)
    conflict = register["reviewConflict"]
    return _expect(
        conflict is not None
        and conflict["classification"] == "CONTRADICTORY_CONCLUSIONS"
        and conflict["effectiveAssessment"] == "BLOCKED"
        and register["securityGate"]["status"] == "BLOCKED"
        and len(register["acceptedSubmissions"]) == 2,
        "conflicting reviewer conclusions preserve both submissions; the "
        "effective assessment is the most blocking pending resolution")


def _s_d7(space):
    intake = _phase9()
    space.register("security-review", _inner(
        "review-valid-independent.json", FIXTURES11))
    revised = _inner("review-valid-independent.json", FIXTURES11)
    revised["scope"] = revised["scope"] + " (revised)"
    space.register("security-review", revised, revises="INTAKE-001")
    effective = intake.effective_statuses(space.ledger())
    return _expect(
        effective["INTAKE-001"] == "SUPERSEDED"
        and effective["INTAKE-001-R1"] == "ACCEPTED",
        "a revision supersedes its original derivationally; the stored "
        "original never changes")


def _s_d8(space):
    ops11 = _phase11()
    finding = {"status": "FIXED_PENDING_REQUALIFICATION",
               "artifact": "e906a48793d7",
               "remediation_artifact": "fixture-successor-alpha"}
    try:
        ops11.security_finding_transition(
            finding, "CLOSED",
            {"closureEvidence": {"reference": "fixture-requal-run",
                                 "artifact": "e906a48793d7"}})
        return _expect(False, "", "a foreign-artifact closure was allowed")
    except ops11.BoundaryViolation as error:
        return _expect("does not transfer" in str(error),
                       "closure evidence from another artifact refuses; "
                       "approval does not transfer between artifacts")


# ---- Track E: alpha sufficiency rehearsal

def _s_e1(space):
    ops13 = _phase13()
    register = _empty_alpha_register()
    register["counts"] = {"acceptedReports": 100, "boundReports": 100}
    register["reports"] = [
        {"classification": "ACCEPTED", "testerId": "T-%03d" % n,
         "reportType": "SUCCESS", "journey": "A"} for n in range(1, 101)]
    result = ops13.evaluate_sufficiency(
        [], register, _security_register(), empty_scratch_ledger(),
        _subject())
    return _expect(
        result["determination"] == "SUFFICIENCY_UNDETERMINED"
        and result["policyState"] == "SUFFICIENCY_POLICY_UNDEFINED"
        and result["measures"]["acceptedTesterReports"] == 100,
        "one hundred reports against no active policy stay "
        "SUFFICIENCY_UNDETERMINED; the repository never invents "
        "thresholds")


def _s_e2(space):
    ops13 = _phase13()
    policy = _inner("sufficiency-policy-active.json", FIXTURES13)
    policy["thresholds"]["minimumDistinctTesters"] = 5
    result = ops13.evaluate_sufficiency(
        [policy], _sufficient_alpha_register(), _security_register(),
        empty_scratch_ledger(), _subject())
    return _expect(
        result["determination"] == "INSUFFICIENT_EVIDENCE"
        and any("minimumDistinctTesters" in s for s in result["shortfalls"]),
        "under an active fixture policy, evidence below threshold stays "
        "INSUFFICIENT with the shortfall named")


def _s_e3(space):
    ops13 = _phase13()
    _register_full_evidence(space)
    result = ops13.evaluate_sufficiency(
        [_inner("sufficiency-policy-active.json", FIXTURES13)],
        _sufficient_alpha_register(), _security_register(),
        space.ledger(), _subject())
    real_state = ops13.policy_registry_state(
        ops13.sealed_records(load_json(
            ROOT / "qualification" / "phase13" / "sufficiency"
            / "threshold-policies.json"), "policy_id",
            "threshold-policies.json"), _subject())
    return _expect(
        result["determination"] == "SUFFICIENT"
        and real_state == "SUFFICIENCY_POLICY_UNDEFINED",
        "thresholds met derive SUFFICIENT inside the isolated fixture "
        "universe only; the real registry remains "
        "SUFFICIENCY_POLICY_UNDEFINED")


def _s_e4(space):
    ops12 = _phase12()
    entry = space.register("alpha-feedback", _inner(
        "tester-artifact-mismatch.json", FIXTURES12))
    register = ops12.derive_register(
        space.ledger(), load_json(PHASE10_GRAPH), {"decisions": []},
        {"attempts": []}, load_json(PHASE12_POLICY), space.intake_root)
    row = register["reports"][0]
    return _expect(
        entry["status"] == "ARTIFACT_MISMATCH"
        and row["classification"] == "ARTIFACT_MISMATCH"
        and register["counts"]["acceptedReports"] == 0
        and register["counts"]["findings"] == 0,
        "a report bound to another artifact is preserved but aggregates "
        "into nothing; applicability never widens by similarity")


def _s_e5(space):
    ops12 = _phase12()
    fixture = _fixture("tester-duplicate-pair.json", FIXTURES12)
    for record in fixture["records"]:
        space.register("alpha-feedback", copy.deepcopy(record))
    common = (space.ledger(), load_json(PHASE10_GRAPH))
    undecided = ops12.derive_register(
        common[0], common[1], {"decisions": []}, {"attempts": []},
        load_json(PHASE12_POLICY), space.intake_root)
    kinds = {f["finding_id"]: f["relationship"]["kind"]
             for f in undecided["findings"]}
    decided = ops12.derive_register(
        common[0], common[1],
        {"decisions": [fixture["decisionDuplicate"],
                       fixture["decisionRelatedLater"]]},
        {"attempts": []}, load_json(PHASE12_POLICY), space.intake_root)
    late_kinds = {f["finding_id"]: f["relationship"]["kind"]
                  for f in decided["findings"]}
    return _expect(
        set(kinds.values()) == {"DISTINCT"}
        and set(late_kinds.values()) == {"RELATED"}
        and decided["counts"]["findings"] == 2,
        "similar reports stay DISTINCT without a recorded decision; a "
        "later recorded decision supersedes reversibly and deletes "
        "nothing")


def _s_e6(space):
    ops12 = _phase12()
    space.register("alpha-feedback", _inner("alpha-severe-unreproduced.json"))
    register = ops12.derive_register(
        space.ledger(), load_json(PHASE10_GRAPH), {"decisions": []},
        {"attempts": []},
        {"thresholds": {"minimumBoundReports": 1}}, space.intake_root)
    sufficiency = register["sufficiency"]
    return _expect(
        sufficiency["determination"] == "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS"
        and len(sufficiency["openBlockers"]) == 1
        and register["counts"]["findings"] == 1,
        "a severe unresolved report caps sufficiency at "
        "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS; the report is never "
        "deleted to clear the blocker")


def _s_e7(space):
    ops12 = _phase12()
    space.register("alpha-feedback", _inner("tester-success-bound.json",
                                            FIXTURES12))
    register = ops12.derive_register(
        space.ledger(), load_json(PHASE10_GRAPH), {"decisions": []},
        {"attempts": []}, load_json(PHASE12_POLICY), space.intake_root)
    success = register["successEvidence"][0]
    observation = register["hardwareObservations"][0]
    return _expect(
        success["evidenceClass"] == "USER_REPORTED"
        and "never SUPPORTED ON PCS" in success["limit"]
        and observation["class"] == "HARDWARE_OBSERVED"
        and "not a matrix result" in observation["note"],
        "a user-reported success stays user evidence: one observed run "
        "on one machine, never hardware support")


# ---- Track F: hardware evidence pipeline

def _s_f1(space):
    record = _inner("hardware-pass-machine.json", FIXTURES13)
    entry = space.register("hardware", record)
    review = hardware_submission_review(record, _subject())
    return _expect(
        entry["status"] == "ACCEPTED" and entry["gateEligible"]
        and review["disposition"] == "ACCEPTABLE_FOR_INTAKE"
        and review["machineIdentity"]["hwId"] == "HW-001"
        and review["machineIdentity"]["manufacturer"]
        == "Constructed Fixture Systems",
        "a complete protocol record with machine identity and evidence "
        "per PASS is acceptable; machine identity is preserved")


def _s_f2(space):
    record = dict(_inner("hardware-pass-machine.json", FIXTURES13),
                  artifactDigest="b" * 64)
    entry = space.register("hardware", record)
    review = hardware_submission_review(record, _subject())
    return _expect(entry["status"] == "ARTIFACT_MISMATCH"
                   and review["disposition"] == "DOES_NOT_APPLY",
                   "the same machine booting different bytes derives "
                   "ARTIFACT_MISMATCH; a machine result binds to the "
                   "artifact it actually ran", entry["status"])


def _s_f3(space):
    record = _inner("hardware-render-split.json")
    entry = space.register("hardware", record)
    review = hardware_submission_review(record, _subject())
    modes = review["renderModesSeparate"]
    return _expect(
        entry["status"] == "ACCEPTED"
        and modes["companion-3d-native"] == "PASS"
        and modes["companion-3d-fallback"] == "FAIL",
        "native 3D PASS beside fallback 3D FAIL: two permanently "
        "separate dimensions, never one merged graphics claim")


def _s_f4(space):
    record = _inner("hardware-pass-machine.json", FIXTURES13)
    record["machine"] = {"manufacturer": "Constructed Fixture Systems"}
    entry = space.register("hardware", record)
    return _expect(
        entry["status"] == "INCOMPLETE"
        and "machine.model" in entry["statusReason"],
        "a record without full machine identity derives INCOMPLETE with "
        "the missing identity fields named", entry["status"])


def _s_f5(space):
    record = _inner("tester-success-bound.json", FIXTURES12)
    route = route_evidence(record, _subject())
    return _expect(
        route["evidenceClass"] == "ALPHA_TESTER_REPORT"
        and route["destination"] == "alpha-feedback",
        "a user success claim routes to alpha-feedback and derives a "
        "HARDWARE_OBSERVED observation, never a protocol PASS")


def _s_f6(space):
    effective = hardware_effective_state([
        {"hwId": "HW-001",
         "results": {"installation": {"status": "PASS"},
                     "companion-3d-native": {"status": "PASS"}}},
        {"hwId": "HW-002",
         "results": {"installation": {"status": "FAIL"},
                     "companion-3d-native": {"status": "NOT_RUN"}}},
        {"hwId": "HW-003",
         "results": {"installation": {"status": "PASS"}}},
    ])
    try:
        hardware_claims(effective, "SUPPORTED ON PCS")
        refused = False
    except BoundaryViolation:
        refused = True
    return _expect(
        refused and effective["aggregateClaim"]["claim"] is None
        and len(effective["machines"]) == 3,
        "three machines with mixed outcomes stay three machine records; "
        "SUPPORTED ON PCS is refused, not derived")


# ---- Track G: signing and approval

def _s_g1(space):
    entry = space.register("signing", _inner("signing-metadata-valid.json",
                                             FIXTURES10))
    return _expect(entry["status"] == "ACCEPTED" and entry["gateEligible"],
                   "a complete production signing record bound to the "
                   "fixture universe's subject is accepted",
                   entry["status"])


def _s_g2(space):
    entry = space.register("signing", dict(
        _inner("signing-metadata-valid.json", FIXTURES10),
        artifactDigest="sha256:" + "b" * 64))
    return _expect(entry["status"] == "ARTIFACT_MISMATCH",
                   "a correct signing shape naming other bytes derives "
                   "ARTIFACT_MISMATCH", entry["status"])


def _s_g3(space):
    record = _inner("second-approval-complete.json", FIXTURES13)
    del record["secondApprover"]["recomputedDigest"]
    entry = space.register("second-approval", record)
    return _expect(
        entry["status"] == "INCOMPLETE"
        and "recomputedDigest" in entry["statusReason"],
        "an approval without each approver's independently recomputed "
        "digest derives INCOMPLETE; neither approver inherits the digest",
        entry["status"])


def _s_g4(space):
    entry = space.register("signing", dict(
        _inner("signing-metadata-valid.json", FIXTURES10),
        category="SIGNING DRILL"))
    return _expect(
        entry["status"] == "REJECTED"
        and "satisfies nothing" in entry["statusReason"],
        "a signing drill confused with production signing is REJECTED at "
        "the boundary", entry["status"])


def _s_g5(space):
    ops13 = _phase13()
    _register_full_evidence(space)
    overlap_entry = space.register("second-approval", _inner(
        "second-approval-signer-overlap.json", FIXTURES13))
    ledger = space.ledger()
    ledger["entries"] = [
        e for e in ledger["entries"]
        if e["source"] != "second-approval"
        or e["intakeId"] == overlap_entry["intakeId"]]
    ledger_sha = _sha256(json.dumps(ledger, sort_keys=True).encode("utf-8"))
    record = _inner("authorization-internal-authorized.json", FIXTURES13)
    record["evidence_cut"] = {
        "ledgerSha256": ledger_sha,
        "ledgerEntries": len(ledger["entries"]),
        "intakeIds": [e["intakeId"] for e in ledger["entries"]]}
    common = dict(
        ledger=ledger, ledger_sha256=ledger_sha,
        intake_root=space.intake_root,
        assignments=_fixture_assignments(),
        policies=[_seal13(_inner("sufficiency-policy-active.json",
                                 FIXTURES13))],
        risks=[], blocking=_cleared_blocking(),
        alpha_register=_sufficient_alpha_register(),
        security_register=_security_register("SATISFIED"),
        as_of=REHEARSAL_DATE)
    refused = ops13.validate_authorization(record, overlap_decisions=[],
                                           **common)
    permitted = ops13.validate_authorization(
        record, overlap_decisions=[_fixture(
            "authority-assignments.json", FIXTURES13)["overlapDecision"]],
        **common)
    return _expect(
        any("also appears as an approver" in i for i in refused)
        and not any("also appears as an approver" in i for i in permitted),
        "a production signer appearing as second approver is a CONFLICT "
        "refusal; only a recorded overlap decision permits the pair")


def _s_g6(space):
    record = _inner("second-approval-complete.json", FIXTURES13)
    record["secondApprover"]["name"] = record["firstApprover"]["name"]
    entry = space.register("second-approval", record)
    return _expect(
        entry["status"] == "REJECTED"
        and "not a second approval" in entry["statusReason"],
        "two approvals by one identity are REJECTED; one person approving "
        "twice is not a second approval", entry["status"])


def _s_g7(space):
    flags = approval_ordering_problems(
        _inner("signing-metadata-valid.json", FIXTURES10),
        _inner("approval-before-signing.json"))
    return _expect(
        len(flags) == 2
        and all("REQUIRES_HUMAN_DECISION" in f for f in flags),
        "an approval dated before the signing evidence derives "
        "REQUIRES_HUMAN_DECISION; it cannot have verified what did not "
        "yet exist")


def _s_g8(space):
    ops13 = _phase13()
    assignments = []
    for record in _fixture("authority-assignments.json",
                           FIXTURES13)["assignments"]:
        record = dict(record)
        if record["authorityId"] == "AUTH-RELEASE":
            record["expires_at"] = "2026-09-30"
        assignments.append(_seal13(record))
    standing_a = standing_assignments(assignments, REHEARSAL_DATE)
    standing_b = standing_assignments(assignments, CUT_B_DATE)
    held_b = ops13.assigned_identities(standing_b)
    return _expect(
        len(standing_a) == 7 and len(standing_b) == 6
        and not held_b["AUTH-RELEASE"],
        "an authority standing at cut A contributes nothing at cut B "
        "after its stated expiry; the record itself is never edited")


def _s_g9(space):
    assignments = _fixture_assignments()
    revocation = dict(_fixture("assignment-lifecycle.json")
                      ["assignmentRevocation"])
    standing_before = standing_assignments(assignments, "2026-08-19",
                                           [revocation])
    standing_after = standing_assignments(assignments, CUT_B_DATE,
                                          [revocation])
    state = assignment_state(assignments[2], CUT_B_DATE, [revocation])
    return _expect(
        len(standing_before) == 7 and len(standing_after) == 6
        and state == "REVOKED",
        "a revoked authority stops contributing at cuts on or after the "
        "revocation; earlier cuts still see it standing")


def _s_g10(space):
    record = _inner("second-approval-complete.json", FIXTURES13)
    record["secondApprover"]["recomputedDigest"] = "sha256:" + "c" * 64
    entry = space.register("second-approval", record)
    return _expect(
        entry["status"] == "ARTIFACT_MISMATCH"
        and ("c" * 64)[:12] in entry["statusReason"],
        "an approver whose independent recomputation names other bytes "
        "derives ARTIFACT_MISMATCH; the mismatch is named, never "
        "averaged away", entry["status"])


def _s_g11(space):
    problems = subject_unsigned_problems()
    return _expect(problems == [],
                   "the real candidate remains UNSIGNED, frozen, and "
                   "ROOT — read from the real immutable inputs",
                   "; ".join(problems))


# ---- Track H: full decision assembly

def _s_h1(space):
    committed = load_json(PHASE13_STATUS)
    assembly = assemble_decision(real_universe(),
                                 committed.get("evaluationDate"))
    return _expect(
        assembly["authorizationState"] == committed["authorizationState"]
        and assembly["candidateDecision"] == committed["candidateDecision"]
        and assembly["candidateDecision"] == "REQUIRES_MORE_EVIDENCE"
        and assembly["inputs"]["authorizationFloor"]["satisfied"] is False,
        "zero external evidence: the real candidate assembles to exactly "
        "the committed Phase 13 state — EVIDENCE_PENDING, "
        "REQUIRES_MORE_EVIDENCE",
        "%s / %s" % (assembly["authorizationState"],
                     assembly["candidateDecision"]))


def _s_h2(space):
    assembly = assemble_decision(build_universe(space), REHEARSAL_DATE)
    return _expect(
        assembly["authorizationState"] == "EVIDENCE_PENDING"
        and assembly["candidateDecision"] == "REQUIRES_MORE_EVIDENCE",
        "an empty fixture universe is not authorized; absence derives "
        "EVIDENCE_PENDING",
        assembly["authorizationState"])


def _s_h3(space):
    for source, record in (
            ("security-review", _inner("review-valid-independent.json",
                                       FIXTURES11)),
            ("signing", _inner("signing-metadata-valid.json", FIXTURES10)),
            ("second-approval", _inner("second-approval-complete.json",
                                       FIXTURES13)),
            ("hardware", _inner("hardware-pass-machine.json", FIXTURES13))):
        space.register(source, record)
    assembly = assemble_decision(build_universe(
        space, security_register=_security_register("SATISFIED"),
        alpha_register=_sufficient_alpha_register(),
        blocking=_cleared_blocking(), assignments=_fixture_assignments(),
        policies=[_seal13(_inner("sufficiency-policy-active.json",
                                 FIXTURES13))]), REHEARSAL_DATE)
    missing = assembly["inputs"]["authorizationFloor"]["missing"]
    return _expect(
        assembly["candidateDecision"] != "AUTHORIZED"
        and any("alpha-feedback" in m for m in missing),
        "four of five floor sources: not authorized, and the absent "
        "source is named",
        assembly["authorizationState"])


def _s_h4(space):
    for source, record in (
            ("security-review", _inner("review-valid-independent.json",
                                       FIXTURES11)),
            ("second-approval", _inner("second-approval-complete.json",
                                       FIXTURES13)),
            ("hardware", _inner("hardware-pass-machine.json", FIXTURES13)),
            ("alpha-feedback", _inner("tester-success-bound.json",
                                      FIXTURES12))):
        space.register(source, record)
    entry = space.register("signing", dict(
        _inner("signing-metadata-valid.json", FIXTURES10),
        artifactDigest="b" * 64))
    assembly = assemble_decision(build_universe(
        space, security_register=_security_register("SATISFIED"),
        alpha_register=_sufficient_alpha_register(),
        blocking=_cleared_blocking(), assignments=_fixture_assignments(),
        policies=[_seal13(_inner("sufficiency-policy-active.json",
                                 FIXTURES13))]), REHEARSAL_DATE)
    missing = assembly["inputs"]["authorizationFloor"]["missing"]
    return _expect(
        entry["status"] == "ARTIFACT_MISMATCH"
        and assembly["candidateDecision"] != "AUTHORIZED"
        and any("signing" in m for m in missing),
        "five records but one bound to other bytes: the mismatched "
        "source counts as absent and authorization stays impossible",
        assembly["authorizationState"])


def _s_h5(space):
    universe, _record = authorized_universe(space)
    universe = dict(universe,
                    security_register=_security_register("UNDER_ANALYSIS"),
                    authorizations=[])
    assembly = assemble_decision(universe, REHEARSAL_DATE)
    return _expect(
        assembly["authorizationState"] == "SECURITY_REVIEW_PENDING"
        and assembly["candidateDecision"] == "REQUIRES_MORE_EVIDENCE",
        "everything present but security unresolved: the ladder holds at "
        "SECURITY_REVIEW_PENDING; the review completes before anything "
        "else is weighed",
        assembly["authorizationState"])


def _s_h6(space):
    universe, _record = authorized_universe(space)
    universe = dict(universe, policies=[], authorizations=[])
    assembly = assemble_decision(universe, REHEARSAL_DATE)
    return _expect(
        assembly["authorizationState"] == "SUFFICIENCY_UNDEFINED"
        and assembly["candidateDecision"] == "REQUIRES_MORE_EVIDENCE",
        "all evidence present but the alpha policy undefined: not "
        "authorized — evidence cannot become sufficient against "
        "undefined thresholds",
        assembly["authorizationState"])


def _s_h7(space):
    universe, _record = authorized_universe(space)
    policy = _inner("sufficiency-policy-active.json", FIXTURES13)
    policy["thresholds"]["minimumDistinctTesters"] = 5
    universe = dict(universe, policies=[_seal13(policy)],
                    authorizations=[])
    assembly = assemble_decision(universe, REHEARSAL_DATE)
    return _expect(
        assembly["authorizationState"] == "REQUIRES_MORE_EVIDENCE"
        and assembly["candidateDecision"] == "REQUIRES_MORE_EVIDENCE"
        and assembly["inputs"]["sufficiency"]["determination"]
        == "INSUFFICIENT_EVIDENCE",
        "an active fixture policy with insufficient evidence: not "
        "authorized, with the determination recorded",
        assembly["authorizationState"])


def _s_h8(space):
    universe, record = authorized_universe(space)
    assembly = assemble_decision(universe, REHEARSAL_DATE)
    standing = [row for row in assembly["inputs"]["authorizations"]
                if row["state"] == "AUTHORIZED"]
    return _expect(
        assembly["authorizationState"] == "AUTHORIZED"
        and len(standing) == 1
        and standing[0]["authorizationId"]
        == record["authorization_id"],
        "every mechanical requirement satisfied by fixture evidence: "
        "AUTHORIZED is demonstrable inside the isolated fixture "
        "universe only, through a validated authorization record")


def _s_h9(space):
    universe, _record = authorized_universe(space)
    assembly_a = assemble_decision(universe, REHEARSAL_DATE)
    frozen = copy.deepcopy(assembly_a)
    revoked = dict(universe, revocations=[_seal13(_inner(
        "revocation-of-authorization.json", FIXTURES13))])
    assembly_b = assemble_decision(revoked, CUT_B_DATE)
    replay = assemble_decision(universe, REHEARSAL_DATE)
    return _expect(
        assembly_a["authorizationState"] == "AUTHORIZED"
        and assembly_b["authorizationState"] == "REVOKED"
        and assembly_b["candidateDecision"] == "REVOKED"
        and replay == frozen,
        "a fixture authorization followed by revocation: the later cut "
        "no longer authorizes, and the earlier cut's record is not "
        "rewritten",
        "%s / %s" % (assembly_a["authorizationState"],
                     assembly_b["authorizationState"]))


def _s_h10(space):
    ops13, ops10 = _phase13(), _phase10()
    record = _inner("authorization-internal-authorized.json", FIXTURES13)
    successor = _fixture("successor-artifact-entry.json",
                         FIXTURES13)["successorEntry"]
    applies = ops13.authorization_applies(record, successor)
    evidence = {"evidenceId": "INTAKE-001",
                "artifactDigest":
                    load_json(PHASE9_LEDGER)["subjectArtifact"]
                    ["imageDigest"],
                "scope": "security-review"}
    transfer = ops10.evaluate_applicability(
        evidence, successor["artifact_id"], load_json(PHASE10_GRAPH))
    return _expect(
        applies["result"] == "REFUSED"
        and transfer["result"] == "DOES_NOT_APPLY",
        "a successor artifact inherits nothing: authorization never "
        "crosses an artifact edge and evidence does not transfer "
        "without a recorded decision")


# ---- Track I: time, expiry, revocation

def _s_i1(space):
    ops13 = _phase13()
    assignments = []
    for record in _fixture("authority-assignments.json",
                           FIXTURES13)["assignments"]:
        record = dict(record)
        if record["authorityId"] == "AUTH-ALPHA-PROGRAM":
            record["expires_at"] = "2026-09-30"
        assignments.append(_seal13(record))
    policy = _inner("sufficiency-policy-active.json", FIXTURES13)
    at_a = ops13.validate_policy(
        policy, standing_assignments(assignments, REHEARSAL_DATE))
    at_b = ops13.validate_policy(
        policy, standing_assignments(assignments, CUT_B_DATE))
    return _expect(
        at_a == [] and any("AUTH-ALPHA-PROGRAM" in i for i in at_b),
        "an authority valid at cut A confers nothing at cut B after "
        "expiry; the activation it validated at A is not rewritten")


def _s_i2(space):
    ops13 = _phase13()
    risk = _inner("risk-acceptance-critical.json", FIXTURES13)
    return _expect(
        ops13.risk_acceptance_state(risk, "2026-09-01") == "STANDING"
        and ops13.risk_acceptance_state(risk, CUT_B_DATE) == "EXPIRED",
        "a risk acceptance standing at cut A is EXPIRED at cut B and "
        "contributes no favorable state afterward")


def _s_i3(space):
    ops13 = _phase13()
    revocation = _inner("revocation-of-authorization.json", FIXTURES13)
    issues = ops13.validate_revocation(revocation, [],
                                       _fixture_assignments(), _subject())
    return _expect(any("does not exist" in i for i in issues),
                   "a revocation recorded before its target authorization "
                   "exists refuses; a revocation of nothing revokes "
                   "nothing")


def _s_i4(space):
    flags = time_consistency_problems(
        record_dates={"date": _fixture("time-anomalies.json")
                      ["futureDated"]["date"]},
        received_on=REHEARSAL_DATE)
    return _expect(
        len(flags) == 1 and "postdates the intake receipt" in flags[0],
        "future-dated evidence derives REQUIRES_HUMAN_DECISION; a claim "
        "observed after it arrived conflicts with intake ordering")


def _s_i5(space):
    flags = time_consistency_problems(
        record_dates={"date": "2026-08-18"}, received_on="2026-08-18",
        revises_received_on="2026-08-19")
    return _expect(
        len(flags) == 1 and "cannot precede" in flags[0],
        "a revision received before its original derives "
        "REQUIRES_HUMAN_DECISION; a correction cannot precede what it "
        "corrects")


def _s_i6(space):
    anomaly = _fixture("time-anomalies.json")["ambiguousSigning"]
    flags = time_consistency_problems(
        record_dates={"date": anomaly["date"],
                      "signingTimestamp": anomaly["signingTimestamp"]},
        received_on=CUT_B_DATE)
    return _expect(
        len(flags) == 1 and "ambiguous time basis" in flags[0],
        "two disagreeing dates for one act are an ambiguous time basis "
        "and fail closed to a human decision")


def _s_i7(space):
    ops13 = _phase13()
    risk = _inner("risk-acceptance-critical.json", FIXTURES13)
    authorization = _inner("authorization-internal-authorized.json",
                           FIXTURES13)
    refusals = 0
    for fn in (
            lambda: ops13.risk_acceptance_state(risk, None),
            lambda: ops13.authorization_state_of(authorization, [], None),
            lambda: _cut_over(space, risks=[_seal13(risk)], as_of=None)):
        try:
            fn()
        except (BoundaryViolation, ops13.BoundaryViolation):
            refusals += 1
    return _expect(refusals == 3,
                   "every evaluation that needs an expiry answer without "
                   "an operator-stated as-of refuses; nothing is assumed "
                   "away")


#: The rehearsal registry: every row of MATRIX.json, in execution order.
SCENARIOS = (
    ("PH14-A1", "A", "every evidence class routes to its workstream", _s_a1),
    ("PH14-A2", "A", "unknown evidence class refuses", _s_a2),
    ("PH14-A3", "A", "ambiguous evidence class refuses", _s_a3),
    ("PH14-A4", "A", "fixture marker is terminal: TEST_FIXTURE_ONLY", _s_a4),
    ("PH14-A5", "A", "wrong-artifact evidence: DOES_NOT_APPLY", _s_a5),
    ("PH14-A6", "A", "missing fields: INCOMPLETE", _s_a6),
    ("PH14-A7", "A", "signing drill: REJECTED", _s_a7),
    ("PH14-A8", "A", "governance records: REQUIRES_HUMAN_DECISION", _s_a8),
    ("PH14-B1", "B", "same inputs derive byte-identical cuts", _s_b1),
    ("PH14-B2", "B", "evidence after a cut is detected, not absorbed", _s_b2),
    ("PH14-B3", "B", "policy activated after a cut", _s_b3),
    ("PH14-B4", "B", "authority assigned after a cut", _s_b4),
    ("PH14-B5", "B", "record expiring between cuts", _s_b5),
    ("PH14-B6", "B", "revocation after authorization", _s_b6),
    ("PH14-B7", "B", "expiring records make as-of mandatory", _s_b7),
    ("PH14-B8", "B", "supersession never rewrites", _s_b8),
    ("PH14-C1", "C", "security: more blocking state stands", _s_c1),
    ("PH14-C2", "C", "hardware: divergent machines both preserved", _s_c2),
    ("PH14-C3", "C", "alpha: unreproduced severe issue stays open", _s_c3),
    ("PH14-C4", "C", "signing: wrong artifact does not apply", _s_c4),
    ("PH14-C5", "C", "unauthorized role contributes nothing", _s_c5),
    ("PH14-C6", "C", "four of five floor: not authorized", _s_c6),
    ("PH14-C7", "C", "conflict never resolves favorably", _s_c7),
    ("PH14-D1", "D", "valid review: accepted and reconciled", _s_d1),
    ("PH14-D2", "D", "review bound to wrong artifact", _s_d2),
    ("PH14-D3", "D", "missing independently computed digest", _s_d3),
    ("PH14-D4", "D", "new finding beyond the baseline", _s_d4),
    ("PH14-D5", "D", "critical dispositions fail closed", _s_d5),
    ("PH14-D6", "D", "conflicting reviewer assessments", _s_d6),
    ("PH14-D7", "D", "revision supersedes derivationally", _s_d7),
    ("PH14-D8", "D", "closure with foreign evidence refuses", _s_d8),
    ("PH14-E1", "E", "no policy: 100 reports stay undetermined", _s_e1),
    ("PH14-E2", "E", "active policy: shortfall stays insufficient", _s_e2),
    ("PH14-E3", "E", "threshold met: sufficient in fixture universe only",
     _s_e3),
    ("PH14-E4", "E", "foreign-artifact reports cannot aggregate", _s_e4),
    ("PH14-E5", "E", "duplicates stay distinct without a decision", _s_e5),
    ("PH14-E6", "E", "severe unresolved report caps sufficiency", _s_e6),
    ("PH14-E7", "E", "user success stays user evidence", _s_e7),
    ("PH14-F1", "F", "valid hardware PASS record", _s_f1),
    ("PH14-F2", "F", "same machine, wrong artifact", _s_f2),
    ("PH14-F3", "F", "native 3D and fallback 3D stay separate", _s_f3),
    ("PH14-F4", "F", "missing machine identity", _s_f4),
    ("PH14-F5", "F", "user claim without protocol evidence", _s_f5),
    ("PH14-F6", "F", "mixed machines derive no support claim", _s_f6),
    ("PH14-G1", "G", "valid fixture signing record", _s_g1),
    ("PH14-G2", "G", "correct signature, wrong artifact", _s_g2),
    ("PH14-G3", "G", "missing recomputed digest", _s_g3),
    ("PH14-G4", "G", "drill confused with production", _s_g4),
    ("PH14-G5", "G", "signer equals second approver", _s_g5),
    ("PH14-G6", "G", "two approvals by one identity", _s_g6),
    ("PH14-G7", "G", "approval predating signer evidence", _s_g7),
    ("PH14-G8", "G", "expired signing/approval authority", _s_g8),
    ("PH14-G9", "G", "revoked authority", _s_g9),
    ("PH14-G10", "G", "independent recomputation mismatch", _s_g10),
    ("PH14-G11", "G", "the real candidate remains UNSIGNED", _s_g11),
    ("PH14-H1", "H", "real universe: REQUIRES_MORE_EVIDENCE", _s_h1),
    ("PH14-H2", "H", "empty fixture universe: not authorized", _s_h2),
    ("PH14-H3", "H", "four of five floor sources", _s_h3),
    ("PH14-H4", "H", "floor present, one wrong artifact", _s_h4),
    ("PH14-H5", "H", "security unresolved holds the ladder", _s_h5),
    ("PH14-H6", "H", "alpha policy undefined: not authorized", _s_h6),
    ("PH14-H7", "H", "active policy, insufficient evidence", _s_h7),
    ("PH14-H8", "H", "fixture universe AUTHORIZED (isolated only)", _s_h8),
    ("PH14-H9", "H", "authorized then revoked at a later cut", _s_h9),
    ("PH14-H10", "H", "successor artifact inherits nothing", _s_h10),
    ("PH14-I1", "I", "authority valid at A, expired at B", _s_i1),
    ("PH14-I2", "I", "risk acceptance valid at A, expired at B", _s_i2),
    ("PH14-I3", "I", "revocation before authorization refuses", _s_i3),
    ("PH14-I4", "I", "future-dated evidence flags", _s_i4),
    ("PH14-I5", "I", "revision predating original flags", _s_i5),
    ("PH14-I6", "I", "ambiguous time basis fails closed", _s_i6),
    ("PH14-I7", "I", "no as-of: every expiry evaluation refuses", _s_i7),
)


# ------------------------------------------------ matrix derivation

def run_rehearsals() -> dict:
    """Execute every scenario in its own scratch universe; derive the
    matrix. The real immutable inputs are byte-compared before and after
    — a single changed byte aborts the run, because a rehearsal that
    touched reality is not a rehearsal."""
    before = {path: path.read_bytes() for path in REAL_IMMUTABLE_INPUTS}
    rows = []
    for scenario_id, track, title, fn in SCENARIOS:
        base = Path(tempfile.mkdtemp(prefix="phase14-rehearsal-"))
        try:
            expected, observed = fn(RehearsalSpace(base))
        finally:
            shutil.rmtree(base, ignore_errors=True)
        rows.append({
            "scenarioId": scenario_id,
            "track": track,
            "title": title,
            "expected": expected,
            "observed": observed,
            "result": "AS_EXPECTED" if observed == expected
            else "DIVERGED",
            "evidenceClass": "FIXTURE_DEMONSTRATION_ONLY",
            "realEvidenceStatus": "EXTERNAL_EVIDENCE_REQUIRED",
        })
    changed = [path.name for path, raw in before.items()
               if path.read_bytes() != raw]
    if changed:
        raise BoundaryViolation(
            "REAL LEDGER INTEGRITY FAIL: %s changed during the "
            "rehearsals; a dry run must leave every real input "
            "byte-identical" % ", ".join(sorted(changed)))
    status = load_json(PHASE13_STATUS)
    return {
        "schemaVersion": 1,
        "purpose": "The Phase 14 rehearsal matrix: every scenario "
                   "executed against scratch universes over "
                   "TEST_FIXTURE_ONLY material. A row here is a "
                   "machinery demonstration and nothing else — it is "
                   "not evidence about the subject artifact, and no row "
                   "can ever upgrade the real candidate.",
        "subjectArtifact": status["subjectArtifact"],
        "executedAgainst": {
            "ledgerSha256": _sha256(before[PHASE9_LEDGER]),
            "graphSha256": _sha256(before[PHASE10_GRAPH]),
            "securityRegisterSha256": _sha256(before[PHASE11_REGISTER]),
            "alphaRegisterSha256": _sha256(before[PHASE12_REGISTER]),
            "authorizationState": status["authorizationState"],
            "candidateDecision": status["candidateDecision"],
        },
        "realLedgerByteIdentical": True,
        "realEvidence": "NONE — every external gate still awaits its "
                        "owner; EXTERNAL_EVIDENCE_REQUIRED",
        "counts": {
            "scenarios": len(rows),
            "asExpected": sum(1 for r in rows
                              if r["result"] == "AS_EXPECTED"),
            "tracks": len({r["track"] for r in rows}),
        },
        "scenarios": rows,
        "note": "Derived by evidence_execution_ops.py run-rehearsals; "
                "recomputable on every run. When real evidence arrives "
                "the executedAgainst pins change and this matrix is "
                "re-derived — exactly like the Phase 11/12 registers.",
    }


def matrix_problems() -> list[str]:
    """Re-execute everything; compare to the committed matrix."""
    derived = run_rehearsals()
    problems = []
    diverged = [r["scenarioId"] for r in derived["scenarios"]
                if r["result"] != "AS_EXPECTED"]
    if diverged:
        problems.append("scenario(s) diverged from their expected "
                        "outcome: %s" % ", ".join(diverged))
    if not MATRIX_PATH.is_file():
        problems.append("MATRIX.json is absent; run build-matrix")
        return problems
    committed = load_json(MATRIX_PATH)
    if committed != derived:
        problems.append(
            "committed MATRIX.json does not reproduce from executing the "
            "scenarios; run build-matrix and review the diff")
    return problems


# ---------------------------------------------------------------- verify

def verify_fixtures() -> list[str]:
    """Every Phase 14 fixture carries all three markers; no fixture
    marker exists anywhere in the real intake tree."""
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
    else:
        issues.append("fixtures/ is missing")
    intake_root = PHASE9_LEDGER.parent
    for path in sorted(intake_root.rglob("*.json")):
        if path == PHASE9_LEDGER:
            continue
        try:
            record = load_json(path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if is_fixture(record):
            issues.append(
                "%s carries a fixture marker inside the real intake tree"
                % path.relative_to(ROOT).as_posix())
    return issues


def verify_all() -> list[str]:
    issues = []
    for name in PACKAGE_FILES:
        if not (PHASE14 / name).is_file():
            issues.append("package: %s is missing" % name)
    issues += ["fixtures: %s" % p for p in verify_fixtures()]
    issues += ["subject: %s" % p for p in subject_unsigned_problems()]
    if issues:
        return issues
    try:
        issues += ["matrix: %s" % p for p in matrix_problems()]
    except BoundaryViolation as error:
        issues.append("rehearsals: %s" % error)
    try:
        committed = load_json(PHASE13_STATUS)
        assembly = assemble_decision(real_universe(),
                                     committed.get("evaluationDate"))
        for field in ("authorizationState", "candidateDecision"):
            if assembly[field] != committed[field]:
                issues.append(
                    "assembly: the real universe assembles to %s %r but "
                    "Phase 13 committed %r; the assembler may never "
                    "diverge from the ladder it composes"
                    % (field, assembly[field], committed[field]))
    except BoundaryViolation as error:
        issues.append("assembly: %s" % error)
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 14 evidence execution verifies clean; every "
              "favorable row is FIXTURE_DEMONSTRATION_ONLY and the real "
              "candidate is unchanged")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_build_matrix(_args) -> int:
    matrix = run_rehearsals()
    diverged = [r["scenarioId"] for r in matrix["scenarios"]
                if r["result"] != "AS_EXPECTED"]
    if diverged:
        print("REFUSED: scenario(s) diverged: %s" % ", ".join(diverged))
        return 2
    dump_json(MATRIX_PATH, matrix)
    print("MATRIX.json derived: %d scenarios across %d tracks, all "
          "AS_EXPECTED, real inputs byte-identical"
          % (matrix["counts"]["scenarios"], matrix["counts"]["tracks"]))
    return 0


def _cmd_route(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    try:
        route = route_evidence(record, _subject())
    except BoundaryViolation as error:
        print("REFUSED: %s" % error)
        return 2
    for key in ("evidenceClass", "workstreamOwner", "routeKind",
                "destination", "validator", "binding", "disposition",
                "dispositionBasis"):
        print("%-18s %s" % (key, route[key]))
    print("(analysis only; nothing was registered anywhere)")
    return 0


def _cmd_assemble(args) -> int:
    committed = load_json(PHASE13_STATUS)
    as_of = args.as_of or committed.get("evaluationDate")
    try:
        assembly = assemble_decision(real_universe(), as_of)
    except BoundaryViolation as error:
        print("REFUSED: %s" % error)
        return 2
    print("subject artifact    %s" % assembly["assembledFor"])
    print("authorization state %s" % assembly["authorizationState"])
    print("candidate decision  %s" % assembly["candidateDecision"])
    print("state basis         %s" % assembly["stateBasis"])
    print("evidence cut seal   %s" % assembly["evidenceCut"]["seal"][:16])
    print("(assembled from real immutable inputs, read-only; the "
          "repository cannot make the decision)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser(
        "verify", help="package, fixtures, matrix reproducibility, real "
                       "ledger byte identity, real-state agreement; exit "
                       "2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    mat = commands.add_parser(
        "build-matrix", help="execute every rehearsal scenario and "
                             "derive MATRIX.json")
    mat.set_defaults(func=_cmd_build_matrix)

    rte = commands.add_parser(
        "route", help="route one candidate evidence record (analysis "
                      "only; registers nothing)")
    rte.add_argument("record")
    rte.set_defaults(func=_cmd_route)

    asm = commands.add_parser(
        "assemble", help="assemble the real candidate decision from "
                         "real immutable inputs (read-only)")
    asm.add_argument("--as-of", default=None)
    asm.set_defaults(func=_cmd_assemble)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 16 external security-review intake and gate-execution operations.

Phase 15 made the security-review workflow operational; Phase 16 makes the
first real submission *receivable*: the operator surface that inspects a
prospective submission before the boundary, carries it through the one
door, validates it against the committed contract, binds it to the exact
artifact, reconciles it, cuts sealed evidence, and derives the release
consequences — composed entirely from the standing engines:

* Phase 9  ``intake.py``                 — the only door evidence enters
* Phase 10 ``candidate_ops.py``          — graph, applicability, candidate
* Phase 11 ``security_review_ops.py``    — contract, reconciliation, gate
* Phase 13 ``release_authority_ops.py``  — authority, risk, authorization
* Phase 14 ``evidence_execution_ops.py`` — router, cuts, assembly, scratch
* Phase 15 ``review_execution_ops.py``   — receive wrapper, ceremony,
  workflow receipts, handoff packaging, the real cut archive

Nothing here re-implements a rule an earlier phase owns, and nothing here
can author the external evidence the decision requires. The Phase 16
receipt machine is the *boundary* view — did a submission cross the
evidence boundary, and in what condition — and its most advanced word is
ACCEPTED, which means only that evidence crossed intact. ACCEPTED is not
APPROVED (that word does not exist here), not a satisfied gate (Phase 11
derives the gate from reconciliation output), and not authorization
(Phase 13's full floor still decides). The failure/recovery matrix and
the full route matrix are derived by executing every scenario against the
real engines in scratch universes; INTAKE_STATUS.json keeps six questions
permanently separate: operational readiness, receipt state, security
assessment, gate state, authorization state, candidate decision.

Determinism: no clocks. Dates come from records or the operator; the
commit is the tamper-evident time.
"""

from __future__ import annotations

import argparse
import ast
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
PHASE16 = ROOT / "qualification" / "phase16"
FIXTURES_DIR = PHASE16 / "fixtures"
STATUS_PATH = PHASE16 / "INTAKE_STATUS.json"
MATRIX_PATH = PHASE16 / "MATRIX.json"
RECOVERY_PATH = PHASE16 / "FAILURE_RECOVERY_MATRIX.json"
PINS_PATH = PHASE16 / "CONTRACT_PINS.json"
HANDOFF16_PATH = PHASE16 / "REVIEWER_HANDOFF.md"
CEREMONY_DOC_PATH = PHASE16 / "IDENTITY_CEREMONY.md"
VERIFY16_PATH = PHASE16 / "tools" / "verify_phase16.py"
ENGINE_PATH = Path(__file__).resolve()

PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE10_TOOL = ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
PHASE10_GRAPH = (
    ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json")
PHASE10_STATUS = ROOT / "qualification" / "phase10" / "candidate-status.json"
PHASE11_TOOL = (
    ROOT / "qualification" / "phase11" / "tools" / "security_review_ops.py")
PHASE11_PACKAGE = ROOT / "qualification" / "phase11" / "security-review"
PHASE11_BASELINE = PHASE11_PACKAGE / "FINDINGS_BASELINE.json"
PHASE11_IDENTITY = PHASE11_PACKAGE / "ARTIFACT_IDENTITY.json"
PHASE11_SCHEMA = PHASE11_PACKAGE / "SUBMISSION_SCHEMA.json"
PHASE11_REGISTER = ROOT / "qualification" / "phase11" / "security-findings.json"
PHASE13_TOOL = (
    ROOT / "qualification" / "phase13" / "tools" / "release_authority_ops.py")
PHASE13_STATUS = ROOT / "qualification" / "phase13" / "authorization-status.json"
PHASE13_FIXTURES = ROOT / "qualification" / "phase13" / "fixtures"
PHASE14_TOOL = (
    ROOT / "qualification" / "phase14" / "tools" / "evidence_execution_ops.py")
PHASE15_TRACK = ROOT / "qualification" / "phase15" / "security-review-execution"
PHASE15_TOOL = PHASE15_TRACK / "tools" / "review_execution_ops.py"
PHASE15_HANDOFF = PHASE15_TRACK / "REVIEW_HANDOFF.md"
PHASE15_CUTS = PHASE15_TRACK / "cuts"
PHASE15_FIXTURES = PHASE15_TRACK / "fixtures"
PHASE15_STATUS = PHASE15_TRACK / "EXTERNAL_STATUS.json"
PHASE15_MATRIX = PHASE15_TRACK / "FAILURE_RECOVERY_MATRIX.json"

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: The documents and derived files this tree must carry. verify fails if
#: any is absent.
PACKAGE_FILES = (
    "README.md", "CONTRACT.md", "SECURITY_REVIEW_RECEIPT.md",
    "REVIEWER_HANDOFF.md", "IDENTITY_CEREMONY.md", "INTAKE_EXECUTION.md",
    "RECONCILIATION_AND_GATE.md", "EVIDENCE_CUT_POLICY.md",
    "FAILURE_AND_RECOVERY.md", "STATE_MODEL.md", "CONTRACT_PINS.json",
    "MATRIX.json", "FAILURE_RECOVERY_MATRIX.json", "INTAKE_STATUS.json",
)

#: Executable package members live below ``tools/`` and therefore are not
#: expressible through ``PACKAGE_FILES``' root-relative names.  Keeping the
#: two lists separate also lets tests prove that the mandated engine location
#: never drifts to a repository-root tools directory.
PACKAGE_TOOL_FILES = (
    "tools/security_review_intake_ops.py",
    "tools/verify_phase16.py",
)

#: The contract inputs this layer consumes, pinned by sha256 in
#: CONTRACT_PINS.json. A pin update is a deliberate act whose audit trail
#: is that file's diff; verify refuses silent drift of any of these under
#: the operating layer.
CONTRACT_PIN_FILES = (
    "qualification/phase11/security-review/REQUEST.md",
    "qualification/phase11/security-review/REVIEW_SCOPE.md",
    "qualification/phase11/security-review/ARTIFACT_IDENTITY.json",
    "qualification/phase11/security-review/FINDINGS_BASELINE.json",
    "qualification/phase11/security-review/REVIEWER_INSTRUCTIONS.md",
    "qualification/phase11/security-review/SUBMISSION_SCHEMA.json",
    "qualification/phase11/security-review/VERIFY_SUBMISSION.py",
    "qualification/phase15/security-review-execution/REVIEW_HANDOFF.md",
    "qualification/phase15/security-review-execution/fixtures/"
    "review-approved-with-conditions.json",
    "qualification/phase15/security-review-execution/fixtures/"
    "review-blocked.json",
)

#: Statements REVIEWER_HANDOFF.md must carry verbatim (markdown-normalized).
HANDOFF16_REQUIRED_STATEMENTS = (
    "The repository's expected digest is not evidence of your observation. "
    "Compute the artifact identity yourself, from the bytes you actually "
    "reviewed, and record how you computed it.",
    "Acceptance into the intake means only that your submission crossed the "
    "evidence boundary intact. It is not agreement, not a security "
    "approval, and not a release authorization.",
)

# ---------------------------------------------------------- receipt states

#: The Phase 16 boundary vocabulary: where one submission stands relative
#: to the evidence boundary. The brief's five states plus the non-favorable
#: operational states the Phase 9 boundary itself distinguishes
#: (UNVERIFIABLE, ARTIFACT_MISMATCH -> DOES_NOT_APPLY) and the derived
#: SUPERSEDED. APPROVED is not a receipt state; ACCEPTED means only that
#: evidence crossed the boundary intact and settles nothing downstream.
RECEIPT_STATES = (
    "AWAITING_SUBMISSION", "RECEIVED", "REJECTED", "INCOMPLETE",
    "UNVERIFIABLE", "DOES_NOT_APPLY", "ACCEPTED", "SUPERSEDED",
)

#: Observable successions for one submission lineage. Absence is refusal;
#: ``receipt_transition`` enforces it, and re-entry from any refused state
#: exists only as a new or revised submission (RECEIVED again, with the
#: revision named). No transition reaches a favorable word because the
#: vocabulary contains none: ACCEPTED is boundary bookkeeping, and its
#: only successor is SUPERSEDED.
RECEIPT_TRANSITIONS = {
    "AWAITING_SUBMISSION": {"RECEIVED"},
    "RECEIVED": {"ACCEPTED", "REJECTED", "INCOMPLETE", "UNVERIFIABLE",
                 "DOES_NOT_APPLY"},
    "REJECTED": {"RECEIVED"},
    "INCOMPLETE": {"RECEIVED"},
    "UNVERIFIABLE": {"RECEIVED"},
    "DOES_NOT_APPLY": {"RECEIVED"},
    "ACCEPTED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}

#: Leaving one of these states happens only through a new or revised
#: submission; the transition refuses unless the revision is named.
REENTRY_REQUIRES_REVISION = (
    "REJECTED", "INCOMPLETE", "UNVERIFIABLE", "DOES_NOT_APPLY",
)

#: Tokens that must never appear in the receipt machine. Receipt states
#: are bookkeeping about a submission's boundary crossing, never a verdict
#: about the artifact. Swept over the vocabulary and every transition
#: target by ``forbidden_vocabulary_problems``.
FORBIDDEN_RECEIPT_TOKENS = (
    "APPROVED", "SATISFIED", "PASS", "AUTHORIZED", "CLEAN", "NO_FINDINGS",
    "GATE",
)

#: Phase 9 stored statuses -> boundary receipt states, exhaustively. A
#: stored status outside this table refuses rather than being guessed.
_BOUNDARY_STATE = {
    "ACCEPTED": "ACCEPTED",
    "REJECTED": "REJECTED",
    "INCOMPLETE": "INCOMPLETE",
    "UNVERIFIABLE": "UNVERIFIABLE",
    "ARTIFACT_MISMATCH": "DOES_NOT_APPLY",
}

#: Overall boundary precedence: ACCEPTED reports that evidence has crossed
#: (a fact, not a verdict — the assessment and the gate live elsewhere);
#: otherwise the most recovery-demanding standing state names the
#: position. Nothing here is favorability.
_BOUNDARY_PRECEDENCE = (
    "ACCEPTED", "INCOMPLETE", "UNVERIFIABLE", "DOES_NOT_APPLY", "REJECTED",
)

# ------------------------------------------------------ inspection classes

#: What ``inspect`` may call a prospective submission. Inspection is
#: read-only and precedes the boundary; STRUCTURALLY_VALID is the only
#: passing class and is still not acceptance.
INSPECTION_CLASSES = (
    "STRUCTURALLY_VALID", "INCOMPLETE", "MALFORMED", "WRONG_ARTIFACT",
    "AMBIGUOUS_IDENTITY", "CREDENTIAL_BEARING", "FIXTURE_MARKED",
    "UNSUPPORTED_EVIDENCE_SHAPE",
)

#: The identity-ceremony vocabulary, inherited unchanged (Phase 12's
#: words, executed by the Phase 15 ceremony).
IDENTITY_CEREMONY_STATES = (
    "VERIFIED", "OBSERVED_UNVERIFIED", "MISSING", "MISMATCH",
)

#: Source patterns the Phase 16 tree must never contain. The first group
#: is clock usage (evidence semantics never ask the wall clock); the
#: second is ledger authorship (the Phase 9 boundary is the only append
#: path); the third is engine duplication (these definitions live in the
#: owning phases and appear here only as compositions).
FORBIDDEN_TIME_TOKENS = (
    "datetime.now", "date.today", "time.time(", "utcnow",
)
FORBIDDEN_APPEND_TOKENS = (
    '"entries"].append', "entries.append(",
)
FORBIDDEN_REIMPLEMENTATIONS = (
    "def register(", "def seal_entry(", "def seal_record(",
    "def validate_record(", "def derive_register(",
    "def derive_security_gate(", "def reconcile_submission(",
    "def classify_conflict(", "def evaluate_applicability(",
    "def build_evidence_cut(", "def verify_cut(", "def assemble_decision(",
    "def derive_authorization_state(", "def validate_authorization(",
    "def validate_risk_acceptance(", "def authorization_floor(",
)

CUT_ID = re.compile(r"^CUT-\d{3}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIGEST_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")

_MODULE_CACHE: dict[str, object] = {}


class BoundaryViolation(ValueError):
    """A refused derivation, transition, inspection, command, or record."""


# ---------------------------------------------------------------- shared I/O

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalize_digest(value: str) -> str:
    value = str(value).strip().lower()
    return value[7:] if value.startswith("sha256:") else value


def _load_module(name: str, path: Path):
    module = _MODULE_CACHE.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE_CACHE[name] = module
    return module


def _phase9():
    return _load_module("phase9_intake_for_phase16", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase16", PHASE10_TOOL)


def _phase11():
    return _load_module("phase11_ops_for_phase16", PHASE11_TOOL)


def _phase13():
    return _load_module("phase13_ops_for_phase16", PHASE13_TOOL)


def _phase14():
    return _load_module("phase14_ops_for_phase16", PHASE14_TOOL)


def _phase15():
    return _load_module("phase15_ops_for_phase16", PHASE15_TOOL)


def is_fixture(record) -> bool:
    """Any one marker makes a record a fixture everywhere it is read —
    the Phase 13/14/15 rule, unchanged."""
    return isinstance(record, dict) and (
        record.get("fixtureClass") == FIXTURE_MARKER
        or record.get("test_fixture_only") is True
        or record.get("fixture") is True)


def _refuse_fixture(record, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: the record declares a %s marker — a fixture is never "
            "evidence" % (where, FIXTURE_MARKER))


def _inner(name: str) -> dict:
    """The wrapped record inside a Phase 16 fixture, deep-copied."""
    return copy.deepcopy(load_json(FIXTURES_DIR / name)["record"])


def _wrapper(name: str) -> dict:
    return load_json(FIXTURES_DIR / name)


def _expected_digests(identity: dict | None = None) -> set[str]:
    if identity is None:
        identity = load_json(PHASE11_IDENTITY)
    artifact = identity["subjectArtifact"]
    return {
        _normalize_digest(artifact[key])
        for key in ("imageDigest", "isoSha256", "qcow2Sha256",
                    "ociTarSha256", "rawSha256")
        if artifact.get(key)
    }


# ------------------------------------------------------ receipt state machine

def receipt_transition(current: str, target: str,
                       revision_of: str | None = None) -> str:
    """Advance the boundary receipt view for one submission lineage;
    refusal is the default.

    Leaving a refused state (REJECTED, INCOMPLETE, UNVERIFIABLE,
    DOES_NOT_APPLY) happens only through a new or revised submission, so
    the transition back to RECEIVED requires the revision to be named —
    REJECTED never becomes ACCEPTED by bookkeeping."""
    if current not in RECEIPT_STATES:
        raise BoundaryViolation("unknown receipt state %r" % current)
    if target not in RECEIPT_STATES:
        raise BoundaryViolation(
            "unknown receipt state %r; the vocabulary contains no "
            "favorable state and no transition can mint one" % target)
    if target not in RECEIPT_TRANSITIONS[current]:
        raise BoundaryViolation(
            "receipt transition %s -> %s is not allowed; the allowed set "
            "from %s is {%s}"
            % (current, target, current,
               ", ".join(sorted(RECEIPT_TRANSITIONS[current])) or "nothing"))
    if current in REENTRY_REQUIRES_REVISION and target == "RECEIVED" \
            and not revision_of:
        raise BoundaryViolation(
            "a %s submission re-enters only as a new or revised "
            "submission; name the revision — bookkeeping alone never "
            "recovers a refused submission" % current)
    return target


def forbidden_vocabulary_problems() -> list[str]:
    """The favorable-token sweep, callable by verify and by the guards."""
    problems = []
    for state in RECEIPT_STATES:
        for token in FORBIDDEN_RECEIPT_TOKENS:
            if token in state:
                problems.append(
                    "receipt state %r contains forbidden token %r"
                    % (state, token))
    for state, targets in RECEIPT_TRANSITIONS.items():
        if state not in RECEIPT_STATES:
            problems.append("transition source %r is not in the vocabulary"
                            % state)
        for target in targets:
            if target not in RECEIPT_STATES:
                problems.append(
                    "transition %s -> %s leaves the vocabulary; a "
                    "transition table that can exit its own state set can "
                    "mint states" % (state, target))
            for token in FORBIDDEN_RECEIPT_TOKENS:
                if token in target:
                    problems.append(
                        "transition %s -> %s reaches forbidden token %r"
                        % (state, target, token))
    missing = set(RECEIPT_STATES) - set(RECEIPT_TRANSITIONS)
    if missing:
        problems.append("states with no transition row: %s"
                        % ", ".join(sorted(missing)))
    unknown = set(_BOUNDARY_STATE.values()) - set(RECEIPT_STATES)
    if unknown:
        problems.append("boundary map targets outside the vocabulary: %s"
                        % ", ".join(sorted(unknown)))
    return problems


def boundary_receipt_state(entry: dict, effective_status: str) -> str:
    """One ledger entry's boundary receipt state, derived, stored nowhere."""
    if effective_status == "SUPERSEDED":
        return "SUPERSEDED"
    stored = entry.get("status")
    state = _BOUNDARY_STATE.get(stored)
    if state is None:
        raise BoundaryViolation(
            "entry %s carries stored status %r, which is outside the "
            "Phase 9 vocabulary; an unknown status is never guessed into "
            "a receipt state" % (entry.get("intakeId"), stored))
    return state


def derive_receipt_register(ledger: dict) -> dict:
    """Boundary receipt states for every security-review intake, plus the
    overall position. Everything is derived; nothing is written anywhere.

    This is the *boundary* view: did each submission cross, and in what
    condition. The *workflow* view (reconciliation position, conflicts)
    stays Phase 15's ``derive_receipt_register``, and the two are reported
    side by side in INTAKE_STATUS.json, never merged."""
    intake = _phase9()
    entries = [e for e in ledger.get("entries", [])
               if e.get("source") == "security-review"]
    if not entries:
        return {
            "overall": "AWAITING_SUBMISSION",
            "entries": [],
            "basis": "zero security-review intakes exist; absence blocks, "
                     "it never approves",
        }
    effective = intake.effective_statuses(ledger)
    rows = []
    for entry in entries:
        intake_id = entry["intakeId"]
        rows.append({
            "intakeId": intake_id,
            "receiptState": boundary_receipt_state(entry,
                                                   effective[intake_id]),
            "storedStatus": entry.get("status"),
            "effectiveStatus": effective[intake_id],
            "revises": entry.get("revises"),
            "gateEligible": bool(entry.get("gateEligible")),
        })
    standing = [r["receiptState"] for r in rows
                if r["receiptState"] != "SUPERSEDED"]
    overall = "AWAITING_SUBMISSION"
    for state in _BOUNDARY_PRECEDENCE:
        if state in standing:
            overall = state
            break
    return {
        "overall": overall,
        "entries": rows,
        "basis": "derived from the Phase 9 ledger's stored and effective "
                 "statuses; no receipt state is stored, ACCEPTED means "
                 "only that evidence crossed the boundary, and nothing "
                 "here is a verdict about the artifact",
    }


# --------------------------------------------------------- identity ceremony

def identity_ceremony(record: dict, identity: dict | None = None) -> dict:
    """The Phase 15 ceremony with fail-closed screening in front of it.

    A malformed observation (not a string, or not a single digest token)
    and an ambiguous observation refuse outright instead of being folded
    into MISSING — the reviewer supplied *something*, and what they
    supplied cannot be evaluated. Well-formed input delegates to the
    Phase 15 ceremony verbatim: the four states, their meanings, and the
    never-fill-the-observed-field rule are inherited, not redefined."""
    _refuse_fixture(record, "identity ceremony")
    observed = record.get("independently_computed_digest")
    if observed is not None and not isinstance(observed, str):
        raise BoundaryViolation(
            "identity ceremony: the independent observation is not a "
            "string; a malformed observation fails closed — it is neither "
            "MISSING nor a measurement")
    if isinstance(observed, str) and observed.strip() \
            and not DIGEST_RE.fullmatch(observed.strip()):
        raise BoundaryViolation(
            "identity ceremony: the independent observation is not a "
            "single sha256 digest; an ambiguous or malformed observation "
            "fails closed rather than being guessed at")
    return _phase15().identity_ceremony(record, identity)


# ------------------------------------------------------------- inspection

def _artifact_digest_claims(record: dict) -> list[str]:
    """Every artifact-identity digest the record claims, normalized and
    deduplicated, in a stable order."""
    claims = []
    for key in ("artifact_digest", "artifactDigest"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            claims.append(_normalize_digest(value))
    value = record.get("artifact")
    if isinstance(value, dict):
        value = value.get("digest")
    if isinstance(value, str) and value.strip():
        claims.append(_normalize_digest(value))
    seen: list[str] = []
    for claim in claims:
        if claim not in seen:
            seen.append(claim)
    return seen


def inspect_submission(record_path: Path,
                       attachments: list[Path] | None = None) -> dict:
    """Examine one prospective submission before the boundary. Read-only:
    no ledger is opened, nothing is appended anywhere, and a passing
    inspection is explicitly not acceptance.

    Exactly one classification, resolved in boundary order: credential
    hygiene first (over raw bytes, so nesting and attachments are the
    same bytes), then parseability, the fixture wall, the evidence-shape
    router, identity coherence, artifact binding, and only then the
    submission contract."""
    intake = _phase9()
    record_path = Path(record_path)
    if not record_path.is_file():
        raise BoundaryViolation("refusing: record %s does not exist; "
                                "inspection takes explicit paths only"
                                % record_path)
    attachment_paths = []
    for attachment in attachments or []:
        attachment = Path(attachment)
        if not attachment.is_file():
            raise BoundaryViolation(
                "refusing: attachment %s does not exist" % attachment)
        attachment_paths.append(attachment)

    def _report(classification: str, basis: str, **extra) -> dict:
        report = {
            "classification": classification,
            "basis": basis,
            "inspectionPassed": classification == "STRUCTURALLY_VALID",
            "receiptState": "RECEIVED",
            "note": "inspection passed is not evidence accepted into the "
                    "immutable boundary; the Phase 9 intake is the only "
                    "door and decides on its own",
        }
        report.update(extra)
        return report

    # 1. Credential hygiene, before anything in the bytes is trusted.
    tainted = {}
    for path in [record_path, *attachment_paths]:
        classes = intake.detect_secret_classes(path.read_bytes())
        if classes:
            tainted[path.name] = classes
    if tainted:
        return _report(
            "CREDENTIAL_BEARING",
            "likely credential material: %s — the value is not repeated "
            "here, and the boundary would refuse this before ingestion"
            % "; ".join("%s: %s" % (name, ", ".join(classes))
                        for name, classes in sorted(tainted.items())),
            secretClasses=tainted)

    # 2. Parseability.
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return _report(
            "MALFORMED",
            "record is not parseable JSON (%s); the boundary would "
            "preserve the bytes verbatim as UNVERIFIABLE" % error)
    if not isinstance(record, dict):
        return _report("MALFORMED",
                       "the record is not a JSON object; there is no "
                       "submission shape to inspect")

    # 3. The fixture wall.
    if is_fixture(record):
        return _report(
            "FIXTURE_MARKED",
            "the record carries a %s marker; a fixture is never evidence "
            "and the boundary rejects it structurally" % FIXTURE_MARKER)

    # 4. Evidence shape, through the Phase 14 router's classifier.
    ops14 = _phase14()
    try:
        evidence_class = ops14.classify_evidence(record)
    except ops14.BoundaryViolation as error:
        return _report(
            "UNSUPPORTED_EVIDENCE_SHAPE",
            "the evidence router refuses this shape: %s" % error)
    if evidence_class != "SECURITY_REVIEW":
        return _report(
            "UNSUPPORTED_EVIDENCE_SHAPE",
            "the record carries the %s fingerprint, not a security-review "
            "submission; it belongs to that class's own route and this "
            "path forwards nothing" % evidence_class,
            routedClass=evidence_class)

    # 5. Identity coherence.
    claims = _artifact_digest_claims(record)
    if len(claims) > 1:
        return _report(
            "AMBIGUOUS_IDENTITY",
            "the record claims %d distinct artifact digests; a submission "
            "naming two artifacts names none, and ambiguity fails closed"
            % len(claims),
            claimedDigests=claims)
    observed = record.get("independently_computed_digest")
    if observed is not None and (
            not isinstance(observed, str)
            or (observed.strip()
                and not DIGEST_RE.fullmatch(observed.strip()))):
        return _report(
            "AMBIGUOUS_IDENTITY",
            "the independent observation is not a single sha256 digest; "
            "a malformed observation fails closed")

    # 6. Artifact binding.
    expected = _expected_digests()
    foreign = [claim for claim in claims if claim not in expected]
    if isinstance(observed, str) and observed.strip() \
            and _normalize_digest(observed) not in expected:
        foreign.append(_normalize_digest(observed))
    if foreign:
        return _report(
            "WRONG_ARTIFACT",
            "digest(s) %s do not identify the subject artifact; a review "
            "of other bytes satisfies nothing here and applicability "
            "never transfers by default"
            % ", ".join(sorted(set(d[:12] for d in foreign))),
            foreignDigests=sorted(set(foreign)))

    # 7. The submission contract, plus the ceremony, read-only.
    problems = _phase11().validate_submission(record)
    ceremony = identity_ceremony(record)
    integrity = attachment_integrity_problems(record, attachment_paths)
    if problems or integrity:
        return _report(
            "INCOMPLETE",
            "the submission does not yet satisfy the committed contract "
            "(%d problem(s)); the original would be preserved and a "
            "revision completes it" % (len(problems) + len(integrity)),
            contractProblems=problems, attachmentProblems=integrity,
            identityCeremony=ceremony)
    return _report(
        "STRUCTURALLY_VALID",
        "the submission satisfies the committed contract as presented; "
        "only the Phase 9 boundary can accept it",
        contractProblems=[], attachmentProblems=[],
        identityCeremony=ceremony)


# ------------------------------------------------------------- one-door I/O

def receive(record_path: Path, attachments: list[Path], received_on: str,
            submitted_by: str, revises: str | None = None,
            ledger_path: Path = PHASE9_LEDGER) -> dict:
    """Register one real security-review submission through the one door.

    Pure delegation: Phase 15's ``receive`` resolves the explicit paths
    and the Phase 9 ``register`` function decides. This wrapper adds no
    append path, no pre-processing, and no opinion — it exists so the
    Phase 16 operator surface is complete, and the guard suite proves the
    delegation structurally (this module contains no ledger-append code)."""
    return _phase15().receive(record_path, attachments, received_on,
                              submitted_by, revises, ledger_path)


def completeness_missing(record: dict) -> list[str]:
    """Required contract fields absent from the record, derived from the
    committed schema — presence only, coherence not judged. COMPLETE
    (nothing missing) is weaker than VALID (zero contract problems), and
    both are weaker than ACCEPTED (a Phase 9 boundary outcome)."""
    schema = load_json(PHASE11_SCHEMA)
    missing = []
    for field in schema.get("required", []):
        value = record.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    finding_required = (schema.get("properties", {}).get("findings", {})
                        .get("items", {}).get("required", []))
    for index, finding in enumerate(record.get("findings") or []):
        if not isinstance(finding, dict):
            missing.append("findings[%d] is not an object" % index)
            continue
        for field in finding_required:
            if not finding.get(field):
                missing.append("findings[%d].%s" % (index, field))
    return missing


def attachment_integrity_problems(record: dict,
                                  attachments: list[Path] | None) -> list[str]:
    """Validate attachment names and declared digests without ingesting.

    Phase 9 remains the authoritative integrity check at intake.  This
    preflight composes the same sha256 comparison so a reviewer can correct a
    package before the immutable boundary records the refusal.  Duplicate
    basenames are ambiguous and therefore fail closed, exactly as Phase 9's
    registration path does.
    """
    paths = [Path(path) for path in attachments or []]
    problems: list[str] = []
    by_name: dict[str, Path] = {}
    for path in paths:
        if not path.is_file():
            problems.append("attachment %s does not exist" % path)
            continue
        if path.name in by_name:
            problems.append("duplicate attachment name %r" % path.name)
            continue
        by_name[path.name] = path
    claimed = record.get("attachmentDigests") or {}
    if not isinstance(claimed, dict):
        return problems + ["attachmentDigests is not an object"]
    for name, digest in sorted(claimed.items()):
        path = by_name.get(name)
        if path is None:
            problems.append("digest claimed for %s, which is not attached"
                            % name)
            continue
        normalized = _normalize_digest(str(digest))
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            # Phase 11 also reports this contract problem; keeping it here
            # makes the integrity result independently explicit.
            problems.append("attachment %s carries a malformed sha256"
                            % name)
        elif _sha256(path.read_bytes()) != normalized:
            problems.append("attachment %s does not match its claimed digest"
                            % name)
    return problems


def validate_submission_record(record: dict,
                               attachments: list[Path] | None = None,
                               received_on: str | None = None) -> dict:
    """Contract validation, completeness, and the identity ceremony —
    read-only, never repairing, never accepting.

    Three different words for three different facts: COMPLETE (every
    required field is present), VALID (the contract, attachment integrity,
    credential hygiene, and any explicitly supplied receipt-time relation
    hold), and ACCEPTED (the Phase 9 boundary took it) — no operation here
    collapses them."""
    _refuse_fixture(record, "validation")
    before = copy.deepcopy(record)
    verdict = _phase15().validate_submission_record(record)
    missing = completeness_missing(record)
    integrity = attachment_integrity_problems(record, attachments)
    raw = json.dumps(record, sort_keys=True).encode("utf-8")
    credential_classes = _phase9().detect_secret_classes(raw)
    for path in attachments or []:
        path = Path(path)
        if path.is_file():
            credential_classes.extend(
                _phase9().detect_secret_classes(path.read_bytes()))
    credential_classes = sorted(set(credential_classes))
    time_problems = _phase14().time_consistency_problems(
        record_dates={name: record[name]
                      for name in ("review_end", "date")
                      if record.get(name) is not None},
        received_on=received_on,
    ) if received_on is not None else []
    if record != before:
        raise BoundaryViolation(
            "validation mutated the record; a malformed submission is "
            "never silently repaired")
    valid = (verdict["contractValid"] and not integrity
             and not credential_classes and not time_problems)
    return {
        "contractProblems": verdict["contractProblems"],
        "contractValid": verdict["contractValid"],
        "missingRequired": missing,
        "complete": not missing,
        "attachmentProblems": integrity,
        "credentialClasses": credential_classes,
        "timeProblems": time_problems,
        "valid": valid,
        "identityCeremony": verdict["identityCeremony"],
        "note": "COMPLETE is presence; VALID is contract + integrity + "
                "credential + explicit-time validation; ACCEPTED is the "
                "Phase 9 boundary's outcome. None implies another, and "
                "validation is not acceptance",
    }


# ------------------------------------------------------------- binding

def bind_record(record: dict, evidence_id: str | None = None,
                graph: dict | None = None) -> dict:
    """Artifact binding for one submission record, through the Phase 10
    applicability engine unchanged. Default for any other artifact is
    DOES_NOT_APPLY; a commit identity is never a substitute for an
    artifact digest; nothing is written anywhere."""
    _refuse_fixture(record, "binding")
    ops10 = _phase10()
    if graph is None:
        graph = load_json(PHASE10_GRAPH)
    claims = _artifact_digest_claims(record)
    if len(claims) > 1:
        raise BoundaryViolation(
            "binding: the record claims %d distinct artifact digests; "
            "ambiguous identity binds to nothing" % len(claims))
    evidence = {
        "evidenceId": evidence_id or record.get("reviewer_id") or "<record>",
        "artifactDigest": claims[0] if claims else None,
        "scope": "security-review",
    }
    candidate = ops10._active_candidate(graph)
    result = ops10.evaluate_applicability(evidence, candidate["artifact_id"],
                                          graph)
    result["targetArtifact"] = candidate["artifact_id"]
    result["note"] = ("evaluated by the Phase 10 applicability engine; "
                      "transfer requires an explicit recorded decision "
                      "over an explicit graph relationship, and commit "
                      "ancestry is not identity")
    return result


# ------------------------------------------------------------ evidence cuts

def build_real_cut(cut_id: str, as_of: str | None) -> dict:
    """A sealed evidence cut over the real universe — Phase 15's cut
    builder over the Phase 14 cut contract, unchanged. One archive exists
    (``qualification/phase15/security-review-execution/cuts/``); Phase 16
    deliberately does not open a second one."""
    return _phase15().build_real_cut(cut_id, as_of)


def write_cut(cut_record: dict) -> Path:
    """Append-only, into the single standing archive."""
    return _phase15().write_cut(cut_record)


def committed_cuts() -> list[dict]:
    return _phase15().committed_cuts()


def cut_problems() -> list[str]:
    return _phase15().cut_problems()


# ----------------------------------------------------------- handoff package

def prepare(out_dir: Path) -> dict:
    """Assemble the reviewer handoff: the Phase 15 package (Phase 11
    commissioning files, REVIEW_HANDOFF.md, marked examples, pinned
    manifest) plus the Phase 16 operational handoff and the executable
    identity-ceremony description, all pinned by sha256 in a second
    manifest. Creates no review, invents no identity, appends nothing,
    and changes no candidate state; the output reproduces byte-for-byte
    from its pinned inputs."""
    ops15 = _phase15()
    out_dir = Path(out_dir)
    for path, statements in (
            (HANDOFF16_PATH, HANDOFF16_REQUIRED_STATEMENTS),):
        if not path.is_file():
            raise BoundaryViolation("refusing: %s is missing; an "
                                    "incomplete handoff is not a handoff"
                                    % path)
        text = ops15._normalized_markdown(path.read_text(encoding="utf-8"))
        for statement in statements:
            if statement not in text:
                raise BoundaryViolation(
                    "refusing: REVIEWER_HANDOFF.md no longer states: %s"
                    % statement)
    if not CEREMONY_DOC_PATH.is_file():
        raise BoundaryViolation("refusing: IDENTITY_CEREMONY.md is missing")
    pin_issues = contract_pin_problems()
    if pin_issues:
        raise BoundaryViolation(
            "refusing: the contract pins do not hold, so the package "
            "cannot be what the contract promises — %s"
            % "; ".join(pin_issues))

    manifest15 = ops15.prepare_review(out_dir)

    additions = (
        (HANDOFF16_PATH, "REVIEWER_HANDOFF.md"),
        (CEREMONY_DOC_PATH, "IDENTITY_CEREMONY.md"),
    )
    files = dict(manifest15["files"])
    for source, name in additions:
        raw = source.read_bytes()
        (out_dir / name).write_bytes(raw)
        files[name] = {"bytes": len(raw), "sha256": _sha256(raw)}
    manifest15_raw = (out_dir / "HANDOFF_MANIFEST.json").read_bytes()
    files["HANDOFF_MANIFEST.json"] = {
        "bytes": len(manifest15_raw), "sha256": _sha256(manifest15_raw)}

    identity = load_json(PHASE11_IDENTITY)["subjectArtifact"]
    manifest = {
        "schemaVersion": 1,
        "purpose": "Phase 16 reviewer handoff for the independent "
                   "security review of the frozen Alpha candidate",
        "subjectArtifact": {
            "identifier": identity["identifier"],
            "imageDigest": identity["imageDigest"],
        },
        "createsNoReview": True,
        "submissionDoor": "qualification/phase9/tools/intake.py register "
                          "--source security-review (operationally: "
                          "security_review_intake_ops.py receive)",
        "expectedSubmissionContract": "SUBMISSION_SCHEMA.json, enforced by "
                                      "VERIFY_SUBMISSION.py; both are in "
                                      "this package and pinned below",
        "identityCeremony": "IDENTITY_CEREMONY.md — the reviewer computes "
                            "the artifact identity independently; the "
                            "repository's expected digest is not evidence "
                            "of an observation",
        "examplesAreNotEvidence": "files under examples/ carry "
                                  "TEST_FIXTURE_ONLY markers and the "
                                  "intake rejects them structurally",
        "files": files,
    }
    dump_json(out_dir / "PHASE16_HANDOFF_MANIFEST.json", manifest)
    return manifest


# --------------------------------------------------------------- pins

def compute_contract_pins() -> dict:
    """The pinned contract inputs, from their committed bytes."""
    pins = {}
    for name in CONTRACT_PIN_FILES:
        path = ROOT / name
        if not path.is_file():
            raise BoundaryViolation("contract pin source %s is missing"
                                    % name)
        raw = path.read_bytes()
        pins[name] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return {
        "schemaVersion": 1,
        "purpose": "the contract inputs the Phase 16 layer operates over, "
                   "pinned by sha256; verify refuses drift, and a pin "
                   "update is a deliberate act recorded in this file's "
                   "diff",
        "pins": pins,
    }


def contract_pin_problems() -> list[str]:
    if not PINS_PATH.is_file():
        return ["CONTRACT_PINS.json is absent"]
    committed = load_json(PINS_PATH)
    derived = compute_contract_pins()
    problems = []
    committed_pins = committed.get("pins", {})
    for name, pin in derived["pins"].items():
        recorded = committed_pins.get(name)
        if recorded is None:
            problems.append("pins: %s is not pinned" % name)
        elif recorded != pin:
            problems.append(
                "pins: %s drifted from its pinned bytes; the contract "
                "under this layer changed without a deliberate pin "
                "update" % name)
    for name in committed_pins:
        if name not in derived["pins"]:
            problems.append("pins: %s is pinned but no longer a contract "
                            "input" % name)
    return problems


# ---------------------------------------------------------- source boundary

def engine_boundary_problems() -> list[str]:
    """Structural walls over this tree's own sources: no clock decides
    evidence semantics, no code path appends to any ledger, and no owning
    engine's rule is re-implemented here."""
    problems: list[str] = []
    sources = {
        ENGINE_PATH.name: ENGINE_PATH.read_text(encoding="utf-8"),
        VERIFY16_PATH.name: VERIFY16_PATH.read_text(encoding="utf-8")
        if VERIFY16_PATH.is_file() else "",
    }
    if not sources[VERIFY16_PATH.name]:
        problems.append("boundary: verify_phase16.py is missing")
    forbidden_defs = {
        token.removeprefix("def ").removesuffix("(")
        for token in FORBIDDEN_REIMPLEMENTATIONS
    }

    def dotted(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            left = dotted(node.value)
            return "%s.%s" % (left, node.attr) if left else node.attr
        if isinstance(node, ast.Call):
            return dotted(node.func) + "()"
        return ""

    for name, source in sources.items():
        try:
            tree = ast.parse(source, filename=name)
        except SyntaxError as error:
            problems.append("boundary: %s is not parseable: %s"
                            % (name, error))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in forbidden_defs:
                problems.append(
                    "boundary: %s defines %s; that rule belongs to its "
                    "owning phase and is composed, never re-implemented"
                    % (name, node.name))
            if not isinstance(node, ast.Call):
                continue
            call = dotted(node.func)
            if call in ("datetime.now", "datetime.datetime.now",
                        "datetime.date.today", "date.today", "time.time",
                        "datetime.datetime.utcnow"):
                problems.append("boundary: %s reads a clock via %s"
                                % (name, call))
            if call == "open" or call.endswith(".open"):
                mode = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for keyword in node.keywords:
                    if keyword.arg == "mode" \
                            and isinstance(keyword.value, ast.Constant):
                        mode = keyword.value.value
                if isinstance(mode, str) and "a" in mode:
                    problems.append(
                        "boundary: %s opens a path in append mode; the "
                        "Phase 9 boundary is the only ledger append door"
                        % name)
            if isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("write_text", "write_bytes") \
                    and "PHASE9_LEDGER" in dotted(node.func.value):
                problems.append(
                    "boundary: %s writes directly through PHASE9_LEDGER; "
                    "the real intake directory belongs only to Phase 9"
                    % name)

        if name == ENGINE_PATH.name:
            receive_defs = [node for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == "receive"]
            if len(receive_defs) != 1:
                problems.append("boundary: receive must have exactly one "
                                "definition")
            else:
                calls = [dotted(node.func)
                         for node in ast.walk(receive_defs[0])
                         if isinstance(node, ast.Call)]
                if "_phase15().receive" not in calls:
                    problems.append(
                        "boundary: receive no longer delegates to Phase "
                        "15's carrier into the Phase 9 boundary")
                if any(call.endswith(".register") for call in calls):
                    problems.append(
                        "boundary: receive invokes a registration method "
                        "directly instead of the standing Phase 15 carrier")
    return problems


# ------------------------------------------------------------ derived status

def derive_intake_status(*, ledger_bytes: bytes, security_register: dict,
                         phase10_status: dict, phase13_status: dict,
                         graph: dict, matrix: dict | None,
                         cuts: list[dict], intake_root: Path) -> dict:
    """INTAKE_STATUS.json, derived. Six questions, six keys, never one
    green status: operational readiness (machinery), receipt state
    (boundary + workflow, side by side), security assessment (the
    reviewers' own words), gate state (Phase 11's derivation),
    authorization state and candidate decision (Phase 13's ladder).
    Every value comes from a live input handed to this function."""
    intake = _phase9()
    ops10 = _phase10()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    subject = ledger["subjectArtifact"]
    candidate = ops10._active_candidate(graph)
    if candidate["artifact_id"] != subject["identifier"]:
        raise BoundaryViolation(
            "CANDIDATE IDENTITY FAIL: the graph's active candidate %s is "
            "not the ledger subject %s"
            % (candidate["artifact_id"], subject["identifier"]))

    effective = intake.effective_statuses(ledger)
    entries = ledger.get("entries", [])
    security_entries = [e for e in entries
                        if e.get("source") == "security-review"]
    accepted_security = [
        e["intakeId"] for e in security_entries
        if e.get("gateEligible") and effective[e["intakeId"]] == "ACCEPTED"]
    boundary = derive_receipt_register(ledger)
    workflow = _phase15().derive_receipt_register(
        ledger, security_register, intake_root)
    gate = security_register.get("securityGate", {})
    conflict = security_register.get("reviewConflict")
    assessments = [
        {"intakeId": s.get("intakeId"),
         "overallAssessment": s.get("overallAssessment"),
         "contractValid": not s.get("contractProblems")}
        for s in security_register.get("acceptedSubmissions", [])]

    scenarios = (matrix or {}).get("scenarios", [])
    all_as_expected = bool(scenarios) and all(
        row.get("result") == "AS_EXPECTED" for row in scenarios)

    floor = phase13_status.get("authorizationFloor", {})
    return {
        "schemaVersion": 1,
        "purpose": "the Phase 16 derived intake status: six permanently "
                   "separate questions — operational readiness, receipt "
                   "state, security assessment, security gate, "
                   "authorization state, candidate decision",
        "subjectArtifact": {
            "identifier": subject["identifier"],
            "imageDigest": subject["imageDigest"],
            "signingStatus": subject["signingStatus"],
            "frozen": bool(subject.get("frozen")),
            "artifactState": ("FROZEN" if subject.get("frozen")
                              else "NOT_FROZEN"),
            "graphRole": candidate.get("relationship"),
            "candidateState": phase10_status.get("currentState"),
        },
        "operationalReadiness": {
            "intakePathReady": all_as_expected,
            "scenarios": len(scenarios),
            "allAsExpected": all_as_expected,
            "basis": "every route/failure scenario re-executes AS_EXPECTED "
                     "against the real engines; readiness is a statement "
                     "about machinery and is never evidence about the "
                     "artifact",
        },
        "receipt": {
            "boundary": boundary,
            "workflow": {"overall": workflow["overall"],
                         "entries": workflow["entries"]},
            "note": "the boundary view answers whether evidence crossed; "
                    "the workflow view (Phase 15) answers where it stands "
                    "in the pipeline; neither is an assessment",
        },
        "securityAssessment": {
            "acceptedSubmissions": assessments,
            "conflict": conflict,
            "humanDecisionRequired": conflict is not None,
            "baselineCounts": security_register.get("counts", {}),
            "note": "assessments are the reviewers' recorded words; the "
                    "repository holds them and never averages, upgrades, "
                    "or resolves them on its own",
        },
        "securityGate": {
            "status": gate.get("status"),
            "basis": gate.get("basis"),
            "derivedBy": "qualification/phase11/tools/"
                         "security_review_ops.py derive_security_gate",
        },
        "authorization": {
            "authorizationState": phase13_status.get("authorizationState"),
            "authorized":
                phase13_status.get("authorizationState") == "AUTHORIZED",
            "floorSatisfied": floor.get("satisfied"),
            "floorMissing": floor.get("missing"),
        },
        "candidateDecision": {
            "decision": phase13_status.get("candidateDecision"),
            "derivedBy": "the Phase 13 most-restrictive-first ladder",
        },
        "evidenceState": {
            "ledgerSha256": _sha256(ledger_bytes),
            "ledgerEntries": len(entries),
            "securityReviewIntakes": len(security_entries),
            "acceptedRealSecurityReviews": len(accepted_security),
            "acceptedRealSubmissions": sorted(accepted_security),
            "basis": "counted from the real Phase 9 ledger; zero is "
                     "reported as zero",
        },
        "cuts": [{"cutId": c.get("cutId"),
                  "asOf": (c.get("cut") or {}).get("asOf"),
                  "ledgerSha256": (c.get("cut") or {}).get("ledgerSha256"),
                  "seal": (c.get("cut") or {}).get("seal")}
                 for c in cuts],
        "derivedFrom": {
            "ledger": "qualification/phase9/intake/LEDGER.json (read-only)",
            "securityRegister": "qualification/phase11/"
                                "security-findings.json",
            "candidateStatus": "qualification/phase10/candidate-status.json",
            "authorizationStatus": "qualification/phase13/"
                                   "authorization-status.json",
            "artifactGraph": "qualification/phase10/artifacts/"
                             "artifact-graph.json",
            "matrix": "qualification/phase16/MATRIX.json",
            "note": "derived, never hand-edited; run sync-status and "
                    "verify refuses drift",
        },
        "note": "No key here implies another. Receipt ACCEPTED is not a "
                "security approval; a security approval is not gate "
                "satisfaction; gate satisfaction is not authorization; "
                "and no favorable word appears without the external "
                "evidence that makes it.",
    }


def intake_status_from_disk() -> dict:
    return derive_intake_status(
        ledger_bytes=PHASE9_LEDGER.read_bytes(),
        security_register=load_json(PHASE11_REGISTER),
        phase10_status=load_json(PHASE10_STATUS),
        phase13_status=load_json(PHASE13_STATUS),
        graph=load_json(PHASE10_GRAPH),
        matrix=load_json(MATRIX_PATH) if MATRIX_PATH.is_file() else None,
        cuts=committed_cuts(),
        intake_root=PHASE9_LEDGER.parent,
    )


def sync_status(write: bool = True) -> tuple[dict, list[str]]:
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    derived = intake_status_from_disk()
    if PHASE9_LEDGER.read_bytes() != ledger_bytes:
        return derived, ["the Phase 9 ledger changed underfoot; refusing"]
    if write:
        dump_json(STATUS_PATH, derived)
    return derived, []


# ------------------------------------------------------- scenario helpers

def _space(base: Path):
    return _phase14().RehearsalSpace(base)


def _scratch_register(space) -> dict:
    return _phase11().derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)


def _stage_file(space, name: str, text: str) -> Path:
    path = space.staging / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _valid_review() -> dict:
    return _inner("review-valid.json")


def _blocked_review() -> dict:
    return _inner("review-blocked.json")


def _stages(**kwargs) -> dict:
    """One scenario's per-stage results; unstated stages were not reached."""
    stages = {
        "identityCeremony": "NOT_REACHED", "intake": "NOT_REACHED",
        "binding": "NOT_REACHED", "reconciliation": "NOT_REACHED",
        "securityGate": "NOT_REACHED", "cut": "NOT_REACHED",
        "assembly": "NOT_REACHED",
    }
    stages.update(kwargs)
    return stages


def _all_criticals_review() -> dict:
    """A contract-valid APPROVED review dispositioning every baseline
    Critical as NOT_APPLICABLE with establishing text — constructed at run
    time from the committed baseline, never committed as favorable fixture
    bytes. Exists to execute the inherited-policy SATISFIED branch in a
    scratch universe."""
    record = _valid_review()
    baseline = load_json(PHASE11_BASELINE)
    findings = []
    for index, row in enumerate(
            (r for r in baseline["findings"]
             if r["severity"] == "Critical"), start=1):
        findings.append({
            "reviewer_finding_id": "P16-ALLCRIT-%d" % index,
            "title": "constructed scenario finding for %s" % row["advisory"],
            "severity": "Critical",
            "affected_component": (row.get("affectedPackages") or ["-"])[0],
            "applicability": "NOT_APPLICABLE",
            "evidence": "constructed scenario: the affected code path is "
                        "not reachable on the artifact as shipped; a real "
                        "review attaches the establishing analysis",
            "rationale": "constructed scenario: reachability analysis "
                         "establishes non-applicability",
            "recommended_disposition": "NOT_APPLICABLE",
            "baseline_advisory": row["advisory"],
        })
    record["findings"] = findings
    record["overall_assessment"] = "APPROVED"
    record["disposition"] = "APPROVED"
    return record


# ------------------------------------------------------------- scenarios

def _s01_no_submission(space) -> dict:
    """Read the current real universe without assuming it stays empty.

    At Phase 16 genesis this row records zero submissions. After the first
    legitimate intake it re-derives to that new state and remains a control
    over composition, while scratch controls continue to execute the original
    absence branch. A suite that hard-codes an empty real ledger would break
    precisely when the operator first succeeds.
    """
    ops14 = _phase14()
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    receipts = derive_receipt_register(ledger)
    register = load_json(PHASE11_REGISTER)
    gate = register["securityGate"]["status"]
    committed13 = load_json(PHASE13_STATUS)
    assembly = ops14.assemble_decision(ops14.real_universe(),
                                       committed13.get("evaluationDate"))
    committed_cut = load_json(PHASE15_CUTS / "CUT-001.json")
    cut_issues = ops14.verify_cut(committed_cut["cut"])
    comparison = ops14.compare_cut_to_ledger(committed_cut["cut"],
                                              ledger_bytes)
    if not comparison["ledgerChanged"]:
        rebuilt = build_real_cut("CUT-001", committed_cut["cut"]["asOf"])
        cut_relation_ok = rebuilt["cut"] == committed_cut["cut"]
        cut_relation = "current inputs reproduce CUT-001"
    else:
        # Append-only evidence after a historical cut is expected. It must be
        # named, and no intake that the cut included may disappear.
        cut_relation_ok = (bool(comparison["postCutIntakeIds"])
                           and not comparison["missingIntakeIds"])
        cut_relation = "CUT-001 remains historical; post-cut %s named" % (
            ",".join(comparison["postCutIntakeIds"]) or "nothing")
    rebuilt_register, register_issues = _phase11().sync_register(write=False)
    checks = [
        not cut_issues,
        cut_relation_ok,
        not register_issues,
        rebuilt_register == register,
        assembly["authorizationState"] ==
        committed13["authorizationState"],
        assembly["candidateDecision"] == committed13["candidateDecision"],
    ]
    entry_count = len(ledger.get("entries", []))
    expected = ("%d real ledger entr%s; boundary %s; gate %s; %s/%s; "
                "%s; real inputs self-consistent" % (
                    entry_count, "y" if entry_count == 1 else "ies",
                    receipts["overall"], gate,
                    assembly["authorizationState"],
                    assembly["candidateDecision"], cut_relation))
    observed = expected if all(checks) else (
        "DIVERGED: cut issues=%r, cut relation=%s, register issues=%r, "
        "assembly=%s/%s committed=%s/%s" % (
            cut_issues, cut_relation_ok, register_issues,
            assembly["authorizationState"], assembly["candidateDecision"],
            committed13["authorizationState"],
            committed13["candidateDecision"]))
    security_entries = [entry for entry in ledger.get("entries", [])
                        if entry.get("source") == "security-review"]
    return {
        "expected": expected,
        "observed": observed,
        "stages": _stages(
            identityCeremony=("NO_OBSERVATION_EXISTS"
                              if not security_entries
                              else "DERIVED_PER_ACCEPTED_SUBMISSION"),
            intake=receipts["overall"],
            binding=("NOT_REACHED" if not security_entries
                     else "DERIVED_BY_PHASE10"),
            reconciliation=("ZERO_SUBMISSIONS" if not security_entries
                            else "DERIVED_BY_PHASE11"),
            securityGate=gate, cut=cut_relation,
            assembly="%s / %s" % (assembly["authorizationState"],
                                  assembly["candidateDecision"])),
        "recovery": "deliver the handoff package to a real reviewer while "
                    "the state is empty; after evidence exists, follow the "
                    "derived gate and revision path without rewriting the "
                    "historical observation",
        "route": "REAL_UNIVERSE_READ_ONLY",
        "evidenceClass": ("NONE" if not security_entries
                          else "SECURITY_REVIEW_SET"),
        "designation": "REAL_UNIVERSE_READ_ONLY",
    }


def _s02_malformed(space) -> dict:
    staged = _stage_file(space, "malformed.json", "this is not json {")
    report = inspect_submission(staged)
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [], "2026-08-19", "phase16 scenario")
    receipts = derive_receipt_register(space.ledger())
    observed = "inspect %s; intake %s; receipt %s; bytes preserved" % (
        report["classification"], entry["status"],
        receipts["entries"][0]["receiptState"])
    return {
        "expected": "inspect MALFORMED; intake UNVERIFIABLE; receipt "
                    "UNVERIFIABLE; bytes preserved",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          identityCeremony="UNPARSEABLE"),
        "recovery": "resubmit a machine-readable record as a revision; "
                    "the original bytes stay preserved verbatim",
        "route": "inspect -> Phase 9 intake",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s03_missing_observation(space) -> dict:
    record = _valid_review()
    del record["independently_computed_digest"]
    report = inspect_submission(space.stage(record))
    entry = space.register("security-review", record)
    ceremony = identity_ceremony(record)
    register = _scratch_register(space)
    problems = register["acceptedSubmissions"][0]["contractProblems"]
    observed = ("inspect %s; intake %s; ceremony %s; advancement %s; "
                "contract-%s" % (
                    report["classification"], entry["status"],
                    ceremony["state"],
                    ceremony["artifactSpecificAdvancement"],
                    "invalid" if problems else "valid"))
    return {
        "expected": "inspect INCOMPLETE; intake ACCEPTED; ceremony "
                    "MISSING; advancement False; contract-invalid",
        "observed": observed,
        "stages": _stages(identityCeremony=ceremony["state"],
                          intake=entry["status"],
                          reconciliation="CONTRIBUTES_NOTHING_UNTIL_REVISED",
                          securityGate=register["securityGate"]["status"]),
        "recovery": "revise with the independently computed digest and "
                    "the stated measurement; the original is preserved",
        "route": "inspect -> Phase 9 intake -> Phase 11 contract",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s04_substituted_observation(space) -> dict:
    record = _valid_review()
    del record["digest_basis"]
    del record["digest_computation"]
    identity = load_json(PHASE11_IDENTITY)
    record["independently_computed_digest"] = \
        identity["subjectArtifact"]["imageDigest"]
    ceremony = identity_ceremony(record, identity)
    observed = "%s; advancement %s; never VERIFIED" % (
        ceremony["state"],
        ceremony["artifactSpecificAdvancement"]) \
        if ceremony["state"] != "VERIFIED" \
        else "VERIFIED from a copied expectation"
    return {
        "expected": "OBSERVED_UNVERIFIED; advancement False; never "
                    "VERIFIED",
        "observed": observed,
        "stages": _stages(identityCeremony=ceremony["state"]),
        "recovery": "the reviewer states the measurement (digest_basis + "
                    "digest_computation) over bytes they actually "
                    "computed; the repository never substitutes its "
                    "expectation",
        "route": "identity ceremony",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s05_wrong_observation(space) -> dict:
    record = _valid_review()
    record["independently_computed_digest"] = "5" * 64
    ceremony = identity_ceremony(record)
    problems = _phase11().validate_submission(record)
    observed = "ceremony %s; advancement %s; contract-%s" % (
        ceremony["state"], ceremony["artifactSpecificAdvancement"],
        "invalid" if problems else "valid")
    return {
        "expected": "ceremony MISMATCH; advancement False; "
                    "contract-invalid",
        "observed": observed,
        "stages": _stages(identityCeremony=ceremony["state"],
                          intake="NOT_ATTEMPTED",
                          reconciliation="REFUSED_BY_CONTRACT"),
        "recovery": "the reviewer verifies what bytes they measured; a "
                    "mismatch is evidence about the measurement, never "
                    "absorbed",
        "route": "identity ceremony -> Phase 11 contract",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s06_foreign_artifact(space) -> dict:
    record = _valid_review()
    foreign = "6" * 64
    record["artifact_digest"] = foreign
    record["artifactDigest"] = foreign
    record["independently_computed_digest"] = foreign
    report = inspect_submission(space.stage(record))
    entry = space.register("security-review", record)
    receipts = derive_receipt_register(space.ledger())
    binding = bind_record(record)
    observed = "inspect %s; intake %s; receipt %s; binding %s" % (
        report["classification"], entry["status"],
        receipts["entries"][0]["receiptState"], binding["result"])
    return {
        "expected": "inspect WRONG_ARTIFACT; intake ARTIFACT_MISMATCH; "
                    "receipt DOES_NOT_APPLY; binding ARTIFACT_MISMATCH",
        "observed": observed,
        "stages": _stages(identityCeremony="MISMATCH",
                          intake=entry["status"],
                          binding=binding["result"]),
        "recovery": "resubmit against the subject artifact, or establish "
                    "an explicit recorded artifact relationship; no "
                    "transfer happens by default",
        "route": "inspect -> Phase 9 intake -> Phase 10 applicability",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s07_ambiguous_identity(space) -> dict:
    record = _valid_review()
    record["artifactDigest"] = "7" * 64  # now disagrees with artifact_digest
    report = inspect_submission(space.stage(record))
    problems = _phase11().validate_submission(record)
    try:
        bind_record(record)
        binding = "bound despite ambiguity"
    except BoundaryViolation:
        binding = "REFUSED"
    observed = "inspect %s; contract-%s; binding %s" % (
        report["classification"], "invalid" if problems else "valid",
        binding)
    return {
        "expected": "inspect AMBIGUOUS_IDENTITY; contract-invalid; "
                    "binding REFUSED",
        "observed": observed,
        "stages": _stages(identityCeremony="AMBIGUOUS_FAILS_CLOSED",
                          intake="NOT_ATTEMPTED", binding=binding),
        "recovery": "the reviewer resubmits with one coherent artifact "
                    "identity; ambiguity is never resolved by choosing "
                    "the convenient digest",
        "route": "inspect",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s08_private_key(space) -> dict:
    staged = space.stage(_valid_review())
    key_text = "-----BEGIN " + "RSA PRIVATE KEY-----\nA\n"
    key_file = _stage_file(space, "notes.txt", key_text)
    report = inspect_submission(staged, [key_file])
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [key_file], "2026-08-19", "phase16 scenario")
    dest = space.intake_root / "security-review" / entry["intakeId"]
    leaked = "RSA PRIVATE" in entry.get("statusReason", "")
    observed = "inspect %s; intake %s before ingestion; %s; %s" % (
        report["classification"], entry["status"],
        "nothing copied" if not dest.exists() and not entry["files"]
        else "bytes were ingested",
        "value withheld" if not leaked else "value leaked")
    return {
        "expected": "inspect CREDENTIAL_BEARING; intake REJECTED before "
                    "ingestion; nothing copied; value withheld",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          identityCeremony="NOT_EXAMINED"),
        "recovery": "resubmit with the private material removed; treat "
                    "any real exposed key as compromised and record that "
                    "event",
        "route": "inspect -> Phase 9 intake (hygiene wall)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s09_nested_credential(space) -> dict:
    record = _valid_review()
    # Constructed at run time, three levels deep; no secret-shaped bytes
    # are ever committed.
    record["environment"] = {"ci": {"log": "session_" + "token = "
                                           + "Xy8" * 8}}
    staged = space.stage(record)
    report = inspect_submission(staged)
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [], "2026-08-19", "phase16 scenario")
    dest = space.intake_root / "security-review" / entry["intakeId"]
    observed = "inspect %s; intake %s before ingestion; %s" % (
        report["classification"], entry["status"],
        "nothing copied" if not dest.exists() and not entry["files"]
        else "bytes were ingested")
    return {
        "expected": "inspect CREDENTIAL_BEARING; intake REJECTED before "
                    "ingestion; nothing copied",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          identityCeremony="NOT_EXAMINED"),
        "recovery": "resubmit with the credential masked; nesting depth "
                    "is irrelevant to a byte-level scan",
        "route": "inspect -> Phase 9 intake (hygiene wall)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s10_attachment_credential(space) -> dict:
    staged = space.stage(_valid_review())
    token_text = "Authorization: Bearer " + "Ab1" * 10 + "\n"
    attachment = _stage_file(space, "capture.log", token_text)
    report = inspect_submission(staged, [attachment])
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [attachment], "2026-08-19",
                               "phase16 scenario")
    dest = space.intake_root / "security-review" / entry["intakeId"]
    observed = "inspect %s; intake %s before ingestion; %s" % (
        report["classification"], entry["status"],
        "nothing copied" if not dest.exists() and not entry["files"]
        else "bytes were ingested")
    return {
        "expected": "inspect CREDENTIAL_BEARING; intake REJECTED before "
                    "ingestion; nothing copied",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          identityCeremony="NOT_EXAMINED"),
        "recovery": "resubmit with the attachment sanitized; the refusal "
                    "names the class and file, never the value",
        "route": "inspect -> Phase 9 intake (hygiene wall)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s11_incomplete_finding(space) -> dict:
    record = _valid_review()
    del record["findings"][0]["evidence"]
    del record["findings"][0]["rationale"]
    report = inspect_submission(space.stage(record))
    entry = space.register("security-review", record)
    register = _scratch_register(space)
    problems = register["acceptedSubmissions"][0]["contractProblems"]
    gate = register["securityGate"]["status"]
    observed = ("inspect %s; intake %s; contract-%s; gate %s; "
                "contributes nothing" % (
                    report["classification"], entry["status"],
                    "invalid" if problems else "valid", gate))
    return {
        "expected": "inspect INCOMPLETE; intake ACCEPTED; "
                    "contract-invalid; gate UNDER_ANALYSIS; contributes "
                    "nothing",
        "observed": observed,
        "stages": _stages(identityCeremony="VERIFIED",
                          intake=entry["status"],
                          reconciliation="REFUSED_BY_CONTRACT",
                          securityGate=gate),
        "recovery": "revise with the finding completed; an incomplete "
                    "finding moves no baseline row",
        "route": "inspect -> Phase 9 intake -> Phase 11 contract",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s12_new_critical(space) -> dict:
    record = _inner("review-new-critical.json")
    space.register("security-review", record)
    register = _scratch_register(space)
    gate = register["securityGate"]
    new_rows = [r for r in register["findings"]
                if r.get("reconciliation") == "NEW_FINDING"]
    named = any(r.get("source_finding_id", "") in gate["basis"]
                for r in new_rows)
    observed = "%d new finding(s); gate %s; %s; %s" % (
        len(new_rows), gate["status"],
        "not SATISFIED" if gate["status"] != "SATISFIED" else "SATISFIED",
        "named by the reviewer's identifier" if named else "unnamed")
    return {
        "expected": "1 new finding(s); gate UNDER_ANALYSIS; not "
                    "SATISFIED; named by the reviewer's identifier",
        "observed": observed,
        "stages": _stages(identityCeremony="VERIFIED", intake="ACCEPTED",
                          binding="APPLIES",
                          reconciliation="NEW_FINDING first-class",
                          securityGate=gate["status"]),
        "recovery": "the new Critical enters triage for its own "
                    "identifier and blocks until dispositioned through "
                    "the Phase 11 lifecycle",
        "route": "Phase 9 intake -> Phase 11 reconciliation",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s13_contradictory_reviewers(space) -> dict:
    space.register("security-review", _valid_review())
    space.register("security-review", _blocked_review())
    register = _scratch_register(space)
    conflict = register["reviewConflict"]
    boundary = derive_receipt_register(space.ledger())
    workflow = _phase15().derive_receipt_register(
        space.ledger(), register, space.intake_root)
    universe = _phase14().build_universe(space, security_register=register)
    assembly = _phase14().assemble_decision(universe, "2026-08-19")
    observed = ("%s; effective %s; gate %s; boundary %s; workflow %s; "
                "assembly %s" % (
                    conflict["classification"] if conflict else "no conflict",
                    conflict["effectiveAssessment"] if conflict else "-",
                    register["securityGate"]["status"],
                    boundary["overall"], workflow["overall"],
                    "non-authorized"
                    if assembly["authorizationState"] != "AUTHORIZED"
                    else "AUTHORIZED"))
    return {
        "expected": "CONTRADICTORY_CONCLUSIONS; effective BLOCKED; gate "
                    "BLOCKED; boundary ACCEPTED; workflow "
                    "CONFLICT_REQUIRES_DECISION; assembly non-authorized",
        "observed": observed,
        "stages": _stages(identityCeremony="VERIFIED",
                          intake=boundary["overall"],
                          reconciliation=conflict["classification"]
                          if conflict else "-",
                          securityGate=register["securityGate"]["status"],
                          assembly=assembly["authorizationState"]),
        "recovery": "both submissions are preserved; resolution is a "
                    "recorded human decision in Phase 11's outcome "
                    "vocabulary, and the effective assessment stays the "
                    "most blocking until then",
        "route": "Phase 9 intake -> Phase 11 reconciliation -> Phase 14 "
                 "assembly",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s14_post_cut_evidence(space) -> dict:
    ops14 = _phase14()
    space.register("security-review", _valid_review())
    frozen = space.ledger_bytes()

    def cut_over(raw: bytes) -> dict:
        return ops14.build_evidence_cut(
            ledger_bytes=raw, graph_bytes=PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")

    cut = cut_over(frozen)
    space.register("security-review", _blocked_review())
    comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
    replay = cut_over(frozen)
    observed = "%s; historical cut %s" % (
        "post-cut intake named"
        if comparison["postCutIntakeIds"] == ["INTAKE-002"]
        else "post-cut intake missed",
        "byte-identical" if replay == cut else "changed")
    return {
        "expected": "post-cut intake named; historical cut byte-identical",
        "observed": observed,
        "stages": _stages(intake="ACCEPTED",
                          cut="post-cut evidence excluded and named"),
        "recovery": "a later decision over a later cut may supersede; the "
                    "sealed cut is never edited and absorbs nothing",
        "route": "Phase 9 intake -> Phase 14 cut",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s15_revision(space) -> dict:
    original = space.register("security-review", _valid_review())
    original_path = (space.intake_root / "security-review"
                     / original["intakeId"] / "record.json")
    before = original_path.read_bytes()
    corrected = _valid_review()
    corrected["scope"] += " (revised: corrected typo)"
    revision = space.register("security-review", corrected,
                              revises=original["intakeId"])
    receipts = derive_receipt_register(space.ledger())
    by_id = {r["intakeId"]: r["receiptState"] for r in receipts["entries"]}
    observed = "%s; original %s; original %s; revision %s" % (
        revision["intakeId"],
        "byte-identical" if original_path.read_bytes() == before
        else "rewritten",
        by_id[original["intakeId"]], by_id[revision["intakeId"]])
    return {
        "expected": "INTAKE-001-R1; original byte-identical; original "
                    "SUPERSEDED; revision ACCEPTED",
        "observed": observed,
        "stages": _stages(intake="ACCEPTED then SUPERSEDED by revision"),
        "recovery": "the derived views follow the latest applicable "
                    "revision; the ledger preserves every original",
        "route": "Phase 9 intake (revision chain)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s16_tampered_ledger(space) -> dict:
    space.register("security-review", _valid_review())
    ledger = space.ledger()
    ledger["entries"][0]["statusReason"] = "edited by hand"
    _phase9().dump_ledger(space.ledger_path, ledger)
    issues = _phase9().verify_intake(space.intake_root, space.ledger())
    try:
        space.register("security-review", _blocked_review())
        refused = "append accepted"
    except SystemExit as error:
        refused = "append refused" if "tampered" in str(error) \
            else "append failed otherwise"
    observed = "%s; %s" % (
        "seal broken" if issues.get("sealBroken") else "seal not detected",
        refused)
    return {
        "expected": "seal broken; append refused",
        "observed": observed,
        "stages": _stages(intake="TAMPER_DETECTED"),
        "recovery": "restore the ledger from the committed history; the "
                    "commit is the tamper-evident time",
        "route": "Phase 9 intake (seal wall)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s17_resealed_entry(space) -> dict:
    """The stronger tamper: edit an entry and recompute its seal. The
    entry-level seal alone cannot catch a full reseal; the sealed cut's
    ledger pin does, and this scenario executes exactly that detection."""
    ops14 = _phase14()
    space.register("security-review", _blocked_review())
    frozen = space.ledger_bytes()
    cut = ops14.build_evidence_cut(
        ledger_bytes=frozen, graph_bytes=PHASE10_GRAPH.read_bytes(),
        security_register_bytes=b"{}", alpha_register_bytes=b"{}",
        assignments=[], policies=[], risks=[], authorizations=[],
        revocations=[], resolutions=[], as_of="2026-08-19")
    intake = _phase9()
    ledger = space.ledger()
    ledger["entries"][0]["statusReason"] = "quietly improved"
    ledger["entries"][0]["seal"] = intake.seal_entry(ledger["entries"][0])
    intake.dump_ledger(space.ledger_path, ledger)
    issues = intake.verify_intake(space.intake_root, space.ledger())
    comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
    observed = "entry seals %s; cut pin %s" % (
        "hold (reseal is self-consistent)"
        if not issues.get("sealBroken") else "broken",
        "names the change" if comparison["ledgerChanged"]
        else "missed the change")
    return {
        "expected": "entry seals hold (reseal is self-consistent); cut "
                    "pin names the change",
        "observed": observed,
        "stages": _stages(intake="RESEAL_ATTEMPTED",
                          cut="ledgerSha256 pin detects the reseal"),
        "recovery": "the committed ledger bytes and every sealed cut pin "
                    "the pre-tamper state; restore from history and "
                    "record the event",
        "route": "Phase 9 intake -> Phase 14 cut (pin wall)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s18_tampered_cut(space) -> dict:
    ops14 = _phase14()
    cut = ops14.build_evidence_cut(
        ledger_bytes=space.ledger_bytes(),
        graph_bytes=PHASE10_GRAPH.read_bytes(),
        security_register_bytes=b"{}", alpha_register_bytes=b"{}",
        assignments=[], policies=[], risks=[], authorizations=[],
        revocations=[], resolutions=[], as_of="2026-08-19")
    tampered = copy.deepcopy(cut)
    tampered["ledgerEntries"] = 999
    issues = ops14.verify_cut(tampered)
    observed = "tampered cut %s; intact cut %s" % (
        "fails its seal" if any("seal" in issue or "IMMUTABILITY" in issue
                                for issue in issues)
        else "passed verification",
        "verifies" if not ops14.verify_cut(cut) else "fails")
    return {
        "expected": "tampered cut fails its seal; intact cut verifies",
        "observed": observed,
        "stages": _stages(cut="IMMUTABILITY FAIL on edit"),
        "recovery": "a change to a sealed cut is a new cut, never an "
                    "edit; the tampered record is preserved as evidence "
                    "of the event",
        "route": "Phase 14 cut (seal wall)",
        "evidenceClass": "NONE",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s19_expired_risk(space) -> dict:
    ops13 = _phase13()
    ops14 = _phase14()
    risk = ops14._inner("risk-acceptance-critical.json", PHASE13_FIXTURES)
    at_expiry = ops13.risk_acceptance_state(risk, risk["expires_at"])
    after = ops13.risk_acceptance_state(risk, "2027-01-01")
    try:
        ops13.risk_acceptance_state(risk, None)
        silent = "silence kept it standing"
    except ops13.BoundaryViolation:
        silent = "no as-of refuses"
    ladder = ops13.derive_authorization_state(
        standing=None, remediation=[], adverse=[], evidence_total=5,
        security_gate="SATISFIED", alpha_accepted=1,
        sufficiency={"policyState": "SUFFICIENCY_POLICY_ACTIVE",
                     "determination": "SUFFICIENT"},
        floor_missing=[], expired_risks=[risk["risk_id"]])
    observed = "%s at expiry; %s after; %s; ladder %s naming the expiry" % (
        at_expiry, after, silent,
        ladder["state"]
        if risk["risk_id"] in ladder["basis"] else "silent about it")
    return {
        "expected": "STANDING at expiry; EXPIRED after; no as-of refuses; "
                    "ladder REQUIRES_MORE_EVIDENCE naming the expiry",
        "observed": observed,
        "stages": _stages(assembly="expired acceptance cannot sustain a "
                                   "favorable state"),
        "recovery": "the accepting authority re-decides or the finding is "
                    "fixed; expiry is derived and nobody flips it by hand",
        "route": "Phase 13 risk acceptance -> Phase 13 ladder",
        "evidenceClass": "RISK_ACCEPTANCE",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s20_revoked_authority(space) -> dict:
    ops13 = _phase13()
    ops14 = _phase14()
    assignment = {
        "assignmentId": "ASSIGNMENT-916",
        "authorityId": "AUTH-SECURITY-OWNER",
        "identity": "Phase16 Constructed Owner",
        "assignedBy": "constructed scenario",
        "date": "2026-08-01",
        "basis": "constructed scenario",
    }
    assignment["seal"] = ops13.seal_record(assignment)
    revocation = {
        "revocationId": "REVOCATION-916",
        "targetAssignment": "ASSIGNMENT-916",
        "reason": "constructed scenario",
        "authority": "constructed scenario",
        "timestamp": "2026-08-10",
    }
    state = ops14.assignment_state(assignment, "2026-08-19", [revocation])
    standing = ops14.standing_assignments([assignment], "2026-08-19",
                                          [revocation])
    risk = ops14._inner("risk-acceptance-critical.json", PHASE13_FIXTURES)
    risk["authority"] = "Phase16 Constructed Owner"
    issues = ops13.validate_risk_acceptance(
        risk, standing, _phase9().subject_digests(space.ledger()),
        {fid: "Critical" for fid in risk["finding_ids"]})
    before_state = ops14.assignment_state(assignment, "2026-08-05",
                                          [revocation])
    observed = "%s at the cut; %d standing; acceptance %s; %s before " \
               "revocation" % (
                   state, len(standing),
                   "ineffective" if issues else "validated",
                   before_state)
    return {
        "expected": "REVOKED at the cut; 0 standing; acceptance "
                    "ineffective; STANDING before revocation",
        "observed": observed,
        "stages": _stages(assembly="revoked authority acts on nothing at "
                                   "this cut; earlier cuts still see it "
                                   "standing"),
        "recovery": "a new assignment through the Phase 13 registry; "
                    "revocation is a record, never an edit",
        "route": "Phase 13/14 authority evaluation",
        "evidenceClass": "AUTHORITY_ASSIGNMENT",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s21_internal_authorized_json(space) -> dict:
    ops13 = _phase13()
    ops14 = _phase14()
    record = ops14._inner("authorization-internal-authorized.json",
                          PHASE13_FIXTURES)
    record["evidence_cut"] = {
        "ledgerSha256": _sha256(space.ledger_bytes()),
        "ledgerEntries": 0,
        "intakeIds": [],
    }
    sealed = dict(record)
    sealed["seal"] = ops13.seal_record(sealed)
    universe = ops14.build_universe(space, authorizations=[sealed])
    assembly = ops14.assemble_decision(universe, "2026-08-19")
    row = assembly["inputs"]["authorizations"][0]
    floor_named = any("ACCEPTED intake" in issue or "floor" in issue
                      for issue in row.get("refusal", []))
    observed = "%s; row %s; %s; state %s" % (
        "refused" if row["state"] == "REFUSED" else "honored",
        row["state"],
        "absent floor named" if floor_named else "floor not named",
        assembly["authorizationState"])
    return {
        "expected": "refused; row REFUSED; absent floor named; state "
                    "EVIDENCE_PENDING",
        "observed": observed,
        "stages": _stages(assembly="internal AUTHORIZED JSON REFUSED"),
        "recovery": "authorization exists only as a validated external "
                    "authority decision over a satisfied floor; there is "
                    "no internal path to it",
        "route": "Phase 14 assembly -> Phase 13 validation",
        "evidenceClass": "AUTHORIZATION",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s22_fixture_to_real_path(space) -> dict:
    # The isolated ledger carries the real subject identity but no copied
    # evidence. Registration still executes the production Phase 9 code path;
    # the real file is byte-compared by the scenario runner. Keeping the
    # scratch universe empty makes this control stable after legitimate real
    # submissions arrive.
    wrapper = _wrapper("review-valid.json")
    entry = _phase9().register(space.ledger_path, "security-review",
                               space.stage(wrapper), [], "2026-08-19",
                               "phase16 scenario")
    floor = _phase13().authorization_floor(space.ledger())
    observed = "%s: %s; floor still missing %d" % (
        entry["status"],
        "a fixture is never evidence"
        if "fixture is never evidence" in entry["statusReason"]
        else entry["statusReason"], len(floor))
    return {
        "expected": "REJECTED: a fixture is never evidence; floor still "
                    "missing 5",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          assembly="fixture satisfies no floor source"),
        "recovery": "real evidence carries no fixture marker; there is "
                    "no fixture bypass and no way to promote one",
        "route": "Phase 9 intake (fixture wall, real code path)",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s23_unsupported_shape(space) -> dict:
    record = _inner("review-unsupported-shape.json")
    report = inspect_submission(space.stage(record))
    ops14 = _phase14()
    try:
        ops14.classify_evidence(record)
        routed = "routed"
    except ops14.BoundaryViolation:
        routed = "router refuses"
    entry = space.register("security-review", record)
    observed = "%s; inspect %s; intake %s; favorable prose moved nothing" \
               % (routed, report["classification"], entry["status"])
    return {
        "expected": "router refuses; inspect UNSUPPORTED_EVIDENCE_SHAPE; "
                    "intake INCOMPLETE; favorable prose moved nothing",
        "observed": observed,
        "stages": _stages(intake=entry["status"],
                          reconciliation="NEVER_REACHED — an unsupported "
                                         "shape is not evidence"),
        "recovery": "the reviewer resubmits in the committed contract "
                    "shape; unknown shapes never become generic evidence",
        "route": "inspect -> Phase 14 router -> Phase 9 intake",
        "evidenceClass": "UNSUPPORTED",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s24_historical_reconstruction(space) -> dict:
    ops13 = _phase13()
    ops14 = _phase14()
    universe, record = ops14.authorized_universe(space)
    earlier = ops14.assemble_decision(universe, "2026-08-19")
    revocation = {
        "revocation_id": "REVOCATION-001",
        "target_authorization": record["authorization_id"],
        "artifact_digest": record["artifact_digest"],
        "reason": "constructed scenario: revoked after the earlier cut",
        "authority": "Constructed Fixture Release Authority",
        "timestamp": "2026-09-01",
        "evidence": "constructed scenario",
    }
    revocation["seal"] = ops13.seal_record(revocation)
    later = ops14.assemble_decision(dict(universe,
                                         revocations=[revocation]),
                                    "2026-09-02")
    replay = ops14.assemble_decision(universe, "2026-08-19")
    observed = "earlier %s; later %s; replay %s" % (
        earlier["authorizationState"], later["authorizationState"],
        replay["authorizationState"])
    return {
        "expected": "earlier AUTHORIZED; later REVOKED; replay AUTHORIZED",
        "observed": observed,
        "stages": _stages(cut="each assembly seals its own cut",
                          assembly="history re-assembled from its own "
                                   "immutable inputs, never rewritten"),
        "recovery": "a historical state is reconstructed by re-assembling "
                    "that cut's inputs; the mutable current state is "
                    "never the shortcut",
        "route": "Phase 14 assembly (fixture universe)",
        "evidenceClass": "AUTHORIZATION",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


def _s25_gate_satisfied_floor_still_refuses(space) -> dict:
    space.register("security-review", _all_criticals_review())
    register = _scratch_register(space)
    gate = register["securityGate"]["status"]
    universe = _phase14().build_universe(space, security_register=register)
    assembly = _phase14().assemble_decision(universe, "2026-08-19")
    missing = assembly["inputs"]["authorizationFloor"]["missing"]
    named = {m.split(":")[0] for m in missing}
    observed = "gate %s by inherited policy; assembly %s; floor missing " \
               "%s" % (gate, assembly["authorizationState"],
                       ", ".join(sorted(named)) or "nothing")
    return {
        "expected": "gate SATISFIED by inherited policy; assembly "
                    "ALPHA_EVIDENCE_PENDING; floor missing "
                    "alpha-feedback, hardware, second-approval, signing",
        "observed": observed,
        "stages": _stages(identityCeremony="VERIFIED", intake="ACCEPTED",
                          binding="APPLIES",
                          reconciliation="every Critical dispositioned by "
                                         "establishing evidence",
                          securityGate=gate,
                          assembly=assembly["authorizationState"]),
        "recovery": "a satisfied security gate is one gate; the Phase 13 "
                    "floor still names every absent source, and only "
                    "their owners can act",
        "route": "Phase 9 intake -> Phase 11 gate -> Phase 14 assembly",
        "evidenceClass": "SECURITY_REVIEW",
        "designation": "FIXTURE_DEMONSTRATION_ONLY",
    }


#: The Phase 16 scenario catalog. Every MATRIX.json and
#: FAILURE_RECOVERY_MATRIX.json row is produced by executing one of these
#: against the real engines — S01 read-only over the real universe, the
#: rest in scratch universes.
SCENARIOS = (
    ("PH16-S01", "No submission (real universe)", _s01_no_submission),
    ("PH16-S02", "Malformed submission", _s02_malformed),
    ("PH16-S03", "Missing artifact observation", _s03_missing_observation),
    ("PH16-S04", "Expected digest substituted for observation",
     _s04_substituted_observation),
    ("PH16-S05", "Wrong observed digest", _s05_wrong_observation),
    ("PH16-S06", "Foreign artifact", _s06_foreign_artifact),
    ("PH16-S07", "Ambiguous identity", _s07_ambiguous_identity),
    ("PH16-S08", "Private key attachment", _s08_private_key),
    ("PH16-S09", "Nested credential", _s09_nested_credential),
    ("PH16-S10", "Attachment credential", _s10_attachment_credential),
    ("PH16-S11", "Incomplete finding", _s11_incomplete_finding),
    ("PH16-S12", "New Critical finding", _s12_new_critical),
    ("PH16-S13", "Contradictory reviewers", _s13_contradictory_reviewers),
    ("PH16-S14", "Evidence after an earlier cut", _s14_post_cut_evidence),
    ("PH16-S15", "Revised submission", _s15_revision),
    ("PH16-S16", "Tampered ledger entry", _s16_tampered_ledger),
    ("PH16-S17", "Resealed ledger entry", _s17_resealed_entry),
    ("PH16-S18", "Tampered evidence cut", _s18_tampered_cut),
    ("PH16-S19", "Expired risk acceptance", _s19_expired_risk),
    ("PH16-S20", "Revoked authority", _s20_revoked_authority),
    ("PH16-S21", "Internal AUTHORIZED JSON", _s21_internal_authorized_json),
    ("PH16-S22", "Favorable fixture to real intake",
     _s22_fixture_to_real_path),
    ("PH16-S23", "Unsupported novel evidence shape", _s23_unsupported_shape),
    ("PH16-S24", "Historical cut reconstruction",
     _s24_historical_reconstruction),
    ("PH16-S25", "Gate satisfied, floor still refuses",
     _s25_gate_satisfied_floor_still_refuses),
)


def run_scenarios() -> dict:
    """Execute every scenario; byte-compare every real immutable input
    before and after. One changed byte aborts the whole run. Returns
    {"matrix": ..., "recovery": ...} — the two derived views of one
    execution."""
    ops14 = _phase14()
    guarded = list(ops14.REAL_IMMUTABLE_INPUTS)
    for extra in (PHASE15_STATUS, PHASE15_MATRIX, STATUS_PATH, MATRIX_PATH,
                  RECOVERY_PATH, PINS_PATH):
        if extra.is_file():
            guarded.append(extra)
    if PHASE15_CUTS.is_dir():
        guarded.extend(sorted(PHASE15_CUTS.glob("*.json")))
    before = {path: path.read_bytes() for path in guarded}

    input_shas = {
        "ledger": _sha256(before[PHASE9_LEDGER]),
        "graph": _sha256(before[PHASE10_GRAPH]),
        "securityRegister": _sha256(PHASE11_REGISTER.read_bytes()),
        "baseline": _sha256(PHASE11_BASELINE.read_bytes()),
    }

    matrix_rows = []
    recovery_rows = []
    for scenario_id, title, fn in SCENARIOS:
        base = Path(tempfile.mkdtemp(prefix="phase16-scenario-"))
        try:
            outcome = fn(_space(base))
        finally:
            shutil.rmtree(base, ignore_errors=True)
        result = "AS_EXPECTED" if outcome["expected"] == outcome["observed"] \
            else "DIVERGED"
        stages = outcome["stages"]
        matrix_rows.append({
            "scenarioId": scenario_id,
            "scenario": title,
            "route": outcome["route"],
            "evidenceClass": outcome["evidenceClass"],
            "designation": outcome["designation"],
            "artifactIdentityResult": stages["identityCeremony"],
            "intakeResult": stages["intake"],
            "bindingResult": stages["binding"],
            "reconciliationResult": stages["reconciliation"],
            "securityGateEffect": stages["securityGate"],
            "cutResult": stages["cut"],
            "assemblyResult": stages["assembly"],
            "recoveryResult": "RECOVERY_PATH_DEFINED",
            "stages": stages,
            "expectedOutcome": outcome["expected"],
            "observed": outcome["observed"],
            "result": result,
            "inputSha256": input_shas,
        })
        recovery_rows.append({
            "scenarioId": scenario_id,
            "scenario": title,
            "expectedResult": outcome["expected"],
            "observedResult": outcome["observed"],
            "result": result,
            "recoveryPath": outcome["recovery"],
            "fixtureOnly":
                outcome["designation"] == "FIXTURE_DEMONSTRATION_ONLY",
            "executedAgainst": input_shas,
        })

    for path, raw in before.items():
        if path.read_bytes() != raw:
            raise BoundaryViolation(
                "REAL LEDGER INTEGRITY FAIL: %s changed during the "
                "scenarios; a demonstration must leave every real input "
                "byte-identical" % path.name)

    status13 = load_json(PHASE13_STATUS)
    common = {
        "subjectArtifact": status13["subjectArtifact"],
        "executedAgainst": dict(
            input_shas,
            authorizationState=status13["authorizationState"],
            candidateDecision=status13["candidateDecision"]),
        "realLedgerByteIdentical": True,
        "realEvidence": "EXTERNAL_EVIDENCE_REQUIRED — nothing in this "
                        "matrix is evidence about the subject artifact",
        "counts": {
            "scenarios": len(matrix_rows),
            "asExpected": sum(1 for r in matrix_rows
                              if r["result"] == "AS_EXPECTED"),
            "realUniverseReadOnly": sum(
                1 for r in matrix_rows
                if r["designation"] == "REAL_UNIVERSE_READ_ONLY"),
        },
    }
    matrix = dict(
        common,
        schemaVersion=1,
        purpose="the Phase 16 route matrix: every row is produced by "
                "executing its scenario against the real engines — the "
                "real-universe row read-only, everything else in scratch "
                "universes",
        scenarios=matrix_rows,
        note="the real-universe row is a statement about the real state; "
             "every FIXTURE_DEMONSTRATION_ONLY row is a statement about "
             "machinery, never about the artifact",
    )
    recovery = dict(
        common,
        schemaVersion=1,
        purpose="the Phase 16 failure-and-recovery matrix, derived from "
                "the same execution as MATRIX.json — never maintained by "
                "hand",
        rows=recovery_rows,
        note="the real-universe zero-evidence row (fixtureOnly false) "
             "stays distinguishable from every hypothetical fixture run",
    )
    return {"matrix": matrix, "recovery": recovery}


def matrix_problems() -> list[str]:
    if not MATRIX_PATH.is_file():
        return ["MATRIX.json is absent; run build-matrix"]
    if not RECOVERY_PATH.is_file():
        return ["FAILURE_RECOVERY_MATRIX.json is absent; run build-matrix"]
    derived = run_scenarios()
    diverged = [row["scenarioId"] for row in derived["matrix"]["scenarios"]
                if row["result"] != "AS_EXPECTED"]
    if diverged:
        return ["scenario(s) %s diverged from their expected outcome"
                % ", ".join(diverged)]
    problems = []
    if load_json(MATRIX_PATH) != derived["matrix"]:
        problems.append("committed MATRIX.json does not reproduce from "
                        "executing the scenarios; run build-matrix and "
                        "review the diff")
    if load_json(RECOVERY_PATH) != derived["recovery"]:
        problems.append("committed FAILURE_RECOVERY_MATRIX.json does not "
                        "reproduce from executing the scenarios; run "
                        "build-matrix and review the diff")
    return problems


# ---------------------------------------------------------------- verify

def verify_fixtures() -> list[str]:
    """Every Phase 16 fixture carries all three markers and an unmarked
    inner record; the real intake tree carries no marker anywhere (the
    latter through the Phase 15 sweep, unchanged)."""
    issues = []
    if not FIXTURES_DIR.is_dir():
        issues.append("fixtures: the fixtures directory is missing")
        return issues
    names = sorted(FIXTURES_DIR.glob("*.json"))
    if not names:
        issues.append("fixtures: the fixtures directory is empty")
    for path in names:
        try:
            record = load_json(path)
        except json.JSONDecodeError:
            issues.append("fixtures: %s is unparseable" % path.name)
            continue
        if not (record.get("fixtureClass") == FIXTURE_MARKER
                and record.get("fixture") is True
                and record.get("test_fixture_only") is True):
            issues.append(
                "fixtures: %s does not carry all three markers "
                "(fixtureClass, fixture, test_fixture_only)" % path.name)
        inner = record.get("record")
        if is_fixture(inner):
            issues.append(
                "fixtures: %s marks its inner record; the inner record is "
                "what a real reviewer would send, and a marker there "
                "makes the valid-path demonstrations vacuous" % path.name)
    issues.extend("real-tree: %s" % issue
                  for issue in _phase15().verify_fixtures()
                  if issue.startswith(("real", "fixtures: real")))
    return issues


def handoff_problems() -> list[str]:
    issues = []
    ops15 = _phase15()
    if HANDOFF16_PATH.is_file():
        text = ops15._normalized_markdown(
            HANDOFF16_PATH.read_text(encoding="utf-8"))
        for statement in HANDOFF16_REQUIRED_STATEMENTS:
            if statement not in text:
                issues.append("handoff: REVIEWER_HANDOFF.md no longer "
                              "states: %s" % statement)
    else:
        issues.append("handoff: REVIEWER_HANDOFF.md is missing")
    if not CEREMONY_DOC_PATH.is_file():
        issues.append("handoff: IDENTITY_CEREMONY.md is missing")
    issues.extend("phase15 handoff: %s" % issue
                  for issue in ops15.handoff_problems())
    return issues


def status_problems() -> list[str]:
    derived, problems = sync_status(write=False)
    if problems:
        return ["status: %s" % p for p in problems]
    if not STATUS_PATH.is_file():
        return ["status: INTAKE_STATUS.json is absent; run sync-status"]
    if load_json(STATUS_PATH) != derived:
        return ["status: committed INTAKE_STATUS.json does not reproduce "
                "from its inputs; run sync-status and review the diff"]
    return []


def ceremony_problems() -> list[str]:
    """The identity-ceremony semantics, executed: substitution never
    verifies, absence is MISSING, foreign bytes are MISMATCH, a stated
    matching measurement is VERIFIED, malformed input refuses."""
    problems = []
    identity = load_json(PHASE11_IDENTITY)
    expected = identity["subjectArtifact"]["imageDigest"]
    base = {
        "artifact_digest": expected, "artifactDigest": expected,
        "digest_basis": "image",
        "digest_computation": "stated measurement for the ceremony check",
    }
    checks = (
        (dict(base, independently_computed_digest=expected), "VERIFIED"),
        (dict(base), "MISSING"),
        (dict(base, independently_computed_digest="9" * 64), "MISMATCH"),
        ({"artifact_digest": expected,
          "independently_computed_digest": expected},
         "OBSERVED_UNVERIFIED"),
    )
    for record, wanted in checks:
        verdict = identity_ceremony(record, identity)
        if verdict["state"] != wanted:
            problems.append(
                "ceremony: expected %s, derived %s" % (wanted,
                                                       verdict["state"]))
        if wanted != "VERIFIED" and verdict["artifactSpecificAdvancement"]:
            problems.append(
                "ceremony: %s claims artifact-specific advancement"
                % wanted)
    try:
        identity_ceremony(
            {"independently_computed_digest": ["not", "a", "digest"]},
            identity)
        problems.append("ceremony: a malformed observation did not refuse")
    except BoundaryViolation:
        pass
    if tuple(IDENTITY_CEREMONY_STATES) != tuple(
            _phase15().IDENTITY_CEREMONY_STATES):
        problems.append("ceremony: the vocabulary drifted from Phase 15's")
    return problems


def authorization_wall_problems() -> list[str]:
    """No AUTHORIZED input can manufacture authorization: the committed
    Phase 13 status must equal a fresh read-only assembly of the real
    universe, and an internal AUTHORIZED record over an empty scratch
    universe must be REFUSED with the absent floor named."""
    problems = []
    ops14 = _phase14()
    committed = load_json(PHASE13_STATUS)
    assembly = ops14.assemble_decision(ops14.real_universe(),
                                       committed.get("evaluationDate"))
    for field in ("authorizationState", "candidateDecision"):
        if assembly[field] != committed[field]:
            problems.append(
                "assembly: the real universe derives %s %r but the "
                "committed Phase 13 status says %r"
                % (field, assembly[field], committed[field]))
    base = Path(tempfile.mkdtemp(prefix="phase16-authwall-"))
    try:
        outcome = _s21_internal_authorized_json(_space(base))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    if outcome["expected"] != outcome["observed"]:
        problems.append("authorization wall: %s" % outcome["observed"])
    return problems


def register_reproducibility_problems() -> list[str]:
    derived, problems = _phase11().sync_register(write=False)
    if problems:
        return ["register: %s" % p for p in problems]
    if load_json(PHASE11_REGISTER) != derived:
        return ["register: committed security-findings.json does not "
                "reproduce from its inputs"]
    return []


def verify_all() -> list[str]:
    issues: list[str] = []
    for name in PACKAGE_FILES:
        if not (PHASE16 / name).is_file():
            issues.append("package: %s is missing" % name)
    for name in PACKAGE_TOOL_FILES:
        if not (PHASE16 / name).is_file():
            issues.append("package: %s is missing" % name)
    issues += ["vocabulary: %s" % p
               for p in forbidden_vocabulary_problems()]
    issues += verify_fixtures()
    issues += handoff_problems()
    issues += ["pins: %s" % p for p in contract_pin_problems()]
    issues += ["boundary: %s" % p for p in engine_boundary_problems()]
    issues += ["subject: %s" % p
               for p in _phase14().subject_unsigned_problems()]
    issues += ["cuts: %s" % p for p in cut_problems()]
    issues += ["ceremony: %s" % p for p in ceremony_problems()]
    if not issues:
        issues += register_reproducibility_problems()
        issues += ["authorization: %s" % p
                   for p in authorization_wall_problems()]
    if not issues:
        issues += ["matrix: %s" % p for p in matrix_problems()]
        issues += status_problems()
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 16 security-review intake operations verify clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_build_matrix(_args) -> int:
    derived = run_scenarios()
    diverged = [row["scenarioId"] for row in derived["matrix"]["scenarios"]
                if row["result"] != "AS_EXPECTED"]
    if diverged:
        for row in derived["matrix"]["scenarios"]:
            if row["result"] != "AS_EXPECTED":
                print("%s DIVERGED:\n  expected %s\n  observed %s"
                      % (row["scenarioId"], row["expectedOutcome"],
                         row["observed"]))
        return 2
    dump_json(MATRIX_PATH, derived["matrix"])
    dump_json(RECOVERY_PATH, derived["recovery"])
    print("matrices written: %d scenario(s), all AS_EXPECTED; the "
          "real-universe row is read-only and every other row is "
          "FIXTURE_DEMONSTRATION_ONLY"
          % derived["matrix"]["counts"]["scenarios"])
    return 0


def _cmd_sync_status(_args) -> int:
    derived, problems = sync_status(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("INTAKE_STATUS.json derived: boundary %s; workflow %s; gate %s; "
          "authorization %s; decision %s"
          % (derived["receipt"]["boundary"]["overall"],
             derived["receipt"]["workflow"]["overall"],
             derived["securityGate"]["status"],
             derived["authorization"]["authorizationState"],
             derived["candidateDecision"]["decision"]))
    return 0


def _cmd_status(_args) -> int:
    derived, problems = sync_status(write=False)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("subject artifact:   %s (%s)"
          % (derived["subjectArtifact"]["identifier"],
             derived["subjectArtifact"]["signingStatus"]))
    print("operational:        intake path ready = %s (%d scenarios)"
          % (derived["operationalReadiness"]["intakePathReady"],
             derived["operationalReadiness"]["scenarios"]))
    print("receipt (boundary): %s"
          % derived["receipt"]["boundary"]["overall"])
    print("receipt (workflow): %s"
          % derived["receipt"]["workflow"]["overall"])
    print("evidence:           %d ledger entries; %d accepted real "
          "security review(s)"
          % (derived["evidenceState"]["ledgerEntries"],
             derived["evidenceState"]["acceptedRealSecurityReviews"]))
    print("security gate:      %s" % derived["securityGate"]["status"])
    print("authorization:      %s"
          % derived["authorization"]["authorizationState"])
    print("candidate decision: %s"
          % derived["candidateDecision"]["decision"])
    return 0


def _cmd_prepare(args) -> int:
    manifest = prepare(Path(args.out))
    print("handoff package prepared at %s (%d files, sha256-pinned)"
          % (args.out, len(manifest["files"])))
    print("it creates no review; the only submission door is the Phase 9 "
          "intake")
    return 0


def _cmd_inspect(args) -> int:
    report = inspect_submission(Path(args.record),
                                [Path(p) for p in args.attach])
    print("classification: %s" % report["classification"])
    print("basis: %s" % report["basis"])
    for problem in report.get("contractProblems") or []:
        print("contract: %s" % problem)
    for problem in report.get("attachmentProblems") or []:
        print("attachments: %s" % problem)
    ceremony = report.get("identityCeremony")
    if ceremony:
        print("identity ceremony: %s" % ceremony["state"])
    print(report["note"])
    return 0 if report["inspectionPassed"] else 2


def _cmd_receive(args) -> int:
    entry = receive(Path(args.record), [Path(p) for p in args.attach],
                    args.received_on, args.submitted_by, args.revises)
    print("%s %s %s" % (entry["intakeId"], entry["status"],
                        entry.get("statusReason", "")))
    print("(the Phase 9 boundary decided this outcome; this command only "
          "carried the paths through the Phase 15 wrapper)")
    return 0


def _cmd_validate(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    if is_fixture(record):
        print("the record carries a %s marker; a fixture is never a "
              "submission" % FIXTURE_MARKER)
        return 2
    verdict = validate_submission_record(
        record, [Path(path) for path in args.attach], args.received_on)
    for field in verdict["missingRequired"]:
        print("missing: %s" % field)
    for problem in verdict["contractProblems"]:
        print("contract: %s" % problem)
    for problem in verdict["attachmentProblems"]:
        print("attachments: %s" % problem)
    for credential_class in verdict["credentialClasses"]:
        print("credential hygiene: likely %s (value withheld)"
              % credential_class)
    for problem in verdict["timeProblems"]:
        print("time: %s" % problem)
    ceremony = verdict["identityCeremony"]
    print("complete: %s; contract-valid: %s; valid: %s; "
          "identity ceremony: %s"
          % (verdict["complete"], verdict["contractValid"],
             verdict["valid"],
             ceremony["state"]))
    print(verdict["note"])
    return 0 if verdict["valid"] else 2


def _cmd_bind(args) -> int:
    try:
        record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    result = bind_record(record, args.evidence_id)
    print("binding: %s (target %s)" % (result["result"],
                                       result["targetArtifact"]))
    print("reasoning: %s" % result["reasoning"])
    return 0 if result["result"] == "APPLIES" else 2


def _cmd_reconcile(args) -> int:
    ops11 = _phase11()
    if args.record:
        try:
            record = json.loads(
                Path(args.record).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            print("unreadable record: %s" % error)
            return 2
        _refuse_fixture(record, "reconcile")
        problems = ops11.validate_submission(record)
        if problems:
            for problem in problems:
                print(problem)
            print("refusing to reconcile a record that fails the contract")
            return 2
        result = ops11.reconcile_submission(record,
                                            load_json(PHASE11_BASELINE))
        for entry in result["classifications"]:
            print("%-24s %-28s %s" % (entry.get("reviewer_finding_id"),
                                      entry["classification"],
                                      entry.get("baseline_advisory") or "-"))
        print("unaddressed baseline rows: %d"
              % len(result["unaddressedBaseline"]))
        print("(analysis only; nothing was appended anywhere)")
        return 0
    derived, problems = ops11.sync_register(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("security-findings.json derived through the Phase 11 engine; "
          "gate %s" % derived["securityGate"]["status"])
    return 0


def _cmd_cut(args) -> int:
    record = build_real_cut(args.label, args.as_of)
    target = write_cut(record)
    print("%s written to %s (seal %s)"
          % (record["cutId"], target.relative_to(ROOT).as_posix(),
             record["cut"]["seal"][:12]))
    print("ledger %s, %d entries, as-of %s"
          % (record["cut"]["ledgerSha256"][:12],
             record["cut"]["ledgerEntries"], record["cut"]["asOf"]))
    return 0


def _cmd_assemble(args) -> int:
    ops14 = _phase14()
    as_of = args.as_of
    if as_of is None:
        as_of = load_json(PHASE13_STATUS).get("evaluationDate")
    assembly = ops14.assemble_decision(ops14.real_universe(), as_of)
    print("authorization state: %s" % assembly["authorizationState"])
    print("candidate decision:  %s" % assembly["candidateDecision"])
    print("favorable evidence:  %d row(s)"
          % len(assembly["favorableEvidence"]))
    print("floor missing:       %s"
          % (", ".join(assembly["inputs"]["authorizationFloor"]["missing"])
             or "nothing"))
    print("(assembled read-only through the Phase 14 assembler; nothing "
          "was written)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser(
        "verify", help="package, vocabulary, pins, fixtures, ceremony, "
                       "matrix, status, cuts; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    matrix = commands.add_parser(
        "build-matrix", help="execute every scenario and write MATRIX.json "
                             "+ FAILURE_RECOVERY_MATRIX.json")
    matrix.set_defaults(func=_cmd_build_matrix)

    sync = commands.add_parser(
        "sync-status", help="derive INTAKE_STATUS.json from live inputs")
    sync.set_defaults(func=_cmd_sync_status)

    status = commands.add_parser(
        "status", help="print the derived intake status without writing")
    status.set_defaults(func=_cmd_status)

    prep = commands.add_parser(
        "prepare", help="assemble the reviewer handoff package (creates "
                        "no review)")
    prep.add_argument("--out", required=True,
                      help="destination directory outside the repository; "
                           "must not exist")
    prep.set_defaults(func=_cmd_prepare)

    ins = commands.add_parser(
        "inspect", help="classify one prospective submission read-only "
                        "(inspection is not acceptance)")
    ins.add_argument("--record", required=True)
    ins.add_argument("--attach", action="append", default=[])
    ins.set_defaults(func=_cmd_inspect)

    recv = commands.add_parser(
        "receive", help="register one real submission through the Phase 9 "
                        "intake (the boundary decides)")
    recv.add_argument("--record", required=True)
    recv.add_argument("--attach", action="append", default=[])
    recv.add_argument("--received-on", required=True)
    recv.add_argument("--submitted-by", required=True)
    recv.add_argument("--revises", default=None)
    recv.set_defaults(func=_cmd_receive)

    val = commands.add_parser(
        "validate", help="contract + completeness + identity ceremony for "
                         "one record (read-only)")
    val.add_argument("record")
    val.add_argument("--attach", action="append", default=[])
    val.add_argument(
        "--received-on", default=None,
        help="explicit intake date for future/ordering checks; no clock is "
             "consulted")
    val.set_defaults(func=_cmd_validate)

    bind = commands.add_parser(
        "bind", help="Phase 10 applicability for one record (read-only; "
                     "DOES_NOT_APPLY is the default for other artifacts)")
    bind.add_argument("--record", required=True)
    bind.add_argument("--evidence-id", default=None)
    bind.set_defaults(func=_cmd_bind)

    rec = commands.add_parser(
        "reconcile", help="derive the register through the Phase 11 "
                          "engine, or classify one record read-only")
    rec.add_argument("--record", default=None,
                     help="classify this record only; append nothing")
    rec.set_defaults(func=_cmd_reconcile)

    cut = commands.add_parser(
        "cut", help="seal an evidence cut over the real universe "
                    "(append-only, single standing archive)")
    cut.add_argument("--label", required=True, help="CUT-NNN")
    cut.add_argument("--as-of", default=None,
                     help="operator-stated evaluation date (mandatory once "
                          "any expiring record exists)")
    cut.set_defaults(func=_cmd_cut)

    asm = commands.add_parser(
        "assemble", help="assemble the real-universe decision read-only "
                         "through the Phase 14 assembler")
    asm.add_argument("--as-of", default=None)
    asm.set_defaults(func=_cmd_assemble)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 15 security-review execution operations.

Phases 9-14 built and rehearsed the external-evidence pipeline. Phase 15
is the first-production-use operational layer for its highest-priority
workflow, the independent security review: the operator commands that
prepare the reviewer handoff, receive a real submission through the one
door, validate it, reconcile it, cut sealed evidence snapshots, and
derive the consequences — composed entirely from the standing engines:

* Phase 9  ``intake.py``                — the only door evidence enters
* Phase 10 ``candidate_ops.py``         — graph, applicability, candidate
* Phase 11 ``security_review_ops.py``   — contract, reconciliation, gate
* Phase 12 ``alpha_ops.py``             — Alpha register and sufficiency
* Phase 13 ``release_authority_ops.py`` — authority, risk, authorization
* Phase 14 ``evidence_execution_ops.py``— router, cuts, assembly, scratch

Nothing here re-implements a rule an earlier phase owns, and nothing
here can author the external evidence the decision requires. The derived
receipt state machine has no favorable state; the identity ceremony
never copies the repository's expected digest into the reviewer-observed
field; the failure/recovery matrix is derived by executing every
scenario against the real engines in scratch universes; and
``EXTERNAL_STATUS.json`` keeps four questions permanently separate:
operational readiness, evidence state, gate state, candidate decision.

Determinism: no clocks. Dates come from records or the operator; the
commit is the tamper-evident time.
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

ROOT = Path(__file__).resolve().parents[4]
PHASE15 = ROOT / "qualification" / "phase15"
TRACK = PHASE15 / "security-review-execution"
FIXTURES_DIR = TRACK / "fixtures"
CUTS_DIR = TRACK / "cuts"
STATUS_PATH = TRACK / "EXTERNAL_STATUS.json"
MATRIX_PATH = TRACK / "FAILURE_RECOVERY_MATRIX.json"
HANDOFF_PATH = TRACK / "REVIEW_HANDOFF.md"

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
PHASE11_REGISTER = ROOT / "qualification" / "phase11" / "security-findings.json"
PHASE12_TOOL = ROOT / "qualification" / "phase12" / "tools" / "alpha_ops.py"
PHASE13_TOOL = (
    ROOT / "qualification" / "phase13" / "tools" / "release_authority_ops.py")
PHASE13_STATUS = ROOT / "qualification" / "phase13" / "authorization-status.json"
PHASE14_TOOL = (
    ROOT / "qualification" / "phase14" / "tools" / "evidence_execution_ops.py")

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: The documents this track must carry. verify fails if any is absent.
PACKAGE_FILES = (
    "EXECUTION_GUIDE.md", "REVIEW_HANDOFF.md", "RECEIPT_PROTOCOL.md",
    "SUBMISSION_ROUTING.md", "RECONCILIATION_PROTOCOL.md",
    "CONFLICT_POLICY.md", "EVIDENCE_CUT_PROTOCOL.md", "DECISION_BOUNDARY.md",
    "EXTERNAL_STATUS.json", "VERIFY_PHASE15.py", "README.md",
    "FAILURE_RECOVERY_MATRIX.json",
)

#: The sentence the handoff package must state verbatim (§16 of the brief).
HANDOFF_REQUIRED_STATEMENT = (
    "A reviewer may submit an unfavorable result. The intake system is not "
    "designed to convert that result into a favorable status.")

def _normalized_markdown(text: str) -> str:
    """Markdown flattened for statement checks: emphasis and blockquote
    markers dropped, whitespace collapsed."""
    return " ".join(text.replace(">", " ").replace("*", " ").split())


#: The Phase 11 commissioning files prepare-review packages for the reviewer.
HANDOFF_PHASE11_FILES = (
    "REQUEST.md", "REVIEW_SCOPE.md", "ARTIFACT_IDENTITY.json",
    "FINDINGS_BASELINE.json", "REVIEWER_INSTRUCTIONS.md",
    "SUBMISSION_SCHEMA.json", "VERIFY_SUBMISSION.py",
)

#: Marked example submissions included in the handoff. The intake refuses
#: them structurally; they exist so the reviewer sees the shape, never so
#: anyone submits them.
HANDOFF_EXAMPLES = (
    "review-approved-with-conditions.json",
    "review-blocked.json",
)

# ------------------------------------------------------------ receipt states

#: The derived receipt vocabulary. UNVERIFIABLE extends the brief's minimum
#: set because it is Phase 9's own word for a submission whose claims cannot
#: be checked; the two layers must not disagree about one entry. There is no
#: favorable state: receipt bookkeeping can never satisfy a gate.
RECEIPT_STATES = (
    "AWAITING_SUBMISSION", "RECEIVED", "REJECTED", "INCOMPLETE",
    "UNVERIFIABLE", "DOES_NOT_APPLY", "ACCEPTED_FOR_RECONCILIATION",
    "RECONCILED", "CONFLICT_REQUIRES_DECISION", "SUPERSEDED", "EXPIRED",
)

#: Observable successions between derivations. Absence is refusal;
#: ``receipt_transition`` enforces it and the guard suite sweeps every
#: state's successors for favorable tokens.
RECEIPT_TRANSITIONS = {
    "AWAITING_SUBMISSION": {"RECEIVED", "REJECTED", "INCOMPLETE",
                            "UNVERIFIABLE", "DOES_NOT_APPLY",
                            "ACCEPTED_FOR_RECONCILIATION"},
    "RECEIVED": {"ACCEPTED_FOR_RECONCILIATION", "SUPERSEDED", "EXPIRED"},
    "REJECTED": {"SUPERSEDED"},
    "INCOMPLETE": {"SUPERSEDED"},
    "UNVERIFIABLE": {"SUPERSEDED"},
    "DOES_NOT_APPLY": {"SUPERSEDED"},
    "ACCEPTED_FOR_RECONCILIATION": {"RECONCILED", "CONFLICT_REQUIRES_DECISION",
                                    "SUPERSEDED", "EXPIRED"},
    "RECONCILED": {"CONFLICT_REQUIRES_DECISION", "SUPERSEDED", "EXPIRED"},
    "CONFLICT_REQUIRES_DECISION": {"RECONCILED", "SUPERSEDED"},
    "SUPERSEDED": set(),
    "EXPIRED": set(),
}

#: Tokens that must never appear in the receipt machine — a receipt state
#: is bookkeeping about a submission's handling, never a verdict about the
#: artifact. Swept over the vocabulary and every transition target.
FORBIDDEN_RECEIPT_TOKENS = (
    "APPROVED", "SATISFIED", "PASS", "AUTHORIZED", "CLEAN", "NO_FINDINGS",
)

#: Precedence for the overall receipt state: the most decision-demanding
#: standing entry names the workflow's position. This orders visibility,
#: not favorability — nothing here is a verdict.
_RECEIPT_PRECEDENCE = (
    "CONFLICT_REQUIRES_DECISION", "RECONCILED", "ACCEPTED_FOR_RECONCILIATION",
    "RECEIVED", "EXPIRED", "DOES_NOT_APPLY", "UNVERIFIABLE", "INCOMPLETE",
    "REJECTED",
)

# ------------------------------------------------------- identity ceremony

#: Phase 12's identity vocabulary, reused verbatim: the reviewer's own
#: measurement of the artifact, kept permanently distinct from the
#: repository's expectation.
IDENTITY_CEREMONY_STATES = (
    "VERIFIED", "OBSERVED_UNVERIFIED", "MISSING", "MISMATCH",
)

CUT_ID = re.compile(r"^CUT-\d{3}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_MODULE_CACHE: dict[str, object] = {}


class BoundaryViolation(ValueError):
    """A refused derivation, transition, command, or record."""


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
    return _load_module("phase9_intake_for_phase15", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_ops_for_phase15", PHASE10_TOOL)


def _phase11():
    return _load_module("phase11_ops_for_phase15", PHASE11_TOOL)


def _phase12():
    return _load_module("phase12_ops_for_phase15", PHASE12_TOOL)


def _phase13():
    return _load_module("phase13_ops_for_phase15", PHASE13_TOOL)


def _phase14():
    return _load_module("phase14_ops_for_phase15", PHASE14_TOOL)


def is_fixture(record) -> bool:
    """Any one marker makes a record a fixture everywhere it is read —
    the Phase 13/14 rule, unchanged."""
    return isinstance(record, dict) and (
        record.get("fixtureClass") == FIXTURE_MARKER
        or record.get("test_fixture_only") is True
        or record.get("fixture") is True)


def _refuse_fixture(record, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: the record declares a %s marker — a fixture is never "
            "evidence" % (where, FIXTURE_MARKER))


def _date(value):
    import datetime
    return datetime.date.fromisoformat(str(value)[:10])


# ------------------------------------------------------ receipt state machine

def receipt_transition(current: str, target: str) -> str:
    """Advance the derived receipt view; refusal is the default."""
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
    return target


def forbidden_vocabulary_problems() -> list[str]:
    """The favorable-token sweep, callable by verify and by the guards."""
    problems = []
    for state in RECEIPT_STATES:
        for token in FORBIDDEN_RECEIPT_TOKENS:
            if token in state:
                problems.append(
                    "receipt state %r contains forbidden token %r" %
                    (state, token))
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
    return problems


def receipt_state_of(entry: dict, effective_status: str,
                     record: dict | None,
                     contract_problems: list[str] | None,
                     in_unresolved_conflict: bool,
                     as_of: str | None = None) -> str:
    """One entry's derived receipt state. Stored nowhere, ever."""
    if effective_status == "SUPERSEDED":
        return "SUPERSEDED"
    stored = entry.get("status")
    if stored == "REJECTED":
        return "REJECTED"
    if stored == "INCOMPLETE":
        return "INCOMPLETE"
    if stored == "UNVERIFIABLE":
        return "UNVERIFIABLE"
    if stored == "ARTIFACT_MISMATCH":
        return "DOES_NOT_APPLY"
    if stored != "ACCEPTED":
        raise BoundaryViolation(
            "entry %s carries stored status %r, which is outside the "
            "Phase 9 vocabulary" % (entry.get("intakeId"), stored))
    if record is not None and record.get("expires_at"):
        if as_of is None:
            raise BoundaryViolation(
                "%s carries expires_at; its receipt state cannot be "
                "evaluated without an operator-stated as-of — silence "
                "does not keep evidence effective" % entry.get("intakeId"))
        if _date(as_of) > _date(record["expires_at"]):
            return "EXPIRED"
    if not entry.get("gateEligible"):
        return "RECEIVED"
    if contract_problems is None:
        # No reconciliation output was derived for this derivation pass.
        return "ACCEPTED_FOR_RECONCILIATION"
    if contract_problems:
        return "RECEIVED"
    if in_unresolved_conflict:
        return "CONFLICT_REQUIRES_DECISION"
    return "RECONCILED"


def apply_conflict_resolution(conflict: dict | None, outcome: str) -> dict:
    """Record-shaped acknowledgement that a human resolved a conflict.

    The outcome must be in Phase 11's recorded vocabulary, and the Phase 14
    wall holds here too: an outcome that would be more favorable than the
    most blocking observation is refused. (Phase 11's outcome vocabulary
    contains no approving token, so the wall is checked, not merely
    assumed.)"""
    if conflict is None:
        raise BoundaryViolation("there is no conflict to resolve")
    ops11 = _phase11()
    ops11.validate_conflict_resolution(outcome)
    severity = ops11.ASSESSMENT_SEVERITY
    effective = conflict.get("effectiveAssessment")
    if outcome in severity and effective in severity \
            and severity[outcome] < severity[effective]:
        raise BoundaryViolation(
            "resolution %r is more favorable than the most blocking "
            "observation %r; the repository never selects the favorable "
            "interpretation" % (outcome, effective))
    return {
        "resolved": outcome != "RESOLUTION_REQUIRED",
        "outcome": outcome,
        "appliesTo": [s["intakeId"] for s in conflict.get("submissions", [])],
        "note": "a resolution is a recorded human decision; this structure "
                "carries it into the receipt view and changes no stored "
                "record",
    }


def derive_receipt_register(ledger: dict, register: dict | None,
                            intake_root: Path,
                            resolution: dict | None = None,
                            as_of: str | None = None) -> dict:
    """Receipt states for every security-review intake, plus the overall.

    ``register`` is the Phase 11 derived register over the same ledger
    (None for the pre-reconciliation view). ``resolution`` is the output
    of ``apply_conflict_resolution`` when a human has resolved a standing
    conflict. Everything is derived; nothing is written anywhere."""
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
    accepted = {}
    conflict = None
    if register is not None:
        accepted = {s["intakeId"]: s
                    for s in register.get("acceptedSubmissions", [])}
        conflict = register.get("reviewConflict")
    conflict_ids = set()
    if conflict is not None:
        conflict_ids = {s["intakeId"] for s in conflict.get("submissions", [])}
    resolved_ids = set()
    if resolution is not None and resolution.get("resolved"):
        resolved_ids = set(resolution.get("appliesTo", []))

    rows = []
    for entry in entries:
        intake_id = entry["intakeId"]
        record = None
        record_path = intake_root / "security-review" / intake_id / "record.json"
        if record_path.is_file():
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                record = None
        problems = None
        if intake_id in accepted:
            problems = accepted[intake_id].get("contractProblems") or []
        unresolved = intake_id in conflict_ids \
            and intake_id not in resolved_ids
        state = receipt_state_of(entry, effective[intake_id],
                                 record if isinstance(record, dict) else None,
                                 problems, unresolved, as_of)
        rows.append({
            "intakeId": intake_id,
            "receiptState": state,
            "storedStatus": entry.get("status"),
            "effectiveStatus": effective[intake_id],
        })

    standing = [r["receiptState"] for r in rows
                if r["receiptState"] != "SUPERSEDED"]
    overall = "AWAITING_SUBMISSION"
    for state in _RECEIPT_PRECEDENCE:
        if state in standing:
            overall = state
            break
    return {
        "overall": overall,
        "entries": rows,
        "basis": "derived from the ledger and the Phase 11 register; no "
                 "receipt state is stored, and none is favorable",
    }


# --------------------------------------------------------- identity ceremony

def identity_ceremony(record: dict, identity: dict | None = None) -> dict:
    """The reviewer-observed artifact identity, evaluated — never filled.

    The reviewer-supplied observation (``independently_computed_digest``)
    stays permanently distinct from the repository's expectation
    (``ARTIFACT_IDENTITY.json``). This function reads both and derives a
    state; it never writes the expected digest into the observed field,
    and a bare digest with no stated measurement (``digest_basis`` +
    ``digest_computation``) derives OBSERVED_UNVERIFIED — mechanically
    indistinguishable from a copied expectation, therefore insufficient
    for artifact-specific advancement."""
    _refuse_fixture(record, "identity ceremony")
    if identity is None:
        identity = load_json(PHASE11_IDENTITY)
    artifact = identity["subjectArtifact"]
    expected = {
        _normalize_digest(artifact[key])
        for key in ("imageDigest", "isoSha256", "qcow2Sha256",
                    "ociTarSha256", "rawSha256")
        if artifact.get(key)
    }
    observed = record.get("independently_computed_digest")
    if not isinstance(observed, str) or not observed.strip():
        return {
            "state": "MISSING",
            "observedDigest": None,
            "artifactSpecificAdvancement": False,
            "basis": "no independent observation exists; the repository's "
                     "expected digest is never substituted for one",
        }
    normalized = _normalize_digest(observed)
    if normalized not in expected:
        return {
            "state": "MISMATCH",
            "observedDigest": normalized,
            "artifactSpecificAdvancement": False,
            "basis": "the reviewer measured different bytes; a review of "
                     "other bytes satisfies nothing here (blocking "
                     "condition 6)",
        }
    basis_stated = bool(str(record.get("digest_basis") or "").strip())
    computation_stated = bool(
        str(record.get("digest_computation") or "").strip())
    if not (basis_stated and computation_stated):
        return {
            "state": "OBSERVED_UNVERIFIED",
            "observedDigest": normalized,
            "artifactSpecificAdvancement": False,
            "basis": "a matching digest with no stated measurement method "
                     "cannot be distinguished from a copied expectation; "
                     "recorded, insufficient on its own",
        }
    return {
        "state": "VERIFIED",
        "observedDigest": normalized,
        "artifactSpecificAdvancement": True,
        "basis": "the reviewer's own measurement matches a subject digest "
                 "and states how it was computed; whether the measurement "
                 "is honest stays a human judgment recorded in triage",
    }


# ------------------------------------------------------------- one-door I/O

def receive(record_path: Path, attachments: list[Path], received_on: str,
            submitted_by: str, revises: str | None = None,
            ledger_path: Path = PHASE9_LEDGER) -> dict:
    """Register one real security-review submission through the one door.

    This wrapper is deliberately thin: it resolves explicit paths and
    hands them to the Phase 9 ``register`` function unmodified. It has no
    append code, no pre-processing, and no opinion — anything the Phase 9
    boundary would reject, this call rejects, because the boundary is the
    code path. ``ledger_path`` exists so the guard suite can prove that
    equivalence in scratch universes; operational use is the real ledger."""
    record_path = Path(record_path)
    if not record_path.is_file():
        raise BoundaryViolation("refusing: record %s does not exist; this "
                                "command takes explicit paths only"
                                % record_path)
    resolved = []
    for attachment in attachments:
        attachment = Path(attachment)
        if not attachment.is_file():
            raise BoundaryViolation(
                "refusing: attachment %s does not exist" % attachment)
        resolved.append(attachment)
    return _phase9().register(ledger_path, "security-review", record_path,
                              resolved, received_on, submitted_by, revises)


def validate_submission_record(record: dict) -> dict:
    """Contract validation plus the identity ceremony, read-only.

    Validation is not acceptance: the only door is the Phase 9 intake."""
    problems = _phase11().validate_submission(record)
    ceremony = None
    if not is_fixture(record):
        ceremony = identity_ceremony(record)
    return {
        "contractProblems": problems,
        "contractValid": not problems,
        "identityCeremony": ceremony,
        "note": "validation is not acceptance; the Phase 9 intake is the "
                "only door",
    }


# ------------------------------------------------------------ evidence cuts

def _register_bytes(register: dict) -> bytes:
    """The canonical register serialization the Phase 14 assembler pins."""
    return json.dumps(register, sort_keys=True).encode("utf-8")


def build_real_cut(cut_id: str, as_of: str | None) -> dict:
    """A sealed evidence cut over the real universe, wrapped for the
    append-only ``cuts/`` directory. Derivation only — the Phase 14 cut
    machinery does all the sealing."""
    if not CUT_ID.match(cut_id):
        raise BoundaryViolation(
            "refusing: %r is not a cut identifier (CUT-NNN); ambiguity "
            "about which cut is which is how the wrong evidence gets "
            "decided on" % cut_id)
    if as_of is not None and not ISO_DATE.match(as_of):
        raise BoundaryViolation("as-of must be an ISO 8601 date")
    ops14 = _phase14()
    universe = ops14.real_universe()
    cut = ops14.build_evidence_cut(
        ledger_bytes=universe["ledger_bytes"],
        graph_bytes=universe["graph_bytes"],
        security_register_bytes=_register_bytes(
            universe["security_register"]),
        alpha_register_bytes=_register_bytes(universe["alpha_register"]),
        assignments=universe["assignments"],
        policies=universe["policies"],
        risks=universe["risks"],
        authorizations=universe["authorizations"],
        revocations=universe["revocations"],
        resolutions=universe["resolutions"],
        assignment_revocations=universe["assignment_revocations"],
        as_of=as_of,
    )
    return {
        "schemaVersion": 1,
        "cutId": cut_id,
        "cut": cut,
        "purpose": "a sealed identification of everything a decision at "
                   "this boundary may rely on; later evidence is named by "
                   "compare_cut_to_ledger, never absorbed here",
        "note": "derived and sealed; historical once committed — a later "
                "cut supersedes by pointing at this one, never by editing "
                "it",
    }


def write_cut(cut_record: dict) -> Path:
    """Append-only: a cut file is never overwritten."""
    CUTS_DIR.mkdir(parents=True, exist_ok=True)
    target = CUTS_DIR / ("%s.json" % cut_record["cutId"])
    if target.exists():
        raise BoundaryViolation(
            "refusing: %s already exists; cuts are append-only — a rerun "
            "is a reproduction, not a new cut" % target.name)
    dump_json(target, cut_record)
    return target


def committed_cuts() -> list[dict]:
    if not CUTS_DIR.is_dir():
        return []
    return [load_json(path) for path in sorted(CUTS_DIR.glob("CUT-*.json"))]


def cut_problems() -> list[str]:
    """Standing checks over the committed cuts: seals verify, names agree,
    the subject artifact is ours. Reproducibility against *changed* inputs
    is deliberately not asserted — a historical cut stays valid when later
    evidence arrives; ``compare_cut_to_ledger`` names the difference."""
    ops14 = _phase14()
    problems: list[str] = []
    if not CUTS_DIR.is_dir():
        return problems
    ledger = load_json(PHASE9_LEDGER)
    subject = ledger["subjectArtifact"]["identifier"]
    for path in sorted(CUTS_DIR.glob("*.json")):
        try:
            record = load_json(path)
        except json.JSONDecodeError:
            problems.append("cuts: %s is unparseable" % path.name)
            continue
        cut_id = record.get("cutId")
        if not cut_id or not CUT_ID.match(str(cut_id)):
            problems.append("cuts: %s carries no CUT-NNN identifier"
                            % path.name)
            continue
        if path.name != "%s.json" % cut_id:
            problems.append("cuts: %s names itself %s; the file name is "
                            "the identifier" % (path.name, cut_id))
        cut = record.get("cut") or {}
        issues = ops14.verify_cut(cut)
        problems.extend("cuts: %s: %s" % (cut_id, issue) for issue in issues)
        if cut.get("subjectArtifact") != subject:
            problems.append(
                "cuts: %s identifies subject %r, not %r" %
                (cut_id, cut.get("subjectArtifact"), subject))
    return problems


# ----------------------------------------------------------- handoff package

def prepare_review(out_dir: Path) -> dict:
    """Assemble the reviewer handoff package into an operator-named
    directory outside the repository. Creates no review, writes nothing
    inside the repository, invents nothing."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise BoundaryViolation(
            "refusing: %s already exists; prepare-review never overwrites"
            % out_dir)
    try:
        out_dir.resolve().relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise BoundaryViolation(
            "refusing: the handoff package is prepared outside the "
            "repository; %s is inside it" % out_dir)
    sources = [(PHASE11_PACKAGE / name, name)
               for name in HANDOFF_PHASE11_FILES]
    sources.append((HANDOFF_PATH, "REVIEW_HANDOFF.md"))
    for example in HANDOFF_EXAMPLES:
        sources.append((FIXTURES_DIR / example, "examples/%s" % example))
    for source, _name in sources:
        if not source.is_file():
            raise BoundaryViolation("refusing: %s is missing; an "
                                    "incomplete handoff is not a handoff"
                                    % source)
    handoff_text = _normalized_markdown(
        HANDOFF_PATH.read_text(encoding="utf-8"))
    if HANDOFF_REQUIRED_STATEMENT not in handoff_text:
        raise BoundaryViolation(
            "refusing: REVIEW_HANDOFF.md no longer states that an "
            "unfavorable result cannot be converted into a favorable "
            "status")
    for example in HANDOFF_EXAMPLES:
        if not is_fixture(load_json(FIXTURES_DIR / example)):
            raise BoundaryViolation(
                "refusing: example %s carries no fixture marker; an "
                "unmarked example is indistinguishable from evidence"
                % example)
    out_dir.mkdir(parents=True)
    (out_dir / "examples").mkdir()
    manifest_files = {}
    for source, name in sources:
        raw = source.read_bytes()
        (out_dir / name).write_bytes(raw)
        manifest_files[name] = {"bytes": len(raw), "sha256": _sha256(raw)}
    identity = load_json(PHASE11_IDENTITY)["subjectArtifact"]
    manifest = {
        "schemaVersion": 1,
        "purpose": "reviewer handoff package for the independent security "
                   "review of the frozen Alpha candidate",
        "subjectArtifact": {
            "identifier": identity["identifier"],
            "imageDigest": identity["imageDigest"],
        },
        "createsNoReview": True,
        "submissionDoor": "qualification/phase9/tools/intake.py register "
                          "--source security-review",
        "examplesAreNotEvidence": "files under examples/ carry "
                                  "TEST_FIXTURE_ONLY markers and the "
                                  "intake rejects them structurally",
        "files": manifest_files,
    }
    dump_json(out_dir / "HANDOFF_MANIFEST.json", manifest)
    return manifest


# ------------------------------------------------------------ derived status

def derive_external_status(*, ledger_bytes: bytes, security_register: dict,
                           phase10_status: dict, phase13_status: dict,
                           graph: dict, matrix: dict | None,
                           cuts: list[dict],
                           intake_root: Path) -> dict:
    """EXTERNAL_STATUS.json, derived. Four questions, four keys, never one
    green status. Every value comes from a live input handed to this
    function; nothing is hard-coded and nothing favorable can appear
    without the evidence that makes it."""
    intake = _phase9()
    ops10 = _phase10()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    subject = ledger["subjectArtifact"]
    candidate = ops10._active_candidate(graph)
    if candidate["artifact_id"] != subject["identifier"]:
        raise BoundaryViolation(
            "CANDIDATE IDENTITY FAIL: the graph's active candidate %s is "
            "not the ledger subject %s" %
            (candidate["artifact_id"], subject["identifier"]))

    effective = intake.effective_statuses(ledger)
    entries = ledger.get("entries", [])
    security_entries = [e for e in entries
                        if e.get("source") == "security-review"]
    accepted_security = [
        e["intakeId"] for e in security_entries
        if e.get("gateEligible") and effective[e["intakeId"]] == "ACCEPTED"]
    receipts = derive_receipt_register(ledger, security_register,
                                       intake_root)
    gate = security_register.get("securityGate", {})
    conflict = security_register.get("reviewConflict")
    baseline_rows = [r for r in security_register.get("findings", [])
                     if r.get("internal_id")]
    unaddressed = sum(1 for r in baseline_rows
                      if r.get("status") == "BASELINE")

    scenarios = (matrix or {}).get("scenarios", [])
    all_as_expected = bool(scenarios) and all(
        row.get("result") == "AS_EXPECTED" for row in scenarios)

    floor = phase13_status.get("authorizationFloor", {})
    return {
        "schemaVersion": 1,
        "purpose": "the Phase 15 derived external status: operational "
                   "readiness, evidence state, gate state, and candidate "
                   "decision, kept permanently separate",
        "subjectArtifact": {
            "identifier": subject["identifier"],
            "imageDigest": subject["imageDigest"],
            "signingStatus": subject["signingStatus"],
            "graphRole": candidate.get("relationship"),
            "candidateState": phase10_status.get("currentState"),
        },
        "operationalReadiness": {
            "pipelineReady": all_as_expected,
            "scenarios": len(scenarios),
            "allAsExpected": all_as_expected,
            "basis": "every failure/recovery scenario re-executes "
                     "AS_EXPECTED against the real engines in scratch "
                     "universes; readiness is a statement about machinery "
                     "and is never evidence about the artifact",
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
        "securityReview": {
            "receiptState": receipts["overall"],
            "receiptEntries": receipts["entries"],
            "gate": {"status": gate.get("status"),
                     "basis": gate.get("basis")},
            "conflict": conflict,
            "humanDecisionRequired": conflict is not None,
            "baselineCounts": security_register.get("counts", {}),
            "baselineRowsStillAtBaseline": unaddressed,
        },
        "authorization": {
            "authorizationState": phase13_status.get("authorizationState"),
            "candidateDecision": phase13_status.get("candidateDecision"),
            "authorized":
                phase13_status.get("authorizationState") == "AUTHORIZED",
            "floorSatisfied": floor.get("satisfied"),
            "floorMissing": floor.get("missing"),
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
            "matrix": "qualification/phase15/security-review-execution/"
                      "FAILURE_RECOVERY_MATRIX.json",
            "note": "derived, never hand-edited; run sync-status and "
                    "verify refuses drift",
        },
        "note": "Operational readiness is about machinery. Evidence state "
                "is counted, never assumed. The gate moves only on "
                "accepted external evidence. The candidate decision comes "
                "from the Phase 13 ladder. None of the four implies "
                "another, and no favorable word appears here without the "
                "external evidence that makes it.",
    }


def external_status_from_disk() -> dict:
    return derive_external_status(
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
    derived = external_status_from_disk()
    if PHASE9_LEDGER.read_bytes() != ledger_bytes:
        return derived, ["the Phase 9 ledger changed underfoot; refusing"]
    if write:
        dump_json(STATUS_PATH, derived)
    return derived, []


# -------------------------------------------- failure and recovery scenarios

def _space(base: Path):
    return _phase14().RehearsalSpace(base)


def _scratch_register(space) -> dict:
    """The Phase 11 register derived over a scratch space's ledger."""
    return _phase11().derive_register(
        load_json(PHASE11_BASELINE), space.ledger(),
        load_json(PHASE10_GRAPH), space.intake_root)


def _receipts_for(space, resolution=None, as_of=None) -> dict:
    return derive_receipt_register(space.ledger(), _scratch_register(space),
                                   space.intake_root, resolution, as_of)


def _valid_review() -> dict:
    return _phase14()._inner("review-approved-with-conditions.json",
                             FIXTURES_DIR)


def _blocked_review() -> dict:
    return _phase14()._inner("review-blocked.json", FIXTURES_DIR)


def _s_m01_no_review(space) -> tuple[str, str]:
    expected = "AWAITING_EXTERNAL_EVIDENCE + AWAITING_SUBMISSION"
    register = _scratch_register(space)
    receipts = _receipts_for(space)
    return expected, "%s + %s" % (register["securityGate"]["status"],
                                  receipts["overall"])


def _s_m02_valid_review(space) -> tuple[str, str]:
    expected = "ACCEPTED contract-valid RECONCILED; gate UNDER_ANALYSIS " \
               "not SATISFIED"
    entry = space.register("security-review", _valid_review())
    register = _scratch_register(space)
    receipts = _receipts_for(space)
    gate = register["securityGate"]["status"]
    observed = "%s contract-%s %s; gate %s not %s" % (
        entry["status"],
        "valid" if not register["acceptedSubmissions"][0]["contractProblems"]
        else "invalid",
        receipts["entries"][0]["receiptState"],
        gate, "SATISFIED" if gate != "SATISFIED" else "reached")
    return expected, observed


def _s_m03_wrong_digest(space) -> tuple[str, str]:
    expected = "ARTIFACT_MISMATCH + DOES_NOT_APPLY"
    record = _valid_review()
    foreign = "1" * 64
    record["artifact_digest"] = foreign
    record["artifactDigest"] = foreign
    record["independently_computed_digest"] = foreign
    entry = space.register("security-review", record)
    receipts = _receipts_for(space)
    return expected, "%s + %s" % (entry["status"],
                                  receipts["entries"][0]["receiptState"])


def _s_m04_missing_observation(space) -> tuple[str, str]:
    expected = "intake ACCEPTED; contract-invalid; receipt RECEIVED; " \
               "ceremony MISSING; advancement False"
    record = _valid_review()
    del record["independently_computed_digest"]
    entry = space.register("security-review", record)
    register = _scratch_register(space)
    receipts = _receipts_for(space)
    ceremony = identity_ceremony(record)
    observed = "intake %s; contract-%s; receipt %s; ceremony %s; " \
               "advancement %s" % (
                   entry["status"],
                   "invalid"
                   if register["acceptedSubmissions"][0]["contractProblems"]
                   else "valid",
                   receipts["entries"][0]["receiptState"],
                   ceremony["state"],
                   ceremony["artifactSpecificAdvancement"])
    return expected, observed


def _s_m05_malformed(space) -> tuple[str, str]:
    expected = "UNVERIFIABLE + UNVERIFIABLE"
    staged = space.staging / "malformed-record.json"
    staged.write_text("this is not json {", encoding="utf-8")
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [], "2026-08-19", "phase15 scenario")
    receipts = _receipts_for(space)
    return expected, "%s + %s" % (entry["status"],
                                  receipts["entries"][0]["receiptState"])


def _s_m06_credential(space) -> tuple[str, str]:
    expected = "REJECTED before ingestion; nothing copied"
    record = _valid_review()
    # Constructed at run time so no secret-shaped bytes are ever committed.
    record["environment_notes"] = "export api_" + "key = " + "Zk9" * 8
    entry = space.register("security-review", record)
    dest = space.intake_root / "security-review" / entry["intakeId"]
    observed = "%s before ingestion; %s" % (
        entry["status"],
        "nothing copied" if not dest.exists() and not entry["files"]
        else "bytes were ingested")
    return expected, observed


def _s_m07_private_key(space) -> tuple[str, str]:
    expected = "REJECTED before ingestion; nothing copied"
    staged = space.stage(_valid_review())
    key_file = space.staging / "notes.txt"
    # Constructed at run time; never committed as fixture bytes.
    key_file.write_text("-----BEGIN " + "RSA PRIVATE KEY-----\nA\n",
                        encoding="utf-8")
    entry = _phase9().register(space.ledger_path, "security-review", staged,
                               [key_file], "2026-08-19", "phase15 scenario")
    dest = space.intake_root / "security-review" / entry["intakeId"]
    observed = "%s before ingestion; %s" % (
        entry["status"],
        "nothing copied" if not dest.exists() and not entry["files"]
        else "bytes were ingested")
    return expected, observed


def _s_m08_new_finding(space) -> tuple[str, str]:
    expected = "NEW_FINDING preserved; baseline unrenumbered; no ID minted"
    record = _phase14()._inner("review-new-critical.json", FIXTURES_DIR)
    space.register("security-review", record)
    register = _scratch_register(space)
    baseline = load_json(PHASE11_BASELINE)
    new_rows = [r for r in register["findings"]
                if r.get("reconciliation") == "NEW_FINDING"]
    committed_ids = [r["internal_id"] for r in baseline["findings"]]
    register_ids = [r["internal_id"] for r in register["findings"]
                    if r.get("internal_id")]
    observed = "%s; baseline %s; %s" % (
        "NEW_FINDING preserved" if new_rows else "new finding lost",
        "unrenumbered" if register_ids == committed_ids else "renumbered",
        "no ID minted" if all(r["internal_id"] is None for r in new_rows)
        else "an ID was minted")
    return expected, observed


def _s_m09_omitted_baseline(space) -> tuple[str, str]:
    expected = "42 unaddressed rows stay BASELINE; silence measurable"
    space.register("security-review", _valid_review())
    register = _scratch_register(space)
    submission = register["acceptedSubmissions"][0]
    reconciliation = _phase11().reconcile_submission(
        _valid_review(), load_json(PHASE11_BASELINE))
    still_baseline = sum(1 for r in register["findings"]
                         if r.get("status") == "BASELINE")
    observed = "%d unaddressed rows stay BASELINE; %s" % (
        still_baseline,
        "silence measurable"
        if len(reconciliation["unaddressedBaseline"]) == still_baseline
        and not submission["contractProblems"]
        else "silence was not measured")
    return expected, observed


def _s_m10_revision(space) -> tuple[str, str]:
    expected = "INTAKE-001-R1; original byte-identical; original SUPERSEDED"
    original = space.register("security-review", _valid_review())
    original_record = (space.intake_root / "security-review"
                       / original["intakeId"] / "record.json")
    before = original_record.read_bytes()
    corrected = _valid_review()
    corrected["scope"] = corrected["scope"] + " (revised: corrected typo)"
    revision = space.register("security-review", corrected,
                              revises=original["intakeId"])
    receipts = _receipts_for(space)
    original_row = next(r for r in receipts["entries"]
                        if r["intakeId"] == original["intakeId"])
    observed = "%s; original %s; original %s" % (
        revision["intakeId"],
        "byte-identical" if original_record.read_bytes() == before
        else "rewritten",
        original_row["receiptState"])
    return expected, observed


def _s_m11_contradictory(space) -> tuple[str, str]:
    expected = "CONTRADICTORY_CONCLUSIONS; effective BLOCKED; receipt " \
               "CONFLICT_REQUIRES_DECISION"
    space.register("security-review", _valid_review())
    space.register("security-review", _blocked_review())
    register = _scratch_register(space)
    receipts = _receipts_for(space)
    conflict = register["reviewConflict"]
    observed = "%s; effective %s; receipt %s" % (
        conflict["classification"] if conflict else "no conflict derived",
        conflict["effectiveAssessment"] if conflict else "-",
        receipts["overall"])
    return expected, observed


def _s_m12_critical_unresolved(space) -> tuple[str, str]:
    expected = "gate UNDER_ANALYSIS; open Criticals named; not SATISFIED"
    record = _phase14()._inner("review-new-critical.json", FIXTURES_DIR)
    space.register("security-review", record)
    register = _scratch_register(space)
    gate = register["securityGate"]
    confirmed_criticals = [
        r for r in register["findings"]
        if str(r.get("severity", "")).lower() == "critical"
        and r.get("status") in ("CONFIRMED", "UNDER_REVIEW")]
    observed = "gate %s; %s; %s" % (
        gate["status"],
        "open Criticals named" if confirmed_criticals else "no Critical",
        "not SATISFIED" if gate["status"] != "SATISFIED" else "SATISFIED")
    return expected, observed


def _s_m13_risk_without_authority(space) -> tuple[str, str]:
    expected = "risk acceptance without authority is ineffective"
    ops13 = _phase13()
    ops14 = _phase14()
    risk = ops14._inner("risk-acceptance-critical.json",
                        ROOT / "qualification" / "phase13" / "fixtures")
    issues = ops13.validate_risk_acceptance(
        risk, [], _phase9().subject_digests(space.ledger()),
        {fid: "Critical" for fid in risk.get("finding_ids", [])})
    observed = ("risk acceptance without authority is ineffective"
                if issues else
                "a risk acceptance validated with no authority standing")
    return expected, observed


def _s_m14_expired_risk(space) -> tuple[str, str]:
    expected = "STANDING at expiry date; EXPIRED after it"
    ops13 = _phase13()
    ops14 = _phase14()
    risk = ops14._inner("risk-acceptance-critical.json",
                        ROOT / "qualification" / "phase13" / "fixtures")
    at_expiry = ops13.risk_acceptance_state(risk, risk["expires_at"])
    later = ops13.risk_acceptance_state(risk, "2027-12-01")
    return expected, "%s at expiry date; %s after it" % (at_expiry, later)


def _s_m15_fixture_to_real_path(space) -> tuple[str, str]:
    expected = "REJECTED: a fixture is never evidence"
    # The scratch ledger begins as a byte-copy of the real one, so the
    # registration below exercises exactly the real path with the real
    # code; the real file is byte-compared by the scenario runner.
    space.ledger_path.write_bytes(PHASE9_LEDGER.read_bytes())
    wrapper = _phase14()._fixture("review-approved-with-conditions.json",
                                  FIXTURES_DIR)
    entry = _phase9().register(space.ledger_path, "security-review",
                               space.stage(wrapper), [], "2026-08-19",
                               "phase15 scenario")
    observed = "%s: %s" % (
        entry["status"],
        "a fixture is never evidence"
        if "fixture is never evidence" in entry["statusReason"]
        else entry["statusReason"])
    return expected, observed


def _s_m16_post_cut(space) -> tuple[str, str]:
    expected = "post-cut intake named; historical cut byte-identical"
    ops14 = _phase14()
    space.register("security-review", _valid_review())
    frozen_bytes = space.ledger_bytes()

    def cut_over(raw: bytes) -> dict:
        return ops14.build_evidence_cut(
            ledger_bytes=raw, graph_bytes=PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")

    cut = cut_over(frozen_bytes)
    space.register("security-review", _blocked_review())
    comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
    replay = cut_over(frozen_bytes)
    observed = "%s; historical cut %s" % (
        "post-cut intake named"
        if comparison["postCutIntakeIds"] == ["INTAKE-002"]
        else "post-cut intake missed",
        "byte-identical"
        if json.dumps(replay, sort_keys=True)
        == json.dumps(cut, sort_keys=True) else "changed")
    return expected, observed


def _s_m17_tampered_record(space) -> tuple[str, str]:
    expected = "seal broken; append refused"
    space.register("security-review", _valid_review())
    ledger = space.ledger()
    ledger["entries"][0]["status"] = "ACCEPTED"
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
    return expected, observed


def _s_m18_candidate_identity(space) -> tuple[str, str]:
    expected = "CANDIDATE IDENTITY FAIL"
    ops14 = _phase14()
    ledger = space.ledger()
    ledger["subjectArtifact"]["identifier"] = "someone-else"
    _phase9().dump_ledger(space.ledger_path, ledger)
    universe = ops14.build_universe(space)
    try:
        ops14.assemble_decision(universe, None)
        observed = "the assembly accepted a mutated candidate"
    except ops14.BoundaryViolation as error:
        observed = "CANDIDATE IDENTITY FAIL" \
            if "CANDIDATE IDENTITY FAIL" in str(error) else str(error)
    return expected, observed


#: The failure-and-recovery scenarios (§17 of the phase brief). Every row
#: of FAILURE_RECOVERY_MATRIX.json is produced by executing one of these
#: against the real engines in a scratch universe.
SCENARIOS = (
    ("PH15-M01", "No review submitted", _s_m01_no_review),
    ("PH15-M02", "Valid artifact-bound review", _s_m02_valid_review),
    ("PH15-M03", "Wrong digest", _s_m03_wrong_digest),
    ("PH15-M04", "Missing independent observation",
     _s_m04_missing_observation),
    ("PH15-M05", "Malformed submission", _s_m05_malformed),
    ("PH15-M06", "Credential detected", _s_m06_credential),
    ("PH15-M07", "Private key submitted", _s_m07_private_key),
    ("PH15-M08", "New finding", _s_m08_new_finding),
    ("PH15-M09", "Baseline finding omitted", _s_m09_omitted_baseline),
    ("PH15-M10", "Reviewer revision", _s_m10_revision),
    ("PH15-M11", "Contradictory reviews", _s_m11_contradictory),
    ("PH15-M12", "Critical unresolved", _s_m12_critical_unresolved),
    ("PH15-M13", "Risk acceptance without authority",
     _s_m13_risk_without_authority),
    ("PH15-M14", "Expired risk acceptance", _s_m14_expired_risk),
    ("PH15-M15", "Fixture submitted to real ledger",
     _s_m15_fixture_to_real_path),
    ("PH15-M16", "Post-cut evidence", _s_m16_post_cut),
    ("PH15-M17", "Tampered sealed record", _s_m17_tampered_record),
    ("PH15-M18", "Candidate identity mutation", _s_m18_candidate_identity),
)


def run_scenarios() -> dict:
    """Execute every scenario in its own scratch universe; byte-compare
    every real immutable input before and after. One changed byte aborts
    the whole run."""
    ops14 = _phase14()
    guarded = list(ops14.REAL_IMMUTABLE_INPUTS)
    if STATUS_PATH.is_file():
        guarded.append(STATUS_PATH)
    if CUTS_DIR.is_dir():
        guarded.extend(sorted(CUTS_DIR.glob("*.json")))
    before = {path: path.read_bytes() for path in guarded}

    rows = []
    for scenario_id, title, fn in SCENARIOS:
        base = Path(tempfile.mkdtemp(prefix="phase15-scenario-"))
        try:
            expected, observed = fn(_space(base))
        finally:
            shutil.rmtree(base, ignore_errors=True)
        rows.append({
            "scenarioId": scenario_id,
            "scenario": title,
            "expectedOutcome": expected,
            "observed": observed,
            "result": "AS_EXPECTED" if expected == observed else "DIVERGED",
            "evidenceClass": "FIXTURE_DEMONSTRATION_ONLY",
            "realEvidenceStatus": "EXTERNAL_EVIDENCE_REQUIRED",
        })

    for path, raw in before.items():
        if path.read_bytes() != raw:
            raise BoundaryViolation(
                "REAL LEDGER INTEGRITY FAIL: %s changed during the "
                "scenarios; a demonstration must leave every real input "
                "byte-identical" % path.name)

    status13 = load_json(PHASE13_STATUS)
    return {
        "schemaVersion": 1,
        "purpose": "the derived failure-and-recovery matrix: every row is "
                    "produced by executing its scenario against the real "
                    "engines in a scratch universe, never by maintaining "
                    "prose",
        "subjectArtifact": status13["subjectArtifact"],
        "executedAgainst": {
            "ledgerSha256": _sha256(before[PHASE9_LEDGER]),
            "graphSha256": _sha256(before[PHASE10_GRAPH]),
            "securityRegisterSha256": _sha256(
                PHASE11_REGISTER.read_bytes()),
            "authorizationState": status13["authorizationState"],
            "candidateDecision": status13["candidateDecision"],
        },
        "realLedgerByteIdentical": True,
        "realEvidence": "EXTERNAL_EVIDENCE_REQUIRED — nothing in this "
                        "matrix is evidence about the subject artifact",
        "counts": {
            "scenarios": len(rows),
            "asExpected": sum(1 for r in rows
                              if r["result"] == "AS_EXPECTED"),
        },
        "scenarios": rows,
        "note": "FIXTURE_DEMONSTRATION_ONLY on every row: the machinery "
                "handling a scenario correctly proves the machinery, "
                "never the artifact.",
    }


def matrix_problems() -> list[str]:
    if not MATRIX_PATH.is_file():
        return ["FAILURE_RECOVERY_MATRIX.json is absent; run build-matrix"]
    derived = run_scenarios()
    diverged = [row["scenarioId"] for row in derived["scenarios"]
                if row["result"] != "AS_EXPECTED"]
    if diverged:
        return ["scenario(s) %s diverged from their expected outcome"
                % ", ".join(diverged)]
    if load_json(MATRIX_PATH) != derived:
        return ["committed FAILURE_RECOVERY_MATRIX.json does not reproduce "
                "from executing the scenarios; run build-matrix and review "
                "the diff"]
    return []


# ---------------------------------------------------------------- verify

def verify_fixtures() -> list[str]:
    """Every Phase 15 fixture carries all three markers; no marker exists
    anywhere in the real intake tree."""
    issues = []
    if FIXTURES_DIR.is_dir():
        for path in sorted(FIXTURES_DIR.glob("*.json")):
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
                    "(fixtureClass, fixture, test_fixture_only)"
                    % path.name)
    intake_root = PHASE9_LEDGER.parent
    for path in sorted(intake_root.rglob("*")):
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            record = load_json(path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict) and is_fixture(record):
            issues.append("real intake tree: %s carries a fixture marker"
                          % path.relative_to(ROOT).as_posix())
        for entry in (record.get("entries") or []) \
                if isinstance(record, dict) else []:
            if is_fixture(entry):
                issues.append(
                    "real ledger: entry %s carries a fixture marker"
                    % entry.get("intakeId"))
    return issues


def handoff_problems() -> list[str]:
    issues = []
    for name in HANDOFF_PHASE11_FILES:
        if not (PHASE11_PACKAGE / name).is_file():
            issues.append("handoff: Phase 11 package file %s is missing"
                          % name)
    if HANDOFF_PATH.is_file():
        text = _normalized_markdown(HANDOFF_PATH.read_text(encoding="utf-8"))
        if HANDOFF_REQUIRED_STATEMENT not in text:
            issues.append(
                "handoff: REVIEW_HANDOFF.md does not state that an "
                "unfavorable result cannot be converted into a favorable "
                "status")
    else:
        issues.append("handoff: REVIEW_HANDOFF.md is missing")
    for example in HANDOFF_EXAMPLES:
        path = FIXTURES_DIR / example
        if not path.is_file():
            issues.append("handoff: example %s is missing" % example)
            continue
        record = load_json(path)
        if not is_fixture(record):
            issues.append("handoff: example %s carries no fixture marker"
                          % example)
    return issues


def status_problems() -> list[str]:
    derived, problems = sync_status(write=False)
    if problems:
        return ["status: %s" % p for p in problems]
    if not STATUS_PATH.is_file():
        return ["status: EXTERNAL_STATUS.json is absent; run sync-status"]
    if load_json(STATUS_PATH) != derived:
        return ["status: committed EXTERNAL_STATUS.json does not reproduce "
                "from its inputs; run sync-status and review the diff"]
    return []


def verify_all() -> list[str]:
    issues: list[str] = []
    for name in PACKAGE_FILES:
        if not (TRACK / name).is_file():
            issues.append("package: %s is missing" % name)
    issues += ["vocabulary: %s" % p
               for p in forbidden_vocabulary_problems()]
    issues += ["fixtures: %s" % p for p in verify_fixtures()]
    issues += ["handoff: %s" % p for p in handoff_problems()]
    issues += ["subject: %s" % p
               for p in _phase14().subject_unsigned_problems()]
    issues += cut_problems()
    if not issues:
        issues += ["matrix: %s" % p for p in matrix_problems()]
        issues += status_problems()
    if not issues:
        ops14 = _phase14()
        committed = load_json(PHASE13_STATUS)
        assembly = ops14.assemble_decision(ops14.real_universe(),
                                           committed.get("evaluationDate"))
        for field in ("authorizationState", "candidateDecision"):
            if assembly[field] != committed[field]:
                issues.append(
                    "assembly: the real universe derives %s %r but the "
                    "committed Phase 13 status says %r"
                    % (field, assembly[field], committed[field]))
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("phase 15 security-review execution verifies clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_build_matrix(_args) -> int:
    derived = run_scenarios()
    diverged = [row["scenarioId"] for row in derived["scenarios"]
                if row["result"] != "AS_EXPECTED"]
    if diverged:
        for row in derived["scenarios"]:
            if row["result"] != "AS_EXPECTED":
                print("%s DIVERGED:\n  expected %s\n  observed %s"
                      % (row["scenarioId"], row["expectedOutcome"],
                         row["observed"]))
        return 2
    dump_json(MATRIX_PATH, derived)
    print("matrix written: %d scenario(s), all AS_EXPECTED, every row "
          "FIXTURE_DEMONSTRATION_ONLY" % derived["counts"]["scenarios"])
    return 0


def _cmd_sync_status(_args) -> int:
    derived, problems = sync_status(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("EXTERNAL_STATUS.json derived: receipt %s; gate %s; "
          "authorization %s; decision %s"
          % (derived["securityReview"]["receiptState"],
             derived["securityReview"]["gate"]["status"],
             derived["authorization"]["authorizationState"],
             derived["authorization"]["candidateDecision"]))
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
    print("operational:        pipeline ready = %s (%d scenarios)"
          % (derived["operationalReadiness"]["pipelineReady"],
             derived["operationalReadiness"]["scenarios"]))
    print("evidence:           %d ledger entries; %d accepted real "
          "security review(s)"
          % (derived["evidenceState"]["ledgerEntries"],
             derived["evidenceState"]["acceptedRealSecurityReviews"]))
    print("security review:    receipt %s; gate %s"
          % (derived["securityReview"]["receiptState"],
             derived["securityReview"]["gate"]["status"]))
    print("authorization:      %s; candidate decision %s"
          % (derived["authorization"]["authorizationState"],
             derived["authorization"]["candidateDecision"]))
    return 0


def _cmd_prepare_review(args) -> int:
    manifest = prepare_review(Path(args.out))
    print("handoff package prepared at %s (%d files, sha256-pinned)"
          % (args.out, len(manifest["files"])))
    print("it creates no review; the only submission door is the Phase 9 "
          "intake")
    return 0


def _cmd_receive(args) -> int:
    entry = receive(Path(args.record), [Path(p) for p in args.attach],
                    args.received_on, args.submitted_by, args.revises)
    print("%s %s %s" % (entry["intakeId"], entry["status"],
                        entry.get("statusReason", "")))
    print("(the Phase 9 boundary decided this outcome; this wrapper only "
          "carried the paths)")
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
    verdict = validate_submission_record(record)
    for problem in verdict["contractProblems"]:
        print(problem)
    ceremony = verdict["identityCeremony"]
    print("identity ceremony: %s (%s)" % (ceremony["state"],
                                          ceremony["basis"]))
    if not verdict["contractValid"]:
        return 2
    print("record satisfies the submission contract (validation is not "
          "acceptance; the Phase 9 intake is the only door)")
    return 0


def _cmd_reconcile(args) -> int:
    if args.record:
        try:
            record = json.loads(
                Path(args.record).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            print("unreadable record: %s" % error)
            return 2
        _refuse_fixture(record, "reconcile")
        problems = _phase11().validate_submission(record)
        if problems:
            for problem in problems:
                print(problem)
            print("refusing to reconcile a record that fails the contract")
            return 2
        result = _phase11().reconcile_submission(
            record, load_json(PHASE11_BASELINE))
        for entry in result["classifications"]:
            print("%-24s %-28s %s" % (entry.get("reviewer_finding_id"),
                                      entry["classification"],
                                      entry.get("baseline_advisory") or "-"))
        print("unaddressed baseline rows: %d"
              % len(result["unaddressedBaseline"]))
        print("(analysis only; nothing was appended anywhere)")
        return 0
    derived, problems = _phase11().sync_register(write=True)
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
        "verify", help="package, vocabulary, fixtures, matrix, status, "
                       "cuts; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    matrix = commands.add_parser(
        "build-matrix", help="execute every failure/recovery scenario and "
                             "write the derived matrix")
    matrix.set_defaults(func=_cmd_build_matrix)

    sync = commands.add_parser(
        "sync-status", help="derive EXTERNAL_STATUS.json from live inputs")
    sync.set_defaults(func=_cmd_sync_status)

    status = commands.add_parser(
        "status", help="print the derived external status without writing")
    status.set_defaults(func=_cmd_status)

    prep = commands.add_parser(
        "prepare-review", help="assemble the reviewer handoff package "
                               "(creates no review)")
    prep.add_argument("--out", required=True,
                      help="destination directory outside the repository; "
                           "must not exist")
    prep.set_defaults(func=_cmd_prepare_review)

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
        "validate", help="contract + identity ceremony for one record "
                         "(read-only; validation is not acceptance)")
    val.add_argument("record")
    val.set_defaults(func=_cmd_validate)

    rec = commands.add_parser(
        "reconcile", help="derive the register through the Phase 11 "
                          "engine, or classify one record read-only")
    rec.add_argument("--record", default=None,
                     help="classify this record only; append nothing")
    rec.set_defaults(func=_cmd_reconcile)

    cut = commands.add_parser(
        "cut", help="seal an evidence cut over the real universe "
                    "(append-only under cuts/)")
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

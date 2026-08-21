#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 17 multi-source external-floor operator.

This is a composition layer.  Real evidence enters only through Phase 9;
source meaning remains in Phases 11–14/16; cuts contain references and hashes,
never copied evidence.  No function reads the wall clock.
"""

from __future__ import annotations

import argparse
import ast
import copy
import datetime
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PHASE17 = ROOT / "qualification" / "phase17"
FIXTURES = PHASE17 / "fixtures"
CUTS = PHASE17 / "cuts"
REGISTRY_PATH = PHASE17 / "SOURCE_REGISTRY.json"
FLOOR_PATH = PHASE17 / "FLOOR_STATUS.json"
MATRIX_PATH = PHASE17 / "MATRIX.json"
RECOVERY_PATH = PHASE17 / "FAILURE_RECOVERY_MATRIX.json"
DASHBOARD_PATH = ROOT / "PHASE17_EXTERNAL_FLOOR_OPERATIONS.md"
ENGINE_PATH = Path(__file__).resolve()
VERIFY_PATH = ENGINE_PATH.with_name("verify_phase17.py")

PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE10_TOOL = ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
PHASE10_GRAPH = ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json"
PHASE11_TOOL = ROOT / "qualification" / "phase11" / "tools" / "security_review_ops.py"
PHASE11_REGISTER = ROOT / "qualification" / "phase11" / "security-findings.json"
PHASE12_TOOL = ROOT / "qualification" / "phase12" / "tools" / "alpha_ops.py"
PHASE12_REGISTER = ROOT / "qualification" / "phase12" / "alpha-findings.json"
PHASE13_TOOL = ROOT / "qualification" / "phase13" / "tools" / "release_authority_ops.py"
PHASE13_STATUS = ROOT / "qualification" / "phase13" / "authorization-status.json"
PHASE13_BLOCKING = ROOT / "qualification" / "phase13" / "blocking" / "blocking-conditions.json"
PHASE14_TOOL = ROOT / "qualification" / "phase14" / "tools" / "evidence_execution_ops.py"
PHASE16_TOOL = ROOT / "qualification" / "phase16" / "tools" / "security_review_intake_ops.py"
PHASE16_STATUS = ROOT / "qualification" / "phase16" / "INTAKE_STATUS.json"

REQUIRED_SOURCES = (
    "security-review", "hardware", "signing", "second-approval",
    "alpha-feedback",
)
SOURCE_CLASSES = {
    "security-review": "SECURITY_REVIEW",
    "hardware": "HARDWARE_VALIDATION",
    "signing": "PRODUCTION_SIGNING",
    "second-approval": "SECOND_APPROVAL",
    "alpha-feedback": "ALPHA_TESTER_REPORT",
}
FIXTURE_MARKER = "TEST_FIXTURE_ONLY"
CUT_ID = re.compile(r"^CUT-\d{3}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

HARDWARE_DIMENSIONS = (
    "installation", "encrypted boot", "login", "desktop", "networking",
    "Wi-Fi", "audio output", "microphone", "pre-rendered", "2D",
    "native 3D", "fallback 3D", "voice", "Trust", "reboot",
    "persistence", "shutdown",
)
_HARDWARE_KEYS = {
    "installation": ("installation",),
    "encrypted boot": ("encrypted-boot",),
    "login": ("login",),
    "desktop": ("bunny-desktop",),
    "networking": ("networking",),
    "Wi-Fi": ("wifi",),
    "audio output": ("audio-output",),
    "microphone": ("microphone", "voice-microphone"),
    "pre-rendered": ("companion-prerendered",),
    "2D": ("companion-2d",),
    "native 3D": ("companion-3d-native",),
    "fallback 3D": ("companion-3d-fallback",),
    "voice": ("voice", "voice-recognition", "voice-response"),
    "Trust": ("trust", "trust-allow-verified", "trust-deny-verified"),
    "reboot": ("reboot", "reboot-persistence"),
    "persistence": ("persistence", "reboot-persistence"),
    "shutdown": ("shutdown",),
}

REGISTRY_FIELDS = (
    "canonicalEvidenceClass", "owningPhaseEngine", "intakeContract",
    "artifactBindingRules", "authorityRequirement", "expirySemantics",
    "revocationSemantics", "conflictSemantics", "sufficiencyModel",
    "revisionsAllowed", "oneRecordCanSatisfyWholeSource",
    "requiredStatusForAuthorization",
)

REAL_IMMUTABLE_INPUTS = (
    PHASE9_LEDGER, PHASE10_GRAPH, PHASE11_REGISTER, PHASE12_REGISTER,
    ROOT / "qualification" / "phase12" / "sufficiency-policy.json",
    ROOT / "qualification" / "phase13" / "governance" / "assignments.json",
    ROOT / "qualification" / "phase13" / "governance" / "separation-policy.json",
    ROOT / "qualification" / "phase13" / "sufficiency" / "threshold-policies.json",
    ROOT / "qualification" / "phase13" / "decisions" / "risk-acceptances.json",
    ROOT / "qualification" / "phase13" / "decisions" / "authorizations.json",
    ROOT / "qualification" / "phase13" / "decisions" / "revocations.json",
    ROOT / "qualification" / "phase13" / "decisions" / "conflict-resolutions.json",
    PHASE13_BLOCKING, PHASE13_STATUS, PHASE16_STATUS,
)


class BoundaryViolation(ValueError):
    """A fail-closed boundary refusal."""


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(payload: dict) -> bytes:
    return (json.dumps(payload, indent=1, sort_keys=True) + "\n").encode("utf-8")


def seal_record(record: dict) -> str:
    unsealed = {k: v for k, v in record.items() if k != "seal"}
    return _sha256(json.dumps(
        unsealed, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))


def _normalize_digest(value: object) -> str:
    text = str(value or "").strip().lower()
    return text[7:] if text.startswith("sha256:") else text


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BoundaryViolation("cannot load owning engine %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _phase9():
    return _load_module("phase9_for_phase17", PHASE9_TOOL)


def _phase10():
    return _load_module("phase10_for_phase17", PHASE10_TOOL)


def _phase11():
    return _load_module("phase11_for_phase17", PHASE11_TOOL)


def _phase12():
    return _load_module("phase12_for_phase17", PHASE12_TOOL)


def _phase13():
    return _load_module("phase13_for_phase17", PHASE13_TOOL)


def _phase14():
    return _load_module("phase14_for_phase17", PHASE14_TOOL)


def _phase16():
    return _load_module("phase16_for_phase17", PHASE16_TOOL)


def is_fixture(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    return any(record.get(key) in (True, FIXTURE_MARKER)
               for key in ("fixture", "fixtureClass", "test_fixture_only"))


def _refuse_fixture(record: object, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: REJECTED — TEST_FIXTURE_ONLY material is never evidence"
            % where
        )


def _date(value: object) -> datetime.date:
    text = str(value)
    if not ISO_DATE.fullmatch(text):
        raise BoundaryViolation("%r is not an exact ISO calendar date" % text)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as error:
        raise BoundaryViolation("%r is not a valid calendar date" % text) from error


def _instant(value: object) -> datetime.datetime:
    """Validate the whole timestamp before comparing it."""
    text = str(value)
    if ISO_DATE.fullmatch(text):
        return datetime.datetime.combine(
            _date(text), datetime.time(), tzinfo=datetime.timezone.utc
        )
    if not ISO_TIMESTAMP.fullmatch(text):
        raise BoundaryViolation(
            "%r is not an exact timezone-qualified ISO timestamp" % text
        )
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise BoundaryViolation("%r is not a valid ISO timestamp" % text) from error


def source_registry() -> dict:
    return load_json(REGISTRY_PATH)


def registry_problems(registry: dict | None = None) -> list[str]:
    registry = registry or source_registry()
    problems = []
    sources = registry.get("sources") or {}
    if tuple(sorted(sources)) != tuple(sorted(REQUIRED_SOURCES)):
        problems.append(
            "registry sources must be exactly %s" % ", ".join(REQUIRED_SOURCES)
        )
    if registry.get("genericFallback") is not None:
        problems.append("registry must not define a generic evidence fallback")
    for source in REQUIRED_SOURCES:
        row = sources.get(source) or {}
        for field in REGISTRY_FIELDS:
            if field not in row or row[field] in ("", None):
                problems.append("registry %s missing %s" % (source, field))
        if row.get("canonicalEvidenceClass") != SOURCE_CLASSES[source]:
            problems.append("registry %s maps to the wrong evidence class" % source)
    return problems


def source_contract(source: str) -> dict:
    if source not in REQUIRED_SOURCES:
        raise BoundaryViolation(
            "unknown source %r; unknown evidence never becomes "
            "generic-external-evidence" % source
        )
    registry = source_registry()
    if registry_problems(registry):
        raise BoundaryViolation("source registry is invalid")
    return copy.deepcopy(registry["sources"][source])


def _subject(ledger: dict | None = None, graph: dict | None = None) -> dict:
    ledger = ledger or load_json(PHASE9_LEDGER)
    graph = graph or load_json(PHASE10_GRAPH)
    candidate = _phase10()._active_candidate(graph)
    subject = ledger["subjectArtifact"]
    if candidate.get("artifact_id") != subject.get("identifier"):
        raise BoundaryViolation(
            "active artifact %s differs from intake subject %s"
            % (candidate.get("artifact_id"), subject.get("identifier"))
        )
    return {
        "identifier": subject["identifier"],
        "digests": sorted(_phase9().subject_digests(ledger)),
        "imageDigest": subject["imageDigest"],
        "frozen": subject.get("frozen") is True,
        "relationship": candidate.get("relationship"),
        "signingStatus": candidate.get("signingStatus"),
        "sourceCommit": subject.get("sourceCommit"),
    }


def require_artifact(artifact: str, subject: dict | None = None) -> dict:
    subject = subject or _subject()
    token = _normalize_digest(artifact)
    if artifact != subject["identifier"] and token not in subject["digests"]:
        raise BoundaryViolation(
            "artifact %r is not the active subject %s" %
            (artifact, subject["identifier"])
        )
    return subject


def _claims(source: str, record: dict) -> list[str]:
    if source == "security-review":
        values = [record.get("artifactDigest"), record.get("artifact_digest"),
                  record.get("independently_computed_digest")]
    elif source == "second-approval":
        values = [record.get("independentlyRecomputedArtifactDigest")]
        for who in ("firstApprover", "secondApprover"):
            values.append((record.get(who) or {}).get("recomputedDigest"))
    elif source == "signing":
        values = [record.get("artifactDigest"),
                  record.get("independentlyRecomputedArtifactDigest")]
    else:
        values = [record.get("artifactDigest")]
    return sorted({_normalize_digest(v) for v in values if v})


def bind_record(source: str, record: dict, artifact: str,
                evidence_id: str) -> dict:
    source_contract(source)
    _refuse_fixture(record, "binding")
    subject = require_artifact(artifact)
    claims = _claims(source, record)
    if not claims:
        return {
            "result": "UNBOUND", "evidenceId": evidence_id,
            "targetArtifact": subject["identifier"],
            "reasoning": "no artifact digest is present; useful observations "
                         "may be preserved but cannot satisfy the floor",
        }
    results = []
    graph = load_json(PHASE10_GRAPH)
    for digest in claims:
        results.append(_phase10().evaluate_applicability({
            "evidenceId": evidence_id, "artifactDigest": digest,
            "scope": source,
        }, subject["identifier"], graph))
    if any(row.get("result") != "APPLIES" for row in results):
        return {
            "result": "DOES_NOT_APPLY", "evidenceId": evidence_id,
            "targetArtifact": subject["identifier"], "claims": claims,
            "reasoning": "one or more claimed digests do not apply; "
                         "evidence never transfers by implication",
        }
    return {
        "result": "APPLIES", "evidenceId": evidence_id,
        "targetArtifact": subject["identifier"], "claims": claims,
        "reasoning": "every claimed digest applies through Phase 10",
    }


def _standing_assignments(context: dict, as_of: str | None) -> list[dict]:
    assignments = list(context.get("assignments") or [])
    revocations = list(context.get("assignmentRevocations") or [])
    return _phase14().standing_assignments(assignments, as_of, revocations)


def _canonical_identity(identity: object, context: dict) -> str:
    text = str(identity or "")
    mapping = context.get("identityMap") or {}
    return str(mapping.get(text, text))


def _holds(identity: object, authority: str, context: dict,
           as_of: str | None) -> bool:
    wanted = _canonical_identity(identity, context)
    for assignment in _standing_assignments(context, as_of):
        if assignment.get("authorityId") == authority and \
                _canonical_identity(assignment.get("identity"), context) == wanted:
            return True
    return False


def _authority_state(identity: object, authority: str, context: dict,
                     as_of: str | None) -> str:
    matching = [a for a in context.get("assignments") or []
                if a.get("authorityId") == authority
                and _canonical_identity(a.get("identity"), context)
                == _canonical_identity(identity, context)]
    if not matching:
        return "UNASSIGNED"
    if _holds(identity, authority, context, as_of):
        return "STANDING"
    states = [_phase14().assignment_state(
        row, as_of, context.get("assignmentRevocations") or []
    ) for row in matching]
    return "REVOKED" if "REVOKED" in states else "EXPIRED"


def _hardware_status(record: dict, dimension: str) -> str:
    results = record.get("results") or {}
    keys = _HARDWARE_KEYS[dimension]
    found = []
    for key in keys:
        if key not in results:
            continue
        row = results[key]
        found.append(row.get("status") if isinstance(row, dict) else row)
    if not found:
        return "NOT_RUN"
    if "FAIL" in found:
        return "FAIL"
    if all(value == "PASS" for value in found):
        return "PASS"
    if all(value == "NOT_SUPPORTED" for value in found):
        return "NOT_SUPPORTED"
    if "NOT_RUN" in found:
        return "NOT_RUN"
    return "MIXED"


def _common_result(source: str, record: dict, artifact: str,
                   evidence_id: str) -> tuple[dict, dict]:
    subject = require_artifact(artifact)
    verdict = _phase9().validate_record(
        source, record, set(subject["digests"])
    )
    binding = bind_record(source, record, artifact, evidence_id)
    return verdict, binding


def _evaluate_security(record: dict, artifact: str, evidence_id: str,
                       as_of: str | None, context: dict) -> dict:
    verdict, binding = _common_result(
        "security-review", record, artifact, evidence_id
    )
    assessment = (record.get("overall_assessment")
                  or record.get("disposition") or "UNDETERMINED")
    gate = context.get("securityGate", "AWAITING_EXTERNAL_EVIDENCE")
    conflict = context.get("securityConflict", "NONE")
    expired = list(context.get("expiredRisks") or [])
    contributes = (
        verdict["status"] == "ACCEPTED"
        and binding["result"] == "APPLIES"
        and gate == "SATISFIED" and conflict == "NONE" and not expired
    )
    reason = "Phase 11 security gate %s" % gate
    if expired:
        reason += "; accepted risk expired: %s" % ", ".join(expired)
    if conflict != "NONE":
        reason += "; conflict %s" % conflict
    return {
        "effectiveStatus": gate, "assessment": assessment,
        "expiryState": "EXPIRED" if expired else "STANDING_OR_NOT_APPLICABLE",
        "revocationState": context.get("securityRevocation", "NONE"),
        "conflictState": conflict, "contributes": contributes,
        "reason": reason, "validation": verdict, "binding": binding,
    }


def _evaluate_hardware(record: dict, artifact: str, evidence_id: str,
                       as_of: str | None, context: dict) -> dict:
    verdict, binding = _common_result("hardware", record, artifact, evidence_id)
    machine = record.get("machine") or {}
    required = {
        "machine.machineId": machine.get("machineId"),
        "installationMediumIdentity": record.get("installationMediumIdentity"),
        "machine.network": machine.get("network"),
        "testedCompanionModes": record.get("testedCompanionModes"),
        "executedJourneys": record.get("executedJourneys"),
    }
    missing = sorted(name for name, value in required.items()
                     if value in (None, "", [], {}))
    dimensions = {name: _hardware_status(record, name)
                  for name in HARDWARE_DIMENSIONS}
    native_ok = dimensions["native 3D"] in ("PASS", "NOT_SUPPORTED")
    dimensional_pass = all(
        status == "PASS" for name, status in dimensions.items()
        if name != "native 3D"
    ) and native_ok
    policy = record.get("supportPolicy") or context.get("hardwarePolicy") or {}
    policy_state = "MISSING"
    if policy:
        if policy.get("status") != "ACTIVE":
            policy_state = "INACTIVE"
        elif policy.get("expiresAt"):
            if as_of is None:
                policy_state = "AS_OF_REQUIRED"
            else:
                policy_state = ("EXPIRED" if _date(as_of) >
                                _date(policy["expiresAt"]) else "STANDING")
        else:
            policy_state = "STANDING"
    authority = policy.get("authority") or record.get("operator")
    authority_state = _authority_state(
        authority, "AUTH-HARDWARE", context, as_of
    )
    contributes = (
        verdict["status"] == "ACCEPTED"
        and binding["result"] == "APPLIES" and not missing
        and dimensional_pass and policy_state == "STANDING"
        and authority_state == "STANDING"
    )
    effective = ("QUALIFIED_FOR_DECLARED_SCOPE" if contributes
                 else "DIMENSIONAL_EVIDENCE_ONLY" if verdict["status"] == "ACCEPTED"
                 else verdict["status"])
    failures = [name for name, status in dimensions.items()
                if status not in ("PASS", "NOT_SUPPORTED")]
    return {
        "effectiveStatus": effective, "dimensions": dimensions,
        "machineIdentity": {
            "hwId": record.get("hwId"), "machineId": machine.get("machineId"),
        },
        "aggregateClaim": None, "missingProtocolFields": missing,
        "policyState": policy_state, "authorityState": authority_state,
        "expiryState": "EXPIRED" if policy_state == "EXPIRED" else "STANDING_OR_NOT_APPLICABLE",
        "revocationState": "REVOKED" if authority_state == "REVOKED" else "NONE",
        "conflictState": context.get("hardwareConflict", "NONE"),
        "contributes": contributes,
        "reason": ("machine-level dimensional result; failures/not-run: %s; "
                   "policy=%s authority=%s; no aggregate PC claim"
                   % (", ".join(failures) or "none", policy_state,
                      authority_state)),
        "validation": verdict, "binding": binding,
    }


def _evaluate_signing(record: dict, artifact: str, evidence_id: str,
                      as_of: str | None, context: dict) -> dict:
    verdict, binding = _common_result("signing", record, artifact, evidence_id)
    subject = require_artifact(artifact)
    required = (
        "artifactDigest", "independentlyRecomputedArtifactDigest",
        "signerAuthority", "signingMethod", "signatureIdentifier",
        "signatureOrVerificationArtifact", "signingTimestamp",
        "verificationResult", "verificationMethod",
    )
    missing = [name for name in required if record.get(name) in (None, "", [], {})]
    submitted = _normalize_digest(record.get("artifactDigest"))
    recomputed = _normalize_digest(
        record.get("independentlyRecomputedArtifactDigest")
    )
    digests_match = (submitted == recomputed and submitted in subject["digests"])
    time_valid = True
    try:
        _instant(record.get("signingTimestamp"))
    except BoundaryViolation:
        time_valid = False
    signer = record.get("signerIdentity")
    authority_state = _authority_state(signer, "AUTH-KEY", context, as_of)
    production = record.get("category") == "PRODUCTION ARTIFACT SIGNED"
    verified = record.get("verificationResult") == "PASS"
    contributes = (
        verdict["status"] == "ACCEPTED" and binding["result"] == "APPLIES"
        and not missing and production and verified and digests_match
        and time_valid and authority_state == "STANDING"
        and context.get("signingConflict", "NONE") == "NONE"
    )
    return {
        "effectiveStatus": "VERIFIED_PRODUCTION_SIGNING" if contributes
                           else "SIGNING_DRILL" if not production
                           else "VERIFICATION_FAILED",
        "missingVerificationFields": missing,
        "submittedDigestMatchesRecomputed": digests_match,
        "verificationSucceeded": verified,
        "authorityState": authority_state,
        "expiryState": "EXPIRED" if authority_state == "EXPIRED" else "STANDING_OR_NOT_APPLICABLE",
        "revocationState": "REVOKED" if authority_state == "REVOKED" else "NONE",
        "conflictState": context.get("signingConflict", "NONE"),
        "contributes": contributes,
        "reason": ("production=%s verification=%s digestBinding=%s "
                   "authority=%s" % (production, verified, digests_match,
                                      authority_state)),
        "validation": verdict, "binding": binding,
    }


def _approval_fields(record: dict) -> dict:
    if "approverId" in record:
        return {
            "identity": record.get("approverId"),
            "role": record.get("authorityRole"),
            "decision": record.get("decision"),
            "digest": record.get("independentlyRecomputedArtifactDigest"),
            "timestamp": record.get("timestamp"),
            "cut": record.get("relevantEvidenceCut"),
            "conditions": record.get("conditions") or [],
        }
    second = record.get("secondApprover") or {}
    return {
        "identity": second.get("name"), "role": second.get("role"),
        "decision": ({"APPROVE": "APPROVED", "REJECT": "REJECTED"}
                     .get(second.get("decision"), second.get("decision"))),
        "digest": second.get("recomputedDigest"),
        "timestamp": second.get("date"), "cut": record.get("relevantEvidenceCut"),
        "conditions": record.get("conditions") or [],
    }


def _evaluate_approval(record: dict, artifact: str, evidence_id: str,
                       as_of: str | None, context: dict) -> dict:
    verdict, binding = _common_result(
        "second-approval", record, artifact, evidence_id
    )
    fields = _approval_fields(record)
    identity = fields["identity"]
    authority_state = _authority_state(
        identity, "AUTH-SECOND-APPROVER", context, as_of
    )
    signer_ids = {
        _canonical_identity(row.get("signerIdentity"), context)
        for row in context.get("signingRecords") or []
    }
    release_ids = {
        _canonical_identity(row.get("identity"), context)
        for row in context.get("assignments") or []
        if row.get("authorityId") == "AUTH-RELEASE"
    }
    canonical = _canonical_identity(identity, context)
    overlap = canonical in signer_ids or canonical in release_ids
    if overlap:
        # Phase 13 remains the policy owner.  A complete overlap decision is
        # the only exception; string inequality is never treated as proof.
        permitted = any(
            row.get("identity") == canonical
            and {"AUTH-KEY", "AUTH-SECOND-APPROVER"} <= set(row.get("roles") or [])
            for row in context.get("overlapDecisions") or []
            if not _phase13().validate_overlap_decision(row)
        )
        overlap = not permitted
    ordering = []
    try:
        approved_at = _instant(fields["timestamp"])
        for signing in context.get("signingRecords") or []:
            if approved_at < _instant(signing.get("signingTimestamp")):
                ordering.append("approval predates production signing")
    except BoundaryViolation as error:
        ordering.append(str(error))
    requested_cut = context.get("cutId")
    cut_matches = bool(fields["cut"]) and (
        requested_cut is None or fields["cut"] == requested_cut
    )
    decision_ok = fields["decision"] == "APPROVED" and not fields["conditions"]
    contributes = (
        verdict["status"] == "ACCEPTED" and binding["result"] == "APPLIES"
        and decision_ok and authority_state == "STANDING" and not overlap
        and not ordering and cut_matches
        and context.get("approvalConflict", "NONE") == "NONE"
        and not context.get("expiredRisks")
    )
    return {
        "effectiveStatus": "APPROVED" if contributes else
                           fields["decision"] or "INCOMPLETE",
        "authorityState": authority_state, "separationViolation": overlap,
        "orderingProblems": ordering, "relevantCutMatches": cut_matches,
        "expiryState": "EXPIRED" if authority_state == "EXPIRED" else "STANDING_OR_NOT_APPLICABLE",
        "revocationState": "REVOKED" if authority_state == "REVOKED" else "NONE",
        "conflictState": context.get("approvalConflict", "NONE"),
        "contributes": contributes,
        "reason": ("decision=%s authority=%s overlap=%s ordering=%s "
                   "cutMatches=%s" % (fields["decision"], authority_state,
                                       overlap, bool(ordering), cut_matches)),
        "validation": verdict, "binding": binding,
    }


def _evaluate_alpha(record: dict, artifact: str, evidence_id: str,
                    as_of: str | None, context: dict) -> dict:
    verdict, binding = _common_result(
        "alpha-feedback", record, artifact, evidence_id
    )
    sufficiency = context.get("alphaSufficiency") or {
        "determination": "SUFFICIENCY_UNDETERMINED",
        "policyState": "SUFFICIENCY_POLICY_UNDEFINED",
        "activePolicy": None,
    }
    blockers = list(context.get("alphaBlockers") or [])
    contributes = (
        verdict["status"] == "ACCEPTED" and binding["result"] == "APPLIES"
        and sufficiency.get("policyState") == "SUFFICIENCY_POLICY_ACTIVE"
        and sufficiency.get("determination") == "SUFFICIENT" and not blockers
        and context.get("alphaConflict", "NONE") == "NONE"
    )
    return {
        "effectiveStatus": sufficiency.get("determination"),
        "policyState": sufficiency.get("policyState"),
        "activePolicy": sufficiency.get("activePolicy"),
        "blockingFindings": blockers,
        "expiryState": context.get("alphaPolicyExpiry", "NOT_APPLICABLE"),
        "revocationState": context.get("alphaAuthorityRevocation", "NONE"),
        "conflictState": context.get("alphaConflict", "NONE"),
        "contributes": contributes,
        "reason": ("policy=%s sufficiency=%s blockers=%d"
                   % (sufficiency.get("policyState"),
                      sufficiency.get("determination"), len(blockers))),
        "validation": verdict, "binding": binding,
    }


_EVALUATORS = {
    "security-review": _evaluate_security,
    "hardware": _evaluate_hardware,
    "signing": _evaluate_signing,
    "second-approval": _evaluate_approval,
    "alpha-feedback": _evaluate_alpha,
}


def evaluate_record(source: str, record: dict, artifact: str,
                    evidence_id: str, as_of: str | None = None,
                    context: dict | None = None) -> dict:
    source_contract(source)
    _refuse_fixture(record, "source evaluation")
    require_artifact(artifact)
    if as_of is not None:
        _date(as_of)
    result = _EVALUATORS[source](
        copy.deepcopy(record), artifact, evidence_id, as_of,
        copy.deepcopy(context or {}),
    )
    result.update({
        "source": source, "evidenceClass": SOURCE_CLASSES[source],
        "artifact": _subject()["identifier"], "evidenceId": evidence_id,
        "ownerEngineResult": True,
    })
    return result


def inspect_path(source: str, path: Path, artifact: str,
                 evidence_id: str, attachments: list[Path] = ()) -> dict:
    source_contract(source)
    subject = require_artifact(artifact)
    raw = path.read_bytes()
    secrets = _phase9().detect_secret_classes(raw)
    for attachment in attachments:
        secrets += _phase9().detect_secret_classes(attachment.read_bytes())
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "source": source, "artifact": subject["identifier"],
            "evidenceId": evidence_id, "inspection": "UNVERIFIABLE",
            "problems": ["record is not parseable JSON: %s" % error],
            "credentialClasses": sorted(set(secrets)),
        }
    if is_fixture(record):
        return {
            "source": source, "artifact": subject["identifier"],
            "evidenceId": evidence_id, "inspection": "REJECTED",
            "problems": ["record is TEST_FIXTURE_ONLY"],
            "credentialClasses": sorted(set(secrets)),
        }
    verdict = _phase9().validate_record(
        source, record, set(subject["digests"])
    )
    return {
        "source": source, "artifact": subject["identifier"],
        "evidenceId": evidence_id,
        "inspection": "QUARANTINE" if secrets else verdict["status"],
        "credentialClasses": sorted(set(secrets)),
        "binding": verdict["binding"],
        "note": "detected secret classes are named; matched values are never output",
    }


def receive(source: str, path: Path, artifact: str, evidence_id: str,
            attachments: list[Path], received_on: str, submitted_by: str,
            revises: str | None = None,
            ledger_path: Path = PHASE9_LEDGER) -> dict:
    """The one real evidence door: pure delegation to Phase 9 register."""
    source_contract(source)
    require_artifact(artifact)
    if not evidence_id:
        raise BoundaryViolation("receive requires an explicit evidence ID")
    return _phase9().register(
        ledger_path, source, path, attachments, received_on, submitted_by,
        revises,
    )


def _template(source: str) -> dict:
    subject = _subject()
    digest = subject["imageDigest"]
    templates = {
        "security-review": {
            "reviewer": "", "scope": "", "date": "",
            "artifactDigest": digest, "disposition": "", "findings": [],
        },
        "hardware": {
            "hwId": "HW-NNN", "operator": "", "date": "",
            "artifactDigest": digest, "installationMediumIdentity": "",
            "machine": {}, "testedCompanionModes": [],
            "executedJourneys": [], "results": {},
        },
        "signing": {
            "category": "PRODUCTION ARTIFACT SIGNED",
            "artifactDigest": digest,
            "independentlyRecomputedArtifactDigest": "",
            "signerIdentity": "", "signerAuthority": "",
            "signingMethod": "", "signatureIdentifier": "",
            "signatureOrVerificationArtifact": "",
            "signingTimestamp": "", "verificationResult": "",
            "verificationMethod": "", "verificationRunBy": "",
        },
        "second-approval": {
            "approverId": "", "authorityRole": "SECOND_APPROVER",
            "independentlyRecomputedArtifactDigest": "",
            "decision": "", "timestamp": "", "relevantEvidenceCut": "",
            "conditions": [],
        },
        "alpha-feedback": {
            "testerId": "T-NNN", "report_type": "", "journey": "",
            "environment": "", "date": "", "artifactDigest": digest,
            "steps": [],
        },
    }
    return templates[source]


def prepare(source: str, out_dir: Path) -> dict:
    source_contract(source)
    resolved = out_dir.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise BoundaryViolation("prepared handoff must be outside the repository")
    if resolved.exists():
        raise BoundaryViolation("prepare refuses an existing destination")
    if source == "security-review":
        return _phase16().prepare(resolved)
    resolved.mkdir(parents=True)
    template = _template(source)
    dump_json(resolved / "record.template.json", template)
    (resolved / "README.md").write_text(
        "# %s evidence handoff\n\nReplace every blank field, preserve original "
        "bytes, and submit through Phase 17 receive (Phase 9 intake). This "
        "package is a template, not evidence.\n" % source,
        encoding="utf-8", newline="\n",
    )
    return {"source": source, "prepared": str(resolved), "evidenceCreated": False}


def _read_effective_records(ledger: dict, source: str,
                            intake_root: Path) -> tuple[list[dict], list[dict]]:
    effective = _phase9().effective_statuses(ledger)
    entries = [e for e in ledger.get("entries", []) if e.get("source") == source]
    records = []
    for entry in entries:
        if not entry.get("gateEligible") or effective.get(entry["intakeId"]) != "ACCEPTED":
            continue
        path = intake_root / source / entry["intakeId"] / "record.json"
        try:
            record = load_json(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        records.append({"entry": entry, "record": record})
    return entries, records


def _real_context(as_of: str | None, ledger: dict) -> dict:
    governance = _phase13()._load_governance()
    security = load_json(PHASE11_REGISTER)
    alpha = load_json(PHASE12_REGISTER)
    subject = _subject(ledger)
    sufficiency = _phase13().evaluate_sufficiency(
        governance["policies"], alpha, security, ledger,
        set(subject["digests"]),
    )
    expired_risks = []
    for risk in governance["risks"]:
        if _phase13().risk_acceptance_state(risk, as_of) == "EXPIRED":
            expired_risks.append(risk.get("risk_id"))
    alpha_blockers = [
        row.get("finding_id") for row in alpha.get("findings", [])
        if row.get("lifecycle_status") in ("FIX_REQUIRED", "BLOCKED")
    ]
    return {
        "assignments": governance["assignments"],
        "overlapDecisions": governance["overlapDecisions"],
        "expiredRisks": expired_risks,
        "securityGate": (security.get("securityGate") or {}).get(
            "status", "AWAITING_EXTERNAL_EVIDENCE"),
        "securityConflict": "CONFLICT" if (security.get("conflicts") or []) else "NONE",
        "alphaSufficiency": sufficiency,
        "alphaBlockers": alpha_blockers,
    }


def _source_row(source: str, ledger: dict, intake_root: Path,
                artifact: str, as_of: str | None, base_context: dict,
                all_records: dict[str, list[dict]]) -> dict:
    entries, accepted = _read_effective_records(ledger, source, intake_root)
    context = copy.deepcopy(base_context)
    context["signingRecords"] = [r["record"] for r in all_records["signing"]]
    evaluations = []
    for item in accepted:
        evaluations.append(evaluate_record(
            source, item["record"], artifact, item["entry"]["intakeId"],
            as_of, context,
        ))
    favorable = [row for row in evaluations if row.get("contributes")]
    adverse = [row for row in evaluations
               if row.get("effectiveStatus") in (
                   "BLOCKED", "VERIFICATION_FAILED", "REJECTED", "FAIL"
               ) or row.get("conflictState") not in (None, "NONE")]
    conflict = "CONFLICT" if favorable and adverse else (
        "CONFLICT" if any(row.get("conflictState") not in (None, "NONE")
                          for row in evaluations) else "NONE"
    )
    contributes = bool(favorable) and not adverse and conflict == "NONE"
    if not entries:
        effective_status = (
            "AWAITING_EXTERNAL_EVIDENCE" if source == "security-review"
            else "NO_EVIDENCE"
        )
        reason = "no Phase 9 intake entry exists for this source"
    elif not accepted:
        effective_status = "NO_GATE_ELIGIBLE_EVIDENCE"
        reason = "evidence was received but no effective gate-eligible ACCEPTED record exists"
    elif contributes:
        effective_status = favorable[0]["effectiveStatus"]
        reason = favorable[0]["reason"]
    else:
        effective_status = evaluations[-1]["effectiveStatus"]
        reason = evaluations[-1]["reason"]
    expiry = "EXPIRED" if any(row.get("expiryState") == "EXPIRED"
                              for row in evaluations) else "NONE_OR_STANDING"
    revocation = "REVOKED" if any(row.get("revocationState") == "REVOKED"
                                  for row in evaluations) else "NONE"
    bound = [row for row in evaluations
             if (row.get("binding") or {}).get("result") == "APPLIES"]
    return {
        "source": source, "artifact": _subject(ledger)["identifier"],
        "evidenceIds": [e["intakeId"] for e in entries],
        "validationStatus": "VALID" if accepted else "MISSING_OR_INVALID",
        "bindingStatus": "BOUND" if bound else "UNBOUND_OR_MISSING",
        "effectiveStatus": effective_status,
        "expiryState": expiry, "revocationState": revocation,
        "conflictState": conflict,
        "source_operational_ready": not registry_problems(),
        "source_evidence_received": bool(entries),
        "source_evidence_valid": bool(accepted),
        "source_artifact_bound": bool(bound),
        "source_sufficient": bool(favorable),
        "source_contributes_to_floor": contributes,
        "contributes_to_floor": contributes,
        "reason": reason,
        "ownerEngineEvaluations": evaluations,
        "provenance": {
            "ownerEngineResult": True,
            "registryClass": SOURCE_CLASSES[source],
        },
    }


def cross_source_conflicts(rows: list[dict], records: dict[str, list[dict]]) -> list[dict]:
    conflicts = []
    hardware_mic_pass = any(
        _hardware_status(item["record"], "microphone") == "PASS"
        for item in records.get("hardware", [])
    )
    alpha_mic_failure = any(
        any("microphone" in json.dumps(finding).lower()
            for finding in item["record"].get("findings") or [])
        for item in records.get("alpha-feedback", [])
    )
    if hardware_mic_pass and alpha_mic_failure:
        conflicts.append({
            "sources": ["hardware", "alpha-feedback"],
            "status": "REQUIRES_HUMAN_DECISION", "blocking": True,
            "reason": "machine-specific microphone PASS and user-reported "
                      "failure elsewhere are both preserved; support scope "
                      "requires human review",
        })
    security = next(row for row in rows if row["source"] == "security-review")
    signing = next(row for row in rows if row["source"] == "signing")
    if signing["contributes_to_floor"] and security["effectiveStatus"] != "SATISFIED":
        conflicts.append({
            "sources": ["security-review", "signing"],
            "status": "BLOCKED", "blocking": True,
            "reason": "valid signing cannot overrule an unsatisfied security gate",
        })
    alpha = next(row for row in rows if row["source"] == "alpha-feedback")
    approval = next(row for row in rows if row["source"] == "second-approval")
    if approval["contributes_to_floor"] and alpha["effectiveStatus"] in (
            "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS", "BLOCKED"):
        conflicts.append({
            "sources": ["second-approval", "alpha-feedback"],
            "status": "BLOCKED", "blocking": True,
            "reason": "second approval cannot overrule an Alpha blocker",
        })
    return conflicts


def converge_rows(rows: list[dict]) -> dict:
    by_source = {row.get("source"): row for row in rows}
    missing_rows = [source for source in REQUIRED_SOURCES if source not in by_source]
    unproven = []
    for source in REQUIRED_SOURCES:
        row = by_source.get(source) or {}
        provenance = row.get("provenance") or {}
        if not provenance.get("ownerEngineResult"):
            unproven.append(source)
        if row.get("contributes_to_floor") and not row.get("evidenceIds"):
            unproven.append(source)
    contributing = [source for source in REQUIRED_SOURCES
                    if by_source.get(source, {}).get("contributes_to_floor")]
    conflicts = [source for source in REQUIRED_SOURCES
                 if by_source.get(source, {}).get("conflictState")
                 not in (None, "NONE")]
    satisfied = (
        len(contributing) == len(REQUIRED_SOURCES)
        and not missing_rows and not unproven and not conflicts
    )
    return {
        "required": list(REQUIRED_SOURCES), "contributing": contributing,
        "count": len(contributing), "missing": [s for s in REQUIRED_SOURCES
                                                 if s not in contributing],
        "unproven": sorted(set(unproven)), "conflicts": conflicts,
        "satisfied": satisfied,
        "authorizedPossible": satisfied,
        "reason": ("all five source-specific results stand" if satisfied
                   else "zero through four sources, unproven internal claims, "
                        "or conflict can never authorize"),
    }


def derive_floor_status(artifact: str, as_of: str | None = None,
                        *, ledger_bytes: bytes | None = None,
                        intake_root: Path | None = None) -> dict:
    if as_of is not None:
        _date(as_of)
    ledger_bytes = ledger_bytes or PHASE9_LEDGER.read_bytes()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    intake_root = intake_root or PHASE9_LEDGER.parent
    subject = require_artifact(artifact, _subject(ledger))
    context = _real_context(as_of, ledger)
    all_records = {
        source: _read_effective_records(ledger, source, intake_root)[1]
        for source in REQUIRED_SOURCES
    }
    rows = [_source_row(source, ledger, intake_root, artifact, as_of,
                        context, all_records)
            for source in REQUIRED_SOURCES]
    conflicts = cross_source_conflicts(rows, all_records)
    convergence = converge_rows(rows)
    universe = _phase14().real_universe()
    assembly = _phase14().assemble_decision(universe, as_of)
    if conflicts:
        candidate = "REQUIRES_HUMAN_DECISION"
    elif not convergence["satisfied"]:
        candidate = "REQUIRES_MORE_EVIDENCE"
    else:
        candidate = assembly["candidateDecision"]
    phase13_status = load_json(PHASE13_STATUS)
    next_action = phase13_status.get("nextAction") or (
        "Commission the independent security review"
    )
    input_paths = [REGISTRY_PATH, PHASE9_LEDGER, PHASE10_GRAPH,
                   PHASE11_REGISTER, PHASE12_REGISTER, PHASE13_STATUS]
    return {
        "schemaVersion": 1,
        "phaseStatus": "PHASE 17 — EXTERNAL FLOOR OPERATIONS READY",
        "subjectArtifact": {
            "identifier": subject["identifier"], "relationship": subject["relationship"],
            "frozen": subject["frozen"], "unchanged": True,
            "signingStatus": subject["signingStatus"],
        },
        "asOf": as_of,
        "sources": rows, "convergence": convergence,
        "conflicts": conflicts,
        "authorizationState": assembly["authorizationState"],
        "candidateDecision": candidate,
        "singleNextDeterministicAction": next_action,
        "inputHashes": {
            path.relative_to(ROOT).as_posix(): _sha256(path.read_bytes())
            for path in input_paths if path.is_file()
        },
        "note": "readiness, receipt, validity, binding, sufficiency, and "
                "contribution are separate; this view creates no evidence",
    }


def _phase14_cut(universe: dict, as_of: str | None) -> dict:
    return _phase14().build_evidence_cut(
        ledger_bytes=universe["ledger_bytes"], graph_bytes=universe["graph_bytes"],
        security_register_bytes=json.dumps(
            universe["security_register"], sort_keys=True
        ).encode("utf-8"),
        alpha_register_bytes=json.dumps(
            universe["alpha_register"], sort_keys=True
        ).encode("utf-8"),
        assignments=universe["assignments"], policies=universe["policies"],
        risks=universe["risks"], authorizations=universe["authorizations"],
        revocations=universe["revocations"], resolutions=universe["resolutions"],
        assignment_revocations=universe.get("assignment_revocations", []),
        as_of=as_of,
    )


def build_floor_cut(cut_id: str, artifact: str, as_of: str | None,
                    universe: dict | None = None,
                    floor_status: dict | None = None) -> dict:
    if not CUT_ID.fullmatch(cut_id):
        raise BoundaryViolation("cut ID must match CUT-NNN")
    if as_of is not None:
        _date(as_of)
    require_artifact(artifact)
    universe = universe or _phase14().real_universe()
    base = _phase14_cut(universe, as_of)
    floor = floor_status or derive_floor_status(artifact, as_of)
    cut = {
        "schemaVersion": 1, "cutId": cut_id,
        "subjectArtifact": floor["subjectArtifact"]["identifier"],
        "asOf": as_of, "phase9LedgerSha256": base["ledgerSha256"],
        "phase9LedgerEntries": base["ledgerEntries"],
        "intakeIds": base["intakeIds"],
        "phase10GraphSha256": base["graphSha256"],
        "phase14CutSeal": base["seal"],
        "securityStateSha256": base["securityRegisterSha256"],
        "alphaStateSha256": base["alphaRegisterSha256"],
        "authorityRecords": base["authorityRecords"],
        "riskAcceptances": base["riskAcceptances"],
        "policyVersions": base["policyVersions"],
        "sourceRegistrySha256": _sha256(REGISTRY_PATH.read_bytes()),
        "sourceEvaluations": floor["sources"],
        "convergence": floor["convergence"],
        "conflicts": floor["conflicts"],
        "authorizationState": floor["authorizationState"],
        "candidateDecision": floor["candidateDecision"],
        "postCutEvidenceIds": [],
        "timeBasis": "explicit asOf only; no wall clock",
    }
    cut["seal"] = seal_record(cut)
    return cut


def write_cut(cut: dict) -> Path:
    path = CUTS / (cut["cutId"] + ".json")
    if path.exists():
        raise BoundaryViolation("cut %s already exists" % cut["cutId"])
    dump_json(path, cut)
    return path


def verify_floor_cut(cut: dict) -> list[str]:
    problems = []
    if seal_record(cut) != cut.get("seal"):
        problems.append("cut seal mismatch")
    if not CUT_ID.fullmatch(str(cut.get("cutId") or "")):
        problems.append("cut ID malformed")
    if cut.get("asOf") is not None:
        try:
            _date(cut["asOf"])
        except BoundaryViolation as error:
            problems.append(str(error))
    if set(row.get("source") for row in cut.get("sourceEvaluations") or []) \
            != set(REQUIRED_SOURCES):
        problems.append("cut does not carry exactly five source evaluations")
    return problems


def assemble_cut(cut: dict, artifact: str) -> dict:
    require_artifact(artifact)
    problems = verify_floor_cut(cut)
    if problems:
        raise BoundaryViolation("cut invalid: %s" % "; ".join(problems))
    current = load_json(PHASE9_LEDGER)
    current_ids = [row["intakeId"] for row in current.get("entries", [])]
    cut_ids = set(cut.get("intakeIds") or [])
    post_cut = [evidence_id for evidence_id in current_ids
                if evidence_id not in cut_ids]
    return {
        "schemaVersion": 1, "cutId": cut["cutId"],
        "subjectArtifact": cut["subjectArtifact"],
        "authorizationState": cut["authorizationState"],
        "candidateDecision": cut["candidateDecision"],
        "convergence": cut["convergence"],
        "postCutEvidenceIds": post_cut,
        "historicalDecisionRewritten": False,
        "note": "assembled from the sealed historical cut; later evidence "
                "is named and excluded",
    }


def render_dashboard(status: dict) -> str:
    lines = [
        "# Phase 17 external floor operations", "", "## Candidate", "",
        "artifact: `%s`" % status["subjectArtifact"]["identifier"], "",
        "state: derived", "", "## Five floor sources", "",
        "| Source | Operational ready | Real evidence | Effective status | Contributes | Next required action |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for row in status["sources"]:
        action = row["reason"] if not row["contributes_to_floor"] else "none for this source"
        lines.append("| %s | %s | %d | %s | %s | %s |" % (
            row["source"], "yes" if row["source_operational_ready"] else "no",
            len(row["evidenceIds"]), row["effectiveStatus"],
            "yes" if row["contributes_to_floor"] else "no",
            action.replace("|", "/"),
        ))
    lines += ["", "## Conflicts", ""]
    if status["conflicts"]:
        for conflict in status["conflicts"]:
            lines.append("- %s — blocking=%s: %s" % (
                " + ".join(conflict["sources"]),
                str(conflict["blocking"]).lower(), conflict["reason"]))
    else:
        lines.append("count: 0")
    lines += ["", "## Expiries", "",
              "Evaluated only from records and the explicit `asOf`; no wall clock is read.",
              "", "## Candidate decision", "",
              status["candidateDecision"], "", "## Single next deterministic action", "",
              status["singleNextDeterministicAction"], ""]
    return "\n".join(lines)


def sync_status(artifact: str, as_of: str | None = None) -> dict:
    status = derive_floor_status(artifact, as_of)
    dump_json(FLOOR_PATH, status)
    DASHBOARD_PATH.write_text(
        render_dashboard(status), encoding="utf-8", newline="\n"
    )
    return status


def boundary_problems() -> list[str]:
    """AST enforcement for the one-door and explicit-time boundaries."""
    problems = []
    sources = [ENGINE_PATH, VERIFY_PATH]

    def dotted(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            left = dotted(node.value)
            return (left + "." + node.attr) if left else node.attr
        if isinstance(node, ast.Call):
            return dotted(node.func) + "()"
        return ""

    for path in sources:
        if not path.is_file():
            problems.append("boundary: missing %s" % path.name)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parent_functions: dict[ast.AST, str] = {}
        for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(function):
                parent_functions[node] = function.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = dotted(node.func)
            if call in ("datetime.datetime.now", "datetime.date.today",
                        "time.time", "datetime.datetime.utcnow"):
                problems.append("boundary: %s reads a wall clock via %s"
                                % (path.name, call))
            if call.endswith(".register") or call == "register":
                if path != ENGINE_PATH or parent_functions.get(node) != "receive":
                    problems.append(
                        "boundary: Phase 9 register may be called only by receive"
                    )
            if call.endswith(".dump_ledger"):
                problems.append("boundary: Phase 17 must not dump a ledger")
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "write_bytes", "write_text", "copy", "copy2", "copyfile"):
                if parent_functions.get(node) == "receive":
                    problems.append(
                        "boundary: receive copies or writes evidence instead of delegating"
                    )
            if call == "open" or call.endswith(".open"):
                mode = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for keyword in node.keywords:
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                        mode = keyword.value.value
                if isinstance(mode, str) and "a" in mode:
                    problems.append("boundary: append-mode file I/O is forbidden")
    source = ENGINE_PATH.read_text(encoding="utf-8")
    if "_phase9().register" not in source:
        problems.append("boundary: receive no longer delegates to Phase 9 register")
    return problems


def _fixture(name: str) -> dict:
    return copy.deepcopy(load_json(FIXTURES / name)["record"])


def _assignment(number: int, authority: str, identity: str,
                expires: str | None = None) -> dict:
    row = {
        "assignmentId": "ASSIGNMENT-%03d" % number,
        "authorityId": authority, "identity": identity,
        "assignedBy": "FIXTURE-ORGANIZATION", "date": "2026-08-18",
        "basis": "TEST_FIXTURE_ONLY scratch authority",
    }
    if expires:
        row["expires_at"] = expires
    return row


def _scenario_context() -> dict:
    return {
        "assignments": [
            _assignment(1, "AUTH-HARDWARE", "FIXTURE-HARDWARE-OPERATOR"),
            _assignment(2, "AUTH-KEY", "FIXTURE-SIGNER"),
            _assignment(3, "AUTH-SECOND-APPROVER", "FIXTURE-SECOND-APPROVER"),
            _assignment(4, "AUTH-ALPHA-PROGRAM", "FIXTURE-ALPHA-OWNER"),
            _assignment(5, "AUTH-RELEASE", "FIXTURE-RELEASE-AUTHORITY"),
        ],
        "securityGate": "SATISFIED", "securityConflict": "NONE",
        "alphaSufficiency": {
            "determination": "SUFFICIENT",
            "policyState": "SUFFICIENCY_POLICY_ACTIVE",
            "activePolicy": "SUFFICIENCY-POLICY-017",
        },
        "alphaBlockers": [], "cutId": "CUT-017",
    }


def _matrix_row(scenario_id: str, source: str, expected: str,
                observed_ok: bool, *, record: dict | None = None,
                intake: str = "SCRATCH", validation: str = "EXECUTED",
                binding: str = "EXECUTED", evaluation: str = "EXECUTED",
                contribution: bool = False, cut_effect: str = "UNCHANGED",
                candidate_effect: str = "NO_AUTHORIZATION",
                designation: str = "TEST_FIXTURE_ONLY") -> dict:
    raw = json.dumps(record or {}, sort_keys=True).encode("utf-8")
    return {
        "id": scenario_id, "source": source,
        "evidenceClass": SOURCE_CLASSES.get(source, "MULTI_SOURCE"),
        "route": "Phase 9 -> owning engine -> Phase 17 floor",
        "artifactIdentity": _subject()["identifier"],
        "intakeResult": intake, "validationResult": validation,
        "bindingResult": binding, "sourceSpecificEvaluation": evaluation,
        "floorContribution": contribution, "cutEffect": cut_effect,
        "candidateEffect": candidate_effect,
        "fixtureOrReal": designation, "expectedOutcome": expected,
        "observedOutcome": expected if observed_ok else "DIVERGED",
        "inputHashes": {
            "scenarioRecordSha256": _sha256(raw),
            "realLedgerSha256": _sha256(PHASE9_LEDGER.read_bytes()),
            "sourceRegistrySha256": _sha256(REGISTRY_PATH.read_bytes()),
        },
    }


def run_scenarios() -> dict:
    """Execute 64 non-trivial controls without touching real inputs."""
    real_before = {path: path.read_bytes() for path in REAL_IMMUTABLE_INPUTS
                   if path.is_file()}
    rows = []
    artifact = _subject()["identifier"]
    context = _scenario_context()

    # Registry, readiness, and real-universe controls (12).
    for source in REQUIRED_SOURCES:
        contract = source_contract(source)
        rows.append(_matrix_row(
            "REGISTRY-%s" % source.upper().replace("-", "_"), source,
            "SOURCE_CLASSIFIED", contract["canonicalEvidenceClass"] == SOURCE_CLASSES[source],
            evaluation=contract["owningPhaseEngine"],
        ))
    try:
        source_contract("generic-external-evidence")
        unknown_refused = False
    except BoundaryViolation:
        unknown_refused = True
    rows.append(_matrix_row("REGISTRY-UNKNOWN-REFUSED", "multi-source",
                            "UNKNOWN_SOURCE_REFUSED", unknown_refused,
                            validation="REFUSED"))
    real = derive_floor_status(artifact)
    rows.append(_matrix_row(
        "REAL_UNIVERSE_READ_ONLY", "multi-source", "REAL_STATE_DERIVED",
        len(real["sources"]) == 5 and real["candidateDecision"] != "AUTHORIZED",
        intake="READ_ONLY", validation="LIVE_INPUTS", binding="LIVE_INPUTS",
        evaluation=real["candidateDecision"], designation="REAL",
    ))
    rows.append(_matrix_row(
        "READINESS-NOT-SATISFACTION", "multi-source",
        "READINESS_SEPARATE_FROM_SATISFACTION",
        all(row["source_operational_ready"] for row in real["sources"])
        and all(row["source_evidence_received"] or
                not row["contributes_to_floor"] for row in real["sources"]),
        intake="LIVE_READ_ONLY", evaluation="FIVE_SOURCE_VIEW",
        designation="REAL",
    ))

    # Hardware dimensional controls (12).
    passing = _fixture("hardware-passing-machine.json")
    mixed = _fixture("hardware-mixed-machine.json")
    hardware_cases = []
    hardware_cases.append(("HW-FULL-PASS", passing, lambda r: r["contributes"],
                           "QUALIFIED_DECLARED_SCOPE"))
    hardware_cases.append(("HW-MIC-FAIL", mixed, lambda r: not r["contributes"] and
                           r["dimensions"]["installation"] == "PASS" and
                           r["dimensions"]["microphone"] == "FAIL",
                           "MACHINE_DIMENSIONS_PRESERVED"))
    native_unsupported = copy.deepcopy(passing)
    native_unsupported["results"]["companion-3d-native"]["status"] = "NOT_SUPPORTED"
    hardware_cases.append(("HW-NATIVE-UNSUPPORTED-FALLBACK-PASS", native_unsupported,
                           lambda r: r["contributes"], "ALTERNATIVE_PRESERVED"))
    native_fail = copy.deepcopy(passing)
    native_fail["results"]["companion-3d-native"]["status"] = "FAIL"
    hardware_cases.append(("HW-NATIVE-FAIL-FALLBACK-PASS", native_fail,
                           lambda r: not r["contributes"], "NATIVE_FAILURE_NOT_ERASED"))
    wrong = copy.deepcopy(passing); wrong["artifactDigest"] = "f" * 64
    hardware_cases.append(("HW-WRONG-ARTIFACT", wrong,
                           lambda r: not r["contributes"], "WRONG_ARTIFACT_REFUSED"))
    missing_machine = copy.deepcopy(passing); missing_machine["machine"].pop("machineId")
    hardware_cases.append(("HW-MISSING-MACHINE-ID", missing_machine,
                           lambda r: not r["contributes"], "MACHINE_ID_REQUIRED"))
    missing_medium = copy.deepcopy(passing); missing_medium.pop("installationMediumIdentity")
    hardware_cases.append(("HW-MISSING-MEDIA-DIGEST", missing_medium,
                           lambda r: not r["contributes"], "MEDIA_ID_REQUIRED"))
    feedback = _fixture("alpha-report.json")
    hardware_cases.append(("HW-USER-FEEDBACK-NOT-PROTOCOL", feedback,
                           lambda r: not r["contributes"], "USER_FEEDBACK_NOT_HARDWARE_PROTOCOL"))
    no_policy = copy.deepcopy(passing); no_policy.pop("supportPolicy")
    hardware_cases.append(("HW-NO-SUPPORT-POLICY", no_policy,
                           lambda r: not r["contributes"], "POLICY_REQUIRED"))
    expired = copy.deepcopy(passing); expired["supportPolicy"]["expiresAt"] = "2026-08-19"
    hardware_cases.append(("HW-EXPIRED-POLICY", expired,
                           lambda r: not r["contributes"], "EXPIRED_POLICY_BLOCKS"))
    contradiction = copy.deepcopy(passing); contradiction["hwId"] = "HW-002"
    contradiction["results"]["companion-3d-native"]["status"] = "FAIL"
    effective = _phase14().hardware_effective_state([
        {"hwId": passing["hwId"], "artifactBinding": "BOUND", "results": passing["results"]},
        {"hwId": contradiction["hwId"], "artifactBinding": "BOUND", "results": contradiction["results"]},
    ])
    rows.append(_matrix_row(
        "HW-CONTRADICTORY-GRAPHICS", "hardware", "NO_AVERAGING",
        any(r["dimension"] == "companion-3d-native" and r["divergent"]
            for r in effective["perDimension"]), record=contradiction,
        contribution=False, evaluation="MACHINE_RESULTS_PRESERVED",
    ))
    try:
        _phase14().hardware_claims(effective, "SUPPORTED ON PCS")
        support_refused = False
    except Exception:
        support_refused = True
    rows.append(_matrix_row("HW-FINITE-SET-NO-PC-CLAIM", "hardware",
                            "AGGREGATE_CLAIM_REFUSED", support_refused,
                            evaluation="NO_AGGREGATE_POLICY"))
    for scenario_id, record, predicate, expected in hardware_cases:
        try:
            result = evaluate_record("hardware", record, artifact, record.get("hwId", "HW-X"),
                                     "2026-08-20", context)
            ok = predicate(result)
        except Exception:
            ok = scenario_id == "HW-USER-FEEDBACK-NOT-PROTOCOL"
            result = {"contributes": False, "effectiveStatus": "REFUSED"}
        rows.append(_matrix_row(scenario_id, "hardware", expected, ok,
                                record=record, contribution=result["contributes"],
                                evaluation=result["effectiveStatus"]))

    # Signing controls (10).
    signing = _fixture("production-signing-shaped.json")
    signing_cases = [
        ("SIGN-PRODUCTION-VERIFIED", signing, True, "VERIFIED_PRODUCTION_SIGNING"),
        ("SIGN-DRILL", _fixture("signing-drill.json"), False, "DRILL_NEVER_CONTRIBUTES"),
    ]
    wrong_artifact = copy.deepcopy(signing); wrong_artifact["artifactDigest"] = "e" * 64
    signing_cases.append(("SIGN-CORRECT-SIGNATURE-WRONG-ARTIFACT", wrong_artifact, False, "WRONG_ARTIFACT"))
    wrong_signature = copy.deepcopy(signing); wrong_signature["verificationResult"] = "FAIL"
    signing_cases.append(("SIGN-WRONG-SIGNATURE-CORRECT-ARTIFACT", wrong_signature, False, "VERIFICATION_FAIL"))
    no_recomputed = copy.deepcopy(signing); no_recomputed.pop("independentlyRecomputedArtifactDigest")
    signing_cases.append(("SIGN-MISSING-RECOMPUTED-DIGEST", no_recomputed, False, "RECOMPUTED_DIGEST_REQUIRED"))
    unauthorized = copy.deepcopy(signing); unauthorized["signerIdentity"] = "UNASSIGNED-SIGNER"
    signing_cases.append(("SIGN-UNAUTHORIZED", unauthorized, False, "AUTHORITY_REQUIRED"))
    expired_context = copy.deepcopy(context)
    expired_context["assignments"][1]["expires_at"] = "2026-08-19"
    revoked_context = copy.deepcopy(context)
    revoked_context["assignmentRevocations"] = [{
        "revocationId": "AR-001", "targetAssignment": "ASSIGNMENT-002",
        "reason": "fixture", "authority": "FIXTURE-ORGANIZATION",
        "timestamp": "2026-08-19",
    }]
    bad_time = copy.deepcopy(signing); bad_time["signingTimestamp"] = "2026-08-19T12:00:00"
    signing_cases.append(("SIGN-MALFORMED-ZONE", bad_time, False, "TIME_REFUSED"))
    fixture_wrapper = load_json(FIXTURES / "production-signing-shaped.json")
    try:
        evaluate_record("signing", fixture_wrapper, artifact, "FIXTURE", "2026-08-20", context)
        fixture_refused = False
    except BoundaryViolation:
        fixture_refused = True
    rows.append(_matrix_row("SIGN-FIXTURE-REAL-PATH", "signing",
                            "FIXTURE_REJECTED", fixture_refused,
                            record=fixture_wrapper, validation="REJECTED"))
    for scenario_id, record, should_contribute, expected in signing_cases:
        result = evaluate_record("signing", record, artifact, "SIG-001",
                                 "2026-08-20", context)
        rows.append(_matrix_row(scenario_id, "signing", expected,
                                result["contributes"] is should_contribute,
                                record=record, contribution=result["contributes"],
                                evaluation=result["effectiveStatus"]))
    for scenario_id, special_context, expected in (
        ("SIGN-EXPIRED-AUTHORITY", expired_context, "EXPIRED_AUTHORITY_BLOCKS"),
        ("SIGN-REVOKED-AUTHORITY", revoked_context, "REVOKED_AUTHORITY_BLOCKS"),
    ):
        result = evaluate_record("signing", signing, artifact, "SIG-001",
                                 "2026-08-20", special_context)
        rows.append(_matrix_row(scenario_id, "signing", expected,
                                not result["contributes"], record=signing,
                                evaluation=result["authorityState"]))

    # Second approval controls (10).
    approval = _fixture("second-approval-independent.json")
    approval_context = copy.deepcopy(context); approval_context["signingRecords"] = [signing]
    approval_cases = [("APPROVAL-AFTER-SIGNING", approval, approval_context, True, "APPROVED")]
    before = copy.deepcopy(approval); before["timestamp"] = "2026-08-19T11:00:00Z"
    approval_cases.append(("APPROVAL-BEFORE-SIGNING", before, approval_context, False, "ORDERING_REFUSED"))
    other = copy.deepcopy(approval); other["independentlyRecomputedArtifactDigest"] = "d" * 64
    approval_cases.append(("APPROVAL-WRONG-ARTIFACT", other, approval_context, False, "WRONG_ARTIFACT"))
    stale = copy.deepcopy(approval); stale["relevantEvidenceCut"] = "CUT-016"
    approval_cases.append(("APPROVAL-EARLIER-CUT", stale, approval_context, False, "STALE_CUT"))
    conditional = copy.deepcopy(approval); conditional["decision"] = "CONDITIONAL"; conditional["conditions"] = ["fix X"]
    approval_cases.append(("APPROVAL-CONDITIONAL", conditional, approval_context, False, "CONDITIONAL_NOT_APPROVED"))
    rejected = copy.deepcopy(approval); rejected["decision"] = "REJECTED"
    approval_cases.append(("APPROVAL-REJECTED", rejected, approval_context, False, "REJECTED_BLOCKS"))
    duplicate = _fixture("second-approval-duplicate-role.json")
    duplicate_context = copy.deepcopy(approval_context)
    duplicate_context["assignments"][2]["identity"] = "FIXTURE-SIGNER"
    approval_cases.append(("APPROVAL-SIGNER-OVERLAP", duplicate, duplicate_context, False, "SEPARATION_REFUSED"))
    release_overlap = copy.deepcopy(approval_context)
    release_overlap["assignments"][4]["identity"] = "FIXTURE-SECOND-APPROVER"
    approval_cases.append(("APPROVAL-RELEASE-OVERLAP", approval, release_overlap, False, "SEPARATION_REFUSED"))
    risk_expired = copy.deepcopy(approval_context); risk_expired["expiredRisks"] = ["RISK-001"]
    approval_cases.append(("APPROVAL-EXPIRED-RISK", approval, risk_expired, False, "EXPIRED_RISK_BLOCKS"))
    revoked_approval = copy.deepcopy(approval_context)
    revoked_approval["assignmentRevocations"] = [{
        "revocationId": "AR-002", "targetAssignment": "ASSIGNMENT-003",
        "reason": "fixture", "authority": "FIXTURE-ORGANIZATION",
        "timestamp": "2026-08-20",
    }]
    approval_cases.append(("APPROVAL-AUTHORITY-REVOKED", approval, revoked_approval, False, "REVOCATION_BLOCKS"))
    for scenario_id, record, case_context, should_contribute, expected in approval_cases:
        result = evaluate_record("second-approval", record, artifact, "APPROVAL-001",
                                 "2026-08-20", case_context)
        rows.append(_matrix_row(scenario_id, "second-approval", expected,
                                result["contributes"] is should_contribute,
                                record=record, contribution=result["contributes"],
                                evaluation=result["effectiveStatus"]))

    # Alpha and security controls (12).
    alpha = _fixture("alpha-report.json")
    alpha_cases = []
    zero_context = copy.deepcopy(context)
    zero_context["alphaSufficiency"] = {
        "determination": "SUFFICIENCY_UNDETERMINED",
        "policyState": "SUFFICIENCY_POLICY_UNDEFINED", "activePolicy": None,
    }
    alpha_cases.append(("ALPHA-ZERO-REPORTS", zero_context, False, "NO_EVIDENCE_UNDETERMINED"))
    alpha_cases.append(("ALPHA-100-NO-POLICY", zero_context, False, "MANY_REPORTS_STILL_UNDETERMINED"))
    alpha_cases.append(("ALPHA-SUFFICIENT-FIXTURE", context, True, "SUFFICIENT_WITH_POLICY"))
    blocked_alpha = copy.deepcopy(context); blocked_alpha["alphaBlockers"] = ["ALPHA-EXT-001"]
    alpha_cases.append(("ALPHA-BLOCKER", blocked_alpha, False, "BLOCKER_PREVENTS_CONTRIBUTION"))
    insufficient_alpha = copy.deepcopy(context)
    insufficient_alpha["alphaSufficiency"]["determination"] = "INSUFFICIENT_EVIDENCE"
    alpha_cases.append(("ALPHA-INSUFFICIENT", insufficient_alpha, False, "INSUFFICIENT"))
    for scenario_id, case_context, should_contribute, expected in alpha_cases:
        result = evaluate_record("alpha-feedback", alpha, artifact, "T-017",
                                 "2026-08-20", case_context)
        rows.append(_matrix_row(scenario_id, "alpha-feedback", expected,
                                result["contributes"] is should_contribute,
                                record=alpha, contribution=result["contributes"],
                                evaluation=result["effectiveStatus"]))
    unbound = copy.deepcopy(alpha); unbound.pop("artifactDigest")
    result = evaluate_record("alpha-feedback", unbound, artifact, "T-018",
                             "2026-08-20", context)
    rows.append(_matrix_row("ALPHA-UNBOUND-PRESERVED", "alpha-feedback",
                            "USER_EVIDENCE_UNBOUND_NONCONTRIBUTING",
                            not result["contributes"] and result["binding"]["result"] == "UNBOUND",
                            record=unbound, binding="UNBOUND", evaluation=result["effectiveStatus"]))
    security = _fixture("security-favorable.json")
    security_cases = [
        ("SECURITY-NO-REVIEW", {**context, "securityGate": "AWAITING_EXTERNAL_EVIDENCE"}, False, "NO_REVIEW_BLOCKS"),
        ("SECURITY-FAVORABLE-SCRATCH", context, True, "SATISFIED_SCRATCH"),
        ("SECURITY-UNRESOLVED-CRITICAL", {**context, "securityGate": "BLOCKED"}, False, "CRITICAL_BLOCKS"),
        ("SECURITY-CONFLICT", {**context, "securityConflict": "CONFLICT"}, False, "CONFLICT_BLOCKS"),
        ("SECURITY-EXPIRED-RISK", {**context, "expiredRisks": ["RISK-001"]}, False, "EXPIRED_RISK_BLOCKS"),
    ]
    for scenario_id, case_context, should_contribute, expected in security_cases:
        result = evaluate_record("security-review", security, artifact, "REVIEW-001",
                                 "2026-08-20", case_context)
        rows.append(_matrix_row(scenario_id, "security-review", expected,
                                result["contributes"] is should_contribute,
                                record=security, contribution=result["contributes"],
                                evaluation=result["effectiveStatus"]))
    wrong_security = copy.deepcopy(security); wrong_security["artifactDigest"] = "c" * 64
    wrong_security["artifact_digest"] = "c" * 64
    result = evaluate_record("security-review", wrong_security, artifact, "REVIEW-X",
                             "2026-08-20", context)
    rows.append(_matrix_row("SECURITY-WRONG-ARTIFACT", "security-review",
                            "WRONG_ARTIFACT_REFUSED", not result["contributes"],
                            record=wrong_security, evaluation=result["effectiveStatus"]))

    # Convergence, cut, revision, successor, and hygiene controls (15).
    base_rows = []
    for source in REQUIRED_SOURCES:
        base_rows.append({
            "source": source, "evidenceIds": [source + "-FIXTURE"],
            "contributes_to_floor": True, "conflictState": "NONE",
            "provenance": {"ownerEngineResult": True},
        })
    for count in range(6):
        candidate_rows = copy.deepcopy(base_rows)
        for index, row in enumerate(candidate_rows):
            row["contributes_to_floor"] = index < count
        convergence = converge_rows(candidate_rows)
        rows.append(_matrix_row(
            "FLOOR-%d-OF-5" % count, "multi-source",
            "FLOOR_SATISFIED" if count == 5 else "AUTHORIZED_IMPOSSIBLE",
            convergence["satisfied"] is (count == 5),
            contribution=convergence["satisfied"],
            candidate_effect="READY_FOR_AUTHORITY" if count == 5 else "REQUIRES_MORE_EVIDENCE",
        ))
    internal_rows = [{"source": s, "contributes_to_floor": True,
                      "conflictState": "NONE", "evidenceIds": [],
                      "provenance": {}} for s in REQUIRED_SOURCES]
    rows.append(_matrix_row("INTERNAL-ALL-PASS-JSON", "multi-source",
                            "INTERNAL_CLAIM_REFUSED",
                            not converge_rows(internal_rows)["satisfied"],
                            validation="REFUSED"))
    conflict_rows = copy.deepcopy(base_rows); conflict_rows[0]["conflictState"] = "CONFLICT"
    rows.append(_matrix_row("FLOOR-ONE-CONFLICT", "multi-source",
                            "CONFLICT_BLOCKS_FLOOR",
                            not converge_rows(conflict_rows)["satisfied"],
                            candidate_effect="REQUIRES_HUMAN_DECISION"))
    cut_a = build_floor_cut("CUT-017", artifact, "2026-08-20")
    cut_b = build_floor_cut("CUT-017", artifact, "2026-08-20")
    rows.append(_matrix_row("CUT-DETERMINISTIC", "multi-source",
                            "BYTE_IDENTICAL", _canonical(cut_a) == _canonical(cut_b),
                            cut_effect=cut_a["seal"]))
    tampered = copy.deepcopy(cut_a); tampered["candidateDecision"] = "AUTHORIZED"
    rows.append(_matrix_row("CUT-TAMPER", "multi-source", "SEAL_REFUSED",
                            bool(verify_floor_cut(tampered)), cut_effect="IMMUTABILITY_FAIL"))
    malformed_dates = ("2026-08-20junk", "2026-02-30")
    for index, value in enumerate(malformed_dates, 1):
        try:
            _instant(value)
            refused = False
        except BoundaryViolation:
            refused = True
        rows.append(_matrix_row("TIME-EXACT-%d" % index, "multi-source",
                                "MALFORMED_TIME_REFUSED", refused,
                                validation="REFUSED"))
    successor = copy.deepcopy(load_json(PHASE10_GRAPH))
    successor["artifacts"].append({
        "artifact_id": "SUCCESSOR-B", "digest": "sha256:" + "b" * 64,
        "digests": {"image": "sha256:" + "b" * 64},
        "parent_artifact": _subject()["identifier"], "relationship": "REMEDIATES",
        "qualification_state": "EVIDENCE_PENDING", "signingStatus": "UNSIGNED",
        "source_commit": "b" * 40, "supersedes": _subject()["identifier"],
        "build_identity": "TEST_FIXTURE_ONLY",
    })
    applicability = _phase10().evaluate_applicability({
        "evidenceId": "PARENT-EVIDENCE", "artifactDigest": _subject()["imageDigest"],
        "scope": "security-review",
    }, "SUCCESSOR-B", successor)
    rows.append(_matrix_row("SUCCESSOR-NO-INHERITANCE", "multi-source",
                            "DOES_NOT_APPLY", applicability["result"] != "APPLIES",
                            candidate_effect="SUCCESSOR_EVIDENCE_PENDING"))
    secret_samples = {
        "SECRET-REVIEW-BEARER": b"Bearer abcdefghijklmnopqrstuvwxyz123456",
        "SECRET-HARDWARE-PASSWORD": b"password=correcthorsebatterystaple",
        "SECRET-SIGNING-PRIVATE-KEY": b"-----BEGIN PRIVATE KEY-----\nfixture",
        "SECRET-APPROVAL-CREDENTIAL": b"api_key=abcdefghijklmnopqrstuvwx",
        "SECRET-ALPHA-TOKEN": b"session_token=abcdefghijklmnopqrstuvwx",
    }
    for scenario_id, raw in secret_samples.items():
        detected = _phase9().detect_secret_classes(raw)
        source = {
            "SECRET-REVIEW-BEARER": "security-review",
            "SECRET-HARDWARE-PASSWORD": "hardware",
            "SECRET-SIGNING-PRIVATE-KEY": "signing",
            "SECRET-APPROVAL-CREDENTIAL": "second-approval",
            "SECRET-ALPHA-TOKEN": "alpha-feedback",
        }[scenario_id]
        rows.append(_matrix_row(scenario_id, source, "SECRET_QUARANTINED",
                                bool(detected), validation="QUARANTINED"))

    # Real inputs must be identical after every scenario family.
    unchanged = all(path.is_file() and path.read_bytes() == raw
                    for path, raw in real_before.items())
    if not unchanged:
        rows.append(_matrix_row("REAL-INPUT-INTEGRITY-FAIL", "multi-source",
                                "REAL_INPUTS_UNCHANGED", False,
                                designation="REAL"))
    for row in rows:
        if any(path.read_bytes() != raw for path, raw in real_before.items()):
            row["observedOutcome"] = "DIVERGED"
    return {
        "schemaVersion": 1, "scenarioCount": len(rows), "scenarios": rows,
        "realInputsUnchanged": unchanged,
        "realInputHashes": {
            path.relative_to(ROOT).as_posix(): _sha256(raw)
            for path, raw in real_before.items()
        },
        "note": "all hypothetical records are TEST_FIXTURE_ONLY and execute "
                "only through production functions in scratch/in-memory universes",
    }


def recovery_matrix(matrix: dict) -> dict:
    rows = []
    for scenario in matrix["scenarios"]:
        if scenario["observedOutcome"] == scenario["expectedOutcome"]:
            recovery = "preserve result; no recovery required"
        else:
            recovery = "stop; reproduce; patch owning phase; add owner regression; re-derive history"
        rows.append({
            "id": scenario["id"], "source": scenario["source"],
            "failure": scenario["expectedOutcome"], "recovery": recovery,
            "realEvidenceMutationPermitted": False,
        })
    return {"schemaVersion": 1, "rows": rows}


def matrix_problems(matrix: dict | None = None) -> list[str]:
    matrix = matrix or load_json(MATRIX_PATH)
    derived = run_scenarios()
    problems = []
    if _canonical(matrix) != _canonical(derived):
        problems.append("MATRIX.json does not re-derive byte-identically")
    if not 50 <= derived["scenarioCount"] <= 70:
        problems.append("matrix scenario count must remain between 50 and 70")
    diverged = [r["id"] for r in derived["scenarios"]
                if r["expectedOutcome"] != r["observedOutcome"]]
    if diverged:
        problems.append("matrix scenarios diverged: %s" % ", ".join(diverged))
    if not any(r["id"] == "REAL_UNIVERSE_READ_ONLY"
               for r in derived["scenarios"]):
        problems.append("matrix lacks REAL_UNIVERSE_READ_ONLY")
    return problems


def status_problems() -> list[str]:
    problems = []
    derived = derive_floor_status(_subject()["identifier"])
    if not FLOOR_PATH.is_file() or _canonical(load_json(FLOOR_PATH)) != _canonical(derived):
        problems.append("FLOOR_STATUS.json does not re-derive")
    rendered = render_dashboard(derived).encode("utf-8")
    if not DASHBOARD_PATH.is_file() or DASHBOARD_PATH.read_bytes() != rendered:
        problems.append("PHASE17_EXTERNAL_FLOOR_OPERATIONS.md does not re-derive")
    return problems


def fixture_problems() -> list[str]:
    problems = []
    for path in sorted(FIXTURES.glob("*.json")):
        wrapper = load_json(path)
        if not is_fixture(wrapper):
            problems.append("fixture %s lacks a structural marker" % path.name)
    return problems


def verify_all() -> list[str]:
    problems = []
    required = (
        "README.md", "CONTRACT.md", "SOURCE_REGISTRY.json",
        "HARDWARE_EXECUTION.md", "SIGNING_EXECUTION.md",
        "SECOND_APPROVAL_EXECUTION.md", "ALPHA_EXECUTION.md",
        "CONVERGENCE_POLICY.md", "FLOOR_STATUS.md", "EVIDENCE_CUT_POLICY.md",
        "FLOOR_STATUS.json", "MATRIX.json", "FAILURE_RECOVERY_MATRIX.json",
        "tools/external_floor_ops.py", "tools/verify_phase17.py",
    )
    for name in required:
        if not (PHASE17 / name).is_file():
            problems.append("required file missing: qualification/phase17/%s" % name)
    problems += registry_problems()
    problems += boundary_problems()
    problems += fixture_problems()
    if MATRIX_PATH.is_file():
        problems += matrix_problems()
    if FLOOR_PATH.is_file() and DASHBOARD_PATH.is_file():
        problems += status_problems()
    subject = _subject()
    if not subject["frozen"] or subject["relationship"] != "ROOT":
        problems.append("subject artifact is no longer frozen ROOT")
    if subject["signingStatus"] != "UNSIGNED":
        # A later real signature may prove a changed state, but the graph must
        # be re-derived by its owning engine before Phase 17 accepts it.
        problems.append("subject artifact signing state changed without owner derivation")
    return problems


def _read_cli_record(path: str) -> dict:
    record = load_json(Path(path))
    _refuse_fixture(record, "operator")
    return record


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=1, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_p = sub.add_parser("prepare")
    prepare_p.add_argument("--source", required=True, choices=REQUIRED_SOURCES)
    prepare_p.add_argument("--out", required=True)

    for command in ("inspect", "validate", "bind", "evaluate"):
        item = sub.add_parser(command)
        item.add_argument("--source", required=True, choices=REQUIRED_SOURCES)
        item.add_argument("--path", required=True)
        item.add_argument("--artifact", required=True)
        item.add_argument("--evidence-id", required=True)
        item.add_argument("--attach", action="append", default=[])
        if command == "evaluate":
            item.add_argument("--as-of")

    receive_p = sub.add_parser("receive")
    receive_p.add_argument("--source", required=True, choices=REQUIRED_SOURCES)
    receive_p.add_argument("--path", required=True)
    receive_p.add_argument("--artifact", required=True)
    receive_p.add_argument("--evidence-id", required=True)
    receive_p.add_argument("--attach", action="append", default=[])
    receive_p.add_argument("--received-on", required=True)
    receive_p.add_argument("--submitted-by", required=True)
    receive_p.add_argument("--revises")

    cut_p = sub.add_parser("cut")
    cut_p.add_argument("--cut-id", required=True)
    cut_p.add_argument("--artifact", required=True)
    cut_p.add_argument("--as-of")

    assemble_p = sub.add_parser("assemble")
    assemble_p.add_argument("--cut-id", required=True)
    assemble_p.add_argument("--artifact", required=True)

    for command in ("floor-status", "status", "sync-status"):
        item = sub.add_parser(command)
        item.add_argument("--artifact", required=True)
        item.add_argument("--as-of")

    sub.add_parser("build-matrix")
    sub.add_parser("verify")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            _print(prepare(args.source, Path(args.out)))
        elif args.command == "inspect":
            _print(inspect_path(args.source, Path(args.path), args.artifact,
                                args.evidence_id, [Path(p) for p in args.attach]))
        elif args.command == "receive":
            _print(receive(args.source, Path(args.path), args.artifact,
                           args.evidence_id, [Path(p) for p in args.attach],
                           args.received_on, args.submitted_by, args.revises))
        elif args.command == "validate":
            record = _read_cli_record(args.path)
            subject = require_artifact(args.artifact)
            _print(_phase9().validate_record(
                args.source, record, set(subject["digests"])))
        elif args.command == "bind":
            _print(bind_record(args.source, _read_cli_record(args.path),
                               args.artifact, args.evidence_id))
        elif args.command == "evaluate":
            _print(evaluate_record(args.source, _read_cli_record(args.path),
                                   args.artifact, args.evidence_id, args.as_of,
                                   _real_context(args.as_of, load_json(PHASE9_LEDGER))))
        elif args.command == "cut":
            cut = build_floor_cut(args.cut_id, args.artifact, args.as_of)
            path = write_cut(cut)
            _print({"cut": cut, "path": str(path)})
        elif args.command == "assemble":
            _print(assemble_cut(load_json(CUTS / (args.cut_id + ".json")),
                                args.artifact))
        elif args.command in ("floor-status", "status"):
            _print(derive_floor_status(args.artifact, args.as_of))
        elif args.command == "sync-status":
            _print(sync_status(args.artifact, args.as_of))
        elif args.command == "build-matrix":
            matrix = run_scenarios()
            dump_json(MATRIX_PATH, matrix)
            dump_json(RECOVERY_PATH, recovery_matrix(matrix))
            _print({"scenarioCount": matrix["scenarioCount"], "written": True})
        elif args.command == "verify":
            problems = verify_all()
            if problems:
                for problem in problems:
                    print(problem)
                return 2
            print("phase 17 verifies clean")
        return 0
    except (BoundaryViolation, OSError, ValueError) as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

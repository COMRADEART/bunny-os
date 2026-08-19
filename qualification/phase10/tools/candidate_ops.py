#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 10 candidate operations: the boundaries, made mechanical.

Phase 9 built the door evidence enters through; this module is what happens
on the other side of it, encoded so the failure modes the phase brief names
cannot happen silently:

* the artifact graph records relationships explicitly — nothing is inferred
  from commit history, and evidence for one artifact evaluated against
  another defaults to DOES_NOT_APPLY;
* the impact model classifies changed components into qualification domains
  through a committed mapping, failing closed on anything unmapped;
* the requalification planner plans work — its vocabulary has no PASS, and
  a plan claiming one fails validation;
* the candidate state machine allows only declared transitions, and
  AUTHORIZED is reachable only from ALPHA_READY with the Phase 9
  authorization floor satisfied;
* the finding lifecycle cannot close a finding because code changed —
  closure requires requalification evidence bound to the finding's
  artifact;
* harness corrections preserve the old verdict verbatim beside the
  corrected one, or they are invalid;
* candidate status is derived reproducibly from immutable inputs (the
  Phase 9 ledger — read, never written — the artifact graph, the findings
  registries, the pre-committed conditions), with state history append-only.

Everything here reads ``qualification/phase9/intake/``; nothing here writes
it. Synthetic evidence carries ``fixtureClass: TEST_FIXTURE_ONLY`` and is
refused structurally by the applicability engine, by status derivation, and
by Phase 9 registration itself.

Determinism: no clocks. Dates come from inputs or from the operator, and
the commit is the tamper-evident time.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE10 = ROOT / "qualification" / "phase10"
GRAPH_PATH = PHASE10 / "artifacts" / "artifact-graph.json"
MAPPING_PATH = PHASE10 / "impact" / "component-domains.json"
STATUS_PATH = PHASE10 / "candidate-status.json"
FINDINGS_PATH = PHASE10 / "findings" / "registry.json"
CORRECTIONS_PATH = PHASE10 / "harness-corrections.json"
FIXTURES_DIR = PHASE10 / "fixtures"
PHASE9_LEDGER = ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
PHASE9_DECISION = (
    ROOT / "qualification" / "phase9" / "decision" / "alpha-release-decision.json"
)
PHASE9_FINDINGS = ROOT / "qualification" / "phase9" / "triage" / "findings.json"
PHASE9_TOOL = ROOT / "qualification" / "phase9" / "tools" / "intake.py"

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

RELATIONSHIPS = (
    "ROOT", "REMEDIATES", "REBUILDS", "EXPERIMENTAL", "PARALLEL", "SUPERSEDES",
)

APPLICABILITY_RESULTS = (
    "APPLIES", "DOES_NOT_APPLY", "PARTIALLY_APPLIES", "REQUIRES_REVIEW",
    "ARTIFACT_MISMATCH",
)

#: §4 changed-area classification. HARNESS_ONLY marks measurement-system
#: changes, which never create a product artifact by themselves.
IMPACT_AREAS = (
    "BOOT", "INSTALLER", "SESSION", "COMPANION", "VOICE", "TRUST",
    "SECURITY", "ACCESSIBILITY", "PERFORMANCE", "UPDATE", "ROLLBACK",
    "RECOVERY", "RELEASE", "DOCUMENTATION", "HARNESS_ONLY",
)

#: §5 planner domains: the product areas plus HARDWARE (the physical-machine
#: gate, which is a qualification domain even though no repo component maps
#: to it — a machine is not a component).
PLANNER_DOMAINS = (
    "BOOT", "INSTALLER", "SESSION", "COMPANION", "VOICE", "TRUST",
    "SECURITY", "ACCESSIBILITY", "PERFORMANCE", "UPDATE", "ROLLBACK",
    "RECOVERY", "RELEASE", "DOCUMENTATION", "HARDWARE",
)

PLAN_STATUSES = ("REQUIRED", "RECOMMENDED", "NOT_REQUIRED", "REQUIRES_HUMAN_REVIEW")

#: Adjacent domains worth a RECOMMENDED when their neighbour changes but
#: nothing maps them directly. Declared, small, and easy to argue with.
ADJACENT_RECOMMENDED = {
    "BOOT": ("ROLLBACK", "RECOVERY"),
    "UPDATE": ("ROLLBACK",),
    "SESSION": ("ACCESSIBILITY",),
    "COMPANION": ("PERFORMANCE",),
    "INSTALLER": ("RECOVERY",),
}

CANDIDATE_STATES = (
    "FROZEN", "EVIDENCE_PENDING", "UNDER_REVIEW", "REMEDIATION_REQUIRED",
    "REQUALIFICATION_REQUIRED", "ALPHA_READY", "AUTHORIZED", "BLOCKED",
    "SUPERSEDED", "RETIRED",
)

#: Every allowed candidate transition, exhaustively. Absence is refusal:
#: REMEDIATION_REQUIRED cannot reach AUTHORIZED — the path runs through a
#: new artifact, which is a new candidate starting at FROZEN.
CANDIDATE_TRANSITIONS = {
    "FROZEN": {"EVIDENCE_PENDING", "REQUALIFICATION_REQUIRED"},
    "EVIDENCE_PENDING": {"UNDER_REVIEW", "BLOCKED", "SUPERSEDED", "RETIRED"},
    "UNDER_REVIEW": {"ALPHA_READY", "REMEDIATION_REQUIRED", "BLOCKED",
                     "EVIDENCE_PENDING", "SUPERSEDED"},
    "REMEDIATION_REQUIRED": {"BLOCKED", "SUPERSEDED", "RETIRED"},
    "REQUALIFICATION_REQUIRED": {"EVIDENCE_PENDING", "BLOCKED", "RETIRED"},
    "ALPHA_READY": {"AUTHORIZED", "EVIDENCE_PENDING", "BLOCKED", "SUPERSEDED"},
    "AUTHORIZED": {"BLOCKED", "SUPERSEDED", "RETIRED"},
    "BLOCKED": {"EVIDENCE_PENDING", "REMEDIATION_REQUIRED", "SUPERSEDED",
                "RETIRED"},
    "SUPERSEDED": {"RETIRED"},
    "RETIRED": set(),
}

FINDING_STATES = (
    "RECEIVED", "VALIDATED", "TRIAGED", "REPRODUCTION_PENDING", "CONFIRMED",
    "NOT_REPRODUCED", "FIX_REQUIRED", "ACCEPTED_RISK", "DEFERRED", "FIXED",
    "REQUALIFIED", "CLOSED",
)

FINDING_TRANSITIONS = {
    "RECEIVED": {"VALIDATED"},
    "VALIDATED": {"TRIAGED"},
    "TRIAGED": {"REPRODUCTION_PENDING"},
    "REPRODUCTION_PENDING": {"CONFIRMED", "NOT_REPRODUCED"},
    "CONFIRMED": {"FIX_REQUIRED", "ACCEPTED_RISK", "DEFERRED"},
    "FIX_REQUIRED": {"FIXED"},
    "FIXED": {"REQUALIFIED"},
    "REQUALIFIED": {"CLOSED"},
    "ACCEPTED_RISK": {"CLOSED", "FIX_REQUIRED"},
    "DEFERRED": {"FIX_REQUIRED", "TRIAGED"},
    "NOT_REPRODUCED": {"TRIAGED"},
    "CLOSED": set(),
}

HARNESS_CLASSIFICATIONS = (
    "PRODUCT_STATUS_UNCHANGED", "EVIDENCE_REINTERPRETED",
    "PRIOR_FALSE_PASS_FOUND", "PRIOR_FALSE_FAIL_FOUND",
)

ACCEPTANCE_FIELDS = ("risk", "owner", "affectedArtifact", "rationale", "reviewBy")

#: Finding identifiers: the ID assigned at first triage is the ID for life.
#: Phase 9's registry assigns the -P9- scheme; findings first entering
#: through Phase 10 operations take -EXT-. Both are one namespace.
FINDING_ID = re.compile(r"^(SEC|HW|ALPHA)-(P9|EXT)-\d{3}$")

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class BoundaryViolation(ValueError):
    """A refused transition, transfer, plan, or record."""


# ---------------------------------------------------------------- shared I/O

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def _phase9():
    spec = importlib.util.spec_from_file_location("phase9_intake_ops", PHASE9_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_fixture(record) -> bool:
    return isinstance(record, dict) and record.get("fixtureClass") == FIXTURE_MARKER


def _refuse_fixture(record, where: str) -> None:
    if is_fixture(record):
        raise BoundaryViolation(
            "%s: the record declares fixtureClass %s — a fixture is never "
            "evidence" % (where, FIXTURE_MARKER)
        )


def _normalize_digest(value: str) -> str:
    value = str(value).strip().lower()
    return value[7:] if value.startswith("sha256:") else value


# ---------------------------------------------------------------- the graph

def validate_graph(graph: dict) -> list[str]:
    """Structural issues with the artifact graph; empty means valid."""
    issues: list[str] = []
    artifacts = graph.get("artifacts", [])
    ids = [a.get("artifact_id") for a in artifacts]
    if len(ids) != len(set(ids)):
        issues.append("artifact_id values are not unique")
    known = set(ids)
    roots = [a for a in artifacts if a.get("relationship") == "ROOT"]
    if len(roots) != 1:
        issues.append("exactly one ROOT artifact is required, found %d" % len(roots))
    for artifact in artifacts:
        aid = artifact.get("artifact_id", "<missing>")
        if artifact.get("relationship") not in RELATIONSHIPS:
            issues.append("%s: relationship %r is not in the vocabulary"
                          % (aid, artifact.get("relationship")))
        if artifact.get("relationship") == "ROOT":
            if artifact.get("parent_artifact") is not None:
                issues.append("%s: ROOT must have no parent" % aid)
        else:
            parent = artifact.get("parent_artifact")
            if not parent:
                issues.append("%s: a non-ROOT artifact must record its parent "
                              "explicitly — relationships are never inferred "
                              "from commit history" % aid)
            elif parent not in known:
                issues.append("%s: parent %r is not in the graph" % (aid, parent))
        supersedes = artifact.get("supersedes")
        if supersedes is not None and supersedes not in known:
            issues.append("%s: supersedes %r is not in the graph" % (aid, supersedes))
        if artifact.get("qualification_state") not in CANDIDATE_STATES:
            issues.append("%s: qualification_state %r is not a candidate state"
                          % (aid, artifact.get("qualification_state")))
        for key, digest in (artifact.get("digests") or {}).items():
            if not SHA256_HEX.match(_normalize_digest(digest)):
                issues.append("%s: digest %s is malformed" % (aid, key))
        for field in ("digest", "source_commit", "build_identity"):
            if not artifact.get(field):
                issues.append("%s: %s is required" % (aid, field))
    for decision in graph.get("transferDecisions", []):
        for field in ("fromArtifact", "toArtifact", "evidenceScope", "result",
                      "reasoning", "decidedBy", "date"):
            if not decision.get(field):
                issues.append("transfer decision missing %s" % field)
        if decision.get("result") not in ("APPLIES", "PARTIALLY_APPLIES",
                                          "REQUIRES_REVIEW"):
            issues.append("transfer decision result %r is not permitted"
                          % decision.get("result"))
    return issues


def artifact_for_digest(graph: dict, digest: str):
    wanted = _normalize_digest(digest)
    for artifact in graph.get("artifacts", []):
        digests = {_normalize_digest(d) for d in (artifact.get("digests") or {}).values()}
        digests.add(_normalize_digest(artifact.get("digest", "")))
        if wanted in digests:
            return artifact
    return None


def _related(graph: dict, first: str, second: str) -> bool:
    """An explicit graph edge between two artifacts, either direction."""
    for artifact in graph.get("artifacts", []):
        aid = artifact.get("artifact_id")
        for other in (artifact.get("parent_artifact"), artifact.get("supersedes")):
            if {aid, other} == {first, second}:
                return True
    return False


# ------------------------------------------------------- applicability (§3)

def evaluate_applicability(evidence: dict, target_artifact_id: str,
                           graph: dict) -> dict:
    """Does this evidence apply to this artifact?

    The default for a different artifact is DOES_NOT_APPLY. Transfer happens
    only through a recorded decision with reasoning and a decider, riding on
    an explicit graph relationship — never because a change looks unrelated.
    """
    _refuse_fixture(evidence, "applicability")
    evidence_id = evidence.get("evidenceId") or evidence.get("intakeId") or "<unnamed>"
    digest = evidence.get("artifactDigest") or evidence.get("digest")
    if not digest:
        return {
            "evidenceId": evidence_id,
            "result": "ARTIFACT_MISMATCH",
            "reasoning": "the evidence names no artifact digest; unbound "
                         "evidence moves no artifact-specific gate",
        }
    source_artifact = artifact_for_digest(graph, digest)
    if source_artifact is None:
        return {
            "evidenceId": evidence_id,
            "result": "ARTIFACT_MISMATCH",
            "reasoning": "digest %s matches no artifact in the graph"
                         % _normalize_digest(digest)[:12],
        }
    source_id = source_artifact["artifact_id"]
    if source_id == target_artifact_id:
        return {
            "evidenceId": evidence_id,
            "result": "APPLIES",
            "reasoning": "the evidence binds to the target artifact itself",
            "evidenceArtifact": source_id,
        }
    scope = evidence.get("scope") or evidence.get("source") or ""
    for decision in graph.get("transferDecisions", []):
        if (decision.get("fromArtifact") == source_id
                and decision.get("toArtifact") == target_artifact_id
                and decision.get("evidenceScope") == scope):
            complete = all(decision.get(f) for f in ("reasoning", "decidedBy", "date"))
            if not complete:
                return {
                    "evidenceId": evidence_id,
                    "result": "DOES_NOT_APPLY",
                    "reasoning": "a transfer decision exists but is missing "
                                 "reasoning or a decider; an incomplete "
                                 "decision transfers nothing",
                    "evidenceArtifact": source_id,
                }
            if not _related(graph, source_id, target_artifact_id):
                return {
                    "evidenceId": evidence_id,
                    "result": "DOES_NOT_APPLY",
                    "reasoning": "a transfer decision exists but the graph "
                                 "records no relationship between %s and %s; "
                                 "no relationship, no transfer"
                                 % (source_id, target_artifact_id),
                    "evidenceArtifact": source_id,
                }
            return {
                "evidenceId": evidence_id,
                "result": decision["result"],
                "reasoning": "recorded transfer decision by %s (%s): %s"
                             % (decision["decidedBy"], decision["date"],
                                decision["reasoning"]),
                "evidenceArtifact": source_id,
            }
    return {
        "evidenceId": evidence_id,
        "result": "DOES_NOT_APPLY",
        "reasoning": "the evidence binds to %s, not %s, and no recorded "
                     "transfer decision covers scope %r; the default is no "
                     "transfer" % (source_id, target_artifact_id, scope),
        "evidenceArtifact": source_id,
    }


# ------------------------------------------------------- impact model (§4)

def classify_components(changed: list[str], mapping: dict) -> dict:
    """Map changed paths to impact areas through the committed mapping.

    Longest-prefix match; top-level ``*.md`` files not otherwise matched are
    repository reports (DOCUMENTATION, not product). Anything unmapped fails
    closed: it lands in ``unmapped`` and the planner refuses to call any
    domain NOT_REQUIRED while that list is non-empty.
    """
    components = mapping["components"]
    by_component: dict[str, dict] = {}
    unmapped: list[str] = []
    for path in sorted(set(changed)):
        name = path.replace("\\", "/").lstrip("./")
        best = None
        for entry in components:
            prefix = entry["prefix"]
            matched = name == prefix or name.startswith(prefix)
            if matched and (best is None or len(prefix) > len(best["prefix"])):
                best = entry
        if best is None and "/" not in name and name.endswith(".md"):
            best = {"prefix": "<root report>", "domains": ["DOCUMENTATION"],
                    "productAffecting": False,
                    "why": "top-level reports are records, not image content"}
        if best is None:
            unmapped.append(name)
            continue
        by_component[name] = {
            "matched": best["prefix"],
            "domains": sorted(best["domains"]),
            "productAffecting": bool(best["productAffecting"]),
        }
    domains = sorted({
        domain for info in by_component.values() for domain in info["domains"]
    })
    return {
        "byComponent": by_component,
        "domains": domains,
        "productAffecting": any(
            info["productAffecting"] for info in by_component.values()
        ),
        "unmapped": unmapped,
    }


def build_impact(parent_id: str, new_id: str, changed: list[str],
                 mapping: dict) -> dict:
    """The §4 impact record for qualification/phase10/impact/<artifact>.json."""
    classified = classify_components(changed, mapping)
    return {
        "schemaVersion": 1,
        "artifact": new_id,
        "parentArtifact": parent_id,
        "changedComponents": classified["byComponent"],
        "unmappedComponents": classified["unmapped"],
        "impactAreas": classified["domains"],
        "productAffecting": classified["productAffecting"],
        "note": "impact is computed against the parent through the committed "
                "component-domain mapping; unmapped components fail closed "
                "in the planner",
    }


# -------------------------------------------------- requalification planner

def plan_requalification(impact: dict) -> dict:
    """REQUIRED / RECOMMENDED / NOT_REQUIRED / REQUIRES_HUMAN_REVIEW per
    qualification domain. The planner plans work; only evidence produces
    PASS, and this vocabulary cannot express one."""
    impacted = set(impact.get("impactAreas", []))
    unmapped = list(impact.get("unmappedComponents", []))
    new_artifact = impact.get("artifact") != impact.get("parentArtifact")
    product = bool(impact.get("productAffecting"))
    plan: dict[str, dict] = {}
    for domain in PLANNER_DOMAINS:
        if domain == "HARDWARE":
            if new_artifact and product:
                plan[domain] = {
                    "status": "REQUIRES_HUMAN_REVIEW",
                    "reason": "a new artifact requires a real-machine "
                              "applicability decision; no repo component "
                              "maps to a physical machine",
                }
            else:
                plan[domain] = {"status": "NOT_REQUIRED",
                                "reason": "artifact unchanged"}
            continue
        if domain in ("SECURITY", "RELEASE") and new_artifact and product:
            plan[domain] = {
                "status": "REQUIRED",
                "reason": "artifact identity changed; %s evidence binds to "
                          "the exact artifact and never transfers by default"
                          % domain.lower(),
            }
            continue
        if domain in impacted:
            plan[domain] = {"status": "REQUIRED",
                            "reason": "a mapped component in this domain changed"}
        elif any(domain in ADJACENT_RECOMMENDED.get(hit, ()) for hit in impacted):
            plan[domain] = {
                "status": "RECOMMENDED",
                "reason": "adjacent to a changed domain (%s)" % ", ".join(
                    sorted(hit for hit in impacted
                           if domain in ADJACENT_RECOMMENDED.get(hit, ()))),
            }
        else:
            plan[domain] = {"status": "NOT_REQUIRED", "reason": "unchanged"}
    if unmapped:
        for domain, row in plan.items():
            if row["status"] in ("NOT_REQUIRED", "RECOMMENDED"):
                plan[domain] = {
                    "status": "REQUIRES_HUMAN_REVIEW",
                    "reason": "unmapped changed component(s) %s could affect "
                              "any domain; extend the mapping or decide by "
                              "hand" % ", ".join(unmapped),
                }
    return plan


def validate_plan(plan: dict) -> list[str]:
    """A plan that outputs PASS — or anything else outside the four planner
    statuses — is not a plan. Only evidence produces PASS."""
    issues = []
    for domain, row in plan.items():
        if domain not in PLANNER_DOMAINS:
            issues.append("%s is not a qualification domain" % domain)
        status = row.get("status") if isinstance(row, dict) else row
        if status not in PLAN_STATUSES:
            issues.append(
                "%s: %r is not a planner status — the planner plans work, "
                "it never grades it" % (domain, status)
            )
        if isinstance(row, dict) and not row.get("reason"):
            issues.append("%s: a plan row without a reason is a guess" % domain)
    return issues


# ------------------------------------------------ remediation boundary (§8)

def validate_remediation(remediation: dict, mapping: dict) -> list[str]:
    """Product-affecting change without new artifact identity: violation."""
    classified = classify_components(remediation.get("changedComponents", []), mapping)
    before = remediation.get("artifactBefore")
    after = remediation.get("artifactAfter")
    violations = []
    if classified["unmapped"]:
        violations.append(
            "unmapped changed component(s): %s — the boundary cannot be "
            "judged until the mapping covers them"
            % ", ".join(classified["unmapped"])
        )
    if classified["productAffecting"] and before == after:
        violations.append(
            "product-affecting components changed (%s) but the artifact "
            "identity did not; a remediation that changes the product "
            "requires a new artifact, a new digest, and its own "
            "qualification boundary"
            % ", ".join(sorted(
                name for name, info in classified["byComponent"].items()
                if info["productAffecting"]))
        )
    if not classified["productAffecting"] and before != after:
        violations.append(
            "no product-affecting component changed, yet a new artifact "
            "identity is claimed; a rebuild needs a cause"
        )
    return violations


# ------------------------------------------------- harness corrections (§9)

def validate_harness_correction(record: dict) -> list[str]:
    """A correction that does not carry the old verdict verbatim is history
    rewriting, and history is never rewritten."""
    issues = []
    if record.get("classification") not in HARNESS_CLASSIFICATIONS:
        issues.append("classification %r is not in the vocabulary"
                      % record.get("classification"))
    original = record.get("originalVerdict")
    if not isinstance(original, dict) or not original.get("verdict") \
            or not original.get("evidence"):
        issues.append("the original verdict (verdict + evidence reference) "
                      "must be preserved verbatim inside the correction")
    for field in ("correctedVerdict", "reason", "harnessChange"):
        if not record.get(field):
            issues.append("%s is required" % field)
    if record.get("classification") in ("PRIOR_FALSE_PASS_FOUND",
                                        "PRIOR_FALSE_FAIL_FOUND"):
        if record.get("correctedVerdict") == (record.get("originalVerdict") or {}).get("verdict"):
            issues.append("a FALSE_PASS/FALSE_FAIL classification with an "
                          "unchanged verdict contradicts itself")
    return issues


# ----------------------------------------------- candidate transitions (§10)

def candidate_transition(current: str, target: str, context: dict | None = None) -> str:
    """Return ``target`` if the transition is allowed; raise otherwise."""
    if current not in CANDIDATE_STATES:
        raise BoundaryViolation("unknown candidate state %r" % current)
    if target not in CANDIDATE_STATES:
        raise BoundaryViolation("unknown candidate state %r" % target)
    if target not in CANDIDATE_TRANSITIONS[current]:
        raise BoundaryViolation(
            "transition %s -> %s is not allowed; the allowed set from %s is "
            "{%s}" % (current, target, current,
                      ", ".join(sorted(CANDIDATE_TRANSITIONS[current])) or "nothing")
        )
    if target == "AUTHORIZED":
        context = context or {}
        decision = context.get("decision")
        ledger = context.get("ledger")
        if not isinstance(decision, dict) or not isinstance(ledger, dict):
            raise BoundaryViolation(
                "AUTHORIZED requires the decision record and the intake "
                "ledger in context; a transition without them is the "
                "repository authorizing itself"
            )
        if decision.get("final_decision") not in ("AUTHORIZED",
                                                  "AUTHORIZED_WITH_LIMITATIONS"):
            raise BoundaryViolation(
                "the decision record says %r, not AUTHORIZED"
                % decision.get("final_decision")
            )
        floor = _phase9().authorization_floor(decision, ledger)
        if floor:
            raise BoundaryViolation(
                "the Phase 9 authorization floor objects: %s" % "; ".join(floor)
            )
        if not decision.get("decision_authority"):
            raise BoundaryViolation("AUTHORIZED requires a named decision authority")
    return target


# -------------------------------------------------- finding lifecycle (§7)

def finding_transition(finding: dict, target: str,
                       context: dict | None = None) -> str:
    """Advance one finding; closure requires evidence against the finding's
    artifact — code having changed closes nothing."""
    current = finding.get("state")
    if current not in FINDING_STATES:
        raise BoundaryViolation("unknown finding state %r" % current)
    if target not in FINDING_STATES:
        raise BoundaryViolation("unknown finding state %r" % target)
    if target not in FINDING_TRANSITIONS[current]:
        raise BoundaryViolation(
            "finding transition %s -> %s is not allowed" % (current, target)
        )
    context = context or {}
    if target == "REQUALIFIED":
        evidence = context.get("requalificationEvidence") or {}
        if not evidence.get("reference") or not evidence.get("artifact"):
            raise BoundaryViolation(
                "REQUALIFIED requires requalification evidence (reference + "
                "artifact); a code change is not requalification"
            )
        if evidence["artifact"] != finding.get("artifact"):
            raise BoundaryViolation(
                "requalification evidence binds to %s but the finding is "
                "against %s; qualification belongs to the artifact that was "
                "actually tested" % (evidence["artifact"], finding.get("artifact"))
            )
    if target == "CLOSED" and current == "ACCEPTED_RISK":
        acceptance = context.get("acceptance") or {}
        missing = [f for f in ACCEPTANCE_FIELDS if not acceptance.get(f)]
        if missing:
            raise BoundaryViolation(
                "closing an accepted risk requires %s; missing: %s — there "
                "is no silent acceptance"
                % ("/".join(ACCEPTANCE_FIELDS), ", ".join(missing))
            )
    return target


# ------------------------------------------- candidate status derivation

def _active_candidate(graph: dict) -> dict:
    live = [a for a in graph.get("artifacts", [])
            if a.get("qualification_state") not in ("SUPERSEDED", "RETIRED")]
    if len(live) != 1:
        raise BoundaryViolation(
            "expected exactly one active candidate, found %d — parallel "
            "candidates need an explicit operator choice" % len(live)
        )
    return live[0]


def next_action(derived: dict) -> str:
    """Exactly one highest-priority next action, deterministically."""
    for finding in derived.get("openFindings", []):
        if finding.get("state") == "FIX_REQUIRED":
            return ("Remediate %s: a fix is required, and the fix produces a "
                    "new artifact with its own qualification boundary"
                    % finding.get("findingId"))
    gates = {row["gate"]: row for row in derived.get("requiredQualification", [])}
    unprocessed = [e for e in derived.get("applicableEvidence", [])
                   if e.get("result") == "APPLIES"]
    if unprocessed and derived.get("currentState") == "EVIDENCE_PENDING":
        return ("Advance the candidate to UNDER_REVIEW: accepted evidence "
                "(%s) awaits gate evaluation"
                % ", ".join(e["evidenceId"] for e in unprocessed))
    ladder = (
        ("Independent security review",
         "Commission the independent security review — the package has been "
         "ready since Phase 8 (qualification/phase8/security-review/PACKAGE.md) "
         "and conditions 1 and 2 stay true until its owner acts"),
        ("Production signing",
         "Establish the key authority and sign the exact artifact bytes "
         "(qualification/phase8/signing/SIGNING_READINESS.md)"),
        ("Second approval",
         "Obtain the second approval, independently naming the digest "
         "(qualification/phase8/signing/APPROVALS.md)"),
        ("Physical hardware qualification",
         "Run the hardware protocol on a real machine "
         "(qualification/phase8/hardware/PROTOCOL.md)"),
        ("Alpha tester validation",
         "Enroll Alpha testers under the controlled protocol "
         "(qualification/phase8/alpha/)"),
    )
    for gate, action in ladder:
        if gate in gates:
            return action
    return ("Present the completed decision matrix to the release decision "
            "authority for the Alpha release decision")


def derive_candidate_status(graph: dict, ledger: dict, decision: dict,
                            phase9_findings: dict, phase10_findings: dict,
                            previous: dict | None) -> dict:
    """The §11 record, reproducible from immutable inputs.

    Reads the Phase 9 ledger; never writes it. State history is carried
    forward append-only from ``previous``; everything else is recomputed.
    """
    intake = _phase9()
    candidate = _active_candidate(graph)
    candidate_id = candidate["artifact_id"]

    effective = intake.effective_statuses(ledger)
    applicable = []
    for entry in ledger.get("entries", []):
        if is_fixture(entry):
            raise BoundaryViolation(
                "ledger entry %s carries the fixture marker; fixtures never "
                "enter the intake ledger" % entry.get("intakeId")
            )
        if not entry.get("gateEligible"):
            continue
        if effective.get(entry["intakeId"]) != "ACCEPTED":
            continue
        evidence = {
            "evidenceId": entry["intakeId"],
            "artifactDigest": ledger["subjectArtifact"]["imageDigest"]
            if entry.get("binding") == "BOUND" else None,
            "scope": entry.get("source"),
        }
        applicable.append(evaluate_applicability(evidence, candidate_id, graph))

    open_findings = []
    for finding in phase10_findings.get("findings", []):
        if finding.get("state") != "CLOSED":
            open_findings.append({
                "findingId": finding.get("findingId"),
                "state": finding.get("state"),
                "artifact": finding.get("artifact"),
            })
    for finding in phase9_findings.get("findings", []):
        open_findings.append({
            "findingId": finding.get("findingId", finding.get("id")),
            "state": "TRIAGED",
            "artifact": finding.get("artifact"),
        })

    gate_fields = (
        ("Independent security review", "security_status"),
        ("Physical hardware qualification", "hardware_status"),
        ("Production signing", "signing_status"),
        ("Second approval", "approval_status"),
        ("Alpha tester validation", "alpha_validation_status"),
    )
    required = [
        {"gate": gate, "status": decision[field],
         "owner": "external — see PHASE9_ALPHA_RELEASE_DECISION_MATRIX.md"}
        for gate, field in gate_fields if decision.get(field) != "PASS"
    ]
    completed = [
        {"gate": "Artifact identity", "status": "PASS",
         "basis": "condition 6 is false: five digests recomputed from bytes "
                  "(qualification/phase7/baseline/freeze.log)"},
        {"gate": "Internal engineering certification",
         "status": decision.get("engineering_status", "NOT_RUN"),
         "basis": decision.get("engineering_status_basis", "")},
    ]

    history = list((previous or {}).get("stateHistory", []))
    if not history:
        raise BoundaryViolation(
            "no state history exists; seed the first record with an explicit "
            "operator entry rather than inventing one"
        )
    current_state = history[-1]["state"]
    if current_state not in CANDIDATE_STATES:
        raise BoundaryViolation("history tail %r is not a candidate state"
                                % current_state)

    derived = {
        "schemaVersion": 1,
        "candidate": candidate_id,
        "artifactDigest": candidate["digest"],
        "parentCandidate": candidate.get("parent_artifact"),
        "currentState": current_state,
        "stateHistory": history,
        "applicableEvidence": applicable,
        "openFindings": open_findings,
        "blockingConditions": decision["blocking_conditions"],
        "requiredQualification": required,
        "completedQualification": completed,
        "derivedFrom": {
            "artifactGraph": "qualification/phase10/artifacts/artifact-graph.json",
            "intakeLedger": "qualification/phase9/intake/LEDGER.json (read-only)",
            "decisionRecord":
                "qualification/phase9/decision/alpha-release-decision.json",
            "findingsRegistries": [
                "qualification/phase9/triage/findings.json",
                "qualification/phase10/findings/registry.json",
            ],
            "note": "recomputable from these immutable inputs plus the "
                    "append-only state history; tested by "
                    "tests/release/test_phase10_operations.py",
        },
    }
    derived["nextAction"] = next_action(derived)
    return derived


def sync_status(write: bool = True) -> tuple[dict, list[str]]:
    """Recompute candidate-status.json; refuse to drop history."""
    graph = load_json(GRAPH_PATH)
    issues = validate_graph(graph)
    if issues:
        return {}, ["graph: %s" % issue for issue in issues]
    ledger_bytes = PHASE9_LEDGER.read_bytes()
    previous = load_json(STATUS_PATH) if STATUS_PATH.is_file() else None
    derived = derive_candidate_status(
        graph, json.loads(ledger_bytes.decode("utf-8")),
        load_json(PHASE9_DECISION), load_json(PHASE9_FINDINGS),
        load_json(FINDINGS_PATH), previous,
    )
    problems: list[str] = []
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

def verify_fixtures() -> list[str]:
    """Every fixture is marked; no marker appears inside real intake."""
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
                    "indistinguishable from evidence" % (path.name, FIXTURE_MARKER)
                )
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
                "%s carries the fixture marker inside the real intake tree"
                % path.relative_to(ROOT).as_posix()
            )
    return issues


def verify_all() -> list[str]:
    issues = ["graph: %s" % i for i in validate_graph(load_json(GRAPH_PATH))]
    issues += ["fixtures: %s" % i for i in verify_fixtures()]
    derived, problems = sync_status(write=False)
    issues += ["status: %s" % p for p in problems]
    if not problems and STATUS_PATH.is_file():
        committed = load_json(STATUS_PATH)
        if committed != derived:
            issues.append(
                "status: committed candidate-status.json does not reproduce "
                "from its immutable inputs; run sync and review the diff"
            )
    return issues


# ---------------------------------------------------------------- CLI

def _cmd_verify(_args) -> int:
    issues = verify_all()
    if not issues:
        print("candidate operations verify clean")
        return 0
    for issue in issues:
        print(issue)
    return 2


def _cmd_sync(_args) -> int:
    derived, problems = sync_status(write=True)
    if problems:
        for problem in problems:
            print(problem)
        return 2
    print("candidate-status.json derived; state %s; next action: %s"
          % (derived["currentState"], derived["nextAction"]))
    return 0


def _cmd_plan(args) -> int:
    mapping = load_json(MAPPING_PATH)
    impact = build_impact(args.parent, args.new, args.changed, mapping)
    plan = plan_requalification(impact)
    issues = validate_plan(plan)
    for domain in PLANNER_DOMAINS:
        row = plan[domain]
        print("%-14s %-22s %s" % (domain, row["status"], row["reason"]))
    if impact["unmappedComponents"]:
        print("unmapped: %s" % ", ".join(impact["unmappedComponents"]))
    return 2 if issues else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ver = commands.add_parser("verify", help="graph, fixtures, reproducibility")
    ver.set_defaults(func=_cmd_verify)

    sync = commands.add_parser("sync", help="derive candidate-status.json")
    sync.set_defaults(func=_cmd_sync)

    plan = commands.add_parser("plan", help="requalification plan for a change set")
    plan.add_argument("--parent", required=True)
    plan.add_argument("--new", required=True)
    plan.add_argument("--changed", nargs="+", required=True)
    plan.set_defaults(func=_cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

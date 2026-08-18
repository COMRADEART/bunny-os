#!/usr/bin/env python3
"""Repository-native release blocker closure commands.

Every command here fails closed. A command that cannot find the evidence it
needs prints what is missing and exits 2; none of them can be made to print
success by being run in a different order or on a different host.

The gates deliberately read the *existing* records where they exist —
``operations/data/stable-qualification.json`` remains the single source of truth
for the nine protected approvals and the blocker codes — so the new evidence
model extends the old one rather than forking it.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release import accessibility as accessibility_module
from release import matrix as matrix_module
from release import updatepolicy as updatepolicy_module
from release.artifacts import ArtifactError, parse_manifest, verify_against_disk
from release.buildmode import BuildModeError, require_candidate_capable
from release.builders import (
    ACCEPTED_PAIRINGS,
    BuilderError,
    evaluate_builder_set,
)
from release.candidate import (
    CANDIDATE_PREREQUISITES,
    CandidateError,
    evaluate_candidate,
    render_dashboard,
)
from release.comparison import (
    reduce_dimension,
    COMPARISON_DIMENSIONS,
    ComparisonError,
    evaluate_comparison,
)
from release.cve import CveAnalysisError, evaluate_document as evaluate_cve_document
from release.hosted import HostedImportError, import_hosted_evidence
from release.evidence import (
    EVIDENCE_CATEGORIES,
    EvidenceError,
    evaluate_evidence,
)
from release.gates import (
    GateError,
    PILOT_REQUIREMENTS,
    SOURCE_GATE_REQUIREMENTS,
    StableInputs,
    evaluate_candidate_gate,
    evaluate_pilot_gate,
    evaluate_source_gate,
    evaluate_stable_gate,
)
from release.hardware import (
    HardwareCollectionError,
    HardwareEvidenceError,
    evaluate_collection,
    evaluate_intake,
)
from release.licensing import LicenceError, evaluate_licence_gate, parse_decision
from release.minimisation import MinimisationError, evaluate_minimisation
from release.normalisation import NormalisationError, normalise_archive
from release.paths import display_path
from release.validation import run_validators
from release.provenance import ProvenanceError, parse_provenance, verify_provenance
from release.reachability import ReachabilityError, parse_review as parse_reachability, summarise
from release.reproducibility import (
    ReproducibilityError,
    compare_builds,
    parse_builder,
    summarise_claims,
)
from release.reviews import (
    ReviewError,
    completed_review_identifiers,
    evaluate_requests,
    evaluate_review_records,
    evaluate_reviews,
)
from release.signing import (
    SigningError,
    evaluate_drill,
    evaluate_two_person_drill,
    parse_key_record,
    validate_namespaces,
)
from release.vulnerability import (
    VulnerabilityError,
    evaluate_position,
    render_markdown,
)

DATA = ROOT / "operations/data"
OUT = ROOT / "build/out/qualification"
HARDWARE_EVIDENCE = ROOT / "hardware/evidence"
SECURITY = ROOT / "security/reachability"
ACCESSIBILITY_EVIDENCE = ROOT / "evidence/accessibility"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional(path: Path, default: Any) -> Any:
    try:
        return load(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return "0" * 40


def now() -> _datetime.datetime:
    stamp = os.environ.get("BUNNY_EVALUATION_TIME")
    if stamp:
        return _datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return _datetime.datetime.now(_datetime.timezone.utc)


def candidate_commit() -> str:
    """The commit being qualified, which is not necessarily ``HEAD``.

    This distinction was missing and it made the evidence model unusable in
    practice. Every record was compared against ``HEAD``, so committing the record
    changed ``HEAD`` and invalidated the record it had just committed. The previous
    phase's twenty records were all generated at ``79bb99dd``, committed as
    ``80df25b``, and consequently every one of them reported:

        generated from commit 79bb99dd but the candidate is 80df25b;
        evidence does not transfer between commits

    Two categories that genuinely passed reported as stale for no reason but the
    act of recording them.

    The candidate commit is the commit that was *built and measured*, declared in
    the record itself. Evidence must match it, so wrong-commit evidence still
    blocks. What no longer happens is a record invalidating itself. Whether the
    candidate is still ``HEAD`` is reported separately, because qualifying an older
    commit is legitimate for a release candidate and must nevertheless be visible.
    """
    document = load_optional(DATA / "release-evidence.json", {})
    declared = document.get("candidateCommit")
    if isinstance(declared, str) and len(declared) == 40:
        return declared
    return source_commit()


def candidate_commit_state() -> dict[str, Any]:
    candidate = candidate_commit()
    head = source_commit()
    return {
        "candidateCommit": candidate,
        "headCommit": head,
        "candidateIsHead": candidate == head,
        "note": (
            "Evidence is bound to the candidate commit, not to HEAD. A candidate behind HEAD is "
            "legitimate — a release candidate qualifies one commit — but the tree has moved since "
            "the evidence was measured and a rebuild is needed before publication."
            if candidate != head
            else "The candidate commit is HEAD."
        ),
    }


def _completed_reviews() -> tuple[str, ...]:
    document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    return completed_review_identifiers(document)


def _external_reviewers() -> set[str]:
    document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    names: set[str] = set()
    for item in document.get("reviews", []):
        if isinstance(item, dict) and item.get("state") == "delivered" and item.get("reviewer"):
            names.add(str(item["reviewer"]))
    return names


# --- Workstream 1: vulnerability position ------------------------------------


def vulnerability_position() -> int:
    path = DATA / "vulnerability-disposition.json"
    try:
        document = load(path)
    except FileNotFoundError:
        print(f"BLOCKED: {path} does not exist; run the scan and record dispositions first")
        return 2
    try:
        position = evaluate_position(document, completed_independent_reviews=_completed_reviews())
    except VulnerabilityError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    atomic_json(OUT / "vulnerability-report.json", position.as_dict())
    write_text(OUT / "vulnerability-report.md", render_markdown(position))

    counts = position.counts()
    print(
        f"vulnerability position for {position.profile}: {counts['Critical']} Critical, "
        f"{counts['High']} High, {counts['Medium']} Medium over {len(position.findings)} findings"
    )
    print(f"wrote {OUT / 'vulnerability-report.json'} and {OUT / 'vulnerability-report.md'}")
    if position.blocked:
        print(f"BLOCKED: {len(position.blockingFindings)} finding(s) block a stable release:")
        for finding in position.blockingFindings[:20]:
            print(f"  - {finding.advisoryId} {finding.package} ({finding.effectiveSeverity}): {finding.disposition}")
        if len(position.blockingFindings) > 20:
            print(f"  ... and {len(position.blockingFindings) - 20} more")
        return 2
    print("no blocking vulnerability finding")
    return 0


def reachability_review() -> int:
    path = DATA / "vulnerability-disposition.json"
    document = load_optional(path, {"findings": [], "reachability": []})
    critical = [
        item.get("advisoryId")
        for item in document.get("findings", [])
        if item.get("scannerSeverity") == "Critical"
    ]
    try:
        reviews = [
            parse_reachability(
                item,
                completed_independent_reviews=_completed_reviews(),
                criticalAdvisories=critical,
            )
            for item in document.get("reachability", [])
        ]
    except ReachabilityError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    summary = summarise(reviews)
    atomic_json(OUT / "reachability-summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if summary["blocked"] else 0


# --- Workstream 4: package minimisation --------------------------------------


def package_minimisation_check() -> int:
    document = load_optional(DATA / "package-minimisation.json", None)
    if document is None:
        print("BLOCKED: operations/data/package-minimisation.json does not exist")
        return 2
    try:
        result = evaluate_minimisation(document)
    except MinimisationError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "package-minimisation.json", result)
    print(
        f"package minimisation: {result['removalCount']} removal(s), "
        f"{result['retainedCount']} explicit retention(s) across "
        f"{', '.join(result['reviewedProfiles'])}"
    )
    if result["result"] != "PASS":
        print("BLOCKED: incomplete removals: " + ", ".join(result["incompleteRemovals"]))
        return 2
    print("package minimisation complete")
    return 0


# --- Workstreams 5 and 6: licence decision and gate ---------------------------


def licence_gate() -> int:
    document = load_optional(DATA / "licence-decision.json", None)
    if document is None:
        print("BLOCKED: operations/data/licence-decision.json does not exist; the licence gate fails closed")
        return 2
    try:
        decision = parse_decision(document)
    except LicenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    scan_result = document.get("licenceScanResult")
    result = evaluate_licence_gate(decision, root=ROOT, licenceScanResult=scan_result)
    atomic_json(OUT / "licence-gate.json", result.as_dict())

    print(f"licence model: {decision.model}")
    for name in result.satisfied:
        print(f"  ok      {name}")
    for name in result.unmet:
        print(f"  BLOCKED {name}")
    if not result.passed:
        print("licence gate BLOCKED")
        return 2
    print("licence gate passed")
    return 0


# --- Workstream 7: independent builders ---------------------------------------


def independent_builder_prepare(builderId: str) -> int:
    """Emit the exact inputs a second builder must reproduce."""
    commit = source_commit()
    base = os.environ.get("BUNNY_BASE_IMAGE", "")
    if not base or "@sha256:" not in base:
        print(
            "BLOCKED: BUNNY_BASE_IMAGE must be set to a digest-pinned base image "
            "(quay.io/fedora/fedora-bootc:44@sha256:...) so both builders pin the same input"
        )
        return 2
    instructions = {
        "schemaVersion": 1,
        "builderId": builderId,
        "sourceCommit": commit,
        "baseImage": base,
        "profile": os.environ.get("BUNNY_PROFILE", "beta"),
        "sourceDateEpoch": os.environ.get("SOURCE_DATE_EPOCH", ""),
        "requiredIndependence": (
            "This builder must differ from its counterpart in at least one of: machineId, "
            "virtualisationInstance, cloudRunner, administrator, environmentId."
        ),
        "steps": [
            "git checkout the exact sourceCommit into an isolated workspace",
            "export BUNNY_BASE_IMAGE to the pinned digest above",
            "export SOURCE_DATE_EPOCH to the commit timestamp",
            "bash build/scripts/build-image.sh <profile>",
            "record scripts/reproducibility/collect-builder-record.sh output",
            "publish build/out/<profile>/bunny-os.oci.tar digest, the SBOM, and the package manifest",
        ],
    }
    atomic_json(OUT / f"builder-{builderId}-instructions.json", instructions)
    print(json.dumps(instructions, indent=2, sort_keys=True))
    return 0


def reproducibility_compare() -> int:
    document = load_optional(DATA / "builders.json", None)
    if document is None:
        print("BLOCKED: operations/data/builders.json does not exist")
        return 2
    comparisons = document.get("comparisons", [])
    if not comparisons:
        print("BLOCKED: no builder comparison has been recorded")
        return 2

    results = []
    for entry in comparisons:
        try:
            first = parse_builder(entry["first"])
            second = parse_builder(entry["second"])
            result = compare_builds(
                first,
                second,
                claim=entry["claim"],
                archiveDigests=tuple(entry["archiveDigests"]),
                fileDigests=(entry.get("fileDigests", [{}, {}])[0], entry.get("fileDigests", [{}, {}])[1]),
                sbomDigests=tuple(entry["sbomDigests"]),
                packageManifests=(entry.get("packageManifests", [[], []])[0], entry.get("packageManifests", [[], []])[1]),
            )
        except (ReproducibilityError, KeyError, TypeError) as exc:
            print(f"BLOCKED: {exc}")
            return 2
        results.append(result)

    summary = summarise_claims(results)
    payload = {
        "schemaVersion": 1,
        "comparisons": [result.as_dict() for result in results],
        **summary,
    }
    atomic_json(OUT / "reproducibility.json", payload)
    for result in results:
        state = "PASS" if result.satisfied else "FAIL"
        print(f"{result.claim}: {state}")
        for reason in result.reasons:
            print(f"    {reason}")
    print(json.dumps(summary["claims"], indent=2, sort_keys=True))
    if not summary["productionRequirementMet"]:
        print(
            "BLOCKED: independent-builder reproducibility is not established. Two builds on one "
            "host are same-host repeatability."
        )
        return 2
    print("independent-builder reproducibility established")
    return 0


# --- Workstreams 8 and 9: signing ---------------------------------------------


def development_signing_drill() -> int:
    try:
        validate_namespaces()
    except SigningError as exc:  # pragma: no cover - static configuration
        print(f"BLOCKED: {exc}")
        return 2

    document = load_optional(DATA / "signing-drill.json", None)
    if document is None:
        print("BLOCKED: operations/data/signing-drill.json does not exist; run the drill first")
        return 2
    try:
        result = evaluate_drill(document.get("checks", []))
    except SigningError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "development-signing-drill.json", result)
    for check in result["checks"]:
        print(f"  {check['outcome']:8} {check['check']}")
    if result["missingChecks"]:
        print("BLOCKED: missing checks: " + ", ".join(result["missingChecks"]))
        return 2
    if result["failingChecks"]:
        print("BLOCKED: failing checks: " + ", ".join(result["failingChecks"]))
        return 2
    print("development signing drill PASSED (development keys; not release signing evidence)")
    return 0


def signing_roles() -> int:
    document = load_optional(DATA / "signing-keys.json", {"schemaVersion": 1, "keys": []})
    try:
        validate_namespaces()
        keys = [parse_key_record(item) for item in document.get("keys", [])]
    except SigningError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    production = [key for key in keys if key.keyClass == "production"]
    payload = {
        "schemaVersion": 1,
        "keys": [key.as_dict() for key in keys],
        "productionKeyCount": len(production),
        "developmentKeyCount": len(keys) - len(production),
        "productionReady": bool(production),
        "note": "Development keys are refused by require_production_key and cannot sign a release.",
    }
    atomic_json(OUT / "signing-roles.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if production else 2


# --- Workstreams 11 to 15: matrices -------------------------------------------


def test_matrix(name: str) -> int:
    document = load_optional(DATA / "qualification-matrices.json", None)
    if document is None:
        print("BLOCKED: operations/data/qualification-matrices.json does not exist")
        return 2
    matrices = document.get("matrices", {})
    if name not in matrices:
        print(f"BLOCKED: no results recorded for the {name} matrix")
        return 2
    try:
        verdict = matrix_module.evaluate_matrix(name, matrices[name], root=ROOT)
    except matrix_module.MatrixError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / f"matrix-{name}.json", verdict.as_dict())
    print(f"{name} matrix: {len(verdict.results)} of {len(matrix_module.MATRICES[name])} scenarios recorded")
    for result in verdict.results:
        print(f"  {result.outcome:15} {result.scenario:42} via {result.method}")
    if verdict.missing:
        print("BLOCKED: unresolved scenarios: " + ", ".join(verdict.missing))
    if verdict.failing:
        print("BLOCKED: failing scenarios: " + ", ".join(verdict.failing))
    return 0 if verdict.complete else 2


def all_matrices() -> tuple[bool, dict[str, Any]]:
    """Every matrix must be present and complete. An absent matrix blocks."""
    document = load_optional(DATA / "qualification-matrices.json", None)
    if document is None:
        return False, {"error": "operations/data/qualification-matrices.json does not exist"}
    try:
        result = matrix_module.evaluate_document(document, root=ROOT)
    except matrix_module.MatrixError as exc:
        return False, {"error": str(exc)}
    absent = sorted(set(matrix_module.MATRICES) - set(document.get("matrices", {})))
    result["absentMatrices"] = absent
    if absent:
        result["result"] = "BLOCKED"
    return result["result"] == "PASS", result


# Workstreams 14 and 16 — hardware intake and independent reviews — are
# implemented below alongside the collector and the review-record intake that
# extend them, rather than in two places.


# --- Workstream 17: stable evidence report ------------------------------------


def stable_evidence_report() -> int:
    document = load_optional(DATA / "release-evidence.json", None)
    if document is None:
        print("BLOCKED: operations/data/release-evidence.json does not exist")
        return 2
    try:
        report = evaluate_evidence(
            document,
            root=ROOT,
            sourceCommit=candidate_commit(),
            now=now(),
            externalReviewers=_external_reviewers(),
        )
    except EvidenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    payload = report.as_dict()
    payload["commitBinding"] = candidate_commit_state()

    # The dashboard is generated from the same evaluation, so the two cannot
    # disagree. A report that says BLOCKED beside a dashboard that says PASS is
    # exactly the failure the evidence model exists to prevent.
    try:
        readiness = _candidate_readiness()
        payload["candidatePrerequisites"] = readiness.as_dict()
        write_text(OUT / "stable-evidence-dashboard.md", render_dashboard(readiness))
    except CandidateError as exc:  # pragma: no cover - defensive
        payload["candidatePrerequisites"] = {"error": str(exc)}

    atomic_json(OUT / "stable-evidence-report.json", payload)

    binding = payload["commitBinding"]
    print(f"candidate commit: {binding['candidateCommit'][:12]}, HEAD: {binding['headCommit'][:12]}")
    if not binding["candidateIsHead"]:
        print(f"  {binding['note']}")
    print(f"evidence records: {payload['recordCount']}, blocking: {payload['blockingRecordCount']}")
    for record in payload["blockingRecords"]:
        print(f"  BLOCKING {record['id']} ({record['category']})")
        for reason in record["blockingReasons"]:
            print(f"      {reason}")
    if payload["missingCategories"]:
        print("  MISSING CATEGORIES: " + ", ".join(payload["missingCategories"]))
    prerequisites = payload.get("candidatePrerequisites", {})
    if "rows" in prerequisites:
        print(
            f"candidate prerequisites: {len(prerequisites['satisfied'])} of "
            f"{prerequisites['prerequisiteCount']} satisfied"
        )
        for state, names in sorted(prerequisites["byState"].items()):
            print(f"  {state:24} {', '.join(names)}")
    print(f"wrote {OUT / 'stable-evidence-report.json'}")
    print(f"wrote {OUT / 'stable-evidence-dashboard.md'}")
    return 2 if payload["blocked"] else 0


# --- Workstream 10: candidate artifacts ---------------------------------------


def validate_release_manifest(path: Path | None = None) -> int:
    target = path or (ROOT / "build/out/qualification-candidate/CANDIDATE.json")
    if not target.is_file():
        print(f"BLOCKED: no candidate manifest at {target}")
        return 2
    try:
        manifest = parse_manifest(load(target), stableGatePassed=False)
    except ArtifactError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    verification = verify_against_disk(manifest, root=target.parent)
    payload = {**manifest.as_dict(), "verification": verification}
    atomic_json(OUT / "release-manifest.json", payload)
    print(f"candidate {manifest.candidateName} {manifest.version}: {len(manifest.artifacts)} artifacts")
    if manifest.missingArtifacts:
        print("  missing: " + ", ".join(manifest.missingArtifacts))
    if manifest.unsignedArtifacts:
        print("  unsigned: " + ", ".join(manifest.unsignedArtifacts))
    if verification["absentArtifacts"]:
        print("  absent on disk: " + ", ".join(verification["absentArtifacts"]))
    for mismatch in verification["digestMismatches"]:
        print(f"  digest mismatch: {mismatch}")
    ok = manifest.complete and not manifest.unsignedArtifacts and verification["result"] == "PASS"
    print("candidate manifest valid" if ok else "BLOCKED: candidate manifest incomplete or unverified")
    return 0 if ok else 2


# --- Workstream 18: gates ------------------------------------------------------


def _stable_inputs() -> StableInputs:
    qualification = load_optional(
        DATA / "stable-qualification.json", {"evidence": {}, "approvals": {}, "blockers": []}
    )

    evidence_document = load_optional(DATA / "release-evidence.json", {"schemaVersion": 1, "records": []})
    try:
        evidence_report = evaluate_evidence(
            evidence_document,
            root=ROOT,
            sourceCommit=candidate_commit(),
            now=now(),
            externalReviewers=_external_reviewers(),
        )
        evidence_detail = evidence_report.as_dict()
        evidence_complete = not evidence_report.blocked
    except EvidenceError as exc:
        evidence_detail = {"error": str(exc)}
        evidence_complete = False

    vulnerability_document = load_optional(DATA / "vulnerability-disposition.json", None)
    vulnerability_blocked = True
    vulnerability_detail: dict[str, Any] = {"error": "no vulnerability disposition recorded"}
    if vulnerability_document is not None:
        try:
            position = evaluate_position(
                vulnerability_document, completed_independent_reviews=_completed_reviews()
            )
            vulnerability_blocked = position.blocked
            vulnerability_detail = {
                "counts": position.counts(),
                "blockingCount": len(position.blockingFindings),
                "blockingAdvisories": [f.advisoryId for f in position.blockingFindings][:50],
            }
        except VulnerabilityError as exc:
            vulnerability_detail = {"error": str(exc)}

        # Both the position and the per-CVE analyses must be clear. The position
        # is a per-finding disposition; the analyses are the binary evidence
        # behind it. A scanner score cannot substitute for either, and a clear
        # position with no analysis behind it is the state this phase was written
        # to make impossible.
        blocking = [
            item
            for item in vulnerability_document.get("findings", [])
            if item.get("scannerSeverity") in {"Critical", "High"}
        ]
        analyses = [
            load(SECURITY / "findings" / f"{item['advisoryId']}.json")
            for item in blocking
            if (SECURITY / "findings" / f"{item['advisoryId']}.json").is_file()
        ]
        try:
            cve_result = evaluate_cve_document(
                {"schemaVersion": 1, "analyses": analyses},
                completed_independent_reviews=_completed_reviews(),
                criticalAdvisories=[
                    item["advisoryId"] for item in blocking if item["scannerSeverity"] == "Critical"
                ],
                independentReviewers=_external_reviewers(),
                expectedAdvisories=[item["advisoryId"] for item in blocking],
            )
            vulnerability_detail["perCveAnalysis"] = {
                "analysed": cve_result["analysed"],
                "byProofClass": cve_result["byProofClass"],
                "uncoveredAdvisories": cve_result["uncoveredAdvisories"],
                "blocked": cve_result["blocked"],
            }
            vulnerability_blocked = vulnerability_blocked or cve_result["blocked"]
        except CveAnalysisError as exc:
            vulnerability_detail["perCveAnalysis"] = {"error": str(exc)}
            vulnerability_blocked = True

    licence_document = load_optional(DATA / "licence-decision.json", None)
    licence_passed = False
    licence_detail: dict[str, Any] = {"error": "no licence decision recorded"}
    if licence_document is not None:
        try:
            decision = parse_decision(licence_document)
            licence_result = evaluate_licence_gate(
                decision, root=ROOT, licenceScanResult=licence_document.get("licenceScanResult")
            )
            licence_passed = licence_result.passed
            licence_detail = licence_result.as_dict()
        except LicenceError as exc:
            licence_detail = {"error": str(exc)}

    builders = load_optional(DATA / "builders.json", {"comparisons": []})
    independent = False
    for entry in builders.get("comparisons", []):
        if entry.get("claim") != "independent-builder":
            continue
        try:
            result = compare_builds(
                parse_builder(entry["first"]),
                parse_builder(entry["second"]),
                claim="independent-builder",
                archiveDigests=tuple(entry["archiveDigests"]),
                fileDigests=(entry.get("fileDigests", [{}, {}])[0], entry.get("fileDigests", [{}, {}])[1]),
                sbomDigests=tuple(entry["sbomDigests"]),
                packageManifests=(
                    entry.get("packageManifests", [[], []])[0],
                    entry.get("packageManifests", [[], []])[1],
                ),
            )
            independent = independent or result.satisfied
        except (ReproducibilityError, KeyError, TypeError):
            independent = False

    signing_document = load_optional(DATA / "signing-keys.json", {"keys": []})
    production_keys = False
    try:
        for item in signing_document.get("keys", []):
            record = parse_key_record(item)
            if record.keyClass == "production" and record.state in {"active", "rotating"}:
                production_keys = True
    except SigningError:
        production_keys = False

    minimisation_document = load_optional(DATA / "package-minimisation.json", None)
    minimisation_complete = False
    if minimisation_document is not None:
        try:
            minimisation_complete = evaluate_minimisation(minimisation_document)["result"] == "PASS"
        except MinimisationError:
            minimisation_complete = False

    hardware_document = load_optional(DATA / "hardware-evidence.json", {"schemaVersion": 1, "reports": []})
    try:
        hardware_qualified = evaluate_intake(hardware_document, evidenceRoot=HARDWARE_EVIDENCE)["requirementMet"]
    except HardwareEvidenceError:
        hardware_qualified = False

    reviews_document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    try:
        reviews_complete = evaluate_reviews(reviews_document, root=ROOT)["allComplete"]
    except ReviewError:
        reviews_complete = False

    matrices_complete, _ = all_matrices()

    candidate = ROOT / "build/out/qualification-candidate/CANDIDATE.json"
    candidate_complete = False
    if candidate.is_file():
        try:
            manifest = parse_manifest(load(candidate))
            verification = verify_against_disk(manifest, root=candidate.parent)
            candidate_complete = (
                manifest.complete
                and not manifest.unsignedArtifacts
                and verification["result"] == "PASS"
            )
        except ArtifactError:
            candidate_complete = False

    return StableInputs(
        evidenceComplete=evidence_complete,
        evidenceDetail=evidence_detail,
        approvals=qualification.get("approvals", {}),
        blockers=tuple(qualification.get("blockers", [])),
        vulnerabilityBlocked=vulnerability_blocked,
        vulnerabilityDetail=vulnerability_detail,
        licenceGatePassed=licence_passed,
        licenceDetail=licence_detail,
        reproducibilityIndependent=independent,
        signingProductionReady=production_keys,
        candidateComplete=candidate_complete,
        minimisationComplete=minimisation_complete,
        hardwareQualified=hardware_qualified,
        reviewsComplete=reviews_complete,
        matricesComplete=matrices_complete,
    )


def validate_repository() -> int:
    """Run every repository validator and report each one separately.

    The same evaluation the source gate performs, exposed on its own so a
    failing validator can be identified without running the whole gate — which
    also runs three test suites.
    """
    report = run_validators(ROOT)
    atomic_json(OUT / "repository-validation.json", report.as_dict())
    print("repository validation:", "PASS" if report.passed else "FAIL")
    print(report.render())
    print(f"\nwrote {display_path(OUT / 'repository-validation.json', ROOT)}")
    if report.passed:
        return 0
    print(
        "\nBLOCKED: " + ", ".join(outcome.name for outcome in report.failing)
        + " failed. A SKIP is not a PASS: a validator whose host tool is absent "
        "reports SKIP with the reason."
    )
    return 2


def _build_mode_blockers(gateName: str) -> list[str]:
    """Refuse any built artifact whose build mode could not have qualified it.

    An archive-only build (BUNNY_ARCHIVE_ONLY=1) produces an OCI archive and no
    disk image. Nothing was installed, nothing booted, no recovery media was
    written, no hardware was exercised. Such an artifact is evidence for the
    reproducibility comparison and for nothing else, and the gates say so rather
    than leaving it to be inferred from which files are absent.
    """
    reasons: list[str] = []
    for path in sorted((ROOT / "build/out").glob("*/provenance.json")):
        document = load_optional(path, None)
        if not isinstance(document, dict):
            continue
        try:
            require_candidate_capable(document, gate=gateName)
        except BuildModeError as exc:
            reasons.append(f"{display_path(path, ROOT)}: {exc}")
    return reasons


def gate(kind: str) -> int:
    if kind == "source":
        return source_gate()

    # Build-mode refusals are *additional* to the gate's own evaluation, never a
    # substitute for it. Returning early here would hide the prerequisite count,
    # which is the number this gate exists to report.
    buildModeBlockers: list[str] = []
    if kind in {"qualification-candidate", "stable-release"}:
        buildModeBlockers = _build_mode_blockers(kind)
        if buildModeBlockers:
            atomic_json(
                OUT / f"gate-{kind}-build-mode.json",
                {"gate": kind, "result": "BLOCKED", "reasons": buildModeBlockers},
            )

    def _with_build_mode(status: int) -> int:
        if not buildModeBlockers:
            return status
        print(f"\nBLOCKED: {kind} also refuses the built artifacts present:")
        for reason in buildModeBlockers:
            print(f"  {reason}")
        return 2

    if kind == "qualification-candidate":
        try:
            readiness = _candidate_readiness()
        except CandidateError as exc:
            print(f"BLOCKED: {exc}")
            return 2
        detail = readiness.as_dict()
        result = evaluate_candidate_gate(
            prerequisitesReady=readiness.ready,
            unsatisfied=tuple(detail["unsatisfied"]),
            detail=detail,
        )
        atomic_json(OUT / "gate-qualification-candidate.json", result.as_dict())
        write_text(OUT / "stable-evidence-dashboard.md", render_dashboard(readiness))
        print(f"qualification candidate gate: {result.recommendation}")
        for row in detail["rows"]:
            marker = "ok     " if row["satisfied"] else "BLOCKED"
            print(f"  {marker} {row['state']:24} {row['description']}")
        if not result.passed:
            print(
                "\nNo artifact may be labelled release-qualified. Building a candidate for "
                "examination remains permitted; calling one qualified does not."
            )
        return _with_build_mode(0 if result.passed else 2)

    stable = evaluate_stable_gate(_stable_inputs())
    if kind == "stable-release":
        atomic_json(OUT / "gate-stable-release.json", stable.as_dict())
        print(f"stable release gate: {stable.recommendation}")
        for name in stable.satisfied:
            print(f"  ok      {name}")
        for name in stable.unmet:
            print(f"  BLOCKED {name}")
        if not stable.passed:
            print(
                "\nStable publication is prohibited. GO requires every requirement above to pass, "
                "every approval recorded, and no blocker code open."
            )
        return _with_build_mode(0 if stable.passed else 2)

    requirements = load_optional(DATA / "pilot-requirements.json", {}).get(kind, {}).get("requirements", {})
    try:
        result = evaluate_pilot_gate(kind, stable=stable, requirements=requirements)
    except GateError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / f"gate-{kind}.json", result.as_dict())
    print(f"{kind} gate: {result.recommendation}")
    for name in result.satisfied:
        print(f"  ok      {name}")
    for name in result.unmet:
        print(f"  BLOCKED {name}")
    if not result.passed:
        print(
            f"\nDo not begin a {kind.replace('-pilot', '')} pilot, manufacture devices, deploy "
            "fleets, or launch a hosted service while any requirement above is unmet."
        )
    return 0 if result.passed else 2


def pilot_closure_assertion() -> int:
    """CI assertion: no gate may report GO without protected evidence present."""
    protected = bool(os.environ.get("BUNNY_PROTECTED_EVIDENCE"))
    stable = evaluate_stable_gate(_stable_inputs())
    results = [stable]

    try:
        readiness = _candidate_readiness()
        detail = readiness.as_dict()
        results.append(
            evaluate_candidate_gate(
                prerequisitesReady=readiness.ready,
                unsatisfied=tuple(detail["unsatisfied"]),
                detail=detail,
            )
        )
    except CandidateError as exc:  # pragma: no cover - defensive
        print(f"CI FAILURE: the candidate prerequisites are malformed: {exc}")
        return 2

    for kind in PILOT_REQUIREMENTS:
        requirements = load_optional(DATA / "pilot-requirements.json", {}).get(kind, {}).get("requirements", {})
        results.append(evaluate_pilot_gate(kind, stable=stable, requirements=requirements))

    unexpected = [result.gate for result in results if result.passed and not protected]
    if unexpected:
        print(
            "CI FAILURE: these gates report GO without protected evidence in this environment: "
            + ", ".join(unexpected)
        )
        return 2

    # A pilot gate must never pass while the stable gate blocks, whatever the
    # pilot's own requirements say. Asserted rather than relied on, because the
    # pilot gates read their requirements from a data file and a change could
    # populate it.
    for result in results:
        if result.gate.endswith("-pilot") and result.passed and not stable.passed:
            print(
                f"CI FAILURE: {result.gate} reports GO while the stable gate reports "
                f"{stable.recommendation}; no pilot may bypass a stable release"
            )
            return 2

    print(
        "pilot-gate closure assertion passed: "
        + ", ".join(f"{result.gate}={result.recommendation}" for result in results)
    )
    return 0


# --- Preflight baseline --------------------------------------------------------


def release_blocker_baseline() -> int:
    path = ROOT / "docs/RELEASE_BLOCKER_BASELINE.md"
    if not path.is_file():
        print("BLOCKED: docs/RELEASE_BLOCKER_BASELINE.md does not exist")
        return 2
    required = (
        "source commit",
        "image base and digest",
        "vulnerability counts",
        "vulnerable package names",
        "licence state",
        "signing-key state",
        "reproducibility state",
        "hardware evidence state",
        "recovery evidence state",
        "accessibility evidence state",
        "security-review state",
        "stable-gate result",
        "oem pilot-gate result",
        "enterprise pilot-gate result",
        "sync pilot-gate result",
        "blockers that can be solved in code",
        "blockers requiring an owner decision",
        "blockers requiring hardware",
        "blockers requiring an independent third party",
    )
    text = path.read_text(encoding="utf-8").casefold()
    missing = [name for name in required if name not in text]
    if missing:
        print("BLOCKED: baseline missing required sections: " + ", ".join(missing))
        return 2
    print(f"release blocker baseline contains all {len(required)} mandatory sections")
    return 0


# --- Qualification evidence closure: baseline ---------------------------------


def qualification_evidence_baseline() -> int:
    path = ROOT / "docs/QUALIFICATION_EVIDENCE_BASELINE.md"
    if not path.is_file():
        print("BLOCKED: docs/QUALIFICATION_EVIDENCE_BASELINE.md does not exist")
        return 2
    required = (
        "automatable in repository",
        "requires ci infrastructure",
        "requires second independent machine",
        "requires physical hardware",
        "requires independent reviewer",
        "requires second authorised signer",
        "requires owner decision",
        "requires operated release evidence",
    )
    text = path.read_text(encoding="utf-8").casefold()
    missing = [name for name in required if name not in text]
    if missing:
        print("BLOCKED: baseline is missing required classifications: " + ", ".join(missing))
        return 2
    print(f"qualification evidence baseline classifies all {len(required)} categories")
    return 0


# --- Workstream 1: independent-builder CI --------------------------------------


def independent_builder_ci_manifest() -> int:
    """Describe the hosted workflow, and refuse to imply it has run."""
    workflow = ROOT / ".github/workflows/independent-builder.yml"
    if not workflow.is_file():
        print(f"BLOCKED: {display_path(workflow, ROOT)} does not exist")
        return 2
    text = workflow.read_text(encoding="utf-8")

    required_recordings = {
        "GITHUB_RUN_ID": "the GitHub run id",
        "RUNNER_ARCH": "the runner architecture",
        "ImageOS": "the runner image",
        "uname -r": "the kernel",
        "podman --version": "the container runtime",
        "collect_builder_record.py builder-record": "the builder record",
        "collect_builder_record.py provenance": "the provenance and artifact manifest",
        "sbom.spdx.json": "the SBOM",
        "package-inventory.txt": "the package inventory",
        "normalise-artifact": "raw and normalised digests",
        "upload-artifact": "comparison artifact upload",
        "BUNNY_CACHES_DISABLED": "mutable caches disabled",
    }
    missing = sorted(
        description for token, description in required_recordings.items() if token not in text
    )
    for secret in ("BUNNY_OS_RELEASE_KEY", "BUNNY_RECOVERY_KEY"):
        if secret not in text:
            missing.append(f"an explicit assertion that {secret} is unreachable")

    builders = load_optional(DATA / "builders.json", {})
    hosted = [
        record
        for record in builders.get("builderRecords", [])
        if isinstance(record, dict) and record.get("builderType") in {"hosted-ci", "self-hosted-ci"}
    ]

    payload = {
        "schemaVersion": 1,
        "workflow": ".github/workflows/independent-builder.yml",
        "workflowPresent": True,
        "recordedFields": sorted(set(required_recordings.values()) - set(missing)),
        "missingFields": missing,
        "executed": bool(hosted),
        "hostedBuilderRecordCount": len(hosted),
        "acceptedPairings": [text for _, _, text in ACCEPTED_PAIRINGS],
        "note": (
            "A prepared workflow is not an executed workflow. `executed` is derived from whether a "
            "hosted-ci builder record exists in operations/data/builders.json, not from the "
            "workflow file being present."
        ),
    }
    atomic_json(OUT / "independent-builder-ci.json", payload)

    print("independent-builder workflow: present")
    for name in payload["recordedFields"]:
        print(f"  ok      records {name}")
    for name in missing:
        print(f"  MISSING {name}")
    print(f"hosted builder records committed: {len(hosted)}")
    if missing:
        print("BLOCKED: the workflow does not record everything an independent builder must record")
        return 2
    if not hosted:
        print(
            "BLOCKED: the workflow is prepared and has not been executed. No hosted-ci builder "
            "record exists, so independent-builder reproducibility remains unestablished."
        )
        return 2
    print("a hosted builder record is recorded")
    return 0


def collect_builder_record(builderId: str, builderType: str | None) -> int:
    """Run the schema-2 collector on this host."""
    command = [
        os.sys.executable,
        str(ROOT / "scripts/reproducibility/collect_builder_record.py"),
        "builder-record",
        "--builder-id",
        builderId,
    ]
    if builderType:
        command += ["--builder-type", builderType]
    output = OUT / f"builder-record-{builderId}.json"
    command += ["--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    print(result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        return 2
    record = load(output)
    try:
        from release.builders import parse_builder_record

        parsed = parse_builder_record(record)
    except BuilderError as exc:
        print(f"BLOCKED: the collected record does not validate: {exc}")
        return 2
    print(f"builder {parsed.builderId}: {parsed.builderType}, boundary {parsed.administratorBoundary[:12]}")
    print(f"wrote {display_path(output, ROOT)}")
    return 0


# --- Workstreams 2 and 3: builder independence --------------------------------


def _tool_classifications() -> dict[str, str]:
    """Per-tool classifications from the builder lock, for independence decisions.

    The lock is read raw rather than parsed: an unreadable lock returns no
    classifications, which leaves every tool ``unknown`` — the strict, blocking
    default — rather than turning a broken lock into a passing verdict.
    """
    try:
        lock = json.loads(
            (ROOT / "build" / "inputs" / "builder-image-lock.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    classifications = {
        str(tool.get("name")): str(tool.get("classification", "unknown"))
        for tool in (lock.get("tools") or [])
        if isinstance(tool, dict)
    }
    for name in lock.get("absentTools") or {}:
        classifications.setdefault(str(name), "unavailable-but-unused")
    return classifications


def verify_builder_independence() -> int:
    document = load_optional(DATA / "builders.json", None)
    if document is None:
        print("BLOCKED: operations/data/builders.json does not exist")
        return 2
    try:
        result = evaluate_builder_set(document, toolClassifications=_tool_classifications())
    except BuilderError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "builder-independence.json", result)

    print(f"builder records: {result['builderCount']} ({', '.join(result['builderTypes']) or 'none'})")
    for reason in result["rejected"]:
        print(f"  REJECTED {reason}")
    for pair in result["pairs"]:
        state = "PASS" if pair["independent"] else "BLOCKED"
        print(f"  {state:8} {pair['first']} + {pair['second']}" + (f" — {pair['pairing']}" if pair["pairing"] else ""))
        for reason in pair["reasons"]:
            print(f"      {reason}")
    if not result["pairs"]:
        print("  no independence pair has been declared")
        print("\nAccepted pairings:")
        for _, _, description in ACCEPTED_PAIRINGS:
            print(f"  - {description}")
    if not result["requirementMet"]:
        print(
            "BLOCKED: no verified independent builder pair. A second workspace, container, or "
            "consecutive run on one host is separation, not independence."
        )
        return 2
    print("builder independence verified from real environment evidence")
    return 0


def import_hosted_builder_evidence(
    artifactDir: Path,
    candidateCommit: str,
    expectedBaseDigest: str | None,
    expectedRunId: str | None,
    localArtifactDir: Path | None,
) -> int:
    """Import a downloaded hosted-builder bundle, and the local builder's pair.

    Imported through this command rather than by editing ``builders.json``: every
    field the hosted record claims about itself is cross-checked against another
    file in the same bundle, and a record edited in one place fails. Hand-editing
    the JSON skips all of it.
    """
    document = load_optional(DATA / "builders.json", {"builderRecords": [], "comparisons": []})
    existing = list(document.get("builderRecords", []))

    # Reuse means a *different* builder citing a run another builder already
    # used. Re-importing the same bundle over its own record is idempotent, and
    # treating that as reuse would make the command runnable exactly once.
    incoming = load_optional(Path(artifactDir) / "builder-record.json", {})
    incomingId = incoming.get("builderId") if isinstance(incoming, dict) else None
    known = {
        str(record.get("workflowRunId"))
        for record in existing
        if record.get("workflowRunId") and record.get("builderId") != incomingId
    }

    try:
        hosted = import_hosted_evidence(
            artifactDir,
            candidateCommit=candidateCommit,
            expectedBaseDigest=expectedBaseDigest,
            knownRunIds=known,
            expectedRunId=expectedRunId,
        )
    except HostedImportError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    payload: dict[str, Any] = {"hosted": hosted.as_dict()}
    print(f"hosted builder {hosted.builder.builderId} ({hosted.builder.builderType})")
    print(f"  workflow run   {hosted.builder.workflowRunId}")
    print(f"  runner         {hosted.provenance.runnerImage} {hosted.provenance.runnerArchitecture}")
    print(f"  source commit  {hosted.builder.sourceCommit[:12]}")
    print(f"  base digest    {hosted.builder.baseImageDigest[-19:]}")
    print(f"  raw archive    {hosted.rawArchiveDigest[:16]}")
    print(f"  normalised     {hosted.normalisedArchiveDigest[:16]}")
    print(f"  packages       {hosted.packageCount}")
    print(f"  boundary       {hosted.builder.administratorBoundary[:12]}")

    local = None
    if localArtifactDir is not None:
        try:
            local = import_hosted_evidence(
                localArtifactDir,
                candidateCommit=candidateCommit,
                expectedBaseDigest=expectedBaseDigest,
            )
        except HostedImportError as exc:
            print(f"BLOCKED: the local builder bundle is unusable: {exc}")
            return 2
        # The local builder is not hosted CI and legitimately has neither a
        # workflow run nor a github-hosted environment; those reasons are its
        # correct description, not a defect.
        local.reasons = [
            reason for reason in local.reasons
            if "workflowRunId" not in reason
            and "hosted-ci record" not in reason
            and "github-hosted" not in reason
            and "the runner reported" not in reason
        ]
        payload["local"] = local.as_dict()
        print(f"\nlocal builder {local.builder.builderId} ({local.builder.builderType})")
        print(f"  source commit  {local.builder.sourceCommit[:12]}")
        print(f"  base digest    {local.builder.baseImageDigest[-19:]}")
        print(f"  raw archive    {local.rawArchiveDigest[:16]}")
        print(f"  normalised     {local.normalisedArchiveDigest[:16]}")
        print(f"  packages       {local.packageCount}")
        print(f"  boundary       {local.builder.administratorBoundary[:12]}")

    rejected = list(hosted.reasons) + list(local.reasons if local else [])
    atomic_json(OUT / "hosted-builder-import.json", payload)
    if rejected:
        print("\nBLOCKED: the evidence was not imported:")
        for reason in rejected:
            print(f"  - {reason}")
        print(f"\nwrote {display_path(OUT / 'hosted-builder-import.json', ROOT)}")
        return 2

    records = [
        record for record in existing
        if record.get("builderId") not in {
            hosted.builder.builderId, local.builder.builderId if local else None
        }
    ]
    records.append(hosted.builder.as_dict())
    if local:
        records.append(local.builder.as_dict())
    document["builderRecords"] = records

    # Importing two records means declaring which pair is claimed to be
    # independent. Declaring the pair is not asserting that it *is* independent:
    # evaluate_independence decides that, and refuses for its own reasons.
    if local:
        pairs = [
            pair for pair in document.get("independencePairs", [])
            if isinstance(pair, dict)
            and {pair.get("first"), pair.get("second")}
            != {local.builder.builderId, hosted.builder.builderId}
        ]
        pairs.append({
            "first": local.builder.builderId,
            "second": hosted.builder.builderId,
            "claim": "independent-builder",
            "declaredBy": "scripts/release.py import-hosted-builder-evidence",
            "candidateCommit": candidateCommit,
        })
        document["independencePairs"] = pairs
    else:
        document.setdefault("independencePairs", [])

    document["builderRecordNote"] = (
        f"Imported by scripts/release.py import-hosted-builder-evidence against candidate "
        f"{candidateCommit}. The hosted record was cross-checked against the runner's own "
        "environment report, the CI provenance and the artifact manifest in the same bundle; "
        "it is not signed, and the import record says so."
    )
    atomic_json(DATA / "builders.json", document)
    print(f"\nimported {len(records)} builder record(s) into {display_path(DATA / 'builders.json', ROOT)}")
    print("A builder record is not a reproducibility result. Run verify-builder-independence")
    print("and compare-independent-builds; independence is decided over a pair.")
    return 0


def assemble_build_comparison(
    first: Path,
    second: Path,
    firstLabel: str,
    secondLabel: str,
    rawVarianceExplanation: str | None,
    sourceCommit: str,
    baseImageDigest: str,
) -> int:
    """Build the seventeen-dimension comparison document from two collections.

    Both sides are collected by the same script from each builder's own archive,
    so a difference in the report is a difference in the images rather than a
    difference in how they were measured.
    """
    try:
        left = load(first)
        right = load(second)
    except FileNotFoundError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    dimensions: dict[str, Any] = {}
    forms: dict[str, str] = {}
    for name, _, _ in COMPARISON_DIMENSIONS:
        pair, form, detail = reduce_dimension(
            left.get("dimensions", {}).get(name),
            right.get("dimensions", {}).get(name),
        )
        pair["detail"] = detail
        dimensions[name] = pair
        forms[name] = form

    document = {
        "schemaVersion": 1,
        # The comparison names the commit and the base it compared. Two builders
        # on different sources or different bases are not comparable, and a
        # record that does not say which it used cannot be checked later.
        "sourceCommit": sourceCommit,
        "baseImageDigest": baseImageDigest,
        "builders": [firstLabel, secondLabel],
        "firstBuilder": firstLabel,
        "secondBuilder": secondLabel,
        "firstArchiveSha256": left.get("archiveSha256"),
        "secondArchiveSha256": right.get("archiveSha256"),
        "collectedBy": "scripts/reproducibility/collect_comparison_dimensions.py",
        "collectionNote": (
            "Both sides were read out of each builder's own OCI archive by the same collector, "
            "with no root, no podman and no mount, so the comparison measures the images and not "
            "the measuring."
        ),
        "storageForms": forms,
        "storageNote": (
            "A dimension larger than 256 KiB is stored as a SHA-256 over its whole collected "
            "value plus every differing member name, capped at 200 with the true count recorded. "
            "Equality is preserved exactly — two dimensions compare equal here if and only if "
            "they were equal in full — and what is dropped is the bulk of the matching members. "
            "The full collections are 71 MB per builder and are not committed."
        ),
        "volatilePathsExcluded": sorted(
            set(left.get("volatilePathsExcluded", [])) | set(right.get("volatilePathsExcluded", []))
        ),
        "dimensions": dimensions,
    }
    if rawVarianceExplanation:
        document["rawVarianceExplanation"] = rawVarianceExplanation

    atomic_json(DATA / "build-comparison.json", document)
    collected = sum(
        1 for value in dimensions.values()
        if value["first"] is not None and value["second"] is not None
    )
    print(f"assembled {len(dimensions)} dimensions, {collected} collected from both builders")
    absent = sorted(
        name for name, value in dimensions.items()
        if value["first"] is None or value["second"] is None
    )
    if absent:
        print(f"NOT_COLLECTED from one or both: {', '.join(absent)}")
    print(f"wrote {display_path(DATA / 'build-comparison.json', ROOT)}")
    return 0


# --- Workstream 4: artifact normalisation -------------------------------------


def normalise_artifact(source: Path, destination: Path, output: Path | None) -> int:
    try:
        result = normalise_archive(source, destination)
    except NormalisationError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    payload = result.as_dict()
    atomic_json(output or (OUT / "normalisation.json"), payload)
    print(f"raw digest        {result.rawDigest}")
    print(f"normalised digest {result.normalisedDigest}")
    print(f"members           {result.memberCount}")
    print(f"applied           {', '.join(result.appliedProperties)}")
    print("both digests are recorded: a normalised match with differing raw digests is a packing")
    print("difference that must still be explained.")
    return 0


# --- Workstream 5: seventeen-dimension comparison -----------------------------


def compare_independent_builds() -> int:
    document = load_optional(DATA / "build-comparison.json", None)
    if document is None:
        print("BLOCKED: operations/data/build-comparison.json does not exist")
        print(
            f"a comparison must record all {len(COMPARISON_DIMENSIONS)} dimensions from both "
            "builders; an unmeasured dimension cannot support a reproducibility claim"
        )
        return 2

    builders = load_optional(DATA / "builders.json", {})
    independent = False
    independence_reasons: tuple[str, ...] = ("no independence pair has been verified",)
    try:
        verdict = evaluate_builder_set(builders, toolClassifications=_tool_classifications())
        passing = [pair for pair in verdict["pairs"] if pair["independent"]]
        independent = bool(passing)
        if not independent:
            reasons = [reason for pair in verdict["pairs"] for reason in pair["reasons"]]
            independence_reasons = tuple(reasons) or independence_reasons
        else:
            independence_reasons = ()
    except BuilderError as exc:
        independence_reasons = (str(exc),)

    try:
        report = evaluate_comparison(
            document, independent=independent, independenceReasons=independence_reasons
        )
    except ComparisonError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    payload = report.as_dict()
    atomic_json(OUT / "reproducibility-comparison.json", payload)

    print(f"outcome: {report.outcome}")
    for state, names in sorted(payload["dimensionsByState"].items()):
        if names:
            print(f"  {state:14} {len(names)}: {', '.join(names)}")
    for reason in report.reasons:
        print(f"  {reason}")
    print(f"wrote {display_path(OUT / 'reproducibility-comparison.json', ROOT)}")
    if not report.satisfiesProductionGate:
        print(
            "BLOCKED: only REPRODUCIBLE between independent builders satisfies the production "
            "evidence gate."
        )
        return 2
    print("independent reproducibility established across every dimension")
    return 0


# --- Workstream 6: CI artifact verification -----------------------------------


def verify_ci_artifacts(
    provenancePath: Path,
    artifactRoot: Path,
    expectedCommit: str,
    expectedBaseDigest: str,
    verificationEnvironment: str,
    output: Path | None,
) -> int:
    try:
        record = parse_provenance(load(provenancePath))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: cannot read {provenancePath}: {exc}")
        return 2
    except ProvenanceError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    builders = load_optional(DATA / "builders.json", {})
    consumed = {
        str(item.get("workflowRunId"))
        for item in builders.get("builderRecords", [])
        if isinstance(item, dict) and item.get("workflowRunId")
    }

    result = verify_provenance(
        record,
        artifactRoot=artifactRoot,
        expectedCommit=expectedCommit,
        expectedBaseDigest=expectedBaseDigest,
        verificationEnvironmentId=verificationEnvironment,
        builderEnvironmentId=record.workflowRunId,
        now=now(),
        consumedRunIds=consumed,
    )
    atomic_json(output or (OUT / "ci-verification.json"), result)
    for check in result["checks"]:
        print(f"  {check['outcome']:8} {check['check']}: {check['detail']}")
    if not result["accepted"]:
        print("BLOCKED: the downloaded evidence is not acceptable. An artifact is not trustworthy")
        print("because it came from a CI provider.")
        return 2
    print("CI artifacts verified against the downloaded bytes")
    return 0


# --- Workstreams 7 to 13: per-CVE reachability --------------------------------


def _reachability(subcommand: str, *extra: str) -> int:
    result = subprocess.run(
        [os.sys.executable, str(ROOT / "scripts/reachability.py"), subcommand, *extra],
        cwd=ROOT,
        text=True,
    )
    return result.returncode


def cve_disposition() -> int:
    """Aggregate the per-CVE analyses into the vulnerability gate's input."""
    findings = load_optional(DATA / "vulnerability-disposition.json", {"findings": []})
    blocking = [
        item for item in findings.get("findings", []) if item.get("scannerSeverity") in {"Critical", "High"}
    ]
    expected = [item["advisoryId"] for item in blocking]
    critical = [item["advisoryId"] for item in blocking if item["scannerSeverity"] == "Critical"]

    analyses = []
    for advisory in expected:
        path = SECURITY / "findings" / f"{advisory}.json"
        if path.is_file():
            analyses.append(load(path))

    try:
        result = evaluate_cve_document(
            {"schemaVersion": 1, "analyses": analyses},
            completed_independent_reviews=_completed_reviews(),
            criticalAdvisories=critical,
            independentReviewers=_external_reviewers(),
            expectedAdvisories=expected,
        )
    except CveAnalysisError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "cve-reachability-disposition.json", result)
    print(f"per-CVE analyses: {result['analysed']} of {len(expected)} Critical/High advisories")
    for name, advisories in sorted(result["byProofClass"].items()):
        print(f"  {name:26} {len(advisories)}")
    if result["uncoveredAdvisories"]:
        print("  UNCOVERED: " + ", ".join(result["uncoveredAdvisories"]))
    if result["blocked"]:
        print(f"BLOCKED: {result['blockingCount']} advisory(ies) block a stable release")
        return 2
    print("every Critical and High advisory has an acceptable, reviewed disposition")
    return 0


# --- Workstreams 14 and 15: independent reviews -------------------------------


def update_support_policy() -> int:
    """Admit or refuse the unsupported-update policy behind blocking condition 7.

    Deliberately a standalone verb rather than a new row in the candidate gate.
    Changing what the release gate is composed of, during a release phase, on
    the strength of a decision taken in that same phase, is the kind of edit
    that should be proposed and reviewed rather than slipped in. This verb
    reports; it does not relabel the update matrix, which still records that
    none of its thirteen scenarios was executed.
    """
    path = DATA / "update-support-policy.json"
    if not path.is_file():
        print("NOT_RUN: operations/data/update-support-policy.json does not exist")
        print("  Blocking condition 7 is unmet: the update matrix is NOT_RUN and no")
        print("  approved unsupported-update policy stands behind it.")
        return 2
    try:
        verdict = updatepolicy_module.load_and_evaluate(path, root=ROOT)
    except updatepolicy_module.UpdatePolicyError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    atomic_json(OUT / "update-support-policy.json", verdict.as_dict())

    print(f"update support policy: {verdict.decision} for release class {verdict.releaseClass}")
    print(f"  approver:          {verdict.approver}")
    print(f"  bound to:          {verdict.boundToDigest}")
    print(f"  refusal qualified: {verdict.refusalQualified}")
    if not verdict.admissible:
        print("  INADMISSIBLE:")
        for reason in verdict.reasons:
            print(f"    - {reason}")
        return 2
    print()
    print("  ADMISSIBLE. Blocking condition 7 is satisfied for the bound artifact.")
    print("  It does not close the update matrix and waives no scenario: all thirteen")
    print("  remain NOT_RUN with their recorded reasons.")
    return 0


def validate_independent_reviews() -> int:
    """Requests must be sendable; delivered records must be signed and bound."""
    document = load_optional(DATA / "independent-reviews.json", None)
    if document is None:
        print("BLOCKED: operations/data/independent-reviews.json does not exist")
        return 2
    try:
        status = evaluate_reviews(document, root=ROOT)
        requests = evaluate_requests(ROOT)
        records = evaluate_review_records(document, root=ROOT, expectedCommit=candidate_commit())
    except ReviewError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    payload = {
        "schemaVersion": 1,
        "status": status,
        "requests": requests,
        "records": records,
        "allComplete": status["allComplete"] and records["allComplete"],
    }
    atomic_json(OUT / "independent-reviews.json", payload)

    for review in status["reviews"]:
        reviewer = review["reviewer"] or "unassigned"
        print(f"  {review['state']:18} {review['kind']:14} reviewer={reviewer}")
        if review["package"]["missingSections"]:
            print("      package missing: " + ", ".join(review["package"]["missingSections"]))
    print()
    for kind, gaps in sorted(requests["requests"].items()):
        state = "ready" if not gaps else "incomplete"
        print(f"  request {kind:14} {state}")
        for gap in gaps:
            print(f"      missing: {gap}")
    print()
    print(f"delivered review records: {records['acceptedCount']} of {records['recordCount']}")
    for reason in records["rejected"]:
        print(f"  REJECTED {reason}")

    if not payload["allComplete"]:
        outstanding = sorted(set(status["outstandingReviews"]) | set(records["outstandingReviewTypes"]))
        print("BLOCKED: outstanding reviews: " + ", ".join(outstanding))
        print("No reviewer name or completion date has been invented; the requests are ready to send.")
        return 2
    print("all independent reviews delivered, signed and bound to this commit")
    return 0


# --- Workstreams 16 to 18: hardware evidence ---------------------------------


def collect_hardware_evidence() -> int:
    """Report what the on-device collector would gather, and what it excludes."""
    from release.hardware import COLLECTOR_FIELDS, EXCLUDED_CATEGORIES, GUIDED_TESTS

    payload = {
        "schemaVersion": 1,
        "command": "bunny-os qualification collect",
        "collectorFields": list(COLLECTOR_FIELDS),
        "excludedCategories": list(EXCLUDED_CATEGORIES),
        "guidedTests": list(GUIDED_TESTS),
        "recordCommand": "bunny-os qualification record --test <test> --outcome <outcome> ...",
        "reportCommand": "bunny-os qualification report --operator <name>",
        "note": (
            "The collector is an allow-list of seventeen facts recorded as classes rather than "
            "identities. It has no function that reads a serial number, a MAC or IP address, a "
            "hostname, a username, a network name, a personal path or file, a Bunny prompt or "
            "memory, or browser history."
        ),
    }
    atomic_json(OUT / "hardware-collector.json", payload)
    print(f"collector fields: {len(COLLECTOR_FIELDS)}")
    print(f"excluded categories: {len(EXCLUDED_CATEGORIES)}")
    print(f"guided tests: {len(GUIDED_TESTS)}")
    print("run on the device under test: bunny-os qualification collect")
    return 0


def validate_hardware_evidence() -> int:
    document = load_optional(DATA / "hardware-evidence.json", {"schemaVersion": 1, "reports": []})
    try:
        result = evaluate_intake(document, evidenceRoot=HARDWARE_EVIDENCE)
    except HardwareEvidenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    collections = load_optional(DATA / "hardware-collections.json", {"schemaVersion": 1, "collections": []})
    try:
        collection_result = evaluate_collection(collections, evidenceRoot=HARDWARE_EVIDENCE)
    except HardwareCollectionError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    payload = {**result, "collections": collection_result}
    atomic_json(OUT / "hardware-evidence.json", payload)
    print(f"hardware evidence: {result['accepted']} accepted of {result['submitted']} submitted")
    for rejection in result["rejected"]:
        print(f"  REJECTED {rejection}")
    print(f"qualified x86-64 UEFI machines: {result['qualifiedX86UefiMachines'] or 'none'}")
    print(
        f"guided collections: {collection_result['accepted']} accepted of "
        f"{collection_result['submitted']} submitted, "
        f"{len(collection_result['completeCollections'])} complete and signed"
    )
    for rejection in collection_result["rejected"]:
        print(f"  REJECTED {rejection}")
    if not result["requirementMet"] or not collection_result["requirementMet"]:
        print(
            "BLOCKED: no x86-64 UEFI physical machine is fully qualified. This cannot be produced "
            "by running more tests; it needs a device."
        )
        return 2
    print("hardware requirement met")
    return 0


# --- Workstream 19: accessibility evidence -----------------------------------


def accessibility_evidence_plan() -> int:
    plan = accessibility_module.evidence_plan()
    atomic_json(OUT / "accessibility-evidence-plan.json", plan)
    print(f"accessibility flows: {len(plan['flows'])}")
    for flow in plan["flows"]:
        marker = "blocks release" if flow["blocksRelease"] else flow["failureSeverity"]
        extra = " (needs an installer ISO)" if flow["requiresPreInstallEnvironment"] else ""
        print(f"  {flow['flow']:32} {marker}{extra}")
    print("\nRefusals:")
    for refusal in plan["refusals"]:
        print(f"  - {refusal}")
    return 0


def validate_accessibility_evidence() -> int:
    document = load_optional(DATA / "accessibility-evidence.json", None)
    if document is None:
        print("BLOCKED: operations/data/accessibility-evidence.json does not exist")
        return 2
    reviews = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    review_complete = False
    try:
        review_complete = "accessibility" in evaluate_reviews(reviews, root=ROOT)["completeReviews"]
    except ReviewError:
        review_complete = False

    try:
        result = accessibility_module.evaluate_evidence(
            document,
            evidenceRoot=ACCESSIBILITY_EVIDENCE if ACCESSIBILITY_EVIDENCE.is_dir() else None,
            independentReviewComplete=review_complete,
        )
    except accessibility_module.AccessibilityEvidenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    atomic_json(OUT / "accessibility-evidence.json", result)
    print(
        f"accessibility: {len(result['passingFlows'])} passing, {len(result['failingFlows'])} failing, "
        f"{len(result['notRunFlows'])} not run of {result['flowCount']} flows"
    )
    for reason in result["rejected"]:
        print(f"  REJECTED {reason}")
    print(f"assistive technologies exercised: {', '.join(result['assistiveTechnologies']) or 'none'}")
    if result["criticalUnresolvedFlows"]:
        print("  critical flows unresolved: " + ", ".join(result["criticalUnresolvedFlows"]))
    for reason in result["reasons"]:
        print(f"  {reason}")
    if not result["requirementMet"]:
        print("BLOCKED: accessibility evidence is incomplete")
        return 2
    print("accessibility requirement met")
    return 0


# --- Workstream 21: two-person development signing drill ---------------------


def two_person_development_signing_drill() -> int:
    document = load_optional(DATA / "two-person-signing-drill.json", None)
    if document is None:
        print("BLOCKED: operations/data/two-person-signing-drill.json does not exist")
        print("run: python scripts/two_person_drill.py --artifact <a built image archive>")
        return 2
    try:
        result = evaluate_two_person_drill(document)
    except SigningError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "two-person-signing-drill.json", result)
    for check in result["checks"]:
        print(f"  {check['outcome']:8} {check['check']}")
    if result["missingChecks"]:
        print("BLOCKED: missing checks: " + ", ".join(result["missingChecks"]))
        return 2
    if result["failingChecks"]:
        print("BLOCKED: failing checks: " + ", ".join(result["failingChecks"]))
        return 2
    print(f"two-person development signing drill PASSED — {len(result['checks'])}/9")
    print(
        "This validates the process. It does not satisfy the production second-signer requirement: "
        "both keys are development keys and one person ran the drill."
    )
    return 0


# --- Workstreams 22 and 23: candidate readiness and the dashboard ------------


def _candidate_observations() -> dict[str, dict[str, Any]]:
    """Gather the fourteen prerequisite states from the evidence on disk."""
    commit = candidate_commit()
    observations: dict[str, dict[str, Any]] = {}

    def observe(name: str, satisfied: bool, evidence: str, **extra: Any) -> None:
        observations[name] = {"satisfied": satisfied, "evidence": evidence, **extra}

    # Licence
    licence_document = load_optional(DATA / "licence-decision.json", None)
    licence_passed = False
    if licence_document is not None:
        try:
            decision = parse_decision(licence_document)
            licence_passed = evaluate_licence_gate(
                decision, root=ROOT, licenceScanResult=licence_document.get("licenceScanResult")
            ).passed
        except LicenceError:
            licence_passed = False
    observe(
        "licence-gate",
        licence_passed,
        "operations/data/licence-decision.json; 7 of 7 requirements" if licence_passed else "licence gate blocked",
        commit=commit if licence_passed else "",
    )

    # Vulnerability, from the per-CVE analyses
    findings = load_optional(DATA / "vulnerability-disposition.json", {"findings": []})
    blocking = [
        item for item in findings.get("findings", []) if item.get("scannerSeverity") in {"Critical", "High"}
    ]
    analyses = [
        load(SECURITY / "findings" / f"{item['advisoryId']}.json")
        for item in blocking
        if (SECURITY / "findings" / f"{item['advisoryId']}.json").is_file()
    ]
    unresolved = [item for item in analyses if item.get("conclusion") != "Not present" and item.get("conclusion") != "Present but unreachable"]
    observe(
        "vulnerability-gate",
        bool(analyses) and not unresolved,
        f"{len(analyses)} per-CVE analyses; {len(unresolved)} unresolved",
        state="PENDING_EXTERNAL_REVIEW" if unresolved else None,
        blocker=f"{len(unresolved)} Critical/High advisories remain Unknown" if unresolved else "none",
        dependency="independent security review",
    )

    # Independent reproducibility
    builders = load_optional(DATA / "builders.json", {})
    independent = False
    try:
        independent = evaluate_builder_set(builders, toolClassifications=_tool_classifications())["requirementMet"]
    except BuilderError:
        independent = False
    observe(
        "independent-reproducibility",
        independent,
        "operations/data/builders.json" if independent else "no verified independent builder pair",
        dependency="hosted CI run of .github/workflows/independent-builder.yml",
    )

    # Development signing drill
    drill = load_optional(DATA / "signing-drill.json", None)
    drill_passed = False
    if drill is not None:
        try:
            drill_passed = evaluate_drill(drill.get("checks", []))["result"] == "PASS"
        except SigningError:
            drill_passed = False
    observe(
        "development-signing-drill",
        drill_passed,
        "operations/data/signing-drill.json; 9/9" if drill_passed else "drill not passing",
        commit=commit if drill_passed else "",
    )

    # Matrices
    matrices = load_optional(DATA / "qualification-matrices.json", {"matrices": {}})
    matrix_states: dict[str, bool] = {}
    for name in ("recovery-media", "installation", "encryption", "update", "rollback"):
        recorded = matrices.get("matrices", {}).get(name)
        state = False
        if recorded is not None:
            try:
                state = matrix_module.evaluate_matrix(name, recorded, root=ROOT).complete
            except matrix_module.MatrixError:
                state = False
        matrix_states[name] = state
    for prerequisite, matrix_name, dependency in (
        ("independent-recovery-media", "recovery-media", "a signed recovery ISO"),
        ("installation-matrix", "installation", "a live installer ISO"),
        ("encryption-matrix", "encryption", "a completed installation"),
        ("update-matrix", "update", "a published signed update manifest"),
        ("rollback-matrix", "rollback", "a previous release to roll back to"),
    ):
        observe(
            prerequisite,
            matrix_states[matrix_name],
            f"{matrix_name} matrix" if matrix_states[matrix_name] else f"{matrix_name} matrix incomplete",
            dependency=dependency,
        )

    # Hardware
    hardware = load_optional(DATA / "hardware-evidence.json", {"schemaVersion": 1, "reports": []})
    hardware_met = False
    try:
        hardware_met = evaluate_intake(hardware, evidenceRoot=HARDWARE_EVIDENCE)["requirementMet"]
    except HardwareEvidenceError:
        hardware_met = False
    observe(
        "physical-hardware-evidence",
        hardware_met,
        "hardware/evidence/" if hardware_met else "zero reports submitted",
        dependency="one x86-64 UEFI machine with Secure Boot and TPM 2.0",
    )

    # Accessibility
    accessibility_document = load_optional(DATA / "accessibility-evidence.json", {"schemaVersion": 1, "results": []})
    reviews_document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    try:
        complete_reviews = evaluate_reviews(reviews_document, root=ROOT)["completeReviews"]
    except ReviewError:
        complete_reviews = []
    accessibility_met = False
    try:
        accessibility_met = accessibility_module.evaluate_evidence(
            accessibility_document,
            independentReviewComplete="accessibility" in complete_reviews,
        )["requirementMet"]
    except accessibility_module.AccessibilityEvidenceError:
        accessibility_met = False
    observe(
        "accessibility-evidence",
        accessibility_met,
        "operations/data/accessibility-evidence.json" if accessibility_met else "0 of 17 flows driven",
        dependency="an independent accessibility review",
    )

    # Independent reviews
    reviews_complete = False
    try:
        reviews_complete = (
            evaluate_reviews(reviews_document, root=ROOT)["allComplete"]
            and evaluate_review_records(reviews_document, root=ROOT, expectedCommit=commit)["allComplete"]
        )
    except ReviewError:
        reviews_complete = False
    observe(
        "independent-reviews",
        reviews_complete,
        "operations/data/independent-reviews.json" if reviews_complete else "four packages prepared, zero delivered",
        dependency="four identified external reviewers",
    )

    # Second production signer
    signing = load_optional(DATA / "signing-keys.json", {"keys": []})
    production_signers: set[str] = set()
    try:
        for item in signing.get("keys", []):
            record = parse_key_record(item)
            if record.keyClass == "production" and record.state in {"active", "rotating"}:
                production_signers.add(record.keyId)
    except SigningError:
        production_signers = set()
    observe(
        "second-production-signer",
        len(production_signers) >= 2,
        f"{len(production_signers)} production key(s) exist",
        dependency="a second person and a key ceremony",
    )

    # Approvals
    qualification = load_optional(DATA / "stable-qualification.json", {"approvals": {}})
    approvals = qualification.get("approvals", {})
    from release.gates import REQUIRED_APPROVALS

    pending = [owner for owner in REQUIRED_APPROVALS if approvals.get(owner) != "APPROVED"]
    observe(
        "protected-approvals",
        not pending,
        f"{len(REQUIRED_APPROVALS) - len(pending)} of {len(REQUIRED_APPROVALS)} recorded",
        blocker="approvals pending: " + ", ".join(pending) if pending else "none",
    )

    return {
        name: {key: value for key, value in observation.items() if value is not None}
        for name, observation in observations.items()
    }


def _candidate_readiness():
    return evaluate_candidate(
        _candidate_observations(), sourceCommit=candidate_commit(), now=now()
    )


def qualification_candidate_readiness() -> int:
    try:
        readiness = _candidate_readiness()
    except CandidateError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    payload = readiness.as_dict()
    atomic_json(OUT / "qualification-candidate.json", payload)
    write_text(OUT / "stable-evidence-dashboard.md", render_dashboard(readiness))

    print(f"candidate prerequisites: {len(payload['satisfied'])} of {len(CANDIDATE_PREREQUISITES)} satisfied")
    for row in payload["rows"]:
        print(f"  {row['state']:24} {row['description']}")
        if not row["satisfied"]:
            print(f"      owner={row['owner']} next={row['nextAction']}")
    print(f"\nwrote {display_path(OUT / 'stable-evidence-dashboard.md', ROOT)}")
    if not readiness.ready:
        print(
            "BLOCKED: no artifact may be labelled release-qualified while a prerequisite is "
            "unsatisfied. Building a candidate for examination remains permitted."
        )
        return 2
    print("every candidate prerequisite is satisfied")
    return 0


# --- Workstream 24: gate-source ----------------------------------------------


def source_gate() -> int:
    """The source gate. Runs the repository's own checks and nothing else."""
    def suite(command: list[str]) -> bool:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        # Say which test failed. This used to swallow the output entirely, and
        # the cost was paid twice in one session: `sourceSuitesPass` reported
        # FAIL while the same command run by hand a minute later passed 4,665
        # tests, and there was nothing anywhere to say what had gone wrong. A
        # gate that can fail without naming a reason cannot be acted on — the
        # only options are to re-run it and hope, or to distrust it.
        print(f"\n{' '.join(command)} exited {result.returncode}; its last lines were:")
        for stream, text in (("stderr", result.stderr), ("stdout", result.stdout)):
            lines = [line for line in (text or "").splitlines() if line.strip()]
            for line in lines[-25:]:
                print(f"  {stream}: {line}")
        return False

    licence_document = load_optional(DATA / "licence-decision.json", None)
    licence_passed = False
    if licence_document is not None:
        try:
            decision = parse_decision(licence_document)
            licence_passed = evaluate_licence_gate(
                decision, root=ROOT, licenceScanResult=licence_document.get("licenceScanResult")
            ).passed
        except LicenceError:
            licence_passed = False

    minimisation_document = load_optional(DATA / "package-minimisation.json", None)
    minimisation = False
    if minimisation_document is not None:
        try:
            minimisation = evaluate_minimisation(minimisation_document)["result"] == "PASS"
        except MinimisationError:
            minimisation = False

    # Run the validators in process rather than shelling out to `task.py
    # validate`, so the gate can name the validator and the file that failed.
    # Shelling out reduced twelve independent checks to one exit code, which is
    # how "repositoryValidation: FAIL" came to describe JSON, schemas and Python
    # when the thing that failed was ShellCheck on one line of one file.
    validation = run_validators(ROOT)
    atomic_json(OUT / "repository-validation.json", validation.as_dict())

    python = os.sys.executable
    requirements = {
        "repositoryValidation": validation.passed,
        "sourceSuitesPass": suite([python, "scripts/task.py", "test"]),
        "qualificationSuitesPass": suite([python, "scripts/task.py", "test-release-closure"]),
        "licenceGatePassed": licence_passed,
        "minimisationComplete": minimisation,
        "baselineRecorded": qualification_evidence_baseline() == 0,
    }
    try:
        result = evaluate_source_gate(requirements)
    except GateError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "gate-source.json", result.as_dict())
    print(f"source gate: {result.recommendation}")
    for name in result.satisfied:
        print(f"  ok      {name}")
    for name in result.unmet:
        print(f"  FAIL    {name}")

    if not validation.passed:
        print("\nrepositoryValidation, by validator:")
        print(validation.render())
    print(f"\nwrote {display_path(OUT / 'repository-validation.json', ROOT)}")
    print(
        "\nA passing source gate asserts nothing about a built image, a booted system, a review, a "
        "device or a signature."
    )
    return 0 if result.passed or result.recommendation == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="release")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "baseline",
        "qualification-evidence-baseline",
        "vulnerability-position",
        "reachability-review",
        "cve-disposition",
        "package-minimisation-check",
        "licence-gate",
        "reproducibility-compare",
        "independent-builder-ci-manifest",
        "verify-builder-independence",
        "compare-independent-builds",
        "development-signing-drill",
        "two-person-development-signing-drill",
        "signing-roles",
        "collect-hardware-evidence",
        "validate-hardware-evidence",
        "accessibility-evidence-plan",
        "validate-accessibility-evidence",
        "validate-independent-reviews",
        "update-support-policy",
        "stable-evidence-report",
        "qualification-candidate-readiness",
        "validate-release-manifest",
        "pilot-closure-assertion",
        "acquire-cve-sources",
        "analyse-cve-symbols",
        "generate-reachability-packages",
        "validate-cve-acquisition",
        "validate-repository",
    ):
        commands.add_parser(name)

    prepare = commands.add_parser("independent-builder-prepare")
    prepare.add_argument("--builder", required=True)

    collect = commands.add_parser("collect-builder-record")
    collect.add_argument("--builder-id", required=True)
    collect.add_argument(
        "--builder-type",
        choices=("local-machine", "hosted-ci", "self-hosted-ci", "cloud-vm", "physical-builder"),
    )

    normalise = commands.add_parser("normalise-artifact")
    normalise.add_argument("--source", required=True, type=Path)
    normalise.add_argument("--destination", required=True, type=Path)
    normalise.add_argument("--output", type=Path)

    hosted_import = commands.add_parser("import-hosted-builder-evidence")
    hosted_import.add_argument("--artifact-dir", required=True, type=Path)
    hosted_import.add_argument("--candidate-commit", required=True)
    hosted_import.add_argument("--expected-base-digest")
    hosted_import.add_argument("--expected-run-id")
    hosted_import.add_argument(
        "--local-artifact-dir",
        type=Path,
        help="the local builder's matching bundle; a pair is what establishes independence",
    )

    assemble = commands.add_parser("assemble-build-comparison")
    assemble.add_argument("--first", required=True, type=Path)
    assemble.add_argument("--second", required=True, type=Path)
    assemble.add_argument("--first-label", default="local")
    assemble.add_argument("--second-label", default="hosted-ci")
    assemble.add_argument("--raw-variance-explanation")
    assemble.add_argument("--source-commit", required=True)
    assemble.add_argument("--base-image-digest", required=True)

    verify_ci = commands.add_parser("verify-ci-artifacts")
    verify_ci.add_argument("--provenance", required=True, type=Path)
    verify_ci.add_argument("--artifact-root", required=True, type=Path)
    verify_ci.add_argument("--expected-commit", required=True)
    verify_ci.add_argument("--expected-base-digest", required=True)
    verify_ci.add_argument("--verification-environment", required=True)
    verify_ci.add_argument("--output", type=Path)

    symbols = commands.add_parser("analyse-symbols")
    symbols.add_argument("--sysroot", type=Path)

    matrix_parser = commands.add_parser("test-matrix")
    matrix_parser.add_argument("--name", required=True, choices=sorted(matrix_module.MATRICES))

    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument(
        "--kind",
        required=True,
        choices=(
            "source",
            "qualification-candidate",
            "stable-release",
            "oem-pilot",
            "enterprise-pilot",
            "sync-pilot",
        ),
    )

    args = parser.parse_args()
    dispatch = {
        "baseline": release_blocker_baseline,
        "qualification-evidence-baseline": qualification_evidence_baseline,
        "vulnerability-position": vulnerability_position,
        "reachability-review": reachability_review,
        "cve-disposition": cve_disposition,
        "package-minimisation-check": package_minimisation_check,
        "licence-gate": licence_gate,
        "reproducibility-compare": reproducibility_compare,
        "independent-builder-ci-manifest": independent_builder_ci_manifest,
        "verify-builder-independence": verify_builder_independence,
        "compare-independent-builds": compare_independent_builds,
        "development-signing-drill": development_signing_drill,
        "two-person-development-signing-drill": two_person_development_signing_drill,
        "signing-roles": signing_roles,
        "collect-hardware-evidence": collect_hardware_evidence,
        "validate-hardware-evidence": validate_hardware_evidence,
        "accessibility-evidence-plan": accessibility_evidence_plan,
        "validate-accessibility-evidence": validate_accessibility_evidence,
        "validate-independent-reviews": validate_independent_reviews,
        "update-support-policy": update_support_policy,
        "stable-evidence-report": stable_evidence_report,
        "qualification-candidate-readiness": qualification_candidate_readiness,
        "validate-release-manifest": validate_release_manifest,
        "validate-repository": validate_repository,
        "pilot-closure-assertion": pilot_closure_assertion,
    }
    if args.command in dispatch:
        return dispatch[args.command]()
    if args.command == "acquire-cve-sources":
        return _reachability("acquire-plan")
    if args.command == "validate-cve-acquisition":
        return _reachability("validate-acquisition")
    if args.command == "analyse-cve-symbols":
        return _reachability("analyse-symbols")
    if args.command == "generate-reachability-packages":
        return _reachability("generate-packages")
    if args.command == "analyse-symbols":
        return _reachability("analyse-symbols", *(["--sysroot", str(args.sysroot)] if args.sysroot else []))
    if args.command == "independent-builder-prepare":
        return independent_builder_prepare(args.builder)
    if args.command == "collect-builder-record":
        return collect_builder_record(args.builder_id, args.builder_type)
    if args.command == "import-hosted-builder-evidence":
        return import_hosted_builder_evidence(
            args.artifact_dir,
            args.candidate_commit,
            args.expected_base_digest,
            args.expected_run_id,
            args.local_artifact_dir,
        )
    if args.command == "assemble-build-comparison":
        return assemble_build_comparison(
            args.first, args.second, args.first_label, args.second_label,
            args.raw_variance_explanation, args.source_commit, args.base_image_digest,
        )
    if args.command == "normalise-artifact":
        return normalise_artifact(args.source, args.destination, args.output)
    if args.command == "verify-ci-artifacts":
        return verify_ci_artifacts(
            args.provenance,
            args.artifact_root,
            args.expected_commit,
            args.expected_base_digest,
            args.verification_environment,
            args.output,
        )
    if args.command == "test-matrix":
        return test_matrix(args.name)
    if args.command == "gate":
        return gate(args.kind)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

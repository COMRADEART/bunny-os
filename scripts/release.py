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
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release import matrix as matrix_module
from release.artifacts import ArtifactError, parse_manifest, verify_against_disk
from release.evidence import (
    EVIDENCE_CATEGORIES,
    EvidenceError,
    evaluate_evidence,
)
from release.gates import (
    GateError,
    PILOT_REQUIREMENTS,
    StableInputs,
    evaluate_pilot_gate,
    evaluate_stable_gate,
)
from release.hardware import HardwareEvidenceError, evaluate_intake
from release.licensing import LicenceError, evaluate_licence_gate, parse_decision
from release.minimisation import MinimisationError, evaluate_minimisation
from release.reachability import ReachabilityError, parse_review as parse_reachability, summarise
from release.reproducibility import (
    ReproducibilityError,
    compare_builds,
    parse_builder,
    summarise_claims,
)
from release.reviews import ReviewError, completed_review_identifiers, evaluate_reviews
from release.signing import (
    SigningError,
    evaluate_drill,
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


# --- Workstream 14: hardware ---------------------------------------------------


def validate_hardware_evidence() -> int:
    document = load_optional(DATA / "hardware-evidence.json", {"schemaVersion": 1, "reports": []})
    try:
        result = evaluate_intake(document, evidenceRoot=HARDWARE_EVIDENCE)
    except HardwareEvidenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "hardware-evidence.json", result)
    print(f"hardware evidence: {result['accepted']} accepted of {result['submitted']} submitted")
    for rejection in result["rejected"]:
        print(f"  REJECTED {rejection}")
    print(f"qualified x86-64 UEFI machines: {result['qualifiedX86UefiMachines'] or 'none'}")
    if not result["requirementMet"]:
        print(
            "BLOCKED: no x86-64 UEFI physical machine is fully qualified. This cannot be produced "
            "by running more tests; it needs a device."
        )
        return 2
    print("hardware requirement met")
    return 0


# --- Workstream 16: independent reviews ----------------------------------------


def validate_independent_reviews() -> int:
    document = load_optional(DATA / "independent-reviews.json", None)
    if document is None:
        print("BLOCKED: operations/data/independent-reviews.json does not exist")
        return 2
    try:
        result = evaluate_reviews(document, root=ROOT)
    except ReviewError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    atomic_json(OUT / "independent-reviews.json", result)
    for review in result["reviews"]:
        reviewer = review["reviewer"] or "unassigned"
        print(f"  {review['state']:18} {review['kind']:14} reviewer={reviewer}")
        if review["package"]["missingSections"]:
            print("      package missing: " + ", ".join(review["package"]["missingSections"]))
    if result["outstandingReviews"]:
        print("BLOCKED: outstanding reviews: " + ", ".join(result["outstandingReviews"]))
        return 2
    print("all independent reviews delivered")
    return 0


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
            sourceCommit=source_commit(),
            now=now(),
            externalReviewers=_external_reviewers(),
        )
    except EvidenceError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    payload = report.as_dict()
    atomic_json(OUT / "stable-evidence-report.json", payload)

    print(f"evidence records: {payload['recordCount']}, blocking: {payload['blockingRecordCount']}")
    for record in payload["blockingRecords"]:
        print(f"  BLOCKING {record['id']} ({record['category']})")
        for reason in record["blockingReasons"]:
            print(f"      {reason}")
    if payload["missingCategories"]:
        print("  MISSING CATEGORIES: " + ", ".join(payload["missingCategories"]))
    print(f"wrote {OUT / 'stable-evidence-report.json'}")
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
            sourceCommit=source_commit(),
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


def gate(kind: str) -> int:
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
        return 0 if stable.passed else 2

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


def main() -> int:
    parser = argparse.ArgumentParser(prog="release")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "baseline",
        "vulnerability-position",
        "reachability-review",
        "package-minimisation-check",
        "licence-gate",
        "reproducibility-compare",
        "development-signing-drill",
        "signing-roles",
        "validate-hardware-evidence",
        "validate-independent-reviews",
        "stable-evidence-report",
        "validate-release-manifest",
        "pilot-closure-assertion",
    ):
        commands.add_parser(name)

    prepare = commands.add_parser("independent-builder-prepare")
    prepare.add_argument("--builder", required=True)

    matrix_parser = commands.add_parser("test-matrix")
    matrix_parser.add_argument("--name", required=True, choices=sorted(matrix_module.MATRICES))

    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument(
        "--kind",
        required=True,
        choices=("stable-release", "oem-pilot", "enterprise-pilot", "sync-pilot"),
    )

    args = parser.parse_args()
    dispatch = {
        "baseline": release_blocker_baseline,
        "vulnerability-position": vulnerability_position,
        "reachability-review": reachability_review,
        "package-minimisation-check": package_minimisation_check,
        "licence-gate": licence_gate,
        "reproducibility-compare": reproducibility_compare,
        "development-signing-drill": development_signing_drill,
        "signing-roles": signing_roles,
        "validate-hardware-evidence": validate_hardware_evidence,
        "validate-independent-reviews": validate_independent_reviews,
        "stable-evidence-report": stable_evidence_report,
        "validate-release-manifest": validate_release_manifest,
        "pilot-closure-assertion": pilot_closure_assertion,
    }
    if args.command in dispatch:
        return dispatch[args.command]()
    if args.command == "independent-builder-prepare":
        return independent_builder_prepare(args.builder)
    if args.command == "test-matrix":
        return test_matrix(args.name)
    if args.command == "gate":
        return gate(args.kind)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

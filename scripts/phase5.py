#!/usr/bin/env python3
"""Repository-native Bunny OS Phase 5 operations commands."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from operations.candidate import validate_candidate
from operations.dashboard import render_markdown
from operations.feedback import ingest_documents, suggest_duplicates
from operations.qualification import evaluate_release
from operations.signatures import validate_signature


DATA = ROOT / "operations/data"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def phase4_preflight() -> int:
    required = (
        "PHASE_4_REPORT.md", "PUBLIC_BETA_SECURITY_REVIEW.md", "PUBLIC_BETA_PRIVACY_REVIEW.md",
        "PUBLIC_BETA_ACCESSIBILITY_REVIEW.md", "PUBLIC_BETA_RELEASE_CHECKLIST.md", "PUBLIC_BETA_GO_NO_GO.md",
        "NETWORK_PRIVACY_TEST_REPORT.md", "REPRODUCIBLE_BUILD_REPORT.md", "LICENSE_COMPLIANCE_REPORT.md",
    )
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        print("Phase 4/public-beta preflight BLOCKED; missing:")
        print("\n".join(missing))
        return 2
    print("Phase 4/public-beta source report preflight passed; runtime evidence must still be checked separately")
    return 0


def baseline() -> int:
    path = ROOT / "docs/PHASE_5_BASELINE.md"
    if not path.is_file():
        print("missing docs/PHASE_5_BASELINE.md")
        return 2
    text = path.read_text(encoding="utf-8").casefold()
    required = (
        "current beta version", "beta duration", "number of releases", "open issues by severity",
        "installation failures", "boot failures", "update failures", "rollback failures", "recovery failures",
        "crash categories", "hardware coverage", "stable-release blockers",
    )
    missing = [value for value in required if value not in text]
    if missing:
        print("Phase 5 baseline missing fields: " + ", ".join(missing))
        return 2
    print("Phase 5 baseline contains all mandatory evidence fields")
    return 0


def import_feedback(source: Path, output: Path) -> int:
    payload = load(source)
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("reports"), list):
        raise SystemExit("feedback export must be a schema version 1 object with reports")
    issues = ingest_documents(payload["reports"])
    value = {
        "schemaVersion": 1,
        "sourceRecords": [{"path": source.name, "count": len(issues)}],
        "issues": [item.export() for item in issues],
        "duplicateSuggestions": suggest_duplicates(issues),
        "automaticClosures": 0,
        "automaticSeverityReductions": 0,
        "redactedBeforeStorage": True,
    }
    atomic_json(output, value)
    print(f"imported {len(issues)} redacted reports; suggested {len(value['duplicateSuggestions'])} duplicate pairs")
    return 0


def triage_report(ledger_path: Path, output: Path) -> int:
    ledger = load(ledger_path)
    issues = ledger.get("issues", [])
    if not isinstance(issues, list):
        raise SystemExit("issue ledger is invalid")
    severity = Counter(item.get("severity", "unknown") for item in issues if isinstance(item, dict))
    component = Counter(item.get("component", "unknown") for item in issues if isinstance(item, dict))
    lines = [
        "# Generated beta triage report", "", f"Source: `{ledger_path.name}`", "",
        f"Verified imported issue records: {len(issues)}", "", "## Severity", "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(severity.items()))
    if not severity:
        lines.append("- No issue records were supplied; incidence and reliability remain unknown.")
    lines.extend(["", "## Components", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(component.items()))
    if not component:
        lines.append("- No component counts available.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    return 0


def dashboard(output: Path) -> int:
    evidence = load(DATA / "stable-qualification.json")
    decision = evaluate_release(evidence["evidence"], evidence["approvals"], evidence["blockers"])
    values = {
        "candidateVersion": evidence["candidateVersion"] or "none",
        "buildStatus": evidence["evidence"]["reproducible_build"],
        "testStatus": evidence["evidence"]["integration_tests"],
        "openBlockers": decision.blockers,
        "securityStatus": evidence["evidence"]["security"],
        "privacyStatus": evidence["evidence"]["privacy"],
        "accessibilityStatus": evidence["evidence"]["accessibility"],
        "installerStatus": evidence["evidence"]["installer"],
        "updateStatus": evidence["evidence"]["updates"],
        "rollbackStatus": evidence["evidence"]["rollback"],
        "recoveryStatus": evidence["evidence"]["recovery"],
        "hardwareCoverage": evidence["evidence"]["hardware"],
        "documentationStatus": evidence["evidence"]["documentation"],
        "signingStatus": evidence["evidence"]["signature_verification"],
        "artifactStatus": evidence["evidence"]["image_inspection"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(values), encoding="utf-8")
    print(f"wrote {output}; recommendation {decision.recommendation}")
    return 0


def source_gate() -> int:
    signatures = load(DATA / "failure-signatures.json")
    for item in signatures.get("signatures", []):
        validate_signature(item)
    update_matrix = load(DATA / "update-compatibility.json")
    if update_matrix.get("schemaVersion") != 1 or not isinstance(update_matrix.get("entries"), list):
        raise SystemExit("update compatibility matrix is invalid")
    hardware = load(DATA / "hardware-evidence.json")
    if hardware.get("schemaVersion") != 1 or not isinstance(hardware.get("reports"), list):
        raise SystemExit("hardware evidence database is invalid")
    print("Phase 5 source gate passed; this is not a stable-candidate or stable-release approval")
    return 0


def candidate_gate(manifest: Path) -> int:
    if not manifest.is_file():
        print(f"stable candidate gate BLOCKED: missing {manifest}")
        return 2
    validate_candidate(load(manifest))
    print("stable candidate manifest structure passed; cryptographic/media/runtime gates remain separate")
    return 0


def stable_gate(evidence_path: Path) -> int:
    evidence = load(evidence_path)
    decision = evaluate_release(evidence.get("evidence", {}), evidence.get("approvals", {}), evidence.get("blockers", []))
    print(json.dumps(decision.as_dict(), sort_keys=True))
    return 0 if decision.passed else 2


def long_run_plan() -> int:
    value = load(DATA / "long-run-scenarios.json")
    scenarios = value.get("scenarios", [])
    if not isinstance(scenarios, list) or not scenarios:
        raise SystemExit("long-run scenario catalogue is empty")
    invalid = [item.get("id", "unknown") for item in scenarios if item.get("status") == "PASS" and not item.get("evidence")]
    if invalid:
        raise SystemExit("long-run scenarios claim PASS without evidence: " + ", ".join(invalid))
    print(f"validated {len(scenarios)} long-run scenarios; execution status remains NOT_RUN")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("phase4-preflight", "baseline", "source-gate", "dashboard", "long-run-plan"):
        commands.add_parser(name)
    importer = commands.add_parser("import-feedback")
    importer.add_argument("--source", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    triage = commands.add_parser("triage-report")
    triage.add_argument("--ledger", type=Path, required=True)
    triage.add_argument("--output", type=Path, required=True)
    candidate = commands.add_parser("candidate-gate")
    candidate.add_argument("--manifest", type=Path, required=True)
    stable = commands.add_parser("stable-gate")
    stable.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "phase4-preflight":
        return phase4_preflight()
    if args.command == "baseline":
        return baseline()
    if args.command == "source-gate":
        return source_gate()
    if args.command == "import-feedback":
        return import_feedback(args.source, args.output)
    if args.command == "triage-report":
        return triage_report(args.ledger, args.output)
    if args.command == "dashboard":
        return dashboard(ROOT / "build/out/phase5/release-dashboard.md")
    if args.command == "candidate-gate":
        return candidate_gate(args.manifest)
    if args.command == "stable-gate":
        return stable_gate(args.evidence)
    if args.command == "long-run-plan":
        return long_run_plan()
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

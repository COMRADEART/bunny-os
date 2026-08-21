# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Applicability, fixtures, and the reproducible release decision.

Evidence for one artifact evaluated against another defaults to
DOES_NOT_APPLY; transfer needs a recorded decision on a recorded
relationship; a fixture is refused structurally wherever evidence is
consumed — including by Phase 9 registration itself. The committed
candidate-status.json must recompute, byte for byte, from its immutable
inputs; the Phase 9 ledger is read and never written; the next action is
exactly one.

Dry runs use the committed fixtures' inner payloads inside constructed
scratch trees only. The real ledger never sees them, and the tests that
prove acceptance flows are the same tests that prove the wrapper is
refused.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_OPS_TOOL = _ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_GRAPH = _ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json"
_STATUS = _ROOT / "qualification" / "phase10" / "candidate-status.json"
_FIXTURES = _ROOT / "qualification" / "phase10" / "fixtures"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
_DECISION = _ROOT / "qualification" / "phase9" / "decision" / "alpha-release-decision.json"
_P9_FINDINGS = _ROOT / "qualification" / "phase9" / "triage" / "findings.json"
_P10_FINDINGS = _ROOT / "qualification" / "phase10" / "findings" / "registry.json"

_IMAGE = "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d"
_FOREIGN = "e501218f" * 8


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops = _load("phase10_ops_operations", _OPS_TOOL)
intake = _load("phase9_intake_for_phase10", _INTAKE_TOOL)


def _graph() -> dict:
    return json.loads(_GRAPH.read_text(encoding="utf-8"))


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _two_artifact_graph(scope_decision: dict | None = None) -> dict:
    """ROOT plus a modelled successor; optionally one transfer decision."""
    graph = _graph()
    graph["artifacts"].append({
        "artifact_id": "fixture-candidate-next",
        "digest": "sha256:" + "ab" * 32,
        "digests": {"image": "sha256:" + "ab" * 32},
        "source_commit": "0" * 40,
        "build_identity": "constructed control",
        "parent_artifact": "e906a48793d7",
        "supersedes": None,
        "relationship": "REMEDIATES",
        "qualification_state": "REQUALIFICATION_REQUIRED",
    })
    if scope_decision:
        graph["transferDecisions"] = [scope_decision]
    return graph


class Applicability(unittest.TestCase):
    def test_evidence_for_the_target_itself_applies(self) -> None:
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _IMAGE,
             "scope": "security-review"},
            "e906a48793d7", _graph())
        self.assertEqual(verdict["result"], "APPLIES")

    def test_a_different_artifact_defaults_to_does_not_apply(self) -> None:
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _IMAGE,
             "scope": "security-review"},
            "fixture-candidate-next", _two_artifact_graph())
        self.assertEqual(verdict["result"], "DOES_NOT_APPLY")
        self.assertIn("default is no transfer", verdict["reasoning"])

    def test_an_unknown_digest_is_artifact_mismatch(self) -> None:
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _FOREIGN,
             "scope": "security-review"},
            "e906a48793d7", _graph())
        self.assertEqual(verdict["result"], "ARTIFACT_MISMATCH")

    def test_unbound_evidence_is_artifact_mismatch(self) -> None:
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "scope": "alpha-feedback"},
            "e906a48793d7", _graph())
        self.assertEqual(verdict["result"], "ARTIFACT_MISMATCH")
        self.assertIn("unbound", verdict["reasoning"])

    def test_a_recorded_transfer_decision_partially_applies(self) -> None:
        graph = _two_artifact_graph({
            "fromArtifact": "e906a48793d7",
            "toArtifact": "fixture-candidate-next",
            "evidenceScope": "security-review",
            "result": "PARTIALLY_APPLIES",
            "reasoning": "constructed control: unchanged components only",
            "decidedBy": "constructed control decider",
            "date": "2026-08-18",
        })
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _IMAGE,
             "scope": "security-review"},
            "fixture-candidate-next", graph)
        self.assertEqual(verdict["result"], "PARTIALLY_APPLIES")
        self.assertIn("constructed control decider", verdict["reasoning"])

    def test_a_decision_without_reasoning_transfers_nothing(self) -> None:
        graph = _two_artifact_graph({
            "fromArtifact": "e906a48793d7",
            "toArtifact": "fixture-candidate-next",
            "evidenceScope": "security-review",
            "result": "APPLIES",
            "reasoning": "",
            "decidedBy": "constructed control decider",
            "date": "2026-08-18",
        })
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _IMAGE,
             "scope": "security-review"},
            "fixture-candidate-next", graph)
        self.assertEqual(verdict["result"], "DOES_NOT_APPLY")
        self.assertIn("incomplete decision", verdict["reasoning"])

    def test_a_decision_without_a_relationship_transfers_nothing(self) -> None:
        """Two siblings share a parent but no edge joins them; a decision
        between them rides on nothing."""
        graph = _two_artifact_graph()
        graph["artifacts"].append(dict(
            graph["artifacts"][1],
            artifact_id="fixture-sibling",
            digest="sha256:" + "cd" * 32,
            digests={"image": "sha256:" + "cd" * 32},
            relationship="PARALLEL",
        ))
        graph["transferDecisions"] = [{
            "fromArtifact": "fixture-candidate-next",
            "toArtifact": "fixture-sibling",
            "evidenceScope": "security-review",
            "result": "APPLIES",
            "reasoning": "constructed control",
            "decidedBy": "constructed control decider",
            "date": "2026-08-18",
        }]
        verdict = ops.evaluate_applicability(
            {"evidenceId": "INTAKE-001",
             "artifactDigest": "sha256:" + "ab" * 32,
             "scope": "security-review"},
            "fixture-sibling", graph)
        self.assertEqual(verdict["result"], "DOES_NOT_APPLY")
        self.assertIn("no relationship, no transfer", verdict["reasoning"])

    def test_a_fixture_is_refused_outright(self) -> None:
        for name in ("security-review-accepted.json",
                     "signing-metadata-valid.json"):
            with self.assertRaises(ops.BoundaryViolation, msg=name):
                ops.evaluate_applicability(_fixture(name), "e906a48793d7",
                                           _graph())


class _ScratchIntake(unittest.TestCase):
    """A constructed Phase 9 tree for dry runs; the real ledger never
    participates."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phase10-dryrun-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        intake_root = self.tmp / "qualification" / "phase9" / "intake"
        for source in intake.SOURCES:
            (intake_root / source).mkdir(parents=True)
        real = json.loads(_LEDGER.read_text(encoding="utf-8"))
        self.ledger_path = intake_root / "LEDGER.json"
        intake.dump_ledger(self.ledger_path, {
            "schemaVersion": 1,
            "appendMechanism": "qualification/phase9/tools/intake.py",
            "sources": list(intake.SOURCES),
            "statusVocabulary": list(intake.STATUSES),
            "sealAlgorithm": real["sealAlgorithm"],
            "subjectArtifact": real["subjectArtifact"],
            "entries": [],
        })
        self.staging = self.tmp / "staging"
        self.staging.mkdir()

    def _register(self, source: str, payload: dict):
        record = self.staging / "record-src.json"
        record.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
        return intake.register(self.ledger_path, source, record, [],
                               "2026-08-18", "dry-run fixture payload")


class FixtureDiscipline(_ScratchIntake):
    def test_every_fixture_is_structurally_marked(self) -> None:
        self.assertEqual(ops.verify_fixtures(), [])
        names = sorted(p.name for p in _FIXTURES.glob("*.json"))
        self.assertEqual(len(names), 7, names)
        for name in names:
            self.assertEqual(_fixture(name)["fixtureClass"],
                             "TEST_FIXTURE_ONLY", name)

    def test_phase9_registration_rejects_a_marked_record(self) -> None:
        entry = self._register("security-review",
                               _fixture("security-review-accepted.json"))
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])
        self.assertFalse(entry["gateEligible"])

    def test_a_marked_ledger_entry_is_refused_by_derivation(self) -> None:
        ledger = intake.load_ledger(self.ledger_path)
        ledger["entries"].append({
            "intakeId": "INTAKE-001", "revises": None,
            "source": "security-review", "status": "ACCEPTED",
            "gateEligible": True, "binding": "BOUND",
            "fixtureClass": "TEST_FIXTURE_ONLY", "files": {},
        })
        with self.assertRaises(ops.BoundaryViolation):
            ops.derive_candidate_status(
                _graph(), ledger,
                json.loads(_DECISION.read_text(encoding="utf-8")),
                json.loads(_P9_FINDINGS.read_text(encoding="utf-8")),
                json.loads(_P10_FINDINGS.read_text(encoding="utf-8")),
                json.loads(_STATUS.read_text(encoding="utf-8")))

    def test_dry_run_accepted_security_review(self) -> None:
        entry = self._register(
            "security-review", _fixture("security-review-accepted.json")["record"])
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])

    def test_dry_run_artifact_mismatch(self) -> None:
        entry = self._register(
            "security-review",
            _fixture("security-review-artifact-mismatch.json")["record"])
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        self.assertFalse(entry["gateEligible"])

    def test_dry_run_incomplete_approval(self) -> None:
        entry = self._register(
            "second-approval",
            _fixture("second-approval-incomplete.json")["record"])
        self.assertEqual(entry["status"], "INCOMPLETE")
        self.assertIn("recomputedDigest", entry["statusReason"])

    def test_dry_run_valid_signing_metadata(self) -> None:
        """Valid metadata is accepted in the scratch tree — and changes
        nothing real: the subject artifact remains UNSIGNED."""
        entry = self._register(
            "signing", _fixture("signing-metadata-valid.json")["record"])
        self.assertEqual(entry["status"], "ACCEPTED")
        real_ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))
        self.assertEqual(real_ledger["subjectArtifact"]["signingStatus"],
                         "UNSIGNED")
        self.assertEqual(real_ledger["entries"], [])

    def test_dry_run_hardware_failure(self) -> None:
        entry = self._register(
            "hardware", _fixture("hardware-failure.json")["record"])
        self.assertEqual(entry["status"], "ACCEPTED")
        results = _fixture("hardware-failure.json")["record"]["results"]
        self.assertEqual(results["voice-microphone"]["status"], "FAIL")
        self.assertEqual(results["boot-installation-media"]["status"], "PASS")

    def test_dry_run_tester_report(self) -> None:
        entry = self._register(
            "alpha-feedback", _fixture("alpha-tester-report.json")["record"])
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(entry["binding"], "BOUND")

    def test_dry_run_remediation_required_transition(self) -> None:
        finding = dict(_fixture("finding-remediation-required.json")["finding"])
        finding["state"] = ops.finding_transition(finding, "FIX_REQUIRED")
        self.assertEqual(finding["state"], "FIX_REQUIRED")
        self.assertEqual(
            ops.candidate_transition("UNDER_REVIEW", "REMEDIATION_REQUIRED"),
            "REMEDIATION_REQUIRED")
        with self.assertRaises(ops.BoundaryViolation):
            ops.candidate_transition("REMEDIATION_REQUIRED", "AUTHORIZED")


class WorkflowSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.committed = json.loads(_STATUS.read_text(encoding="utf-8"))
        cls.ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))
        cls.decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        cls.p9_findings = json.loads(_P9_FINDINGS.read_text(encoding="utf-8"))
        cls.p10_findings = json.loads(_P10_FINDINGS.read_text(encoding="utf-8"))

    def test_the_committed_status_reproduces_from_immutable_inputs(self) -> None:
        derived = ops.derive_candidate_status(
            _graph(), self.ledger, self.decision, self.p9_findings,
            self.p10_findings, self.committed)
        self.assertEqual(derived, self.committed,
                         "candidate-status.json does not reproduce; run sync "
                         "and review the diff")

    def test_sync_reads_the_ledger_and_never_writes_it(self) -> None:
        before = _LEDGER.read_bytes()
        derived, problems = ops.sync_status(write=False)
        self.assertEqual(problems, [])
        self.assertEqual(_LEDGER.read_bytes(), before)
        self.assertEqual(derived, self.committed)

    def test_the_status_carries_the_section11_fields(self) -> None:
        for field in ("candidate", "artifactDigest", "parentCandidate",
                      "currentState", "applicableEvidence", "openFindings",
                      "blockingConditions", "requiredQualification",
                      "completedQualification", "nextAction", "stateHistory"):
            self.assertIn(field, self.committed)

    def test_exactly_one_next_action(self) -> None:
        action = self.committed["nextAction"]
        self.assertIsInstance(action, str)
        self.assertTrue(action)
        self.assertIn("security review", action,
                      "with zero intakes, the review is the critical path")

    def test_the_blocking_conditions_are_the_precommitted_ten(self) -> None:
        self.assertEqual(self.committed["blockingConditions"],
                         self.decision["blocking_conditions"])

    def test_the_committed_history_is_legal_under_the_state_machine(self) -> None:
        history = [entry["state"] for entry in self.committed["stateHistory"]]
        self.assertEqual(history[0], "FROZEN",
                         "a candidate's history begins at its freeze")
        for current, target in zip(history, history[1:]):
            self.assertIn(target, ops.CANDIDATE_TRANSITIONS[current],
                          "%s -> %s is not a declared transition"
                          % (current, target))
        self.assertEqual(self.committed["currentState"], history[-1])

    def test_derivation_without_seeded_history_is_refused(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.derive_candidate_status(
                _graph(), self.ledger, self.decision, self.p9_findings,
                self.p10_findings, None)
        self.assertIn("state history", str(caught.exception))

    def test_two_live_candidates_need_an_operator(self) -> None:
        graph = _two_artifact_graph()
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.derive_candidate_status(
                graph, self.ledger, self.decision, self.p9_findings,
                self.p10_findings, self.committed)
        self.assertIn("exactly one active candidate", str(caught.exception))

    def test_a_fix_required_finding_takes_priority(self) -> None:
        registry = json.loads(json.dumps(self.p10_findings))
        registry["findings"].append({
            "findingId": "SEC-EXT-001", "state": "FIX_REQUIRED",
            "artifact": "e906a48793d7"})
        derived = ops.derive_candidate_status(
            _graph(), self.ledger, self.decision, self.p9_findings,
            registry, self.committed)
        self.assertTrue(derived["nextAction"].startswith("Remediate SEC-EXT-001"))
        self.assertEqual(len(derived["openFindings"]), 1)


if __name__ == "__main__":
    unittest.main()

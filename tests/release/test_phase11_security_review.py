# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The security review is commissionable, and the machinery cannot lie about it.

What Phase 11 built is tested the way Phases 9 and 10 are tested: the
commissioning package is complete and agrees with the intake boundary; the
finding baseline reproduces from the pinned Phase 8 package and refuses to
absorb a changed one; the submission contract is enforced from the committed
schema (which may not contain a keyword the validator ignores); dry-run
submissions flow through the *real* Phase 9 registration into constructed
scratch trees only; reconciliation classifies every difference; the finding
lifecycle cannot close anything without evidence bound to the right
artifact; reviewer conflicts are recorded fail-closed, never averaged; and
the derived register reproduces from its immutable inputs.

The real ledger participates in nothing here: tests compare its bytes
before and after, never its emptiness — the suite must stay green on the
day real evidence arrives.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_OPS11_TOOL = (_ROOT / "qualification" / "phase11" / "tools"
               / "security_review_ops.py")
_OPS10_TOOL = (_ROOT / "qualification" / "phase10" / "tools"
               / "candidate_ops.py")
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_PACKAGE_DIR = _ROOT / "qualification" / "phase11" / "security-review"
_FIXTURES = _ROOT / "qualification" / "phase11" / "fixtures"
_REGISTER = _ROOT / "qualification" / "phase11" / "security-findings.json"
_BASELINE = _PACKAGE_DIR / "FINDINGS_BASELINE.json"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
_GRAPH = (_ROOT / "qualification" / "phase10" / "artifacts"
          / "artifact-graph.json")

_IMAGE = "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops11 = _load("phase11_ops_under_test", _OPS11_TOOL)
ops10 = _load("phase10_ops_for_phase11_tests", _OPS10_TOOL)
intake = _load("phase9_intake_for_phase11_tests", _INTAKE_TOOL)


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _baseline() -> dict:
    return json.loads(_BASELINE.read_text(encoding="utf-8"))


def _graph() -> dict:
    return json.loads(_GRAPH.read_text(encoding="utf-8"))


def _valid_record() -> dict:
    return json.loads(json.dumps(
        _fixture("review-valid-independent.json")["record"]))


class CommissioningPackage(unittest.TestCase):
    def test_the_package_is_complete(self) -> None:
        for name in ops11.PACKAGE_FILES:
            self.assertTrue((_PACKAGE_DIR / name).is_file(),
                            "%s is missing from the commissioning package"
                            % name)

    def test_the_identity_agrees_with_the_intake_boundary(self) -> None:
        self.assertEqual(ops11._identity_problems(), [])

    def test_the_scope_is_frozen_with_the_eight_questions(self) -> None:
        self.assertEqual(ops11._scope_problems(), [])
        text = (_PACKAGE_DIR / "REVIEW_SCOPE.md").read_text(encoding="utf-8")
        self.assertIn("SCOPE-1", text)
        self.assertEqual(len(ops11.FROZEN_QUESTIONS), 8)

    def test_a_lost_question_would_be_caught(self) -> None:
        """The freeze check must actually read the committed document."""
        text = (_PACKAGE_DIR / "REVIEW_SCOPE.md").read_text(encoding="utf-8")
        for question in ops11.FROZEN_QUESTIONS:
            self.assertIn(question, text)

    def test_the_schema_uses_only_enforced_keywords(self) -> None:
        self.assertEqual(ops11._schema_problems(), [])

    def test_the_request_names_the_artifact_and_independent_verification(self) -> None:
        text = (_PACKAGE_DIR / "REQUEST.md").read_text(encoding="utf-8")
        self.assertIn("e906a48793d7", text)
        self.assertIn("independently verify", text.lower())
        self.assertIn("Do not trust this repository's claim", text)

    def test_the_baseline_reproduces_from_the_pinned_package(self) -> None:
        rebuilt, problems = ops11.baseline_from_disk()
        self.assertEqual(problems, [])
        self.assertEqual(rebuilt, _baseline(),
                         "FINDINGS_BASELINE.json does not reproduce; run "
                         "build-baseline and review the diff")

    def test_the_baseline_counts_are_the_committed_44(self) -> None:
        baseline = _baseline()
        rows = baseline["findings"]
        self.assertEqual(baseline["counts"], {"critical": 8, "high": 36})
        self.assertEqual(len(rows), 44)
        self.assertEqual([r["internal_id"] for r in rows],
                         ["SEC-BL-%03d" % i for i in range(1, 45)])
        for row in rows:
            self.assertTrue(ops11.BASELINE_ID.match(row["internal_id"]))

    def test_a_changed_package_is_refused_not_absorbed(self) -> None:
        package_bytes = ops11.PHASE8_PACKAGE.read_bytes()
        package = json.loads(package_bytes.decode("utf-8"))
        package["findings"] = package["findings"][1:]
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.build_baseline(package, "0" * 64)
        self.assertIn("not a silent replacement", str(caught.exception))

    def test_a_drifted_pin_is_reported(self) -> None:
        """A committed baseline pinning different Phase 8 bytes must fail
        closed rather than renumber."""
        scratch = Path(tempfile.mkdtemp(prefix="phase11-baseline-"))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        drifted = _baseline()
        drifted["sourcePackage"]["sha256"] = "0" * 64
        drifted_path = scratch / "FINDINGS_BASELINE.json"
        drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
        original = ops11.BASELINE_PATH
        ops11.BASELINE_PATH = drifted_path
        self.addCleanup(setattr, ops11, "BASELINE_PATH", original)
        _rebuilt, problems = ops11.baseline_from_disk()
        self.assertEqual(len(problems), 1)
        self.assertIn("historical evidence", problems[0])


class SubmissionContract(unittest.TestCase):
    def test_the_valid_fixture_record_satisfies_the_contract(self) -> None:
        self.assertEqual(ops11.validate_submission(_valid_record()), [])

    def test_the_wrapper_is_refused(self) -> None:
        problems = ops11.validate_submission(
            _fixture("review-valid-independent.json"))
        self.assertEqual(len(problems), 1)
        self.assertIn("a fixture is never evidence", problems[0])

    def test_a_missing_independent_digest_fails(self) -> None:
        record = _fixture("review-missing-independent-digest.json")["record"]
        problems = ops11.validate_submission(record)
        self.assertTrue(any("independently_computed_digest" in p
                            for p in problems), problems)

    def test_a_foreign_digest_names_blocking_condition_6(self) -> None:
        record = _fixture("review-artifact-mismatch.json")["record"]
        problems = ops11.validate_submission(record)
        self.assertTrue(any("blocking condition 6" in p for p in problems),
                        problems)

    def test_alias_disagreement_fails(self) -> None:
        record = _valid_record()
        record["disposition"] = "APPROVED"
        problems = ops11.validate_submission(record)
        self.assertTrue(any("disposition must equal overall_assessment" in p
                            for p in problems), problems)

    def test_an_unfrozen_scope_version_fails(self) -> None:
        record = _valid_record()
        record["review_scope_version"] = "SCOPE-0"
        problems = ops11.validate_submission(record)
        self.assertTrue(any("review_scope_version" in p for p in problems),
                        problems)

    def test_the_release_authority_overlap_requires_a_policy(self) -> None:
        record = _valid_record()
        record["independence"]["is_release_decision_authority"] = True
        problems = ops11.validate_submission(record)
        self.assertTrue(any("no such policy currently exists" in p
                            for p in problems), problems)

    def test_finding_fields_are_required(self) -> None:
        record = _valid_record()
        del record["findings"][0]["rationale"]
        problems = ops11.validate_submission(record)
        self.assertTrue(any("findings[0]" in p and "rationale" in p
                            for p in problems), problems)

    def test_duplicate_reviewer_finding_ids_fail(self) -> None:
        record = _valid_record()
        record["findings"][1]["reviewer_finding_id"] = \
            record["findings"][0]["reviewer_finding_id"]
        problems = ops11.validate_submission(record)
        self.assertTrue(any("duplicated" in p for p in problems), problems)

    def test_a_review_ending_before_it_started_fails(self) -> None:
        record = _valid_record()
        record["review_start"] = "2026-08-19"
        problems = ops11.validate_submission(record)
        self.assertTrue(any("postdates" in p for p in problems), problems)

    def test_an_invented_outcome_fails(self) -> None:
        record = _valid_record()
        record["overall_assessment"] = "PASSED"
        record["disposition"] = "PASSED"
        problems = ops11.validate_submission(record)
        self.assertTrue(any("overall_assessment" in p for p in problems),
                        problems)


class _ScratchIntake(unittest.TestCase):
    """A constructed Phase 9 tree; the real ledger never participates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.real_ledger_bytes = _LEDGER.read_bytes()
        cls.real_graph_bytes = _GRAPH.read_bytes()
        cls.real_register_bytes = _REGISTER.read_bytes()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phase11-dryrun-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.intake_root = self.tmp / "qualification" / "phase9" / "intake"
        for source in intake.SOURCES:
            (self.intake_root / source).mkdir(parents=True)
        real = json.loads(self.real_ledger_bytes.decode("utf-8"))
        self.ledger_path = self.intake_root / "LEDGER.json"
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

    def _register(self, payload: dict):
        record = self.staging / "record-src.json"
        record.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
        return intake.register(self.ledger_path, "security-review", record,
                               [], "2026-08-18", "dry-run fixture payload")

    def _derive(self) -> dict:
        return ops11.derive_register(
            _baseline(), intake.load_ledger(self.ledger_path), _graph(),
            self.intake_root)

    def _assert_reality_untouched(self) -> None:
        self.assertEqual(_LEDGER.read_bytes(), self.real_ledger_bytes,
                         "a dry run reached the real intake ledger")
        self.assertEqual(_GRAPH.read_bytes(), self.real_graph_bytes,
                         "a dry run reached the real artifact graph")
        self.assertEqual(_REGISTER.read_bytes(), self.real_register_bytes,
                         "a dry run reached the real finding register")


class ScratchIntakeDryRuns(_ScratchIntake):
    def test_a_valid_review_is_accepted_and_gate_eligible(self) -> None:
        entry = self._register(_valid_record())
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])
        self.assertEqual(entry["binding"], "BOUND")
        self._assert_reality_untouched()

    def test_an_artifact_mismatch_is_named_as_such(self) -> None:
        entry = self._register(
            _fixture("review-artifact-mismatch.json")["record"])
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        self.assertFalse(entry["gateEligible"])
        self._assert_reality_untouched()

    def test_the_wrapper_is_rejected_by_the_real_intake_code(self) -> None:
        entry = self._register(_fixture("review-valid-independent.json"))
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])
        self._assert_reality_untouched()

    def test_phase9_acceptance_is_not_contract_validity(self) -> None:
        """The layering the missing-digest fixture exists to prove: the
        intake (which does not know the field) accepts; the Phase 11
        contract holds the submission unusable until revised."""
        record = _fixture("review-missing-independent-digest.json")["record"]
        entry = self._register(record)
        self.assertEqual(entry["status"], "ACCEPTED")
        derived = self._derive()
        self.assertEqual(derived["counts"]["acceptedSubmissions"], 1)
        self.assertEqual(derived["counts"]["contractValidSubmissions"], 0)
        self.assertEqual(derived["securityGate"]["status"], "UNDER_ANALYSIS")
        self.assertIn("none satisfies the submission contract",
                      derived["securityGate"]["basis"])
        self._assert_reality_untouched()


class RegisterDerivation(_ScratchIntake):
    def test_the_committed_register_reproduces_from_its_inputs(self) -> None:
        derived, problems = ops11.sync_register(write=False)
        self.assertEqual(problems, [])
        self.assertEqual(
            derived, json.loads(self.real_register_bytes.decode("utf-8")),
            "security-findings.json does not reproduce; run sync and review "
            "the diff")

    def test_zero_evidence_derives_awaiting_never_approved(self) -> None:
        derived = self._derive()
        self.assertEqual(derived["securityGate"]["status"],
                         "AWAITING_EXTERNAL_EVIDENCE")
        self.assertIn("absence blocks", derived["securityGate"]["basis"])
        self.assertEqual(derived["counts"]["baseline"], 44)

    def test_a_confirming_review_overlays_the_baseline(self) -> None:
        self._register(_valid_record())
        derived = self._derive()
        rows = {r["source_finding_id"]: r for r in derived["findings"]}
        confirmed = rows["GHSA-5cgq-3rg8-m6cv"]
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(confirmed["applicability"], "APPLICABLE")
        self.assertEqual(confirmed["source_evidence_id"], "INTAKE-001")
        cleared = rows["GO-2026-6180"]
        self.assertEqual(cleared["status"], "NOT_APPLICABLE")
        self.assertTrue(cleared["applicability_evidence"]["reference"])
        self.assertEqual(derived["securityGate"]["status"], "UNDER_ANALYSIS",
                         "a confirmed Critical without a disposition cannot "
                         "satisfy the gate")
        self._assert_reality_untouched()

    def test_a_new_critical_enters_untriaged_and_blocks(self) -> None:
        self._register(_fixture("review-new-critical.json")["record"])
        derived = self._derive()
        self.assertEqual(derived["counts"]["fromEvidence"], 1)
        new_row = derived["findings"][-1]
        self.assertEqual(new_row["reconciliation"], "NEW_FINDING")
        self.assertIsNone(new_row["internal_id"],
                          "the register never mints triage identifiers")
        self.assertEqual(derived["securityGate"]["status"], "BLOCKED")

    def test_an_undetermined_answer_is_held_not_closed(self) -> None:
        self._register(
            _fixture("review-baseline-not-applicable.json")["record"])
        derived = self._derive()
        rows = {r["source_finding_id"]: r for r in derived["findings"]}
        self.assertEqual(rows["CVE-2026-11822"]["status"], "NOT_APPLICABLE")
        held = rows["CVE-2020-27815"]
        self.assertEqual(held["status"], "UNDER_REVIEW")
        self.assertEqual(held["reconciliation"], "REQUIRES_FURTHER_ANALYSIS")

    def test_conflicting_reviews_are_recorded_fail_closed(self) -> None:
        for record in _fixture("review-conflicting-conclusions.json")["records"]:
            self._register(record)
        derived = self._derive()
        conflict = derived["reviewConflict"]
        self.assertEqual(conflict["classification"],
                         "CONTRADICTORY_CONCLUSIONS")
        self.assertEqual(conflict["effectiveAssessment"], "BLOCKED")
        self.assertEqual(conflict["resolution"], "RESOLUTION_REQUIRED")
        rows = {r["source_finding_id"]: r for r in derived["findings"]}
        contested = rows["GHSA-p77j-4mvh-x3m3"]
        self.assertEqual(contested["reconciliation"], "EVIDENCE_CONFLICT")
        self.assertEqual(contested["status"], "UNDER_REVIEW")
        self.assertEqual(derived["securityGate"]["status"], "BLOCKED")
        self.assertIn("most blocking", derived["securityGate"]["basis"])

    def test_a_no_remediation_review_satisfies_without_a_rebuild(self) -> None:
        self._register(_fixture("review-no-remediation.json")["record"])
        derived = self._derive()
        self.assertEqual(derived["securityGate"]["status"], "SATISFIED")
        criticals = [r for r in derived["findings"]
                     if r["severity"] == "Critical"]
        self.assertEqual({r["status"] for r in criticals},
                         {"NOT_APPLICABLE"})
        self.assertEqual(derived["subjectArtifact"], "e906a48793d7",
                         "no rebuild merely to celebrate a PASS")
        self._assert_reality_untouched()

    def test_a_fixture_marked_ledger_entry_is_refused(self) -> None:
        ledger = intake.load_ledger(self.ledger_path)
        ledger["entries"].append({
            "intakeId": "INTAKE-001", "revises": None,
            "source": "security-review", "status": "ACCEPTED",
            "gateEligible": True, "binding": "BOUND",
            "fixtureClass": "TEST_FIXTURE_ONLY", "files": {},
        })
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.derive_register(_baseline(), ledger, _graph(),
                                  self.intake_root)

    def test_the_gate_cannot_be_satisfied_without_evidence(self) -> None:
        gate = ops11.derive_security_gate([], [], None)
        self.assertEqual(gate["status"], "AWAITING_EXTERNAL_EVIDENCE")
        only_invalid = [{"intakeId": "INTAKE-001", "record": {},
                         "contractProblems": ["missing everything"]}]
        gate = ops11.derive_security_gate(only_invalid, [], None)
        self.assertEqual(gate["status"], "UNDER_ANALYSIS")

    def test_a_successor_candidate_does_not_inherit_the_review(self) -> None:
        graph = _graph()
        graph["artifacts"][0]["qualification_state"] = "SUPERSEDED"
        successor = _fixture("approval-transfer-to-successor.json")[
            "successorEntry"]
        graph["artifacts"].append(successor)
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.derive_register(_baseline(),
                                  intake.load_ledger(self.ledger_path),
                                  graph, self.intake_root)
        self.assertIn("does not inherit", str(caught.exception))


class FindingLifecycle(unittest.TestCase):
    def test_the_vocabulary_is_the_nine(self) -> None:
        self.assertEqual(len(ops11.SECURITY_FINDING_STATES), 9)
        register = json.loads(_REGISTER.read_text(encoding="utf-8"))
        self.assertEqual(register["stateVocabulary"],
                         list(ops11.SECURITY_FINDING_STATES))

    def test_confirmed_to_closed_does_not_exist(self) -> None:
        self.assertNotIn(
            "CLOSED", ops11.SECURITY_FINDING_TRANSITIONS["CONFIRMED"])
        finding = dict(_fixture("finding-close-without-evidence.json")["finding"])
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(finding, "CLOSED", {
                "closureEvidence": {"reference": "anything",
                                    "artifact": "e906a48793d7"}})
        self.assertIn("not allowed", str(caught.exception))

    def test_every_undeclared_transition_is_refused(self) -> None:
        for current in ops11.SECURITY_FINDING_STATES:
            for target in ops11.SECURITY_FINDING_STATES:
                if target in ops11.SECURITY_FINDING_TRANSITIONS[current]:
                    continue
                with self.assertRaises(ops11.BoundaryViolation,
                                       msg="%s -> %s" % (current, target)):
                    ops11.security_finding_transition({"status": current},
                                                      target)

    def test_the_remediation_walk_closes_only_on_bound_evidence(self) -> None:
        finding = dict(_fixture("finding-close-without-evidence.json")["finding"])
        finding["status"] = ops11.security_finding_transition(
            finding, "REMEDIATION_REQUIRED")
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(
                finding, "FIXED_PENDING_REQUALIFICATION")
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(
                finding, "FIXED_PENDING_REQUALIFICATION",
                {"remediationArtifact": finding["artifact"]})
        self.assertIn("never modified", str(caught.exception))
        finding["status"] = ops11.security_finding_transition(
            finding, "FIXED_PENDING_REQUALIFICATION",
            {"remediationArtifact": "fixture-successor-security"})
        finding["remediation_artifact"] = "fixture-successor-security"
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(finding, "CLOSED")
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(finding, "CLOSED", {
                "closureEvidence": {"reference": "requal-run-1",
                                    "artifact": "e906a48793d7"}})
        self.assertIn("does not transfer", str(caught.exception))
        finding["status"] = ops11.security_finding_transition(finding, "CLOSED", {
            "closureEvidence": {"reference": "requal-run-1",
                                "artifact": "fixture-successor-security"}})
        self.assertEqual(finding["status"], "CLOSED")

    def test_an_accepted_risk_requires_the_full_record(self) -> None:
        finding = dict(_fixture("finding-close-without-evidence.json")["finding"])
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(finding, "ACCEPTED_RISK")
        self.assertIn("no silent acceptance", str(caught.exception))
        acceptance = {
            "decisionAuthority": "constructed control authority",
            "rationale": "constructed control rationale",
            "affectedArtifact": "e906a48793d7",
            "alphaScopeImpact": "constructed control impact statement",
            "reviewBy": "2026-12-01",
        }
        partial = {k: v for k, v in acceptance.items() if k != "reviewBy"}
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(finding, "ACCEPTED_RISK",
                                              {"acceptance": partial})
        self.assertIn("reviewBy", str(caught.exception))
        finding["status"] = ops11.security_finding_transition(
            finding, "ACCEPTED_RISK", {"acceptance": acceptance})
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(finding, "CLOSED", {
                "closureEvidence": {"reference": "decision-record",
                                    "artifact": "e906a48793d7"}})
        finding["status"] = ops11.security_finding_transition(finding, "CLOSED", {
            "closureEvidence": {"reference": "decision-record",
                                "artifact": "e906a48793d7"},
            "acceptance": acceptance})
        self.assertEqual(finding["status"], "CLOSED")

    def test_not_applicable_requires_establishing_evidence(self) -> None:
        finding = {"status": "BASELINE", "artifact": "e906a48793d7",
                   "severity": "High"}
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(finding, "UNDER_REVIEW")
        finding["status"] = ops11.security_finding_transition(
            finding, "UNDER_REVIEW", {"sourceEvidence": "INTAKE-001"})
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(finding, "NOT_APPLICABLE")
        self.assertIn("not sufficient", str(caught.exception))
        finding["status"] = ops11.security_finding_transition(
            finding, "NOT_APPLICABLE",
            {"applicabilityEvidence": {"reference": "INTAKE-001",
                                       "analysis": "symbol absent"}})
        self.assertEqual(finding["status"], "NOT_APPLICABLE")

    def test_an_unestablished_conclusion_reconciles_to_held(self) -> None:
        record = {"findings": [{
            "reviewer_finding_id": "X-1",
            "baseline_advisory": "CVE-2026-11822",
            "severity": "High", "affected_component": "sqlite-libs",
            "applicability": "NOT_APPLICABLE",
            "evidence": "   ", "rationale": "not exploitable",
        }]}
        result = ops11.reconcile_submission(record, _baseline())
        self.assertEqual(result["classifications"][0]["classification"],
                         "REQUIRES_FURTHER_ANALYSIS")

    def test_register_row_invariants_fire(self) -> None:
        base = {"internal_id": "SEC-BL-999", "artifact": "e906a48793d7",
                "severity": "Critical"}
        cases = [
            (dict(base, status="CLOSED", closure_evidence=None),
             "without closure evidence"),
            (dict(base, status="ACCEPTED_RISK", source_evidence_id="I-1"),
             "ACCEPTED_RISK missing"),
            (dict(base, status="NOT_APPLICABLE", source_evidence_id="I-1"),
             "not sufficient"),
            (dict(base, status="UNDER_REVIEW"), "names none"),
            (dict(base, status="CONFIRMED", source_evidence_id="I-1",
                  disposition="WAIVED"), "not a Critical disposition"),
            (dict(base, status="FIXED_PENDING_REQUALIFICATION",
                  source_evidence_id="I-1",
                  remediation_artifact="e906a48793d7"),
             "the frozen artifact itself"),
        ]
        for row, expected in cases:
            issues = ops11.validate_register_row(row)
            self.assertTrue(any(expected in issue for issue in issues),
                            "%s: %s" % (expected, issues))

    def test_critical_disposition_gaps_are_the_work_queue(self) -> None:
        rows = [
            {"internal_id": "SEC-BL-001", "severity": "Critical",
             "status": "CONFIRMED", "disposition": None},
            {"internal_id": "SEC-BL-002", "severity": "Critical",
             "status": "CONFIRMED", "disposition": "FIX_BEFORE_ALPHA"},
            {"internal_id": "SEC-BL-009", "severity": "High",
             "status": "CONFIRMED", "disposition": None},
        ]
        self.assertEqual(ops11.critical_disposition_gaps(rows), ["SEC-BL-001"])


class RemediationPath(unittest.TestCase):
    def test_the_modelled_successor_is_well_formed(self) -> None:
        successor = _fixture("review-remediation-required.json")[
            "successorEntry"]
        self.assertEqual(
            ops11.validate_successor_entry(successor, "e906a48793d7"), [])

    def test_a_successor_born_qualified_is_refused(self) -> None:
        successor = dict(_fixture("review-remediation-required.json")[
            "successorEntry"])
        successor["qualification_state"] = "ALPHA_READY"
        issues = ops11.validate_successor_entry(successor, "e906a48793d7")
        self.assertTrue(any("inherits no PASS" in issue for issue in issues))

    def test_a_successor_with_the_wrong_parent_is_refused(self) -> None:
        successor = dict(_fixture("review-remediation-required.json")[
            "successorEntry"])
        successor["parent_artifact"] = "something-else"
        issues = ops11.validate_successor_entry(successor, "e906a48793d7")
        self.assertTrue(any("parent" in issue for issue in issues))

    def test_the_requalification_plan_keeps_security_required(self) -> None:
        mapping = json.loads(
            (_ROOT / "qualification" / "phase10" / "impact"
             / "component-domains.json").read_text(encoding="utf-8"))
        impact = ops10.build_impact(
            "e906a48793d7", "fixture-successor-security",
            ["companion/core/runtime.py"], mapping)
        plan = ops10.plan_requalification(impact)
        self.assertEqual(ops11.validate_security_requalification_plan(plan), [])
        weakened = json.loads(json.dumps(plan))
        weakened["SECURITY"] = {"status": "NOT_REQUIRED",
                                "reason": "constructed control weakening"}
        issues = ops11.validate_security_requalification_plan(weakened)
        self.assertTrue(any("SECURITY must be REQUIRED" in issue
                            for issue in issues))
        smuggled = json.loads(json.dumps(plan))
        smuggled["SECURITY"] = {"status": "PASS", "reason": "constructed"}
        issues = ops11.validate_security_requalification_plan(smuggled)
        self.assertTrue(any("PASS" in issue or "planner" in issue
                            for issue in issues))

    def test_the_requirements_list_is_the_committed_six(self) -> None:
        self.assertEqual(len(ops11.SECURITY_REQUALIFICATION_REQUIREMENTS), 6)
        self.assertIn("security rescan",
                      ops11.SECURITY_REQUALIFICATION_REQUIREMENTS)

    def test_a_root_review_does_not_apply_to_the_successor(self) -> None:
        fixture = _fixture("approval-transfer-to-successor.json")
        graph = _graph()
        graph["artifacts"].append(fixture["successorEntry"])
        verdict = ops10.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _IMAGE,
             "scope": "security-review"},
            "fixture-successor-security", graph)
        self.assertEqual(verdict["result"], "DOES_NOT_APPLY")
        self.assertIn("default is no transfer", verdict["reasoning"])


class ConflictClassification(unittest.TestCase):
    def test_identical_assessments_are_no_conflict(self) -> None:
        self.assertIsNone(ops11.classify_conflict(
            [("INTAKE-001", "APPROVED"), ("INTAKE-002", "APPROVED")]))
        self.assertIsNone(ops11.classify_conflict(
            [("INTAKE-001", "BLOCKED")]))

    def test_contradictory_conclusions_fail_closed(self) -> None:
        conflict = ops11.classify_conflict(
            [("INTAKE-001", "APPROVED"), ("INTAKE-002", "BLOCKED")])
        self.assertEqual(conflict["classification"],
                         "CONTRADICTORY_CONCLUSIONS")
        self.assertEqual(conflict["effectiveAssessment"], "BLOCKED")
        self.assertEqual(conflict["resolution"], "RESOLUTION_REQUIRED")
        self.assertIn("never selects the favorable interpretation",
                      conflict["note"])

    def test_divergent_assessments_take_the_most_blocking(self) -> None:
        conflict = ops11.classify_conflict(
            [("INTAKE-001", "APPROVED"),
             ("INTAKE-002", "MORE_EVIDENCE_REQUIRED")])
        self.assertEqual(conflict["classification"], "DIVERGENT_ASSESSMENTS")
        self.assertEqual(conflict["effectiveAssessment"],
                         "MORE_EVIDENCE_REQUIRED")

    def test_the_resolution_vocabulary_is_closed(self) -> None:
        for outcome in ops11.CONFLICT_OUTCOMES:
            self.assertEqual(
                ops11.validate_conflict_resolution(outcome), outcome)
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.validate_conflict_resolution("MOST_FAVORABLE")

    def test_an_invented_assessment_is_refused(self) -> None:
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.classify_conflict([("INTAKE-001", "PASSED"),
                                     ("INTAKE-002", "BLOCKED")])


class FixtureDiscipline(unittest.TestCase):
    def test_every_fixture_is_structurally_marked(self) -> None:
        self.assertEqual(ops11.verify_fixtures(), [])
        names = sorted(p.name for p in _FIXTURES.glob("*.json"))
        self.assertEqual(len(names), 10, names)
        for name in names:
            self.assertEqual(_fixture(name)["fixtureClass"],
                             "TEST_FIXTURE_ONLY", name)

    def test_the_verify_command_is_clean(self) -> None:
        self.assertEqual(ops11.verify_all(), [])


if __name__ == "__main__":
    unittest.main()

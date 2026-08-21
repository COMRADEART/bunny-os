# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 16 reconciliation, cuts, assembly, matrices, and verifier guards.

The tests drive Phases 9-15 through the Phase 16 composition surface. Favorable
states exist only in isolated TEST_FIXTURE_ONLY universes; every real input is
byte-compared, and the current-real-universe assertions are derivations rather
than an assumption that the ledger is empty.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_PHASE16 = _ROOT / "qualification" / "phase16"
_OPS16_TOOL = _PHASE16 / "tools" / "security_review_intake_ops.py"
_VERIFY16 = _PHASE16 / "tools" / "verify_phase16.py"
_FIXTURES = _PHASE16 / "fixtures"
_FIXTURES13 = _ROOT / "qualification" / "phase13" / "fixtures"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops16 = _load("phase16_gate_ops_under_test", _OPS16_TOOL)
intake = ops16._phase9()
ops10 = ops16._phase10()
ops11 = ops16._phase11()
ops13 = ops16._phase13()
ops14 = ops16._phase14()
ops15 = ops16._phase15()

_BASELINE = ops16.load_json(ops16.PHASE11_BASELINE)
_GRAPH = ops16.load_json(ops16.PHASE10_GRAPH)


def _inner(name: str = "review-valid.json") -> dict:
    return copy.deepcopy(ops16.load_json(_FIXTURES / name)["record"])


def _wrapper(name: str = "review-valid.json") -> dict:
    return ops16.load_json(_FIXTURES / name)


class _Scratch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        guarded = list(ops14.REAL_IMMUTABLE_INPUTS)
        for path in (ops16.PHASE15_STATUS, ops16.PHASE15_MATRIX,
                     ops16.STATUS_PATH, ops16.MATRIX_PATH,
                     ops16.RECOVERY_PATH, ops16.PINS_PATH):
            if path.is_file() and path not in guarded:
                guarded.append(path)
        if ops16.PHASE15_CUTS.is_dir():
            guarded.extend(path for path in sorted(
                ops16.PHASE15_CUTS.glob("*.json")) if path not in guarded)
        cls.real_bytes = {path: path.read_bytes() for path in guarded}

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_bytes.items():
            if not path.is_file() or path.read_bytes() != raw:
                raise AssertionError(
                    "%s changed during Phase 16 gate tests" % path.name)

    def _space(self):
        base = Path(tempfile.mkdtemp(prefix="phase16-gate-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)

    def _register(self, space) -> dict:
        return ops11.derive_register(_BASELINE, space.ledger(), _GRAPH,
                                     space.intake_root)

    def _cut(self, space, **overrides) -> dict:
        kwargs = dict(
            ledger_bytes=space.ledger_bytes(),
            graph_bytes=ops16.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")
        kwargs.update(overrides)
        return ops14.build_evidence_cut(**kwargs)


class SecurityReviewReconciliation(_Scratch):
    def test_no_new_findings_does_not_close_the_baseline(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"] = []
        record["overall_assessment"] = record["disposition"] = "APPROVED"
        space.register("security-review", record)
        register = self._register(space)
        self.assertEqual(register["counts"]["fromEvidence"], 0)
        self.assertEqual(sum(row["status"] == "BASELINE"
                             for row in register["findings"]), 44)
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")

    def test_baseline_reassessment_maps_by_public_advisory(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        register = self._register(space)
        row = next(row for row in register["findings"]
                   if row["source_finding_id"] ==
                   "GHSA-5cgq-3rg8-m6cv")
        self.assertEqual(row["reconciliation"], "CONFIRMED")
        self.assertEqual(row["source_evidence_id"], "INTAKE-001")

    def test_new_critical_under_approving_assessment_is_first_class(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-new-critical.json"))
        register = self._register(space)
        rows = [row for row in register["findings"]
                if row.get("reconciliation") == "NEW_FINDING"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["internal_id"])
        self.assertEqual(rows[0]["source_finding_id"], "P16-C-NEW-1")
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")
        self.assertIn("P16-C-NEW-1", register["securityGate"]["basis"])

    def test_new_noncritical_under_review_cannot_satisfy_the_gate(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"] = [{
            "reviewer_finding_id": "P16-NEW-MEDIUM",
            "title": "constructed new medium finding",
            "severity": "Medium",
            "affected_component": "bunny-helper",
            "applicability": "APPLICABLE",
            "evidence": "constructed scenario: reachable behavior observed",
            "rationale": "constructed scenario: behavior crosses a trust boundary",
            "recommended_disposition": "FIX_IN_LATER_RELEASE",
            "baseline_advisory": None,
        }]
        record["overall_assessment"] = record["disposition"] = "APPROVED"
        space.register("security-review", record)
        register = self._register(space)
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")
        self.assertIn("P16-NEW-MEDIUM",
                      register["securityGate"]["basis"])

    def test_unresolved_baseline_evidence_stays_unresolved(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"][0]["applicability"] = "UNDETERMINED"
        record["findings"][0]["recommended_disposition"] = \
            "NO_CHANGE_REQUIRED"
        record["overall_assessment"] = record["disposition"] = "APPROVED"
        space.register("security-review", record)
        register = self._register(space)
        row = next(row for row in register["findings"]
                   if row["source_finding_id"] ==
                   "GHSA-5cgq-3rg8-m6cv")
        self.assertEqual(row["reconciliation"],
                         "REQUIRES_FURTHER_ANALYSIS")
        self.assertEqual(row["status"], "UNDER_REVIEW")
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")

    def test_blocked_assessment_with_no_findings_stays_blocked(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register(space)
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")

    def test_more_evidence_required_stays_under_analysis(self) -> None:
        space = self._space()
        record = _inner("review-blocked.json")
        record["overall_assessment"] = record["disposition"] = \
            "MORE_EVIDENCE_REQUIRED"
        space.register("security-review", record)
        self.assertEqual(self._register(space)["securityGate"]["status"],
                         "UNDER_ANALYSIS")

    def test_contradictory_reviews_preserve_both_and_use_most_blocking(
            self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register(space)
        conflict = register["reviewConflict"]
        self.assertEqual(conflict["classification"],
                         "CONTRADICTORY_CONCLUSIONS")
        self.assertEqual(conflict["effectiveAssessment"], "BLOCKED")
        self.assertEqual(len(conflict["submissions"]), 2)
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")
        workflow = ops15.derive_receipt_register(
            space.ledger(), register, space.intake_root)
        self.assertEqual(workflow["overall"],
                         "CONFLICT_REQUIRES_DECISION")

    def test_duplicate_finding_identity_contributes_nothing(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"].append(copy.deepcopy(record["findings"][0]))
        entry = space.register("security-review", record)
        self.assertEqual(entry["status"], "ACCEPTED")
        register = self._register(space)
        submission = register["acceptedSubmissions"][0]
        self.assertTrue(any("duplicated" in p for p in
                            submission["contractProblems"]))
        self.assertEqual(register["counts"]["contractValidSubmissions"], 0)
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")

    def test_unmapped_reviewer_finding_is_preserved_not_guessed(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"][0]["baseline_advisory"] = \
            "CVE-CONSTRUCTED-NOT-IN-BASELINE"
        record["findings"][0]["severity"] = "High"
        record["findings"][0]["reviewer_finding_id"] = "P16-UNMAPPED"
        space.register("security-review", record)
        register = self._register(space)
        row = next(row for row in register["findings"]
                   if row.get("source_finding_id") == "P16-UNMAPPED")
        self.assertEqual(row["reconciliation"], "NEW_FINDING")
        self.assertIsNone(row["internal_id"])

    def test_baseline_silence_never_becomes_a_disposition(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        register = self._register(space)
        untouched = [row for row in register["findings"]
                     if row["status"] == "BASELINE"]
        self.assertEqual(len(untouched), 43)
        self.assertTrue(all(row["disposition"] is None for row in untouched))

    def test_reconciliation_is_reproducible(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        first = self._register(space)
        self.assertEqual(self._register(space), first)


class RiskAndAuthoritySemantics(_Scratch):
    def test_reviewer_risk_acceptance_prose_is_not_a_phase13_record(self) -> None:
        space = self._space()
        record = _inner()
        record["findings"][0]["recommended_disposition"] = "ACCEPTED_RISK"
        record["overall_assessment"] = record["disposition"] = "APPROVED"
        space.register("security-review", record)
        register = self._register(space)
        self.assertNotEqual(register["securityGate"]["status"], "SATISFIED")
        universe = ops14.build_universe(space, security_register=register)
        assembly = ops14.assemble_decision(universe, "2026-08-19")
        self.assertEqual(assembly["inputs"]["riskAcceptances"], [])

    def test_expired_risk_acceptance_cannot_sustain_favorability(self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        self.assertEqual(ops13.risk_acceptance_state(
            risk, risk["expires_at"]), "STANDING")
        self.assertEqual(ops13.risk_acceptance_state(
            risk, "2026-12-01"), "EXPIRED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.risk_acceptance_state(risk, None)

    def test_wrong_artifact_risk_acceptance_is_nontransferable(self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        risk["artifact_digest"] = "f" * 64
        result = ops13.risk_acceptance_applies(
            risk, intake.subject_digests(self._space().ledger()))
        self.assertEqual(result["result"], "REFUSED")
        self.assertIn("never transfers", result["reasoning"])

    def test_expired_and_revoked_assignment_states_use_the_cut(self) -> None:
        assignment = {
            "assignmentId": "ASSIGNMENT-916",
            "authorityId": "AUTH-SECURITY-OWNER",
            "identity": "Constructed Owner", "assignedBy": "fixture",
            "date": "2026-08-01", "basis": "fixture",
            "expires_at": "2026-08-31",
        }
        revocation = {
            "revocationId": "REVOCATION-916",
            "targetAssignment": "ASSIGNMENT-916",
            "reason": "fixture", "authority": "fixture",
            "timestamp": "2026-08-20",
        }
        self.assertEqual(ops14.assignment_state(
            assignment, "2026-08-19", [revocation]), "STANDING")
        self.assertEqual(ops14.assignment_state(
            assignment, "2026-08-20", [revocation]), "REVOKED")
        self.assertEqual(ops14.assignment_state(
            assignment, "2026-09-01", []), "EXPIRED")


class SealedEvidenceCuts(_Scratch):
    def test_same_inputs_and_as_of_derive_the_same_seal(self) -> None:
        space = self._space()
        self.assertEqual(self._cut(space), self._cut(space))

    def test_as_of_is_mandatory_once_an_expiring_record_exists(self) -> None:
        space = self._space()
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        risk["seal"] = ops13.seal_record(risk)
        with self.assertRaises(ops14.BoundaryViolation):
            self._cut(space, risks=[risk], as_of=None)

    def test_ambiguous_impossible_and_unparseable_cut_dates_refuse(self) -> None:
        space = self._space()
        for value in ("2026-08-19-latest", "2026-02-30", "latest"):
            with self.subTest(value=value), self.assertRaises(
                    ops14.BoundaryViolation):
                self._cut(space, as_of=value)

    def test_future_dated_record_and_ambiguous_record_dates_fail_closed(
            self) -> None:
        future = ops14.time_consistency_problems(
            record_dates={"date": "2026-08-20"},
            received_on="2026-08-19")
        self.assertTrue(any("postdates" in problem for problem in future))
        ambiguous = ops14.time_consistency_problems(
            record_dates={"date": "2026-08-18",
                          "review_end": "2026-08-19"},
            received_on="2026-08-19")
        self.assertTrue(any("ambiguous" in problem
                            for problem in ambiguous))

    def test_post_cut_evidence_is_excluded_and_named(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        frozen = space.ledger_bytes()
        cut = self._cut(space)
        space.register("security-review", _inner("review-blocked.json"))
        comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
        self.assertEqual(comparison["postCutIntakeIds"], ["INTAKE-002"])
        self.assertTrue(comparison["ledgerChanged"])
        replay = ops14.build_evidence_cut(
            ledger_bytes=frozen,
            graph_bytes=ops16.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")
        self.assertEqual(replay, cut)

    def test_cut_tampering_and_sealed_record_editing_fail(self) -> None:
        cut = self._cut(self._space())
        cut["ledgerEntries"] = 99
        self.assertTrue(any("seal" in problem or "IMMUTABILITY" in problem
                            for problem in ops14.verify_cut(cut)))
        record = {"risk_id": "RISK-916", "scope": "fixture"}
        record["seal"] = ops13.seal_record(record)
        record["scope"] = "edited"
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.sealed_records({"records": [record]}, "risk_id", "risks")
        self.assertIn("IMMUTABILITY FAIL", str(caught.exception))

    def test_resealed_ledger_still_differs_from_the_cut_pin(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        cut = self._cut(space)
        ledger = space.ledger()
        ledger["entries"][0]["statusReason"] = "quiet edit"
        ledger["entries"][0]["seal"] = intake.seal_entry(
            ledger["entries"][0])
        intake.dump_ledger(space.ledger_path, ledger)
        self.assertEqual(intake.verify_intake(space.intake_root,
                                              space.ledger()), {})
        comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
        self.assertTrue(comparison["ledgerChanged"])

    def test_same_cut_supersession_and_existing_label_refuse(self) -> None:
        cut = self._cut(self._space())
        assembly = {"evidenceCut": cut,
                    "authorizationState": "EVIDENCE_PENDING"}
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.supersede_assembly(assembly, copy.deepcopy(assembly))
        existing = ops16.load_json(ops16.PHASE15_CUTS / "CUT-001.json")
        with self.assertRaises(ValueError):
            ops16.write_cut(existing)

    def test_historical_authorization_reconstructs_before_revocation(
            self) -> None:
        space = self._space()
        universe, record = ops14.authorized_universe(space)
        earlier = ops14.assemble_decision(universe, "2026-08-19")
        revocation = {
            "revocation_id": "REVOCATION-001",
            "target_authorization": record["authorization_id"],
            "artifact_digest": record["artifact_digest"],
            "reason": "constructed later revocation",
            "authority": "Constructed Fixture Release Authority",
            "timestamp": "2026-09-01", "evidence": "constructed",
        }
        revocation["seal"] = ops13.seal_record(revocation)
        later = ops14.assemble_decision(
            dict(universe, revocations=[revocation]), "2026-09-02")
        replay = ops14.assemble_decision(universe, "2026-08-19")
        self.assertEqual(earlier["authorizationState"], "AUTHORIZED")
        self.assertEqual(later["authorizationState"], "REVOKED")
        self.assertEqual(replay, earlier)


class DecisionAssembly(_Scratch):
    def test_zero_evidence_scratch_universe_is_non_authorizing(self) -> None:
        assembly = ops14.assemble_decision(
            ops14.build_universe(self._space()), None)
        self.assertEqual(assembly["authorizationState"], "EVIDENCE_PENDING")
        self.assertEqual(assembly["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")

    def test_accepted_blocking_review_remains_non_authorized(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register(space)
        assembly = ops14.assemble_decision(
            ops14.build_universe(space, security_register=register),
            "2026-08-19")
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")
        self.assertNotEqual(assembly["authorizationState"], "AUTHORIZED")

    def test_favorable_security_gate_alone_names_the_missing_floor(self) -> None:
        space = self._space()
        space.register("security-review", ops16._all_criticals_review())
        register = self._register(space)
        self.assertEqual(register["securityGate"]["status"], "SATISFIED")
        assembly = ops14.assemble_decision(
            ops14.build_universe(space, security_register=register),
            "2026-08-19")
        self.assertEqual(assembly["authorizationState"],
                         "ALPHA_EVIDENCE_PENDING")
        missing = " ".join(
            assembly["inputs"]["authorizationFloor"]["missing"])
        for source in ("hardware", "signing", "second-approval",
                       "alpha-feedback"):
            self.assertIn(source, missing)

    def test_internal_authorized_json_is_refused_with_absent_floor(self) -> None:
        outcome = ops16._s21_internal_authorized_json(self._space())
        self.assertEqual(outcome["expected"], outcome["observed"])
        self.assertIn("absent floor named", outcome["observed"])

    def test_fixture_rejection_satisfies_no_authorization_floor(self) -> None:
        space = self._space()
        entry = space.register("security-review", _wrapper())
        self.assertEqual(entry["status"], "REJECTED")
        self.assertEqual(len(ops13.authorization_floor(space.ledger())), 5)

    def test_real_assembly_matches_the_committed_derived_state(self) -> None:
        committed = ops16.load_json(ops16.PHASE13_STATUS)
        assembly = ops14.assemble_decision(
            ops14.real_universe(), committed.get("evaluationDate"))
        self.assertEqual(assembly["authorizationState"],
                         committed["authorizationState"])
        self.assertEqual(assembly["candidateDecision"],
                         committed["candidateDecision"])


class DerivedViewsAndVerification(_Scratch):
    def test_status_reproduces_and_keeps_six_questions_separate(self) -> None:
        derived, problems = ops16.sync_status(write=False)
        self.assertEqual(problems, [])
        self.assertEqual(derived, ops16.load_json(ops16.STATUS_PATH))
        for key in ("operationalReadiness", "receipt",
                    "securityAssessment", "securityGate",
                    "authorization", "candidateDecision"):
            self.assertIn(key, derived)
        self.assertNotIn("overall", derived)
        self.assertEqual(derived["subjectArtifact"]["identifier"],
                         "e906a48793d7")
        self.assertEqual(derived["subjectArtifact"]["artifactState"],
                         "FROZEN")
        self.assertEqual(derived["subjectArtifact"]["graphRole"], "ROOT")
        self.assertEqual(derived["subjectArtifact"]["signingStatus"],
                         "UNSIGNED")

    def test_status_values_change_when_scratch_inputs_change(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register(space)
        derived = ops16.derive_intake_status(
            ledger_bytes=space.ledger_bytes(), security_register=register,
            phase10_status=ops16.load_json(ops16.PHASE10_STATUS),
            phase13_status=ops16.load_json(ops16.PHASE13_STATUS),
            graph=_GRAPH, matrix=None, cuts=[],
            intake_root=space.intake_root)
        self.assertEqual(derived["evidenceState"][
            "acceptedRealSecurityReviews"], 1)
        self.assertEqual(derived["receipt"]["boundary"]["overall"],
                         "ACCEPTED")
        self.assertEqual(derived["securityGate"]["status"], "BLOCKED")
        self.assertFalse(derived["operationalReadiness"]["intakePathReady"])

    def test_matrices_rederive_byte_identically_with_required_fields(
            self) -> None:
        self.assertEqual(ops16.matrix_problems(), [])
        matrix = ops16.load_json(ops16.MATRIX_PATH)
        recovery = ops16.load_json(ops16.RECOVERY_PATH)
        self.assertGreaterEqual(matrix["counts"]["scenarios"], 24)
        self.assertEqual(matrix["counts"]["asExpected"],
                         matrix["counts"]["scenarios"])
        required = {
            "scenario", "route", "evidenceClass",
            "artifactIdentityResult", "intakeResult", "bindingResult",
            "reconciliationResult", "securityGateEffect", "cutResult",
            "assemblyResult", "recoveryResult", "designation",
            "inputSha256",
        }
        for row in matrix["scenarios"]:
            self.assertEqual(required - set(row), set(), row["scenarioId"])
        self.assertFalse(recovery["rows"][0]["fixtureOnly"])
        self.assertTrue(all(row["fixtureOnly"]
                            for row in recovery["rows"][1:]))

    def test_current_real_row_is_derived_not_an_emptiness_assertion(self) -> None:
        source = _OPS16_TOOL.read_text(encoding="utf-8")
        self.assertNotIn("assert not ledger", source)
        self.assertNotIn("ledger == []", source)
        row = ops16.run_scenarios()["matrix"]["scenarios"][0]
        self.assertEqual(row["designation"], "REAL_UNIVERSE_READ_ONLY")
        self.assertEqual(row["result"], "AS_EXPECTED")

    def test_every_fixture_is_marked_and_real_intake_has_none(self) -> None:
        self.assertEqual(ops16.verify_fixtures(), [])
        for path in sorted(_FIXTURES.glob("*.json")):
            record = ops16.load_json(path)
            self.assertEqual(record["fixtureClass"],
                             "TEST_FIXTURE_ONLY")
            self.assertIs(record["fixture"], True)
            self.assertIs(record["test_fixture_only"], True)
            self.assertFalse(ops16.is_fixture(record["record"]))

    def test_verifier_and_all_composed_boundaries_are_clean(self) -> None:
        self.assertEqual(ops16.verify_all(), [])
        result = subprocess.run(
            [sys.executable, str(_VERIFY16)], cwd=str(_ROOT),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)
        self.assertIn("phase 16 verifies clean", result.stdout)

    def test_no_phase16_source_reads_a_wall_clock(self) -> None:
        self.assertEqual(ops16.engine_boundary_problems(), [])
        for path in (_OPS16_TOOL, _VERIFY16):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            calls = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Attribute):
                    owner = function.value
                    if isinstance(owner, ast.Name):
                        calls.append("%s.%s" % (owner.id, function.attr))
                elif isinstance(function, ast.Name):
                    calls.append(function.id)
            self.assertTrue(
                {"datetime.now", "date.today", "time.time", "utcnow"}
                .isdisjoint(calls),
                "%s reads a wall clock through %r" % (path.name, calls))

    def test_phase16_is_not_inside_a_product_copy_root(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "*Containerfile*", "*Dockerfile*"],
            cwd=str(_ROOT), capture_output=True, text=True, check=True)
        for relative in tracked.stdout.splitlines():
            path = _ROOT / relative
            for line in path.read_text(
                    encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith(("COPY ", "ADD ")):
                    self.assertNotIn("qualification", stripped,
                                     "%s ships Phase 16 via %s" %
                                     (path, stripped))

    def test_both_phase16_modules_are_in_release_discovery(self) -> None:
        loader = unittest.TestLoader()
        suite = loader.discover(str(_ROOT / "tests" / "release"),
                                top_level_dir=str(_ROOT))
        self.assertEqual(loader.errors, [])
        names = set()

        def walk(item):
            if isinstance(item, unittest.TestSuite):
                for child in item:
                    walk(child)
            else:
                names.add(type(item).__module__)

        walk(suite)
        self.assertIn("tests.release.test_phase16_intake_operations", names)
        self.assertIn("tests.release.test_phase16_gate_execution", names)
        self.assertGreater(suite.countTestCases(), 639)


if __name__ == "__main__":
    unittest.main()

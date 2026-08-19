# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The four external workstreams and the decision assembler, rehearsed.

Every scenario here exercises the real machinery — the Phase 9
registration code, the Phase 11 contract and reconciler, the Phase 12
register derivation, the Phase 13 validators and ladder — inside
scratch universes over TEST_FIXTURE_ONLY records. A fixture universe
can reach AUTHORIZED when every mechanical requirement is genuinely
satisfied, and that is a statement about the machinery: the real
candidate assembles to EVIDENCE_PENDING / REQUIRES_MORE_EVIDENCE on the
same code path, in the same run, and every real input is byte-compared
before and after — never asserted empty.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_OPS14_TOOL = (_ROOT / "qualification" / "phase14" / "tools"
               / "evidence_execution_ops.py")
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_OPS11_TOOL = (_ROOT / "qualification" / "phase11" / "tools"
               / "security_review_ops.py")
_OPS12_TOOL = _ROOT / "qualification" / "phase12" / "tools" / "alpha_ops.py"
_OPS13_TOOL = (_ROOT / "qualification" / "phase13" / "tools"
               / "release_authority_ops.py")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops14 = _load("phase14_rehearsal_under_test", _OPS14_TOOL)
intake = _load("phase9_intake_for_rehearsal_tests", _INTAKE_TOOL)
ops11 = _load("phase11_ops_for_rehearsal_tests", _OPS11_TOOL)
ops12 = _load("phase12_ops_for_rehearsal_tests", _OPS12_TOOL)
ops13 = _load("phase13_ops_for_rehearsal_tests", _OPS13_TOOL)

_GRAPH = json.loads(ops14.PHASE10_GRAPH.read_text(encoding="utf-8"))
_BASELINE = json.loads(ops14.PHASE11_BASELINE.read_text(encoding="utf-8"))
_ALPHA_POLICY = json.loads(ops14.PHASE12_POLICY.read_text(encoding="utf-8"))


def _subject() -> set[str]:
    return intake.subject_digests(
        json.loads(ops14.PHASE9_LEDGER.read_text(encoding="utf-8")))


class _Scratch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_bytes = {path: path.read_bytes()
                          for path in ops14.REAL_IMMUTABLE_INPUTS}

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_bytes.items():
            if path.read_bytes() != raw:
                raise AssertionError(
                    "%s changed during the rehearsals; a dry run must "
                    "leave every real input byte-identical" % path.name)

    def _space(self) -> "ops14.RehearsalSpace":
        base = Path(tempfile.mkdtemp(prefix="phase14-rehearsal-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)

    def _alpha_register_for(self, space, dedup=None, repro=None,
                            policy=None):
        return ops12.derive_register(
            space.ledger(), _GRAPH, dedup or {"decisions": []},
            repro or {"attempts": []}, policy or _ALPHA_POLICY,
            space.intake_root)

    def _security_register_for(self, space):
        return ops11.derive_register(_BASELINE, space.ledger(), _GRAPH,
                                     space.intake_root)


class SecurityReviewRehearsal(_Scratch):
    def test_a_valid_review_is_accepted_and_gate_eligible(self) -> None:
        space = self._space()
        entry = space.register("security-review", ops14._inner(
            "review-valid-independent.json", ops14.FIXTURES11))
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])
        self.assertEqual(ops11.validate_submission(ops14._inner(
            "review-valid-independent.json", ops14.FIXTURES11)), [])

    def test_reconciliation_classifies_against_the_baseline(self) -> None:
        reconciliation = ops11.reconcile_submission(
            ops14._inner("review-valid-independent.json",
                         ops14.FIXTURES11), _BASELINE)
        classes = {c["reviewer_finding_id"]: c["classification"]
                   for c in reconciliation["classifications"]}
        self.assertEqual(classes["R1-F1"], "CONFIRMED")
        self.assertEqual(classes["R1-F2"], "NOT_APPLICABLE")
        self.assertEqual(len(reconciliation["unaddressedBaseline"]), 42)

    def test_an_accepted_review_does_not_satisfy_the_gate_alone(
            self) -> None:
        space = self._space()
        space.register("security-review", ops14._inner(
            "review-valid-independent.json", ops14.FIXTURES11))
        register = self._security_register_for(space)
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")
        self.assertIn("lack an accepted disposition",
                      register["securityGate"]["basis"])

    def test_a_review_bound_to_the_wrong_artifact(self) -> None:
        space = self._space()
        entry = space.register("security-review", ops14._inner(
            "review-artifact-mismatch.json", ops14.FIXTURES11))
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        self.assertFalse(entry["gateEligible"])

    def test_a_missing_independent_digest_contributes_nothing(
            self) -> None:
        space = self._space()
        record = ops14._inner("review-missing-independent-digest.json",
                              ops14.FIXTURES11)
        entry = space.register("security-review", record)
        self.assertEqual(entry["status"], "ACCEPTED")
        problems = ops11.validate_submission(record)
        self.assertTrue(any("independently_computed_digest" in p
                            for p in problems), problems)
        register = self._security_register_for(space)
        self.assertEqual(register["counts"]["contractValidSubmissions"], 0)
        self.assertEqual(register["securityGate"]["status"],
                         "UNDER_ANALYSIS")

    def test_a_new_finding_beyond_the_baseline(self) -> None:
        space = self._space()
        space.register("security-review", ops14._inner(
            "review-new-critical.json", ops14.FIXTURES11))
        register = self._security_register_for(space)
        new_rows = [r for r in register["findings"]
                    if r.get("reconciliation") == "NEW_FINDING"]
        self.assertEqual(len(new_rows), 1)
        self.assertIsNone(new_rows[0]["internal_id"])
        self.assertEqual(register["counts"]["fromEvidence"], 1)

    def test_conflicting_reviewers_block_pending_resolution(self) -> None:
        space = self._space()
        for record in ops14._fixture("review-conflicting-conclusions.json",
                                     ops14.FIXTURES11)["records"]:
            space.register("security-review", copy.deepcopy(record))
        register = self._security_register_for(space)
        conflict = register["reviewConflict"]
        self.assertEqual(conflict["classification"],
                         "CONTRADICTORY_CONCLUSIONS")
        self.assertEqual(conflict["effectiveAssessment"], "BLOCKED")
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")
        self.assertEqual(len(register["acceptedSubmissions"]), 2)

    def test_a_revision_supersedes_derivationally(self) -> None:
        space = self._space()
        space.register("security-review", ops14._inner(
            "review-valid-independent.json", ops14.FIXTURES11))
        revised = ops14._inner("review-valid-independent.json",
                               ops14.FIXTURES11)
        revised["scope"] += " (revised)"
        space.register("security-review", revised, revises="INTAKE-001")
        effective = intake.effective_statuses(space.ledger())
        self.assertEqual(effective["INTAKE-001"], "SUPERSEDED")
        self.assertEqual(effective["INTAKE-001-R1"], "ACCEPTED")

    def test_closure_with_foreign_artifact_evidence_refuses(self) -> None:
        finding = {"status": "FIXED_PENDING_REQUALIFICATION",
                   "artifact": "e906a48793d7",
                   "remediation_artifact": "fixture-successor-alpha"}
        with self.assertRaises(ops11.BoundaryViolation) as caught:
            ops11.security_finding_transition(
                finding, "CLOSED",
                {"closureEvidence": {"reference": "fixture-run",
                                     "artifact": "e906a48793d7"}})
        self.assertIn("does not transfer", str(caught.exception))

    def test_critical_dispositions_fail_closed_three_ways(self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json",
                            ops14.FIXTURES13)
        unassigned = ops13.validate_risk_acceptance(
            risk, [], _subject(), {"SEC-BL-001": "Critical"})
        self.assertTrue(any("AUTH-SECURITY-OWNER" in i
                            for i in unassigned), unassigned)
        self.assertEqual(ops13.risk_acceptance_state(risk, "2026-10-01"),
                         "EXPIRED")
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(
                {"status": "UNDER_REVIEW"}, "NOT_APPLICABLE",
                {"applicabilityEvidence": {"reference": "INTAKE-001"}})


class AlphaSufficiencyRehearsal(_Scratch):
    def test_a_hundred_reports_without_a_policy_stay_undetermined(
            self) -> None:
        expected, observed = ops14._s_e1(None)
        self.assertEqual(observed, expected)

    def test_an_active_policy_shortfall_stays_insufficient(self) -> None:
        policy = ops14._inner("sufficiency-policy-active.json",
                              ops14.FIXTURES13)
        policy["thresholds"]["minimumDistinctTesters"] = 5
        result = ops13.evaluate_sufficiency(
            [policy], ops14._sufficient_alpha_register(),
            ops14._security_register(), ops14.empty_scratch_ledger(),
            _subject())
        self.assertEqual(result["determination"], "INSUFFICIENT_EVIDENCE")

    def test_sufficiency_is_reachable_in_the_fixture_universe_only(
            self) -> None:
        space = self._space()
        ops14._register_full_evidence(space)
        result = ops13.evaluate_sufficiency(
            [ops14._inner("sufficiency-policy-active.json",
                          ops14.FIXTURES13)],
            ops14._sufficient_alpha_register(),
            ops14._security_register(), space.ledger(), _subject())
        self.assertEqual(result["determination"], "SUFFICIENT")
        real_policies = ops13.sealed_records(
            json.loads((_ROOT / "qualification" / "phase13"
                        / "sufficiency" / "threshold-policies.json")
                       .read_text(encoding="utf-8")),
            "policy_id", "threshold-policies.json")
        self.assertEqual(ops13.policy_registry_state(
            real_policies, _subject()), "SUFFICIENCY_POLICY_UNDEFINED")

    def test_foreign_artifact_reports_cannot_aggregate(self) -> None:
        space = self._space()
        entry = space.register("alpha-feedback", ops14._inner(
            "tester-artifact-mismatch.json", ops14.FIXTURES12))
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        register = self._alpha_register_for(space)
        self.assertEqual(register["counts"]["acceptedReports"], 0)
        self.assertEqual(register["reports"][0]["classification"],
                         "ARTIFACT_MISMATCH")

    def test_duplicates_stay_distinct_without_a_recorded_decision(
            self) -> None:
        space = self._space()
        fixture = ops14._fixture("tester-duplicate-pair.json",
                                 ops14.FIXTURES12)
        for record in fixture["records"]:
            space.register("alpha-feedback", copy.deepcopy(record))
        undecided = self._alpha_register_for(space)
        self.assertEqual(
            {f["relationship"]["kind"] for f in undecided["findings"]},
            {"DISTINCT"})
        decided = self._alpha_register_for(
            space, dedup={"decisions": [fixture["decisionDuplicate"]]})
        self.assertEqual(
            {f["relationship"]["kind"] for f in decided["findings"]},
            {"DUPLICATE_OF"})
        reversed_later = self._alpha_register_for(
            space, dedup={"decisions": [fixture["decisionDuplicate"],
                                        fixture["decisionRelatedLater"]]})
        self.assertEqual(
            {f["relationship"]["kind"]
             for f in reversed_later["findings"]}, {"RELATED"})
        self.assertEqual(reversed_later["counts"]["findings"], 2)

    def test_a_severe_unresolved_report_caps_sufficiency(self) -> None:
        space = self._space()
        space.register("alpha-feedback",
                       ops14._inner("alpha-severe-unreproduced.json"))
        register = self._alpha_register_for(
            space, policy={"thresholds": {"minimumBoundReports": 1}})
        self.assertEqual(register["sufficiency"]["determination"],
                         "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS")
        self.assertEqual(len(register["sufficiency"]["openBlockers"]), 1)
        self.assertEqual(register["counts"]["findings"], 1)

    def test_an_unreproduced_severe_issue_stays_open(self) -> None:
        expected, observed = ops14._s_c3(self._space())
        self.assertEqual(observed, expected)

    def test_user_success_stays_user_evidence(self) -> None:
        space = self._space()
        space.register("alpha-feedback", ops14._inner(
            "tester-success-bound.json", ops14.FIXTURES12))
        register = self._alpha_register_for(space)
        success = register["successEvidence"][0]
        self.assertEqual(success["evidenceClass"], "USER_REPORTED")
        self.assertIn("never SUPPORTED ON PCS", success["limit"])
        self.assertEqual(register["hardwareObservations"][0]["class"],
                         "HARDWARE_OBSERVED")


class HardwareRehearsal(_Scratch):
    def test_a_valid_protocol_record_is_accepted(self) -> None:
        space = self._space()
        entry = space.register("hardware", ops14._inner(
            "hardware-pass-machine.json", ops14.FIXTURES13))
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])

    def test_the_same_machine_with_the_wrong_artifact(self) -> None:
        space = self._space()
        entry = space.register("hardware", dict(ops14._inner(
            "hardware-pass-machine.json", ops14.FIXTURES13),
            artifactDigest="b" * 64))
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")

    def test_native_and_fallback_3d_never_merge(self) -> None:
        space = self._space()
        entry = space.register("hardware",
                               ops14._inner("hardware-render-split.json"))
        self.assertEqual(entry["status"], "ACCEPTED")
        review = ops14.hardware_submission_review(
            ops14._inner("hardware-render-split.json"), _subject())
        self.assertEqual(review["renderModesSeparate"]
                         ["companion-3d-native"], "PASS")
        self.assertEqual(review["renderModesSeparate"]
                         ["companion-3d-fallback"], "FAIL")

    def test_missing_machine_identity_is_incomplete(self) -> None:
        space = self._space()
        record = ops14._inner("hardware-pass-machine.json",
                              ops14.FIXTURES13)
        record["machine"] = {"manufacturer": "Constructed Fixture Systems"}
        entry = space.register("hardware", record)
        self.assertEqual(entry["status"], "INCOMPLETE")
        self.assertIn("machine.model", entry["statusReason"])

    def test_a_user_claim_is_not_hardware_evidence(self) -> None:
        route = ops14.route_evidence(
            ops14._inner("tester-success-bound.json", ops14.FIXTURES12),
            _subject())
        self.assertEqual(route["evidenceClass"], "ALPHA_TESTER_REPORT")
        self.assertEqual(route["destination"], "alpha-feedback")

    def test_mixed_machines_derive_no_support_claim(self) -> None:
        expected, observed = ops14._s_f6(None)
        self.assertEqual(observed, expected)


class SigningApprovalRehearsal(_Scratch):
    def test_a_valid_signing_record_is_accepted(self) -> None:
        space = self._space()
        entry = space.register("signing", ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10))
        self.assertEqual(entry["status"], "ACCEPTED")

    def test_signing_for_other_bytes_does_not_apply(self) -> None:
        space = self._space()
        entry = space.register("signing", dict(ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10),
            artifactDigest="sha256:" + "b" * 64))
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")

    def test_a_missing_recomputed_digest_is_incomplete(self) -> None:
        space = self._space()
        record = ops14._inner("second-approval-complete.json",
                              ops14.FIXTURES13)
        del record["secondApprover"]["recomputedDigest"]
        entry = space.register("second-approval", record)
        self.assertEqual(entry["status"], "INCOMPLETE")
        self.assertIn("recomputedDigest", entry["statusReason"])

    def test_a_drill_is_rejected(self) -> None:
        space = self._space()
        entry = space.register("signing", dict(ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10),
            category="SIGNING DRILL"))
        self.assertEqual(entry["status"], "REJECTED")

    def test_the_signer_as_second_approver_is_a_conflict(self) -> None:
        expected, observed = ops14._s_g5(self._space())
        self.assertEqual(observed, expected)

    def test_one_identity_approving_twice_is_rejected(self) -> None:
        space = self._space()
        record = ops14._inner("second-approval-complete.json",
                              ops14.FIXTURES13)
        record["secondApprover"]["name"] = record["firstApprover"]["name"]
        entry = space.register("second-approval", record)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("not a second approval", entry["statusReason"])

    def test_a_recomputation_mismatch_fails_closed(self) -> None:
        space = self._space()
        record = ops14._inner("second-approval-complete.json",
                              ops14.FIXTURES13)
        record["secondApprover"]["recomputedDigest"] = "sha256:" + "c" * 64
        entry = space.register("second-approval", record)
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")

    def test_expired_and_revoked_authority_stop_contributing(self) -> None:
        for fn in (ops14._s_g8, ops14._s_g9):
            expected, observed = fn(None)
            self.assertEqual(observed, expected)

    def test_the_real_candidate_is_unsigned_from_real_inputs(self) -> None:
        self.assertEqual(ops14.subject_unsigned_problems(), [])
        ledger = json.loads(ops14.PHASE9_LEDGER.read_text(encoding="utf-8"))
        self.assertEqual(ledger["subjectArtifact"]["signingStatus"],
                         "UNSIGNED")
        self.assertIs(ledger["subjectArtifact"]["frozen"], True)


class DecisionAssembly(_Scratch):
    def test_the_real_universe_assembles_to_the_committed_state(
            self) -> None:
        committed = json.loads(
            ops14.PHASE13_STATUS.read_text(encoding="utf-8"))
        assembly = ops14.assemble_decision(
            ops14.real_universe(), committed.get("evaluationDate"))
        self.assertEqual(assembly["authorizationState"],
                         committed["authorizationState"])
        self.assertEqual(assembly["candidateDecision"],
                         committed["candidateDecision"])
        self.assertEqual(assembly["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")
        self.assertEqual(assembly["favorableEvidence"], [])

    def test_an_empty_fixture_universe_is_not_authorized(self) -> None:
        assembly = ops14.assemble_decision(
            ops14.build_universe(self._space()), ops14.REHEARSAL_DATE)
        self.assertEqual(assembly["authorizationState"],
                         "EVIDENCE_PENDING")
        self.assertEqual(assembly["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")

    def test_four_of_five_floor_sources_are_not_enough(self) -> None:
        expected, observed = ops14._s_h3(self._space())
        self.assertEqual(observed, expected)

    def test_a_wrong_artifact_floor_member_counts_as_absent(self) -> None:
        expected, observed = ops14._s_h4(self._space())
        self.assertEqual(observed, expected)

    def test_unresolved_security_holds_the_ladder(self) -> None:
        expected, observed = ops14._s_h5(self._space())
        self.assertEqual(observed, expected)

    def test_an_undefined_alpha_policy_refuses(self) -> None:
        expected, observed = ops14._s_h6(self._space())
        self.assertEqual(observed, expected)

    def test_an_active_policy_with_insufficient_evidence_refuses(
            self) -> None:
        expected, observed = ops14._s_h7(self._space())
        self.assertEqual(observed, expected)

    def test_the_fixture_universe_can_reach_authorized(self) -> None:
        space = self._space()
        universe, record = ops14.authorized_universe(space)
        assembly = ops14.assemble_decision(universe, ops14.REHEARSAL_DATE)
        self.assertEqual(assembly["authorizationState"], "AUTHORIZED")
        self.assertEqual(assembly["candidateDecision"], "AUTHORIZED")
        rows = assembly["inputs"]["authorizations"]
        self.assertEqual([r["state"] for r in rows], ["AUTHORIZED"])
        # The AUTHORIZED the assembler reports is the sealed record's own
        # authorization, not a state the assembler synthesized.
        self.assertEqual(rows[0]["authorizationId"],
                         record["authorization_id"])

    def test_every_favorable_conclusion_identifies_everything(self) -> None:
        space = self._space()
        universe, _record = ops14.authorized_universe(space)
        assembly = ops14.assemble_decision(universe, ops14.REHEARSAL_DATE)
        self.assertEqual(len(assembly["favorableEvidence"]), 5)
        for row in assembly["favorableEvidence"]:
            for field in ("intakeId", "source", "artifactDigest",
                          "validationResult", "binding", "policyVersions",
                          "asOfCut", "expiryStatus"):
                self.assertIn(field, row)
            self.assertEqual(row["validationResult"], "ACCEPTED")
            self.assertEqual(row["asOfCut"],
                             assembly["evidenceCut"]["seal"])

    def test_revocation_at_a_later_cut_revokes_without_rewriting(
            self) -> None:
        space = self._space()
        universe, _record = ops14.authorized_universe(space)
        assembly_a = ops14.assemble_decision(universe,
                                             ops14.REHEARSAL_DATE)
        frozen = copy.deepcopy(assembly_a)
        revoked = dict(universe, revocations=[ops14._seal13(ops14._inner(
            "revocation-of-authorization.json", ops14.FIXTURES13))])
        assembly_b = ops14.assemble_decision(revoked, ops14.CUT_B_DATE)
        self.assertEqual(assembly_a["authorizationState"], "AUTHORIZED")
        self.assertEqual(assembly_b["authorizationState"], "REVOKED")
        self.assertEqual(ops14.assemble_decision(
            universe, ops14.REHEARSAL_DATE), frozen)

    def test_an_authorization_past_expiry_derives_expired(self) -> None:
        space = self._space()
        universe, _record = ops14.authorized_universe(space)
        assembly = ops14.assemble_decision(universe, "2026-11-25")
        self.assertEqual(assembly["authorizationState"], "EXPIRED")
        self.assertEqual(assembly["candidateDecision"], "EXPIRED")

    def test_assembly_over_expiring_records_requires_as_of(self) -> None:
        space = self._space()
        universe = ops14.build_universe(
            space,
            assignments=ops14._fixture_assignments(),
            risks=[ops14._seal13(ops14._inner(
                "risk-acceptance-critical.json", ops14.FIXTURES13))])
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.assemble_decision(universe, None)

    def test_a_successor_artifact_inherits_nothing(self) -> None:
        record = ops14._inner("authorization-internal-authorized.json",
                              ops14.FIXTURES13)
        successor = ops14._fixture("successor-artifact-entry.json",
                                   ops14.FIXTURES13)["successorEntry"]
        applies = ops13.authorization_applies(record, successor)
        self.assertEqual(applies["result"], "REFUSED")
        self.assertIn("never transfers", applies["reasoning"])
        ops10 = ops14._phase10()
        evidence = {"evidenceId": "INTAKE-001",
                    "artifactDigest": json.loads(
                        ops14.PHASE9_LEDGER.read_text(encoding="utf-8"))
                    ["subjectArtifact"]["imageDigest"],
                    "scope": "security-review"}
        transfer = ops10.evaluate_applicability(
            evidence, successor["artifact_id"], _GRAPH)
        self.assertEqual(transfer["result"], "DOES_NOT_APPLY")

    def test_the_assembler_writes_nothing(self) -> None:
        before = {path: path.read_bytes()
                  for path in ops14.REAL_IMMUTABLE_INPUTS}
        committed = json.loads(
            ops14.PHASE13_STATUS.read_text(encoding="utf-8"))
        first = ops14.assemble_decision(ops14.real_universe(),
                                        committed.get("evaluationDate"))
        second = ops14.assemble_decision(ops14.real_universe(),
                                         committed.get("evaluationDate"))
        self.assertEqual(first, second)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw, path.name)


if __name__ == "__main__":
    unittest.main()

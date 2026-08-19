# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The external-evidence execution layer works, and touches nothing real.

Phase 14 is tested the way Phases 9-13 are tested, plus the property
that defines it: every rehearsal runs against scratch universes, and
the real ledger, graph, registers, registries, status, and matrix are
byte-compared before and after — never asserted empty — so the suite
stays green on the day real evidence arrives.

This module covers the primitives: the fail-closed router (ten classes,
ambiguity and unknowns refused, fixtures terminal); the sealed evidence
cut (byte-identical re-derivation, post-cut detection, mandatory as-of,
supersession without rewriting); the single conflict policy (most
blocking effective, a favorable resolution raises); the hardware
per-machine discipline; time semantics failing closed; the fixture
boundary in both directions; the Track J immutability controls; and the
derived MATRIX.json reproducing from executing all seventy-two
scenarios.
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
_VERIFY14_TOOL = (_ROOT / "qualification" / "phase14" / "tools"
                  / "verify_phase14.py")
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_OPS13_TOOL = (_ROOT / "qualification" / "phase13" / "tools"
               / "release_authority_ops.py")
_MATRIX = _ROOT / "qualification" / "phase14" / "MATRIX.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops14 = _load("phase14_ops_under_test", _OPS14_TOOL)
intake = _load("phase9_intake_for_phase14_tests", _INTAKE_TOOL)
ops13 = _load("phase13_ops_for_phase14_tests", _OPS13_TOOL)


def _subject() -> set[str]:
    return intake.subject_digests(
        json.loads(ops14.PHASE9_LEDGER.read_text(encoding="utf-8")))


class _Scratch(unittest.TestCase):
    """Constructed universes only; the real evidence never participates.

    The class-level byte comparison is the Track J control that matters
    most: a rehearsal that touched reality is not a rehearsal.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.real_bytes = {path: path.read_bytes()
                          for path in ops14.REAL_IMMUTABLE_INPUTS}
        cls.real_bytes[_MATRIX] = _MATRIX.read_bytes()

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_bytes.items():
            if path.read_bytes() != raw:
                raise AssertionError(
                    "%s changed during the dry runs; Phase 14 must never "
                    "mutate its immutable inputs" % path.name)

    def _space(self) -> "ops14.RehearsalSpace":
        base = Path(tempfile.mkdtemp(prefix="phase14-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)


class RouterClasses(_Scratch):
    def test_the_ten_classes_agree_with_the_fingerprints(self) -> None:
        self.assertEqual(len(ops14.EVIDENCE_CLASSES), 10)
        self.assertEqual(
            sorted(ops14.EVIDENCE_CLASSES),
            sorted(name for name, _ in ops14._CLASS_FINGERPRINTS))
        for route in ops14.EVIDENCE_CLASSES.values():
            self.assertIn(route["routeKind"],
                          ("PHASE9_INTAKE", "PHASE13_REGISTRY"))
            self.assertTrue(route["validator"])

    def test_every_class_routes_to_its_declared_destination(self) -> None:
        expected, observed = ops14._s_a1(None)
        self.assertEqual(observed, expected)

    def test_an_unroutable_record_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.classify_evidence({"shapeless": True})
        self.assertIn("generic evidence", str(caught.exception))

    def test_an_ambiguous_record_is_refused(self) -> None:
        record = ops14._inner("hardware-pass-machine.json",
                              ops14.FIXTURES13)
        record.update({"reviewer": "R", "findings": [],
                       "disposition": "APPROVED"})
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.classify_evidence(record)
        self.assertIn("saying nothing", str(caught.exception))

    def test_a_non_object_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.classify_evidence(["not", "a", "record"])

    def test_a_fixture_marker_is_terminal(self) -> None:
        record = dict(ops14._inner("signing-metadata-valid.json",
                                   ops14.FIXTURES10), fixture=True)
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "TEST_FIXTURE_ONLY")
        self.assertIn("never routes", route["destination"])
        self.assertEqual(route["evidenceClass"], "SIGNING")

    def test_the_whole_fixture_wrapper_is_also_terminal(self) -> None:
        wrapper = ops14._fixture("authorization-internal-authorized.json",
                                 ops14.FIXTURES13)
        route = ops14.route_evidence(wrapper, _subject())
        self.assertEqual(route["disposition"], "TEST_FIXTURE_ONLY")
        self.assertIsNone(route["evidenceClass"])

    def test_wrong_artifact_derives_does_not_apply(self) -> None:
        record = dict(ops14._inner("signing-metadata-valid.json",
                                   ops14.FIXTURES10),
                      artifactDigest="b" * 64)
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "DOES_NOT_APPLY")
        self.assertEqual(route["binding"], "MISMATCH")

    def test_missing_fields_derive_incomplete(self) -> None:
        record = ops14._inner("signing-metadata-valid.json",
                              ops14.FIXTURES10)
        del record["verificationRunBy"]
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "INCOMPLETE")
        self.assertIn("verificationRunBy", route["dispositionBasis"])

    def test_a_signing_drill_derives_rejected(self) -> None:
        record = dict(ops14._inner("signing-metadata-valid.json",
                                   ops14.FIXTURES10),
                      category="SIGNING DRILL")
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "REJECTED")

    def test_an_unbound_alpha_report_is_unbound_not_mismatched(self) -> None:
        record = ops14._inner("tester-success-bound.json", ops14.FIXTURES12)
        del record["artifactDigest"]
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["binding"], "UNBOUND")
        self.assertEqual(route["disposition"], "ACCEPTABLE_FOR_INTAKE")

    def test_governance_records_require_a_human_decision(self) -> None:
        expected, observed = ops14._s_a8(None)
        self.assertEqual(observed, expected)

    def test_a_governance_record_for_other_bytes_does_not_apply(
            self) -> None:
        record = dict(ops14._inner("risk-acceptance-critical.json",
                                   ops14.FIXTURES13),
                      artifact_digest="sha256:" + "b" * 64)
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "DOES_NOT_APPLY")
        self.assertIn("never transfers", route["dispositionBasis"])

    def test_an_incomplete_governance_record_is_incomplete(self) -> None:
        record = ops14._inner("risk-acceptance-critical.json",
                              ops14.FIXTURES13)
        del record["scope"]
        route = ops14.route_evidence(record, _subject())
        self.assertEqual(route["disposition"], "INCOMPLETE")
        self.assertIn("scope", route["dispositionBasis"])

    def test_the_router_registers_nothing(self) -> None:
        before = ops14.PHASE9_LEDGER.read_bytes()
        ops14.route_evidence(ops14._inner("signing-metadata-valid.json",
                                          ops14.FIXTURES10), _subject())
        self.assertEqual(ops14.PHASE9_LEDGER.read_bytes(), before)


class EvidenceCuts(_Scratch):
    def _cut(self, space, **overrides):
        defaults = dict(
            ledger_bytes=space.ledger_bytes(),
            graph_bytes=ops14.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of=None)
        defaults.update(overrides)
        return ops14.build_evidence_cut(**defaults)

    def test_the_same_inputs_derive_byte_identical_cuts(self) -> None:
        space = self._space()
        space.register("signing", ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10))
        first = self._cut(space, as_of="2026-08-19")
        second = self._cut(space, as_of="2026-08-19")
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))
        self.assertEqual(ops14.verify_cut(first), [])

    def test_the_seal_spellings_cannot_drift(self) -> None:
        sample = {"a": 1, "nested": {"b": [1, 2]}, "seal": "ignored"}
        self.assertEqual(ops14.seal_record(sample),
                         intake.seal_entry(sample))
        self.assertEqual(ops14.seal_record(sample),
                         ops13.seal_record(sample))

    def test_an_edited_cut_fails_its_seal(self) -> None:
        cut = self._cut(self._space())
        cut["ledgerEntries"] = 99
        issues = ops14.verify_cut(cut)
        self.assertTrue(any("IMMUTABILITY FAIL" in i for i in issues),
                        issues)

    def test_post_cut_evidence_is_detected_and_named(self) -> None:
        space = self._space()
        space.register("signing", ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10))
        cut = self._cut(space)
        space.register("second-approval", ops14._inner(
            "second-approval-complete.json", ops14.FIXTURES13))
        delta = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
        self.assertTrue(delta["ledgerChanged"])
        self.assertEqual(delta["postCutIntakeIds"], ["INTAKE-002"])
        self.assertEqual(delta["missingIntakeIds"], [])

    def test_expiring_records_make_as_of_mandatory(self) -> None:
        risk = ops14._seal13(ops14._inner("risk-acceptance-critical.json",
                                          ops14.FIXTURES13))
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            self._cut(self._space(), risks=[risk], as_of=None)
        self.assertIn("--as-of is mandatory", str(caught.exception))
        self.assertIn("RISK-001", str(caught.exception))

    def test_no_expiring_records_needs_no_as_of(self) -> None:
        cut = self._cut(self._space())
        self.assertIsNone(cut["asOf"])
        self.assertEqual(cut["expiringRecords"], [])

    def test_a_malformed_as_of_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            self._cut(self._space(), as_of="not-a-date")

    def test_cut_rows_derive_states_per_evaluation_date(self) -> None:
        risk = ops14._seal13(ops14._inner("risk-acceptance-critical.json",
                                          ops14.FIXTURES13))
        space = self._space()
        early = self._cut(space, risks=[risk], as_of="2026-09-01")
        late = self._cut(space, risks=[risk], as_of="2026-09-20")
        self.assertEqual(early["riskAcceptances"][0]["state"], "STANDING")
        self.assertEqual(late["riskAcceptances"][0]["state"], "EXPIRED")

    def test_supersession_points_and_never_rewrites(self) -> None:
        expected, observed = ops14._s_b8(self._space())
        self.assertEqual(observed, expected)

    def test_superseding_the_same_cut_is_refused(self) -> None:
        space = self._space()
        assembly = ops14.assemble_decision(
            ops14.build_universe(space), ops14.REHEARSAL_DATE)
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.supersede_assembly(assembly, copy.deepcopy(assembly))
        self.assertIn("not for a rerun", str(caught.exception))

    def test_an_unsealed_assembly_cannot_supersede(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.supersede_assembly({"evidenceCut": {}},
                                     {"evidenceCut": {"seal": "x"}})


class ConflictPolicy(_Scratch):
    def test_the_more_blocking_state_stands(self) -> None:
        result = ops14.most_blocking([
            {"reference": "A", "assessment": "ACCEPTED_RISK",
             "favorable": True},
            {"reference": "B", "assessment": "UNRESOLVED",
             "favorable": False}], "security")
        self.assertEqual(result["effectiveAssessment"], ["UNRESOLVED"])
        self.assertEqual(result["resolution"], "REQUIRES_HUMAN_DECISION")

    def test_every_domain_keeps_favorable_out_of_effective(self) -> None:
        for domain in ("security", "hardware", "alpha", "release"):
            result = ops14.most_blocking([
                {"reference": "A", "assessment": "PASS", "favorable": True},
                {"reference": "B", "assessment": "FAIL",
                 "favorable": False}], domain)
            self.assertNotIn("PASS", result["effectiveAssessment"], domain)

    def test_a_favorable_resolution_would_raise(self) -> None:
        """The guard on the guard, executed: a (stubbed) classifier that
        resolves toward the favorable assessment is refused."""
        class _FavorableStub:
            @staticmethod
            def classify_evidence_conflict(domain, observations):
                return {"conflictStatus": "CONFLICT",
                        "effectiveAssessment": ["PASS"],
                        "resolution": "REQUIRES_HUMAN_DECISION"}
        original = ops14._MODULE_CACHE.get("phase13_ops_for_phase14")
        ops14._MODULE_CACHE["phase13_ops_for_phase14"] = _FavorableStub()
        try:
            with self.assertRaises(ops14.BoundaryViolation) as caught:
                ops14.most_blocking([
                    {"reference": "A", "assessment": "PASS",
                     "favorable": True},
                    {"reference": "B", "assessment": "FAIL",
                     "favorable": False}], "alpha")
            self.assertIn("never become more favorable",
                          str(caught.exception))
        finally:
            if original is None:
                ops14._MODULE_CACHE.pop("phase13_ops_for_phase14", None)
            else:
                ops14._MODULE_CACHE["phase13_ops_for_phase14"] = original

    def test_hardware_divergence_is_preserved_never_averaged(self) -> None:
        effective = ops14.hardware_effective_state([
            {"hwId": "HW-001",
             "results": {"installation": {"status": "PASS"}}},
            {"hwId": "HW-002",
             "results": {"installation": {"status": "FAIL"}}}])
        row = effective["perDimension"][0]
        self.assertEqual(row["byMachine"],
                         {"HW-001": "PASS", "HW-002": "FAIL"})
        self.assertTrue(row["divergent"])
        self.assertIsNone(row["claim"])
        self.assertIsNone(effective["aggregateClaim"]["claim"])

    def test_a_merged_render_dimension_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.hardware_effective_state([
                {"hwId": "HW-001", "results": {"companion-3d": "PASS"}}])
        self.assertIn("permanently separate", str(caught.exception))

    def test_a_machine_without_identity_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.hardware_effective_state([{"results": {}}])

    def test_aggregate_hardware_claims_are_refused(self) -> None:
        effective = ops14.hardware_effective_state([
            {"hwId": "HW-001",
             "results": {"installation": {"status": "PASS"}}}])
        for claim in ("SUPPORTED ON PCS", "SUPPORTED ON ALL PCS"):
            with self.assertRaises(ops14.BoundaryViolation) as caught:
                ops14.hardware_claims(effective, claim)
            self.assertIn("no pre-existing policy", str(caught.exception))


class HardwareReview(_Scratch):
    def test_a_complete_record_reviews_acceptable_with_identity(
            self) -> None:
        review = ops14.hardware_submission_review(
            ops14._inner("hardware-pass-machine.json", ops14.FIXTURES13),
            _subject())
        self.assertEqual(review["disposition"], "ACCEPTABLE_FOR_INTAKE")
        self.assertEqual(review["machineIdentity"]["hwId"], "HW-001")
        self.assertEqual(review["piiProblems"], [])

    def test_render_modes_stay_separate(self) -> None:
        review = ops14.hardware_submission_review(
            ops14._inner("hardware-render-split.json"), _subject())
        modes = review["renderModesSeparate"]
        self.assertEqual(modes["companion-3d-native"], "PASS")
        self.assertEqual(modes["companion-3d-fallback"], "FAIL")

    def test_an_operator_email_blocks_acceptance(self) -> None:
        record = dict(ops14._inner("hardware-pass-machine.json",
                                   ops14.FIXTURES13),
                      operator="operator@example.org")
        review = ops14.hardware_submission_review(record, _subject())
        self.assertEqual(review["disposition"], "INCOMPLETE")
        self.assertTrue(any("PII" in p for p in review["piiProblems"]))

    def test_the_wrapped_fixture_is_refused(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.hardware_submission_review(
                ops14._fixture("hardware-pass-machine.json",
                               ops14.FIXTURES13), _subject())


class SigningApprovalChecks(_Scratch):
    def test_an_approval_predating_signing_flags(self) -> None:
        flags = ops14.approval_ordering_problems(
            ops14._inner("signing-metadata-valid.json", ops14.FIXTURES10),
            ops14._inner("approval-before-signing.json"))
        self.assertEqual(len(flags), 2)
        for flag in flags:
            self.assertIn("REQUIRES_HUMAN_DECISION", flag)

    def test_a_well_ordered_approval_does_not_flag(self) -> None:
        flags = ops14.approval_ordering_problems(
            ops14._inner("signing-metadata-valid.json", ops14.FIXTURES10),
            ops14._inner("second-approval-complete.json",
                         ops14.FIXTURES13))
        self.assertEqual(flags, [])

    def test_unparseable_ordering_dates_fail_closed(self) -> None:
        flags = ops14.approval_ordering_problems(
            {"signingTimestamp": "sometime"},
            ops14._inner("second-approval-complete.json",
                         ops14.FIXTURES13))
        self.assertEqual(len(flags), 1)
        self.assertIn("cannot be determined", flags[0])

    def test_the_subject_remains_unsigned(self) -> None:
        self.assertEqual(ops14.subject_unsigned_problems(), [])


class StandingAuthority(_Scratch):
    def _expiring(self, authority_id="AUTH-RELEASE"):
        assignments = []
        for record in ops14._fixture("authority-assignments.json",
                                     ops14.FIXTURES13)["assignments"]:
            record = dict(record)
            if record["authorityId"] == authority_id:
                record["expires_at"] = "2026-09-30"
            assignments.append(ops14._seal13(record))
        return assignments

    def test_assignments_without_expiry_need_no_as_of(self) -> None:
        standing = ops14.standing_assignments(
            ops14._fixture_assignments(), None)
        self.assertEqual(len(standing), 7)

    def test_an_expiring_assignment_requires_as_of(self) -> None:
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.standing_assignments(self._expiring(), None)

    def test_expiry_removes_authority_at_later_cuts_only(self) -> None:
        assignments = self._expiring()
        self.assertEqual(len(ops14.standing_assignments(
            assignments, "2026-08-19")), 7)
        standing = ops14.standing_assignments(assignments, "2026-12-01")
        self.assertEqual(len(standing), 6)
        self.assertFalse(ops13.assigned_identities(standing)
                         ["AUTH-RELEASE"])

    def test_a_revocation_removes_authority_from_its_timestamp(
            self) -> None:
        assignments = ops14._fixture_assignments()
        revocation = ops14._fixture("assignment-lifecycle.json")[
            "assignmentRevocation"]
        self.assertEqual(len(ops14.standing_assignments(
            assignments, "2026-08-19", [revocation])), 7)
        self.assertEqual(len(ops14.standing_assignments(
            assignments, "2026-12-01", [revocation])), 6)
        self.assertEqual(ops14.assignment_state(
            assignments[2], "2026-12-01", [revocation]), "REVOKED")

    def test_a_dangling_assignment_revocation_fails_closed(self) -> None:
        revocation = dict(ops14._fixture("assignment-lifecycle.json")[
            "assignmentRevocation"], targetAssignment="ASSIGNMENT-099")
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.standing_assignments(ops14._fixture_assignments(),
                                       "2026-12-01", [revocation])
        self.assertIn("revokes nothing", str(caught.exception))

    def test_assignment_states_derive(self) -> None:
        assignments = self._expiring("AUTH-KEY")
        expiring = next(a for a in assignments
                        if a["authorityId"] == "AUTH-KEY")
        self.assertEqual(ops14.assignment_state(expiring, "2026-08-19"),
                         "STANDING")
        self.assertEqual(ops14.assignment_state(expiring, "2026-12-01"),
                         "EXPIRED")
        with self.assertRaises(ops14.BoundaryViolation):
            ops14.assignment_state(expiring, None)


class TimeSemantics(_Scratch):
    def test_future_dated_evidence_flags(self) -> None:
        flags = ops14.time_consistency_problems(
            record_dates={"date": "2026-12-15"},
            received_on="2026-08-19")
        self.assertEqual(len(flags), 1)
        self.assertIn("postdates the intake receipt", flags[0])

    def test_revision_before_original_flags(self) -> None:
        flags = ops14.time_consistency_problems(
            record_dates={"date": "2026-08-18"}, received_on="2026-08-18",
            revises_received_on="2026-08-19")
        self.assertEqual(len(flags), 1)
        self.assertIn("cannot precede", flags[0])

    def test_ambiguous_time_basis_flags(self) -> None:
        flags = ops14.time_consistency_problems(
            record_dates={"date": "2026-08-18",
                          "signingTimestamp": "2026-08-19"},
            received_on="2026-12-01")
        self.assertEqual(len(flags), 1)
        self.assertIn("ambiguous time basis", flags[0])

    def test_unparseable_dates_fail_closed(self) -> None:
        flags = ops14.time_consistency_problems(
            record_dates={"date": "recently"}, received_on="2026-08-19")
        self.assertEqual(len(flags), 1)
        self.assertIn("fails closed", flags[0])

    def test_consistent_dates_pass_clean(self) -> None:
        self.assertEqual(ops14.time_consistency_problems(
            record_dates={"date": "2026-08-18",
                          "signingTimestamp": "2026-08-18"},
            received_on="2026-08-19"), [])


class FixtureBoundary(_Scratch):
    def test_every_phase14_fixture_carries_all_three_markers(self) -> None:
        names = sorted(p.name for p in ops14.FIXTURES_DIR.glob("*.json"))
        self.assertTrue(names, "no phase14 fixtures found")
        for name in names:
            record = ops14._fixture(name)
            self.assertEqual(record.get("fixtureClass"),
                             "TEST_FIXTURE_ONLY", name)
            self.assertIs(record.get("fixture"), True, name)
            self.assertIs(record.get("test_fixture_only"), True, name)
        self.assertEqual(ops14.verify_fixtures(), [])

    def test_any_single_marker_makes_a_fixture(self) -> None:
        self.assertTrue(ops14.is_fixture(
            {"fixtureClass": "TEST_FIXTURE_ONLY"}))
        self.assertTrue(ops14.is_fixture({"test_fixture_only": True}))
        self.assertTrue(ops14.is_fixture({"fixture": True}))
        self.assertFalse(ops14.is_fixture({"fixture": "yes"}))
        self.assertFalse(ops14.is_fixture({}))

    def test_the_real_intake_code_rejects_a_phase14_wrapper(self) -> None:
        space = self._space()
        entry = intake.register(
            space.ledger_path, "hardware",
            space.stage(ops14._fixture("hardware-render-split.json")),
            [], "2026-08-19", "phase14 boundary control")
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("a fixture is never evidence", entry["statusReason"])

    def test_the_assembler_refuses_a_fixture_authorization(self) -> None:
        space = self._space()
        universe = ops14.build_universe(
            space, authorizations=[dict(ops14._inner(
                "authorization-internal-authorized.json",
                ops14.FIXTURES13), fixture=True)])
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.assemble_decision(universe, ops14.REHEARSAL_DATE)
        self.assertIn("never evidence", str(caught.exception))

    def test_append_record_refuses_phase14_fixture_material(self) -> None:
        registries_before = {
            path: path.read_bytes()
            for path in ops14.REAL_IMMUTABLE_INPUTS
            if "phase13" in path.as_posix()}
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.append_record("assignment", dict(
                ops14._fixture("authority-assignments.json",
                               ops14.FIXTURES13)["assignments"][0],
                test_fixture_only=True))
        for path, raw in registries_before.items():
            self.assertEqual(path.read_bytes(), raw, path.name)

    def test_a_fixture_ledger_entry_refuses_assembly(self) -> None:
        space = self._space()
        ledger = space.ledger()
        entry = {"intakeId": "INTAKE-001", "revises": None,
                 "source": "signing", "receivedOn": "2026-08-19",
                 "submittedBy": "control", "files": {},
                 "status": "ACCEPTED", "statusReason": "", "usableIf": "",
                 "binding": "BOUND", "gateEligible": True,
                 "validation": {}, "fixture": True}
        entry["seal"] = intake.seal_entry(entry)
        ledger["entries"].append(entry)
        intake.dump_ledger(space.ledger_path, ledger)
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.assemble_decision(ops14.build_universe(space),
                                    ops14.REHEARSAL_DATE)
        self.assertIn("fixtures never enter", str(caught.exception))


class ImmutabilityControls(_Scratch):
    def test_tampering_an_accepted_scratch_entry_fails_closed(self) -> None:
        space = self._space()
        space.register("signing", ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10))
        ledger = space.ledger()
        ledger["entries"][0]["statusReason"] = "improved wording"
        intake.dump_ledger(space.ledger_path, ledger)
        issues = intake.verify_intake(space.intake_root,
                                      space.ledger())
        self.assertEqual(issues.get("sealBroken"), ["INTAKE-001"])
        with self.assertRaises(SystemExit) as caught:
            space.register("second-approval", ops14._inner(
                "second-approval-complete.json", ops14.FIXTURES13))
        self.assertIn("tampered ledger", str(caught.exception))

    def test_tampering_a_rejected_scratch_entry_fails_closed(self) -> None:
        space = self._space()
        space.register("signing", dict(ops14._inner(
            "signing-metadata-valid.json", ops14.FIXTURES10),
            category="SIGNING DRILL"))
        ledger = space.ledger()
        ledger["entries"][0]["status"] = "ACCEPTED"
        intake.dump_ledger(space.ledger_path, ledger)
        issues = intake.verify_intake(space.intake_root, space.ledger())
        self.assertEqual(issues.get("sealBroken"), ["INTAKE-001"])

    def test_editing_a_sealed_policy_fails_immutability(self) -> None:
        sealed = ops14._seal13(ops14._inner(
            "sufficiency-policy-active.json", ops14.FIXTURES13))
        sealed["thresholds"]["minimumAcceptedTesterReports"] = 0
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.sealed_records({"records": [sealed]}, "policy_id",
                                 "phase14 control")
        self.assertIn("IMMUTABILITY FAIL", str(caught.exception))

    def test_editing_a_sealed_assignment_fails_immutability(self) -> None:
        sealed = ops14._fixture_assignments()[0]
        tampered = dict(sealed, identity="Someone Else")
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.sealed_records({"records": [tampered]}, "assignmentId",
                                 "phase14 control")
        self.assertIn("IMMUTABILITY FAIL", str(caught.exception))

    def test_altering_the_graph_changes_the_cut_and_refuses_assembly(
            self) -> None:
        space = self._space()
        honest = ops14.build_evidence_cut(
            ledger_bytes=space.ledger_bytes(),
            graph_bytes=ops14.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[])
        altered = ops14.build_evidence_cut(
            ledger_bytes=space.ledger_bytes(), graph_bytes=b"{}",
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[])
        self.assertNotEqual(honest["graphSha256"], altered["graphSha256"])
        self.assertNotEqual(honest["seal"], altered["seal"])
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.assemble_decision(ops14.build_universe(
                space, graph_bytes=b'{"artifacts": []}'),
                ops14.REHEARSAL_DATE)
        self.assertIn("artifact graph invalid", str(caught.exception))

    def test_mutating_the_candidate_identity_refuses_assembly(self) -> None:
        space = self._space()
        ledger = space.ledger()
        ledger["subjectArtifact"]["identifier"] = "someone-else"
        intake.dump_ledger(space.ledger_path, ledger)
        with self.assertRaises(ops14.BoundaryViolation) as caught:
            ops14.assemble_decision(ops14.build_universe(space),
                                    ops14.REHEARSAL_DATE)
        self.assertIn("CANDIDATE IDENTITY FAIL", str(caught.exception))

    def test_representative_rehearsals_leave_real_bytes_identical(
            self) -> None:
        before = {path: path.read_bytes()
                  for path in ops14.REAL_IMMUTABLE_INPUTS}
        for fn in (ops14._s_d1, ops14._s_h8, ops14._s_e5):
            expected, observed = fn(self._space())
            self.assertEqual(observed, expected)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw, path.name)


class MatrixAndVerify(_Scratch):
    def test_the_committed_matrix_reproduces_by_execution(self) -> None:
        self.assertEqual(ops14.matrix_problems(), [])

    def test_every_row_is_a_fixture_demonstration(self) -> None:
        matrix = json.loads(_MATRIX.read_text(encoding="utf-8"))
        rows = matrix["scenarios"]
        self.assertEqual(len(rows), len(ops14.SCENARIOS))
        ids = [r["scenarioId"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({r["track"] for r in rows},
                         set("ABCDEFGHI"))
        for row in rows:
            self.assertEqual(row["evidenceClass"],
                             "FIXTURE_DEMONSTRATION_ONLY", row["scenarioId"])
            self.assertEqual(row["realEvidenceStatus"],
                             "EXTERNAL_EVIDENCE_REQUIRED", row["scenarioId"])
            self.assertEqual(row["result"], "AS_EXPECTED", row["scenarioId"])

    def test_the_matrix_names_the_world_it_ran_in(self) -> None:
        matrix = json.loads(_MATRIX.read_text(encoding="utf-8"))
        executed = matrix["executedAgainst"]
        self.assertEqual(
            executed["ledgerSha256"],
            ops14._sha256(ops14.PHASE9_LEDGER.read_bytes()))
        self.assertEqual(executed["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")
        self.assertIs(matrix["realLedgerByteIdentical"], True)
        self.assertIn("not evidence about the subject artifact",
                      matrix["purpose"])

    def test_verify_all_is_clean(self) -> None:
        self.assertEqual(ops14.verify_all(), [])

    def test_the_engine_reads_no_clock(self) -> None:
        for path in (_OPS14_TOOL, _VERIFY14_TOOL):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("datetime.now", "date.today", "time.time(",
                              "utcnow"):
                self.assertNotIn(forbidden, source,
                                 "%s reads a clock via %s"
                                 % (path.name, forbidden))

    def test_the_scenario_registry_is_complete(self) -> None:
        ids = [scenario_id for scenario_id, _, _, _ in ops14.SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({track for _, track, _, _ in ops14.SCENARIOS},
                         set("ABCDEFGHI"))
        self.assertGreaterEqual(len(ids), 70)


if __name__ == "__main__":
    unittest.main()

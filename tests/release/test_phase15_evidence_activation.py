# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The evidence path is activated, and silence still authorizes nothing.

The second Phase 15 guard module covers the derived views and the walls
around them: EXTERNAL_STATUS.json reproduces from live inputs and keeps
its four questions separate; the failure/recovery matrix reproduces by
re-executing every scenario; zero external evidence derives a
non-authorizing state no matter how many internal tests pass; internal
JSON cannot claim AUTHORIZED; fixture material cannot satisfy anything
real; the handoff package pins its bytes, marks its examples, and the
real intake code rejects them; and both Phase 15 test modules are inside
the discovered release suite (the Phase 5 undiscovered-directory trap,
re-checked).

The real ledger participates in nothing here: every class byte-compares
all real immutable inputs before and after — never their emptiness.
"""

from __future__ import annotations

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
_TRACK = _ROOT / "qualification" / "phase15" / "security-review-execution"
_OPS15_TOOL = _TRACK / "tools" / "review_execution_ops.py"
_VERIFY15 = _TRACK / "VERIFY_PHASE15.py"
_FIXTURES = _TRACK / "fixtures"
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_OPS11_TOOL = (_ROOT / "qualification" / "phase11" / "tools"
               / "security_review_ops.py")
_OPS13_TOOL = (_ROOT / "qualification" / "phase13" / "tools"
               / "release_authority_ops.py")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops15 = _load("phase15_activation_under_test", _OPS15_TOOL)
intake = _load("phase9_intake_for_activation_tests", _INTAKE_TOOL)
ops11 = _load("phase11_ops_for_activation_tests", _OPS11_TOOL)
ops13 = _load("phase13_ops_for_activation_tests", _OPS13_TOOL)
ops14 = ops15._phase14()

_BASELINE = json.loads(ops15.PHASE11_BASELINE.read_text(encoding="utf-8"))
_GRAPH = json.loads(ops15.PHASE10_GRAPH.read_text(encoding="utf-8"))


def _inner(name: str) -> dict:
    return copy.deepcopy(json.loads(
        (_FIXTURES / name).read_text(encoding="utf-8"))["record"])


def _wrapper(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class _Scratch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_bytes = {path: path.read_bytes()
                          for path in ops14.REAL_IMMUTABLE_INPUTS}
        for extra in (ops15.STATUS_PATH, ops15.MATRIX_PATH):
            if extra.is_file():
                cls.real_bytes[extra] = extra.read_bytes()
        if ops15.CUTS_DIR.is_dir():
            for cut in sorted(ops15.CUTS_DIR.glob("*.json")):
                cls.real_bytes[cut] = cut.read_bytes()

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_bytes.items():
            if path.read_bytes() != raw:
                raise AssertionError(
                    "%s changed during the dry runs; Phase 15 must never "
                    "mutate its immutable inputs" % path.name)

    def _space(self):
        base = Path(tempfile.mkdtemp(prefix="phase15-activation-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)


class StatusDerivation(_Scratch):
    def test_the_committed_status_reproduces_from_live_inputs(self) -> None:
        derived, problems = ops15.sync_status(write=False)
        self.assertEqual(problems, [])
        self.assertEqual(derived, ops15.load_json(ops15.STATUS_PATH),
                         "EXTERNAL_STATUS.json does not reproduce; run "
                         "sync-status and review the diff")

    def test_the_four_questions_stay_separate(self) -> None:
        status = ops15.load_json(ops15.STATUS_PATH)
        for key in ("operationalReadiness", "evidenceState",
                    "securityReview", "authorization"):
            self.assertIn(key, status)
        self.assertNotIn("overall", status)
        self.assertNotIn("green", json.dumps(status).lower())
        self.assertTrue(status["operationalReadiness"]["pipelineReady"])
        self.assertEqual(
            status["evidenceState"]["acceptedRealSecurityReviews"], 0)
        self.assertEqual(status["securityReview"]["gate"]["status"],
                         "AWAITING_EXTERNAL_EVIDENCE")
        self.assertEqual(status["authorization"]["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")
        self.assertFalse(status["authorization"]["authorized"])

    def test_the_values_are_derived_not_hard_coded(self) -> None:
        """The same derivation over a scratch universe with one accepted
        review reports different numbers — nothing is a constant."""
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        register = ops11.derive_register(_BASELINE, space.ledger(), _GRAPH,
                                         space.intake_root)
        derived = ops15.derive_external_status(
            ledger_bytes=space.ledger_bytes(),
            security_register=register,
            phase10_status=ops15.load_json(ops15.PHASE10_STATUS),
            phase13_status=ops15.load_json(ops15.PHASE13_STATUS),
            graph=_GRAPH, matrix=None, cuts=[],
            intake_root=space.intake_root)
        self.assertEqual(
            derived["evidenceState"]["acceptedRealSecurityReviews"], 1)
        self.assertEqual(derived["securityReview"]["receiptState"],
                         "RECONCILED")
        self.assertEqual(derived["securityReview"]["gate"]["status"],
                         "UNDER_ANALYSIS")
        self.assertEqual(derived["operationalReadiness"]["scenarios"], 0,
                         "no matrix handed in means zero scenarios, not a "
                         "hard-coded count")
        self.assertFalse(derived["operationalReadiness"]["pipelineReady"])

    def test_a_mutated_candidate_identity_fails_the_derivation(self) -> None:
        space = self._space()
        ledger = space.ledger()
        ledger["subjectArtifact"]["identifier"] = "someone-else"
        intake.dump_ledger(space.ledger_path, ledger)
        with self.assertRaises(ops15.BoundaryViolation) as caught:
            ops15.derive_external_status(
                ledger_bytes=space.ledger_bytes(),
                security_register={"securityGate": {}, "findings": []},
                phase10_status=ops15.load_json(ops15.PHASE10_STATUS),
                phase13_status=ops15.load_json(ops15.PHASE13_STATUS),
                graph=_GRAPH, matrix=None, cuts=[],
                intake_root=space.intake_root)
        self.assertIn("CANDIDATE IDENTITY FAIL", str(caught.exception))

    def test_every_matrix_row_is_a_fixture_demonstration(self) -> None:
        matrix = ops15.load_json(ops15.MATRIX_PATH)
        self.assertEqual(matrix["counts"]["scenarios"],
                         len(matrix["scenarios"]))
        for row in matrix["scenarios"]:
            self.assertEqual(row["evidenceClass"],
                             "FIXTURE_DEMONSTRATION_ONLY")
            self.assertEqual(row["realEvidenceStatus"],
                             "EXTERNAL_EVIDENCE_REQUIRED")
            self.assertEqual(row["result"], "AS_EXPECTED")


class NoFavorableStatusBySilence(_Scratch):
    def test_zero_external_evidence_is_not_authorized(self) -> None:
        committed = ops15.load_json(ops15.PHASE13_STATUS)
        assembly = ops14.assemble_decision(
            ops14.real_universe(), committed.get("evaluationDate"))
        self.assertNotEqual(assembly["authorizationState"], "AUTHORIZED")
        self.assertEqual(assembly["authorizationState"],
                         committed["authorizationState"])
        self.assertEqual(assembly["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")
        self.assertEqual(assembly["favorableEvidence"], [])

    def test_internal_tests_passing_changes_nothing(self) -> None:
        """This test suite running is itself the 'many internal tests'
        premise; the derivation afterwards still refuses."""
        committed = ops15.load_json(ops15.PHASE13_STATUS)
        first = ops14.assemble_decision(ops14.real_universe(),
                                        committed.get("evaluationDate"))
        second = ops14.assemble_decision(ops14.real_universe(),
                                         committed.get("evaluationDate"))
        self.assertEqual(first, second)
        self.assertNotEqual(first["authorizationState"], "AUTHORIZED")

    def test_no_reviewer_response_stays_awaiting(self) -> None:
        status = ops15.load_json(ops15.STATUS_PATH)
        self.assertEqual(status["securityReview"]["receiptState"],
                         "AWAITING_SUBMISSION")
        self.assertIn("blocks",
                      ops15.load_json(ops15.PHASE11_REGISTER)
                      ["securityGate"]["basis"])

    def test_the_floor_reports_all_five_sources_missing(self) -> None:
        status = ops15.load_json(ops15.STATUS_PATH)
        self.assertFalse(status["authorization"]["floorSatisfied"])
        missing = " ".join(status["authorization"]["floorMissing"])
        for source in ("security-review", "hardware", "signing",
                       "second-approval", "alpha-feedback"):
            self.assertIn(source, missing)


class AssemblyNegativeControls(_Scratch):
    def test_internal_json_claiming_authorized_is_refused(self) -> None:
        """An AUTHORIZED record over an empty ledger names the absent
        floor and never becomes standing."""
        space = self._space()
        record = ops14._inner("authorization-internal-authorized.json",
                              _ROOT / "qualification" / "phase13"
                              / "fixtures")
        record["evidence_cut"] = {
            "ledgerSha256": ops15._sha256(space.ledger_bytes()),
            "ledgerEntries": 0,
            "intakeIds": [],
        }
        sealed = dict(record)
        sealed["seal"] = ops13.seal_record(sealed)
        universe = ops14.build_universe(space, authorizations=[sealed])
        assembly = ops14.assemble_decision(universe, "2026-08-19")
        self.assertNotEqual(assembly["authorizationState"], "AUTHORIZED")
        rows = assembly["inputs"]["authorizations"]
        self.assertEqual(rows[0]["state"], "REFUSED")
        self.assertTrue(any("floor" in issue or "ACCEPTED intake" in issue
                            for issue in rows[0]["refusal"]))

    def test_one_satisfied_source_does_not_satisfy_the_floor(self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        missing = ops13.authorization_floor(space.ledger())
        self.assertEqual(len(missing), 4)
        joined = " ".join(missing)
        self.assertNotIn("security-review", joined)
        for source in ("hardware", "signing", "second-approval",
                       "alpha-feedback"):
            self.assertIn(source, joined)

    def test_fixture_material_cannot_reach_the_real_floor(self) -> None:
        """The real registration code, over a byte-copy of the real
        ledger: the marked wrapper is REJECTED and gate-eligible stays
        empty. The real file is untouched (class-level byte compare)."""
        space = self._space()
        space.ledger_path.write_bytes(ops15.PHASE9_LEDGER.read_bytes())
        entry = intake.register(
            space.ledger_path, "security-review",
            space.stage(_wrapper("review-approved-with-conditions.json")),
            [], "2026-08-19", "activation test")
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])
        self.assertEqual(len(ops13.authorization_floor(space.ledger())), 5)

    def test_a_reviewer_assignment_grants_no_other_authority(self) -> None:
        assignment = {
            "assignmentId": "ASSIGNMENT-901",
            "authorityId": "AUTH-SECURITY-REVIEWER",
            "identity": "Constructed Fixture Reviewer",
            "assignedBy": "constructed fixture",
            "date": "2026-08-19",
            "basis": "constructed fixture",
        }
        assignment["seal"] = ops13.seal_record(assignment)
        assigned = ops13.assigned_identities([assignment])
        self.assertIn("Constructed Fixture Reviewer",
                      assigned.get("AUTH-SECURITY-REVIEWER", set()))
        for other in ("AUTH-KEY", "AUTH-RELEASE", "AUTH-SECOND-APPROVER"):
            self.assertNotIn("Constructed Fixture Reviewer",
                             assigned.get(other, set()))

    def test_separation_of_duties_pairs_are_violations(self) -> None:
        def _assignment(number, authority):
            record = {
                "assignmentId": "ASSIGNMENT-%03d" % number,
                "authorityId": authority,
                "identity": "One Person",
                "assignedBy": "constructed fixture",
                "date": "2026-08-19",
                "basis": "constructed fixture",
            }
            record["seal"] = ops13.seal_record(record)
            return record

        violations = ops13.separation_violations(
            [_assignment(902, "AUTH-KEY"),
             _assignment(903, "AUTH-SECOND-APPROVER")], [])
        self.assertTrue(violations,
                        "a signer becoming second approver must violate "
                        "the separation policy")

    def test_expired_and_revoked_assignments_stop_acting(self) -> None:
        assignment = {
            "assignmentId": "ASSIGNMENT-904",
            "authorityId": "AUTH-SECURITY-OWNER",
            "identity": "Constructed Fixture Owner",
            "assignedBy": "constructed fixture",
            "date": "2026-08-01",
            "basis": "constructed fixture",
            "expires_at": "2026-08-31",
        }
        assignment["seal"] = ops13.seal_record(assignment)
        self.assertEqual(
            ops14.assignment_state(assignment, "2026-08-19"), "STANDING")
        self.assertEqual(
            ops14.assignment_state(assignment, "2026-09-01"), "EXPIRED")
        revocation = {
            "revocationId": "REVOCATION-901",
            "targetAssignment": "ASSIGNMENT-904",
            "reason": "constructed fixture",
            "authority": "constructed fixture",
            "timestamp": "2026-08-10",
        }
        self.assertEqual(
            ops14.assignment_state(assignment, "2026-08-19", [revocation]),
            "REVOKED")
        self.assertEqual(
            ops14.standing_assignments([assignment], "2026-08-19",
                                       [revocation]),
            [])


class FixtureIsolation(_Scratch):
    def test_every_fixture_carries_all_three_markers(self) -> None:
        names = sorted(p.name for p in _FIXTURES.glob("*.json"))
        self.assertTrue(names, "the fixtures directory must not be empty")
        for name in names:
            record = _wrapper(name)
            self.assertEqual(record.get("fixtureClass"), "TEST_FIXTURE_ONLY",
                             name)
            self.assertIs(record.get("fixture"), True, name)
            self.assertIs(record.get("test_fixture_only"), True, name)

    def test_any_single_marker_makes_a_record_a_fixture(self) -> None:
        for marker in ({"fixtureClass": "TEST_FIXTURE_ONLY"},
                       {"fixture": True},
                       {"test_fixture_only": True}):
            record = dict(_inner("review-blocked.json"), **marker)
            self.assertTrue(ops15.is_fixture(record))
            with self.assertRaises(ops15.BoundaryViolation):
                ops15.identity_ceremony(record)

    def test_the_inner_records_carry_no_marker(self) -> None:
        for path in sorted(_FIXTURES.glob("*.json")):
            self.assertFalse(ops15.is_fixture(_wrapper(path.name)["record"]),
                             "%s: the inner record is what a real reviewer "
                             "would send; a marker there would make the "
                             "valid-path demonstrations vacuous" % path.name)

    def test_the_real_intake_tree_carries_no_marker(self) -> None:
        self.assertEqual(
            [issue for issue in ops15.verify_fixtures()
             if "real" in issue], [])

    def test_the_scenarios_leave_every_real_input_byte_identical(
            self) -> None:
        before = {path: path.read_bytes()
                  for path in ops14.REAL_IMMUTABLE_INPUTS}
        derived = ops15.run_scenarios()
        self.assertTrue(derived["realLedgerByteIdentical"])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw,
                             "%s changed; the comparison is bytes, never "
                             "emptiness" % path.name)


class HandoffPackage(_Scratch):
    def test_prepare_review_pins_every_byte(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="phase15-handoff-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        out = base / "handoff"
        manifest = ops15.prepare_review(out)
        for name, pin in manifest["files"].items():
            raw = (out / name).read_bytes()
            self.assertEqual(len(raw), pin["bytes"], name)
            self.assertEqual(ops15._sha256(raw), pin["sha256"], name)
        self.assertTrue(manifest["createsNoReview"])
        self.assertIn("intake.py register", manifest["submissionDoor"])
        written = ops15.load_json(out / "HANDOFF_MANIFEST.json")
        self.assertEqual(written["files"], manifest["files"])

    def test_prepare_review_refuses_existing_and_in_repo_targets(
            self) -> None:
        base = Path(tempfile.mkdtemp(prefix="phase15-handoff-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        existing = base / "already-there"
        existing.mkdir()
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.prepare_review(existing)
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.prepare_review(_TRACK / "handoff-inside-repo")
        self.assertFalse((_TRACK / "handoff-inside-repo").exists())

    def test_the_handoff_states_the_unfavorable_rule(self) -> None:
        text = ops15._normalized_markdown(
            (_TRACK / "REVIEW_HANDOFF.md").read_text(encoding="utf-8"))
        self.assertIn(ops15.HANDOFF_REQUIRED_STATEMENT, text)

    def test_the_packaged_examples_are_marked_and_rejected(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="phase15-handoff-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        out = base / "handoff"
        ops15.prepare_review(out)
        space = self._space()
        for example in ops15.HANDOFF_EXAMPLES:
            packaged = json.loads((out / "examples" / example)
                                  .read_text(encoding="utf-8"))
            self.assertTrue(ops15.is_fixture(packaged), example)
            self.assertIn("TEST_FIXTURE_ONLY", packaged["warning"])
            self.assertIn("NOT EXTERNAL EVIDENCE", packaged["warning"])
            entry = space.register("security-review", packaged)
            self.assertEqual(entry["status"], "REJECTED", example)
            self.assertIn("fixture is never evidence",
                          entry["statusReason"])

    def test_the_packaged_validator_still_works(self) -> None:
        """VERIFY_SUBMISSION.py travels with the package and must pass a
        clean inner record and fail the marked wrapper, from the copy."""
        base = Path(tempfile.mkdtemp(prefix="phase15-handoff-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        out = base / "handoff"
        ops15.prepare_review(out)
        inner = base / "candidate-record.json"
        inner.write_text(json.dumps(
            _inner("review-approved-with-conditions.json"), indent=1),
            encoding="utf-8")
        clean = subprocess.run(
            [sys.executable, str(out / "VERIFY_SUBMISSION.py"), str(inner)],
            capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        marked = subprocess.run(
            [sys.executable, str(out / "VERIFY_SUBMISSION.py"),
             str(out / "examples" / ops15.HANDOFF_EXAMPLES[0])],
            capture_output=True, text=True)
        self.assertEqual(marked.returncode, 2,
                         "the marked example must never validate")


class MatrixAndVerify(_Scratch):
    def test_the_committed_matrix_reproduces_by_execution(self) -> None:
        self.assertEqual(ops15.matrix_problems(), [])

    def test_verify_all_is_clean(self) -> None:
        self.assertEqual(ops15.verify_all(), [])

    def test_the_verification_gate_exits_zero(self) -> None:
        result = subprocess.run([sys.executable, str(_VERIFY15)],
                                capture_output=True, text=True,
                                cwd=str(_ROOT))
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)
        self.assertIn("phase 15 verifies clean", result.stdout)

    def test_both_phase15_modules_are_inside_the_discovered_suite(
            self) -> None:
        """The Phase 5 undiscovered-directory trap, re-checked: counted
        with discover(), never by test id."""
        suite = unittest.defaultTestLoader.discover(
            str(_ROOT / "tests" / "release"), top_level_dir=str(_ROOT))
        self.assertEqual(unittest.defaultTestLoader.errors, [],
                         "discovery must not swallow an import error")
        names = set()

        def _walk(item):
            if isinstance(item, unittest.TestSuite):
                for child in item:
                    _walk(child)
            else:
                names.add(type(item).__module__)

        _walk(suite)
        self.assertIn("tests.release.test_phase15_review_execution", names)
        self.assertIn("tests.release.test_phase15_evidence_activation",
                      names)
        self.assertGreater(suite.countTestCases(), 554,
                           "the release suite must have grown past its "
                           "Phase 14 count")


if __name__ == "__main__":
    unittest.main()

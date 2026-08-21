# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The review workflow is executable, and no path through it can author
its own evidence.

Phase 15's engine is composition over Phases 9-14; these tests drive the
composed surface the way a real operator will: the receipt state machine
(which has no favorable state and no transition that can mint one), the
identity ceremony (which never fills the reviewer-observed field from
the repository's expectation), the one-door wrapper (which rejects
exactly what the Phase 9 boundary rejects, because the boundary is the
code path), revision and supersession (originals preserved byte for
byte), sealed evidence cuts (reproducible, append-only, post-cut
evidence named), conflict handling (most-blocking, no averaging, no
majority), Critical policy, and the time semantics inherited from
Phase 14.

The real ledger participates in nothing here: every class byte-compares
all real immutable inputs before and after — never their emptiness — so
the suite stays green on the day real evidence arrives.
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
_TRACK = _ROOT / "qualification" / "phase15" / "security-review-execution"
_OPS15_TOOL = _TRACK / "tools" / "review_execution_ops.py"
_VERIFY15 = _TRACK / "VERIFY_PHASE15.py"
_FIXTURES = _TRACK / "fixtures"
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_OPS11_TOOL = (_ROOT / "qualification" / "phase11" / "tools"
               / "security_review_ops.py")
_OPS13_TOOL = (_ROOT / "qualification" / "phase13" / "tools"
               / "release_authority_ops.py")
_FIXTURES13 = _ROOT / "qualification" / "phase13" / "fixtures"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops15 = _load("phase15_ops_under_test", _OPS15_TOOL)
intake = _load("phase9_intake_for_phase15_tests", _INTAKE_TOOL)
ops11 = _load("phase11_ops_for_phase15_tests", _OPS11_TOOL)
ops13 = _load("phase13_ops_for_phase15_tests", _OPS13_TOOL)
ops14 = ops15._phase14()

_BASELINE = json.loads(ops15.PHASE11_BASELINE.read_text(encoding="utf-8"))
_GRAPH = json.loads(ops15.PHASE10_GRAPH.read_text(encoding="utf-8"))
_IDENTITY = json.loads(ops15.PHASE11_IDENTITY.read_text(encoding="utf-8"))


def _inner(name: str) -> dict:
    return copy.deepcopy(json.loads(
        (_FIXTURES / name).read_text(encoding="utf-8"))["record"])


def _wrapper(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class _Scratch(unittest.TestCase):
    """Byte-compares every real immutable input around the class — the
    guarantee is byte identity, never emptiness."""

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
        base = Path(tempfile.mkdtemp(prefix="phase15-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)

    def _register_derived(self, space) -> dict:
        return ops11.derive_register(_BASELINE, space.ledger(), _GRAPH,
                                     space.intake_root)

    def _receipts(self, space, register=None, resolution=None, as_of=None):
        if register is None:
            register = self._register_derived(space)
        return ops15.derive_receipt_register(
            space.ledger(), register, space.intake_root, resolution, as_of)


class ReceiptMachine(_Scratch):
    def test_the_vocabulary_has_no_favorable_state(self) -> None:
        self.assertEqual(ops15.forbidden_vocabulary_problems(), [])
        for token in ("APPROVED", "SATISFIED", "AUTHORIZED", "PASS"):
            self.assertNotIn(token, ops15.RECEIPT_STATES)

    def test_received_to_approved_does_not_exist(self) -> None:
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receipt_transition("RECEIVED", "APPROVED")

    def test_accepted_cannot_transition_to_gate_satisfaction(self) -> None:
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receipt_transition("ACCEPTED_FOR_RECONCILIATION",
                                     "SATISFIED")
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receipt_transition("ACCEPTED_FOR_RECONCILIATION",
                                     "SECURITY_GATE_SATISFIED")

    def test_every_forbidden_transition_is_swept(self) -> None:
        """Absence is refusal for the whole cross product, executed."""
        for current in ops15.RECEIPT_STATES:
            allowed = ops15.RECEIPT_TRANSITIONS[current]
            for target in ops15.RECEIPT_STATES:
                if target in allowed:
                    self.assertEqual(
                        ops15.receipt_transition(current, target), target)
                else:
                    with self.assertRaises(ops15.BoundaryViolation):
                        ops15.receipt_transition(current, target)

    def test_zero_submissions_derive_awaiting_submission(self) -> None:
        receipts = self._receipts(self._space())
        self.assertEqual(receipts["overall"], "AWAITING_SUBMISSION")
        self.assertEqual(receipts["entries"], [])
        self.assertIn("absence blocks", receipts["basis"])

    def test_stored_statuses_map_to_receipt_states(self) -> None:
        space = self._space()
        record = _inner("review-approved-with-conditions.json")
        foreign = dict(record, artifact_digest="2" * 64,
                       artifactDigest="2" * 64,
                       independently_computed_digest="2" * 64)
        space.register("security-review", foreign)          # INTAKE-001
        incomplete = _inner("review-blocked.json")
        del incomplete["reviewer"]
        del incomplete["reviewer_id"]
        space.register("security-review", incomplete)       # INTAKE-002
        staged = space.staging / "not-json.json"
        staged.write_text("{ not json", encoding="utf-8")
        intake_mod = ops15._phase9()
        intake_mod.register(space.ledger_path, "security-review", staged,
                            [], "2026-08-19", "phase15 test")  # INTAKE-003
        space.register("security-review", record)           # INTAKE-004
        receipts = self._receipts(space)
        by_id = {r["intakeId"]: r["receiptState"]
                 for r in receipts["entries"]}
        self.assertEqual(by_id["INTAKE-001"], "DOES_NOT_APPLY")
        self.assertEqual(by_id["INTAKE-002"], "INCOMPLETE")
        self.assertEqual(by_id["INTAKE-003"], "UNVERIFIABLE")
        self.assertEqual(by_id["INTAKE-004"], "RECONCILED")
        self.assertEqual(receipts["overall"], "RECONCILED")

    def test_accepted_without_contract_validity_is_received(self) -> None:
        space = self._space()
        record = _inner("review-approved-with-conditions.json")
        del record["independently_computed_digest"]
        entry = space.register("security-review", record)
        self.assertEqual(entry["status"], "ACCEPTED")
        receipts = self._receipts(space)
        self.assertEqual(receipts["entries"][0]["receiptState"], "RECEIVED")

    def test_no_register_output_means_accepted_for_reconciliation(
            self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        receipts = ops15.derive_receipt_register(
            space.ledger(), None, space.intake_root)
        self.assertEqual(receipts["entries"][0]["receiptState"],
                         "ACCEPTED_FOR_RECONCILIATION")

    def test_expiring_record_requires_an_as_of(self) -> None:
        entry = {"intakeId": "INTAKE-001", "status": "ACCEPTED",
                 "gateEligible": True}
        record = {"expires_at": "2026-09-01"}
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receipt_state_of(entry, "ACCEPTED", record, [], False)
        self.assertEqual(
            ops15.receipt_state_of(entry, "ACCEPTED", record, [], False,
                                   as_of="2026-09-01"),
            "RECONCILED", "expiring exactly at the boundary still stands")
        self.assertEqual(
            ops15.receipt_state_of(entry, "ACCEPTED", record, [], False,
                                   as_of="2026-09-02"),
            "EXPIRED")

    def test_conflict_derives_a_human_decision_requirement(self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register_derived(space)
        receipts = self._receipts(space, register)
        self.assertEqual(receipts["overall"], "CONFLICT_REQUIRES_DECISION")
        resolution = ops15.apply_conflict_resolution(
            register["reviewConflict"], "REMEDIATION_REQUIRED")
        resolved = self._receipts(space, register, resolution)
        states = {r["receiptState"] for r in resolved["entries"]}
        self.assertEqual(states, {"RECONCILED"})

    def test_a_resolution_outside_the_vocabulary_is_refused(self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register_derived(space)
        # Every engine's BoundaryViolation subclasses ValueError, and the
        # refusal may come from the engine's own Phase 11 instance.
        with self.assertRaises(ValueError):
            ops15.apply_conflict_resolution(register["reviewConflict"],
                                            "APPROVED")

    def test_resolving_a_nonexistent_conflict_is_refused(self) -> None:
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.apply_conflict_resolution(None, "REMEDIATION_REQUIRED")


class IdentityCeremony(_Scratch):
    def test_a_stated_measurement_is_verified(self) -> None:
        verdict = ops15.identity_ceremony(
            _inner("review-approved-with-conditions.json"), _IDENTITY)
        self.assertEqual(verdict["state"], "VERIFIED")
        self.assertTrue(verdict["artifactSpecificAdvancement"])

    def test_a_missing_observation_is_missing(self) -> None:
        record = _inner("review-approved-with-conditions.json")
        del record["independently_computed_digest"]
        verdict = ops15.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "MISSING")
        self.assertFalse(verdict["artifactSpecificAdvancement"])
        self.assertIsNone(verdict["observedDigest"])

    def test_foreign_bytes_are_a_mismatch(self) -> None:
        record = _inner("review-approved-with-conditions.json")
        record["independently_computed_digest"] = "3" * 64
        verdict = ops15.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "MISMATCH")
        self.assertFalse(verdict["artifactSpecificAdvancement"])

    def test_the_expected_digest_substituted_for_an_absent_observation_is_insufficient(
            self) -> None:
        """The §10 negative control: mechanically copying the repository's
        expected digest into an absent observation must not verify."""
        record = _inner("review-approved-with-conditions.json")
        del record["independently_computed_digest"]
        del record["digest_basis"]
        del record["digest_computation"]
        record["independently_computed_digest"] = \
            _IDENTITY["subjectArtifact"]["imageDigest"]
        verdict = ops15.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "OBSERVED_UNVERIFIED")
        self.assertFalse(verdict["artifactSpecificAdvancement"])
        self.assertIn("copied expectation", verdict["basis"])

    def test_the_ceremony_never_mutates_the_record(self) -> None:
        record = _inner("review-blocked.json")
        del record["independently_computed_digest"]
        before = copy.deepcopy(record)
        ops15.identity_ceremony(record, _IDENTITY)
        self.assertEqual(record, before,
                         "the ceremony wrote into the record; the observed "
                         "field must never be filled by the repository")

    def test_a_fixture_record_is_refused(self) -> None:
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.identity_ceremony(
                _wrapper("review-approved-with-conditions.json"), _IDENTITY)

    def test_the_vocabulary_matches_phase12(self) -> None:
        ops12 = ops15._phase12()
        self.assertEqual(tuple(ops15.IDENTITY_CEREMONY_STATES),
                         tuple(ops12.IDENTITY_STATES))


class OneDoorWrapper(_Scratch):
    def test_receive_registers_through_the_real_boundary(self) -> None:
        space = self._space()
        staged = space.stage(_inner("review-approved-with-conditions.json"))
        entry = ops15.receive(staged, [], "2026-08-19", "phase15 test",
                              ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "ACCEPTED")
        ledger = space.ledger()
        self.assertEqual(ledger["entries"][0]["intakeId"], entry["intakeId"])
        self.assertEqual(intake.seal_entry(ledger["entries"][0]),
                         ledger["entries"][0]["seal"])

    def test_the_wrapper_rejects_what_the_boundary_rejects(self) -> None:
        """Equivalence, executed per refusal class on identical bytes."""
        record = _inner("review-approved-with-conditions.json")
        # Constructed at run time so no secret-shaped bytes are committed.
        record["notes"] = "api_" + "key = " + "Qx7" * 8
        space_a, space_b = self._space(), self._space()
        direct = intake.register(space_a.ledger_path, "security-review",
                                 space_a.stage(record), [], "2026-08-19",
                                 "direct")
        wrapped = ops15.receive(space_b.stage(record), [], "2026-08-19",
                                "wrapped", ledger_path=space_b.ledger_path)
        self.assertEqual(direct["status"], "REJECTED")
        self.assertEqual(wrapped["status"], direct["status"])
        self.assertEqual(wrapped["files"], {})
        self.assertFalse(
            (space_b.intake_root / "security-review"
             / wrapped["intakeId"]).exists(),
            "credential refusal must precede ingestion")

    def test_the_wrapper_rejects_a_private_key_attachment(self) -> None:
        space = self._space()
        staged = space.stage(_inner("review-approved-with-conditions.json"))
        key = space.staging / "key.txt"
        key.write_text("-----BEGIN " + "EC PRIVATE KEY-----\nA\n",
                       encoding="utf-8")
        entry = ops15.receive(staged, [key], "2026-08-19", "phase15 test",
                              ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("private key material", entry["statusReason"])
        self.assertEqual(entry["files"], {})

    def test_the_wrapper_rejects_a_fixture_marker(self) -> None:
        space = self._space()
        staged = space.stage(_wrapper("review-blocked.json"))
        entry = ops15.receive(staged, [], "2026-08-19", "phase15 test",
                              ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])

    def test_the_wrapper_refuses_missing_paths(self) -> None:
        space = self._space()
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receive(space.staging / "absent.json", [], "2026-08-19",
                          "x", ledger_path=space.ledger_path)
        staged = space.stage(_inner("review-blocked.json"))
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.receive(staged, [space.staging / "absent-attachment"],
                          "2026-08-19", "x", ledger_path=space.ledger_path)

    def test_the_wrapper_refuses_a_tampered_ledger(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        ledger = space.ledger()
        ledger["entries"][0]["statusReason"] = "edited by hand"
        intake.dump_ledger(space.ledger_path, ledger)
        staged = space.stage(_inner("review-approved-with-conditions.json"))
        with self.assertRaises(SystemExit):
            ops15.receive(staged, [], "2026-08-19", "phase15 test",
                          ledger_path=space.ledger_path)

    def test_the_engine_has_no_append_code(self) -> None:
        source = _OPS15_TOOL.read_text(encoding="utf-8")
        self.assertNotIn('"entries"].append', source)
        self.assertNotIn("entries.append", source)
        self.assertEqual(source.count("dump_ledger("),
                         source.count("dump_ledger(space.ledger_path"),
                         "the engine may write only scratch ledgers, "
                         "never the real one")


class RevisionAndSupersession(_Scratch):
    def test_a_valid_revision_supersedes_without_overwrite(self) -> None:
        space = self._space()
        original = space.register("security-review",
                                  _inner("review-approved-with-conditions.json"))
        original_path = (space.intake_root / "security-review"
                         / original["intakeId"] / "record.json")
        before = original_path.read_bytes()
        corrected = _inner("review-approved-with-conditions.json")
        corrected["scope"] += " (revision)"
        revision = space.register("security-review", corrected,
                                  revises=original["intakeId"])
        self.assertEqual(revision["intakeId"], "INTAKE-001-R1")
        self.assertEqual(original_path.read_bytes(), before)
        effective = intake.effective_statuses(space.ledger())
        self.assertEqual(effective["INTAKE-001"], "SUPERSEDED")
        self.assertEqual(effective["INTAKE-001-R1"], "ACCEPTED")

    def test_a_rejected_submission_recovers_through_a_revision(self) -> None:
        space = self._space()
        rejected = space.register("security-review",
                                  _wrapper("review-blocked.json"))
        self.assertEqual(rejected["status"], "REJECTED")
        revision = space.register("security-review",
                                  _inner("review-blocked.json"),
                                  revises=rejected["intakeId"])
        self.assertEqual(revision["status"], "ACCEPTED")
        effective = intake.effective_statuses(space.ledger())
        self.assertEqual(effective[rejected["intakeId"]], "SUPERSEDED")

    def test_a_mismatch_recovers_through_a_correct_artifact_revision(
            self) -> None:
        space = self._space()
        wrong = _inner("review-blocked.json")
        wrong["artifact_digest"] = "4" * 64
        wrong["artifactDigest"] = "4" * 64
        wrong["independently_computed_digest"] = "4" * 64
        mismatch = space.register("security-review", wrong)
        self.assertEqual(mismatch["status"], "ARTIFACT_MISMATCH")
        revision = space.register("security-review",
                                  _inner("review-blocked.json"),
                                  revises=mismatch["intakeId"])
        self.assertEqual(revision["status"], "ACCEPTED")
        self.assertTrue(revision["gateEligible"])

    def test_revising_a_nonexistent_intake_refuses(self) -> None:
        space = self._space()
        with self.assertRaises(SystemExit):
            space.register("security-review", _inner("review-blocked.json"),
                           revises="INTAKE-041")

    def test_altering_immutable_source_bytes_is_detected(self) -> None:
        space = self._space()
        entry = space.register("security-review",
                               _inner("review-blocked.json"))
        record_path = (space.intake_root / "security-review"
                       / entry["intakeId"] / "record.json")
        record_path.write_text("{}", encoding="utf-8")
        issues = intake.verify_intake(space.intake_root, space.ledger())
        self.assertTrue(issues.get("fileChanged"),
                        "a rewritten source file must break its pin")

    def test_supersession_after_a_cut_leaves_the_cut_sealed(self) -> None:
        space = self._space()
        original = space.register("security-review",
                                  _inner("review-approved-with-conditions.json"))
        frozen = space.ledger_bytes()
        cut = ops14.build_evidence_cut(
            ledger_bytes=frozen, graph_bytes=ops15.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")
        space.register("security-review", _inner("review-blocked.json"),
                       revises=original["intakeId"])
        self.assertEqual(ops14.verify_cut(cut), [])
        comparison = ops14.compare_cut_to_ledger(cut, space.ledger_bytes())
        self.assertEqual(comparison["postCutIntakeIds"], ["INTAKE-001-R1"])
        replay = ops14.build_evidence_cut(
            ledger_bytes=frozen, graph_bytes=ops15.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")
        self.assertEqual(replay, cut,
                         "the historical cut must re-derive exactly as "
                         "sealed from its own inputs")


class EvidenceCuts(_Scratch):
    def _cut(self, ledger_bytes, **overrides):
        kwargs = dict(
            ledger_bytes=ledger_bytes,
            graph_bytes=ops15.PHASE10_GRAPH.read_bytes(),
            security_register_bytes=b"{}", alpha_register_bytes=b"{}",
            assignments=[], policies=[], risks=[], authorizations=[],
            revocations=[], resolutions=[], as_of="2026-08-19")
        kwargs.update(overrides)
        return ops14.build_evidence_cut(**kwargs)

    def test_same_inputs_and_boundary_derive_byte_identical_cuts(
            self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        raw = space.ledger_bytes()
        first, second = self._cut(raw), self._cut(raw)
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")))

    def test_as_of_is_mandatory_once_an_expiring_record_exists(self) -> None:
        space = self._space()
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        risk["seal"] = ops13.seal_record(risk)
        with self.assertRaises(ops14.BoundaryViolation):
            self._cut(space.ledger_bytes(), risks=[risk], as_of=None)

    def test_a_real_cut_label_is_validated_and_append_only(self) -> None:
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.build_real_cut("latest", None)
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.build_real_cut("CUT-1", None)
        record = ops15.build_real_cut("CUT-001", "2026-08-19")
        with self.assertRaises(ops15.BoundaryViolation):
            ops15.write_cut(record)  # CUT-001.json is already committed

    def test_the_committed_cut_reproduces_and_identifies_zero_evidence(
            self) -> None:
        committed = ops15.load_json(ops15.CUTS_DIR / "CUT-001.json")
        rebuilt = ops15.build_real_cut("CUT-001",
                                       committed["cut"]["asOf"])
        self.assertEqual(rebuilt["cut"], committed["cut"],
                         "CUT-001 must re-derive byte-identical while its "
                         "inputs are unchanged")
        self.assertEqual(committed["cut"]["ledgerEntries"], 0)
        self.assertEqual(committed["cut"]["intakeIds"], [])
        self.assertEqual(committed["cut"]["gateEligibleAccepted"], [])
        self.assertEqual(ops14.verify_cut(committed["cut"]), [])

    def test_a_tampered_cut_breaks_its_seal(self) -> None:
        committed = ops15.load_json(ops15.CUTS_DIR / "CUT-001.json")
        tampered = copy.deepcopy(committed["cut"])
        tampered["ledgerEntries"] = 999
        issues = ops14.verify_cut(tampered)
        self.assertTrue(any("IMMUTABILITY" in issue or "seal" in issue
                            for issue in issues),
                        "a tampered cut must fail its seal check: %r"
                        % issues)

    def test_cut_problems_is_clean_on_the_committed_tree(self) -> None:
        self.assertEqual(ops15.cut_problems(), [])


class ConflictHandling(_Scratch):
    def test_contradictory_reviews_require_a_human_decision(self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register_derived(space)
        conflict = register["reviewConflict"]
        self.assertEqual(conflict["classification"],
                         "CONTRADICTORY_CONCLUSIONS")
        self.assertEqual(conflict["effectiveAssessment"], "BLOCKED")
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")
        self.assertEqual(conflict["resolution"], "RESOLUTION_REQUIRED")

    def test_no_majority_vote_exists(self) -> None:
        """Two favorable against one blocking still blocks — executed."""
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        second = _inner("review-approved-with-conditions.json")
        second["reviewer_id"] = "REVIEWER-EX9"
        second["reviewer"] = "REVIEWER-EX9"
        space.register("security-review", second)
        space.register("security-review", _inner("review-blocked.json"))
        register = self._register_derived(space)
        self.assertEqual(register["reviewConflict"]["effectiveAssessment"],
                         "BLOCKED",
                         "two PASS never beats one FAIL")
        self.assertEqual(register["securityGate"]["status"], "BLOCKED")

    def test_a_local_operation_cannot_overrule_an_unfavorable_finding(
            self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        first = self._register_derived(space)
        self.assertEqual(first["securityGate"]["status"], "BLOCKED")
        again = self._register_derived(space)
        self.assertEqual(again, first,
                         "re-running a local derivation must change "
                         "nothing about an external result")

    def test_an_expired_favorable_authority_confers_nothing(self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        self.assertEqual(ops13.risk_acceptance_state(risk,
                                                     risk["expires_at"]),
                         "STANDING")
        self.assertEqual(ops13.risk_acceptance_state(risk, "2027-01-01"),
                         "EXPIRED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.risk_acceptance_state(risk, None)

    def test_revocation_affects_later_cuts_without_rewriting_earlier_ones(
            self) -> None:
        space = self._space()
        universe, record = ops14.authorized_universe(space)
        earlier = ops14.assemble_decision(universe, "2026-08-19")
        self.assertEqual(earlier["authorizationState"], "AUTHORIZED")
        revocation = {
            "revocation_id": "REVOCATION-001",
            "target_authorization": record["authorization_id"],
            "artifact_digest": record["artifact_digest"],
            "reason": "constructed fixture: revoked after the earlier cut",
            "authority": "Constructed Fixture Release Authority",
            "timestamp": "2026-09-01",
            "evidence": "constructed fixture",
        }
        revocation["seal"] = ops13.seal_record(revocation)
        revoked_universe = dict(universe, revocations=[revocation])
        later = ops14.assemble_decision(revoked_universe, "2026-09-02")
        self.assertEqual(later["authorizationState"], "REVOKED")
        replay = ops14.assemble_decision(universe, "2026-08-19")
        self.assertEqual(replay["authorizationState"], "AUTHORIZED",
                         "the earlier cut re-derives from its own inputs; "
                         "revocation rewrites nothing")

    def test_conflicting_dispositions_on_one_critical_hold_the_row(
            self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-blocked.json"))
        clearing = _inner("review-blocked.json")
        clearing["reviewer_id"] = "REVIEWER-EX8"
        clearing["reviewer"] = "REVIEWER-EX8"
        clearing["findings"][0].update(
            applicability="NOT_APPLICABLE",
            recommended_disposition="NOT_APPLICABLE",
            evidence="constructed fixture: the reaching path is compiled "
                     "out on this artifact",
            rationale="constructed fixture: not reachable as shipped")
        space.register("security-review", clearing)
        register = self._register_derived(space)
        row = next(r for r in register["findings"]
                   if r["source_finding_id"] == "GHSA-5cgq-3rg8-m6cv")
        self.assertEqual(row["reconciliation"], "EVIDENCE_CONFLICT")
        self.assertEqual(row["status"], "UNDER_REVIEW",
                         "conflicting dispositions hold; nothing averages")


class CriticalPolicy(_Scratch):
    def test_a_confirmed_unresolved_critical_blocks_the_gate(self) -> None:
        space = self._space()
        space.register("security-review",
                       _inner("review-approved-with-conditions.json"))
        register = self._register_derived(space)
        self.assertNotEqual(register["securityGate"]["status"], "SATISFIED")
        row = next(r for r in register["findings"]
                   if r["source_finding_id"] == "GHSA-5cgq-3rg8-m6cv")
        self.assertEqual(row["status"], "CONFIRMED")
        self.assertIn(row["internal_id"],
                      ops11.critical_disposition_gaps(register["findings"]))

    def test_not_applicable_without_analysis_refuses(self) -> None:
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(
                {"status": "UNDER_REVIEW"}, "NOT_APPLICABLE",
                {"applicabilityEvidence": {"reference": "",
                                           "analysis": ""}})

    def test_accepted_risk_without_authority_is_ineffective(self) -> None:
        space = self._space()
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        issues = ops13.validate_risk_acceptance(
            risk, [], intake.subject_digests(space.ledger()),
            {fid: "Critical" for fid in risk["finding_ids"]})
        self.assertTrue(issues,
                        "no standing authority means no effective "
                        "acceptance")

    def test_a_valid_acceptance_is_effective_only_within_its_window(
            self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        self.assertEqual(ops13.risk_acceptance_state(risk, "2026-08-19"),
                         "STANDING")
        self.assertEqual(ops13.risk_acceptance_state(risk, "2026-12-01"),
                         "EXPIRED")

    def test_a_new_critical_blocks_until_resolved(self) -> None:
        space = self._space()
        space.register("security-review", _inner("review-new-critical.json"))
        register = self._register_derived(space)
        self.assertEqual(register["counts"]["fromEvidence"], 1)
        self.assertNotEqual(register["securityGate"]["status"], "SATISFIED")
        self.assertIn("EX3-N1", register["securityGate"]["basis"],
                      "the new Critical is named by the reviewer's own "
                      "identifier — the Phase 11 repair's guard")

    def test_accepted_risk_transition_needs_the_full_record(self) -> None:
        with self.assertRaises(ops11.BoundaryViolation):
            ops11.security_finding_transition(
                {"status": "CONFIRMED"}, "ACCEPTED_RISK",
                {"acceptance": {"decisionAuthority": "someone"}})


class TimeSemantics(_Scratch):
    def test_future_dated_evidence_fails_closed(self) -> None:
        problems = ops14.time_consistency_problems(
            record_dates={"date": "2027-01-01"}, received_on="2026-08-19")
        self.assertTrue(any("postdates" in p for p in problems))

    def test_an_ambiguous_time_basis_fails_closed(self) -> None:
        problems = ops14.time_consistency_problems(
            record_dates={"date": "2026-08-01", "review_end": "2026-08-02"},
            received_on="2026-08-19")
        self.assertTrue(any("ambiguous" in p for p in problems))

    def test_an_unparseable_date_fails_closed(self) -> None:
        problems = ops14.time_consistency_problems(
            record_dates={"date": "sometime in august"},
            received_on="2026-08-19")
        self.assertTrue(any("fails" in p and "closed" in p
                            for p in problems))

    def test_authority_expiring_around_a_cut_boundary(self) -> None:
        risk = ops14._inner("risk-acceptance-critical.json", _FIXTURES13)
        risk["expires_at"] = "2026-08-18"
        self.assertEqual(ops13.risk_acceptance_state(risk, "2026-08-19"),
                         "EXPIRED", "expiring exactly before the cut")
        risk["expires_at"] = "2026-08-19"
        self.assertEqual(ops13.risk_acceptance_state(risk, "2026-08-19"),
                         "STANDING", "expiring exactly at the cut still "
                         "stands at that cut")

    def test_the_engine_reads_no_clock(self) -> None:
        for path in (_OPS15_TOOL, _VERIFY15):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("datetime.now", "date.today", "time.time(",
                              "utcnow"):
                self.assertNotIn(forbidden, source,
                                 "%s reads a clock via %s"
                                 % (path.name, forbidden))


if __name__ == "__main__":
    unittest.main()

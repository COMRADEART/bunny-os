# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 16 receipt, inspection, validation, identity, and one-door guards.

Every submission here is the unmarked inner payload of a committed
TEST_FIXTURE_ONLY wrapper and runs only in a temporary Phase 9 universe. The
real evidence universe is byte-compared around each class; the invariant is
identity, never emptiness, so these tests remain valid after real evidence
arrives.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_PHASE16 = _ROOT / "qualification" / "phase16"
_OPS16_TOOL = _PHASE16 / "tools" / "security_review_intake_ops.py"
_VERIFY16 = _PHASE16 / "tools" / "verify_phase16.py"
_FIXTURES = _PHASE16 / "fixtures"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops16 = _load("phase16_intake_ops_under_test", _OPS16_TOOL)
intake = ops16._phase9()
ops10 = ops16._phase10()
ops11 = ops16._phase11()
ops13 = ops16._phase13()
ops14 = ops16._phase14()

_GRAPH = ops16.load_json(ops16.PHASE10_GRAPH)
_IDENTITY = ops16.load_json(ops16.PHASE11_IDENTITY)


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
                    "%s changed during Phase 16 scratch intake tests"
                    % path.name)

    def _space(self):
        base = Path(tempfile.mkdtemp(prefix="phase16-intake-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return ops14.RehearsalSpace(base)

    def _json_file(self, payload: dict, name: str = "record.json") -> Path:
        base = Path(tempfile.mkdtemp(prefix="phase16-inspection-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        path = base / name
        path.write_text(json.dumps(payload, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
        return path


class ReceiptStateMachine(_Scratch):
    def test_the_vocabulary_contains_no_favorable_receipt_word(self) -> None:
        self.assertEqual(ops16.forbidden_vocabulary_problems(), [])
        self.assertIn("ACCEPTED", ops16.RECEIPT_STATES)
        self.assertNotIn("APPROVED", ops16.RECEIPT_STATES)
        for token in ops16.FORBIDDEN_RECEIPT_TOKENS:
            for state in ops16.RECEIPT_STATES:
                self.assertNotIn(token, state)

    def test_the_complete_forbidden_transition_cross_product_executes(
            self) -> None:
        for current in ops16.RECEIPT_STATES:
            allowed = ops16.RECEIPT_TRANSITIONS[current]
            for target in ops16.RECEIPT_STATES:
                with self.subTest(current=current, target=target):
                    if target in allowed:
                        revision = ("INTAKE-001" if current in
                                    ops16.REENTRY_REQUIRES_REVISION else None)
                        self.assertEqual(ops16.receipt_transition(
                            current, target, revision), target)
                    else:
                        with self.assertRaises(ops16.BoundaryViolation):
                            ops16.receipt_transition(current, target,
                                                     "INTAKE-001")

    def test_a_refused_receipt_cannot_reenter_without_a_revision(self) -> None:
        for state in ops16.REENTRY_REQUIRES_REVISION:
            with self.subTest(state=state), self.assertRaises(
                    ops16.BoundaryViolation):
                ops16.receipt_transition(state, "RECEIVED")

    def test_approved_and_gate_states_cannot_be_minted(self) -> None:
        for target in ("APPROVED", "SATISFIED", "AUTHORIZED",
                       "SECURITY_GATE_PASS"):
            with self.subTest(target=target), self.assertRaises(
                    ops16.BoundaryViolation):
                ops16.receipt_transition("AWAITING_SUBMISSION", target)

    def test_zero_scratch_submissions_derive_awaiting(self) -> None:
        register = ops16.derive_receipt_register(self._space().ledger())
        self.assertEqual(register["overall"], "AWAITING_SUBMISSION")
        self.assertEqual(register["entries"], [])
        self.assertIn("absence blocks", register["basis"])

    def test_every_phase9_outcome_maps_to_a_boundary_receipt(self) -> None:
        space = self._space()
        foreign = _inner()
        for field in ("artifact_digest", "artifactDigest",
                      "independently_computed_digest"):
            foreign[field] = "6" * 64
        space.register("security-review", foreign)
        incomplete = _inner()
        del incomplete["reviewer"]
        space.register("security-review", incomplete)
        malformed = space.staging / "malformed.json"
        malformed.write_text("{not json", encoding="utf-8")
        intake.register(space.ledger_path, "security-review", malformed, [],
                        "2026-08-19", "phase16 test")
        space.register("security-review", _wrapper())
        space.register("security-review", _inner())
        derived = ops16.derive_receipt_register(space.ledger())
        by_id = {row["intakeId"]: row["receiptState"]
                 for row in derived["entries"]}
        self.assertEqual(by_id, {
            "INTAKE-001": "DOES_NOT_APPLY",
            "INTAKE-002": "INCOMPLETE",
            "INTAKE-003": "UNVERIFIABLE",
            "INTAKE-004": "REJECTED",
            "INTAKE-005": "ACCEPTED",
        })
        self.assertEqual(derived["overall"], "ACCEPTED")

    def test_revision_preserves_the_original_and_derives_supersession(
            self) -> None:
        space = self._space()
        incomplete = _inner()
        del incomplete["reviewer"]
        original = space.register("security-review", incomplete)
        original_path = (space.intake_root / "security-review"
                         / original["intakeId"] / "record.json")
        original_bytes = original_path.read_bytes()
        revision = space.register("security-review", _inner(),
                                  revises=original["intakeId"])
        self.assertEqual(revision["intakeId"], "INTAKE-001-R1")
        self.assertEqual(original_path.read_bytes(), original_bytes)
        rows = {row["intakeId"]: row["receiptState"] for row in
                ops16.derive_receipt_register(space.ledger())["entries"]}
        self.assertEqual(rows["INTAKE-001"], "SUPERSEDED")
        self.assertEqual(rows["INTAKE-001-R1"], "ACCEPTED")


class ProspectiveInspection(_Scratch):
    def test_a_valid_shape_passes_inspection_but_is_not_accepted(self) -> None:
        report = ops16.inspect_submission(self._json_file(_inner()))
        self.assertEqual(report["classification"], "STRUCTURALLY_VALID")
        self.assertTrue(report["inspectionPassed"])
        self.assertEqual(report["receiptState"], "RECEIVED")
        self.assertIn("not evidence accepted", report["note"])

    def test_all_required_inspection_failure_classes_execute(self) -> None:
        cases = []
        incomplete = _inner()
        del incomplete["independently_computed_digest"]
        cases.append(("INCOMPLETE", self._json_file(incomplete,
                                                     "incomplete.json"), []))
        malformed = self._json_file({}, "malformed.json")
        malformed.write_text("{ no", encoding="utf-8")
        cases.append(("MALFORMED", malformed, []))
        foreign = _inner()
        for field in ("artifact_digest", "artifactDigest",
                      "independently_computed_digest"):
            foreign[field] = "7" * 64
        cases.append(("WRONG_ARTIFACT", self._json_file(
            foreign, "foreign.json"), []))
        ambiguous = _inner()
        ambiguous["artifactDigest"] = "8" * 64
        cases.append(("AMBIGUOUS_IDENTITY", self._json_file(
            ambiguous, "ambiguous.json"), []))
        credential = _inner()
        credential["notes"] = {"nested": {"auth_token": "P16" * 8}}
        cases.append(("CREDENTIAL_BEARING", self._json_file(
            credential, "credential.json"), []))
        cases.append(("FIXTURE_MARKED", self._json_file(
            _wrapper(), "fixture.json"), []))
        cases.append(("UNSUPPORTED_EVIDENCE_SHAPE", self._json_file(
            _wrapper("review-unsupported-shape.json")["record"],
            "unsupported.json"), []))
        for expected, path, attachments in cases:
            with self.subTest(expected=expected):
                report = ops16.inspect_submission(path, attachments)
                self.assertEqual(report["classification"], expected)
                self.assertFalse(report["inspectionPassed"])

    def test_an_attachment_credential_is_named_without_the_value(self) -> None:
        record_path = self._json_file(_inner())
        attachment = record_path.parent / "support.log"
        secret = "Bearer " + ("Qx7" * 8)
        attachment.write_text(secret, encoding="utf-8")
        report = ops16.inspect_submission(record_path, [attachment])
        self.assertEqual(report["classification"], "CREDENTIAL_BEARING")
        self.assertIn("support.log", report["basis"])
        self.assertIn("bearer token", report["basis"])
        self.assertNotIn(secret, json.dumps(report))

    def test_inspection_never_touches_a_ledger(self) -> None:
        space = self._space()
        before = space.ledger_bytes()
        ops16.inspect_submission(space.stage(_inner()))
        self.assertEqual(space.ledger_bytes(), before)


class IdentityCeremony(_Scratch):
    def test_exact_independent_match_is_verified(self) -> None:
        verdict = ops16.identity_ceremony(_inner(), _IDENTITY)
        self.assertEqual(verdict["state"], "VERIFIED")
        self.assertTrue(verdict["artifactSpecificAdvancement"])

    def test_missing_observation_is_missing(self) -> None:
        record = _inner()
        del record["independently_computed_digest"]
        verdict = ops16.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "MISSING")
        self.assertFalse(verdict["artifactSpecificAdvancement"])

    def test_wrong_observation_is_mismatch(self) -> None:
        record = _inner()
        record["independently_computed_digest"] = "9" * 64
        verdict = ops16.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "MISMATCH")
        self.assertFalse(verdict["artifactSpecificAdvancement"])

    def test_expected_digest_without_measurement_is_never_verified(
            self) -> None:
        record = _inner()
        del record["digest_basis"]
        del record["digest_computation"]
        record["independently_computed_digest"] = \
            _IDENTITY["subjectArtifact"]["imageDigest"]
        verdict = ops16.identity_ceremony(record, _IDENTITY)
        self.assertEqual(verdict["state"], "OBSERVED_UNVERIFIED")
        self.assertFalse(verdict["artifactSpecificAdvancement"])

    def test_malformed_and_ambiguous_observations_fail_closed(self) -> None:
        for value in (["a", "b"], "two possible digests", "abc",
                      "a" * 64 + "\nnot-a-second-identity"):
            with self.subTest(value=value), self.assertRaises(
                    ops16.BoundaryViolation):
                ops16.identity_ceremony(
                    {"independently_computed_digest": value}, _IDENTITY)

    def test_commit_identity_is_not_artifact_identity(self) -> None:
        record = {"sourceCommit":
                  _IDENTITY["subjectArtifact"]["sourceCommit"]}
        result = ops16.bind_record(record, "commit-only")
        self.assertEqual(result["result"], "ARTIFACT_MISMATCH")
        self.assertIn("no artifact digest", result["reasoning"])

    def test_the_ceremony_never_mutates_the_review(self) -> None:
        record = _inner()
        before = copy.deepcopy(record)
        ops16.identity_ceremony(record, _IDENTITY)
        self.assertEqual(record, before)


class ValidationBoundary(_Scratch):
    def test_complete_valid_and_accepted_are_distinct_facts(self) -> None:
        record = _inner()
        verdict = ops16.validate_submission_record(record)
        self.assertTrue(verdict["complete"])
        self.assertTrue(verdict["contractValid"])
        self.assertTrue(verdict["valid"])
        self.assertNotIn("accepted", verdict,
                         "validation must not invent an intake outcome")
        space = self._space()
        entry = space.register("security-review", record)
        self.assertEqual(entry["status"], "ACCEPTED")

    def test_phase9_acceptance_does_not_make_an_incomplete_contract_valid(
            self) -> None:
        record = _inner()
        del record["independently_computed_digest"]
        verdict = ops16.validate_submission_record(record)
        self.assertFalse(verdict["complete"])
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["identityCeremony"]["state"], "MISSING")
        self.assertEqual(self._space().register(
            "security-review", record)["status"], "ACCEPTED")

    def test_attachment_integrity_matches_and_mismatch_refuses(self) -> None:
        record = _inner()
        path = self._json_file(record).parent / "analysis.txt"
        path.write_text("constructed non-secret analysis\n", encoding="utf-8")
        record["attachmentDigests"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
        self.assertTrue(ops16.validate_submission_record(
            record, [path])["valid"])
        path.write_text("changed\n", encoding="utf-8")
        verdict = ops16.validate_submission_record(record, [path])
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("does not match" in problem for problem in
                            verdict["attachmentProblems"]))

    def test_missing_and_duplicate_attachment_names_refuse(self) -> None:
        record = _inner()
        record["attachmentDigests"] = {"analysis.txt": "0" * 64}
        verdict = ops16.validate_submission_record(record, [])
        self.assertFalse(verdict["valid"])
        self.assertIn("not attached", verdict["attachmentProblems"][0])
        first = self._json_file({}, "same.txt")
        second_dir = Path(tempfile.mkdtemp(prefix="phase16-duplicate-"))
        self.addCleanup(shutil.rmtree, second_dir, ignore_errors=True)
        second = second_dir / "same.txt"
        second.write_text("x", encoding="utf-8")
        self.assertTrue(any("duplicate" in p for p in
                            ops16.attachment_integrity_problems(
                                _inner(), [first, second])))

    def test_nested_credentials_fail_without_echoing_the_value(self) -> None:
        record = _inner()
        value = "P16" * 8
        record["notes"] = {"a": {"b": {"password": value}}}
        verdict = ops16.validate_submission_record(record)
        self.assertFalse(verdict["valid"])
        self.assertIn("password assignment", verdict["credentialClasses"])
        self.assertNotIn(value, json.dumps(verdict))

    def test_password_prose_and_public_fingerprint_are_not_credentials(
            self) -> None:
        record = _inner()
        record["notes"] = (
            "Password handling was reviewed; no password value is present. "
            "Public key fingerprint SHA256:abcdefghijklmnop is public.")
        verdict = ops16.validate_submission_record(record)
        self.assertEqual(verdict["credentialClasses"], [])
        self.assertTrue(verdict["valid"])

    def test_duplicate_finding_identity_is_invalid(self) -> None:
        record = _inner()
        record["findings"].append(copy.deepcopy(record["findings"][0]))
        verdict = ops16.validate_submission_record(record)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("duplicated" in p for p in
                            verdict["contractProblems"]))

    def test_invalid_and_future_dates_fail_closed_without_a_clock(self) -> None:
        for invalid in ("2026-02-30", "2026-08-19-or-later", "recently"):
            record = _inner()
            record["review_end"] = invalid
            record["date"] = invalid
            with self.subTest(invalid=invalid):
                self.assertFalse(ops16.validate_submission_record(
                    record)["valid"])
        future = _inner()
        future["review_end"] = "2026-08-20"
        future["date"] = "2026-08-20"
        verdict = ops16.validate_submission_record(
            future, received_on="2026-08-19")
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("postdates" in p for p in
                            verdict["timeProblems"]))

    def test_validation_never_repairs_or_mutates(self) -> None:
        record = _inner()
        del record["digest_computation"]
        before = copy.deepcopy(record)
        ops16.validate_submission_record(record)
        self.assertEqual(record, before)

    def test_a_marked_fixture_is_refused(self) -> None:
        with self.assertRaises(ops16.BoundaryViolation):
            ops16.validate_submission_record(_wrapper())


class OneDoorAndCredentialHygiene(_Scratch):
    def test_receive_delegates_to_phase9_and_uses_its_seal(self) -> None:
        space = self._space()
        staged = space.stage(_inner())
        entry = ops16.receive(staged, [], "2026-08-19", "phase16 test",
                              ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "ACCEPTED")
        stored = space.ledger()["entries"][0]
        self.assertEqual(stored["seal"], intake.seal_entry(stored))

    def test_receive_and_direct_phase9_have_identical_refusal_semantics(
            self) -> None:
        record = _inner()
        record["notes"] = {"auth_token": "Qx7" * 8}
        direct_space, wrapped_space = self._space(), self._space()
        direct = intake.register(
            direct_space.ledger_path, "security-review",
            direct_space.stage(record), [], "2026-08-19", "direct")
        wrapped = ops16.receive(
            wrapped_space.stage(record), [], "2026-08-19", "wrapped",
            ledger_path=wrapped_space.ledger_path)
        self.assertEqual(wrapped["status"], direct["status"])
        self.assertEqual(wrapped["binding"], direct["binding"])
        self.assertEqual(wrapped["files"], {})

    def test_private_key_password_bearer_and_attachment_secrets_refuse(
            self) -> None:
        cases = []
        private = _inner()
        private["notes"] = "-----BEGIN " + "PRIVATE KEY-----\nX"
        cases.append((private, [], "private key material"))
        password = _inner()
        password["notes"] = {"password": "P16" * 8}
        cases.append((password, [], "password assignment"))
        bearer = _inner()
        bearer["notes"] = "Bearer " + ("Ab9" * 8)
        cases.append((bearer, [], "bearer token"))
        for index, (record, attachments, expected_class) in enumerate(cases):
            space = self._space()
            entry = ops16.receive(
                space.stage(record), attachments, "2026-08-19",
                "phase16 test", ledger_path=space.ledger_path)
            self.assertEqual(entry["status"], "REJECTED", index)
            self.assertIn(expected_class, entry["statusReason"])
            self.assertEqual(entry["files"], {})
            self.assertFalse((space.intake_root / "security-review"
                              / entry["intakeId"]).exists())
        space = self._space()
        record_path = space.stage(_inner())
        attachment = space.staging / "support.log"
        value = "Qx7" * 8
        attachment.write_text("session_token=" + value, encoding="utf-8")
        entry = ops16.receive(
            record_path, [attachment], "2026-08-19", "phase16 test",
            ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("support.log", entry["statusReason"])
        self.assertNotIn(value, entry["statusReason"])

    def test_fixture_marker_is_rejected_by_the_production_boundary(self) -> None:
        space = self._space()
        entry = ops16.receive(
            space.stage(_wrapper()), [], "2026-08-19", "phase16 test",
            ledger_path=space.ledger_path)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])
        self.assertEqual(ops13.authorization_floor(space.ledger()), [
            source + ": no gate-eligible ACCEPTED intake exists, so the "
            "authority that owns this gate has not acted"
            for source in ops13.AUTHORIZATION_FLOOR_SOURCES])

    def test_invalid_or_ambiguous_receipt_dates_refuse_before_append(
            self) -> None:
        for received_on in ("2026-02-30", "2026-08-19-latest", "today"):
            space = self._space()
            before = space.ledger_bytes()
            with self.subTest(received_on=received_on), self.assertRaises(
                    SystemExit):
                ops16.receive(
                    space.stage(_inner()), [], received_on, "phase16 test",
                    ledger_path=space.ledger_path)
            self.assertEqual(space.ledger_bytes(), before)

    def test_tampered_ledger_refuses_a_direct_append_attempt(self) -> None:
        space = self._space()
        space.register("security-review", _inner())
        ledger = space.ledger()
        ledger["entries"][0]["statusReason"] = "edited"
        intake.dump_ledger(space.ledger_path, ledger)
        with self.assertRaises(SystemExit):
            ops16.receive(space.stage(_inner()), [], "2026-08-19",
                          "phase16 test", ledger_path=space.ledger_path)

    def test_source_proves_there_is_no_phase16_append_path(self) -> None:
        self.assertEqual(ops16.engine_boundary_problems(), [])
        tree = ast.parse(_OPS16_TOOL.read_text(encoding="utf-8"))
        definitions = {node.name for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef)}
        for owner_function in ("register", "seal_entry", "seal_record",
                               "derive_security_gate",
                               "assemble_decision"):
            self.assertNotIn(owner_function, definitions)
        source = _OPS16_TOOL.read_text(encoding="utf-8")
        self.assertNotIn('open(PHASE9_LEDGER, "a', source)
        self.assertNotIn("PHASE9_LEDGER.write_", source)


class ArtifactBinding(_Scratch):
    def _successor_graph(self) -> dict:
        graph = copy.deepcopy(_GRAPH)
        root = graph["artifacts"][0]
        root["qualification_state"] = "SUPERSEDED"
        graph["artifacts"].append({
            "artifact_id": "CANDIDATE-NEXT",
            "build_identity": "constructed scratch successor",
            "digest": "sha256:" + "a" * 64,
            "digests": {"image": "sha256:" + "a" * 64},
            "parent_artifact": root["artifact_id"],
            "qualification_state": "EVIDENCE_PENDING",
            "relationship": "REBUILDS",
            "signingStatus": "UNSIGNED",
            "source_commit": "b" * 40,
            "supersedes": root["artifact_id"],
        })
        return graph

    def test_exact_subject_bytes_bind(self) -> None:
        self.assertEqual(ops16.bind_record(_inner())["result"], "APPLIES")

    def test_foreign_and_missing_digests_do_not_bind(self) -> None:
        foreign = _inner()
        foreign["artifact_digest"] = foreign["artifactDigest"] = "c" * 64
        self.assertEqual(ops16.bind_record(foreign)["result"],
                         "ARTIFACT_MISMATCH")
        self.assertEqual(ops16.bind_record({})["result"],
                         "ARTIFACT_MISMATCH")

    def test_related_successor_without_transfer_inherits_nothing(self) -> None:
        result = ops16.bind_record(_inner(), graph=self._successor_graph())
        self.assertEqual(result["result"], "DOES_NOT_APPLY")
        self.assertIn("no recorded transfer", result["reasoning"])

    def test_incomplete_transfer_decision_transfers_nothing(self) -> None:
        graph = self._successor_graph()
        graph["transferDecisions"] = [{
            "fromArtifact": "e906a48793d7",
            "toArtifact": "CANDIDATE-NEXT",
            "evidenceScope": "security-review",
            "result": "APPLIES",
            "reasoning": "",
            "decidedBy": "",
            "date": "",
        }]
        result = ops16.bind_record(_inner(), graph=graph)
        self.assertEqual(result["result"], "DOES_NOT_APPLY")
        self.assertIn("incomplete", result["reasoning"])

    def test_complete_recorded_transfer_uses_phase10_semantics(self) -> None:
        graph = self._successor_graph()
        graph["transferDecisions"] = [{
            "fromArtifact": "e906a48793d7",
            "toArtifact": "CANDIDATE-NEXT",
            "evidenceScope": "security-review",
            "result": "REQUIRES_REVIEW",
            "reasoning": "constructed scratch decision; re-evaluate scope",
            "decidedBy": "Constructed Decider",
            "date": "2026-08-19",
        }]
        result = ops16.bind_record(_inner(), graph=graph)
        self.assertEqual(result["result"], "REQUIRES_REVIEW")
        self.assertIn("Constructed Decider", result["reasoning"])

    def test_fixture_cannot_be_a_transfer_source(self) -> None:
        with self.assertRaises(ops16.BoundaryViolation):
            ops16.bind_record(_wrapper())


class ReviewerPackage(_Scratch):
    def test_prepare_is_reproducible_and_creates_no_review(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="phase16-handoff-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        first, second = base / "first", base / "second"
        ledger_before = ops16.PHASE9_LEDGER.read_bytes()
        manifest_a = ops16.prepare(first)
        manifest_b = ops16.prepare(second)
        self.assertEqual(manifest_a, manifest_b)
        for relative, pin in manifest_a["files"].items():
            raw_a = (first / relative).read_bytes()
            raw_b = (second / relative).read_bytes()
            self.assertEqual(raw_a, raw_b, relative)
            self.assertEqual(len(raw_a), pin["bytes"])
            self.assertEqual(hashlib.sha256(raw_a).hexdigest(),
                             pin["sha256"])
        self.assertTrue(manifest_a["createsNoReview"])
        self.assertEqual(ops16.PHASE9_LEDGER.read_bytes(), ledger_before)

    def test_prepare_refuses_overwrite_and_repository_destination(self) -> None:
        existing = Path(tempfile.mkdtemp(prefix="phase16-existing-"))
        self.addCleanup(shutil.rmtree, existing, ignore_errors=True)
        with self.assertRaises(ValueError):
            ops16.prepare(existing)
        inside = _PHASE16 / "never-create-handoff-here"
        self.assertFalse(inside.exists())
        with self.assertRaises(ValueError):
            ops16.prepare(inside)
        self.assertFalse(inside.exists())

    def test_contract_pins_and_required_handoff_statements_hold(self) -> None:
        self.assertEqual(ops16.contract_pin_problems(), [])
        self.assertEqual(ops16.handoff_problems(), [])


if __name__ == "__main__":
    unittest.main()

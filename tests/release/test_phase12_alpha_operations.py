# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Alpha tester program is operable, and the machinery cannot inflate it.

Phase 12 is tested the way Phases 9–11 are tested: the canonical package
is complete and agrees with the intake boundary; the reused Phase 7/8
sources are pinned and drift fails closed; the report contract is
enforced from the committed schema (which may not contain a keyword the
validator ignores); dry-run reports flow through the *real* Phase 9
registration into constructed scratch trees only; the credential scan
refuses secrets before ingestion and never repeats the value; unbound
reports are preserved without moving gates; revisions supersede without
overwriting; dedup is recorded human decisions, reversible, never
automatic; NOT_REPRODUCED leaves evidence valid and findings open; one
success never becomes a hardware PASS; the program state machine refuses
silence; and the derived register reproduces from its immutable inputs.

The real ledger participates in nothing here: tests compare its bytes
before and after, never its emptiness — the suite must stay green on the
day real tester evidence arrives.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_OPS12_TOOL = _ROOT / "qualification" / "phase12" / "tools" / "alpha_ops.py"
_OPS10_TOOL = (_ROOT / "qualification" / "phase10" / "tools"
               / "candidate_ops.py")
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_PACKAGE_DIR = _ROOT / "qualification" / "phase12" / "alpha"
_FIXTURES = _ROOT / "qualification" / "phase12" / "fixtures"
_REGISTER = _ROOT / "qualification" / "phase12" / "alpha-findings.json"
_DEDUP = _ROOT / "qualification" / "phase12" / "dedup-decisions.json"
_REPRO = _ROOT / "qualification" / "phase12" / "reproductions.json"
_POLICY = _ROOT / "qualification" / "phase12" / "sufficiency-policy.json"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
_GRAPH = (_ROOT / "qualification" / "phase10" / "artifacts"
          / "artifact-graph.json")
_MATRIX = _ROOT / "qualification" / "phase8" / "hardware-matrix.json"

_ISO = "823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops12 = _load("phase12_ops_under_test", _OPS12_TOOL)
ops10 = _load("phase10_ops_for_phase12_tests", _OPS10_TOOL)
intake = _load("phase9_intake_for_phase12_tests", _INTAKE_TOOL)


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _graph() -> dict:
    return json.loads(_GRAPH.read_text(encoding="utf-8"))


def _record(name: str, key: str = "record") -> dict:
    return json.loads(json.dumps(_fixture(name)[key]))


_EMPTY_DEDUP = {"decisions": []}
_EMPTY_REPRO = {"attempts": []}


class CanonicalPackage(unittest.TestCase):
    def test_the_package_is_complete(self) -> None:
        for name in ops12.PACKAGE_FILES:
            self.assertTrue((_PACKAGE_DIR / name).is_file(),
                            "%s is missing from the canonical package" % name)

    def test_the_pins_reproduce(self) -> None:
        self.assertEqual(ops12.pins_problems(), [])

    def test_a_drifted_pin_fails_closed(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="phase12-pins-"))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        drifted = json.loads((_PACKAGE_DIR / "PHASE8_PINS.json").read_text(
            encoding="utf-8"))
        first = sorted(drifted["pinnedSources"])[0]
        drifted["pinnedSources"][first]["sha256"] = "0" * 64
        path = scratch / "PHASE8_PINS.json"
        path.write_text(json.dumps(drifted), encoding="utf-8")
        original = ops12.PINS_PATH
        ops12.PINS_PATH = path
        self.addCleanup(setattr, ops12, "PINS_PATH", original)
        problems = ops12.pins_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("changed under the Phase 12 package", problems[0])

    def test_the_identity_agrees_with_the_intake_boundary(self) -> None:
        self.assertEqual(ops12._identity_problems(), [])

    def test_the_schema_uses_only_enforced_keywords(self) -> None:
        self.assertEqual(ops12._schema_problems(), [])

    def test_the_secret_tables_cannot_drift(self) -> None:
        self.assertEqual(ops12._secret_pattern_problems(), [])

    def test_render_modes_stay_separate_matrix_dimensions(self) -> None:
        """native-3D, fallback-3D, 2D and prerendered are four dimensions,
        never one generic 'graphics'."""
        self.assertEqual(len(ops12.RENDER_MODES), 4)
        for mode in ops12.RENDER_MODES:
            self.assertIn(mode, intake.HARDWARE_DIMENSIONS)
        self.assertNotIn("graphics", intake.HARDWARE_DIMENSIONS)

    def test_the_privacy_floor_is_documented(self) -> None:
        text = (_PACKAGE_DIR / "PRIVACY_POLICY.md").read_text(
            encoding="utf-8")
        for phrase in ("real name", "email address", "IP address",
                       "hardware serial number", "T-NNN"):
            self.assertIn(phrase, text)


class ReportContract(unittest.TestCase):
    def test_valid_fixture_reports_satisfy_the_contract(self) -> None:
        for name in ("tester-success-bound.json", "tester-failure-bound.json",
                     "tester-report-unbound.json",
                     "tester-artifact-mismatch.json",
                     "tester-performance-observation.json",
                     "tester-accessibility-observation.json",
                     "tester-security-observation.json"):
            self.assertEqual(ops12.validate_report(_record(name)), [], name)

    def test_the_wrapper_is_refused(self) -> None:
        problems = ops12.validate_report(_fixture("tester-success-bound.json"))
        self.assertEqual(len(problems), 1)
        self.assertIn("a fixture is never evidence", problems[0])

    def test_missing_required_fields_fail(self) -> None:
        problems = ops12.validate_report(_record("tester-missing-fields.json"))
        self.assertTrue(any("report_type" in p for p in problems), problems)
        self.assertTrue(any("user_observation" in p for p in problems),
                        problems)

    def test_verified_requires_the_observed_digest(self) -> None:
        record = _record("tester-report-unbound.json")
        record["artifact_identity_status"] = "VERIFIED"
        record["artifact_digest_verified"] = True
        problems = ops12.validate_report(record)
        self.assertTrue(any("MISSING" in p for p in problems), problems)

    def test_a_foreign_digest_must_say_mismatch(self) -> None:
        record = _record("tester-artifact-mismatch.json")
        record["artifact_identity_status"] = "VERIFIED"
        record["artifact_digest_verified"] = True
        problems = ops12.validate_report(record)
        self.assertTrue(any("MISMATCH" in p for p in problems), problems)

    def test_a_subject_digest_cannot_claim_mismatch(self) -> None:
        record = _record("tester-success-bound.json")
        record["artifact_identity_status"] = "MISMATCH"
        problems = ops12.validate_report(record)
        self.assertTrue(any("IS the subject artifact" in p for p in problems),
                        problems)

    def test_the_expected_digest_is_never_substituted(self) -> None:
        record = _record("tester-report-unbound.json")
        record["artifactDigest"] = _ISO
        problems = ops12.validate_report(record)
        self.assertTrue(any("never substitute the expected digest" in p
                            for p in problems), problems)

    def test_the_intake_alias_must_carry_the_observed_digest(self) -> None:
        record = _record("tester-success-bound.json")
        del record["artifactDigest"]
        problems = ops12.validate_report(record)
        self.assertTrue(any("intake binds on it" in p for p in problems),
                        problems)
        record = _record("tester-success-bound.json")
        record["artifactDigest"] = "1" * 64
        problems = ops12.validate_report(record)
        self.assertTrue(any("never a substituted expected digest" in p
                            for p in problems), problems)

    def test_verified_flag_and_status_must_agree(self) -> None:
        record = _record("tester-success-bound.json")
        record["artifact_identity_status"] = "OBSERVED_UNVERIFIED"
        problems = ops12.validate_report(record)
        self.assertTrue(any("incoherent" in p for p in problems), problems)

    def test_a_tester_id_outside_the_scheme_fails(self) -> None:
        record = _record("tester-success-bound.json")
        record["tester_id"] = record["testerId"] = "tester-jane@example.org"
        problems = ops12.validate_report(record)
        self.assertTrue(any("T-\\d{3}" in p for p in problems), problems)

    def test_an_invented_report_type_fails(self) -> None:
        record = _record("tester-success-bound.json")
        record["report_type"] = "TRIUMPH"
        problems = ops12.validate_report(record)
        self.assertTrue(any("report_type" in p for p in problems), problems)

    def test_the_courtesy_scan_names_the_class_never_the_value(self) -> None:
        record = _record("tester-success-bound.json")
        secret = "fixture-value-000-not-real"
        record["additional_context"] = "password: %s" % secret
        problems = ops12.validate_report(record)
        self.assertTrue(any("password assignment" in p for p in problems),
                        problems)
        self.assertFalse(any(secret in p for p in problems),
                         "the refusal repeated the secret")


class _ScratchIntake(unittest.TestCase):
    """A constructed Phase 9 tree; the real evidence never participates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.real_ledger_bytes = _LEDGER.read_bytes()
        cls.real_graph_bytes = _GRAPH.read_bytes()
        cls.real_register_bytes = _REGISTER.read_bytes()
        cls.real_matrix_bytes = _MATRIX.read_bytes()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phase12-dryrun-"))
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

    def _stage(self, name: str, payload) -> Path:
        path = self.staging / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")
        return path

    def _register(self, record, attachments=(), revises=None):
        return intake.register(
            self.ledger_path, "alpha-feedback",
            self._stage("record-src.json", record),
            [self._stage(name, blob) for name, blob in attachments],
            "2026-08-18", "dry-run fixture payload", revises)

    def _derive(self, dedup=None, repro=None, graph=None):
        return ops12.derive_register(
            intake.load_ledger(self.ledger_path),
            graph or _graph(),
            dedup or json.loads(json.dumps(_EMPTY_DEDUP)),
            repro or json.loads(json.dumps(_EMPTY_REPRO)),
            json.loads(_POLICY.read_text(encoding="utf-8")),
            self.intake_root)

    def _assert_reality_untouched(self) -> None:
        self.assertEqual(_LEDGER.read_bytes(), self.real_ledger_bytes,
                         "a dry run reached the real intake ledger")
        self.assertEqual(_GRAPH.read_bytes(), self.real_graph_bytes,
                         "a dry run reached the real artifact graph")
        self.assertEqual(_REGISTER.read_bytes(), self.real_register_bytes,
                         "a dry run reached the real alpha register")
        self.assertEqual(_MATRIX.read_bytes(), self.real_matrix_bytes,
                         "a dry run reached the real hardware matrix")


class ScratchIntakeDryRuns(_ScratchIntake):
    def test_a_bound_success_report_is_accepted(self) -> None:
        entry = self._register(_record("tester-success-bound.json"))
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(entry["binding"], "BOUND")
        self.assertTrue(entry["gateEligible"])
        self._assert_reality_untouched()

    def test_a_bound_failure_report_is_accepted(self) -> None:
        entry = self._register(_record("tester-failure-bound.json"))
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(entry["binding"], "BOUND")

    def test_an_unbound_report_is_preserved_not_eligible(self) -> None:
        entry = self._register(_record("tester-report-unbound.json"))
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(entry["binding"], "USER_EVIDENCE_UNBOUND")
        self.assertFalse(entry["gateEligible"])

    def test_a_mismatched_digest_is_named_as_such(self) -> None:
        entry = self._register(_record("tester-artifact-mismatch.json"))
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        self.assertFalse(entry["gateEligible"])

    def test_the_wrapper_is_rejected_by_the_real_intake_code(self) -> None:
        entry = self._register(_fixture("tester-success-bound.json"))
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("fixture is never evidence", entry["statusReason"])
        self._assert_reality_untouched()

    def test_a_revision_supersedes_without_overwriting(self) -> None:
        original = self._register(_record("tester-report-revision.json",
                                          "original"))
        self.assertEqual(original["binding"], "USER_EVIDENCE_UNBOUND")
        stored_before = json.loads(json.dumps(
            intake.load_ledger(self.ledger_path)["entries"][0]))
        revision = self._register(_record("tester-report-revision.json",
                                          "revision"),
                                  revises=original["intakeId"])
        self.assertEqual(revision["intakeId"], "INTAKE-001-R1")
        self.assertEqual(revision["binding"], "BOUND")
        ledger = intake.load_ledger(self.ledger_path)
        self.assertEqual(ledger["entries"][0], stored_before,
                         "the original ledger entry changed")
        effective = intake.effective_statuses(ledger)
        self.assertEqual(effective[original["intakeId"]], "SUPERSEDED")
        self.assertEqual(effective[revision["intakeId"]], "ACCEPTED")
        derived = self._derive()
        classifications = {r["intakeId"]: r["classification"]
                           for r in derived["reports"]}
        self.assertEqual(classifications[original["intakeId"]], "SUPERSEDED")
        self.assertEqual(classifications[revision["intakeId"]], "ACCEPTED")
        self.assertEqual(
            [f["source_report_ids"] for f in derived["findings"]],
            [[revision["intakeId"]]],
            "only the effective revision derives rows; a later revision "
            "established artifact applicability")

    def test_a_secret_in_nested_metadata_is_rejected_unread(self) -> None:
        record = _record("tester-report-unbound.json")
        record["logs"] = {"session": {"detail":
                                      "password: fixture000-not-real"}}
        entry = self._register(record)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertEqual(entry["files"], {}, "nothing was ingested")
        self.assertIn("credential material", entry["statusReason"])
        self.assertIn("password assignment", entry["statusReason"])
        self.assertNotIn("fixture000-not-real", entry["statusReason"],
                         "the refusal repeated the secret")
        on_disk = [p for p in self.intake_root.rglob("*")
                   if p.is_file() and b"fixture000-not-real" in p.read_bytes()]
        self.assertEqual(on_disk, [], "the secret bytes touched the tree")

    def test_a_secret_in_an_attachment_is_rejected_unread(self) -> None:
        token = b"Bearer fixturetokenAAAABBBBCCCC1234"
        entry = self._register(
            _record("tester-failure-bound.json"),
            attachments=[("journal.txt",
                          b"constructed fixture log line\n" + token + b"\n")])
        self.assertEqual(entry["status"], "REJECTED")
        self.assertEqual(entry["files"], {}, "nothing was ingested")
        self.assertIn("bearer token", entry["statusReason"])
        self.assertIn("journal.txt", entry["statusReason"])
        on_disk = [p for p in self.intake_root.rglob("*")
                   if p.is_file() and token in p.read_bytes()]
        self.assertEqual(on_disk, [], "the token bytes touched the tree")

    def test_a_modified_attachment_claim_fails_integrity(self) -> None:
        fixture = _fixture("tester-attachment-mismatch.json")
        entry = self._register(
            fixture["record"],
            attachments=[(fixture["attachmentName"],
                          fixture["attachmentContent"].encode("utf-8"))])
        self.assertEqual(entry["status"], "UNVERIFIABLE")
        self.assertIn("claimed digests do not match",
                      entry["validation"]["integrity"])

    def test_an_ingested_attachment_is_pinned_against_modification(self) -> None:
        blob = b"constructed fixture screenshot bytes\n"
        import hashlib
        record = _record("tester-failure-bound.json")
        record["attachmentDigests"] = {
            "screenshot.png": hashlib.sha256(blob).hexdigest()}
        entry = self._register(record, attachments=[("screenshot.png", blob)])
        self.assertEqual(entry["status"], "ACCEPTED")
        (path,) = [self.tmp / name for name in entry["files"]
                   if name.endswith("screenshot.png")]
        path.write_bytes(blob + b"tampered")
        issues = intake.verify_intake(self.intake_root,
                                      intake.load_ledger(self.ledger_path))
        self.assertEqual(list(issues), ["fileChanged"])


class RegisterDerivation(_ScratchIntake):
    def test_the_committed_register_reproduces_from_its_inputs(self) -> None:
        derived, problems = ops12.sync_register(write=False)
        self.assertEqual(problems, [])
        self.assertEqual(
            derived, json.loads(self.real_register_bytes.decode("utf-8")),
            "alpha-findings.json does not reproduce; run sync and review "
            "the diff")

    def test_zero_reports_derive_ready_never_success(self) -> None:
        derived = self._derive()
        self.assertEqual(derived["program"]["state"], "READY_FOR_TESTERS")
        self.assertIn("silence advances nothing", derived["program"]["basis"])
        self.assertEqual(derived["sufficiency"]["determination"],
                         "SUFFICIENCY_UNDETERMINED")
        self.assertEqual(derived["sufficiency"]["evidenceLevel"],
                         "NO_EVIDENCE")
        self.assertEqual(derived["counts"]["acceptedReports"], 0)
        self.assertEqual(derived["findings"], [])
        self.assertEqual(derived["successEvidence"], [])

    def test_one_success_is_one_observation_never_a_pass(self) -> None:
        self._register(_record("tester-success-bound.json"))
        derived = self._derive()
        self.assertEqual(len(derived["successEvidence"]), 1)
        success = derived["successEvidence"][0]
        self.assertEqual(success["evidenceClass"], "USER_REPORTED")
        self.assertIn("never SUPPORTED ON PCS", success["limit"])
        self.assertEqual(len(derived["hardwareObservations"]), 1)
        self.assertEqual(derived["hardwareObservations"][0]["class"],
                         "HARDWARE_OBSERVED")
        self.assertIn("PASS still requires the committed hardware protocol",
                      derived["hardwareObservations"][0]["note"])
        self.assertEqual(derived["findings"], [],
                         "a success derives no finding")
        self.assertEqual(derived["program"]["state"], "EVIDENCE_RECEIVED")
        self._assert_reality_untouched()

    def test_an_unclassified_failure_derives_a_labeled_finding(self) -> None:
        self._register(_record("tester-failure-bound.json"))
        derived = self._derive()
        self.assertEqual(len(derived["findings"]), 1)
        finding = derived["findings"][0]
        self.assertEqual(finding["category"], "FUNCTIONAL")
        self.assertEqual(finding["classificationSource"], "DERIVED")
        self.assertEqual(finding["userObservation"], "I could not install it.")
        self.assertEqual(finding["lifecycle_status"], "RECEIVED")
        self.assertEqual(finding["user_impact"], "UNKNOWN")
        self.assertIsNone(finding["derived_severity"],
                          "severity is not derived from the tester's words")
        self.assertEqual(finding["artifact"], "e906a48793d7")
        self.assertEqual(finding["reproducibility_status"], "NOT_ATTEMPTED")

    def test_unbound_evidence_is_visible_and_moves_nothing(self) -> None:
        self._register(_record("tester-report-unbound.json"))
        derived = self._derive()
        self.assertEqual(len(derived["unboundEvidence"]), 1)
        self.assertIn("moves no artifact-specific gate",
                      derived["unboundEvidence"][0]["gateNote"])
        finding = derived["findings"][0]
        self.assertIsNone(finding["artifact"])
        self.assertEqual(finding["evidenceBinding"], "USER_EVIDENCE_UNBOUND")

    def test_subjective_and_measured_performance_stay_separate(self) -> None:
        self._register(_record("tester-performance-observation.json"))
        derived = self._derive()
        self.assertEqual(len(derived["performance"]["subjective"]), 1)
        self.assertEqual(derived["performance"]["subjective"][0]["observation"],
                         "The desktop felt slow.")
        self.assertEqual(len(derived["performance"]["testerMeasurements"]), 1)
        measurement = derived["performance"]["testerMeasurements"][0]
        self.assertEqual(measurement["evidenceClass"], "USER_REPORTED")
        self.assertIn("MEASURED only when independently validated",
                      measurement["note"])
        self.assertEqual(derived["performance"]["projectMeasured"], [],
                         "nothing was independently measured")

    def test_an_accessibility_observation_is_first_class(self) -> None:
        self._register(_record("tester-accessibility-observation.json"))
        derived = self._derive()
        self.assertEqual(len(derived["accessibilityObservations"]), 1)
        observation = derived["accessibilityObservations"][0]
        self.assertIn("Orca", observation["technology"])
        self.assertEqual(observation["evidenceClass"], "USER_REPORTED")

    def test_a_security_observation_is_surfaced_not_promoted(self) -> None:
        self._register(_record("tester-security-observation.json"))
        derived = self._derive()
        self.assertEqual(len(derived["securityObservations"]), 1)
        observation = derived["securityObservations"][0]
        self.assertIsNone(observation["assessment"])
        self.assertIn("never impersonates the independent review",
                      observation["note"])
        self.assertIn("NOT_A_SECURITY_ISSUE requires a recorded assessment",
                      observation["note"])

    def test_a_contract_invalid_accepted_report_derives_nothing(self) -> None:
        self._register(_record("tester-missing-fields.json"))
        derived = self._derive()
        self.assertEqual(derived["counts"]["acceptedReports"], 1)
        self.assertEqual(derived["findings"], [])
        row = derived["reports"][0]
        self.assertTrue(row["contractProblems"])
        self.assertIn("derives no rows", row["note"])

    def test_similar_reports_stay_distinct_without_a_decision(self) -> None:
        for record in _fixture("tester-duplicate-pair.json")["records"]:
            self._register(json.loads(json.dumps(record)))
        derived = self._derive()
        self.assertEqual(len(derived["findings"]), 2)
        for finding in derived["findings"]:
            self.assertEqual(finding["relationship"]["kind"], "DISTINCT")

    def test_a_recorded_duplicate_decision_relates_without_deleting(self) -> None:
        fixture = _fixture("tester-duplicate-pair.json")
        for record in fixture["records"]:
            self._register(json.loads(json.dumps(record)))
        derived = self._derive(
            dedup={"decisions": [fixture["decisionDuplicate"]]})
        self.assertEqual(len(derived["findings"]), 2,
                         "deduplication deleted a report's finding")
        kinds = {f["finding_id"]: f["relationship"] for f in derived["findings"]}
        for finding_id, relationship in kinds.items():
            self.assertEqual(relationship["kind"], "DUPLICATE_OF")
            self.assertTrue(relationship["rationale"])
            self.assertTrue(relationship["decidedBy"])
            self.assertTrue(relationship["date"])

    def test_a_later_decision_reverses_an_earlier_one(self) -> None:
        fixture = _fixture("tester-duplicate-pair.json")
        for record in fixture["records"]:
            self._register(json.loads(json.dumps(record)))
        derived = self._derive(dedup={"decisions": [
            fixture["decisionDuplicate"], fixture["decisionRelatedLater"]]})
        for finding in derived["findings"]:
            self.assertEqual(finding["relationship"]["kind"], "RELATED",
                             "the later recorded decision supersedes")

    def test_a_decision_without_rationale_is_refused(self) -> None:
        fixture = _fixture("tester-duplicate-pair.json")
        for record in fixture["records"]:
            self._register(json.loads(json.dumps(record)))
        bare = dict(fixture["decisionDuplicate"], rationale="")
        with self.assertRaises(ops12.BoundaryViolation) as caught:
            self._derive(dedup={"decisions": [bare]})
        self.assertIn("automatic merge in disguise", str(caught.exception))

    def test_a_dangling_decision_fails_closed(self) -> None:
        fixture = _fixture("tester-duplicate-pair.json")
        self._register(json.loads(json.dumps(fixture["records"][0])))
        with self.assertRaises(ops12.BoundaryViolation) as caught:
            self._derive(dedup={"decisions": [fixture["decisionDuplicate"]]})
        self.assertIn("unknown finding", str(caught.exception))

    def test_a_reproduced_attempt_moves_the_finding(self) -> None:
        self._register(
            json.loads(json.dumps(
                _fixture("tester-duplicate-pair.json")["records"][0])))
        attempt = _fixture("reproduction-attempts.json")["reproduced"]
        derived = self._derive(repro={"attempts": [attempt]})
        self.assertEqual(derived["findings"][0]["reproducibility_status"],
                         "REPRODUCED")

    def test_not_reproduced_leaves_valid_open_evidence(self) -> None:
        self._register(
            json.loads(json.dumps(
                _fixture("tester-duplicate-pair.json")["records"][0])))
        attempt = _fixture("reproduction-attempts.json")["notReproduced"]
        derived = self._derive(repro={"attempts": [attempt]})
        finding = derived["findings"][0]
        self.assertEqual(finding["reproducibility_status"], "NOT_REPRODUCED")
        self.assertEqual(finding["lifecycle_status"], "RECEIVED",
                         "NOT_REPRODUCED closed a finding")
        report = derived["reports"][0]
        self.assertEqual(report["classification"], "ACCEPTED",
                         "NOT_REPRODUCED invalidated the tester report")

    def test_a_successor_attempt_moves_nothing_without_a_relationship(self) -> None:
        self._register(
            json.loads(json.dumps(
                _fixture("tester-duplicate-pair.json")["records"][0])))
        attempt = _fixture("reproduction-attempts.json")["successorAttempt"]
        graph = _graph()
        graph["artifacts"].append(
            _fixture("alpha-close-without-evidence.json")["successorEntry"])
        finding = {"source_report_ids": ["INTAKE-001"],
                   "artifact": "e906a48793d7"}
        status, other = ops12.reproducibility_for(finding, [attempt], graph)
        self.assertEqual(status, "NOT_ATTEMPTED")
        self.assertEqual(len(other), 1)
        self.assertIn("no recorded applicability relationship",
                      other[0]["note"])

    def test_a_recorded_relationship_lets_an_attempt_count(self) -> None:
        attempt = _fixture("reproduction-attempts.json")["successorAttempt"]
        graph = _graph()
        graph["artifacts"].append(
            _fixture("alpha-close-without-evidence.json")["successorEntry"])
        graph["transferDecisions"] = [{
            "fromArtifact": "fixture-successor-alpha",
            "toArtifact": "e906a48793d7",
            "evidenceScope": "reproduction",
            "result": "APPLIES",
            "reasoning": "constructed control: the affected component is "
                         "byte-identical between the artifacts",
            "decidedBy": "constructed control decider",
            "date": "2026-08-18",
        }]
        finding = {"source_report_ids": ["INTAKE-001"],
                   "artifact": "e906a48793d7"}
        status, other = ops12.reproducibility_for(finding, [attempt], graph)
        self.assertEqual(status, "REPRODUCED")
        self.assertEqual(other, [])

    def test_an_invalid_attempt_is_refused(self) -> None:
        attempt = dict(_fixture("reproduction-attempts.json")["reproduced"])
        attempt["result"] = "INVALID"
        issues = ops12.validate_reproduction_attempt(attempt)
        self.assertTrue(any("not in the vocabulary" in i for i in issues))

    def test_a_successor_candidate_runs_its_own_program(self) -> None:
        graph = _graph()
        graph["artifacts"][0]["qualification_state"] = "SUPERSEDED"
        graph["artifacts"].append(
            _fixture("alpha-close-without-evidence.json")["successorEntry"])
        with self.assertRaises(ops12.BoundaryViolation) as caught:
            self._derive(graph=graph)
        self.assertIn("does not transfer", str(caught.exception))

    def test_a_fixture_marked_ledger_entry_is_refused(self) -> None:
        ledger = intake.load_ledger(self.ledger_path)
        ledger["entries"].append({
            "intakeId": "INTAKE-001", "revises": None,
            "source": "alpha-feedback", "status": "ACCEPTED",
            "gateEligible": True, "binding": "BOUND",
            "fixtureClass": "TEST_FIXTURE_ONLY", "files": {},
        })
        with self.assertRaises(ops12.BoundaryViolation):
            ops12.derive_register(
                ledger, _graph(), dict(_EMPTY_DEDUP), dict(_EMPTY_REPRO),
                json.loads(_POLICY.read_text(encoding="utf-8")),
                self.intake_root)


class ProgramStateMachine(unittest.TestCase):
    def test_the_vocabulary_is_the_eight(self) -> None:
        self.assertEqual(len(ops12.PROGRAM_STATES), 8)
        register = json.loads(_REGISTER.read_text(encoding="utf-8"))
        self.assertEqual(register["vocabularies"]["programStates"],
                         list(ops12.PROGRAM_STATES))

    def test_ready_cannot_reach_sufficient_directly(self) -> None:
        self.assertNotIn("ALPHA_EVIDENCE_SUFFICIENT",
                         ops12.PROGRAM_TRANSITIONS["READY_FOR_TESTERS"])
        with self.assertRaises(ops12.BoundaryViolation):
            ops12.program_transition("READY_FOR_TESTERS",
                                     "ALPHA_EVIDENCE_SUFFICIENT")

    def test_every_undeclared_transition_is_refused(self) -> None:
        for current in ops12.PROGRAM_STATES:
            for target in ops12.PROGRAM_STATES:
                if target in ops12.PROGRAM_TRANSITIONS[current]:
                    continue
                with self.assertRaises(ops12.BoundaryViolation,
                                       msg="%s -> %s" % (current, target)):
                    ops12.program_transition(current, target)

    def test_evidence_received_requires_evidence(self) -> None:
        with self.assertRaises(ops12.BoundaryViolation) as caught:
            ops12.program_transition("READY_FOR_TESTERS", "EVIDENCE_RECEIVED")
        self.assertIn("silence never advances", str(caught.exception))
        self.assertEqual(
            ops12.program_transition("READY_FOR_TESTERS", "EVIDENCE_RECEIVED",
                                     {"acceptedReports": 1}),
            "EVIDENCE_RECEIVED")

    def test_sufficient_requires_the_determination(self) -> None:
        with self.assertRaises(ops12.BoundaryViolation) as caught:
            ops12.program_transition(
                "TRIAGE_IN_PROGRESS", "ALPHA_EVIDENCE_SUFFICIENT",
                {"sufficiency": {"determination": "SUFFICIENCY_UNDETERMINED"}})
        self.assertIn("never rounded up", str(caught.exception))
        self.assertEqual(
            ops12.program_transition(
                "TRIAGE_IN_PROGRESS", "ALPHA_EVIDENCE_SUFFICIENT",
                {"sufficiency": {"determination": "SUFFICIENT"}}),
            "ALPHA_EVIDENCE_SUFFICIENT")

    def test_blocked_requires_a_reason(self) -> None:
        with self.assertRaises(ops12.BoundaryViolation):
            ops12.program_transition("EVIDENCE_RECEIVED", "BLOCKED")

    def test_the_derived_ladder_never_advances_on_silence(self) -> None:
        self.assertEqual(ops12.derive_program_state(0, 0, [])["state"],
                         "READY_FOR_TESTERS")
        self.assertEqual(ops12.derive_program_state(0, 5, [])["state"],
                         "READY_FOR_TESTERS",
                         "triage rows without accepted evidence advanced "
                         "the state")
        self.assertEqual(ops12.derive_program_state(1, 0, [])["state"],
                         "EVIDENCE_RECEIVED")
        self.assertEqual(ops12.derive_program_state(1, 1, [])["state"],
                         "TRIAGE_IN_PROGRESS")
        self.assertEqual(
            ops12.derive_program_state(1, 1, ["AF-INTAKE-001-T"])["state"],
            "REMEDIATION_REQUIRED")


class SufficiencyPolicy(unittest.TestCase):
    def test_undefined_thresholds_are_never_guessed(self) -> None:
        policy = json.loads(_POLICY.read_text(encoding="utf-8"))
        verdict = ops12.evaluate_sufficiency(policy, 5, 5, [])
        self.assertEqual(verdict["determination"], "SUFFICIENCY_UNDETERMINED")
        self.assertIn("owner-undefined", verdict["basis"])
        self.assertIn("nothing is guessed", verdict["basis"])

    def test_no_evidence_and_insufficient_evidence_differ(self) -> None:
        policy = {"thresholds": {"minimumBoundReports": 3}}
        none = ops12.evaluate_sufficiency(policy, 0, 0, [])
        some = ops12.evaluate_sufficiency(policy, 1, 1, [])
        self.assertEqual(none["evidenceLevel"], "NO_EVIDENCE")
        self.assertEqual(some["evidenceLevel"], "EVIDENCE_PRESENT")
        self.assertEqual(none["determination"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(some["determination"], "INSUFFICIENT_EVIDENCE")

    def test_blockers_hold_sufficiency_open(self) -> None:
        policy = {"thresholds": {"minimumBoundReports": 2}}
        blocked = ops12.evaluate_sufficiency(policy, 3, 3, ["AF-INTAKE-001-T"])
        self.assertEqual(blocked["determination"],
                         "SUFFICIENT_WITH_UNRESOLVED_BLOCKERS")
        clean = ops12.evaluate_sufficiency(policy, 3, 3, [])
        self.assertEqual(clean["determination"], "SUFFICIENT")


class SecretScanning(unittest.TestCase):
    def test_every_class_fires(self) -> None:
        cases = {
            "private key material":
                b"-----BEGIN OPENSSH PRIVATE KEY-----\ncontrol\n",
            "bearer token": b"Authorization: Bearer abcdefghijklmnopqrstu",
            "cloud access key id": b"AKIAABCDEFGHIJKLMNOP",
            "api or session token assignment":
                b"api_key = abcdefghijklmnop123456",
            "password assignment": b'"password": "fixture0-value"',
            "json web token":
                b"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkifQ",
            "code-forge token":
                b"ghp_" + b"a" * 36,
        }
        for label, raw in cases.items():
            self.assertIn(label, intake.detect_secret_classes(raw), label)

    def test_prose_about_passwords_does_not_fire(self) -> None:
        for clean in (b"the password prompt appeared and I typed mine",
                      b"passwords: do not include them in reports",
                      b"the passphrase dialog was confusing",
                      b"bearer of good news",
                      b"never paste an api key into a report"):
            self.assertEqual(intake.detect_secret_classes(clean), [], clean)

    def test_the_scan_is_byte_level_so_nesting_is_irrelevant(self) -> None:
        nested = json.dumps(
            {"a": {"b": [{"c": {"passwd: deepfixture0": True}}]}}
        ).encode("utf-8")
        self.assertEqual(intake.detect_secret_classes(nested),
                         ["password assignment"])


class ClosureAndTransfer(unittest.TestCase):
    def test_an_alpha_finding_cannot_close_without_bound_evidence(self) -> None:
        finding = dict(_fixture("alpha-close-without-evidence.json")["finding"])
        with self.assertRaises(ops10.BoundaryViolation):
            ops10.finding_transition(finding, "CLOSED")
        finding["state"] = ops10.finding_transition(finding, "FIX_REQUIRED")
        finding["state"] = ops10.finding_transition(finding, "FIXED")
        with self.assertRaises(ops10.BoundaryViolation) as caught:
            ops10.finding_transition(finding, "REQUALIFIED", {
                "requalificationEvidence": {
                    "reference": "requal-run",
                    "artifact": "fixture-successor-alpha"}})
        self.assertIn("actually tested", str(caught.exception))

    def test_register_row_invariants_fire(self) -> None:
        states = tuple(ops10.FINDING_STATES)
        row = dict(_fixture("alpha-close-without-evidence.json")["registerRow"])
        issues = ops12.validate_alpha_row(row, states)
        self.assertTrue(any("CLOSED without closure evidence" in i
                            for i in issues), issues)
        row["closure_evidence"] = {"reference": "requal-run",
                                   "artifact": "fixture-successor-alpha"}
        issues = ops12.validate_alpha_row(row, states)
        self.assertTrue(any("actually tested" in i for i in issues), issues)
        unbound = dict(row, artifact=None, lifecycle_status="CONFIRMED",
                       closure_evidence=None)
        issues = ops12.validate_alpha_row(unbound, states)
        self.assertTrue(any("unbound user evidence" in i for i in issues),
                        issues)

    def test_tester_evidence_does_not_apply_to_the_successor(self) -> None:
        graph = _graph()
        graph["artifacts"].append(
            _fixture("alpha-close-without-evidence.json")["successorEntry"])
        verdict = ops10.evaluate_applicability(
            {"evidenceId": "INTAKE-001", "artifactDigest": _ISO,
             "scope": "alpha-feedback"},
            "fixture-successor-alpha", graph)
        self.assertEqual(verdict["result"], "DOES_NOT_APPLY")
        self.assertIn("default is no transfer", verdict["reasoning"])


class FixtureDiscipline(unittest.TestCase):
    def test_every_fixture_is_structurally_marked(self) -> None:
        self.assertEqual(ops12.verify_fixtures(), [])
        names = sorted(p.name for p in _FIXTURES.glob("*.json"))
        self.assertEqual(len(names), 13, names)
        for name in names:
            self.assertEqual(_fixture(name)["fixtureClass"],
                             "TEST_FIXTURE_ONLY", name)

    def test_the_verify_command_is_clean(self) -> None:
        self.assertEqual(ops12.verify_all(), [])


if __name__ == "__main__":
    unittest.main()

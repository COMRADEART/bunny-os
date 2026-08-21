# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The release decision is governable, and the machinery cannot make it.

Phase 13 is tested the way Phases 9-12 are tested: the committed
governance model agrees with the module; a role in a JSON file is not an
assignment and not an act; separation of duties fails closed on one
identity; undefined thresholds cannot produce sufficiency and an
activated policy is sealed against edits; the ten inherited blocking
conditions keep their titles verbatim behind a pinned source and never
weaken silently; conflicting evidence defaults to a human decision with
the unfavorable assessment effective; risk acceptance is scoped,
expiring, non-transferable, and closes nothing; an internal JSON
claiming AUTHORIZED is refused with the absent floor named; expiry and
revocation derive rather than being flipped; REVOKED never becomes
AUTHORIZED again; authorization never crosses an artifact edge; every
forbidden state transition is swept; and the derived status reproduces
from its immutable inputs.

The real ledger, graph, and registers participate in nothing here: tests
compare their bytes before and after, never their emptiness — the suite
must stay green on the day real evidence arrives.
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
_OPS13_TOOL = (_ROOT / "qualification" / "phase13" / "tools"
               / "release_authority_ops.py")
_INTAKE_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_FIXTURES = _ROOT / "qualification" / "phase13" / "fixtures"
_FIXTURES11 = _ROOT / "qualification" / "phase11" / "fixtures"
_FIXTURES10 = _ROOT / "qualification" / "phase10" / "fixtures"
_FIXTURES12 = _ROOT / "qualification" / "phase12" / "fixtures"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
_GRAPH = (_ROOT / "qualification" / "phase10" / "artifacts"
          / "artifact-graph.json")
_DECISION = (_ROOT / "qualification" / "phase9" / "decision"
             / "alpha-release-decision.json")
_REGISTER11 = _ROOT / "qualification" / "phase11" / "security-findings.json"
_REGISTER12 = _ROOT / "qualification" / "phase12" / "alpha-findings.json"
_STATUS = _ROOT / "qualification" / "phase13" / "authorization-status.json"
_BLOCKING = (_ROOT / "qualification" / "phase13" / "blocking"
             / "blocking-conditions.json")

_IMAGE = ("sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5"
          "aa7f8562d")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops13 = _load("phase13_ops_under_test", _OPS13_TOOL)
intake = _load("phase9_intake_for_phase13_tests", _INTAKE_TOOL)


def _fixture(name: str, root: Path = _FIXTURES) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def _record(name: str, root: Path = _FIXTURES, key: str = "record") -> dict:
    return copy.deepcopy(_fixture(name, root)[key])


def _seal(record: dict) -> dict:
    sealed = dict(record)
    sealed["seal"] = ops13.seal_record(sealed)
    return sealed


def _assignments() -> list[dict]:
    return [_seal(r) for r in _fixture("authority-assignments.json")
            ["assignments"]]


def _empty_ledger() -> dict:
    real = json.loads(_LEDGER.read_text(encoding="utf-8"))
    return {
        "schemaVersion": 1,
        "appendMechanism": real["appendMechanism"],
        "sources": list(intake.SOURCES),
        "statusVocabulary": list(intake.STATUSES),
        "sealAlgorithm": real["sealAlgorithm"],
        "subjectArtifact": real["subjectArtifact"],
        "entries": [],
    }


def _empty_alpha() -> dict:
    return {"counts": {"acceptedReports": 0, "boundReports": 0},
            "reports": [], "findings": [], "hardwareObservations": [],
            "accessibilityObservations": [], "performance": {}}


def _empty_security(gate: str = "AWAITING_EXTERNAL_EVIDENCE") -> dict:
    return {"securityGate": {"status": gate}, "findings": []}


def _clear_blocking() -> dict:
    committed = json.loads(_BLOCKING.read_text(encoding="utf-8"))
    rows = []
    for row in committed["conditions"]:
        cleared = dict(row)
        cleared["state"] = "FALSE"
        cleared["evidenceCharacter"] = "CLEARED"
        rows.append(cleared)
    return {"conditions": rows}


class _Scratch(unittest.TestCase):
    """Constructed trees only; the real evidence never participates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.real_bytes = {
            path: path.read_bytes()
            for path in (_LEDGER, _GRAPH, _DECISION, _REGISTER11,
                         _REGISTER12, _STATUS)
        }

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_bytes.items():
            if path.read_bytes() != raw:
                raise AssertionError(
                    "%s changed during the dry runs; Phase 13 must never "
                    "mutate its immutable inputs" % path.name)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phase13-dryrun-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.intake_root = self.tmp / "qualification" / "phase9" / "intake"
        for source in intake.SOURCES:
            (self.intake_root / source).mkdir(parents=True)
        self.ledger_path = self.intake_root / "LEDGER.json"
        intake.dump_ledger(self.ledger_path, _empty_ledger())
        self.staging = self.tmp / "staging"
        self.staging.mkdir()

    def _stage(self, name: str, payload) -> Path:
        path = self.staging / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _register(self, source: str, record: dict) -> dict:
        return intake.register(
            self.ledger_path, source, self._stage(
                "%s-%d.json" % (source, len(list(self.staging.iterdir()))),
                record),
            [], "2026-08-19", "phase13 dry run")

    def _full_evidence_ledger(self) -> dict:
        """Five gate-eligible ACCEPTED intakes through the real intake."""
        self._register("security-review", _record(
            "review-valid-independent.json", _FIXTURES11))
        self._register("signing", _record(
            "signing-metadata-valid.json", _FIXTURES10))
        self._register("second-approval", _record(
            "second-approval-complete.json"))
        self._register("hardware", _record("hardware-pass-machine.json"))
        self._register("alpha-feedback", _record(
            "tester-success-bound.json", _FIXTURES12))
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        for entry in ledger["entries"]:
            if not entry.get("gateEligible"):
                raise AssertionError(
                    "dry-run intake %s is not gate-eligible: %s"
                    % (entry["intakeId"], entry.get("statusReason")))
        return ledger

    def _sufficient_alpha(self) -> dict:
        return {
            "counts": {"acceptedReports": 1, "boundReports": 1},
            "reports": [{"classification": "ACCEPTED", "testerId": "T-001",
                         "reportType": "SUCCESS", "journey": "A"}],
            "findings": [],
            "hardwareObservations": [{"machineLabel": "fixture-vm-1"}],
            "accessibilityObservations": [],
            "performance": {},
        }

    def _validate(self, record: dict, **overrides) -> list[str]:
        ledger = overrides.pop("ledger", None) or _empty_ledger()
        ledger_bytes = json.dumps(ledger, sort_keys=True).encode("utf-8")
        defaults = dict(
            ledger=ledger,
            ledger_sha256=overrides.pop(
                "ledger_sha256", ops13._sha256(ledger_bytes)),
            intake_root=self.intake_root,
            assignments=[], overlap_decisions=[], policies=[], risks=[],
            blocking=_clear_blocking(), alpha_register=_empty_alpha(),
            security_register=_empty_security(), as_of="2026-08-19")
        defaults.update(overrides)
        return ops13.validate_authorization(record, **defaults)

    def _full_context(self) -> dict:
        """Everything AUTHORIZED requires, constructed: five accepted
        intakes, assignments, an active policy, cleared conditions."""
        ledger = self._full_evidence_ledger()
        ledger_bytes = self.ledger_path.read_bytes()
        return {
            "ledger": ledger,
            "ledger_sha256": ops13._sha256(ledger_bytes),
            "assignments": _assignments(),
            "policies": [_seal(_record("sufficiency-policy-active.json"))],
            "alpha_register": self._sufficient_alpha(),
            "security_register": _empty_security("SATISFIED"),
            "blocking": _clear_blocking(),
        }

    def _authz(self, ledger: dict, **overrides) -> dict:
        record = _record("authorization-internal-authorized.json")
        record["evidence_cut"] = {
            "ledgerSha256": ops13._sha256(self.ledger_path.read_bytes()),
            "ledgerEntries": len(ledger["entries"]),
            "intakeIds": [e["intakeId"] for e in ledger["entries"]],
        }
        record.update(overrides)
        return record


class GovernanceModel(unittest.TestCase):
    def test_the_seven_authorities_are_defined(self) -> None:
        self.assertEqual(len(ops13.AUTHORITIES), 7)
        self.assertEqual(set(ops13.ROLE_BY_AUTHORITY.values()), {
            "SECURITY_REVIEWER", "SECURITY_OWNER", "ALPHA_PROGRAM_OWNER",
            "RELEASE_AUTHORITY", "KEY_AUTHORITY", "SECOND_APPROVER",
            "HARDWARE_VALIDATION_OWNER"})

    def test_the_committed_model_agrees_with_the_module(self) -> None:
        self.assertEqual(ops13._governance_shape_problems(), [])

    def test_a_role_in_a_json_file_is_not_an_authority_action(self) -> None:
        levels = ops13.authority_levels([], _empty_ledger(), [], [], [], [])
        for authority_id, row in levels.items():
            self.assertEqual(row["level"], "ROLE_DEFINED", authority_id)
            self.assertIn("not an authority action", row["basis"])

    def test_an_assignment_raises_the_level_to_assigned_only(self) -> None:
        levels = ops13.authority_levels(_assignments(), _empty_ledger(),
                                        [], [], [], [])
        for authority_id, row in levels.items():
            self.assertEqual(row["level"], "AUTHORITY_ASSIGNED",
                             authority_id)

    def test_an_active_policy_is_the_alpha_owners_act(self) -> None:
        policy = _seal(_record("sufficiency-policy-active.json"))
        levels = ops13.authority_levels(_assignments(), _empty_ledger(),
                                        [policy], [], [], [])
        self.assertEqual(levels["AUTH-ALPHA-PROGRAM"]["level"],
                         "AUTHORITY_ACTED")
        self.assertEqual(levels["AUTH-RELEASE"]["level"],
                         "AUTHORITY_ASSIGNED")

    def test_the_seal_algorithm_matches_phase9(self) -> None:
        """The two spellings of the seal must never drift."""
        sample = {"a": 1, "nested": {"b": [1, 2]}, "seal": "ignored"}
        self.assertEqual(ops13.seal_record(sample),
                         intake.seal_entry(sample))


class AssignmentRecords(unittest.TestCase):
    def test_the_fixture_assignments_validate(self) -> None:
        for record in _fixture("authority-assignments.json")["assignments"]:
            self.assertEqual(ops13.validate_assignment(record), [])

    def test_a_missing_field_is_refused(self) -> None:
        record = _fixture("authority-assignments.json")["assignments"][0]
        record = {k: v for k, v in record.items() if k != "assignedBy"}
        issues = ops13.validate_assignment(record)
        self.assertTrue(any("assignedBy" in i for i in issues), issues)

    def test_an_unknown_authority_is_refused(self) -> None:
        record = dict(_fixture("authority-assignments.json")
                      ["assignments"][0], authorityId="AUTH-EMPEROR")
        issues = ops13.validate_assignment(record)
        self.assertTrue(any("not a defined authority" in i for i in issues),
                        issues)

    def test_the_fixture_wrapper_is_refused(self) -> None:
        issues = ops13.validate_assignment(
            _fixture("authority-assignments.json"))
        self.assertTrue(any("fixture" in i for i in issues), issues)

    def test_assignment_dates_are_exact_valid_calendar_dates(self) -> None:
        original = _fixture("authority-assignments.json")["assignments"][0]
        for invalid in ("2026-02-30", "2026-08-19-later"):
            with self.subTest(value=invalid):
                issues = ops13.validate_assignment(
                    dict(original, date=invalid))
                self.assertTrue(any("exact, valid" in issue
                                    for issue in issues), issues)


class SeparationOfDuties(unittest.TestCase):
    def test_distinct_identities_hold_separation(self) -> None:
        self.assertEqual(
            ops13.separation_violations(_assignments(), []), [])

    def test_one_identity_in_an_incompatible_pair_fails(self) -> None:
        assignments = _assignments() + [_seal(
            _fixture("authority-assignments.json")["overlapAssignment"])]
        violations = ops13.separation_violations(assignments, [])
        self.assertEqual(len(violations), 1)
        self.assertIn("AUTH-KEY", violations[0]["roles"])
        self.assertIn("AUTH-SECOND-APPROVER", violations[0]["roles"])
        self.assertIn("recorded policy decision", violations[0]["problem"])

    def test_a_recorded_overlap_decision_permits_it(self) -> None:
        assignments = _assignments() + [_seal(
            _fixture("authority-assignments.json")["overlapAssignment"])]
        decision = _fixture("authority-assignments.json")["overlapDecision"]
        self.assertEqual(
            ops13.separation_violations(assignments, [decision]), [])

    def test_an_incomplete_overlap_decision_permits_nothing(self) -> None:
        assignments = _assignments() + [_seal(
            _fixture("authority-assignments.json")["overlapAssignment"])]
        decision = dict(_fixture("authority-assignments.json")
                        ["overlapDecision"])
        del decision["reason"]
        violations = ops13.separation_violations(assignments, [decision])
        self.assertEqual(len(violations), 1)


class ThresholdPolicies(unittest.TestCase):
    def test_zero_policies_is_undefined(self) -> None:
        subject = {_IMAGE[7:]}
        self.assertEqual(ops13.policy_registry_state([], subject),
                         "SUFFICIENCY_POLICY_UNDEFINED")

    def test_a_hundred_reports_without_thresholds_stay_undetermined(
            self) -> None:
        register = _empty_alpha()
        register["counts"] = {"acceptedReports": 100, "boundReports": 100}
        register["reports"] = [
            {"classification": "ACCEPTED", "testerId": "T-%03d" % n,
             "reportType": "SUCCESS", "journey": "A"}
            for n in range(1, 101)
        ]
        result = ops13.evaluate_sufficiency(
            [], register, _empty_security(), _empty_ledger(),
            {_IMAGE[7:]})
        self.assertEqual(result["determination"],
                         "SUFFICIENCY_UNDETERMINED")
        self.assertEqual(result["policyState"],
                         "SUFFICIENCY_POLICY_UNDEFINED")
        self.assertEqual(result["measures"]["acceptedTesterReports"], 100)

    def test_a_proposed_policy_is_not_active(self) -> None:
        proposed = _record("sufficiency-policy-active.json")
        proposed["status"] = "PROPOSED"
        state = ops13.policy_registry_state([proposed], {_IMAGE[7:]})
        self.assertEqual(state, "SUFFICIENCY_POLICY_PROPOSED")

    def test_activation_requires_an_assigned_owner(self) -> None:
        policy = _record("sufficiency-policy-active.json")
        issues = ops13.validate_policy(policy, [])
        self.assertTrue(any("assigned AUTH-ALPHA-PROGRAM" in i
                            for i in issues), issues)
        self.assertEqual(ops13.validate_policy(policy, _assignments()), [])

    def test_an_active_policy_with_a_null_dimension_is_refused(self) -> None:
        policy = _record("sufficiency-policy-active.json")
        policy["thresholds"]["minimumDistinctTesters"] = None
        issues = ops13.validate_policy(policy, _assignments())
        self.assertTrue(any("may not leave" in i for i in issues), issues)

    def test_a_missing_dimension_is_refused(self) -> None:
        policy = _record("sufficiency-policy-active.json")
        del policy["thresholds"]["minimumEvidencePeriodDays"]
        issues = ops13.validate_policy(policy, _assignments())
        self.assertTrue(any("unenforced fiction" in i for i in issues),
                        issues)

    def test_a_policy_for_other_bytes_activates_nothing_here(self) -> None:
        policy = _record("sufficiency-policy-active.json")
        policy["artifact_digest"] = "sha256:" + "b" * 64
        state = ops13.policy_registry_state([policy], {_IMAGE[7:]})
        self.assertEqual(state, "SUFFICIENCY_POLICY_UNDEFINED")

    def test_editing_an_active_policy_fails_immutability(self) -> None:
        sealed = _seal(_record("sufficiency-policy-active.json"))
        sealed["thresholds"]["minimumAcceptedTesterReports"] = 0
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.sealed_records({"records": [sealed]}, "policy_id",
                                 "test registry")
        self.assertIn("IMMUTABILITY FAIL", str(caught.exception))

    def test_supersession_preserves_the_old_policy(self) -> None:
        first = _record("sufficiency-policy-active.json")
        second = _record("sufficiency-policy-active.json")
        second["policy_id"] = "SUFFICIENCY-POLICY-002"
        second["supersedes"] = "SUFFICIENCY-POLICY-001"
        second["thresholds"]["minimumDistinctTesters"] = 5
        active = ops13.active_policy([first, second], {_IMAGE[7:]})
        self.assertEqual(active["policy_id"], "SUFFICIENCY-POLICY-002")
        self.assertEqual(first["thresholds"]["minimumDistinctTesters"], 1)

    def test_two_unsuperseded_actives_are_refused(self) -> None:
        first = _record("sufficiency-policy-active.json")
        second = _record("sufficiency-policy-active.json")
        second["policy_id"] = "SUFFICIENCY-POLICY-002"
        problems = ops13.policy_chain_problems([first, second])
        self.assertTrue(any("never a parallel truth" in p
                            for p in problems), problems)

    def test_a_dangling_supersedes_is_refused(self) -> None:
        record = _record("sufficiency-policy-active.json")
        record["supersedes"] = "SUFFICIENCY-POLICY-099"
        problems = ops13.policy_chain_problems([record])
        self.assertTrue(any("unknown policy" in p for p in problems),
                        problems)

    def test_zero_evidence_against_an_active_policy_is_insufficient(
            self) -> None:
        policy = _record("sufficiency-policy-active.json")
        result = ops13.evaluate_sufficiency(
            [policy], _empty_alpha(), _empty_security(), _empty_ledger(),
            {_IMAGE[7:]})
        self.assertEqual(result["determination"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(result["shortfalls"])


class BlockingRegistry(unittest.TestCase):
    def test_the_committed_registry_reproduces(self) -> None:
        _, problems = ops13.blocking_from_disk()
        self.assertEqual(problems, [])

    def test_all_ten_inherit_blocking_with_titles_verbatim(self) -> None:
        registry = json.loads(_BLOCKING.read_text(encoding="utf-8"))
        decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        titles = {c["condition"]: c["title"]
                  for c in decision["blocking_conditions"]}
        self.assertEqual(len(registry["conditions"]), 10)
        for row in registry["conditions"]:
            self.assertEqual(row["class"], "BLOCKING")
            self.assertEqual(row["title"], titles[row["condition"]])

    def test_a_drifted_source_pin_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="phase13-blocking-"))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        drifted = json.loads(_BLOCKING.read_text(encoding="utf-8"))
        key = ("qualification/phase8/conditions/"
               "ALPHA_RELEASE_BLOCKING_CONDITIONS.md")
        drifted["sourcePins"][key]["sha256"] = "0" * 64
        path = scratch / "blocking-conditions.json"
        path.write_text(json.dumps(drifted), encoding="utf-8")
        original = ops13.BLOCKING_PATH
        ops13.BLOCKING_PATH = path
        self.addCleanup(setattr, ops13, "BLOCKING_PATH", original)
        _, problems = ops13.blocking_from_disk()
        self.assertTrue(any("changed under the committed pin" in p
                            for p in problems), problems)

    def test_reclassification_without_an_assignment_is_refused(self) -> None:
        decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        record = _record("blocking-reclassification.json")
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.build_blocking(decision, _empty_ledger(), [record], [],
                                 "0" * 64, 1)
        self.assertIn("not an authority action", str(caught.exception))

    def test_a_complete_recorded_reclassification_applies(self) -> None:
        decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        record = _record("blocking-reclassification.json")
        registry = ops13.build_blocking(decision, _empty_ledger(),
                                        [record], _assignments(),
                                        "0" * 64, 1)
        by_number = {r["condition"]: r for r in registry["conditions"]}
        self.assertEqual(by_number[9]["class"], "REQUIRES_HUMAN_DECISION")
        self.assertIn("RECLASSIFY-001", by_number[9]["classBasis"])
        for number in set(range(1, 11)) - {9}:
            self.assertEqual(by_number[number]["class"], "BLOCKING")

    def test_an_incomplete_reclassification_weakens_nothing(self) -> None:
        decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        record = _record("blocking-reclassification.json")
        del record["policyBasis"]
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.build_blocking(decision, _empty_ledger(), [record],
                                 _assignments(), "0" * 64, 1)

    def test_true_by_absence_is_not_adverse(self) -> None:
        registry = json.loads(_BLOCKING.read_text(encoding="utf-8"))
        for row in registry["conditions"]:
            if row["state"] == "TRUE":
                self.assertEqual(row["evidenceCharacter"],
                                 "ABSENCE_OF_EVIDENCE", row)


class ConflictModel(unittest.TestCase):
    def test_pass_and_fail_require_a_human_decision(self) -> None:
        observations = _fixture("conflicting-observations.json")[
            "alphaObservations"]
        result = ops13.classify_evidence_conflict("alpha", observations)
        self.assertEqual(result["conflictStatus"], "CONFLICT")
        self.assertEqual(result["resolution"], "REQUIRES_HUMAN_DECISION")
        self.assertEqual(result["effectiveAssessment"], ["FAIL"])
        self.assertEqual(result["decisionAuthorityRequired"],
                         "AUTH-ALPHA-PROGRAM")
        self.assertEqual(result["evidence"], observations)

    def test_the_security_domain_escalates_to_the_security_owner(
            self) -> None:
        observations = _fixture("conflicting-observations.json")[
            "securityObservations"]
        result = ops13.classify_evidence_conflict("security", observations)
        self.assertEqual(result["decisionAuthorityRequired"],
                         "AUTH-SECURITY-OWNER")
        self.assertEqual(result["effectiveAssessment"], ["CONFIRMED"])

    def test_unanimous_observations_do_not_conflict(self) -> None:
        result = ops13.classify_evidence_conflict("hardware", [
            {"reference": "HW-001", "assessment": "PASS",
             "favorable": True},
            {"reference": "HW-002", "assessment": "PASS",
             "favorable": True},
        ])
        self.assertEqual(result["conflictStatus"], "NO_CONFLICT")

    def test_an_unstated_direction_is_refused(self) -> None:
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.classify_evidence_conflict("alpha", [
                {"reference": "X", "assessment": "PASS"}])

    def test_resolution_requires_the_assigned_domain_authority(
            self) -> None:
        resolution = _fixture("conflicting-observations.json")["resolution"]
        self.assertEqual(
            ops13.validate_conflict_resolution(resolution, _assignments()),
            [])
        issues = ops13.validate_conflict_resolution(resolution, [])
        self.assertTrue(any("assigned AUTH-HARDWARE" in i for i in issues),
                        issues)


class RiskAcceptance(unittest.TestCase):
    _SEVERITIES = {"SEC-BL-001": "Critical"}

    def _subject(self) -> set[str]:
        return intake.subject_digests(_empty_ledger())

    def test_the_fixture_acceptance_validates(self) -> None:
        record = _record("risk-acceptance-critical.json")
        self.assertEqual(ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES), [])

    def test_a_missing_field_is_refused(self) -> None:
        record = _record("risk-acceptance-critical.json")
        del record["revocation_conditions"]
        issues = ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES)
        self.assertTrue(any("revocation_conditions" in i for i in issues),
                        issues)

    def test_critical_requires_the_security_owner(self) -> None:
        record = _record("risk-acceptance-critical.json")
        record["authority"] = "Constructed Fixture Release Authority"
        issues = ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES)
        self.assertTrue(any("AUTH-SECURITY-OWNER" in i for i in issues),
                        issues)

    def test_accepted_risk_is_not_not_affected(self) -> None:
        record = _record("risk-acceptance-critical.json")
        record["applicability"] = "NOT_APPLICABLE"
        issues = ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES)
        self.assertTrue(any("not NOT_AFFECTED" in i for i in issues),
                        issues)

    def test_an_acceptance_cannot_close_the_finding(self) -> None:
        record = _record("risk-acceptance-critical.json")
        record["closes_finding"] = True
        issues = ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES)
        self.assertTrue(any("never closes" in i for i in issues), issues)

    def test_a_dangling_finding_reference_fails_closed(self) -> None:
        record = _record("risk-acceptance-critical.json")
        record["finding_ids"] = ["SEC-BL-999"]
        issues = ops13.validate_risk_acceptance(
            record, _assignments(), self._subject(), self._SEVERITIES)
        self.assertTrue(any("dangling" in i for i in issues), issues)

    def test_expiry_derives_and_silence_refuses(self) -> None:
        record = _record("risk-acceptance-critical.json")
        self.assertEqual(ops13.risk_acceptance_state(record, "2026-09-01"),
                         "STANDING")
        self.assertEqual(ops13.risk_acceptance_state(record, "2026-09-20"),
                         "EXPIRED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.risk_acceptance_state(record, None)

    def test_risk_dates_and_evaluation_date_fail_closed(self) -> None:
        for field in ("accepted_at", "expires_at"):
            for invalid in ("2026-02-30", "2026-08-19-later"):
                with self.subTest(field=field, value=invalid):
                    record = _record("risk-acceptance-critical.json")
                    record[field] = invalid
                    issues = ops13.validate_risk_acceptance(
                        record, _assignments(), self._subject(),
                        self._SEVERITIES)
                    self.assertTrue(any(field in issue and "exact, valid"
                                        in issue for issue in issues), issues)
        record = _record("risk-acceptance-critical.json")
        for invalid in ("2026-02-30", "2026-09-01-later"):
            with self.subTest(as_of=invalid):
                with self.assertRaises(ops13.BoundaryViolation):
                    ops13.risk_acceptance_state(record, invalid)

    def test_an_acceptance_never_transfers_to_a_successor(self) -> None:
        record = _record("risk-acceptance-critical.json")
        successor = _fixture("successor-artifact-entry.json")[
            "successorEntry"]
        digests = {ops13._normalize_digest(d)
                   for d in successor["digests"].values()}
        result = ops13.risk_acceptance_applies(record, digests)
        self.assertEqual(result["result"], "REFUSED")
        self.assertIn("never transfers", result["reasoning"])
        self.assertEqual(ops13.risk_acceptance_applies(
            record, self._subject())["result"], "APPLIES")


class AuthorizationRecords(_Scratch):
    def test_internal_json_claiming_authorized_is_refused(self) -> None:
        record = _record("authorization-internal-authorized.json")
        issues = self._validate(record, assignments=_assignments())
        for source in ops13.AUTHORIZATION_FLOOR_SOURCES:
            self.assertTrue(any(source in i for i in issues),
                            "floor did not name %s: %s" % (source, issues))

    def test_the_fixture_wrapper_is_rejected(self) -> None:
        issues = self._validate(
            _fixture("authorization-internal-authorized.json"))
        self.assertEqual(len(issues), 1)
        self.assertIn("never an authorization", issues[0])

    def test_a_wrong_artifact_does_not_apply(self) -> None:
        record = _record("authorization-wrong-artifact.json")
        issues = self._validate(record)
        self.assertTrue(any("DOES_NOT_APPLY" in i for i in issues), issues)

    def test_no_expiry_is_invalid(self) -> None:
        record = _record("authorization-no-expiry.json")
        issues = self._validate(record)
        self.assertTrue(any("no infinite authorization" in i.lower()
                            for i in issues), issues)

    def test_authorization_dates_are_exact_valid_calendar_dates(self) -> None:
        for field in ("issued_at", "expires_at", "decision_timestamp"):
            for invalid in ("2026-02-30", "2026-08-19-later"):
                with self.subTest(field=field, value=invalid):
                    record = _record("authorization-internal-authorized.json")
                    record[field] = invalid
                    issues = self._validate(record)
                    self.assertTrue(any(
                        field in issue and "exact, valid" in issue
                        for issue in issues), issues)

    def test_a_stored_revocation_status_is_refused(self) -> None:
        record = _record("authorization-internal-authorized.json")
        record["revocation_status"] = False
        issues = self._validate(record)
        self.assertTrue(any("never stored" in i for i in issues), issues)

    def test_an_unassigned_release_authority_is_refused(self) -> None:
        context = self._full_context()
        assignments = [a for a in context.pop("assignments")
                       if a["authorityId"] != "AUTH-RELEASE"]
        record = self._authz(context["ledger"])
        issues = self._validate(record, assignments=assignments, **context)
        self.assertTrue(any("not an assigned AUTH-RELEASE" in i
                            for i in issues), issues)

    def test_a_signing_drill_satisfies_nothing(self) -> None:
        drill = _record("signing-metadata-valid.json", _FIXTURES10)
        drill["category"] = "SIGNING DRILL"
        entry = self._register("signing", drill)
        self.assertEqual(entry["status"], "REJECTED")
        self.assertFalse(entry["gateEligible"])
        record = _record("authorization-internal-authorized.json")
        issues = self._validate(
            record,
            ledger=json.loads(self.ledger_path.read_text(encoding="utf-8")),
            assignments=_assignments())
        self.assertTrue(any("signing" in i for i in issues), issues)

    def test_the_signer_may_not_be_the_second_approver(self) -> None:
        context = self._full_context()
        ledger = context["ledger"]
        overlap = _record("second-approval-signer-overlap.json")
        entry = self._register("second-approval", overlap)
        self.assertEqual(entry["status"], "ACCEPTED")
        # Rebuild the ledger with the overlapping approval superseding the
        # clean one so _accepted_record reads the overlap.
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        ledger["entries"] = [
            e for e in ledger["entries"]
            if not (e["source"] == "second-approval"
                    and e["intakeId"] != entry["intakeId"])]
        context["ledger"] = ledger
        context["ledger_sha256"] = ops13._sha256(json.dumps(
            ledger, sort_keys=True).encode("utf-8"))
        record = self._authz(ledger)
        record["evidence_cut"]["ledgerSha256"] = context["ledger_sha256"]
        issues = self._validate(record, **context)
        self.assertTrue(any("also appears as an approver" in i
                            for i in issues), issues)
        decision = _fixture("authority-assignments.json")["overlapDecision"]
        issues = self._validate(record, overlap_decisions=[decision],
                                **context)
        self.assertFalse(any("also appears as an approver" in i
                             for i in issues), issues)

    def test_undefined_thresholds_refuse_authorization(self) -> None:
        context = self._full_context()
        context["policies"] = []
        record = self._authz(context["ledger"])
        issues = self._validate(record, **context)
        self.assertTrue(any("SUFFICIENCY_UNDETERMINED" in i
                            for i in issues), issues)

    def test_an_unsatisfied_security_gate_refuses(self) -> None:
        context = self._full_context()
        context["security_register"] = _empty_security("UNDER_ANALYSIS")
        record = self._authz(context["ledger"])
        issues = self._validate(record, **context)
        self.assertTrue(any("not SATISFIED" in i for i in issues), issues)

    def test_a_true_blocking_condition_refuses(self) -> None:
        context = self._full_context()
        blocking = context["blocking"]
        blocking["conditions"][0]["state"] = "TRUE"
        record = self._authz(context["ledger"])
        issues = self._validate(record, **context)
        self.assertTrue(any("is not FALSE" in i for i in issues), issues)

    def test_an_expired_acceptance_blocks_authorization(self) -> None:
        context = self._full_context()
        risk = _record("risk-acceptance-critical.json")
        record = self._authz(context["ledger"],
                             accepted_risks=["RISK-001"])
        issues = self._validate(record, risks=[risk], as_of="2026-10-01",
                                **context)
        self.assertTrue(any("expired" in i for i in issues), issues)

    def test_an_evidence_cut_for_other_bytes_is_refused(self) -> None:
        context = self._full_context()
        record = self._authz(context["ledger"])
        record["evidence_cut"]["ledgerSha256"] = "f" * 64
        issues = self._validate(record, **context)
        self.assertTrue(any("different evidence" in i for i in issues),
                        issues)

    def test_the_satisfied_floor_validates_and_authorizes(self) -> None:
        context = self._full_context()
        record = self._authz(context["ledger"])
        issues = self._validate(record, **context)
        self.assertEqual(issues, [])
        state = ops13.authorization_transition(
            "READY_FOR_AUTHORIZATION", "AUTHORIZED",
            {"authorizationRecord": record, "validationIssues": issues})
        self.assertEqual(state, "AUTHORIZED")


class RevocationAndExpiry(unittest.TestCase):
    def _authorizations(self) -> list[dict]:
        return [_record("authorization-internal-authorized.json")]

    def test_a_valid_revocation_validates(self) -> None:
        record = _record("revocation-of-authorization.json")
        subject = intake.subject_digests(_empty_ledger())
        self.assertEqual(ops13.validate_revocation(
            record, self._authorizations(), _assignments(), subject), [])

    def test_an_unknown_target_is_refused(self) -> None:
        record = _record("revocation-of-authorization.json")
        record["target_authorization"] = "AUTHORIZATION-099"
        issues = ops13.validate_revocation(
            record, self._authorizations(), _assignments(),
            intake.subject_digests(_empty_ledger()))
        self.assertTrue(any("does not exist" in i for i in issues), issues)

    def test_an_unassigned_revoker_is_refused(self) -> None:
        record = _record("revocation-of-authorization.json")
        issues = ops13.validate_revocation(
            record, self._authorizations(), [],
            intake.subject_digests(_empty_ledger()))
        self.assertTrue(any("assigned AUTH-RELEASE" in i for i in issues),
                        issues)

    def test_states_derive_and_revocation_outranks_expiry(self) -> None:
        authorization = self._authorizations()[0]
        revocation = _record("revocation-of-authorization.json")
        self.assertEqual(ops13.authorization_state_of(
            authorization, [], "2026-09-01"), "AUTHORIZED")
        self.assertEqual(ops13.authorization_state_of(
            authorization, [], "2026-11-20"), "EXPIRED")
        self.assertEqual(ops13.authorization_state_of(
            authorization, [revocation], "2026-11-20"), "REVOKED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.authorization_state_of(authorization, [], None)

    def test_editing_a_sealed_revocation_fails_immutability(self) -> None:
        sealed = _seal(_record("revocation-of-authorization.json"))
        sealed["revocation_status"] = False
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.sealed_records({"records": [sealed]}, "revocation_id",
                                 "revocations")
        self.assertIn("IMMUTABILITY FAIL", str(caught.exception))

    def test_revoked_never_returns_to_authorized(self) -> None:
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.authorization_transition("REVOKED", "AUTHORIZED", {})

    def test_authorized_reaches_revoked_only_with_the_record(self) -> None:
        revocation = _record("revocation-of-authorization.json")
        self.assertEqual(ops13.authorization_transition(
            "AUTHORIZED", "REVOKED", {"revocationRecord": revocation}),
            "REVOKED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.authorization_transition("AUTHORIZED", "REVOKED", {})

    def test_expiry_requires_a_past_date(self) -> None:
        self.assertEqual(ops13.authorization_transition(
            "AUTHORIZED", "EXPIRED",
            {"asOf": "2026-11-20", "expiresAt": "2026-11-19"}), "EXPIRED")
        with self.assertRaises(ops13.BoundaryViolation):
            ops13.authorization_transition(
                "AUTHORIZED", "EXPIRED",
                {"asOf": "2026-11-01", "expiresAt": "2026-11-19"})


class SuccessorArtifacts(unittest.TestCase):
    def test_authorization_never_crosses_an_artifact_edge(self) -> None:
        record = _record("authorization-internal-authorized.json")
        successor = _fixture("successor-artifact-entry.json")[
            "successorEntry"]
        result = ops13.authorization_applies(record, successor)
        self.assertEqual(result["result"], "REFUSED")
        self.assertIn("NOT_AUTHORIZED", result["reasoning"])
        self.assertIn("never transfers", result["reasoning"])

    def test_authorization_applies_to_its_own_bytes(self) -> None:
        record = _record("authorization-internal-authorized.json")
        graph = json.loads(_GRAPH.read_text(encoding="utf-8"))
        subject = graph["artifacts"][0]
        self.assertEqual(ops13.authorization_applies(record, subject)
                         ["result"], "APPLIES")

    def test_a_transfer_decision_transfers_no_authorization(self) -> None:
        """Phase 10 transfer decisions cover evidence. authorization_applies
        deliberately has no graph parameter: there is no mechanism to ride."""
        record = _record("authorization-internal-authorized.json")
        successor = _fixture("successor-artifact-entry.json")[
            "successorEntry"]
        self.assertEqual(ops13.authorization_applies(record, successor)
                         ["result"], "REFUSED")


class StateMachine(unittest.TestCase):
    def test_the_vocabulary_and_priority_agree(self) -> None:
        self.assertEqual(sorted(ops13.AUTHORIZATION_STATES),
                         sorted(ops13.DECISION_PRIORITY))
        self.assertEqual(sorted(ops13.AUTHORIZATION_TRANSITIONS),
                         sorted(ops13.AUTHORIZATION_STATES))
        self.assertEqual(set(ops13.CANDIDATE_DECISION_BY_STATE),
                         set(ops13.AUTHORIZATION_STATES))

    def test_every_forbidden_transition_is_refused(self) -> None:
        """The full sweep: every state pair outside the table refuses."""
        for current in ops13.AUTHORIZATION_STATES:
            for target in ops13.AUTHORIZATION_STATES:
                if target in ops13.AUTHORIZATION_TRANSITIONS[current]:
                    continue
                with self.assertRaises(
                        ops13.BoundaryViolation,
                        msg="%s -> %s must refuse" % (current, target)):
                    ops13.authorization_transition(current, target, {})

    def test_only_ready_for_authorization_reaches_authorized(self) -> None:
        sources = [state for state in ops13.AUTHORIZATION_STATES
                   if "AUTHORIZED"
                   in ops13.AUTHORIZATION_TRANSITIONS[state]]
        self.assertEqual(sources, ["READY_FOR_AUTHORIZATION"])
        for state in ("EVIDENCE_PENDING", "SUFFICIENCY_UNDEFINED",
                      "BLOCKED", "REVOKED", "EXPIRED"):
            with self.assertRaises(ops13.BoundaryViolation):
                ops13.authorization_transition(state, "AUTHORIZED", {})

    def test_every_guard_refuses_silence(self) -> None:
        cases = (
            ("READY_FOR_AUTHORIZATION", "AUTHORIZED"),
            ("REQUIRES_MORE_EVIDENCE", "READY_FOR_AUTHORIZATION"),
            ("AUTHORIZED", "REVOKED"),
            ("AUTHORIZED", "EXPIRED"),
            ("READY_FOR_AUTHORIZATION", "BLOCKED"),
            ("SECURITY_REVIEW_PENDING", "REMEDIATION_REQUIRED"),
        )
        for current, target in cases:
            with self.assertRaises(
                    ops13.BoundaryViolation,
                    msg="%s -> %s with no context must refuse"
                        % (current, target)):
                ops13.authorization_transition(current, target, {})

    def test_ready_requires_floor_sufficiency_and_clear_blocking(
            self) -> None:
        good = {"floorSatisfied": True,
                "sufficiency": {"determination": "SUFFICIENT"},
                "blockingClear": True}
        self.assertEqual(ops13.authorization_transition(
            "REQUIRES_MORE_EVIDENCE", "READY_FOR_AUTHORIZATION", good),
            "READY_FOR_AUTHORIZATION")
        for broken in ({"floorSatisfied": False},
                       {"sufficiency": {"determination":
                                        "SUFFICIENCY_UNDETERMINED"}},
                       {"blockingClear": False}):
            context = dict(good, **broken)
            with self.assertRaises(ops13.BoundaryViolation):
                ops13.authorization_transition(
                    "REQUIRES_MORE_EVIDENCE", "READY_FOR_AUTHORIZATION",
                    context)

    def test_the_ladder_is_most_restrictive_first(self) -> None:
        base = dict(standing=None, remediation=[], adverse=[],
                    evidence_total=0,
                    security_gate="AWAITING_EXTERNAL_EVIDENCE",
                    alpha_accepted=0,
                    sufficiency={"policyState":
                                 "SUFFICIENCY_POLICY_UNDEFINED",
                                 "determination":
                                 "SUFFICIENCY_UNDETERMINED"},
                    floor_missing=["security-review"], expired_risks=[])
        self.assertEqual(ops13.derive_authorization_state(**base)["state"],
                         "EVIDENCE_PENDING")
        stacked = dict(base,
                       standing={"authorizationId": "AUTHORIZATION-001",
                                 "state": "REVOKED"},
                       remediation=["SEC-BL-001"],
                       adverse=["condition 1"])
        self.assertEqual(ops13.derive_authorization_state(**stacked)
                         ["state"], "REVOKED")
        stacked["standing"] = None
        self.assertEqual(ops13.derive_authorization_state(**stacked)
                         ["state"], "REMEDIATION_REQUIRED")
        stacked["remediation"] = []
        self.assertEqual(ops13.derive_authorization_state(**stacked)
                         ["state"], "BLOCKED")

    def test_an_expired_standing_authorization_derives_expired(
            self) -> None:
        result = ops13.derive_authorization_state(
            standing={"authorizationId": "AUTHORIZATION-001",
                      "state": "EXPIRED", "expiresAt": "2026-11-19"},
            remediation=[], adverse=[], evidence_total=5,
            security_gate="SATISFIED", alpha_accepted=1,
            sufficiency={"policyState": "SUFFICIENCY_POLICY_ACTIVE",
                         "determination": "SUFFICIENT"},
            floor_missing=[], expired_risks=[])
        self.assertEqual(result["state"], "EXPIRED")

    def test_a_satisfied_world_without_a_decision_is_ready_not_authorized(
            self) -> None:
        result = ops13.derive_authorization_state(
            standing=None, remediation=[], adverse=[], evidence_total=5,
            security_gate="SATISFIED", alpha_accepted=1,
            sufficiency={"policyState": "SUFFICIENCY_POLICY_ACTIVE",
                         "determination": "SUFFICIENT"},
            floor_missing=[], expired_risks=[])
        self.assertEqual(result["state"], "READY_FOR_AUTHORIZATION")
        self.assertIn("cannot make it", result["basis"])
        self.assertEqual(
            ops13.CANDIDATE_DECISION_BY_STATE[result["state"]],
            "NOT_AUTHORIZED")


class DerivedStatus(_Scratch):
    def test_the_committed_status_reproduces(self) -> None:
        self.assertEqual(ops13.verify_all(), [])

    def test_zero_evidence_derives_evidence_pending(self) -> None:
        status = json.loads(_STATUS.read_text(encoding="utf-8"))
        self.assertEqual(status["authorizationState"], "EVIDENCE_PENDING")
        self.assertEqual(status["candidateDecision"],
                         "REQUIRES_MORE_EVIDENCE")
        self.assertFalse(status["authorizationFloor"]["satisfied"])
        missing = "; ".join(status["authorizationFloor"]["missing"])
        for source in ops13.AUTHORIZATION_FLOOR_SOURCES:
            self.assertIn(source, missing)
        self.assertEqual(status["sufficiency"]["determination"],
                         "SUFFICIENCY_UNDETERMINED")
        self.assertIsNone(status["standingAuthorization"])

    def test_the_status_says_it_does_not_authorize(self) -> None:
        status = json.loads(_STATUS.read_text(encoding="utf-8"))
        self.assertIn("PHASE 13 DOES NOT AUTHORIZE THE ARTIFACT",
                      status["note"])
        self.assertEqual(status["decisionPriority"],
                         list(ops13.DECISION_PRIORITY))

    def test_every_authority_is_role_defined_only(self) -> None:
        status = json.loads(_STATUS.read_text(encoding="utf-8"))
        self.assertEqual(len(status["authorityModel"]), 7)
        for authority_id, row in status["authorityModel"].items():
            self.assertEqual(row["level"], "ROLE_DEFINED", authority_id)

    def test_verify_leaves_every_immutable_input_byte_identical(
            self) -> None:
        before = {path: path.read_bytes() for path in self.real_bytes}
        self.assertEqual(ops13.verify_all(), [])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw,
                             "%s changed during verify" % path.name)

    def test_a_missing_history_refuses_derivation(self) -> None:
        blocking = json.loads(_BLOCKING.read_text(encoding="utf-8"))
        governance = {key: [] for key in
                      ("assignments", "overlapDecisions", "policies",
                       "risks", "authorizations", "revocations",
                       "resolutions")}
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.derive_status(
                _empty_ledger(), "0" * 64,
                json.loads(_GRAPH.read_text(encoding="utf-8")),
                json.loads(_DECISION.read_text(encoding="utf-8")),
                json.loads(_REGISTER11.read_text(encoding="utf-8")),
                json.loads(_REGISTER12.read_text(encoding="utf-8")),
                governance, blocking, None, None)
        self.assertIn("seed the first record", str(caught.exception))

    def test_history_is_carried_forward_append_only(self) -> None:
        committed = json.loads(_STATUS.read_text(encoding="utf-8"))
        derived, problems = ops13.sync_status(write=False)
        self.assertEqual(problems, [])
        old_history = committed["stateHistory"]
        self.assertEqual(derived["stateHistory"][: len(old_history)],
                         old_history)


class FixtureBoundary(_Scratch):
    def test_every_fixture_carries_all_three_markers(self) -> None:
        names = sorted(p.name for p in _FIXTURES.glob("*.json"))
        self.assertTrue(names, "no phase13 fixtures found")
        for name in names:
            record = _fixture(name)
            self.assertEqual(record.get("fixtureClass"),
                             "TEST_FIXTURE_ONLY", name)
            self.assertIs(record.get("fixture"), True, name)
            self.assertIs(record.get("test_fixture_only"), True, name)
        self.assertEqual(ops13.verify_fixtures(), [])

    def test_any_single_marker_makes_a_fixture(self) -> None:
        self.assertTrue(ops13.is_fixture(
            {"fixtureClass": "TEST_FIXTURE_ONLY"}))
        self.assertTrue(ops13.is_fixture({"test_fixture_only": True}))
        self.assertTrue(ops13.is_fixture({"fixture": True}))
        self.assertFalse(ops13.is_fixture({"fixture": "yes"}))
        self.assertFalse(ops13.is_fixture({}))

    def test_the_real_intake_rejects_the_fixture_wrapper(self) -> None:
        entry = intake.register(
            self.ledger_path, "second-approval",
            self._stage("wrapper.json", _fixture(
                "authorization-internal-authorized.json")),
            [], "2026-08-19", "phase13 dry run")
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("a fixture is never evidence", entry["statusReason"])

    def test_append_record_refuses_a_fixture(self) -> None:
        with self.assertRaises(ops13.BoundaryViolation) as caught:
            ops13.append_record("assignment", dict(
                _fixture("authority-assignments.json")["assignments"][0],
                fixture=True))
        self.assertIn("never", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 17 source semantics, one-door intake, convergence, and cuts."""

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
from unittest import mock


_ROOT = Path(__file__).resolve().parents[2]
_OPS = _ROOT / "qualification" / "phase17" / "tools" / "external_floor_ops.py"
_VERIFY = _OPS.with_name("verify_phase17.py")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops = _load("phase17_external_floor_under_test", _OPS)


class _RealInputGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.before = {path: path.read_bytes() for path in ops.REAL_IMMUTABLE_INPUTS
                      if path.is_file()}

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.before.items():
            if not path.is_file() or path.read_bytes() != raw:
                raise AssertionError("Phase 17 test mutated real input %s" % path)

    def fixture(self, name: str) -> dict:
        return copy.deepcopy(ops.load_json(ops.FIXTURES / name)["record"])

    def context(self) -> dict:
        return ops._scenario_context()


class RegistryAndBoundary(_RealInputGuard):
    def test_registry_is_exactly_the_five_floor_sources(self) -> None:
        registry = ops.source_registry()
        self.assertEqual(set(registry["sources"]), set(ops.REQUIRED_SOURCES))
        self.assertEqual(ops.registry_problems(registry), [])

    def test_every_registry_row_has_the_complete_contract(self) -> None:
        for source in ops.REQUIRED_SOURCES:
            with self.subTest(source=source):
                row = ops.source_contract(source)
                self.assertEqual(row["canonicalEvidenceClass"],
                                 ops.SOURCE_CLASSES[source])
                for field in ops.REGISTRY_FIELDS:
                    self.assertIn(field, row)

    def test_unknown_sources_fail_closed_without_a_generic_fallback(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.source_contract("generic-external-evidence")
        self.assertIn("never becomes generic", str(caught.exception))
        self.assertIsNone(ops.source_registry()["genericFallback"])

    def test_source_readiness_is_not_a_source_result(self) -> None:
        status = ops.derive_floor_status("e906a48793d7")
        self.assertTrue(all(row["source_operational_ready"]
                            for row in status["sources"]))
        self.assertFalse(any(row["source_contributes_to_floor"]
                             for row in status["sources"]))

    def test_ast_boundary_proves_the_one_door_and_no_clock(self) -> None:
        self.assertEqual(ops.boundary_problems(), [])

    def test_receive_contains_the_only_phase9_register_call(self) -> None:
        tree = ast.parse(_OPS.read_text(encoding="utf-8"))
        calls = []
        for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "register":
                    calls.append(function.name)
        self.assertEqual(calls, ["receive"])

    def test_phase17_is_outside_product_copy_roots(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "*Containerfile*", "*Dockerfile*"],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        )
        for relative in tracked.stdout.splitlines():
            for line in (_ROOT / relative).read_text(
                    encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith(("COPY ", "ADD ")):
                    self.assertNotIn("qualification", line)

    def test_every_fixture_wrapper_is_structurally_marked(self) -> None:
        self.assertEqual(ops.fixture_problems(), [])

    def test_fixture_wrapper_is_terminal_at_evaluation(self) -> None:
        wrapper = ops.load_json(ops.FIXTURES / "production-signing-shaped.json")
        with self.assertRaises(ops.BoundaryViolation):
            ops.evaluate_record("signing", wrapper, "e906a48793d7",
                                "FIXTURE", "2026-08-20", self.context())


class OperatorSurface(_RealInputGuard):
    def test_all_required_commands_are_exposed(self) -> None:
        parser = ops._parser()
        actions = next(action for action in parser._actions
                       if action.dest == "command")
        for command in ("prepare", "inspect", "receive", "validate", "bind",
                        "evaluate", "cut", "assemble", "floor-status", "status",
                        "sync-status"):
            self.assertIn(command, actions.choices)

    def test_prepare_creates_a_template_not_evidence(self) -> None:
        parent = Path(tempfile.mkdtemp(prefix="phase17-prepare-test-"))
        self.addCleanup(shutil.rmtree, parent, ignore_errors=True)
        destination = parent / "hardware-handoff"
        result = ops.prepare("hardware", destination)
        self.assertFalse(result["evidenceCreated"])
        self.assertTrue((destination / "record.template.json").is_file())

    def test_prepare_refuses_an_existing_destination(self) -> None:
        destination = Path(tempfile.mkdtemp(prefix="phase17-existing-test-"))
        self.addCleanup(shutil.rmtree, destination, ignore_errors=True)
        with self.assertRaises(ops.BoundaryViolation):
            ops.prepare("signing", destination)

    def test_prepare_refuses_a_destination_inside_the_repository(self) -> None:
        with self.assertRaises(ops.BoundaryViolation):
            ops.prepare("alpha-feedback", ops.PHASE17 / "prepared-test")

    def test_inspect_rejects_a_marked_fixture_without_revealing_values(self) -> None:
        result = ops.inspect_path(
            "signing", ops.FIXTURES / "production-signing-shaped.json",
            "e906a48793d7", "SIG-001",
        )
        self.assertEqual(result["inspection"], "REJECTED")
        self.assertNotIn("PRIVATE KEY", json.dumps(result))

    def test_inspect_quarantines_secret_classes(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="phase17-secret-test-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        path = base / "record.json"
        record = self.fixture("alpha-report.json")
        record["credential"] = "session_token=abcdefghijklmnopqrstuvwx"
        path.write_text(json.dumps(record), encoding="utf-8")
        result = ops.inspect_path("alpha-feedback", path, "e906a48793d7", "T-017")
        self.assertEqual(result["inspection"], "QUARANTINE")
        self.assertIn("api or session token assignment", result["credentialClasses"])
        self.assertNotIn("abcdefghijklmnopqrstuvwx", json.dumps(result))

    def test_receive_delegates_verbatim_to_phase9(self) -> None:
        stub = mock.Mock()
        stub.register.return_value = {"status": "ACCEPTED"}
        with mock.patch.object(ops, "_phase9", return_value=stub), \
                mock.patch.object(ops, "require_artifact", return_value={
                    "identifier": "e906a48793d7"
                }):
            result = ops.receive(
                "hardware", Path("record.json"), "e906a48793d7", "HW-001",
                [Path("photo.png")], "2026-08-20", "operator", None,
                Path("scratch-ledger.json"),
            )
        self.assertEqual(result["status"], "ACCEPTED")
        stub.register.assert_called_once_with(
            Path("scratch-ledger.json"), "hardware", Path("record.json"),
            [Path("photo.png")], "2026-08-20", "operator", None,
        )

    def test_receive_requires_an_evidence_id(self) -> None:
        with self.assertRaises(ops.BoundaryViolation):
            ops.receive("hardware", Path("x"), "e906a48793d7", "", [],
                        "2026-08-20", "operator", ledger_path=Path("scratch"))

    def test_bind_preserves_unbound_alpha_evidence(self) -> None:
        record = self.fixture("alpha-report.json")
        record.pop("artifactDigest")
        result = ops.bind_record("alpha-feedback", record, "e906a48793d7", "T-017")
        self.assertEqual(result["result"], "UNBOUND")

    def test_bind_refuses_wrong_artifact(self) -> None:
        record = self.fixture("hardware-passing-machine.json")
        record["artifactDigest"] = "f" * 64
        result = ops.bind_record("hardware", record, "e906a48793d7", "HW-001")
        self.assertEqual(result["result"], "DOES_NOT_APPLY")


class SourceSemantics(_RealInputGuard):
    def test_hardware_is_dimensional_and_bounded(self) -> None:
        result = ops.evaluate_record(
            "hardware", self.fixture("hardware-passing-machine.json"),
            "e906a48793d7", "HW-001", "2026-08-20", self.context(),
        )
        self.assertTrue(result["contributes"])
        self.assertEqual(set(result["dimensions"]), set(ops.HARDWARE_DIMENSIONS))
        self.assertIsNone(result["aggregateClaim"])

    def test_a_microphone_failure_survives_an_installation_pass(self) -> None:
        result = ops.evaluate_record(
            "hardware", self.fixture("hardware-mixed-machine.json"),
            "e906a48793d7", "HW-002", "2026-08-20", self.context(),
        )
        self.assertEqual(result["dimensions"]["installation"], "PASS")
        self.assertEqual(result["dimensions"]["microphone"], "FAIL")
        self.assertFalse(result["contributes"])

    def test_native_not_supported_and_fallback_pass_stay_separate(self) -> None:
        record = self.fixture("hardware-passing-machine.json")
        record["results"]["companion-3d-native"]["status"] = "NOT_SUPPORTED"
        result = ops.evaluate_record("hardware", record, "e906a48793d7",
                                     "HW-001", "2026-08-20", self.context())
        self.assertEqual(result["dimensions"]["native 3D"], "NOT_SUPPORTED")
        self.assertEqual(result["dimensions"]["fallback 3D"], "PASS")

    def test_signing_drill_never_contributes(self) -> None:
        result = ops.evaluate_record(
            "signing", self.fixture("signing-drill.json"), "e906a48793d7",
            "SIG-DRILL", "2026-08-20", self.context(),
        )
        self.assertEqual(result["effectiveStatus"], "SIGNING_DRILL")
        self.assertFalse(result["contributes"])

    def test_production_signing_requires_two_matching_digests(self) -> None:
        record = self.fixture("production-signing-shaped.json")
        record["independentlyRecomputedArtifactDigest"] = "f" * 64
        result = ops.evaluate_record("signing", record, "e906a48793d7",
                                     "SIG-001", "2026-08-20", self.context())
        self.assertFalse(result["submittedDigestMatchesRecomputed"])
        self.assertFalse(result["contributes"])

    def test_production_signing_requires_successful_verification(self) -> None:
        record = self.fixture("production-signing-shaped.json")
        record["verificationResult"] = "FAIL"
        result = ops.evaluate_record("signing", record, "e906a48793d7",
                                     "SIG-001", "2026-08-20", self.context())
        self.assertFalse(result["verificationSucceeded"])
        self.assertFalse(result["contributes"])

    def test_second_approval_must_follow_signing(self) -> None:
        record = self.fixture("second-approval-independent.json")
        record["timestamp"] = "2026-08-19T11:00:00Z"
        context = self.context()
        context["signingRecords"] = [self.fixture("production-signing-shaped.json")]
        result = ops.evaluate_record("second-approval", record, "e906a48793d7",
                                     "APPROVAL-1", "2026-08-20", context)
        self.assertTrue(result["orderingProblems"])
        self.assertFalse(result["contributes"])

    def test_authoritative_identity_mapping_detects_role_overlap(self) -> None:
        record = self.fixture("second-approval-independent.json")
        context = self.context()
        context["signingRecords"] = [self.fixture("production-signing-shaped.json")]
        context["identityMap"] = {
            "FIXTURE-SECOND-APPROVER": "PERSON-1",
            "FIXTURE-SIGNER": "PERSON-1",
        }
        result = ops.evaluate_record("second-approval", record, "e906a48793d7",
                                     "APPROVAL-1", "2026-08-20", context)
        self.assertTrue(result["separationViolation"])
        self.assertFalse(result["contributes"])

    def test_alpha_many_reports_cannot_replace_an_undefined_policy(self) -> None:
        context = self.context()
        context["alphaSufficiency"] = {
            "determination": "SUFFICIENCY_UNDETERMINED",
            "policyState": "SUFFICIENCY_POLICY_UNDEFINED",
            "activePolicy": None,
        }
        for _ in range(100):
            result = ops.evaluate_record(
                "alpha-feedback", self.fixture("alpha-report.json"),
                "e906a48793d7", "T-017", "2026-08-20", context,
            )
        self.assertEqual(result["effectiveStatus"], "SUFFICIENCY_UNDETERMINED")
        self.assertFalse(result["contributes"])

    def test_alpha_blocker_overrules_sufficiency(self) -> None:
        context = self.context(); context["alphaBlockers"] = ["ALPHA-EXT-001"]
        result = ops.evaluate_record("alpha-feedback", self.fixture("alpha-report.json"),
                                     "e906a48793d7", "T-017", "2026-08-20", context)
        self.assertFalse(result["contributes"])

    def test_security_uses_the_phase11_gate_not_the_receipt_assessment(self) -> None:
        context = self.context(); context["securityGate"] = "BLOCKED"
        result = ops.evaluate_record(
            "security-review", self.fixture("security-favorable.json"),
            "e906a48793d7", "REVIEW-001", "2026-08-20", context,
        )
        self.assertEqual(result["effectiveStatus"], "BLOCKED")
        self.assertFalse(result["contributes"])


class FloorAndCuts(_RealInputGuard):
    def test_real_floor_rederives_zero_of_five(self) -> None:
        status = ops.derive_floor_status("e906a48793d7")
        self.assertEqual(status["convergence"]["count"], 0)
        self.assertEqual(status["convergence"]["missing"], list(ops.REQUIRED_SOURCES))
        self.assertEqual(status["authorizationState"], "EVIDENCE_PENDING")
        self.assertEqual(status["candidateDecision"], "REQUIRES_MORE_EVIDENCE")

    def test_real_artifact_remains_root_frozen_and_unsigned(self) -> None:
        subject = ops.derive_floor_status("e906a48793d7")["subjectArtifact"]
        self.assertEqual(subject["relationship"], "ROOT")
        self.assertTrue(subject["frozen"])
        self.assertTrue(subject["unchanged"])
        self.assertEqual(subject["signingStatus"], "UNSIGNED")

    def test_zero_through_four_sources_cannot_satisfy_the_floor(self) -> None:
        base = [{
            "source": source, "evidenceIds": [source + "-1"],
            "contributes_to_floor": True, "conflictState": "NONE",
            "provenance": {"ownerEngineResult": True},
        } for source in ops.REQUIRED_SOURCES]
        for count in range(5):
            rows = copy.deepcopy(base)
            for index, row in enumerate(rows):
                row["contributes_to_floor"] = index < count
            with self.subTest(count=count):
                self.assertFalse(ops.converge_rows(rows)["satisfied"])

    def test_five_proven_source_results_can_reach_the_mechanical_floor(self) -> None:
        rows = [{
            "source": source, "evidenceIds": [source + "-1"],
            "contributes_to_floor": True, "conflictState": "NONE",
            "provenance": {"ownerEngineResult": True},
        } for source in ops.REQUIRED_SOURCES]
        self.assertTrue(ops.converge_rows(rows)["satisfied"])

    def test_internal_all_pass_json_without_evidence_is_refused(self) -> None:
        rows = [{"source": source, "evidenceIds": [],
                 "contributes_to_floor": True, "conflictState": "NONE",
                 "provenance": {}} for source in ops.REQUIRED_SOURCES]
        result = ops.converge_rows(rows)
        self.assertFalse(result["satisfied"])
        self.assertEqual(set(result["unproven"]), set(ops.REQUIRED_SOURCES))

    def test_same_cut_inputs_reproduce_byte_identically(self) -> None:
        first = ops.build_floor_cut("CUT-017", "e906a48793d7", "2026-08-20")
        second = ops.build_floor_cut("CUT-017", "e906a48793d7", "2026-08-20")
        self.assertEqual(ops._canonical(first), ops._canonical(second))

    def test_cut_tampering_breaks_the_seal(self) -> None:
        cut = ops.build_floor_cut("CUT-017", "e906a48793d7", "2026-08-20")
        cut["candidateDecision"] = "AUTHORIZED"
        self.assertIn("cut seal mismatch", ops.verify_floor_cut(cut))

    def test_cut_ids_are_explicit_and_exact(self) -> None:
        for invalid in ("latest", "CUT-17", "CUT-017-extra"):
            with self.subTest(value=invalid):
                with self.assertRaises(ops.BoundaryViolation):
                    ops.build_floor_cut(invalid, "e906a48793d7", "2026-08-20")

    def test_post_cut_evidence_is_named_for_every_source(self) -> None:
        cut = ops.build_floor_cut("CUT-017", "e906a48793d7", "2026-08-20")
        original_path = ops.PHASE9_LEDGER
        for index, source in enumerate(ops.REQUIRED_SOURCES, 1):
            base = Path(tempfile.mkdtemp(prefix="phase17-postcut-test-"))
            self.addCleanup(shutil.rmtree, base, ignore_errors=True)
            ledger = ops.load_json(original_path)
            ledger["entries"].append({"intakeId": "INTAKE-%03d" % index,
                                      "source": source})
            path = base / "LEDGER.json"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            with self.subTest(source=source), mock.patch.object(ops, "PHASE9_LEDGER", path):
                assembled = ops.assemble_cut(cut, "e906a48793d7")
                self.assertEqual(assembled["postCutEvidenceIds"],
                                 ["INTAKE-%03d" % index])
                self.assertFalse(assembled["historicalDecisionRewritten"])

    def test_time_validation_refuses_prefix_impossible_and_unzoned_values(self) -> None:
        for invalid in ("2026-08-20suffix", "2026-02-30",
                        "2026-08-20T12:00:00"):
            with self.subTest(value=invalid):
                with self.assertRaises(ops.BoundaryViolation):
                    ops._instant(invalid)

    def test_generated_floor_and_dashboard_rederive(self) -> None:
        self.assertEqual(ops.status_problems(), [])

    def test_matrix_and_recovery_views_rederive(self) -> None:
        self.assertEqual(ops.matrix_problems(), [])
        matrix = ops.load_json(ops.MATRIX_PATH)
        recovery = ops.load_json(ops.RECOVERY_PATH)
        self.assertEqual(len(recovery["rows"]), matrix["scenarioCount"])

    def test_phase17_verifier_executes_clean(self) -> None:
        result = subprocess.run([sys.executable, str(_VERIFY)], cwd=_ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("phase 17 verifies clean", result.stdout)

    def test_both_phase17_modules_are_in_release_discovery(self) -> None:
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
        self.assertIn("tests.release.test_phase17_external_floor", names)
        self.assertIn("tests.release.test_phase17_matrix", names)
        self.assertGreaterEqual(suite.countTestCases(), 830)


if __name__ == "__main__":
    unittest.main()

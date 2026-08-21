# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Phase 10 boundaries, each with its failure branch executed.

The artifact graph records relationships explicitly; the impact mapping
mirrors the build COPY roots and fails closed on anything unmapped; the
planner cannot say PASS; the candidate state machine cannot walk
REMEDIATION_REQUIRED into AUTHORIZED; the finding lifecycle cannot close a
finding because code changed; a harness correction without its history is
refused. Every one of those "cannot"s is exercised here as a real refusal,
not assumed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "qualification" / "phase10" / "tools" / "candidate_ops.py"
_GRAPH = _ROOT / "qualification" / "phase10" / "artifacts" / "artifact-graph.json"
_MAPPING = _ROOT / "qualification" / "phase10" / "impact" / "component-domains.json"
_CORRECTIONS = _ROOT / "qualification" / "phase10" / "harness-corrections.json"
_CONTAINERFILE = _ROOT / "build" / "Containerfile"

_IMAGE = "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d"


def _load_tool():
    spec = importlib.util.spec_from_file_location("phase10_ops_model", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops = _load_tool()


def _control_next(graph: dict, relationship: str = "REMEDIATES") -> dict:
    """A modelled CANDIDATE-NEXT in a constructed graph — modelled only;
    nothing here claims such an artifact exists."""
    graph = json.loads(json.dumps(graph))
    graph["artifacts"].append({
        "artifact_id": "fixture-candidate-next",
        "digest": "sha256:" + "ab" * 32,
        "digests": {"image": "sha256:" + "ab" * 32},
        "source_commit": "0" * 40,
        "build_identity": "constructed control",
        "parent_artifact": "e906a48793d7",
        "supersedes": None,
        "relationship": relationship,
        "qualification_state": "REQUALIFICATION_REQUIRED",
    })
    graph["artifacts"][0] = dict(graph["artifacts"][0],
                                 qualification_state="REMEDIATION_REQUIRED")
    return graph


class GraphStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = json.loads(_GRAPH.read_text(encoding="utf-8"))

    def test_the_committed_graph_is_valid(self) -> None:
        self.assertEqual(ops.validate_graph(self.graph), [])

    def test_the_root_is_the_frozen_candidate_and_nothing_else_exists(self) -> None:
        (artifact,) = self.graph["artifacts"]
        self.assertEqual(artifact["artifact_id"], "e906a48793d7")
        self.assertEqual(artifact["relationship"], "ROOT")
        self.assertIsNone(artifact["parent_artifact"])
        self.assertIsNone(artifact["supersedes"])
        self.assertEqual(artifact["digest"], _IMAGE)
        self.assertEqual(artifact["qualification_state"], "EVIDENCE_PENDING")
        self.assertEqual(self.graph["transferDecisions"], [])

    def test_two_roots_are_refused(self) -> None:
        broken = json.loads(json.dumps(self.graph))
        broken["artifacts"].append(dict(broken["artifacts"][0],
                                        artifact_id="second-root"))
        issues = ops.validate_graph(broken)
        self.assertTrue(any("exactly one ROOT" in i for i in issues))

    def test_a_parentless_non_root_is_refused(self) -> None:
        broken = _control_next(self.graph)
        broken["artifacts"][1]["parent_artifact"] = None
        issues = ops.validate_graph(broken)
        self.assertTrue(any("never inferred from commit history" in i
                            for i in issues))

    def test_an_unknown_relationship_is_refused(self) -> None:
        broken = _control_next(self.graph)
        broken["artifacts"][1]["relationship"] = "LOOKS_SIMILAR"
        issues = ops.validate_graph(broken)
        self.assertTrue(any("LOOKS_SIMILAR" in i for i in issues))

    def test_an_orphan_parent_is_refused(self) -> None:
        broken = _control_next(self.graph)
        broken["artifacts"][1]["parent_artifact"] = "never-recorded"
        issues = ops.validate_graph(broken)
        self.assertTrue(any("never-recorded" in i for i in issues))

    def test_a_transfer_decision_without_reasoning_is_refused(self) -> None:
        broken = _control_next(self.graph)
        broken["transferDecisions"] = [{
            "fromArtifact": "e906a48793d7", "toArtifact": "fixture-candidate-next",
            "evidenceScope": "security-review", "result": "PARTIALLY_APPLIES",
            "reasoning": "", "decidedBy": "control", "date": "2026-08-18",
        }]
        issues = ops.validate_graph(broken)
        self.assertTrue(any("transfer decision missing reasoning" in i
                            for i in issues))

    def test_a_modelled_candidate_next_validates_as_a_model(self) -> None:
        self.assertEqual(ops.validate_graph(_control_next(self.graph)), [])


class CandidateStateMachine(unittest.TestCase):
    def test_the_state_vocabulary_is_the_ten(self) -> None:
        self.assertEqual(ops.CANDIDATE_STATES, (
            "FROZEN", "EVIDENCE_PENDING", "UNDER_REVIEW",
            "REMEDIATION_REQUIRED", "REQUALIFICATION_REQUIRED", "ALPHA_READY",
            "AUTHORIZED", "BLOCKED", "SUPERSEDED", "RETIRED",
        ))

    def test_the_declared_forward_path_is_allowed(self) -> None:
        self.assertEqual(
            ops.candidate_transition("FROZEN", "EVIDENCE_PENDING"),
            "EVIDENCE_PENDING")
        self.assertEqual(
            ops.candidate_transition("EVIDENCE_PENDING", "UNDER_REVIEW"),
            "UNDER_REVIEW")
        for target in ("ALPHA_READY", "REMEDIATION_REQUIRED", "BLOCKED"):
            self.assertEqual(
                ops.candidate_transition("UNDER_REVIEW", target), target)

    def test_remediation_required_cannot_reach_authorized_directly(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.candidate_transition("REMEDIATION_REQUIRED", "AUTHORIZED")
        self.assertIn("not allowed", str(caught.exception))

    def test_every_undeclared_transition_is_refused(self) -> None:
        for current in ops.CANDIDATE_STATES:
            for target in ops.CANDIDATE_STATES:
                if target in ops.CANDIDATE_TRANSITIONS[current]:
                    continue
                with self.assertRaises(ops.BoundaryViolation,
                                       msg="%s -> %s" % (current, target)):
                    ops.candidate_transition(current, target)

    def test_authorized_requires_context(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.candidate_transition("ALPHA_READY", "AUTHORIZED")
        self.assertIn("authorizing itself", str(caught.exception))

    def test_authorized_requires_an_authorized_decision(self) -> None:
        ledger = {"entries": []}
        decision = {"final_decision": "MORE_EVIDENCE_REQUIRED"}
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.candidate_transition("ALPHA_READY", "AUTHORIZED",
                                     {"decision": decision, "ledger": ledger})
        self.assertIn("MORE_EVIDENCE_REQUIRED", str(caught.exception))

    def test_authorized_requires_the_phase9_floor(self) -> None:
        decision = {"final_decision": "AUTHORIZED",
                    "decision_authority": "constructed control authority"}
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.candidate_transition("ALPHA_READY", "AUTHORIZED",
                                     {"decision": decision,
                                      "ledger": {"entries": []}})
        self.assertIn("authorization floor", str(caught.exception))

    def test_authorized_with_real_floor_evidence_is_allowed(self) -> None:
        """The pass branch: with gate-eligible ACCEPTED intake in the three
        floor sources, the transition succeeds — authority stays human."""
        entries = [
            {"intakeId": "INTAKE-%03d" % i, "revises": None, "source": source,
             "status": "ACCEPTED", "gateEligible": True}
            for i, source in enumerate(
                ("security-review", "signing", "second-approval"), 1)
        ]
        decision = {"final_decision": "AUTHORIZED",
                    "decision_authority": "constructed control authority"}
        self.assertEqual(
            ops.candidate_transition("ALPHA_READY", "AUTHORIZED",
                                     {"decision": decision,
                                      "ledger": {"entries": entries}}),
            "AUTHORIZED")


class FindingLifecycle(unittest.TestCase):
    def _finding(self, state: str) -> dict:
        return {"findingId": "SEC-EXT-001", "state": state,
                "artifact": "e906a48793d7"}

    def test_the_full_lifecycle_closes_on_bound_evidence(self) -> None:
        finding = self._finding("RECEIVED")
        path = ("VALIDATED", "TRIAGED", "REPRODUCTION_PENDING", "CONFIRMED",
                "FIX_REQUIRED", "FIXED")
        for target in path:
            finding["state"] = ops.finding_transition(finding, target)
        finding["state"] = ops.finding_transition(
            finding, "REQUALIFIED",
            {"requalificationEvidence": {
                "reference": "qualification/constructed/control",
                "artifact": "e906a48793d7"}},
        )
        self.assertEqual(ops.finding_transition(finding, "CLOSED"), "CLOSED")

    def test_a_code_change_closes_nothing(self) -> None:
        for premature in ("FIX_REQUIRED", "FIXED"):
            with self.assertRaises(ops.BoundaryViolation,
                                   msg="%s -> CLOSED" % premature):
                ops.finding_transition(self._finding(premature), "CLOSED")

    def test_requalification_requires_evidence(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.finding_transition(self._finding("FIXED"), "REQUALIFIED")
        self.assertIn("code change is not requalification",
                      str(caught.exception))

    def test_requalification_evidence_binds_to_the_findings_artifact(self) -> None:
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.finding_transition(
                self._finding("FIXED"), "REQUALIFIED",
                {"requalificationEvidence": {
                    "reference": "control", "artifact": "fixture-candidate-next"}},
            )
        self.assertIn("actually tested", str(caught.exception))

    def test_closing_an_accepted_risk_needs_the_full_record(self) -> None:
        acceptance = {"risk": "control", "owner": "control",
                      "affectedArtifact": "e906a48793d7",
                      "rationale": "control", "reviewBy": "2026-09-18"}
        incomplete = dict(acceptance, reviewBy="")
        with self.assertRaises(ops.BoundaryViolation) as caught:
            ops.finding_transition(self._finding("ACCEPTED_RISK"), "CLOSED",
                                   {"acceptance": incomplete})
        self.assertIn("no silent acceptance", str(caught.exception))
        self.assertEqual(
            ops.finding_transition(self._finding("ACCEPTED_RISK"), "CLOSED",
                                   {"acceptance": acceptance}),
            "CLOSED")

    def test_not_reproduced_reopens_only_to_triage(self) -> None:
        self.assertEqual(
            ops.finding_transition(self._finding("NOT_REPRODUCED"), "TRIAGED"),
            "TRIAGED")
        with self.assertRaises(ops.BoundaryViolation):
            ops.finding_transition(self._finding("NOT_REPRODUCED"), "CLOSED")

    def test_skipping_states_is_refused(self) -> None:
        for current, target in (("RECEIVED", "CLOSED"), ("TRIAGED", "FIXED"),
                                ("RECEIVED", "CONFIRMED")):
            with self.assertRaises(ops.BoundaryViolation):
                ops.finding_transition(self._finding(current), target)


class ImpactAndPlanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(_MAPPING.read_text(encoding="utf-8"))

    def test_every_containerfile_copy_root_is_product_affecting(self) -> None:
        """The mapping's productAffecting mirrors what the build ships."""
        sources = []
        for line in _CONTAINERFILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("COPY "):
                parts = line.split()
                sources.extend(parts[1:-1])
        self.assertTrue(sources, "the Containerfile stopped copying anything?")
        for source in sources:
            probe = source if "." in source else source + "/probe"
            classified = ops.classify_components([probe], self.mapping)
            self.assertEqual(classified["unmapped"], [], source)
            self.assertTrue(
                classified["productAffecting"],
                "%s is a build COPY root but the mapping calls it "
                "non-product" % source)

    def test_every_mapping_prefix_exists_in_the_repository(self) -> None:
        for entry in self.mapping["components"]:
            path = _ROOT / entry["prefix"].rstrip("/")
            self.assertTrue(path.exists(),
                            "%s is mapped but does not exist" % entry["prefix"])

    def test_a_companion_change_affects_companion_not_installer(self) -> None:
        classified = ops.classify_components(
            ["companion/renderer_modes.py"], self.mapping)
        self.assertIn("COMPANION", classified["domains"])
        self.assertIn("PERFORMANCE", classified["domains"])
        self.assertIn("ACCESSIBILITY", classified["domains"])
        self.assertNotIn("INSTALLER", classified["domains"])
        self.assertNotIn("BOOT", classified["domains"])
        self.assertTrue(classified["productAffecting"])

    def test_a_root_report_is_a_record_not_product(self) -> None:
        classified = ops.classify_components(
            ["PHASE9_EXTERNAL_EVIDENCE_INTAKE_AND_ALPHA_RELEASE_DECISION.md"],
            self.mapping)
        self.assertEqual(classified["domains"], ["DOCUMENTATION"])
        self.assertFalse(classified["productAffecting"])

    def test_docs_are_product_in_this_repository(self) -> None:
        """docs/ is a build COPY root; the mapping must say so."""
        classified = ops.classify_components(["docs/UPDATES.md"], self.mapping)
        self.assertTrue(classified["productAffecting"])

    def test_the_planner_plans_a_voice_change(self) -> None:
        impact = ops.build_impact(
            "e906a48793d7", "fixture-candidate-next",
            ["companion/voice_runtime.py"], self.mapping)
        plan = ops.plan_requalification(impact)
        self.assertEqual(ops.validate_plan(plan), [])
        self.assertEqual(plan["VOICE"]["status"], "REQUIRED")
        self.assertEqual(plan["SECURITY"]["status"], "REQUIRED")
        self.assertEqual(plan["RELEASE"]["status"], "REQUIRED")
        self.assertEqual(plan["HARDWARE"]["status"], "REQUIRES_HUMAN_REVIEW")
        self.assertEqual(plan["INSTALLER"]["status"], "NOT_REQUIRED")
        self.assertEqual(plan["BOOT"]["status"], "NOT_REQUIRED")
        for row in plan.values():
            self.assertTrue(row["reason"])

    def test_the_planner_never_outputs_pass(self) -> None:
        smuggled = {"SECURITY": {"status": "PASS", "reason": "wishful"}}
        issues = ops.validate_plan(smuggled)
        self.assertTrue(any("never grades" in i for i in issues))
        self.assertNotIn("PASS", ops.PLAN_STATUSES)

    def test_an_unmapped_component_fails_closed(self) -> None:
        impact = ops.build_impact(
            "e906a48793d7", "fixture-candidate-next",
            ["totally-new-tree/module.py"], self.mapping)
        self.assertEqual(impact["unmappedComponents"], ["totally-new-tree/module.py"])
        plan = ops.plan_requalification(impact)
        self.assertEqual(ops.validate_plan(plan), [])
        for domain, row in plan.items():
            self.assertNotEqual(
                row["status"], "NOT_REQUIRED",
                "%s relaxed while an unmapped component exists" % domain)

    def test_harness_only_changes_plan_no_requalification(self) -> None:
        impact = ops.build_impact(
            "e906a48793d7", "e906a48793d7",
            ["tests/release/test_phase10_model.py"], self.mapping)
        self.assertFalse(impact["productAffecting"])
        plan = ops.plan_requalification(impact)
        for domain, row in plan.items():
            self.assertEqual(row["status"], "NOT_REQUIRED", domain)


class RemediationBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(_MAPPING.read_text(encoding="utf-8"))

    def test_product_change_without_new_identity_fails(self) -> None:
        violations = ops.validate_remediation(
            {"changedComponents": ["companion/approvals.py"],
             "artifactBefore": "e906a48793d7",
             "artifactAfter": "e906a48793d7"},
            self.mapping)
        self.assertTrue(any("requires a new artifact" in v for v in violations))

    def test_product_change_with_new_identity_passes(self) -> None:
        self.assertEqual(
            ops.validate_remediation(
                {"changedComponents": ["companion/approvals.py"],
                 "artifactBefore": "e906a48793d7",
                 "artifactAfter": "fixture-candidate-next"},
                self.mapping),
            [])

    def test_a_harness_change_needs_no_new_artifact(self) -> None:
        self.assertEqual(
            ops.validate_remediation(
                {"changedComponents": ["tests/release/test_phase9_intake.py"],
                 "artifactBefore": "e906a48793d7",
                 "artifactAfter": "e906a48793d7"},
                self.mapping),
            [])

    def test_a_rebuild_without_cause_is_flagged(self) -> None:
        violations = ops.validate_remediation(
            {"changedComponents": ["tests/release/test_phase9_intake.py"],
             "artifactBefore": "e906a48793d7",
             "artifactAfter": "fixture-candidate-next"},
            self.mapping)
        self.assertTrue(any("needs a cause" in v for v in violations))

    def test_a_docs_change_is_a_product_change_here(self) -> None:
        violations = ops.validate_remediation(
            {"changedComponents": ["docs/RECOVERY.md"],
             "artifactBefore": "e906a48793d7",
             "artifactAfter": "e906a48793d7"},
            self.mapping)
        self.assertTrue(violations, "docs/ ships in the image; editing it "
                                    "without a new artifact must fail")


class HarnessCorrections(unittest.TestCase):
    def _correction(self, **overrides) -> dict:
        record = {
            "classification": "PRIOR_FALSE_PASS_FOUND",
            "originalVerdict": {"verdict": "PASS",
                                "evidence": "qualification/constructed/control"},
            "correctedVerdict": "FAIL",
            "reason": "constructed control: the checker had no true-positive branch",
            "harnessChange": "constructed control: the checker now fails on the case",
        }
        record.update(overrides)
        return record

    def test_a_valid_correction_carries_its_history(self) -> None:
        self.assertEqual(ops.validate_harness_correction(self._correction()), [])

    def test_a_correction_without_the_original_is_refused(self) -> None:
        issues = ops.validate_harness_correction(
            self._correction(originalVerdict=None))
        self.assertTrue(any("preserved verbatim" in i for i in issues))

    def test_a_false_pass_with_unchanged_verdict_contradicts_itself(self) -> None:
        issues = ops.validate_harness_correction(
            self._correction(correctedVerdict="PASS"))
        self.assertTrue(any("contradicts itself" in i for i in issues))

    def test_the_classification_vocabulary_matches_the_registry(self) -> None:
        registry = json.loads(_CORRECTIONS.read_text(encoding="utf-8"))
        self.assertEqual(tuple(registry["classificationVocabulary"]),
                         ops.HARNESS_CLASSIFICATIONS)
        self.assertEqual(registry["corrections"], [])


if __name__ == "__main__":
    unittest.main()

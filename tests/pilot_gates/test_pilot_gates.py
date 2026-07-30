"""Gate separation: stable release, and the three pilots.

Three of the fourteen mandated adversarial cases live here: pilot approval
without a stable release, OEM approval without hardware, and sync approval
without a cryptographic review.

The load-bearing property is that a passing *source* gate contributes nothing to
a pilot gate. Phase 7 source is complete and fully tested; that was never
evidence that a device may be manufactured.

Directory naming note: the brief names this suite ``tests/pilot-gates/``. A
hyphen cannot be imported as a Python package, so the underscore spelling is
used to keep the tests running.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from release.gates import (
    ENTERPRISE_PILOT_REQUIREMENTS,
    GATES,
    OEM_PILOT_REQUIREMENTS,
    PILOT_REQUIREMENTS,
    REQUIRED_APPROVALS,
    SYNC_PILOT_REQUIREMENTS,
    GateError,
    StableInputs,
    assert_no_unprotected_go,
    evaluate_pilot_gate,
    evaluate_stable_gate,
)

ROOT = Path(__file__).resolve().parents[2]


def stable_inputs(**overrides) -> StableInputs:
    base = dict(
        evidenceComplete=True,
        evidenceDetail={},
        approvals={owner: "APPROVED" for owner in REQUIRED_APPROVALS},
        blockers=(),
        vulnerabilityBlocked=False,
        vulnerabilityDetail={},
        licenceGatePassed=True,
        licenceDetail={},
        reproducibilityIndependent=True,
        signingProductionReady=True,
        candidateComplete=True,
        minimisationComplete=True,
        hardwareQualified=True,
        reviewsComplete=True,
        matricesComplete=True,
    )
    base.update(overrides)
    return StableInputs(**base)


class GateStructureTests(unittest.TestCase):
    def test_six_separate_gates_exist(self):
        # Was four. `source` and `qualification-candidate` were split out so a
        # passing repository and a buildable candidate stop being mistaken for
        # release readiness; neither contributes to any other gate.
        self.assertEqual(
            set(GATES),
            {
                "source",
                "qualification-candidate",
                "stable-release",
                "oem-pilot",
                "enterprise-pilot",
                "sync-pilot",
            },
        )

    def test_each_pilot_declares_its_own_additional_requirements(self):
        self.assertEqual(set(PILOT_REQUIREMENTS), {"oem-pilot", "enterprise-pilot", "sync-pilot"})
        self.assertEqual(len(OEM_PILOT_REQUIREMENTS), 6)
        self.assertEqual(len(ENTERPRISE_PILOT_REQUIREMENTS), 6)
        self.assertEqual(len(SYNC_PILOT_REQUIREMENTS), 7)

    def test_pilot_requirement_sets_are_not_identical(self):
        self.assertNotEqual(set(OEM_PILOT_REQUIREMENTS), set(ENTERPRISE_PILOT_REQUIREMENTS))
        self.assertNotEqual(set(ENTERPRISE_PILOT_REQUIREMENTS), set(SYNC_PILOT_REQUIREMENTS))

    def test_unknown_pilot_gate_is_refused(self):
        with self.assertRaises(GateError):
            evaluate_pilot_gate("marketing-pilot", stable=evaluate_stable_gate(stable_inputs()), requirements={})

    def test_undeclared_requirement_is_refused(self):
        stable = evaluate_stable_gate(stable_inputs())
        with self.assertRaises(GateError) as caught:
            evaluate_pilot_gate("oem-pilot", stable=stable, requirements={"vibesConfirmed": True})
        self.assertIn("unknown requirements", str(caught.exception))


class StableGateTests(unittest.TestCase):
    def test_everything_satisfied_reaches_go(self):
        result = evaluate_stable_gate(stable_inputs())
        self.assertEqual(result.recommendation, "GO")

    def test_each_condition_alone_blocks(self):
        conditions = {
            "evidenceComplete": False,
            "vulnerabilityBlocked": True,
            "licenceGatePassed": False,
            "reproducibilityIndependent": False,
            "signingProductionReady": False,
            "candidateComplete": False,
            "minimisationComplete": False,
            "hardwareQualified": False,
            "reviewsComplete": False,
            "matricesComplete": False,
        }
        for name, value in conditions.items():
            result = evaluate_stable_gate(stable_inputs(**{name: value}))
            self.assertEqual(result.recommendation, "NO-GO", f"{name} alone must block")

    def test_one_pending_approval_blocks(self):
        approvals = {owner: "APPROVED" for owner in REQUIRED_APPROVALS}
        approvals["Security"] = "PENDING"
        result = evaluate_stable_gate(stable_inputs(approvals=approvals))
        self.assertEqual(result.recommendation, "NO-GO")
        self.assertTrue(any("Security" in item for item in result.unmet))

    def test_one_open_blocker_code_blocks(self):
        result = evaluate_stable_gate(stable_inputs(blockers=("unsigned-artifact",)))
        self.assertEqual(result.recommendation, "NO-GO")

    def test_development_signing_does_not_satisfy_the_gate(self):
        result = evaluate_stable_gate(stable_inputs(signingProductionReady=False))
        self.assertTrue(
            any("development keys cannot satisfy" in item for item in result.unmet)
        )


class PilotGateTests(unittest.TestCase):
    """The three mandated adversarial pilot cases."""

    def _all_pilot_requirements(self, gate):
        return {name: True for name in PILOT_REQUIREMENTS[gate]}

    # --- adversarial: pilot approval without a stable release ---
    def test_no_pilot_passes_while_the_stable_gate_is_no_go(self):
        stable = evaluate_stable_gate(stable_inputs(hardwareQualified=False))
        self.assertEqual(stable.recommendation, "NO-GO")
        for gate in PILOT_REQUIREMENTS:
            result = evaluate_pilot_gate(
                gate, stable=stable, requirements=self._all_pilot_requirements(gate)
            )
            self.assertEqual(result.recommendation, "BLOCKED", f"{gate} must block")
            self.assertTrue(
                any("no pilot may begin without a published, signed stable release" in item for item in result.unmet)
            )

    def test_pilot_passes_only_when_stable_passes_and_its_own_requirements_do(self):
        stable = evaluate_stable_gate(stable_inputs())
        for gate in PILOT_REQUIREMENTS:
            result = evaluate_pilot_gate(
                gate, stable=stable, requirements=self._all_pilot_requirements(gate)
            )
            self.assertEqual(result.recommendation, "GO", f"{gate}: {result.unmet}")

    # --- adversarial: OEM approval without hardware ---
    def test_oem_pilot_blocks_without_a_qualified_hardware_model(self):
        stable = evaluate_stable_gate(stable_inputs())
        requirements = self._all_pilot_requirements("oem-pilot")
        requirements["qualifiedHardwareModel"] = False
        result = evaluate_pilot_gate("oem-pilot", stable=stable, requirements=requirements)
        self.assertEqual(result.recommendation, "BLOCKED")
        self.assertTrue(any("qualifiedHardwareModel" in item for item in result.unmet))

    def test_oem_pilot_blocks_without_factory_finalisation_on_hardware(self):
        stable = evaluate_stable_gate(stable_inputs())
        requirements = self._all_pilot_requirements("oem-pilot")
        requirements["factoryFinalisationOnHardware"] = False
        result = evaluate_pilot_gate("oem-pilot", stable=stable, requirements=requirements)
        self.assertEqual(result.recommendation, "BLOCKED")

    # --- adversarial: sync approval without a cryptographic review ---
    def test_sync_pilot_blocks_without_an_independent_cryptographic_review(self):
        stable = evaluate_stable_gate(stable_inputs())
        requirements = self._all_pilot_requirements("sync-pilot")
        requirements["independentCryptographicReview"] = False
        result = evaluate_pilot_gate("sync-pilot", stable=stable, requirements=requirements)
        self.assertEqual(result.recommendation, "BLOCKED")
        self.assertTrue(any("independentCryptographicReview" in item for item in result.unmet))

    def test_enterprise_pilot_blocks_without_a_tenant_isolation_penetration_test(self):
        stable = evaluate_stable_gate(stable_inputs())
        requirements = self._all_pilot_requirements("enterprise-pilot")
        requirements["tenantIsolationPenetrationTest"] = False
        result = evaluate_pilot_gate("enterprise-pilot", stable=stable, requirements=requirements)
        self.assertEqual(result.recommendation, "BLOCKED")

    def test_a_missing_requirement_key_counts_as_unmet(self):
        stable = evaluate_stable_gate(stable_inputs())
        result = evaluate_pilot_gate("oem-pilot", stable=stable, requirements={})
        self.assertEqual(result.recommendation, "BLOCKED")
        self.assertEqual(len(result.unmet), len(OEM_PILOT_REQUIREMENTS))

    def test_truthy_non_true_value_does_not_satisfy_a_requirement(self):
        stable = evaluate_stable_gate(stable_inputs())
        requirements = self._all_pilot_requirements("oem-pilot")
        requirements["namedSupportOwner"] = "probably someone"
        result = evaluate_pilot_gate("oem-pilot", stable=stable, requirements=requirements)
        self.assertEqual(result.recommendation, "BLOCKED")


class CiAssertionTests(unittest.TestCase):
    def test_go_without_protected_evidence_is_a_ci_failure(self):
        stable = evaluate_stable_gate(stable_inputs())
        self.assertTrue(stable.passed)
        with self.assertRaises(GateError) as caught:
            assert_no_unprotected_go([stable], protectedEvidencePresent=False)
        self.assertIn("no protected evidence", str(caught.exception))

    def test_go_with_protected_evidence_is_allowed(self):
        stable = evaluate_stable_gate(stable_inputs())
        assert_no_unprotected_go([stable], protectedEvidencePresent=True)

    def test_blocked_gates_never_trip_the_assertion(self):
        stable = evaluate_stable_gate(stable_inputs(hardwareQualified=False))
        assert_no_unprotected_go([stable], protectedEvidencePresent=False)


class RepositoryStateTests(unittest.TestCase):
    """The recorded state must keep every pilot blocked."""

    def setUp(self):
        self.requirements = json.loads(
            (ROOT / "operations/data/pilot-requirements.json").read_text(encoding="utf-8")
        )

    def test_no_pilot_requirement_is_currently_satisfied(self):
        for gate in PILOT_REQUIREMENTS:
            declared = self.requirements[gate]["requirements"]
            self.assertEqual(set(declared), set(PILOT_REQUIREMENTS[gate]))
            satisfied = [name for name, value in declared.items() if value is True]
            self.assertEqual(
                satisfied,
                [],
                f"{gate} claims {satisfied}; update the pilot readiness reports if this is real",
            )

    def test_every_unmet_requirement_carries_a_note(self):
        for gate in PILOT_REQUIREMENTS:
            entry = self.requirements[gate]
            for name, value in entry["requirements"].items():
                if value is not True:
                    self.assertIn(name, entry["notes"], f"{gate}/{name} has no note explaining why")
                    self.assertTrue(entry["notes"][name].strip())


if __name__ == "__main__":
    unittest.main()

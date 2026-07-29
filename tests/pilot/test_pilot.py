from __future__ import annotations

import json
from pathlib import Path
import unittest

from enterprise.pilot import (
    MAXIMUM_DEVICES,
    PERMITTED_MEASURES,
    PILOT_ENTRY_GATES,
    PILOT_ORDER,
    PROHIBITED_MEASURES,
    PilotError,
    assert_pilot_order,
    describe_pilots,
    evaluate_pilot,
)

ROOT = Path(__file__).resolve().parents[2]


def definition(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "pilot": "internal-pilot",
        "scope": "Internal engineering laptops only",
        "durationDays": 30,
        "deviceCount": 10,
        "supportedHardware": ["reference-x86-64-uefi"],
        "supportOwner": "Bunny OS maintainers",
        "successCriteria": ["enrolmentSuccessRate", "updateSuccessRate", "rollbackSuccessRate"],
        "privacyNotice": "docs/FLEET_PRIVACY.md",
        "incidentProcess": "SECURITY_POLICY.md",
        "rollbackPlan": "Unenrol and restore the previous deployment.",
        "exitPlan": "Unenrol every device and delete the organisation record.",
    }
    value.update(overrides)
    return value


def gates(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {name: True for name in PILOT_ENTRY_GATES}
    value.update(overrides)
    return value


class PilotOrderTests(unittest.TestCase):
    def test_internal_pilot_needs_no_predecessor(self) -> None:
        assert_pilot_order("internal-pilot", [])

    def test_larger_pilot_cannot_skip_smaller_ones(self) -> None:
        with self.assertRaises(PilotError) as error:
            assert_pilot_order("small-business-pilot", [])
        self.assertIn("smaller pilots complete", str(error.exception))

    def test_ordered_progression_is_permitted(self) -> None:
        completed: list[str] = []
        for pilot in PILOT_ORDER:
            assert_pilot_order(pilot, completed)
            completed.append(pilot)

    def test_unknown_pilot_is_refused(self) -> None:
        with self.assertRaises(PilotError):
            assert_pilot_order("global-rollout", [])

    def test_unknown_completed_pilot_is_refused(self) -> None:
        with self.assertRaises(PilotError):
            assert_pilot_order("small-community-pilot", ["mass-production"])

    def test_catalogue_lists_predecessors(self) -> None:
        rows = {row["pilot"]: row for row in describe_pilots()}
        self.assertEqual(rows["small-business-pilot"]["predecessors"][0], "internal-pilot")


class PilotReadinessTests(unittest.TestCase):
    def test_all_gates_passing_makes_a_pilot_ready(self) -> None:
        readiness = evaluate_pilot(definition(), gates())
        self.assertTrue(readiness.ready, readiness.as_dict())
        self.assertEqual(readiness.as_dict()["recommendation"], "GO")

    def test_every_gate_blocks_independently(self) -> None:
        for name in PILOT_ENTRY_GATES:
            with self.subTest(gate=name):
                readiness = evaluate_pilot(definition(), gates(**{name: False}))
                self.assertFalse(readiness.ready)
                self.assertIn(name, readiness.failedGates)

    def test_missing_gate_evidence_is_not_a_pass(self) -> None:
        value = gates()
        del value["stableReleasePublished"]
        readiness = evaluate_pilot(definition(), value)
        self.assertFalse(readiness.ready)
        self.assertIn("stableReleasePublished", readiness.missingGates)

    def test_missing_required_field_blocks_a_pilot(self) -> None:
        for field in ("scope", "supportOwner", "privacyNotice", "rollbackPlan", "exitPlan"):
            with self.subTest(field=field):
                value = definition()
                del value[field]
                readiness = evaluate_pilot(value, gates())
                self.assertFalse(readiness.ready)
                self.assertIn(field, readiness.missingFields)

    def test_device_count_ceiling_is_enforced(self) -> None:
        readiness = evaluate_pilot(definition(deviceCount=MAXIMUM_DEVICES["internal-pilot"] + 1), gates())
        self.assertFalse(readiness.ready)
        self.assertTrue(any("permits at most" in item for item in readiness.problems))

    def test_behavioural_success_criteria_are_refused(self) -> None:
        readiness = evaluate_pilot(definition(successCriteria=["userProductivity"]), gates())
        self.assertFalse(readiness.ready)
        self.assertTrue(any("research protocol" in item for item in readiness.problems))

    def test_every_prohibited_measure_is_refused(self) -> None:
        for measure in sorted(PROHIBITED_MEASURES):
            with self.subTest(measure=measure):
                readiness = evaluate_pilot(definition(successCriteria=[measure]), gates())
                self.assertFalse(readiness.ready)

    def test_permitted_measures_are_operational_only(self) -> None:
        readiness = evaluate_pilot(definition(successCriteria=list(PERMITTED_MEASURES)), gates())
        self.assertTrue(readiness.ready, readiness.as_dict())

    def test_unrecognised_measure_is_flagged(self) -> None:
        readiness = evaluate_pilot(definition(successCriteria=["vibes"]), gates())
        self.assertFalse(readiness.ready)

    def test_unknown_gate_name_is_refused(self) -> None:
        with self.assertRaises(PilotError):
            evaluate_pilot(definition(), gates(marketingReadiness=True))

    def test_pilot_entry_depends_on_a_published_stable_release(self) -> None:
        self.assertIn("stableReleasePublished", PILOT_ENTRY_GATES)
        self.assertIn("signedStableArtifacts", PILOT_ENTRY_GATES)


class RecordedReadinessTests(unittest.TestCase):
    def test_recorded_evidence_is_currently_no_go(self) -> None:
        path = ROOT / "operations/data/phase7-readiness.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        readiness = evaluate_pilot(
            {"pilot": "internal-pilot", **evidence["pilotDefinition"]},
            evidence["entryGates"],
        )
        self.assertFalse(
            readiness.ready,
            "Phase 7 pilot readiness must remain NO-GO while the stable release gate is unmet.",
        )

    def test_recorded_evidence_names_the_stable_release_blocker(self) -> None:
        path = ROOT / "operations/data/phase7-readiness.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(evidence["entryGates"]["stableReleasePublished"])
        self.assertIn("unsigned-artifact", evidence["inheritedBlockers"])


if __name__ == "__main__":
    unittest.main()

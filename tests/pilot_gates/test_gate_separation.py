# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Six separated gates, and the one relationship between them that is enforced.

The mandated adversarial case exercised here:

* a pilot gate invoked before a stable release (case 17)
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from release.gates import (
    GATES,
    PILOT_REQUIREMENTS,
    REQUIRED_APPROVALS,
    SOURCE_GATE_REQUIREMENTS,
    GateError,
    StableInputs,
    assert_no_unprotected_go,
    evaluate_candidate_gate,
    evaluate_pilot_gate,
    evaluate_source_gate,
    evaluate_stable_gate,
)

ROOT = Path(__file__).resolve().parents[2]


def stable_inputs(**overrides: object) -> StableInputs:
    values: dict[str, object] = {
        "evidenceComplete": True,
        "evidenceDetail": {},
        "approvals": {owner: "APPROVED" for owner in REQUIRED_APPROVALS},
        "blockers": (),
        "vulnerabilityBlocked": False,
        "vulnerabilityDetail": {},
        "licenceGatePassed": True,
        "licenceDetail": {},
        "reproducibilityIndependent": True,
        "signingProductionReady": True,
        "candidateComplete": True,
        "minimisationComplete": True,
        "hardwareQualified": True,
        "reviewsComplete": True,
        "matricesComplete": True,
    }
    values.update(overrides)
    return StableInputs(**values)  # type: ignore[arg-type]


class SixSeparatedGates(unittest.TestCase):
    def test_there_are_six(self) -> None:
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

    def test_a_passing_source_gate_does_not_make_a_pilot_passable(self) -> None:
        source = evaluate_source_gate({name: True for name in SOURCE_GATE_REQUIREMENTS})
        self.assertEqual(source.recommendation, "PASS")
        stable = evaluate_stable_gate(stable_inputs(vulnerabilityBlocked=True))
        self.assertEqual(stable.recommendation, "NO-GO")
        for kind, requirements in PILOT_REQUIREMENTS.items():
            result = evaluate_pilot_gate(
                kind, stable=stable, requirements={name: True for name in requirements}
            )
            self.assertEqual(result.recommendation, "BLOCKED", kind)

    def test_a_passing_candidate_gate_does_not_make_a_pilot_passable(self) -> None:
        candidate = evaluate_candidate_gate(prerequisitesReady=True, unsatisfied=(), detail={})
        self.assertEqual(candidate.recommendation, "PASS")
        stable = evaluate_stable_gate(stable_inputs(hardwareQualified=False))
        for kind, requirements in PILOT_REQUIREMENTS.items():
            result = evaluate_pilot_gate(
                kind, stable=stable, requirements={name: True for name in requirements}
            )
            self.assertEqual(result.recommendation, "BLOCKED", kind)


class PilotCannotBypassStable(unittest.TestCase):
    """Adversarial case 17."""

    def test_every_pilot_gate_blocks_while_the_stable_gate_blocks(self) -> None:
        stable = evaluate_stable_gate(stable_inputs(vulnerabilityBlocked=True))
        for kind, requirements in PILOT_REQUIREMENTS.items():
            result = evaluate_pilot_gate(
                kind, stable=stable, requirements={name: True for name in requirements}
            )
            self.assertFalse(result.passed, kind)
            self.assertTrue(
                any("no pilot may begin without a published, signed stable release" in item for item in result.unmet),
                f"{kind}: {result.unmet}",
            )

    def test_satisfying_every_pilot_requirement_is_not_enough(self) -> None:
        stable = evaluate_stable_gate(stable_inputs(reviewsComplete=False))
        result = evaluate_pilot_gate(
            "sync-pilot",
            stable=stable,
            requirements={name: True for name in PILOT_REQUIREMENTS["sync-pilot"]},
        )
        self.assertEqual(result.recommendation, "BLOCKED")
        self.assertEqual(len(result.unmet), 1)
        self.assertIn("stable-release", result.unmet[0])

    def test_a_pilot_passes_only_with_a_passing_stable_gate(self) -> None:
        stable = evaluate_stable_gate(stable_inputs())
        self.assertTrue(stable.passed)
        result = evaluate_pilot_gate(
            "oem-pilot",
            stable=stable,
            requirements={name: True for name in PILOT_REQUIREMENTS["oem-pilot"]},
        )
        self.assertEqual(result.recommendation, "GO")

    def test_an_unknown_pilot_requirement_is_rejected(self) -> None:
        stable = evaluate_stable_gate(stable_inputs())
        with self.assertRaises(GateError):
            evaluate_pilot_gate("oem-pilot", stable=stable, requirements={"vibes": True})

    def test_an_unknown_pilot_gate_is_rejected(self) -> None:
        stable = evaluate_stable_gate(stable_inputs())
        with self.assertRaises(GateError):
            evaluate_pilot_gate("consumer-pilot", stable=stable, requirements={})

    def test_a_go_without_protected_evidence_raises(self) -> None:
        stable = evaluate_stable_gate(stable_inputs())
        with self.assertRaises(GateError) as raised:
            assert_no_unprotected_go([stable], protectedEvidencePresent=False)
        self.assertIn("no protected evidence", str(raised.exception))

    def test_each_pilot_names_its_own_requirements(self) -> None:
        # Merged requirement lists hide which pilot fails for which reason.
        oem = set(PILOT_REQUIREMENTS["oem-pilot"])
        enterprise = set(PILOT_REQUIREMENTS["enterprise-pilot"])
        sync = set(PILOT_REQUIREMENTS["sync-pilot"])
        self.assertIn("qualifiedHardwareModel", oem)
        self.assertIn("tenantIsolationPenetrationTest", enterprise)
        self.assertIn("independentCryptographicReview", sync)
        self.assertNotIn("qualifiedHardwareModel", sync)


class CommittedGateState(unittest.TestCase):
    def _payload(self, name: str) -> dict[str, object] | None:
        path = ROOT / "build/out/qualification" / f"{name}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_stable_gate_reports_no_go(self) -> None:
        payload = self._payload("gate-stable-release")
        if payload is None:
            self.skipTest("run scripts/release.py gate --kind stable-release first")
        self.assertEqual(payload["recommendation"], "NO-GO")

    def test_the_candidate_gate_reports_blocked(self) -> None:
        payload = self._payload("gate-qualification-candidate")
        if payload is None:
            self.skipTest("run scripts/release.py gate --kind qualification-candidate first")
        self.assertEqual(payload["recommendation"], "BLOCKED")

    def test_every_pilot_gate_reports_blocked(self) -> None:
        for kind in PILOT_REQUIREMENTS:
            payload = self._payload(f"gate-{kind}")
            if payload is None:
                self.skipTest(f"run scripts/release.py gate --kind {kind} first")
            self.assertEqual(payload["recommendation"], "BLOCKED", kind)

    def test_no_pilot_requirement_is_recorded_as_satisfied(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/pilot-requirements.json").read_text(encoding="utf-8")
        )
        for kind, block in document.items():
            if not isinstance(block, dict):
                continue
            satisfied = [
                name for name, value in (block.get("requirements") or {}).items() if value is True
            ]
            self.assertEqual(satisfied, [], f"{kind} claims {satisfied}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

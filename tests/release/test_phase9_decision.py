# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Alpha release decision record, and why it cannot say AUTHORIZED.

``qualification/phase9/decision/alpha-release-decision.json`` represents
authorization separately from qualification (§17): it carries the required
fields, the ten pre-committed blocking conditions, and one of four final
decisions. The repository cannot authorize itself — an AUTHORIZED decision
requires gate-eligible ACCEPTED intake from the owners whose absence is the
current state — and that floor is enforced mechanically here, with its
failure branch executed against a constructed decision on every run.

The live assertions are written against the ledger, not against today: when
real evidence arrives and a human moves a status, the assertions follow the
evidence instead of failing the mechanism for being used.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_DECISION = _ROOT / "qualification" / "phase9" / "decision" / "alpha-release-decision.json"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"
_FINDINGS = _ROOT / "qualification" / "phase9" / "triage" / "findings.json"
_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"

_REQUIRED_FIELDS = (
    "artifact", "digest", "engineering_status", "security_status",
    "hardware_status", "signing_status", "approval_status",
    "alpha_validation_status", "blocking_conditions", "final_decision",
    "decision_authority", "timestamp",
)

_FINAL_DECISIONS = (
    "AUTHORIZED", "AUTHORIZED_WITH_LIMITATIONS", "BLOCKED",
    "MORE_EVIDENCE_REQUIRED",
)

#: The §18 matrix vocabulary; gate statuses in the decision use it too.
_GATE_STATUSES = (
    "PASS", "FAIL", "NOT_RUN", "NOT_SUPPORTED", "ACCEPTED_RISK",
    "MORE_EVIDENCE_REQUIRED",
)

#: The ten conditions, fixed at 17a34aa6 before any external evidence.
#: Hard-coded so the decision record cannot drop or reword one silently.
_CONDITION_TITLES = {
    1: "Security review returns BLOCKED (or no completed review exists)",
    2: "A Critical issue lacks an accepted disposition",
    3: "A confirmed data-loss defect exists",
    4: "A confirmed privacy breach exists",
    5: "A confirmed release-blocking accessibility defect exists",
    6: "The artifact identity cannot be verified",
    7: "Required signing policy is unmet",
    8: "Required second approval is absent",
    9: "A hardware failure affects the declared supported hardware set",
    10: "Alpha testing finds an unresolved release blocker",
}

#: decision gate field → the intake source whose ACCEPTED, gate-eligible
#: evidence is the only thing that may move it off NOT_RUN.
_GATE_SOURCES = {
    "security_status": "security-review",
    "hardware_status": "hardware",
    "signing_status": "signing",
    "approval_status": "second-approval",
    "alpha_validation_status": "alpha-feedback",
}


def _load_tool():
    spec = importlib.util.spec_from_file_location("phase9_intake_decision", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = _load_tool()


class AlphaReleaseDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.decision = json.loads(_DECISION.read_text(encoding="utf-8"))
        cls.ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))

    def test_the_required_fields_are_present(self) -> None:
        for field in _REQUIRED_FIELDS:
            self.assertIn(field, self.decision)
            self.assertNotIn(self.decision[field], (None, "", []), field)

    def test_the_decision_binds_to_the_subject_artifact(self) -> None:
        self.assertEqual(self.decision["artifact"], "e906a48793d7")
        self.assertEqual(
            self.decision["digest"],
            "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d",
        )

    def test_the_final_decision_vocabulary_is_closed(self) -> None:
        self.assertIn(self.decision["final_decision"], _FINAL_DECISIONS)

    def test_gate_statuses_use_the_matrix_vocabulary(self) -> None:
        for field in ("engineering_status", "security_status",
                      "hardware_status", "signing_status", "approval_status",
                      "alpha_validation_status"):
            self.assertIn(self.decision[field], _GATE_STATUSES, field)

    def test_the_ten_conditions_are_all_present_and_unreworded(self) -> None:
        conditions = self.decision["blocking_conditions"]
        self.assertEqual({c["condition"] for c in conditions},
                         set(_CONDITION_TITLES))
        for condition in conditions:
            self.assertEqual(condition["title"],
                             _CONDITION_TITLES[condition["condition"]])
            self.assertIn(condition["state"],
                          ("TRUE", "FALSE", "UNDETERMINED"))
            self.assertTrue(condition["basis"],
                            "a condition state without a basis is a guess")

    def test_external_statuses_track_the_ledger_not_hope(self) -> None:
        """A gate leaves NOT_RUN only on gate-eligible ACCEPTED intake."""
        effective = intake.effective_statuses(self.ledger)
        for field, source in _GATE_SOURCES.items():
            eligible = [
                e for e in self.ledger["entries"]
                if e["source"] == source and e.get("gateEligible")
                and effective[e["intakeId"]] == "ACCEPTED"
            ]
            if not eligible:
                self.assertEqual(
                    self.decision[field], "NOT_RUN",
                    "%s has no accepted evidence; absence is NOT_RUN, "
                    "never PASS" % field,
                )

    def test_conditions_seven_and_eight_cannot_clear_on_absence(self) -> None:
        effective = intake.effective_statuses(self.ledger)
        by_condition = {c["condition"]: c for c in
                        self.decision["blocking_conditions"]}
        for condition_id, source in ((7, "signing"), (8, "second-approval")):
            eligible = [
                e for e in self.ledger["entries"]
                if e["source"] == source and e.get("gateEligible")
                and effective[e["intakeId"]] == "ACCEPTED"
            ]
            if not eligible:
                self.assertEqual(
                    by_condition[condition_id]["state"], "TRUE",
                    "condition %d: absence blocks, it does not clear"
                    % condition_id,
                )

    def test_the_repository_did_not_authorize_itself(self) -> None:
        """AUTHORIZED without owner evidence in the ledger is a violation;
        today's decision is MORE_EVIDENCE_REQUIRED, which the floor never
        objects to."""
        self.assertEqual(
            intake.authorization_floor(self.decision, self.ledger), []
        )


class AuthorizationFloorControls(unittest.TestCase):
    """The self-authorization failure branch, executed every run."""

    def setUp(self) -> None:
        real = json.loads(_LEDGER.read_text(encoding="utf-8"))
        self.empty_ledger = dict(real, entries=[])

    def _constructed_decision(self, final: str) -> dict:
        return {"final_decision": final}

    def test_authorized_without_evidence_is_a_violation(self) -> None:
        violations = intake.authorization_floor(
            self._constructed_decision("AUTHORIZED"), self.empty_ledger
        )
        self.assertEqual(len(violations), 3,
                         "security-review, signing and second-approval "
                         "must each refuse")
        for violation in violations:
            self.assertIn("no gate-eligible ACCEPTED intake", violation)

    def test_authorized_with_limitations_is_held_to_the_same_floor(self) -> None:
        violations = intake.authorization_floor(
            self._constructed_decision("AUTHORIZED_WITH_LIMITATIONS"),
            self.empty_ledger,
        )
        self.assertEqual(len(violations), 3)

    def test_more_evidence_required_is_always_expressible(self) -> None:
        self.assertEqual(
            intake.authorization_floor(
                self._constructed_decision("MORE_EVIDENCE_REQUIRED"),
                self.empty_ledger,
            ),
            [],
            "the honest default must never be blocked by the floor",
        )

    def test_the_floor_clears_only_on_eligible_accepted_intake(self) -> None:
        entries = []
        for index, source in enumerate(intake.AUTHORIZATION_FLOOR_SOURCES, 1):
            entry = {
                "intakeId": "INTAKE-%03d" % index,
                "revises": None,
                "source": source,
                "status": "ACCEPTED",
                "gateEligible": True,
                "files": {},
            }
            entry["seal"] = intake.seal_entry(entry)
            entries.append(entry)
        ledger = dict(self.empty_ledger, entries=entries)
        self.assertEqual(
            intake.authorization_floor(
                self._constructed_decision("AUTHORIZED"), ledger
            ),
            [],
            "with real accepted evidence the floor no longer objects — "
            "authority itself remains a human question",
        )


class FindingsRegistry(unittest.TestCase):
    """Triage structure: closed vocabularies, no silent acceptance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(_FINDINGS.read_text(encoding="utf-8"))
        cls.ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))

    def test_the_identifier_schemes_are_the_three(self) -> None:
        self.assertEqual(
            self.registry["identifierSchemes"],
            {"security-review": "SEC-P9-NNN", "hardware": "HW-P9-NNN",
             "alpha-feedback": "ALPHA-P9-NNN"},
        )

    def test_the_vocabularies_are_closed(self) -> None:
        self.assertEqual(len(self.registry["categoryVocabulary"]), 11)
        self.assertEqual(tuple(self.registry["confidenceVocabulary"]),
                         ("CONFIRMED", "LIKELY", "REPORTED", "UNREPRODUCED"))
        self.assertEqual(
            tuple(self.registry["dispositionVocabulary"]),
            ("FIX_NOW", "FIX_BEFORE_ALPHA", "ACCEPT_FOR_ALPHA", "DEFER",
             "NOT_REPRODUCIBLE", "NOT_APPLICABLE"),
        )
        self.assertEqual(len(self.registry["hardwareClassificationVocabulary"]), 9)
        self.assertEqual(len(self.registry["securityDisagreementVocabulary"]), 7)

    def test_every_finding_cites_an_accepted_intake(self) -> None:
        accepted = {
            e["intakeId"] for e in self.ledger["entries"]
            if e["status"] == "ACCEPTED"
        }
        for finding in self.registry["findings"]:
            self.assertIn(finding["intakeId"], accepted,
                          "a finding exists only downstream of ACCEPTED intake")

    def test_no_silent_acceptance(self) -> None:
        required = self.registry["acceptForAlphaRequires"]
        self.assertEqual(required,
                         ["risk", "owner", "affectedArtifact", "rationale",
                          "reviewBy"])
        for finding in self.registry["findings"]:
            if finding.get("disposition") == "ACCEPT_FOR_ALPHA":
                for field in required:
                    self.assertIn(field, finding)
                    self.assertTrue(finding[field])

    def test_reproduction_names_its_boundary(self) -> None:
        for finding in self.registry["findings"]:
            if finding.get("reproductionConfidence") == "CONFIRMED":
                self.assertIn(finding.get("reproducedOn"),
                              ("ON_SUBJECT_ARTIFACT", "ON_NEWER_ARTIFACT"))


if __name__ == "__main__":
    unittest.main()

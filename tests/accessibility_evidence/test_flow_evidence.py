# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility evidence from real assistive-technology sessions.

The rules under test are the ones a well-meaning submission gets wrong: a result
with no steps, media without consent, an unversioned assistive technology, and a
project deciding for itself that its own interfaces are usable.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from release.accessibility import (
    ACCESSIBILITY_FLOWS,
    CRITICAL_FLOWS,
    ENVIRONMENTS,
    PRE_INSTALL_FLOWS,
    RESULTS,
    AccessibilityEvidenceError,
    evaluate_evidence,
    evidence_plan,
    parse_flow_result,
)

ROOT = Path(__file__).resolve().parents[2]


def flow(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "flow": "login",
        "assistiveTechnology": "Orca",
        "assistiveTechnologyVersion": "50.2",
        "environment": "installed-system",
        "imageDigest": "sha256:" + "a" * 64,
        "operator": "an operator",
        "operatorIsDailyUser": True,
        "startedAt": "2026-08-01T10:00:00Z",
        "completedAt": "2026-08-01T10:20:00Z",
        "steps": ["focus the password field", "type the passphrase", "confirm"],
        "result": "PASS",
        "failureSeverity": "none",
        "notes": "",
        "redactionState": "not-required",
        "screenshotConsent": False,
    }
    record.update(overrides)
    return record


class SeventeenFlows(unittest.TestCase):
    def test_there_are_seventeen_flows(self) -> None:
        self.assertEqual(len(ACCESSIBILITY_FLOWS), 17)

    def test_seven_flows_are_critical(self) -> None:
        for name in (
            "keyboard-only-installation",
            "screen-reader-installation",
            "disk-selection",
            "encryption",
            "recovery-key-display",
            "login",
            "recovery",
        ):
            self.assertIn(name, CRITICAL_FLOWS, name)

    def test_the_two_pre_install_flows_are_named(self) -> None:
        for name in PRE_INSTALL_FLOWS:
            self.assertIn(name, ACCESSIBILITY_FLOWS)

    def test_source_inspection_is_not_an_environment(self) -> None:
        self.assertNotIn("source-inspection", ENVIRONMENTS)
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(environment="source-inspection"))
        self.assertIn("not an environment", str(raised.exception))

    def test_the_plan_names_every_flow_and_every_refusal(self) -> None:
        plan = evidence_plan()
        self.assertEqual(len(plan["flows"]), 17)
        joined = " ".join(plan["refusals"])
        self.assertIn("source-inspection", joined)
        self.assertIn("NOT_RUN", joined)


class AResultNeedsSteps(unittest.TestCase):
    def test_a_pass_with_no_steps_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(steps=[]))
        self.assertIn("an assertion", str(raised.exception))

    def test_a_not_run_carrying_steps_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(result="NOT_RUN"))
        self.assertIn("that is a PARTIAL", str(raised.exception).replace("PARTIAL, not NOT_RUN", "that is a PARTIAL"))

    def test_a_clean_not_run_is_accepted(self) -> None:
        parsed = parse_flow_result(
            flow(result="NOT_RUN", steps=[], failureSeverity="none", assistiveTechnology="")
        )
        self.assertEqual(parsed.result, "NOT_RUN")
        self.assertTrue(parsed.blocking)

    def test_a_not_run_with_a_failure_severity_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(result="NOT_RUN", steps=[], failureSeverity="critical"))
        self.assertIn("has no observed failure", str(raised.exception))

    def test_a_pass_with_a_failure_severity_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(failureSeverity="high"))
        self.assertIn("a pass with a failure is a partial", str(raised.exception))

    def test_a_failure_without_a_severity_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(result="FAIL", failureSeverity="none"))
        self.assertIn("cannot be triaged", str(raised.exception))

    def test_an_unversioned_assistive_technology_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(assistiveTechnologyVersion="latest"))
        self.assertIn("is not a finding", str(raised.exception))

    def test_a_result_that_does_not_name_the_image_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(imageDigest=""))
        self.assertIn("cannot be attributed to a build", str(raised.exception))


class MediaNeedsConsent(unittest.TestCase):
    def test_media_without_consent_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(flow(evidenceReference="login.webm", screenshotConsent=False))
        self.assertIn("shows a person using a computer", str(raised.exception))

    def test_media_with_pending_redaction_is_refused(self) -> None:
        with self.assertRaises(AccessibilityEvidenceError) as raised:
            parse_flow_result(
                flow(
                    evidenceReference="login.webm",
                    screenshotConsent=True,
                    redactionState="pending",
                )
            )
        self.assertIn("must be removed before delivery", str(raised.exception))

    def test_consented_and_redacted_media_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "login.webm").write_bytes(b"recording")
            parsed = parse_flow_result(
                flow(
                    evidenceReference="login.webm",
                    screenshotConsent=True,
                    redactionState="completed",
                ),
                evidenceRoot=root,
            )
        self.assertEqual(parsed.evidenceReference, "login.webm")

    def test_media_escaping_the_evidence_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AccessibilityEvidenceError) as raised:
                parse_flow_result(
                    flow(
                        evidenceReference="../../LICENSE",
                        screenshotConsent=True,
                        redactionState="completed",
                    ),
                    evidenceRoot=Path(directory),
                )
            self.assertIn("escapes the evidence root", str(raised.exception))


class TheProjectCannotDecideForItself(unittest.TestCase):
    def _all_passing(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "results": [flow(flow=name) for name in ACCESSIBILITY_FLOWS],
        }

    def test_every_flow_passing_is_still_blocked_without_a_review(self) -> None:
        result = evaluate_evidence(self._all_passing(), independentReviewComplete=False)
        self.assertFalse(result["requirementMet"])
        self.assertTrue(
            any("cannot be the party" in reason for reason in result["reasons"]), result["reasons"]
        )

    def test_every_flow_passing_with_a_review_is_accepted(self) -> None:
        result = evaluate_evidence(self._all_passing(), independentReviewComplete=True)
        self.assertTrue(result["requirementMet"], result["reasons"])
        self.assertEqual(result["result"], "PASS")

    def test_one_missing_flow_blocks(self) -> None:
        document = self._all_passing()
        document["results"] = document["results"][:-1]  # type: ignore[index]
        result = evaluate_evidence(document, independentReviewComplete=True)
        self.assertFalse(result["requirementMet"])
        self.assertEqual(len(result["missingFlows"]), 1)

    def test_a_flow_driven_twice_keeps_its_worst_result(self) -> None:
        document = {
            "schemaVersion": 1,
            "results": [
                flow(flow="login", result="PASS"),
                flow(
                    flow="login",
                    result="FAIL",
                    failureSeverity="critical",
                    assistiveTechnology="Orca",
                    assistiveTechnologyVersion="49.0",
                ),
            ],
        }
        result = evaluate_evidence(document, independentReviewComplete=True)
        self.assertIn("login", result["failingFlows"])
        self.assertNotIn("login", result["passingFlows"])

    def test_a_critical_flow_failure_is_reported_as_such(self) -> None:
        document = self._all_passing()
        document["results"] = [  # type: ignore[index]
            flow(flow=name, result="FAIL" if name == "encryption" else "PASS",
                 failureSeverity="critical" if name == "encryption" else "none")
            for name in ACCESSIBILITY_FLOWS
        ]
        result = evaluate_evidence(document, independentReviewComplete=True)
        self.assertIn("encryption", result["criticalUnresolvedFlows"])

    def test_results_vocabulary_is_fixed(self) -> None:
        self.assertEqual(set(RESULTS), {"PASS", "FAIL", "PARTIAL", "NOT_RUN"})


class CommittedState(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(
            (ROOT / "operations/data/accessibility-evidence.json").read_text(encoding="utf-8")
        )

    def test_no_flow_has_been_driven(self) -> None:
        result = evaluate_evidence(self.document, independentReviewComplete=False)
        self.assertEqual(len(result["notRunFlows"]), 17)
        self.assertEqual(result["passingFlows"], [])
        self.assertEqual(result["assistiveTechnologies"], [])

    def test_the_record_blocks(self) -> None:
        result = evaluate_evidence(self.document, independentReviewComplete=False)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertFalse(result["requirementMet"])

    def test_every_critical_flow_is_unresolved(self) -> None:
        result = evaluate_evidence(self.document, independentReviewComplete=False)
        self.assertEqual(set(result["criticalUnresolvedFlows"]), set(CRITICAL_FLOWS))

    def test_the_record_says_static_tests_are_not_sufficient(self) -> None:
        self.assertIn("not sufficient", self.document["note"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

from __future__ import annotations

import unittest

from operations.feedback import FeedbackIssue, ingest_documents, stable_issue_id, suggest_duplicates


def report(source_id: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source": "github-export",
        "sourceId": source_id,
        "affectedVersion": "0.5.0-beta.1",
        "component": "Installer",
        "severity": "High",
        "reproducibility": "always",
        "environment": {"firmware": "UEFI", "email": "person@example.org"},
        "owner": "installer-team",
        "targetRelease": "unassigned",
        "workaround": "Use another disk",
        "verificationStatus": "unverified",
        "closureEvidence": "",
        "symptomText": "installation fails with disk-probe-timeout",
        "affectedWorkflow": "clean-install",
        "errorSignature": "disk-probe-timeout",
        "stackSignature": "probe-timeout-v1",
        "hardwareClass": "q35-virtio",
        "kernelVersion": "unknown",
        "imageVersion": "beta.1",
        "evidenceLinks": ["https://example.invalid/issues/1"],
    }
    value.update(changes)
    return value


class FeedbackTests(unittest.TestCase):
    def test_stable_id_does_not_depend_on_report_text(self) -> None:
        self.assertEqual(stable_issue_id("a", "b"), stable_issue_id("a", "b"))

    def test_import_redacts_identifiers_before_storage(self) -> None:
        issue = FeedbackIssue.parse(report("1"))
        self.assertEqual(issue.data["environment"]["email"], "[redacted]")
        self.assertEqual(issue.data["severityStatus"], "human-confirmation-required")

    def test_import_rejects_user_content_field(self) -> None:
        raw = report("1")
        raw["prompt"] = "private"
        with self.assertRaises(ValueError):
            FeedbackIssue.parse(raw)

    def test_import_rejects_non_https_evidence(self) -> None:
        with self.assertRaises(ValueError):
            FeedbackIssue.parse(report("1", evidenceLinks=["file:///private/log"]))

    def test_duplicate_source_records_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ingest_documents([report("1"), report("1")])

    def test_duplicate_is_suggestion_only(self) -> None:
        issues = ingest_documents([report("1"), report("2")])
        suggestions = suggest_duplicates(issues)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["action"], "suggest-only")
        self.assertTrue(suggestions[0]["humanConfirmationRequired"])

    def test_different_reports_are_not_merged(self) -> None:
        issues = ingest_documents([report("1"), report("2", component="Audio", errorSignature="codec", stackSignature="alsa", hardwareClass="laptop", affectedWorkflow="audio", symptomText="headphones produce no sound after resume")])
        self.assertEqual(suggest_duplicates(issues), [])

    def test_unknown_taxonomy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FeedbackIssue.parse(report("1", component="Other"))


if __name__ == "__main__":
    unittest.main()

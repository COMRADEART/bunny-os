# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent review intake: the self-review wall and the signature requirement.

The mandated adversarial cases exercised here:

* a self-review marked independent (case 8)
* an unsigned review report (case 9)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from release.reviews import (
    PROHIBITED_CLAIM_MARKERS,
    PROJECT_PRINCIPALS,
    REQUEST_SECTIONS,
    REVIEW_KINDS,
    ReviewError,
    acceptable_review_identifiers,
    evaluate_requests,
    evaluate_review_records,
    is_self_review,
    parse_review_record,
    request_gaps,
)

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "80df25b09f6578276d18c8a82f15c47dd8959740"
OTHER_COMMIT = "79bb99ddb39d8a5dbc279629f43b23346fb0e5e8"

DECLARATION = (
    "I have no employment, contract, consultancy, equity or advisory relationship with ComradeArt "
    "or the Bunny OS project other than this engagement, and I authored none of the code under "
    "review. These conclusions are my own."
)


def record(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "reviewId": "review-security-001",
        "reviewType": "security",
        "reviewerName": "Dr A. Reviewer",
        "reviewerOrganisation": "Independent Security Practice",
        "independenceDeclaration": DECLARATION,
        "scopeCommit": COMMIT,
        "scopeArtifacts": ["security/reachability/packages/", "services/"],
        "completedAt": "2026-08-15T00:00:00Z",
        "findings": [],
        "conclusion": "pass",
        "reportDigest": hashlib.sha256(b"report").hexdigest(),
        "signature": "MEUCIQ...",
    }
    value.update(overrides)
    return value


class SelfReviewIsRefused(unittest.TestCase):
    """Adversarial case 8."""

    def test_a_maintainer_cannot_mark_their_own_review_independent(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(
                record(reviewerName="Bunny OS maintainer", reviewerOrganisation="ComradeArt")
            )
        message = str(raised.exception)
        self.assertIn("affiliated with the project", message)
        self.assertIn("cannot mark their own review as independent", message)

    def test_every_project_principal_is_refused(self) -> None:
        for principal in PROJECT_PRINCIPALS:
            self.assertTrue(is_self_review(principal, ""), principal)
            with self.assertRaises(ReviewError, msg=principal):
                parse_review_record(record(reviewerName=principal, reviewerOrganisation=""))

    def test_an_internal_organisation_is_refused(self) -> None:
        with self.assertRaises(ReviewError):
            parse_review_record(
                record(reviewerName="Someone", reviewerOrganisation="Internal audit")
            )

    def test_a_declaration_that_is_a_flag_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(record(independenceDeclaration="independent: true"))
        self.assertIn("not a flag", str(raised.exception))

    def test_an_anonymous_reviewer_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(record(reviewerName=""))
        self.assertIn("identifiable reviewer", str(raised.exception))

    def test_an_external_reviewer_is_accepted(self) -> None:
        parsed = parse_review_record(record())
        self.assertEqual(parsed.reviewerName, "Dr A. Reviewer")
        self.assertTrue(parsed.acceptable)


class UnsignedReportIsRefused(unittest.TestCase):
    """Adversarial case 9."""

    def test_an_unsigned_record_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(record(signature=None))
        self.assertIn("unsigned", str(raised.exception))
        self.assertIn("can be substituted", str(raised.exception))

    def test_a_digest_that_does_not_match_the_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.md"
            report.write_bytes(b"the actual report")
            with self.assertRaises(ReviewError) as raised:
                parse_review_record(
                    record(reportReference="report.md", reportDigest=hashlib.sha256(b"report").hexdigest()),
                    root=root,
                )
            self.assertIn("was changed after the record was written", str(raised.exception))

    def test_a_matching_digest_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.md"
            report.write_bytes(b"the actual report")
            parsed = parse_review_record(
                record(
                    reportReference="report.md",
                    reportDigest=hashlib.sha256(b"the actual report").hexdigest(),
                ),
                root=root,
            )
            self.assertEqual(parsed.reportReference, "report.md")

    def test_a_missing_report_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewError) as raised:
                parse_review_record(record(reportReference="absent.md"), root=Path(directory))
            self.assertIn("does not exist", str(raised.exception))

    def test_a_report_reference_escaping_the_repository_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewError) as raised:
                parse_review_record(record(reportReference="../outside.md"), root=Path(directory))
            self.assertIn("escapes the repository", str(raised.exception))

    def test_a_bad_digest_format_is_refused(self) -> None:
        with self.assertRaises(ReviewError):
            parse_review_record(record(reportDigest="not-a-digest"))


class ScopeAndConclusion(unittest.TestCase):
    def test_a_review_of_another_commit_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(record(scopeCommit=OTHER_COMMIT), expectedCommit=COMMIT)
        self.assertIn("does not transfer between commits", str(raised.exception))

    def test_an_unscoped_review_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(record(scopeArtifacts=[]))
        self.assertIn("unscoped review", str(raised.exception))

    def test_a_pass_with_an_open_critical_finding_is_refused(self) -> None:
        with self.assertRaises(ReviewError) as raised:
            parse_review_record(
                record(
                    findings=[
                        {
                            "findingId": "F-1",
                            "severity": "critical",
                            "summary": "the broker exposes a generic exec path",
                            "state": "open",
                        }
                    ]
                )
            )
        self.assertIn("conditional pass at best", str(raised.exception))

    def test_a_conditional_with_an_open_finding_is_not_acceptable(self) -> None:
        parsed = parse_review_record(
            record(
                conclusion="conditional",
                findings=[
                    {
                        "findingId": "F-1",
                        "severity": "high",
                        "summary": "unresolved",
                        "state": "open",
                    }
                ],
            )
        )
        self.assertFalse(parsed.acceptable)
        self.assertEqual(len(parsed.unresolvedFindings), 1)

    def test_a_fail_is_never_acceptable(self) -> None:
        parsed = parse_review_record(record(conclusion="fail"))
        self.assertFalse(parsed.acceptable)

    def test_a_reachability_conclusion_is_carried_per_advisory(self) -> None:
        parsed = parse_review_record(
            record(
                findings=[
                    {
                        "findingId": "F-1",
                        "severity": "informational",
                        "summary": "the module is present but no path reaches it",
                        "state": "resolved",
                        "advisoryIds": ["GHSA-5cgq-3rg8-m6cv"],
                        "reachabilityConclusion": "Present but unreachable",
                    }
                ]
            )
        )
        self.assertEqual(parsed.findings[0].advisoryIds, ("GHSA-5cgq-3rg8-m6cv",))
        self.assertEqual(parsed.findings[0].reachabilityConclusion, "Present but unreachable")

    def test_only_acceptable_records_become_usable_identifiers(self) -> None:
        document = {"records": [record(), record(reviewId="review-fail", conclusion="fail")]}
        identifiers = acceptable_review_identifiers(document, expectedCommit=COMMIT)
        self.assertEqual(identifiers, ("review-security-001",))


class RecordSetEvaluation(unittest.TestCase):
    def test_no_records_means_all_four_outstanding(self) -> None:
        result = evaluate_review_records({"records": []}, expectedCommit=COMMIT)
        self.assertEqual(set(result["outstandingReviewTypes"]), set(REVIEW_KINDS))
        self.assertEqual(result["result"], "BLOCKED")

    def test_one_bad_record_blocks_even_beside_good_ones(self) -> None:
        result = evaluate_review_records(
            {
                "records": [
                    record(),
                    record(reviewId="bad", reviewType="legal", signature=None),
                ]
            },
            expectedCommit=COMMIT,
        )
        self.assertFalse(result["allComplete"])
        self.assertTrue(result["rejected"])

    def test_all_four_delivered_and_clean_passes(self) -> None:
        result = evaluate_review_records(
            {
                "records": [
                    record(reviewId=f"review-{kind}", reviewType=kind)
                    for kind in REVIEW_KINDS
                ]
            },
            expectedCommit=COMMIT,
        )
        self.assertTrue(result["allComplete"], result)
        self.assertEqual(result["result"], "PASS")

    def test_the_committed_document_has_no_delivered_record(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/independent-reviews.json").read_text(encoding="utf-8")
        )
        result = evaluate_review_records(document, root=ROOT, expectedCommit=COMMIT)
        self.assertEqual(result["acceptedCount"], 0)
        self.assertEqual(result["result"], "BLOCKED")


class RequestPackages(unittest.TestCase):
    def test_all_four_requests_exist_and_are_complete(self) -> None:
        result = evaluate_requests(ROOT)
        self.assertEqual(result["result"], "PASS", result["requests"])
        self.assertEqual(set(result["readyRequests"]), set(REVIEW_KINDS))

    def test_every_request_names_all_ten_sections(self) -> None:
        for kind in REVIEW_KINDS:
            self.assertEqual(request_gaps(ROOT, kind), (), kind)

    def test_every_request_forbids_a_certification_claim(self) -> None:
        for kind in REVIEW_KINDS:
            text = (ROOT / "reviews" / kind / "REQUEST.md").read_text(encoding="utf-8").casefold()
            self.assertTrue(
                any(marker in text for marker in PROHIBITED_CLAIM_MARKERS),
                f"{kind} does not forbid a certification claim",
            )

    def test_no_request_invents_a_reviewer_or_a_date(self) -> None:
        # A request naming a reviewer would be a fabricated engagement. Each must
        # instead tell the reviewer to record the commit they are given.
        for kind in REVIEW_KINDS:
            text = (ROOT / "reviews" / kind / "REQUEST.md").read_text(encoding="utf-8")
            self.assertIn("scopeCommit", text, kind)
            self.assertIn("the commit you are given", text.casefold(), kind)

    def test_a_missing_section_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reviews/security").mkdir(parents=True)
            (root / "reviews/security/REQUEST.md").write_text(
                "# Request\n\nexact scope: everything\n", encoding="utf-8"
            )
            gaps = request_gaps(root, "security")
            self.assertIn("severity model", gaps)
            self.assertIn("prohibited claims", gaps)

    def test_an_absent_request_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(request_gaps(Path(directory), "legal"), ("REQUEST.md does not exist",))

    def test_the_ten_required_sections_are_declared(self) -> None:
        self.assertEqual(len(REQUEST_SECTIONS), 10)
        for name in ("threat model", "severity model", "prohibited claims"):
            self.assertIn(name, REQUEST_SECTIONS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

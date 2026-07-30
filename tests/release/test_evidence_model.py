"""Stable evidence model: structure, and the four ways a record can lie.

Three of the fourteen mandated adversarial cases live here — forged evidence,
stale evidence, and evidence from the wrong commit — plus the self-review case,
because the evidence model is where a third-party claim is checked.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
from pathlib import Path
import tempfile
import unittest

from release.evidence import (
    EVIDENCE_CATEGORIES,
    EVIDENCE_TYPES,
    NON_WAIVABLE_CATEGORIES,
    EvidenceError,
    evaluate_evidence,
    file_digest,
    parse_record,
    verify_record,
)

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
NOW = _datetime.datetime(2026, 7, 29, 12, 0, 0, tzinfo=_datetime.timezone.utc)


def record(**overrides):
    base = {
        "id": "build-001",
        "category": "Build",
        "description": "beta image built from a digest-pinned base",
        "evidenceType": "command-output",
        "evidenceReference": "artifact.txt",
        "generatedAt": "2026-07-29T10:00:00Z",
        "sourceCommit": COMMIT,
        "result": "PASS",
        "reviewer": "Bunny OS maintainer",
    }
    base.update(overrides)
    return base


class EvidenceStructureTests(unittest.TestCase):
    def test_twenty_categories_are_defined(self):
        self.assertEqual(len(EVIDENCE_CATEGORIES), 20)
        for name in ("Build", "Signing", "Vulnerability", "Licence", "Secure Boot", "Soak", "Support"):
            self.assertIn(name, EVIDENCE_CATEGORIES)

    def test_unknown_field_is_refused(self):
        with self.assertRaises(EvidenceError) as caught:
            parse_record(record(unexpectedField="value"))
        self.assertIn("unknown evidence fields", str(caught.exception))

    def test_missing_field_is_refused(self):
        payload = record()
        del payload["reviewer"]
        with self.assertRaises(EvidenceError):
            parse_record(payload)

    def test_short_commit_is_refused(self):
        with self.assertRaises(EvidenceError) as caught:
            parse_record(record(sourceCommit="abc1234"))
        self.assertIn("40-character", str(caught.exception))

    def test_every_evidence_type_parses(self):
        for kind in EVIDENCE_TYPES:
            parsed = parse_record(record(evidenceType=kind))
            self.assertEqual(parsed.evidenceType, kind)

    def test_non_waivable_category_refuses_a_waiver(self):
        for category in sorted(NON_WAIVABLE_CATEGORIES):
            with self.assertRaises(EvidenceError) as caught:
                parse_record(
                    record(
                        category=category,
                        waiver={
                            "reason": "accepted for the pilot",
                            "reviewer": "someone",
                            "reference": "REV-1",
                            "approvedAt": "2026-07-29T10:00:00Z",
                        },
                    )
                )
            self.assertIn("cannot be waived", str(caught.exception))

    def test_waivable_category_accepts_a_waiver_but_stays_blocking(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "artifact.txt"
            target.write_text("evidence", encoding="utf-8")
            parsed = parse_record(
                record(
                    category="Performance",
                    result="FAIL",
                    contentDigest=file_digest(target),
                    waiver={
                        "reason": "performance target relaxed for the candidate",
                        "reviewer": "Release owner",
                        "reference": "WAIVER-7",
                        "approvedAt": "2026-07-29T10:00:00Z",
                    },
                )
            )
            verdict = verify_record(parsed, root=root, sourceCommit=COMMIT, now=NOW)
            self.assertTrue(verdict.blocking, "a waiver must be recorded, never applied automatically")
            self.assertTrue(any("waiver" in reason for reason in verdict.reasons))


class AdversarialEvidenceTests(unittest.TestCase):
    """The mandated adversarial cases for the evidence model."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.artifact = self.root / "artifact.txt"
        self.artifact.write_text("real evidence content", encoding="utf-8")
        self.digest = file_digest(self.artifact)
        self.addCleanup(self._temporary.cleanup)

    def test_honest_record_does_not_block(self):
        parsed = parse_record(record(contentDigest=self.digest))
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertFalse(verdict.blocking, verdict.reasons)

    # --- adversarial: forged evidence record ---
    def test_forged_record_naming_a_missing_artifact_blocks(self):
        parsed = parse_record(record(evidenceReference="does-not-exist.txt", contentDigest=self.digest))
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("does not exist" in reason for reason in verdict.reasons))

    def test_forged_record_with_substituted_content_blocks(self):
        parsed = parse_record(record(contentDigest=self.digest))
        self.artifact.write_text("content substituted after the record was written", encoding="utf-8")
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("digest mismatch" in reason for reason in verdict.reasons))

    def test_record_without_a_digest_cannot_detect_substitution_and_blocks(self):
        parsed = parse_record(record())
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("cannot detect substitution" in reason for reason in verdict.reasons))

    def test_evidence_reference_escaping_the_repository_blocks(self):
        parsed = parse_record(record(evidenceReference="../outside.txt", contentDigest=self.digest))
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("escapes the repository" in reason for reason in verdict.reasons))

    # --- adversarial: stale evidence ---
    def test_expired_evidence_blocks_even_when_passing(self):
        parsed = parse_record(
            record(contentDigest=self.digest, expiresAt="2026-07-01T00:00:00Z")
        )
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("expired" in reason for reason in verdict.reasons))

    def test_unexpired_evidence_does_not_block(self):
        parsed = parse_record(
            record(contentDigest=self.digest, expiresAt="2027-07-01T00:00:00Z")
        )
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertFalse(verdict.blocking, verdict.reasons)

    # --- adversarial: evidence from the wrong commit ---
    def test_evidence_generated_from_another_commit_blocks(self):
        parsed = parse_record(record(contentDigest=self.digest, sourceCommit=OTHER_COMMIT))
        verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("does not transfer between commits" in reason for reason in verdict.reasons))

    # --- adversarial: self-review marked independent ---
    def test_third_party_report_from_an_unregistered_reviewer_blocks(self):
        parsed = parse_record(record(evidenceType="third-party-report", reviewer="Bunny OS maintainer"))
        verdict = verify_record(
            parsed, root=self.root, sourceCommit=COMMIT, now=NOW, externalReviewers=set()
        )
        self.assertTrue(verdict.blocking)
        self.assertTrue(any("not a registered independent party" in reason for reason in verdict.reasons))

    def test_third_party_report_from_a_registered_reviewer_is_accepted(self):
        parsed = parse_record(record(evidenceType="third-party-report", reviewer="Some Audit Ltd"))
        verdict = verify_record(
            parsed,
            root=self.root,
            sourceCommit=COMMIT,
            now=NOW,
            externalReviewers={"Some Audit Ltd"},
        )
        self.assertFalse(verdict.blocking, verdict.reasons)

    # --- unknown results ---
    def test_unknown_and_not_run_results_block(self):
        for result in ("UNKNOWN", "NOT_RUN", "BLOCKED", "FAIL"):
            parsed = parse_record(record(result=result, contentDigest=self.digest))
            verdict = verify_record(parsed, root=self.root, sourceCommit=COMMIT, now=NOW)
            self.assertTrue(verdict.blocking, f"{result} must block")


class EvidenceDocumentTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.artifact = self.root / "artifact.txt"
        self.artifact.write_text("content", encoding="utf-8")
        self.digest = file_digest(self.artifact)
        self.addCleanup(self._temporary.cleanup)

    def _document(self, records):
        return {"schemaVersion": 1, "records": records}

    def test_absent_category_is_reported_as_missing(self):
        report = evaluate_evidence(
            self._document([record(contentDigest=self.digest)]),
            root=self.root,
            sourceCommit=COMMIT,
            now=NOW,
        )
        self.assertTrue(report.blocked)
        self.assertIn("Signing", report.missingCategories)
        self.assertNotIn("Build", report.missingCategories)

    def test_duplicate_identifiers_are_refused(self):
        payload = self._document([record(contentDigest=self.digest), record(contentDigest=self.digest)])
        with self.assertRaises(EvidenceError) as caught:
            evaluate_evidence(payload, root=self.root, sourceCommit=COMMIT, now=NOW)
        self.assertIn("duplicate evidence ids", str(caught.exception))

    def test_all_categories_present_and_passing_is_not_blocked(self):
        records = [
            record(
                id=f"rec-{index}",
                category=category,
                contentDigest=self.digest,
            )
            for index, category in enumerate(EVIDENCE_CATEGORIES)
        ]
        report = evaluate_evidence(
            self._document(records), root=self.root, sourceCommit=COMMIT, now=NOW
        )
        self.assertEqual(report.missingCategories, ())
        self.assertFalse(report.blocked, [v.reasons for v in report.verdicts if v.blocking])

    def test_one_blocking_record_blocks_its_whole_category(self):
        records = [
            record(id=f"rec-{index}", category=category, contentDigest=self.digest)
            for index, category in enumerate(EVIDENCE_CATEGORIES)
        ]
        records[0]["result"] = "FAIL"
        report = evaluate_evidence(
            self._document(records), root=self.root, sourceCommit=COMMIT, now=NOW
        )
        self.assertTrue(report.blocked)
        self.assertIn(EVIDENCE_CATEGORIES[0], report.missingCategories)

    def test_bad_schema_version_is_refused(self):
        with self.assertRaises(EvidenceError):
            evaluate_evidence({"schemaVersion": 99, "records": []}, root=self.root, sourceCommit=COMMIT, now=NOW)


class FileDigestTests(unittest.TestCase):
    def test_digest_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "f.bin"
            payload = b"x" * (1 << 21)
            path.write_bytes(payload)
            self.assertEqual(file_digest(path), hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()

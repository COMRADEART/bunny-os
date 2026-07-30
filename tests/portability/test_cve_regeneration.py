"""A committed CVE record must follow from the committed evidence.

The CI step that checked this stripped ``generatedAt`` from both sides, compared,
and printed one filename. It could not tell a record that drifted by a timestamp
from one whose conclusion had been edited, and it hid the fact that all 25
records differed in ``sourceCommit`` because the generator stamped ``HEAD`` —
so committing the evidence invalidated it.

These tests hold the replacement: every field classified, one class excludable,
and a structured diff when it fails.

See ``docs/CVE_REGENERATION_INVARIANTS.md``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.regeneration import (  # noqa: E402
    CLASSIFICATIONS,
    EXCLUDABLE_CLASSIFICATIONS,
    GENERATION_METADATA_FIELDS,
    classify_field,
    diff_documents,
    evaluate_regeneration,
    render_differences,
)

FINDINGS = ROOT / "security/reachability/findings"


def a_record() -> dict:
    """A real committed record, so the tests bind to the real shape."""
    return json.loads((FINDINGS / "GHSA-5cgq-3rg8-m6cv.json").read_text(encoding="utf-8"))


def compare(mutate) -> tuple:
    committed = a_record()
    regenerated = copy.deepcopy(committed)
    mutate(regenerated)
    report = evaluate_regeneration({"r.json": committed}, {"r.json": regenerated})
    return report, report.differences


class ClassificationVocabularyTests(unittest.TestCase):
    def test_the_six_classifications_are_named(self) -> None:
        self.assertEqual(
            CLASSIFICATIONS,
            ("Semantic evidence", "Environment metadata", "Generation metadata",
             "Commit identity", "Unstable ordering", "Bug"),
        )

    def test_only_generation_metadata_and_ordering_are_excludable(self) -> None:
        self.assertEqual(
            EXCLUDABLE_CLASSIFICATIONS, {"Generation metadata", "Unstable ordering"}
        )

    def test_the_excluded_field_list_is_exactly_one_field(self) -> None:
        # Widening this set is a change to what the evidence claims. The test
        # exists so that widening it cannot happen quietly.
        self.assertEqual(GENERATION_METADATA_FIELDS, {"generatedAt"})

    def test_an_unrecognised_field_defaults_to_semantic_evidence(self) -> None:
        # Fail closed: a field nobody classified is treated as a measurement.
        self.assertEqual(classify_field("someNewField"), "Semantic evidence")
        self.assertEqual(classify_field("mapping.privilegeRequired"), "Semantic evidence")


class AllowedGenerationDifferenceTests(unittest.TestCase):
    def test_a_differing_generated_at_is_the_only_permitted_difference(self) -> None:
        report, differences = compare(
            lambda r: r.__setitem__("generatedAt", "2099-01-01T00:00:00.000000Z")
        )
        self.assertEqual([d.classification for d in differences], ["Generation metadata"])
        self.assertTrue(report.deterministic)
        self.assertEqual(report.blocking, [])

    def test_the_generated_at_value_is_still_reported_not_deleted(self) -> None:
        _, differences = compare(
            lambda r: r.__setitem__("generatedAt", "2099-01-01T00:00:00.000000Z")
        )
        self.assertEqual(differences[0].regenerated, "2099-01-01T00:00:00.000000Z")
        self.assertIn("generatedAt", differences[0].path)


class SemanticDifferencesAlwaysFailTests(unittest.TestCase):
    def test_a_changed_carrier_object_fails(self) -> None:
        report, differences = compare(
            lambda r: r.__setitem__("carrierObjects", ["/usr/sbin/tampered.file"])
        )
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Semantic evidence")

    def test_a_changed_package_fails(self) -> None:
        report, differences = compare(lambda r: r.__setitem__("packageName", "not-the-package"))
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Semantic evidence")

    def test_a_changed_advisory_fails(self) -> None:
        report, differences = compare(lambda r: r.__setitem__("advisoryId", "CVE-1999-0001"))
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Semantic evidence")

    def test_a_changed_disposition_fails(self) -> None:
        # The disposition is the whole point of the record: "Unknown" blocks and
        # "Present but unreachable" does not.
        report, differences = compare(
            lambda r: r.__setitem__("conclusion", "Present but unreachable")
        )
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Semantic evidence")
        self.assertEqual(differences[0].committed, "Unknown")

    def test_a_changed_candidate_commit_fails(self) -> None:
        report, differences = compare(lambda r: r.__setitem__("sourceCommit", "f" * 40))
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Commit identity")

    def test_a_changed_nested_value_fails(self) -> None:
        # The walk must be recursive; a top-level comparison would miss this.
        def mutate(record):
            record["mapping"]["privilegeRequired"] = "none"

        report, differences = compare(mutate)
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].path, "mapping.privilegeRequired")
        self.assertEqual(differences[0].classification, "Semantic evidence")

    def test_a_removed_field_is_a_bug_not_an_omission(self) -> None:
        report, differences = compare(lambda r: r.pop("conclusion"))
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Bug")

    def test_a_changed_type_is_a_bug(self) -> None:
        report, differences = compare(lambda r: r.__setitem__("carrierObjects", "a string"))
        self.assertFalse(report.deterministic)
        self.assertEqual(differences[0].classification, "Bug")

    def test_a_semantic_difference_is_never_excluded_by_an_accompanying_timestamp(self) -> None:
        # The failure mode the old check had: strip the timestamp, and hope.
        def mutate(record):
            record["generatedAt"] = "2099-01-01T00:00:00.000000Z"
            record["conclusion"] = "Present but unreachable"

        report, _ = compare(mutate)
        self.assertFalse(report.deterministic)
        self.assertEqual(len(report.blocking), 1)
        self.assertEqual(report.blocking[0].path, "conclusion")


class OrderingTests(unittest.TestCase):
    def test_reordered_list_members_do_not_fail(self) -> None:
        record = a_record()
        if len(record.get("candidateCarriers", [])) < 2:
            self.skipTest("record has no multi-member list to reorder")
        report, differences = compare(
            lambda r: r.__setitem__("candidateCarriers", list(reversed(r["candidateCarriers"])))
        )
        self.assertTrue(report.deterministic)
        self.assertEqual(differences[0].classification, "Unstable ordering")

    def test_reordered_object_keys_are_not_a_difference_at_all(self) -> None:
        committed = a_record()
        regenerated = dict(reversed(list(committed.items())))
        self.assertEqual(diff_documents(committed, regenerated), [])

    def test_a_changed_member_is_not_mistaken_for_a_reorder(self) -> None:
        report, differences = compare(
            lambda r: r.__setitem__(
                "candidateCarriers", [*r["candidateCarriers"][:-1], "something-else"]
            )
        )
        self.assertFalse(report.deterministic)
        self.assertTrue(any(d.classification == "Semantic evidence" for d in differences))


class DocumentSetTests(unittest.TestCase):
    def test_a_committed_record_that_is_not_regenerated_fails(self) -> None:
        report = evaluate_regeneration({"a.json": a_record()}, {})
        self.assertFalse(report.deterministic)
        self.assertEqual(report.missing, ["a.json"])

    def test_a_regenerated_record_that_is_not_committed_fails(self) -> None:
        report = evaluate_regeneration({}, {"a.json": a_record()})
        self.assertFalse(report.deterministic)
        self.assertEqual(report.unexpected, ["a.json"])


class StructuredDiffOutputTests(unittest.TestCase):
    def test_the_failure_names_path_values_and_classification(self) -> None:
        _, differences = compare(lambda r: r.__setitem__("conclusion", "Not affected"))
        rendered = render_differences(differences)
        self.assertIn("field path:", rendered)
        self.assertIn("committed:", rendered)
        self.assertIn("regenerated:", rendered)
        self.assertIn("classification: Semantic evidence", rendered)
        self.assertIn("Not affected", rendered)
        self.assertIn("BLOCKING", rendered)

    def test_the_failure_does_not_report_merely_does_not_regenerate(self) -> None:
        _, differences = compare(lambda r: r.__setitem__("conclusion", "Not affected"))
        self.assertNotIn("does not regenerate", render_differences(differences))


class LiveRegenerationTests(unittest.TestCase):
    """The command CI runs, against the real committed records."""

    def test_the_committed_findings_regenerate_deterministically(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/reachability.py", "verify-findings"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("regenerate deterministically", result.stdout)

    def test_every_committed_record_binds_to_the_declared_candidate(self) -> None:
        declared = json.loads(
            (ROOT / "operations/data/release-evidence.json").read_text(encoding="utf-8")
        )["candidateCommit"]
        for path in sorted(FINDINGS.glob("*.json")):
            with self.subTest(record=path.name):
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["sourceCommit"], declared)

    def test_no_record_binds_to_head(self) -> None:
        # The defect: HEAD moves when the record is committed.
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
        declared = json.loads(
            (ROOT / "operations/data/release-evidence.json").read_text(encoding="utf-8")
        )["candidateCommit"]
        if head == declared:
            self.skipTest("candidate is currently HEAD; the distinction is not observable")
        record = a_record()
        self.assertNotEqual(record["sourceCommit"], head)

    def test_the_desktop_evidence_names_the_candidate_not_head(self) -> None:
        declared = json.loads(
            (ROOT / "operations/data/release-evidence.json").read_text(encoding="utf-8")
        )["candidateCommit"]
        evidence = a_record()["desktopActivationEvidence"]
        self.assertTrue(evidence, "the record must state what was measured")
        self.assertIn(declared[:12], evidence[0])

    def test_the_desktop_evidence_contains_no_windows_separators(self) -> None:
        # Built from git paths, so it reads identically on every platform.
        for line in a_record()["desktopActivationEvidence"]:
            self.assertNotIn("\\", line)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

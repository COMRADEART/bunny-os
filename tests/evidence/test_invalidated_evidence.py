# SPDX-License-Identifier: GPL-3.0-or-later
"""Invalidated evidence stays invalid, and stays present.

An evidence record that turns out to be wrong is a fact about the project, and
deleting it removes the only durable trace that the mistake happened. So the
defective record is retained byte-for-byte and classified in a separate registry
rather than edited in place.

The failure this guards against is the tempting one. The physical-hardware record
carries a digest measured from CRLF bytes, and there is a one-character change
that makes it verify: replace its digest with the digest of the committed bytes.
That would bind a record to bytes it was never measured from, and it would
silently convert "no physical machine has been qualified" into "physical evidence
present and verifying". These tests make that edit fail loudly.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "qualification" / "hardware" / "INVALIDATED_EVIDENCE.json"
EVIDENCE = ROOT / "operations" / "data" / "release-evidence.json"


def registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def evidence_records() -> dict[str, dict]:
    document = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return {record["id"]: record for record in document["records"]}


def committed_digest(path: str) -> str:
    return sha256(
        subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=ROOT)
    ).hexdigest()


class RegistryShapeTests(unittest.TestCase):
    def test_the_registry_exists_and_is_not_empty(self):
        self.assertTrue(REGISTRY.is_file())
        self.assertTrue(registry()["invalidated"])

    def test_every_entry_names_a_record_that_still_exists(self):
        records = evidence_records()
        for entry in registry()["invalidated"]:
            self.assertIn(
                entry["recordId"],
                records,
                "an invalidated record was deleted; retain it and keep it classified",
            )

    def test_every_entry_states_why_and_what_replaces_it(self):
        for entry in registry()["invalidated"]:
            self.assertEqual(entry["classification"], "INVALIDATED_EVIDENCE")
            self.assertTrue(entry["reason"])
            self.assertTrue(entry["replacementRequired"])
            self.assertEqual(entry["qualificationEffect"], "none")


class DigestImmutabilityTests(unittest.TestCase):
    """The digest of an invalidated record is never edited."""

    def test_the_recorded_digest_still_matches_the_registry(self):
        records = evidence_records()
        for entry in registry()["invalidated"]:
            record = records[entry["recordId"]]
            self.assertEqual(
                record["contentDigest"],
                entry["recordedDigest"],
                f"{entry['recordId']}: the recorded digest was edited. An invalidated "
                "record is replaced by a new measurement under a new id, never "
                "repaired in place.",
            )

    def test_the_recorded_digest_is_still_wrong(self):
        """If this passes by accident one day, something was quietly repaired."""
        for entry in registry()["invalidated"]:
            if entry["reason"] != "CONTENT_FILTER_BOUND_DIGEST":
                continue
            actual = committed_digest(entry["evidenceReference"])
            self.assertEqual(
                actual,
                entry["committedDigest"],
                "the attested file changed; the registry records the byte state at "
                "invalidation and needs re-checking",
            )
            self.assertNotEqual(
                entry["recordedDigest"],
                actual,
                f"{entry['recordId']}: the record now matches the committed bytes. "
                "If it was re-measured, mint a new evidence id and remove this "
                "entry deliberately; do not re-digest in place.",
            )

    def test_replacement_must_not_reuse_the_same_identifier(self):
        for entry in registry()["invalidated"]:
            self.assertTrue(entry["mustNotBeReplacedInPlace"])
            self.assertIsNone(
                entry["replacementEvidenceId"],
                "a replacement id is recorded; assert it differs from the "
                "invalidated record id before closing this out",
            )


class NoCreditTests(unittest.TestCase):
    """An invalidated record cannot satisfy anything."""

    def test_an_invalidated_record_does_not_report_pass(self):
        records = evidence_records()
        for entry in registry()["invalidated"]:
            self.assertNotEqual(
                records[entry["recordId"]]["result"],
                "PASS",
                f"{entry['recordId']} is invalidated and must not claim PASS",
            )

    def test_the_physical_hardware_prerequisite_is_not_satisfied(self):
        """The gate's own arithmetic, not a restatement of it."""
        result = subprocess.run(
            ["python", "scripts/release.py", "gate", "--kind", "qualification-candidate"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0, "the candidate gate must still block")
        self.assertIn("Physical hardware evidence passed", result.stdout)
        for line in result.stdout.splitlines():
            if "Physical hardware evidence passed" in line:
                self.assertIn(
                    "BLOCKED",
                    line,
                    "physical hardware must not be satisfied while its only record "
                    "is invalidated",
                )


if __name__ == "__main__":
    unittest.main()

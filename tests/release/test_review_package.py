# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The review package's promises, enforced.

The §5 rules are structural claims about a committed JSON document, so they
are tested as such: the disposition vocabulary is closed, UNKNOWN is exactly
the set of rows whose versions cannot be ordered, nothing is NOT_AFFECTED
(no evidence in this repository establishes that for any finding), the
per-binary analysis is carried verbatim rather than collapsed, and the
package binds to the frozen artifact by digest.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "qualification/phase8/security-review/review-package.json"
_GO_HIGH = _ROOT / "qualification/phase7/security/high-go-version-analysis.json"


class ReviewPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = json.loads(_PACKAGE.read_text(encoding="utf-8"))
        cls.findings = cls.package["findings"]

    def test_the_counts_are_the_inventory_counts(self) -> None:
        self.assertEqual(
            sum(1 for f in self.findings if f["severity"] == "Critical"), 8
        )
        self.assertEqual(
            sum(1 for f in self.findings if f["severity"] == "High"), 36
        )

    def test_the_disposition_vocabulary_is_closed(self) -> None:
        allowed = {"AFFECTED", "NOT_AFFECTED", "UNKNOWN", "REQUIRES_REVIEW"}
        for finding in self.findings:
            self.assertIn(finding["disposition"], allowed, finding["advisory"])

    def test_nothing_is_not_affected_without_evidence(self) -> None:
        """No evidence in this repository establishes NOT_AFFECTED for any
        finding; a package claiming one would be manufacturing a review."""
        self.assertEqual(
            [f["advisory"] for f in self.findings if f["disposition"] == "NOT_AFFECTED"],
            [],
        )

    def test_unknown_is_exactly_the_pseudo_version_rows(self) -> None:
        go_high = json.loads(_GO_HIGH.read_text(encoding="utf-8"))
        pseudo = sorted(
            r["finding"] for r in go_high["rows"]
            if r["binaries"] and all(
                "UNDETERMINED" in m["verdict"]
                for b in r["binaries"].values() for m in b.values()
            )
        )
        unknown = sorted(
            f["advisory"] for f in self.findings if f["disposition"] == "UNKNOWN"
        )
        self.assertEqual(unknown, pseudo)

    def test_the_per_binary_analysis_is_not_collapsed(self) -> None:
        """The x/crypto split is the canary: podman at/above fix, skopeo
        affected. A package that collapsed either way loses one of them."""
        row = next(f for f in self.findings if f["advisory"] == "GHSA-q4h4-gmj2-qvw2")
        binaries = row["affectedBinaries"]
        podman = binaries["/usr/bin/podman"]["golang.org/x/crypto"]["versionVerdict"]
        skopeo = binaries["/usr/bin/skopeo"]["golang.org/x/crypto"]["versionVerdict"]
        self.assertIn("AT_OR_ABOVE_FIX", podman)
        self.assertIn("AFFECTED", skopeo)

    def test_every_go_high_finding_carries_per_binary_rows(self) -> None:
        for finding in self.findings:
            if finding["artifactTypes"] == ["go-module"] and finding["severity"] == "High":
                self.assertTrue(
                    finding["affectedBinaries"], f"{finding['advisory']} carries no binaries"
                )

    def test_the_package_binds_to_the_frozen_artifact(self) -> None:
        artifact = self.package["artifact"]
        self.assertEqual(artifact["identifier"], "e906a48793d7")
        self.assertEqual(
            artifact["imageDigest"],
            "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d",
        )
        self.assertEqual(artifact["signingStatus"], "UNSIGNED")
        self.assertTrue(artifact["frozen"])

    def test_the_allowed_review_outcomes_are_the_four(self) -> None:
        self.assertEqual(
            self.package["allowedReviewOutcomes"],
            ["APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED", "MORE_EVIDENCE_REQUIRED"],
        )


if __name__ == "__main__":
    unittest.main()

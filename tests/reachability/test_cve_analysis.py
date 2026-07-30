# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-CVE analysis: the proof classes, and the four ways to overclaim one.

The mandated adversarial cases exercised here:

* missing debuginfo (case 5)
* source and binary version mismatch (case 6)
* absent symbol treated as absent code (case 7)
* Critical CVE accepted without a reviewer (case 15)
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from release.acquisition import (
    KINDS_REQUIRED_FOR_MAPPING,
    AcquisitionError,
    evaluate_manifest,
    match_installed,
    parse_acquisition,
    parse_nevra,
)
from release.cve import (
    ANALYSIS_FIELDS,
    CLASS_EVIDENCE_REQUIREMENTS,
    MAPPING_FIELDS,
    NON_BLOCKING_CLASSES,
    PROOF_CLASSES,
    UNKNOWN,
    CveAnalysisError,
    classify_symbol_evidence,
    evaluate_document,
    parse_analysis,
)

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "security/reachability/findings"


def analysis(**overrides: object) -> dict[str, object]:
    """A minimally valid analysis record, concluding Unknown."""
    record: dict[str, object] = {
        "advisoryId": "GHSA-5cgq-3rg8-m6cv",
        "cveId": UNKNOWN,
        "packageName": "golang.org/x/crypto",
        "sourcePackage": UNKNOWN,
        "binaryPackage": UNKNOWN,
        "installedVersion": "v0.46.0",
        "fixedVersion": "0.52.0",
        "installedExecutableOrLibrary": "/sysroot/ostree/repo/objects/8f/bfb473.file",
        "sourceRpmReference": UNKNOWN,
        "debuginfoReference": UNKNOWN,
        "elfBuildId": UNKNOWN,
        "strippedState": UNKNOWN,
        "language": "go",
        "exportedSymbols": [],
        "dynamicDependencies": [],
        "packageScripts": UNKNOWN,
        "systemdUnits": ["podman.socket (present, not enabled)"],
        "socketUnits": ["podman.socket"],
        "dbusActivation": UNKNOWN,
        "desktopActivation": "no",
        "commandInvocationPaths": ["/usr/sbin/podman 0755"],
        "bunnyInvocationPaths": ["none"],
        "pluginInvocationPaths": ["none"],
        "sandboxReachability": "yes",
        "userInvocability": "yes",
        "networkExposure": "none",
        "defaultEnablement": "no",
        "vulnerableFunctionOrSubsystem": UNKNOWN,
        "mapping": {name: UNKNOWN for name in MAPPING_FIELDS},
        "evidenceSource": "evidence/reachability/beta-facts.txt",
        "conclusion": "Unknown",
    }
    record.update(overrides)
    return record


class AbsentSymbolIsNotAbsentCode(unittest.TestCase):
    """Adversarial case 7. The inference this module exists to refuse."""

    def test_absent_symbol_in_a_stripped_binary_supports_nothing(self) -> None:
        verdict = classify_symbol_evidence(
            symbolPresent=False, strippedState="stripped", language="c", debuginfoAvailable=False
        )
        self.assertEqual(verdict["supports"], "nothing")
        self.assertFalse(verdict["sufficientForNotPresent"])
        self.assertIn("not evidence of absent code", verdict["caveat"])

    def test_absent_symbol_in_an_unstripped_go_binary_supports_nothing(self) -> None:
        # Go inlines across package boundaries and the linker rewrites call
        # graphs, so even an unstripped Go binary cannot answer this by name.
        verdict = classify_symbol_evidence(
            symbolPresent=False, strippedState="not-stripped", language="go", debuginfoAvailable=True
        )
        self.assertEqual(verdict["supports"], "nothing")
        self.assertFalse(verdict["sufficientForNotPresent"])

    def test_no_symbol_observation_alone_is_ever_sufficient(self) -> None:
        for stripped in ("stripped", "not-stripped", "partially-stripped", "unknown"):
            for language in ("go", "c", "rust"):
                for present in (True, False):
                    verdict = classify_symbol_evidence(
                        symbolPresent=present,
                        strippedState=stripped,
                        language=language,
                        debuginfoAvailable=True,
                    )
                    self.assertFalse(
                        verdict["sufficientForNotPresent"],
                        f"{stripped}/{language}/present={present} claimed sufficiency",
                    )

    def test_not_present_resting_only_on_symbols_is_rejected(self) -> None:
        with self.assertRaises(CveAnalysisError) as raised:
            parse_analysis(
                analysis(
                    conclusion="Not present",
                    reviewer="External Reviewer",
                    sourcePackageVersion="0.46.0",
                    buildConfiguration="",
                    symbolOrSourceMapping="",
                    exportedSymbols=[],
                    strippedState="stripped",
                )
            )
        # It fails on the missing per-class evidence first, which is the same
        # refusal: the record cites nothing but a symbol table.
        self.assertIn("requires evidence this record does not carry", str(raised.exception))

    def test_not_present_with_debuginfo_and_a_mapping_is_accepted(self) -> None:
        record = parse_analysis(
            analysis(
                conclusion="Not present",
                reviewer="External Reviewer",
                sourcePackageVersion="0.46.0",
                buildConfiguration="Fedora podman.spec, no build tags affecting the module",
                symbolOrSourceMapping="debuginfo shows no instructions from the vulnerable file",
                debuginfoReference="podman-debuginfo-5.8.4-1.fc44.x86_64",
                strippedState="stripped",
            )
        )
        self.assertEqual(record.proofClass, "Not present")
        self.assertFalse(record.blocking)


class MissingDebuginfoBlocks(unittest.TestCase):
    """Adversarial case 5."""

    def test_acquisition_without_debuginfo_is_incomplete(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "acquiredBy": "operator",
            "targets": [
                {
                    "installedNevra": "podman-5.8.4-1.fc44.x86_64",
                    "binaryPath": "/usr/sbin/podman",
                    "acquired": [
                        {
                            "kind": "binary-rpm",
                            "nevra": "podman-5.8.4-1.fc44.x86_64",
                            "repository": "fedora",
                            "url": "https://dl.fedoraproject.org/pub/fedora/linux/podman.rpm",
                            "sha256": "a" * 64,
                            "sizeBytes": 1,
                            "acquiredAt": "2026-07-30T00:00:00Z",
                            "repositoryMetadataDigest": "b" * 64,
                            "storedOutsideRepository": True,
                        }
                    ],
                }
            ],
        }
        result = evaluate_manifest(manifest)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("debuginfo-rpm", result["targets"][0]["missingKinds"])
        self.assertIn("debuginfo", result["note"])

    def test_debuginfo_is_required_for_mapping(self) -> None:
        self.assertIn("debuginfo-rpm", KINDS_REQUIRED_FOR_MAPPING)
        self.assertIn("debugsource-rpm", KINDS_REQUIRED_FOR_MAPPING)

    def test_symbol_verdict_says_debuginfo_must_be_acquired(self) -> None:
        verdict = classify_symbol_evidence(
            symbolPresent=False, strippedState="stripped", language="go", debuginfoAvailable=False
        )
        self.assertIn("Debuginfo must be acquired", verdict["caveat"])


class VersionMismatchRejected(unittest.TestCase):
    """Adversarial case 6."""

    def test_analysing_a_different_release_is_rejected(self) -> None:
        with self.assertRaises(CveAnalysisError) as raised:
            parse_analysis(
                analysis(
                    conclusion="Present but unreachable",
                    reviewer="External Reviewer",
                    installedVersion="v0.46.0",
                    sourcePackageVersion="0.52.0",
                    activationAnalysis="no unit enabled",
                    privilegeAnalysis="unprivileged invocation only",
                    invocationGraph="no path from an entry point",
                    systemConfiguration="podman.socket absent from sockets.target.wants",
                    sandboxOrMacControl="SELinux targeted enforcing",
                )
            )
        self.assertIn("does not correspond to installed", str(raised.exception))

    def test_a_matching_version_with_a_v_prefix_is_accepted(self) -> None:
        record = parse_analysis(
            analysis(
                conclusion="Present but unreachable",
                reviewer="External Reviewer",
                installedVersion="v0.46.0",
                sourcePackageVersion="0.46.0",
                activationAnalysis="no unit enabled",
                privilegeAnalysis="unprivileged invocation only",
                invocationGraph="no path from an entry point",
                systemConfiguration="podman.socket absent from sockets.target.wants",
                sandboxOrMacControl="SELinux targeted enforcing",
            )
        )
        self.assertEqual(record.proofClass, "Present but unreachable")

    def test_a_debuginfo_of_a_different_release_does_not_match(self) -> None:
        record = parse_acquisition(
            {
                "kind": "debuginfo-rpm",
                "nevra": "podman-debuginfo-5.8.4-2.fc44.x86_64",
                "repository": "fedora-debuginfo",
                "url": "https://kojipkgs.fedoraproject.org/packages/podman-debuginfo.rpm",
                "sha256": "c" * 64,
                "sizeBytes": 1,
                "acquiredAt": "2026-07-30T00:00:00Z",
                "repositoryMetadataDigest": "d" * 64,
                "storedOutsideRepository": True,
            }
        )
        ok, reason = match_installed(record, installedNevra="podman-5.8.4-1.fc44.x86_64")
        self.assertFalse(ok)
        self.assertIn("establishes nothing about the shipped binary", reason)


class CriticalNeedsAnIndependentReviewer(unittest.TestCase):
    """Adversarial case 15."""

    def test_critical_cannot_reach_a_non_blocking_class_without_a_review(self) -> None:
        with self.assertRaises(CveAnalysisError) as raised:
            parse_analysis(
                analysis(
                    conclusion="Present but unreachable",
                    reviewer="Bunny OS maintainer",
                    sourcePackageVersion="0.46.0",
                    activationAnalysis="no unit enabled",
                    privilegeAnalysis="unprivileged invocation only",
                    invocationGraph="no path from an entry point",
                    systemConfiguration="podman.socket absent",
                    sandboxOrMacControl="SELinux targeted enforcing",
                ),
                criticalAdvisories=["GHSA-5cgq-3rg8-m6cv"],
            )
        self.assertIn("completed independent security review", str(raised.exception))

    def test_a_reference_to_an_undelivered_review_is_not_enough(self) -> None:
        with self.assertRaises(CveAnalysisError):
            parse_analysis(
                analysis(
                    conclusion="Not present",
                    reviewer="External Reviewer",
                    independentReviewReference="review-security-001",
                    sourcePackageVersion="0.46.0",
                    buildConfiguration="recorded",
                    symbolOrSourceMapping="debuginfo mapping",
                    debuginfoReference="podman-debuginfo-5.8.4-1.fc44.x86_64",
                ),
                criticalAdvisories=["GHSA-5cgq-3rg8-m6cv"],
                completed_independent_reviews=(),
            )

    def test_the_reviewer_must_themselves_be_independent(self) -> None:
        with self.assertRaises(CveAnalysisError) as raised:
            parse_analysis(
                analysis(
                    conclusion="Not present",
                    reviewer="Someone Internal",
                    independentReviewReference="review-security-001",
                    sourcePackageVersion="0.46.0",
                    buildConfiguration="recorded",
                    symbolOrSourceMapping="debuginfo mapping",
                    debuginfoReference="podman-debuginfo-5.8.4-1.fc44.x86_64",
                ),
                criticalAdvisories=["GHSA-5cgq-3rg8-m6cv"],
                completed_independent_reviews=("review-security-001",),
                independentReviewers=("A Real External Reviewer",),
            )
        self.assertIn("cannot be self-reviewed", str(raised.exception))

    def test_a_delivered_review_by_an_external_reviewer_is_accepted(self) -> None:
        record = parse_analysis(
            analysis(
                conclusion="Not present",
                reviewer="A Real External Reviewer",
                independentReviewReference="review-security-001",
                sourcePackageVersion="0.46.0",
                buildConfiguration="recorded",
                symbolOrSourceMapping="debuginfo mapping",
                debuginfoReference="podman-debuginfo-5.8.4-1.fc44.x86_64",
            ),
            criticalAdvisories=["GHSA-5cgq-3rg8-m6cv"],
            completed_independent_reviews=("review-security-001",),
            independentReviewers=("A Real External Reviewer",),
        )
        self.assertFalse(record.blocking)


class ProofClassEvidenceRequirements(unittest.TestCase):
    def test_every_class_is_in_the_requirements_table(self) -> None:
        self.assertEqual(set(PROOF_CLASSES), set(CLASS_EVIDENCE_REQUIREMENTS))

    def test_unknown_and_reachable_and_blocking_both_block(self) -> None:
        for name in ("Unknown", "Reachable and blocking"):
            self.assertNotIn(name, NON_BLOCKING_CLASSES)

    def test_reachable_but_mitigated_still_blocks(self) -> None:
        # A mitigation is not a fix. It becomes non-blocking only through
        # explicit approver acceptance, which is not a property of the analysis.
        self.assertNotIn("Reachable but mitigated", NON_BLOCKING_CLASSES)
        record = parse_analysis(
            analysis(
                conclusion="Reachable but mitigated",
                reviewer="External Reviewer",
                sourcePackageVersion="0.46.0",
                exactMitigation="SELinux targeted policy confines a rootless invocation",
                bypassAnalysis="no bypass identified within the confined domain",
                residualImpact="denial of service within the caller's own session",
            )
        )
        self.assertTrue(record.blocking)

    def test_present_but_unreachable_needs_all_six_evidence_fields(self) -> None:
        for omitted in CLASS_EVIDENCE_REQUIREMENTS["Present but unreachable"]:
            fields = {
                "activationAnalysis": "no unit enabled",
                "privilegeAnalysis": "unprivileged invocation only",
                "invocationGraph": "no path from an entry point",
                "systemConfiguration": "podman.socket absent",
                "sandboxOrMacControl": "SELinux targeted enforcing",
                "reviewer": "External Reviewer",
            }
            fields.pop(omitted)
            with self.assertRaises(CveAnalysisError, msg=f"{omitted} was not required"):
                parse_analysis(
                    analysis(conclusion="Present but unreachable", sourcePackageVersion="0.46.0", **fields)
                )

    def test_an_unmappable_finding_retains_unknown(self) -> None:
        record = parse_analysis(analysis())
        self.assertEqual(record.proofClass, "Unknown")
        self.assertEqual(len(record.unknownMappingFields), len(MAPPING_FIELDS))
        self.assertTrue(record.blocking)


class DocumentCoverage(unittest.TestCase):
    def test_an_advisory_with_no_analysis_blocks(self) -> None:
        result = evaluate_document(
            {"schemaVersion": 1, "analyses": [analysis()]},
            expectedAdvisories=["GHSA-5cgq-3rg8-m6cv", "GHSA-89gr-r52h-f8rx"],
        )
        self.assertEqual(result["uncoveredAdvisories"], ["GHSA-89gr-r52h-f8rx"])
        self.assertTrue(result["blocked"])
        self.assertFalse(result["coverageComplete"])

    def test_a_duplicate_analysis_is_rejected(self) -> None:
        with self.assertRaises(CveAnalysisError):
            evaluate_document({"schemaVersion": 1, "analyses": [analysis(), analysis()]})

    def test_a_scanner_score_cannot_substitute_for_a_disposition(self) -> None:
        # There is no field in the model that accepts a numeric score, and the
        # summary reports per-advisory classes rather than a count.
        result = evaluate_document({"schemaVersion": 1, "analyses": [analysis()]})
        self.assertNotIn("score", json.dumps(result).casefold())
        self.assertIn("byProofClass", result)


class CommittedFindingsAreWellFormed(unittest.TestCase):
    """The 24 generated records must validate against the model that made them."""

    def setUp(self) -> None:
        index_path = FINDINGS / "index.json"
        if not index_path.is_file():
            self.skipTest("run scripts/reachability.py generate-findings first")
        self.index = json.loads(index_path.read_text(encoding="utf-8"))

    def test_every_advisory_has_a_record_that_parses(self) -> None:
        for advisory in self.index["advisories"]:
            path = FINDINGS / f"{advisory}.json"
            self.assertTrue(path.is_file(), f"{advisory} has no record")
            record = json.loads(path.read_text(encoding="utf-8"))
            parsed = parse_analysis(record)
            self.assertEqual(parsed.advisoryId, advisory)

    def test_every_committed_record_concludes_unknown_and_blocks(self) -> None:
        for advisory in self.index["advisories"]:
            record = json.loads((FINDINGS / f"{advisory}.json").read_text(encoding="utf-8"))
            parsed = parse_analysis(record)
            self.assertEqual(parsed.proofClass, "Unknown", advisory)
            self.assertTrue(parsed.blocking, advisory)

    def test_no_committed_record_invents_a_vulnerable_function(self) -> None:
        for advisory in self.index["advisories"]:
            record = json.loads((FINDINGS / f"{advisory}.json").read_text(encoding="utf-8"))
            self.assertEqual(record["vulnerableFunctionOrSubsystem"], UNKNOWN, advisory)
            self.assertEqual(record["elfBuildId"], UNKNOWN, advisory)
            self.assertEqual(record["strippedState"], UNKNOWN, advisory)

    def test_every_record_carries_all_required_fields(self) -> None:
        for advisory in self.index["advisories"]:
            record = json.loads((FINDINGS / f"{advisory}.json").read_text(encoding="utf-8"))
            missing = [name for name in ANALYSIS_FIELDS if name not in record]
            self.assertEqual(missing, [], f"{advisory} missing {missing}")


class AcquisitionTrust(unittest.TestCase):
    def test_a_third_party_host_is_refused(self) -> None:
        with self.assertRaises(AcquisitionError) as raised:
            parse_acquisition(
                {
                    "kind": "debuginfo-rpm",
                    "nevra": "podman-debuginfo-5.8.4-1.fc44.x86_64",
                    "repository": "somewhere",
                    "url": "https://rpms.example.invalid/podman-debuginfo.rpm",
                    "sha256": "e" * 64,
                    "sizeBytes": 1,
                    "acquiredAt": "2026-07-30T00:00:00Z",
                    "repositoryMetadataDigest": "f" * 64,
                    "storedOutsideRepository": True,
                }
            )
        self.assertIn("not Fedora infrastructure", str(raised.exception))

    def test_an_rpm_committed_to_the_repository_is_refused(self) -> None:
        with self.assertRaises(AcquisitionError) as raised:
            parse_acquisition(
                {
                    "kind": "source-rpm",
                    "nevra": "podman-5.8.4-1.fc44.src",
                    "repository": "fedora-source",
                    "url": "https://dl.fedoraproject.org/pub/fedora/linux/podman.src.rpm",
                    "sha256": "1" * 64,
                    "sizeBytes": 1,
                    "acquiredAt": "2026-07-30T00:00:00Z",
                    "repositoryMetadataDigest": "2" * 64,
                    "storedOutsideRepository": False,
                }
            )
        self.assertIn("storedOutsideRepository must be true", str(raised.exception))

    def test_repository_metadata_must_be_recorded(self) -> None:
        with self.assertRaises(AcquisitionError):
            parse_acquisition(
                {
                    "kind": "binary-rpm",
                    "nevra": "podman-5.8.4-1.fc44.x86_64",
                    "repository": "fedora",
                    "url": "https://dl.fedoraproject.org/pub/podman.rpm",
                    "sha256": "3" * 64,
                    "sizeBytes": 1,
                    "acquiredAt": "2026-07-30T00:00:00Z",
                    "repositoryMetadataDigest": "not-a-digest",
                    "storedOutsideRepository": True,
                }
            )

    def test_an_approximate_package_name_is_refused(self) -> None:
        with self.assertRaises(AcquisitionError):
            parse_nevra("podman")

    def test_no_rpm_is_committed_to_the_repository(self) -> None:
        # Tracked, not merely present. A scanner tarball downloaded into an
        # ignored scratch directory is not a committed RPM, and testing the
        # filesystem rather than the index would fail on it.
        import subprocess

        try:
            result = subprocess.run(
                ["git", "ls-files", "-z", "*.rpm"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):  # pragma: no cover
            self.skipTest("git is unavailable")
        tracked = [name for name in result.stdout.split("\0") if name]
        self.assertEqual(tracked, [], f"RPMs tracked in git: {tracked}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

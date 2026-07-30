"""Independent-builder reproducibility and the four separate claims.

One of the fourteen mandated adversarial cases lives here: same-host builds
marked independent. It is the failure this repository has actually made before —
two runs on one builder recorded as reproducibility evidence — so it gets the
most coverage.
"""

from __future__ import annotations

import unittest

from release.reproducibility import (
    INDEPENDENCE_DIMENSIONS,
    REPRODUCIBILITY_CLAIMS,
    STRONG_DIMENSIONS,
    ReproducibilityError,
    compare_builds,
    independent_dimensions,
    parse_builder,
    shared_inputs,
    summarise_claims,
)

COMMIT = "c" * 40
BASE = "quay.io/fedora/fedora-bootc:44@sha256:" + "f" * 64


def builder(**overrides):
    base = {
        "builderId": "builder-a",
        "machineId": "machine-1",
        "virtualisationInstance": "wsl:FedoraLinux-44",
        "cloudRunner": None,
        "administrator": "operator-1",
        "environmentId": "env-a",
        "operatingSystem": "fedora-44 6.18.33",
        "toolchain": {"podman": "5.8.4", "image-builder": "76.0.0"},
        "workspace": "/var/tmp/bunny-builder-a",
        "sourceCommit": COMMIT,
        "baseImageDigest": BASE,
    }
    base.update(overrides)
    return base


def compare(first, second, claim, *, archives=("d1", "d1"), files=None, sboms=("s1", "s1"), packages=None):
    files = files if files is not None else ({"a": "1"}, {"a": "1"})
    packages = packages if packages is not None else (["p@1"], ["p@1"])
    return compare_builds(
        parse_builder(first),
        parse_builder(second),
        claim=claim,
        archiveDigests=archives,
        fileDigests=files,
        sbomDigests=sboms,
        packageManifests=packages,
    )


class ClaimStructureTests(unittest.TestCase):
    def test_four_claims_are_distinguished(self):
        self.assertEqual(
            set(REPRODUCIBILITY_CLAIMS),
            {"same-host-repeatability", "independent-builder", "filesystem-content", "archive-byte"},
        )

    def test_strong_dimensions_are_a_subset_of_all_dimensions(self):
        self.assertTrue(set(STRONG_DIMENSIONS).issubset(set(INDEPENDENCE_DIMENSIONS)))

    def test_unknown_claim_is_refused(self):
        with self.assertRaises(ReproducibilityError):
            compare(builder(), builder(builderId="b"), "totally-reproducible")

    def test_builder_record_requires_a_toolchain(self):
        payload = builder()
        payload["toolchain"] = {}
        with self.assertRaises(ReproducibilityError):
            parse_builder(payload)


class IndependenceTests(unittest.TestCase):
    def test_identical_builders_differ_in_nothing(self):
        self.assertEqual(independent_dimensions(parse_builder(builder()), parse_builder(builder())), ())

    def test_differing_machine_is_detected(self):
        dimensions = independent_dimensions(
            parse_builder(builder()), parse_builder(builder(machineId="machine-2"))
        )
        self.assertIn("machineId", dimensions)

    # --- adversarial: same-host builds marked independent ---
    def test_two_runs_on_one_host_cannot_be_independent(self):
        result = compare(builder(), builder(builderId="builder-b"), "independent-builder")
        self.assertFalse(result.satisfied)
        self.assertTrue(any("differ in no meaningful dimension" in reason for reason in result.reasons))

    def test_two_workspaces_on_one_machine_cannot_be_independent(self):
        """Environment separation alone is not independence."""
        result = compare(
            builder(),
            builder(builderId="builder-b", environmentId="env-b", workspace="/var/tmp/bunny-builder-b"),
            "independent-builder",
        )
        self.assertFalse(result.satisfied)
        self.assertTrue(
            any("environment separation on one machine" in reason for reason in result.reasons),
            result.reasons,
        )

    def test_two_vms_on_one_machine_cannot_be_independent(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", virtualisationInstance="wsl:Second", environmentId="env-b"),
            "independent-builder",
        )
        self.assertFalse(result.satisfied)

    def test_a_different_machine_can_be_independent(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", machineId="machine-2", environmentId="env-b"),
            "independent-builder",
        )
        self.assertTrue(result.satisfied, result.reasons)

    def test_a_different_administrator_can_be_independent(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", administrator="operator-2"),
            "independent-builder",
        )
        self.assertTrue(result.satisfied, result.reasons)

    def test_a_cloud_runner_can_be_independent(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", cloudRunner="run-12345"),
            "independent-builder",
        )
        self.assertTrue(result.satisfied, result.reasons)

    def test_same_host_claim_accepts_environment_separation(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", environmentId="env-b"),
            "same-host-repeatability",
        )
        self.assertTrue(result.satisfied, result.reasons)

    def test_same_host_claim_rejects_a_genuinely_different_machine(self):
        result = compare(
            builder(),
            builder(builderId="builder-b", machineId="machine-2"),
            "same-host-repeatability",
        )
        self.assertFalse(result.satisfied)


class InputAgreementTests(unittest.TestCase):
    def test_differing_commit_is_reported(self):
        mismatch = shared_inputs(
            parse_builder(builder()), parse_builder(builder(sourceCommit="d" * 40))
        )
        self.assertIn("sourceCommit", mismatch)

    def test_differing_base_digest_fails_every_claim(self):
        result = compare(
            builder(),
            builder(builderId="b", machineId="machine-2", baseImageDigest="other"),
            "independent-builder",
        )
        self.assertFalse(result.satisfied)
        self.assertTrue(any("identical inputs" in reason for reason in result.reasons))

    def test_differing_toolchain_version_is_reported(self):
        second = builder(builderId="b", machineId="machine-2")
        second["toolchain"] = {"podman": "5.9.0", "image-builder": "76.0.0"}
        result = compare(builder(), second, "independent-builder")
        self.assertFalse(result.satisfied)
        self.assertTrue(any("toolchain.podman" in reason for reason in result.reasons))


class ComparisonLevelTests(unittest.TestCase):
    def test_archive_mismatch_fails_the_archive_claim(self):
        result = compare(
            builder(), builder(builderId="b", machineId="m2"), "archive-byte", archives=("d1", "d2")
        )
        self.assertFalse(result.satisfied)
        self.assertFalse(result.archiveDigestsMatch)

    def test_file_content_can_match_while_the_archive_differs(self):
        """The exact situation the archive-normalisation fix addressed."""
        result = compare(
            builder(),
            builder(builderId="b", machineId="m2"),
            "filesystem-content",
            archives=("d1", "d2"),
        )
        self.assertTrue(result.fileContentsMatch)
        self.assertTrue(result.satisfied, result.reasons)

    def test_differing_files_are_listed(self):
        result = compare(
            builder(),
            builder(builderId="b", machineId="m2"),
            "independent-builder",
            files=({"a": "1", "b": "2"}, {"a": "1", "b": "3"}),
        )
        self.assertEqual(result.differingFiles, ("b",))
        self.assertFalse(result.satisfied)

    def test_sbom_file_digest_mismatch_alone_does_not_fail(self):
        """Syft stamps a fresh UUID, a timestamp and the input path into every
        document, so two scans of byte-identical archives never produce
        identical bytes. Measured directly: 6076 of 6077 entries matched, and
        the odd one was the document-root entry named after the file path."""
        result = compare(
            builder(), builder(builderId="b", machineId="m2"), "independent-builder", sboms=("s1", "s2")
        )
        self.assertFalse(result.sbomMatch)
        self.assertTrue(result.packageManifestMatch)
        self.assertTrue(result.satisfied, result.reasons)

    def test_sbom_and_manifest_both_differing_fails(self):
        result = compare(
            builder(),
            builder(builderId="b", machineId="m2"),
            "independent-builder",
            sboms=("s1", "s2"),
            packages=(["p@1"], ["p@2"]),
        )
        self.assertFalse(result.satisfied)
        self.assertTrue(any("package manifests differ" in reason for reason in result.reasons))

    def test_package_manifest_mismatch_fails_any_claim(self):
        result = compare(
            builder(),
            builder(builderId="b", machineId="m2"),
            "independent-builder",
            packages=(["p@1"], ["p@2"]),
        )
        self.assertFalse(result.satisfied)

    def test_package_manifest_order_does_not_matter(self):
        result = compare(
            builder(),
            builder(builderId="b", machineId="m2"),
            "independent-builder",
            packages=(["b@1", "a@1"], ["a@1", "b@1"]),
        )
        self.assertTrue(result.packageManifestMatch)


class SummaryTests(unittest.TestCase):
    def test_only_independent_builder_meets_the_production_requirement(self):
        same_host = compare(builder(), builder(builderId="b", environmentId="env-b"), "same-host-repeatability")
        summary = summarise_claims([same_host])
        self.assertTrue(summary["claims"]["same-host-repeatability"])
        self.assertFalse(summary["productionRequirementMet"])

    def test_independent_builder_pass_meets_the_production_requirement(self):
        independent = compare(builder(), builder(builderId="b", machineId="m2"), "independent-builder")
        summary = summarise_claims([independent])
        self.assertTrue(summary["productionRequirementMet"])

    def test_failing_on_independence_still_establishes_the_content_claims(self):
        """Content claims are measurements, not judgements about independence.

        This is the repository's actual position: two isolated workspaces
        produced byte-identical archives, which establishes archive-byte and
        filesystem-content reproducibility while establishing nothing about
        independent builders.
        """
        failed = compare(builder(), builder(builderId="b"), "independent-builder")
        summary = summarise_claims([failed])
        self.assertFalse(summary["claims"]["independent-builder"])
        self.assertFalse(summary["productionRequirementMet"])
        self.assertTrue(summary["claims"]["archive-byte"])
        self.assertTrue(summary["claims"]["filesystem-content"])

    def test_mismatched_inputs_establish_nothing(self):
        """Comparing builds of different commits proves nothing about either."""
        failed = compare(
            builder(),
            builder(builderId="b", sourceCommit="d" * 40),
            "independent-builder",
        )
        summary = summarise_claims([failed])
        self.assertFalse(any(summary["claims"].values()))

    def test_differing_content_does_not_establish_the_content_claims(self):
        failed = compare(
            builder(),
            builder(builderId="b"),
            "independent-builder",
            archives=("d1", "d2"),
            files=({"a": "1"}, {"a": "2"}),
        )
        summary = summarise_claims([failed])
        self.assertFalse(summary["claims"]["archive-byte"])
        self.assertFalse(summary["claims"]["filesystem-content"])


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builder independence, artifact normalisation, and the seventeen dimensions.

The mandated adversarial cases exercised here:

* the same physical host represented as two builders (case 1)
* the same CI run represented twice (case 2)
* a mutable base tag instead of a digest (case 3)
* a mismatched source commit (case 4)
"""

from __future__ import annotations

import datetime as _datetime
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from release.builders import (
    ACCEPTED_PAIRINGS,
    BUILDER_TYPES,
    INSUFFICIENT_FOR_INDEPENDENCE,
    WEAK_DIMENSIONS,
    BuilderError,
    evaluate_builder_set,
    evaluate_independence,
    parse_builder_record,
)
from release.comparison import (
    COMPARISON_DIMENSIONS,
    DIMENSION_KINDS,
    OUTCOMES,
    ComparisonError,
    compare_dimension,
    evaluate_comparison,
)
from release.normalisation import (
    NORMALISABLE_PROPERTIES,
    PROTECTED_PROPERTIES,
    NormalisationError,
    assert_normalisation_scope,
    classify_digest_pair,
    file_digest,
    member_digests,
    normalise_archive,
)
from release.provenance import (
    ProvenanceError,
    parse_provenance,
    verify_provenance,
)

ROOT = Path(__file__).resolve().parents[2]

COMMIT = "80df25b09f6578276d18c8a82f15c47dd8959740"
OTHER_COMMIT = "79bb99ddb39d8a5dbc279629f43b23346fb0e5e8"
BASE = "quay.io/fedora/fedora-bootc:44@sha256:" + "f" * 64


def builder(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schemaVersion": 2,
        "builderId": "local-fedora",
        "environmentId": "e" * 32,
        "sourceCommit": COMMIT,
        "baseImageDigest": BASE,
        "architecture": "x86_64",
        "operatingSystem": "fedora-44",
        "kernelVersion": "6.18.33.2",
        "builderType": "local-machine",
        "administratorBoundary": "a" * 32,
        "buildStartedAt": "2026-07-30T01:00:00Z",
        "buildCompletedAt": "2026-07-30T02:00:00Z",
        "toolchain": {"podman": "5.8.4", "syft": "1.50.0"},
    }
    record.update(overrides)
    return record


def hosted(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "builderId": "hosted-ci-1",
        "builderType": "hosted-ci",
        "administratorBoundary": "b" * 32,
        "workflowRunId": "1234567890.1",
        "environmentId": "c" * 32,
        "kernelVersion": "6.11.0-1018-azure",
        "operatingSystem": "ubuntu-24.04",
    }
    defaults.update(overrides)
    return builder(**defaults)


class SameHostIsNotTwoBuilders(unittest.TestCase):
    """Adversarial case 1. The mistake this repository already made once."""

    def test_two_workspaces_on_one_host_are_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder(builderId="builder-a", environmentId="1" * 32)),
            parse_builder_record(builder(builderId="builder-b", environmentId="2" * 32)),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(
            any("share administratorBoundary" in reason for reason in verdict.reasons),
            verdict.reasons,
        )

    def test_the_refusal_names_the_weak_dimension(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder(builderId="builder-a", environmentId="1" * 32)),
            parse_builder_record(builder(builderId="builder-b", environmentId="2" * 32)),
        )
        joined = " ".join(verdict.reasons)
        self.assertIn("environmentId", joined)
        self.assertIn("environment separation on one host", joined)

    def test_none_of_the_weak_dimensions_confers_independence(self) -> None:
        for dimension, extra in (
            ("environmentId", {"environmentId": "9" * 32}),
            (
                "build window",
                {"buildStartedAt": "2026-07-30T05:00:00Z", "buildCompletedAt": "2026-07-30T06:00:00Z"},
            ),
        ):
            verdict = evaluate_independence(
                parse_builder_record(builder(builderId="a")),
                parse_builder_record(builder(builderId="b", **extra)),
            )
            self.assertFalse(verdict.independent, f"{dimension} conferred independence")

    def test_two_containers_under_one_daemon_are_refused(self) -> None:
        # Same administrator, different environment: a container is a workspace.
        verdict = evaluate_independence(
            parse_builder_record(builder(builderId="container-a", environmentId="1" * 32)),
            parse_builder_record(builder(builderId="container-b", environmentId="2" * 32)),
        )
        self.assertFalse(verdict.independent)

    def test_a_copied_record_is_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder(builderId="builder-a")),
            parse_builder_record(builder(builderId="builder-b")),
        )
        self.assertTrue(
            any("copied builder record" in reason for reason in verdict.reasons), verdict.reasons
        )

    def test_the_same_builder_id_twice_is_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder()), parse_builder_record(builder())
        )
        self.assertTrue(any("same builderId" in reason for reason in verdict.reasons))

    def test_weak_dimensions_are_named_in_the_model(self) -> None:
        self.assertIn("environmentId", WEAK_DIMENSIONS)

    def test_the_schema_has_no_workspace_field_to_differ_in(self) -> None:
        # Schema 1 carried a workspace path and it was the only dimension the two
        # local builders differed in. Schema 2 has nowhere to put one.
        record = parse_builder_record(builder())
        self.assertNotIn("workspace", record.as_dict())
        self.assertIn("a different workspace identifier", INSUFFICIENT_FOR_INDEPENDENCE)
        self.assertIn("two containers under the same daemon", INSUFFICIENT_FOR_INDEPENDENCE)


class SameRunTwice(unittest.TestCase):
    """Adversarial case 2."""

    def test_two_records_citing_one_workflow_run_are_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(hosted(builderId="job-build")),
            parse_builder_record(
                hosted(builderId="job-verify", administratorBoundary="z" * 32, environmentId="d" * 32)
            ),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(
            any("workflow run 1234567890.1" in reason for reason in verdict.reasons), verdict.reasons
        )

    def test_two_consecutive_builds_by_one_runner_are_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(
                hosted(builderId="run-1", workflowRunId="1.1", cloudRunner="runner-7")
            ),
            parse_builder_record(
                hosted(
                    builderId="run-2",
                    workflowRunId="2.1",
                    cloudRunner="runner-7",
                    administratorBoundary="y" * 32,
                    builderType="self-hosted-ci",
                )
            ),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(any("runner runner-7" in reason for reason in verdict.reasons), verdict.reasons)

    def test_a_hosted_record_without_a_run_id_is_refused_at_parse_time(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(hosted(workflowRunId=None))
        self.assertIn("must record workflowRunId", str(raised.exception))

    def test_a_reused_run_is_refused_by_the_provenance_verifier(self) -> None:
        record = parse_provenance(provenance())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bunny-os.oci.tar").write_bytes(b"payload")
            result = verify_provenance(
                record,
                artifactRoot=root,
                expectedCommit=COMMIT,
                expectedBaseDigest=BASE,
                verificationEnvironmentId="verifier",
                builderEnvironmentId="1234567890.1",
                now=_datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc),
                consumedRunIds=["1234567890.1"],
            )
        self.assertIn("run-not-reused", result["failingChecks"])


class MutableBaseTag(unittest.TestCase):
    """Adversarial case 3."""

    def test_a_builder_record_naming_a_tag_is_refused(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(builder(baseImageDigest="quay.io/fedora/fedora-bootc:44"))
        self.assertIn("is not digest-pinned", str(raised.exception))

    def test_a_truncated_digest_is_refused(self) -> None:
        with self.assertRaises(BuilderError):
            parse_builder_record(
                builder(baseImageDigest="quay.io/fedora/fedora-bootc:44@sha256:fb71f099")
            )

    def test_provenance_naming_a_tag_is_refused(self) -> None:
        with self.assertRaises(ProvenanceError) as raised:
            parse_provenance(provenance(baseImageDigest="quay.io/fedora/fedora-bootc:44"))
        self.assertIn("not digest-pinned", str(raised.exception))

    def test_the_workflow_refuses_a_mutable_tag(self) -> None:
        workflow = (ROOT / ".github/workflows/independent-builder.yml").read_text(encoding="utf-8")
        self.assertIn("@sha256:[0-9a-f]{64}$", workflow)
        self.assertIn("base_image must be digest-pinned", workflow)


class MismatchedSourceCommit(unittest.TestCase):
    """Adversarial case 4."""

    def test_builders_of_different_commits_are_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder()),
            parse_builder_record(hosted(sourceCommit=OTHER_COMMIT)),
        )
        self.assertFalse(verdict.independent)
        self.assertIn("sourceCommit", verdict.mismatchedInputs)
        self.assertTrue(
            any("did not build the same thing" in reason for reason in verdict.reasons), verdict.reasons
        )

    def test_a_short_commit_is_refused_at_parse_time(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(builder(sourceCommit="80df25b"))
        self.assertIn("full 40-character SHA", str(raised.exception))

    def test_a_branch_name_is_refused(self) -> None:
        with self.assertRaises(BuilderError):
            parse_builder_record(builder(sourceCommit="feature/qualification-evidence-closure"))

    def test_provenance_from_another_commit_fails_verification(self) -> None:
        record = parse_provenance(provenance(sourceCommit=OTHER_COMMIT))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bunny-os.oci.tar").write_bytes(b"payload")
            result = verify_provenance(
                record,
                artifactRoot=root,
                expectedCommit=COMMIT,
                expectedBaseDigest=BASE,
                verificationEnvironmentId="verifier",
                builderEnvironmentId="run",
                now=_datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc),
            )
        self.assertIn("source-commit", result["failingChecks"])

    def test_a_differing_toolchain_version_is_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder()),
            parse_builder_record(hosted(toolchain={"podman": "5.8.4", "syft": "1.49.0"})),
        )
        self.assertFalse(verdict.independent)
        self.assertIn("toolchain.syft", verdict.mismatchedInputs)


class RequiredFieldsAndBoundaries(unittest.TestCase):
    def test_a_missing_administrator_boundary_is_refused(self) -> None:
        record = builder()
        del record["administratorBoundary"]
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(record)
        self.assertIn("administratorBoundary", str(raised.exception))

    def test_a_missing_source_commit_is_refused(self) -> None:
        record = builder()
        del record["sourceCommit"]
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(record)
        self.assertIn("sourceCommit", str(raised.exception))

    def test_completion_before_start_is_refused(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(
                builder(buildStartedAt="2026-07-30T02:00:00Z", buildCompletedAt="2026-07-30T01:00:00Z")
            )
        self.assertIn("precedes", str(raised.exception))

    def test_a_cloud_vm_without_a_provider_is_refused(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(builder(builderType="cloud-vm"))
        self.assertIn("must record cloudProvider", str(raised.exception))

    def test_an_unknown_builder_type_is_refused(self) -> None:
        with self.assertRaises(BuilderError):
            parse_builder_record(builder(builderType="laptop"))

    def test_a_schema_one_record_is_refused(self) -> None:
        with self.assertRaises(BuilderError) as raised:
            parse_builder_record(builder(schemaVersion=1))
        self.assertIn("schemaVersion must be 2", str(raised.exception))


class AcceptedPairings(unittest.TestCase):
    def test_local_plus_hosted_ci_is_accepted(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(builder()), parse_builder_record(hosted())
        )
        self.assertTrue(verdict.independent, verdict.reasons)
        self.assertIn("hosted CI", verdict.pairing or "")

    def test_two_cloud_vms_at_one_provider_are_refused(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(
                builder(builderId="vm-a", builderType="cloud-vm", cloudProvider="acme")
            ),
            parse_builder_record(
                builder(
                    builderId="vm-b",
                    builderType="cloud-vm",
                    cloudProvider="acme",
                    administratorBoundary="q" * 32,
                    environmentId="7" * 32,
                )
            ),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(any("two independent cloud providers" in r for r in verdict.reasons))

    def test_two_cloud_vms_at_different_providers_are_accepted(self) -> None:
        verdict = evaluate_independence(
            parse_builder_record(
                builder(builderId="vm-a", builderType="cloud-vm", cloudProvider="acme")
            ),
            parse_builder_record(
                builder(
                    builderId="vm-b",
                    builderType="cloud-vm",
                    cloudProvider="globex",
                    administratorBoundary="q" * 32,
                    environmentId="7" * 32,
                    kernelVersion="6.12.0",
                )
            ),
        )
        self.assertTrue(verdict.independent, verdict.reasons)

    def test_two_local_machines_are_not_an_accepted_pairing(self) -> None:
        # Two local machines under two administrators is a *physical-builder*
        # pairing; "local-machine" is an undifferentiated desktop and the model
        # will not infer a boundary from two of them.
        verdict = evaluate_independence(
            parse_builder_record(builder(builderId="a")),
            parse_builder_record(
                builder(builderId="b", administratorBoundary="q" * 32, environmentId="7" * 32)
            ),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(any("not an accepted independence pairing" in r for r in verdict.reasons))

    def test_every_accepted_pairing_uses_known_builder_types(self) -> None:
        for types, _, _ in ACCEPTED_PAIRINGS:
            for name in types:
                self.assertIn(name, BUILDER_TYPES)

    def test_the_committed_builder_set_records_no_independent_pair(self) -> None:
        document = json.loads((ROOT / "operations/data/builders.json").read_text(encoding="utf-8"))
        result = evaluate_builder_set(document)
        self.assertFalse(result["requirementMet"])
        self.assertEqual(result["result"], "BLOCKED")


class Normalisation(unittest.TestCase):
    def _archive(self, path: Path, *, mtime: int, order: list[str], uid: int) -> None:
        with tarfile.open(path, "w") as archive:
            for name in order:
                payload = name.encode("utf-8") * 4
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mtime = mtime
                info.uid = uid
                info.gid = uid
                info.uname = f"user{uid}"
                info.gname = f"group{uid}"
                archive.addfile(info, io.BytesIO(payload))

    def test_normalisation_removes_non_semantic_variance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left.tar", root / "right.tar"
            self._archive(left, mtime=1000, order=["b", "a", "c"], uid=1000)
            self._archive(right, mtime=2000, order=["c", "a", "b"], uid=0)
            self.assertNotEqual(file_digest(left), file_digest(right))

            first = normalise_archive(left, root / "left.norm.tar")
            second = normalise_archive(right, root / "right.norm.tar")
            self.assertNotEqual(first.rawDigest, second.rawDigest)
            self.assertEqual(first.normalisedDigest, second.normalisedDigest)

    def test_normalisation_preserves_member_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "a.tar"
            self._archive(source, mtime=1000, order=["x", "y"], uid=1000)
            before = member_digests(source)
            normalise_archive(source, root / "a.norm.tar")
            after = member_digests(root / "a.norm.tar")
            self.assertEqual(before, after)

    def test_normalisation_detects_a_content_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "l.tar", root / "r.tar"
            self._archive(left, mtime=1000, order=["a"], uid=0)
            with tarfile.open(right, "w") as archive:
                payload = b"different"
                info = tarfile.TarInfo("a")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            first = normalise_archive(left, root / "l.norm.tar")
            second = normalise_archive(right, root / "r.norm.tar")
            self.assertNotEqual(first.normalisedDigest, second.normalisedDigest)

    def test_a_gzipped_archive_normalises_its_gzip_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, mtime in (("l.tgz", 1000), ("r.tgz", 5000)):
                raw = io.BytesIO()
                with tarfile.open(fileobj=raw, mode="w") as archive:
                    payload = b"same"
                    info = tarfile.TarInfo("a")
                    info.size = len(payload)
                    info.mtime = mtime
                    archive.addfile(info, io.BytesIO(payload))
                (root / name).write_bytes(gzip.compress(raw.getvalue(), mtime=mtime))
            first = normalise_archive(root / "l.tgz", root / "l.norm.tgz")
            second = normalise_archive(root / "r.tgz", root / "r.norm.tgz")
            self.assertTrue(first.gzipped)
            self.assertEqual(first.normalisedDigest, second.normalisedDigest)

    def test_normalising_a_semantic_property_is_refused(self) -> None:
        for name in PROTECTED_PROPERTIES:
            with self.assertRaises(NormalisationError, msg=name):
                assert_normalisation_scope([*NORMALISABLE_PROPERTIES, name])

    def test_overwriting_the_source_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a.tar"
            self._archive(source, mtime=0, order=["a"], uid=0)
            with self.assertRaises(NormalisationError) as raised:
                normalise_archive(source, source)
            self.assertIn("separate path", str(raised.exception))

    def test_an_unexplained_raw_difference_is_inconclusive(self) -> None:
        result = classify_digest_pair(
            rawDigests=("a" * 64, "b" * 64),
            normalisedDigests=("c" * 64, "c" * 64),
            memberDigests=({"x": "1"}, {"x": "1"}),
        )
        self.assertEqual(result["outcome"], "INCONCLUSIVE")
        self.assertFalse(result["satisfiesProductionGate"])

    def test_an_explained_raw_difference_is_archive_variance(self) -> None:
        result = classify_digest_pair(
            rawDigests=("a" * 64, "b" * 64),
            normalisedDigests=("c" * 64, "c" * 64),
            memberDigests=({"x": "1"}, {"x": "1"}),
            rawVarianceExplanation="podman save stamps entry mtimes with wall-clock time",
        )
        self.assertEqual(result["outcome"], "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE")
        self.assertFalse(result["satisfiesProductionGate"])

    def test_a_content_difference_is_non_reproducible(self) -> None:
        result = classify_digest_pair(
            rawDigests=("a" * 64, "a" * 64),
            normalisedDigests=("c" * 64, "c" * 64),
            memberDigests=({"x": "1"}, {"x": "2"}),
        )
        self.assertEqual(result["outcome"], "NON_REPRODUCIBLE")


class SeventeenDimensions(unittest.TestCase):
    def _dimensions(self, **populated: object) -> dict[str, object]:
        dimensions = {name: {"first": None, "second": None} for name, _, _ in COMPARISON_DIMENSIONS}
        dimensions.update(populated)  # type: ignore[arg-type]
        return dimensions

    def _all_matching(self) -> dict[str, object]:
        return {
            name: {"first": f"value-{name}", "second": f"value-{name}"}
            for name, _, _ in COMPARISON_DIMENSIONS
        }

    def test_there_are_seventeen_dimensions(self) -> None:
        self.assertEqual(len(COMPARISON_DIMENSIONS), 17)
        self.assertEqual(len(DIMENSION_KINDS), 17)

    def test_an_uncollected_dimension_makes_the_result_inconclusive(self) -> None:
        dimensions = self._all_matching()
        dimensions["selinuxLabels"] = {"first": None, "second": None}
        report = evaluate_comparison(
            {"dimensions": dimensions, "builders": ["a", "b"]}, independent=True
        )
        self.assertEqual(report.outcome, "INCONCLUSIVE")
        self.assertFalse(report.satisfiesProductionGate)

    def test_all_matching_and_independent_is_reproducible(self) -> None:
        report = evaluate_comparison(
            {"dimensions": self._all_matching(), "builders": ["a", "b"]}, independent=True
        )
        self.assertEqual(report.outcome, "REPRODUCIBLE")
        self.assertTrue(report.satisfiesProductionGate)

    def test_all_matching_but_not_independent_does_not_satisfy_the_gate(self) -> None:
        report = evaluate_comparison(
            {"dimensions": self._all_matching(), "builders": ["a", "b"]},
            independent=False,
            independenceReasons=("two workspaces on one host",),
        )
        self.assertEqual(report.outcome, "REPRODUCIBLE")
        self.assertFalse(report.satisfiesProductionGate)
        self.assertTrue(any("same-host repeatability" in r for r in report.reasons))

    def test_a_semantic_difference_is_non_reproducible(self) -> None:
        dimensions = self._all_matching()
        dimensions["permissions"] = {"first": {"/usr/bin/x": "0755"}, "second": {"/usr/bin/x": "4755"}}
        report = evaluate_comparison(
            {"dimensions": dimensions, "builders": ["a", "b"]}, independent=True
        )
        self.assertEqual(report.outcome, "NON_REPRODUCIBLE")

    def test_a_raw_difference_alone_needs_an_explanation(self) -> None:
        dimensions = self._all_matching()
        dimensions["rawArchive"] = {"first": "a" * 64, "second": "b" * 64}
        blocked = evaluate_comparison(
            {"dimensions": dimensions, "builders": ["a", "b"]}, independent=True
        )
        self.assertEqual(blocked.outcome, "INCONCLUSIVE")
        explained = evaluate_comparison(
            {
                "dimensions": dimensions,
                "builders": ["a", "b"],
                "rawVarianceExplanation": "podman save stamps wall-clock mtimes",
            },
            independent=True,
        )
        self.assertEqual(explained.outcome, "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE")
        self.assertFalse(explained.satisfiesProductionGate)

    def test_only_reproducible_satisfies_the_gate(self) -> None:
        self.assertEqual(
            set(OUTCOMES),
            {
                "REPRODUCIBLE",
                "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE",
                "NON_REPRODUCIBLE",
                "INCONCLUSIVE",
            },
        )

    def test_an_unknown_dimension_is_rejected(self) -> None:
        with self.assertRaises(ComparisonError):
            evaluate_comparison(
                {"dimensions": {"vibes": {"first": 1, "second": 1}}}, independent=True
            )

    def test_a_dimension_collected_from_one_builder_only_is_not_collected(self) -> None:
        result = compare_dimension("kernel", {"first": "7.1.5"})
        self.assertEqual(result.state, "NOT_COLLECTED")
        self.assertIn("second", result.detail)

    def test_the_committed_comparison_does_not_satisfy_the_production_gate(self) -> None:
        # This asserted `INCONCLUSIVE` and had to change when the comparison was
        # first run against two real builders — it became `NON_REPRODUCIBLE`.
        # Pinning one measured outcome made the test a record of what happened
        # to be true rather than of what must be. The invariant is that the
        # committed comparison never claims more than it measured: only
        # REPRODUCIBLE between independent builders satisfies the gate, and this
        # comparison is not that.
        document = json.loads(
            (ROOT / "operations/data/build-comparison.json").read_text(encoding="utf-8")
        )
        report = evaluate_comparison(document, independent=False)
        self.assertIn(report.outcome, OUTCOMES)
        self.assertNotEqual(report.outcome, "REPRODUCIBLE")
        self.assertFalse(report.satisfiesProductionGate)

    def test_no_committed_comparison_can_pass_without_independent_builders(self) -> None:
        document = json.loads(
            (ROOT / "operations/data/build-comparison.json").read_text(encoding="utf-8")
        )
        self.assertFalse(
            evaluate_comparison(document, independent=False).satisfiesProductionGate
        )


def provenance(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schemaVersion": 1,
        "repository": "COMRADEART/bunny-os",
        "workflow": ".github/workflows/independent-builder.yml",
        "workflowRunId": "1234567890.1",
        "workflowRunAttempt": 1,
        "runnerImage": "ubuntu24",
        "runnerArchitecture": "X64",
        "kernelVersion": "6.11.0-1018-azure",
        "containerRuntime": "podman version 5.8.4",
        "imageBuilderVersion": "absent",
        "sourceCommit": COMMIT,
        "baseImageDigest": BASE,
        "generatedAt": "2026-07-30T02:00:00Z",
        "expiresAt": "2026-10-28T02:00:00Z",
        "cacheDisabled": True,
        "artifacts": {"bunny-os.oci.tar": file_digest_of(b"payload")},
        "dependencyLockHashes": {},
    }
    record.update(overrides)
    return record


def file_digest_of(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


class ProvenanceVerification(unittest.TestCase):
    def _verify(self, record_overrides: dict[str, object], **kwargs: object) -> dict[str, object]:
        record = parse_provenance(provenance(**record_overrides))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bunny-os.oci.tar").write_bytes(b"payload")
            defaults: dict[str, object] = {
                "artifactRoot": root,
                "expectedCommit": COMMIT,
                "expectedBaseDigest": BASE,
                "verificationEnvironmentId": "verifier",
                "builderEnvironmentId": "1234567890.1",
                "now": _datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc),
            }
            defaults.update(kwargs)
            return verify_provenance(record, **defaults)  # type: ignore[arg-type]

    def test_a_well_formed_bundle_is_accepted(self) -> None:
        result = self._verify({})
        self.assertTrue(result["accepted"], result["checks"])

    def test_a_substituted_artifact_fails_the_checksum(self) -> None:
        result = self._verify({"artifacts": {"bunny-os.oci.tar": "0" * 64}})
        self.assertIn("artifact-checksums", result["failingChecks"])

    def test_an_absent_artifact_fails(self) -> None:
        result = self._verify({"artifacts": {"missing.tar": "0" * 64}})
        self.assertIn("artifacts-present", result["failingChecks"])

    def test_expired_provenance_is_rejected(self) -> None:
        result = self._verify(
            {"expiresAt": "2026-07-01T00:00:00Z"},
        )
        self.assertIn("not-expired", result["failingChecks"])

    def test_provenance_without_an_expiry_is_rejected(self) -> None:
        record = provenance()
        del record["expiresAt"]
        result = self._verify({"expiresAt": None} if False else {})
        self.assertTrue(result["accepted"])
        # An absent expiry is a distinct failure from an expired one.
        parsed = parse_provenance({**record})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bunny-os.oci.tar").write_bytes(b"payload")
            without = verify_provenance(
                parsed,
                artifactRoot=root,
                expectedCommit=COMMIT,
                expectedBaseDigest=BASE,
                verificationEnvironmentId="verifier",
                builderEnvironmentId="run",
                now=_datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc),
            )
        self.assertIn("not-expired", without["failingChecks"])

    def test_verifying_in_the_building_environment_is_rejected(self) -> None:
        result = self._verify({}, verificationEnvironmentId="1234567890.1")
        self.assertIn("separate-verification-environment", result["failingChecks"])

    def test_another_repository_is_rejected(self) -> None:
        result = self._verify({"repository": "someone-else/bunny-os"})
        self.assertIn("repository", result["failingChecks"])

    def test_a_warm_cache_is_reported(self) -> None:
        result = self._verify({"cacheDisabled": False})
        self.assertIn("mutable-cache-disabled", result["failingChecks"])

    def test_a_path_escaping_the_artifact_root_is_rejected(self) -> None:
        result = self._verify({"artifacts": {"../outside.tar": "0" * 64}})
        self.assertIn("artifact-checksums", result["failingChecks"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

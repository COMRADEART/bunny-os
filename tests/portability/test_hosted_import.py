"""Importing evidence produced somewhere this repository does not control.

A hosted builder is only useful as independent evidence if its record cannot be
written by hand. Every claim the record makes about itself is cross-checked
against another file in the same bundle that would have to be edited
consistently for the claim to survive.

The checks are cross-references, not signatures, and these tests hold that
distinction: a record edited in one place is caught; a consistently forged
bundle is not, and the import record says `unsigned` rather than implying more.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.builders import evaluate_independence, parse_builder_record  # noqa: E402
from release.hosted import (  # noqa: E402
    REQUIRED_ARTIFACTS,
    HostedImportError,
    import_hosted_evidence,
)

CANDIDATE = "9ea5459bdaf122f8c5999683b2c8961555826954"
OTHER_COMMIT = "b" * 40
BASE = "quay.io/fedora/fedora-bootc:44@sha256:" + "c" * 64
OTHER_BASE = "quay.io/fedora/fedora-bootc:44@sha256:" + "d" * 64
RUN = "30558894088.1"
ARCHIVE_RAW = "a" * 64
ARCHIVE_NORMALISED = "e" * 64


def builder_record(**overrides) -> dict:
    record = {
        "schemaVersion": 2,
        "builderId": "hosted-ci-30558894088",
        "environmentId": "f" * 32,
        "sourceCommit": CANDIDATE,
        "baseImageDigest": BASE,
        "architecture": "x86_64",
        "operatingSystem": "ubuntu-24.04",
        "kernelVersion": "6.11.0-1018-azure",
        "builderType": "hosted-ci",
        "cloudProvider": None,
        "cloudRunner": "runner-1",
        "workflowRunId": RUN,
        "administratorBoundary": "1" * 32,
        "buildStartedAt": "2026-07-30T15:53:00Z",
        "buildCompletedAt": "2026-07-30T16:20:00Z",
        "toolchain": {"podman": "podman version 4.9.3", "syft": "1.50.0"},
        "dependencyLockHashes": {},
    }
    record.update(overrides)
    return record


def provenance_record(**overrides) -> dict:
    record = {
        "schemaVersion": 1,
        "repository": "COMRADEART/bunny-os",
        "workflow": ".github/workflows/independent-builder.yml",
        "workflowRef": "refs/heads/feature/qualification-evidence-closure",
        "workflowRunId": RUN,
        "workflowRunAttempt": 1,
        "runnerImage": "ubuntu24",
        "runnerArchitecture": "X64",
        "kernelVersion": "6.11.0-1018-azure",
        "containerRuntime": "podman version 4.9.3",
        "imageBuilderVersion": "absent",
        "sourceCommit": CANDIDATE,
        "baseImageDigest": BASE,
        "generatedAt": "2026-07-30T16:20:00Z",
        "expiresAt": "2026-10-28T16:20:00Z",
        "cacheDisabled": True,
        "artifacts": {"bunny-os.oci.tar": ARCHIVE_RAW},
        "dependencyLockHashes": {},
    }
    record.update(overrides)
    return record


class Bundle:
    """A downloaded hosted-builder artifact directory."""

    def __init__(self, directory: Path, **overrides) -> None:
        self.root = directory
        self.packages = overrides.pop("packages", ["alpha@1.0", "beta@2.0", "gamma@3.0"])
        self.builder = builder_record(**overrides.pop("builder", {}))
        self.provenance = provenance_record(**overrides.pop("provenance", {}))
        self.environment = {
            "runnerImage": "ubuntu24",
            "runnerArch": "X64",
            "runnerName": "runner-1",
            "runnerEnvironment": "github-hosted",
            "kernel": "6.11.0-1018-azure",
            "os": "ubuntu-24.04",
            "containerRuntime": "podman version 4.9.3",
            "imageBuilder": "absent (BUNNY_ARCHIVE_ONLY=1)",
            "workflowRunId": RUN,
            "cpus": "4",
        }
        self.environment.update(overrides.pop("environment", {}))
        self.normalisation = {
            "rawDigest": ARCHIVE_RAW,
            "normalisedDigest": ARCHIVE_NORMALISED,
        }
        self.normalisation.update(overrides.pop("normalisation", {}))
        self.manifest = overrides.pop("manifest", {"bunny-os.oci.tar": ARCHIVE_RAW})
        self.omit = set(overrides.pop("omit", ()))
        self.write()

    def write(self) -> None:
        write = self.root
        write.mkdir(parents=True, exist_ok=True)

        def dump(name: str, value) -> None:
            if name in self.omit:
                return
            (write / name).write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )

        dump("builder-record.json", self.builder)
        dump("ci-provenance.json", self.provenance)
        dump("normalisation.json", self.normalisation)
        dump("sbom.spdx.json", {
            "packages": [
                {"name": entry.split("@")[0], "versionInfo": entry.split("@")[1]}
                for entry in self.packages
            ]
        })
        if "package-inventory.txt" not in self.omit:
            (write / "package-inventory.txt").write_text(
                "\n".join(self.packages) + "\n", encoding="utf-8", newline="\n"
            )
        if "artifact-manifest.sha256" not in self.omit:
            (write / "artifact-manifest.sha256").write_text(
                "".join(f"{digest}  {name}\n" for name, digest in self.manifest.items()),
                encoding="utf-8", newline="\n",
            )
        if "runner-environment.txt" not in self.omit:
            (write / "runner-environment.txt").write_text(
                "".join(f"{k}={v}\n" for k, v in self.environment.items()),
                encoding="utf-8", newline="\n",
            )
        if "build.log" not in self.omit:
            (write / "build.log").write_text("build log\n", encoding="utf-8", newline="\n")


def evidence(directory: Path, **kwargs):
    return import_hosted_evidence(
        directory,
        candidateCommit=kwargs.pop("candidateCommit", CANDIDATE),
        expectedBaseDigest=kwargs.pop("expectedBaseDigest", BASE),
        knownRunIds=kwargs.pop("knownRunIds", ()),
        expectedRunId=kwargs.pop("expectedRunId", None),
    )


class AWellFormedBundleIsAcceptedTests(unittest.TestCase):
    def test_a_complete_consistent_bundle_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            result = evidence(Path(directory))
            self.assertTrue(result.accepted, result.reasons)
            self.assertEqual(result.builder.workflowRunId, RUN)
            self.assertEqual(result.rawArchiveDigest, ARCHIVE_RAW)
            self.assertEqual(result.packageCount, 3)

    def test_the_import_record_says_it_is_unsigned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            payload = evidence(Path(directory)).as_dict()
            self.assertFalse(payload["signed"])
            self.assertEqual(payload["provenanceClaim"], "unsigned")
            self.assertIn("not signed", payload["note"])

    def test_every_required_artifact_is_digested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            digests = evidence(Path(directory)).bundleDigests
            self.assertEqual(set(digests), set(REQUIRED_ARTIFACTS))
            for name, value in digests.items():
                self.assertRegex(value, r"^[0-9a-f]{64}$", name)


class IncompleteBundleTests(unittest.TestCase):
    def test_a_bundle_missing_any_required_artifact_is_refused(self) -> None:
        for name in REQUIRED_ARTIFACTS:
            with self.subTest(missing=name), tempfile.TemporaryDirectory() as directory:
                Bundle(Path(directory), omit=(name,))
                with self.assertRaises(HostedImportError) as caught:
                    evidence(Path(directory))
                self.assertIn(name, str(caught.exception))

    def test_a_directory_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(HostedImportError):
            evidence(Path("/nonexistent/bundle"))


class WorkflowIdentityTests(unittest.TestCase):
    def test_a_record_with_no_run_id_is_refused(self) -> None:
        # Refused at the parser, before any cross-referencing: a hosted-ci
        # record with no run identifier is not a record of a run.
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"workflowRunId": None})
            with self.assertRaises(HostedImportError) as caught:
                evidence(Path(directory))
            self.assertIn("workflowRunId", str(caught.exception))

    def test_a_run_id_that_is_not_a_run_identifier_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"workflowRunId": "not-a-run"},
                   environment={"workflowRunId": "not-a-run"},
                   provenance={"workflowRunId": "not-a-run"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("is not a run id" in r for r in result.reasons), result.reasons)

    def test_a_reused_run_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            result = evidence(Path(directory), knownRunIds=[RUN])
            self.assertFalse(result.accepted)
            self.assertTrue(
                any("already recorded" in r for r in result.reasons), result.reasons
            )

    def test_a_run_id_other_than_the_expected_one_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            result = evidence(Path(directory), expectedRunId="99999999")
            self.assertFalse(result.accepted)
            self.assertTrue(any("not the expected run" in r for r in result.reasons))

    def test_a_non_hosted_builder_type_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"builderType": "local-machine"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("only a hosted-ci record" in r for r in result.reasons))

    def test_a_self_hosted_runner_environment_is_refused(self) -> None:
        # A self-hosted runner shares an administrator with this project, which
        # is the whole thing the hosted builder is supposed to avoid.
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), environment={"runnerEnvironment": "self-hosted"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("not github-hosted" in r for r in result.reasons))


class ManuallyEditedRecordTests(unittest.TestCase):
    """A record edited in one place disagrees with the rest of its bundle."""

    def test_an_edited_run_id_disagrees_with_the_runner_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"workflowRunId": "11111111.1"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(
                any("the runner reported" in r for r in result.reasons), result.reasons
            )

    def test_an_edited_kernel_disagrees_with_the_runner_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"kernelVersion": "6.99.0-invented"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("claims kernel" in r for r in result.reasons))

    def test_an_edited_operating_system_disagrees_with_the_runner_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"operatingSystem": "fedora-44"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("claims OS" in r for r in result.reasons))

    def test_an_edited_provenance_run_id_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), provenance={"workflowRunId": "22222222.1"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("CI provenance records" in r for r in result.reasons))

    def test_an_edited_archive_digest_disagrees_with_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), normalisation={"rawDigest": "9" * 64})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("artifact manifest records" in r for r in result.reasons))

    def test_a_consistently_forged_bundle_is_not_claimed_to_be_caught(self) -> None:
        # Stated, not hidden: editing every file consistently defeats a
        # cross-reference check. The record reports `unsigned` for this reason.
        with tempfile.TemporaryDirectory() as directory:
            Bundle(
                Path(directory),
                builder={"kernelVersion": "6.99.0-invented"},
                environment={"kernel": "6.99.0-invented"},
            )
            result = evidence(Path(directory))
            self.assertTrue(result.accepted, result.reasons)
            self.assertFalse(result.as_dict()["signed"])


class SourceAndBaseMismatchTests(unittest.TestCase):
    def test_a_source_commit_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"sourceCommit": OTHER_COMMIT},
                   provenance={"sourceCommit": OTHER_COMMIT})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(
                any("evidence does not transfer between commits" in r for r in result.reasons)
            )

    def test_an_import_bound_to_the_wrong_candidate_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory))
            result = evidence(Path(directory), candidateCommit=OTHER_COMMIT)
            self.assertFalse(result.accepted)
            self.assertTrue(any("the candidate is" in r for r in result.reasons))

    def test_a_base_image_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), builder={"baseImageDigest": OTHER_BASE},
                   provenance={"baseImageDigest": OTHER_BASE})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("not comparable" in r for r in result.reasons))

    def test_a_base_disagreement_within_the_bundle_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), provenance={"baseImageDigest": OTHER_BASE})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("disagree about the base image" in r for r in result.reasons))


class ArtifactContentTests(unittest.TestCase):
    def test_an_sbom_and_inventory_that_disagree_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Bundle(Path(directory))
            (bundle.root / "package-inventory.txt").write_text(
                "alpha@1.0\n", encoding="utf-8", newline="\n"
            )
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("different builds" in r for r in result.reasons))

    def test_an_empty_package_inventory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), packages=[])
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("nothing was measured" in r for r in result.reasons))

    def test_an_unsigned_production_provenance_claim_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), normalisation={"provenanceClaim": "production"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("without a signature" in r for r in result.reasons))

    def test_an_archive_only_bundle_claiming_candidate_status_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), normalisation={"candidateStatus": "candidate"})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("claims candidate status" in r for r in result.reasons))

    def test_image_builder_being_installed_is_not_a_rejection(self) -> None:
        # Availability is not use. The local Fedora builder has image-builder
        # installed and correctly does not run it in archive-only mode; an
        # earlier check rejected it on the version string alone.
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), provenance={"imageBuilderVersion": "image-builder 1.4.0"})
            result = evidence(Path(directory))
            self.assertTrue(result.accepted, result.reasons)

    def test_a_build_provenance_that_is_not_archive_only_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Bundle(Path(directory))
            (bundle.root / "provenance.json").write_text(json.dumps({
                "archiveOnly": False, "diskImages": ["bunny-os.qcow2"],
                "sourceCommit": CANDIDATE,
            }), encoding="utf-8")
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("does not declare archiveOnly=true" in r for r in result.reasons))
            self.assertTrue(any("lists disk images" in r for r in result.reasons))

    def test_an_archive_only_build_provenance_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Bundle(Path(directory))
            (bundle.root / "provenance.json").write_text(json.dumps({
                "archiveOnly": True, "diskImages": [], "sourceCommit": CANDIDATE,
            }), encoding="utf-8")
            result = evidence(Path(directory))
            self.assertTrue(result.accepted, result.reasons)

    def test_a_build_provenance_for_another_commit_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Bundle(Path(directory))
            (bundle.root / "provenance.json").write_text(json.dumps({
                "archiveOnly": True, "diskImages": [], "sourceCommit": OTHER_COMMIT,
            }), encoding="utf-8")
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("the build provenance describes" in r for r in result.reasons))

    def test_a_manifest_without_the_archive_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Bundle(Path(directory), manifest={"other.txt": "b" * 64})
            result = evidence(Path(directory))
            self.assertFalse(result.accepted)
            self.assertTrue(any("does not list bunny-os.oci.tar" in r for r in result.reasons))


class SharedAdministratorBoundaryTests(unittest.TestCase):
    """Two builders behind one administrator are separation, not independence."""

    def test_two_builders_sharing_an_administrator_are_not_independent(self) -> None:
        local = parse_builder_record(builder_record(
            builderId="local-fedora-wsl",
            builderType="local-machine",
            environmentId="a" * 32,
            administratorBoundary="shared" + "0" * 26,
            workflowRunId=None,
            cloudRunner=None,
            operatingSystem="fedora-44",
        ))
        hosted = parse_builder_record(builder_record(
            builderId="hosted-ci-1",
            builderType="hosted-ci",
            environmentId="b" * 32,
            administratorBoundary="shared" + "0" * 26,
            cloudRunner="gh-runner-9",
        ))
        verdict = evaluate_independence(local, hosted)
        self.assertFalse(verdict.independent)
        self.assertTrue(
            any("administrator" in reason.lower() for reason in verdict.reasons),
            verdict.reasons,
        )

    def test_distinct_boundaries_are_required_for_the_accepted_pairing(self) -> None:
        local = parse_builder_record(builder_record(
            builderId="local-fedora-wsl",
            builderType="local-machine",
            environmentId="a" * 32,
            administratorBoundary="1" * 32,
            workflowRunId=None,
            cloudRunner=None,
            operatingSystem="fedora-44",
        ))
        hosted = parse_builder_record(builder_record(
            builderId="hosted-ci-1",
            builderType="hosted-ci",
            environmentId="b" * 32,
            administratorBoundary="2" * 32,
            cloudRunner="gh-runner-9",
        ))
        verdict = evaluate_independence(local, hosted)
        self.assertTrue(verdict.independent, verdict.reasons)


class EvidenceCommitPromotionTests(unittest.TestCase):
    """The evidence commit must not become the candidate."""

    def test_the_committed_candidate_is_not_the_evidence_commit(self) -> None:
        declared = json.loads(
            (ROOT / "operations/data/release-evidence.json").read_text(encoding="utf-8")
        )["candidateCommit"]
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
        # The evidence commit is HEAD when this runs after an evidence import.
        # A candidate equal to it would claim the evidence describes a tree that
        # did not exist when the evidence was measured.
        self.assertNotEqual(
            declared, head,
            "candidateCommit equals HEAD; an evidence-import commit was promoted to candidate",
        )

    def test_a_hosted_record_built_from_the_evidence_commit_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_commit = "f" * 40
            Bundle(Path(directory), builder={"sourceCommit": evidence_commit},
                   provenance={"sourceCommit": evidence_commit})
            result = evidence(Path(directory), candidateCommit=CANDIDATE)
            self.assertFalse(result.accepted)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

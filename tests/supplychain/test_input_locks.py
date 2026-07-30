# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The input locks refuse everything they are supposed to refuse.

Each test names a mistake that has either happened in this project or is one
version of a lock away from happening. A lock that accepts an ambiguous record
reports success for an unpinned build, which is worse than having no lock at
all — it looks like evidence.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from release.supplychain import (  # noqa: E402
    SupplyChainError,
    evaluate_input_locks,
    normalise_architecture,
    parse_base_image_lock,
    parse_builder_image_lock,
    parse_package_snapshot_lock,
    parse_reproducibility_lock,
    toolchain_mismatches,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
COMMIT = "9ea5459bdaf122f8c5999683b2c8961555826954"


def base_lock(**overrides):
    lock = {
        "schemaVersion": 1,
        "upstreamReference": f"quay.io/fedora/fedora-bootc:44@{DIGEST_A}",
        "upstreamDigest": DIGEST_A,
        "upstreamMediaType": "application/vnd.oci.image.index.v1+json",
        "selectedArchitecture": "amd64",
        "selectedManifestDigest": DIGEST_B,
        "retainedReference": f"ghcr.io/comradeart/bunny-os-base@{DIGEST_B}",
        "retainedDigest": DIGEST_B,
        "retainedLocation": "ghcr.io/comradeart/bunny-os-base",
        "architectures": ["amd64", "arm64"],
        "manifests": [
            {"digest": DIGEST_B, "mediaType": "application/vnd.oci.image.manifest.v1+json",
             "size": 1, "architecture": "amd64", "os": "linux"},
            {"digest": DIGEST_C, "mediaType": "application/vnd.oci.image.manifest.v1+json",
             "size": 1, "architecture": "arm64", "os": "linux"},
        ],
        "copiedAt": "2026-07-30T18:00:00Z",
        "verificationStatus": "verified",
    }
    lock.update(overrides)
    return lock


def builder_lock(**overrides):
    tools = [
        {"name": name, "version": "1.0", "classification": "output-affecting", "reason": "r"}
        for name in (
            "podman", "buildah", "skopeo", "conmon", "crun", "runc", "python3", "rpm",
            "dnf5", "libdnf5", "tar", "gzip", "zstd", "syft", "grype", "createrepo_c",
            "policycoreutils", "libselinux-utils",
        )
    ]
    lock = {
        "schemaVersion": 1,
        "builderReference": f"ghcr.io/comradeart/bunny-os-builder@{DIGEST_A}",
        "builderDigest": DIGEST_A,
        "baseReference": f"registry.fedoraproject.org/fedora@{DIGEST_B}",
        "baseDigest": DIGEST_B,
        "sourceCommit": COMMIT,
        "containerfileDigest": "d" * 64,
        "architecture": "x86_64",
        "tools": tools,
        "builtAt": "2026-07-30T18:00:00Z",
        "verificationStatus": "verified",
    }
    lock.update(overrides)
    return lock


def snapshot_lock(**overrides):
    lock = {
        "schemaVersion": 1,
        "snapshotId": "fedora-44-beta-20260730",
        "profile": "beta",
        "architecture": "x86_64",
        "packages": [
            {
                "name": "orca", "epoch": "0", "version": "49.1", "release": "1.fc44",
                "architecture": "noarch", "checksum": "e" * 64, "size": 100,
                "sourceRepository": "fedora", "signingKey": "dbfcf71c6d9f90a6",
                "signatureVerified": True, "sourceRpm": "orca-49.1-1.fc44.src.rpm",
                "licence": "LGPL-2.1-or-later", "location": "packages/orca.rpm",
            }
        ],
        "repositoryMetadataDigest": "f" * 64,
        "manifestDigest": "0" * 64,
        "signature": {
            "algorithm": "ed25519", "keyId": "dev-snapshot-signing1",
            "role": "snapshot-signing", "trust": "development", "value": "ab",
        },
        "createdAt": "2026-07-30T18:00:00Z",
        "retainedLocation": "/var/lib/bunny-retention/package-snapshots/x",
        "verificationStatus": "verified",
    }
    lock.update(overrides)
    return lock


def epoch_lock(**overrides):
    lock = {
        "schemaVersion": 1,
        "candidateCommit": COMMIT,
        "sourceDateEpoch": 1785438206,
        "epochSource": "commit timestamp",
        "profile": "beta",
        "architecture": "x86_64",
        "baseImageDigest": DIGEST_A,
        "retainedBaseDigest": DIGEST_B,
        "builderImageDigest": DIGEST_A,
        "packageSnapshotDigest": "0" * 64,
        "appliedTo": ["rpm-transaction-install-time", "font-directory-mtimes"],
        "neverAppliedTo": [
            "certificate-validity", "security-advisory-freshness",
            "package-signature-verification", "update-metadata-expiry", "evidence-timestamps",
        ],
    }
    lock.update(overrides)
    return lock


class BaseImageLockTests(unittest.TestCase):
    def test_a_valid_lock_parses(self):
        self.assertEqual(parse_base_image_lock(base_lock()).selectedArchitecture, "amd64")

    def test_a_mutable_tag_is_refused(self):
        """CI protection 1: mutable base tags."""
        with self.assertRaises(SupplyChainError) as caught:
            parse_base_image_lock(base_lock(upstreamReference="quay.io/fedora/fedora-bootc:44"))
        self.assertIn("not digest-pinned", str(caught.exception))

    def test_a_retained_digest_that_is_not_the_selected_manifest_is_refused(self):
        """CI protection 3: base mirror digest mismatch.

        A copy that changed the manifest digest re-encoded the image, and a
        re-encoded image is a different image however similar it looks.
        """
        with self.assertRaises(SupplyChainError) as caught:
            parse_base_image_lock(
                base_lock(retainedDigest=DIGEST_C,
                          retainedReference=f"ghcr.io/x@{DIGEST_C}")
            )
        self.assertIn("re-encoded", str(caught.exception))

    def test_a_manifest_not_in_the_upstream_index_is_refused(self):
        unrelated = "sha256:" + "9" * 64
        with self.assertRaises(SupplyChainError) as caught:
            parse_base_image_lock(
                base_lock(selectedManifestDigest=unrelated,
                          retainedDigest=unrelated,
                          retainedReference=f"ghcr.io/x@{unrelated}")
            )
        self.assertIn("not in the recorded manifest inventory", str(caught.exception))

    def test_a_failed_verification_is_recorded_not_hidden(self):
        lock = parse_base_image_lock(base_lock(verificationStatus="failed"))
        verdict = evaluate_input_locks(base=lock, builder=None, snapshot=None, reproducibility=None)
        self.assertEqual(verdict.result, "BLOCKED")

    def test_an_architecture_outside_the_index_is_refused(self):
        with self.assertRaises(SupplyChainError):
            parse_base_image_lock(base_lock(selectedArchitecture="s390x"))


class BuilderImageLockTests(unittest.TestCase):
    def test_a_valid_lock_parses(self):
        self.assertEqual(len(parse_builder_image_lock(builder_lock()).tools), 18)

    def test_a_mutable_builder_tag_is_refused(self):
        """CI protection 4: mutable builder tags."""
        with self.assertRaises(SupplyChainError):
            parse_builder_image_lock(
                builder_lock(builderReference="ghcr.io/comradeart/bunny-os-builder:latest")
            )

    def test_a_tool_with_no_version_is_refused(self):
        lock = builder_lock()
        lock["tools"][0]["version"] = ""
        with self.assertRaises(SupplyChainError) as caught:
            parse_builder_image_lock(lock)
        self.assertIn("not pinned", str(caught.exception))

    def test_an_unpinned_tool_must_be_declared_absent_with_a_reason(self):
        lock = builder_lock()
        lock["tools"] = [t for t in lock["tools"] if t["name"] != "zstd"]
        with self.assertRaises(SupplyChainError) as caught:
            parse_builder_image_lock(lock)
        self.assertIn("zstd", str(caught.exception))

        lock["absentTools"] = {"zstd": "not used by the archive-only path"}
        self.assertTrue(parse_builder_image_lock(lock))

    def test_declaring_a_tool_absent_without_a_reason_is_refused(self):
        lock = builder_lock()
        lock["tools"] = [t for t in lock["tools"] if t["name"] != "zstd"]
        lock["absentTools"] = {"zstd": ""}
        with self.assertRaises(SupplyChainError) as caught:
            parse_builder_image_lock(lock)
        self.assertIn("without saying why", str(caught.exception))

    def test_a_non_blocking_classification_requires_a_reason(self):
        lock = builder_lock()
        lock["tools"][0]["classification"] = "evidence-generation-only"
        lock["tools"][0]["reason"] = ""
        with self.assertRaises(SupplyChainError) as caught:
            parse_builder_image_lock(lock)
        self.assertIn("must say why", str(caught.exception))

    def test_unknown_classification_blocks(self):
        lock = builder_lock()
        lock["tools"][0]["classification"] = "unknown"
        parsed = parse_builder_image_lock(lock)
        self.assertEqual(parsed.unknownTools, ("podman",))
        verdict = evaluate_input_locks(
            base=None, builder=parsed, snapshot=None, reproducibility=None
        )
        self.assertEqual(verdict.result, "BLOCKED")


class SnapshotLockTests(unittest.TestCase):
    def test_a_valid_lock_parses(self):
        self.assertEqual(len(parse_package_snapshot_lock(snapshot_lock()).packages), 1)

    def test_an_unsigned_snapshot_manifest_is_refused(self):
        """CI protection 8: unsigned snapshot metadata."""
        with self.assertRaises(SupplyChainError) as caught:
            parse_package_snapshot_lock(snapshot_lock(signature={}))
        self.assertIn("must be signed", str(caught.exception))

    def test_a_package_whose_signature_was_not_verified_is_refused(self):
        lock = snapshot_lock()
        lock["packages"][0]["signatureVerified"] = False
        with self.assertRaises(SupplyChainError) as caught:
            parse_package_snapshot_lock(lock)
        self.assertIn("original trusted signature", str(caught.exception))

    def test_a_package_with_a_non_sha256_checksum_is_refused(self):
        """CI protection 9: package checksum mismatch starts with a checksum that is one."""
        lock = snapshot_lock()
        lock["packages"][0]["checksum"] = "not-a-digest"
        with self.assertRaises(SupplyChainError):
            parse_package_snapshot_lock(lock)

    def test_a_duplicate_package_is_refused(self):
        lock = snapshot_lock()
        lock["packages"].append(copy.deepcopy(lock["packages"][0]))
        with self.assertRaises(SupplyChainError) as caught:
            parse_package_snapshot_lock(lock)
        self.assertIn("recorded twice", str(caught.exception))

    def test_the_signature_must_declare_its_trust_level(self):
        lock = snapshot_lock()
        lock["signature"]["trust"] = "unspecified"
        with self.assertRaises(SupplyChainError) as caught:
            parse_package_snapshot_lock(lock)
        self.assertIn("development", str(caught.exception))

    def test_a_development_key_is_not_silently_production(self):
        parsed = parse_package_snapshot_lock(snapshot_lock())
        self.assertEqual(parsed.signature["trust"], "development")
        self.assertTrue(str(parsed.signature["keyId"]).startswith("dev-"))


class EpochLockTests(unittest.TestCase):
    def test_a_valid_lock_parses(self):
        self.assertEqual(parse_reproducibility_lock(epoch_lock()).sourceDateEpoch, 1785438206)

    def test_the_epoch_may_not_be_applied_to_certificate_validity(self):
        with self.assertRaises(SupplyChainError) as caught:
            parse_reproducibility_lock(epoch_lock(appliedTo=["certificate-validity"]))
        self.assertIn("never be applied", str(caught.exception))

    def test_the_epoch_may_not_be_applied_to_evidence_timestamps(self):
        with self.assertRaises(SupplyChainError):
            parse_reproducibility_lock(epoch_lock(appliedTo=["evidence-timestamps"]))

    def test_every_forbidden_site_must_be_listed_explicitly(self):
        lock = epoch_lock()
        lock["neverAppliedTo"] = ["certificate-validity"]
        with self.assertRaises(SupplyChainError) as caught:
            parse_reproducibility_lock(lock)
        self.assertIn("missing", str(caught.exception))

    def test_an_undeclared_application_site_is_refused(self):
        with self.assertRaises(SupplyChainError) as caught:
            parse_reproducibility_lock(epoch_lock(appliedTo=["anything-i-like"]))
        self.assertIn("not declared epoch-applicable", str(caught.exception))

    def test_a_short_commit_is_refused(self):
        with self.assertRaises(SupplyChainError):
            parse_reproducibility_lock(epoch_lock(candidateCommit="9ea5459"))


class CrossLockTests(unittest.TestCase):
    def _all(self, **overrides):
        return evaluate_input_locks(
            base=parse_base_image_lock(overrides.get("base", base_lock())),
            builder=parse_builder_image_lock(overrides.get("builder", builder_lock())),
            snapshot=parse_package_snapshot_lock(overrides.get("snapshot", snapshot_lock())),
            reproducibility=parse_reproducibility_lock(overrides.get("epoch", epoch_lock())),
        )

    def test_a_consistent_set_passes(self):
        self.assertEqual(self._all().result, "PASS")

    def test_an_absent_lock_blocks(self):
        """CI protection 2: missing retained base."""
        verdict = evaluate_input_locks(
            base=None,
            builder=parse_builder_image_lock(builder_lock()),
            snapshot=parse_package_snapshot_lock(snapshot_lock()),
            reproducibility=parse_reproducibility_lock(epoch_lock()),
        )
        self.assertEqual(verdict.result, "BLOCKED")
        self.assertIn("base-image-lock-present", verdict.as_dict()["failed"])

    def test_an_epoch_lock_naming_a_different_base_blocks(self):
        verdict = self._all(epoch=epoch_lock(retainedBaseDigest=DIGEST_C))
        self.assertIn("epoch-lock-names-retained-base", verdict.as_dict()["failed"])

    def test_an_epoch_lock_naming_a_different_builder_blocks(self):
        """CI protection 5: builder-image mismatch."""
        verdict = self._all(epoch=epoch_lock(builderImageDigest=DIGEST_C))
        self.assertIn("epoch-lock-names-builder-image", verdict.as_dict()["failed"])

    def test_an_epoch_lock_naming_a_different_snapshot_blocks(self):
        verdict = self._all(epoch=epoch_lock(packageSnapshotDigest="1" * 64))
        self.assertIn("epoch-lock-names-snapshot", verdict.as_dict()["failed"])

    def test_the_architecture_must_match_the_selected_manifest(self):
        verdict = self._all(epoch=epoch_lock(architecture="aarch64"))
        self.assertIn("architecture-retained", verdict.as_dict()["failed"])

    def test_oci_and_rpm_architecture_names_are_the_same_architecture(self):
        """amd64 and x86_64 name one architecture; arm64 and x86_64 do not."""
        self.assertEqual(normalise_architecture("amd64"), normalise_architecture("x86_64"))
        self.assertNotEqual(normalise_architecture("arm64"), normalise_architecture("x86_64"))
        self.assertEqual(self._all().result, "PASS")


class ToolchainMismatchTests(unittest.TestCase):
    def test_an_output_affecting_difference_blocks(self):
        blocking, recorded, unclassified = toolchain_mismatches(
            {"podman": "5.8.4"}, {"podman": "4.9.3"},
            classifications={"podman": "output-affecting"},
        )
        self.assertEqual(blocking, ("podman",))
        self.assertEqual(recorded, ())
        self.assertEqual(unclassified, ())

    def test_an_evidence_only_difference_is_recorded_not_blocking(self):
        blocking, recorded, _ = toolchain_mismatches(
            {"syft": "1.50.0"}, {"syft": "1.49.0"},
            classifications={"syft": "evidence-generation-only"},
        )
        self.assertEqual(blocking, ())
        self.assertEqual(recorded, ("syft",))

    def test_an_unclassified_difference_blocks(self):
        _, _, unclassified = toolchain_mismatches(
            {"mystery": "1"}, {"mystery": "2"}, classifications={}
        )
        self.assertEqual(unclassified, ("mystery",))

    def test_absent_on_one_side_counts_as_a_difference(self):
        """'absent' is a version, and image-builder's absence is why this matters."""
        blocking, recorded, unclassified = toolchain_mismatches(
            {"image-builder": "1.2"}, {},
            classifications={"image-builder": "unavailable-but-unused"},
        )
        self.assertEqual(recorded, ("image-builder",))
        self.assertEqual(blocking, ())
        self.assertEqual(unclassified, ())

    def test_the_podman_difference_that_actually_happened_blocks(self):
        """Run 30564513627 had podman 4.9.3; run 30566412012 had 5.8.4.

        The first wrote /etc/hostname into the image and the second did not.
        This is the measurement behind classifying podman output-affecting.
        """
        blocking, _, _ = toolchain_mismatches(
            {"podman": "podman version 4.9.3"},
            {"podman": "podman version 5.8.4"},
            classifications={"podman": "output-affecting"},
        )
        self.assertEqual(blocking, ("podman",))


class CommittedLockTests(unittest.TestCase):
    """The locks committed to this repository must parse.

    A lock that this repository ships and its own parser rejects is a lock
    nothing else will accept either.
    """

    def _lock(self, name):
        path = ROOT / "build" / "inputs" / name
        if not path.is_file():
            self.skipTest(f"{name} has not been generated in this checkout")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_committed_base_lock_parses(self):
        parse_base_image_lock(self._lock("base-image-lock.json"))

    def test_committed_builder_lock_parses(self):
        parse_builder_image_lock(self._lock("builder-image-lock.json"))

    def test_committed_snapshot_lock_parses(self):
        parse_package_snapshot_lock(self._lock("package-snapshot-lock.json"))

    def test_committed_epoch_lock_parses(self):
        parse_reproducibility_lock(self._lock("reproducibility-lock.json"))


if __name__ == "__main__":
    unittest.main()

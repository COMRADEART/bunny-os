# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The twenty-two things CI must reject.

Numbered to the brief. Where a protection is enforced by a lock parser it is
tested in ``test_input_locks.py`` and cross-referenced here rather than
duplicated, so the numbering stays complete and nothing is tested twice.

The general principle these hold: a check that cannot fail is not a check. Each
test constructs the failure and asserts it is refused, because a protection
nobody has seen refuse anything is a protection nobody has tested.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from release.builders import evaluate_independence, parse_builder_record  # noqa: E402
from release.comparison import evaluate_comparison, evaluate_selinux_evidence  # noqa: E402
from release.mutablestate import (  # noqa: E402
    IDENTITY_PATHS,
    MutableStateError,
    audit_machine_identity,
    evaluate_identity,
    parse_policy,
    policy_paths_are_not_excluded,
)

FINALISER = ROOT / "build" / "scripts" / "finalise-image.sh"
POLICY = ROOT / "build" / "inputs" / "mutable-state-policy.json"
TOOLCHAIN = ROOT / "build" / "builder" / "toolchain.lock.json"


def entries(**paths):
    return {path: {"type": "file", "size": size} for path, size in paths.items()}


class MachineIdentityProtections(unittest.TestCase):
    """Protections 12, 13, 14 — hostname, machine id, SSH host keys."""

    def test_hostname_must_be_absent(self):
        findings = audit_machine_identity(
            {**entries(**{"etc/machine-id": 0}), "etc/hostname": {"type": "file", "size": 12}}
        )
        hostname = next(f for f in findings if f.path == "etc/hostname")
        self.assertFalse(hostname.ok)
        self.assertEqual(evaluate_identity(findings)["result"], "BLOCKED")

    def test_machine_id_must_exist_and_be_empty(self):
        populated = audit_machine_identity(entries(**{"etc/machine-id": 32}))
        finding = next(f for f in populated if f.path == "etc/machine-id")
        self.assertFalse(finding.ok, "a populated machine-id ships the builder's identity")

        empty = audit_machine_identity(entries(**{"etc/machine-id": 0}))
        finding = next(f for f in empty if f.path == "etc/machine-id")
        self.assertTrue(finding.ok)

    def test_an_absent_machine_id_is_not_a_pass(self):
        """Absent and empty are different first-boot paths, and only one was declared."""
        findings = audit_machine_identity({})
        finding = next(f for f in findings if f.path == "etc/machine-id")
        self.assertFalse(finding.ok)

    def test_no_ssh_host_key_is_shipped(self):
        findings = audit_machine_identity(
            {
                **entries(**{"etc/machine-id": 0}),
                "etc/ssh/ssh_host_ed25519_key": {"type": "file", "size": 400},
            }
        )
        self.assertEqual(evaluate_identity(findings)["result"], "BLOCKED")

    def test_no_dbus_machine_id_is_shipped(self):
        findings = audit_machine_identity(
            {**entries(**{"etc/machine-id": 0}), "var/lib/dbus/machine-id": {"type": "file", "size": 33}}
        )
        self.assertEqual(evaluate_identity(findings)["result"], "BLOCKED")

    def test_no_random_seed_is_shipped(self):
        findings = audit_machine_identity(
            {
                **entries(**{"etc/machine-id": 0}),
                "var/lib/systemd/random-seed": {"type": "file", "size": 512},
            }
        )
        self.assertEqual(evaluate_identity(findings)["result"], "BLOCKED")

    def test_brlapi_key_must_be_absent_from_the_immutable_artifact(self):
        """Protection 11."""
        findings = audit_machine_identity(
            {**entries(**{"etc/machine-id": 0}), "etc/brlapi.key": {"type": "file", "size": 33}}
        )
        finding = next(f for f in findings if f.path == "etc/brlapi.key")
        self.assertFalse(finding.ok)

    def test_a_clean_artifact_passes(self):
        findings = audit_machine_identity(entries(**{"etc/machine-id": 0}))
        self.assertEqual(evaluate_identity(findings)["result"], "PASS")

    def test_every_identity_path_carries_a_reason(self):
        for path, expectation, reason in IDENTITY_PATHS:
            self.assertTrue(reason.strip(), f"{path} has no stated reason")


class MutableStatePolicyProtections(unittest.TestCase):
    def test_the_committed_policy_parses(self):
        if not POLICY.is_file():
            self.skipTest("policy not present in this checkout")
        entries_parsed = parse_policy(json.loads(POLICY.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(entries_parsed), 8)

    def test_an_entry_without_a_generator_is_refused(self):
        with self.assertRaises(MutableStateError) as caught:
            parse_policy(
                {
                    "schemaVersion": 1,
                    "paths": [
                        {
                            "path": "etc/example",
                            "category": "runtime-cache",
                            "disposition": "absent-from-image",
                            "reason": "because",
                            "generator": "",
                            "generationTime": "first boot",
                            "owner": "root:root",
                            "permissions": "0644",
                            "recoveryBehaviour": "recreated",
                            "validationTest": "tests/x.py",
                        }
                    ],
                }
            )
        self.assertIn("unexplained exclusion", str(caught.exception))

    def test_the_policy_is_not_a_comparison_ignore_list(self):
        """The policy must not overlap the comparison's exclusion list.

        A path in both is invisible to the comparison, so the policy would be
        enforcing nothing while appearing to enforce something.
        """
        if not POLICY.is_file():
            self.skipTest("policy not present in this checkout")
        parsed = parse_policy(json.loads(POLICY.read_text(encoding="utf-8")))
        overlap = policy_paths_are_not_excluded(parsed, ["etc/brlapi.key"])
        self.assertEqual(overlap, ("etc/brlapi.key",), "the guard must detect an overlap")

        clean = policy_paths_are_not_excluded(parsed, ["var/log/dnf.log", "run/something"])
        self.assertEqual(clean, ())

    def test_machine_id_is_declared_even_though_the_comparison_excludes_it(self):
        if not POLICY.is_file():
            self.skipTest("policy not present in this checkout")
        parsed = parse_policy(json.loads(POLICY.read_text(encoding="utf-8")))
        self.assertIn("etc/machine-id", {entry.path for entry in parsed})


class FinalisationProtections(unittest.TestCase):
    """Protections 15, 16, 17 — font caches, countme, package-manager state."""

    def _finaliser(self):
        if not FINALISER.is_file():
            self.skipTest("finalise-image.sh not present")
        return FINALISER.read_text(encoding="utf-8")

    def _database_finaliser(self):
        """The delegated half.

        Database canonicalisation used to be three lines inside
        finalise-image.sh. It is now build/scripts/finalise-package-databases.sh
        and the module it execs, because it has a contract the rest of
        finalisation does not — idempotent, fail-closed on eleven conditions,
        and able to prove it altered no content. These assertions follow it
        rather than being deleted along with the lines they were watching.
        """
        module = ROOT / "scripts" / "reproducibility" / "finalise_package_databases.py"
        wrapper = ROOT / "build" / "scripts" / "finalise-package-databases.sh"
        if not (module.is_file() and wrapper.is_file()):
            self.skipTest("the database finaliser is not present")
        return wrapper.read_text(encoding="utf-8") + module.read_text(encoding="utf-8")

    def test_package_caches_are_removed(self):
        text = self._finaliser()
        self.assertIn("/var/cache/dnf", text)
        self.assertIn("/var/cache/libdnf5", text)

    def test_countme_state_is_removed_and_disabled(self):
        text = self._finaliser()
        self.assertIn("countme", text)
        self.assertIn("countme=0", text, "removing the counter without disabling it regenerates it")

    def test_sqlite_residue_is_checkpointed(self):
        text = self._database_finaliser()
        self.assertIn("wal_checkpoint", text)
        self.assertIn("transaction_history.sqlite", text)

    def test_the_database_finaliser_is_still_invoked(self):
        """Delegating the step must not amount to dropping it."""
        self.assertIn("finalise-package-databases.sh", self._finaliser())

    def test_the_transaction_history_itself_is_not_deleted(self):
        text = self._finaliser() + self._database_finaliser()
        self.assertNotIn("rm -f /usr/lib/sysimage/libdnf5/transaction_history.sqlite\n", text)

    def test_the_database_finaliser_proves_it_changed_no_content(self):
        """The check that stops a canonicaliser laundering a real difference.

        VACUUM is content-preserving by definition, and the one difference this
        project actually found was a content difference that a plausible
        canonicalisation would have erased. So the claim is measured either side
        rather than cited.
        """
        text = self._database_finaliser()
        self.assertIn("logical_digest", text)
        self.assertIn("logicalDigestPreserved", text)

    def test_the_database_finaliser_refuses_a_drifted_sqlite(self):
        text = self._database_finaliser()
        self.assertIn("expect_sqlite", text)
        self.assertIn("sqlite3.sqlite_version", text)

    def test_font_directory_mtimes_are_pinned_rather_than_caches_deleted(self):
        text = self._finaliser()
        self.assertIn("/usr/share/fonts", text)
        self.assertIn("fc-cache", text)

    def test_the_finaliser_verifies_its_own_result(self):
        text = self._finaliser()
        self.assertIn("11. verifying no unexpected mutable state remains", text)
        self.assertIn("exit 2", text)


class ToolchainClassificationProtections(unittest.TestCase):
    """Protection 6 and the classifications the builder lock relies on."""

    def _declared(self):
        if not TOOLCHAIN.is_file():
            self.skipTest("toolchain.lock.json not present")
        return json.loads(TOOLCHAIN.read_text(encoding="utf-8"))

    def test_podman_is_output_affecting(self):
        self.assertEqual(
            self._declared()["classifications"]["podman"]["classification"], "output-affecting"
        )

    def test_python_is_output_affecting(self):
        self.assertEqual(
            self._declared()["classifications"]["python3"]["classification"], "output-affecting"
        )

    def test_every_container_tool_is_output_affecting(self):
        classifications = self._declared()["classifications"]
        for name in ("podman", "buildah", "crun", "runc", "conmon", "skopeo"):
            self.assertEqual(
                classifications[name]["classification"],
                "output-affecting",
                f"{name} runs in the path that builds the image",
            )

    def test_package_tools_are_output_affecting(self):
        classifications = self._declared()["classifications"]
        for name in ("rpm", "dnf5", "libdnf5"):
            self.assertEqual(classifications[name]["classification"], "output-affecting")

    def test_archive_tools_are_output_affecting(self):
        classifications = self._declared()["classifications"]
        for name in ("tar", "gzip", "zstd"):
            self.assertEqual(classifications[name]["classification"], "output-affecting")

    def test_evidence_tools_never_write_into_the_image(self):
        """The classification is a claim about the build, so check the build.

        Asserting that the *reason* contains a particular word tests the prose.
        What the classification actually claims is that neither tool runs while
        the image is being constructed, and the Containerfile is where that is
        either true or false.
        """
        classifications = self._declared()["classifications"]
        for name in ("syft", "grype"):
            self.assertEqual(classifications[name]["classification"], "evidence-generation-only")

        containerfile = ROOT / "build" / "Containerfile"
        if not containerfile.is_file():
            self.skipTest("Containerfile not present")
        text = containerfile.read_text(encoding="utf-8")
        for name in ("syft", "grype"):
            self.assertNotIn(
                name,
                text,
                f"{name} is classified evidence-generation-only, so it must not appear in the "
                "product Containerfile at all",
            )

    def test_selinux_tools_run_in_verification_mode_only(self):
        classifications = self._declared()["classifications"]
        for name in ("policycoreutils", "libselinux-utils"):
            self.assertEqual(classifications[name]["classification"], "evidence-generation-only")
        collector = ROOT / "scripts" / "reproducibility" / "collect_intended_selinux.py"
        if collector.is_file():
            text = collector.read_text(encoding="utf-8")
            self.assertNotIn("setfiles -r", text, "the collector must never relabel")
            self.assertIn("matchpathcon", text)

    def test_every_classification_carries_a_reason_and_a_test(self):
        for name, entry in self._declared()["classifications"].items():
            self.assertTrue(entry.get("reason", "").strip(), f"{name} has no reason")
            self.assertTrue(entry.get("test", "").strip(), f"{name} names no test")

    def test_image_builder_absence_is_declared_with_a_reason(self):
        absent = self._declared()["absentTools"]
        self.assertIn("image-builder", absent)
        self.assertIn("archive-only", absent["image-builder"])


class BuilderPairProtections(unittest.TestCase):
    """Protections 20 and 22 — one hosted run used twice, evidence commit promoted."""

    def _record(self, **overrides):
        record = {
            "schemaVersion": 2,
            "builderId": "hosted-ci-1",
            "environmentId": "e1",
            "sourceCommit": "9ea5459bdaf122f8c5999683b2c8961555826954",
            "baseImageDigest": "quay.io/fedora/fedora-bootc:44@sha256:" + "c" * 64,
            "architecture": "x86_64",
            "operatingSystem": "ubuntu-24.04",
            "kernelVersion": "6.17.0",
            "builderType": "hosted-ci",
            "administratorBoundary": "b1",
            "buildStartedAt": "2026-07-30T17:00:00Z",
            "buildCompletedAt": "2026-07-30T17:30:00Z",
            "toolchain": {"podman": "5.8.4"},
            "workflowRunId": "30566412012.1",
        }
        record.update(overrides)
        return parse_builder_record(record)

    def test_one_hosted_run_cannot_be_two_builders(self):
        """Protection 20."""
        verdict = evaluate_independence(
            self._record(),
            self._record(builderId="hosted-ci-2", environmentId="e2", administratorBoundary="b2"),
        )
        self.assertFalse(verdict.independent)
        self.assertTrue(
            any("workflow run" in reason for reason in verdict.reasons),
            verdict.reasons,
        )

    def test_two_distinct_hosted_runs_under_distinct_boundaries_are_a_pair(self):
        verdict = evaluate_independence(
            self._record(builderType="local-machine", builderId="local", workflowRunId=None,
                         administratorBoundary="b1", operatingSystem="fedora-44"),
            self._record(builderId="hosted", administratorBoundary="b2", environmentId="e2"),
        )
        self.assertTrue(verdict.independent, verdict.reasons)


class SelinuxEvidenceProtections(unittest.TestCase):
    """Protection 18 — intended SELinux contexts not collected."""

    def test_absent_intended_contexts_make_the_composite_not_collected(self):
        result = evaluate_selinux_evidence({}, stage="archive")
        self.assertEqual(result["compositeState"], "NOT_COLLECTED")
        self.assertFalse(result["fullyQualified"])

    def test_matching_intended_contexts_satisfy_the_archive_stage_only(self):
        document = {
            "selinux": {
                "intendedSelinuxContexts": {
                    "first": {"usr/bin/passwd": "system_u:object_r:passwd_exec_t:s0"},
                    "second": {"usr/bin/passwd": "system_u:object_r:passwd_exec_t:s0"},
                }
            }
        }
        result = evaluate_selinux_evidence(document, stage="archive")
        self.assertEqual(result["compositeState"], "MATCH")
        self.assertEqual(result["outstandingAtLaterStages"], ["appliedSelinuxContexts"])
        self.assertFalse(
            result["fullyQualified"],
            "an archive build must never report installed-system SELinux as satisfied",
        )

    def test_differing_intended_contexts_make_the_composite_differ(self):
        document = {
            "selinux": {
                "intendedSelinuxContexts": {
                    "first": {"usr/bin/passwd": "a"},
                    "second": {"usr/bin/passwd": "b"},
                }
            }
        }
        self.assertEqual(
            evaluate_selinux_evidence(document, stage="archive")["compositeState"], "DIFFER"
        )

    def test_two_empty_sets_are_not_a_match(self):
        """The failure the whole subcheck model exists to prevent."""
        document = {"selinux": {"intendedSelinuxContexts": {"first": None, "second": None}}}
        self.assertEqual(
            evaluate_selinux_evidence(document, stage="archive")["compositeState"], "NOT_COLLECTED"
        )

    def test_the_comparison_reports_the_outstanding_installed_system_subcheck(self):
        document = {
            "dimensions": {
                name: {"first": 1, "second": 1}
                for name in (
                    "filesystemTree", "fileDigests", "permissions", "ownership",
                    "extendedAttributes", "selinuxLabels", "packageInventory", "sbom",
                    "bootConfiguration", "systemdUnits", "desktopEntries", "schemas",
                    "kernel", "initramfs", "ociLayers", "rawArchive", "normalisedArchive",
                )
            },
            "selinux": {
                "intendedSelinuxContexts": {"first": {"a": "x"}, "second": {"a": "x"}},
            },
        }
        report = evaluate_comparison(document, independent=True)
        self.assertEqual(report.outcome, "REPRODUCIBLE")
        self.assertTrue(report.satisfiesProductionGate)
        self.assertFalse(report.as_dict()["satisfiesInstalledSystemSelinux"])
        self.assertTrue(
            any("installed-system qualification" in reason for reason in report.reasons)
        )


class ReproducibilityOutcomeProtections(unittest.TestCase):
    def _document(self, **overrides):
        dimensions = {
            name: {"first": 1, "second": 1}
            for name in (
                "filesystemTree", "fileDigests", "permissions", "ownership",
                "extendedAttributes", "selinuxLabels", "packageInventory", "sbom",
                "bootConfiguration", "systemdUnits", "desktopEntries", "schemas",
                "kernel", "initramfs", "ociLayers", "rawArchive", "normalisedArchive",
            )
        }
        dimensions.update(overrides)
        return {"dimensions": dimensions}

    def test_content_reproducible_archive_variance_does_not_satisfy_the_gate(self):
        document = self._document(rawArchive={"first": "a", "second": "b"})
        document["rawVarianceExplanation"] = "packing metadata"
        report = evaluate_comparison(document, independent=True)
        self.assertEqual(report.outcome, "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE")
        self.assertFalse(
            report.satisfiesProductionGate,
            "only REPRODUCIBLE satisfies the production prerequisite",
        )

    def test_a_normalised_archive_difference_is_non_reproducible(self):
        report = evaluate_comparison(
            self._document(normalisedArchive={"first": "a", "second": "b"}), independent=True
        )
        self.assertEqual(report.outcome, "NON_REPRODUCIBLE")

    def test_a_perfect_comparison_between_dependent_builders_does_not_pass(self):
        report = evaluate_comparison(self._document(), independent=False)
        self.assertEqual(report.outcome, "REPRODUCIBLE")
        self.assertFalse(report.satisfiesProductionGate)


if __name__ == "__main__":
    unittest.main()

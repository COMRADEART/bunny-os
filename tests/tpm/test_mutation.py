# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mutation battery for the critical TPM adversarial checks.

A check that fires on tampered input might still be tautological — firing
for a reason unrelated to the fraud it names. Each test here mutates the
*environment of the check* (the context or the untampered fields) so that
the specific fraud disappears, and asserts the refusal disappears with it.
A refusal that survives its own fraud being removed is refusing something
else, and the battery fails.

This is deliberate mutation testing of the checks themselves, not of the
frauds: detection must be attributable to the exact clause that names it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification/tpm/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tpm_context import (  # noqa: E402
    verify_internal_consistency,
    verify_record_binding,
)
from test_adversarial import ARGV_CRB, ARGV_NONE, ARGV_TCG, CONTEXT, record  # noqa: E402


class MutationBattery(unittest.TestCase):
    def assert_attributable(self, *, tampered: dict, argv: list | None,
                            marker: str, repaired: dict | None = None,
                            repaired_argv: list | None = None) -> None:
        """The refusal fires on the tampered record and vanishes on the
        repaired one; both halves are load-bearing."""
        reasons = verify_internal_consistency(tampered, argv)
        self.assertTrue(any(marker in r for r in reasons),
                        f"check did not fire: {reasons}")
        fixed = repaired if repaired is not None else record()
        fixed_reasons = verify_internal_consistency(
            fixed, repaired_argv if repaired_argv is not None else ARGV_CRB)
        self.assertFalse(any(marker in r for r in fixed_reasons),
                         f"check fired without its fraud: {fixed_reasons}")

    def test_interface_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(), argv=ARGV_NONE, marker="no tpm-crb device")

    def test_no_tpm_label_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(tpmInterface="none", tpmState="none"), argv=ARGV_CRB,
            marker="attached a TPM device",
            repaired=record(tpmInterface="none", tpmState="none"),
            repaired_argv=ARGV_NONE)

    def test_acceleration_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(), argv=ARGV_TCG, marker="relabelled KVM")

    def test_fresh_vars_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(ovmfVarsSourceDigest="c" * 64), argv=ARGV_CRB,
            marker="labelled fresh")

    def test_fresh_tpm_state_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(tpmStateSourceManifest=[{"path": "x"}]), argv=ARGV_CRB,
            marker="reused state labelled fresh")

    def test_timeout_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(resetClassification="HARNESS_TIMEOUT"), argv=ARGV_CRB,
            marker="timeout is not a reset",
            repaired=record(resetClassification="HARNESS_TIMEOUT",
                            guestResetCount=0, result="FAIL",
                            stagesReached=["firmware-bds"], lastStage="firmware-bds"))

    def test_screenshot_check_is_attributable(self) -> None:
        self.assert_attributable(
            tampered=record(classificationBasis=["screenshot only"]), argv=ARGV_CRB,
            marker="screenshot")

    def test_grub_success_check_is_attributable(self) -> None:
        tampered = record(stagesReached=["grub-menu"], lastStage="grub-menu",
                          guestResetCount=0)
        tampered.pop("resetClassification")
        tampered.pop("classificationBasis")
        self.assert_attributable(
            tampered=tampered, argv=ARGV_CRB, marker="not booting")

    def test_binding_archive_check_is_attributable(self) -> None:
        tampered = record(sourceArchiveDigest="f" * 64)
        reasons = verify_record_binding(tampered, CONTEXT)
        self.assertTrue(any("sourceArchiveDigest" in r for r in reasons))
        # Mutate the context to match the forged digest: the fraud is gone,
        # the refusal must be gone with it.
        agreed = replace(CONTEXT, sourceArchiveDigest="f" * 64)
        self.assertFalse(any("sourceArchiveDigest" in r
                             for r in verify_record_binding(tampered, agreed)))

    def test_binding_machine_pin_is_attributable(self) -> None:
        tampered = record(machineType="pc-q35-9.2")
        reasons = verify_record_binding(tampered, CONTEXT)
        self.assertTrue(any("machineType" in r for r in reasons))
        declared = record(machineType="pc-q35-9.2", diagnostic=True)
        self.assertFalse(any("machineType" in r
                             for r in verify_record_binding(declared, CONTEXT)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from installer.drivers.policy import firmware_policy, graphics_driver
from installer.hardware.preflight import classify, minimum_requirements
from installer.hardware.probe import probe


class HardwareTests(unittest.TestCase):
    def test_legacy_bios_is_unsupported(self) -> None:
        value = classify(architecture="x86_64", ram_bytes=8 * 1024**3, storage_bytes=64 * 1024**3, firmware_mode="bios", secure_boot="unknown", tpm_present=False)
        self.assertEqual(value["overall"], "unsupported")

    def test_nvidia_proprietary_is_not_automatically_offered(self) -> None:
        value = graphics_driver("NVIDIA Corporation", secure_boot="enabled")
        self.assertFalse(value["proprietaryOffered"])
        self.assertEqual(value["status"], "experimental")

    def test_firmware_sources_are_bounded(self) -> None:
        self.assertFalse(firmware_policy()["arbitraryVendorDownloads"])

    def test_requirements_do_not_invent_benchmarks(self) -> None:
        self.assertIn("No local-model", minimum_requirements()["benchmarkClaim"])

    def test_host_probe_never_claims_physical_certification(self) -> None:
        self.assertFalse(probe(storage_bytes=64 * 1024**3)["physicalHardwareCertified"])

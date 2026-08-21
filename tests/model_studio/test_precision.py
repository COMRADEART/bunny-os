# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The precision rule, on five machines and against four explicit requests.

The regression this file exists for: ``if cuda: bf16``. It passes every test
somebody writes on an Ampere laptop and produces NaNs on a Turing one.
"""

from __future__ import annotations

import unittest

from model_studio.hardware.probe import (
    SUPPORTED,
    UNKNOWN,
    UNSUPPORTED,
    Accelerator,
    cpu_accelerator,
    probe_hardware,
)
from model_studio.hardware.precision import select_precision
from tests.model_studio.support import cpu_torch, cuda_torch, mps_torch


def _cuda(name: str, capability: tuple[int, int], bf16: str) -> Accelerator:
    return Accelerator(
        kind="cuda", name=name, vendor="nvidia", vram_bytes=8 * 1024 ** 3,
        compute_capability=capability, bf16=bf16, fp16=SUPPORTED,
    )


class PrecisionRule(unittest.TestCase):
    def test_ampere_and_later_get_bfloat16(self) -> None:
        for name, capability in (
            ("NVIDIA A100", (8, 0)),
            ("NVIDIA GeForce RTX 3050 Laptop GPU", (8, 6)),
            ("NVIDIA GeForce RTX 4050 Laptop GPU", (8, 9)),
            ("NVIDIA H100", (9, 0)),
        ):
            with self.subTest(name=name):
                decision = select_precision(_cuda(name, capability, SUPPORTED))
                self.assertEqual(decision.dtype, "bf16")
                self.assertTrue(decision.honoured)

    def test_turing_falls_to_float16(self) -> None:
        decision = select_precision(_cuda("NVIDIA GeForce RTX 2060", (7, 5), UNSUPPORTED))
        self.assertEqual(decision.dtype, "fp16")
        self.assertIn("does not support bfloat16", decision.reason)

    def test_pascal_falls_to_float16(self) -> None:
        decision = select_precision(_cuda("NVIDIA GeForce GTX 1080", (6, 1), UNSUPPORTED))
        self.assertEqual(decision.dtype, "fp16")

    def test_cpu_is_float32(self) -> None:
        decision = select_precision(cpu_accelerator("no torch"))
        self.assertEqual(decision.dtype, "fp32")

    def test_unknown_capability_never_resolves_to_bfloat16(self) -> None:
        """The rule that separates this from `if cuda: bf16`."""
        decision = select_precision(_cuda("NVIDIA T4", (7, 5), UNKNOWN))
        self.assertEqual(decision.dtype, "fp16")
        self.assertIn("could not be queried", decision.reason)

    def test_unknown_everything_is_float32(self) -> None:
        accelerator = Accelerator(kind="cuda", name="cuda device", bf16=UNKNOWN, fp16=UNKNOWN)
        self.assertEqual(select_precision(accelerator).dtype, "fp32")

    def test_metal_uses_its_own_supported_type(self) -> None:
        accelerator = Accelerator(kind="mps", name="Apple Metal", bf16=UNSUPPORTED, fp16=SUPPORTED)
        self.assertEqual(select_precision(accelerator).dtype, "fp16")
        newer = Accelerator(kind="mps", name="Apple Metal", bf16=SUPPORTED, fp16=SUPPORTED)
        self.assertEqual(select_precision(newer).dtype, "bf16")


class ExplicitRequests(unittest.TestCase):
    def test_a_supported_request_is_honoured(self) -> None:
        decision = select_precision(_cuda("A100", (8, 0), SUPPORTED), requested="bf16")
        self.assertEqual(decision.dtype, "bf16")
        self.assertTrue(decision.honoured)

    def test_an_unsupported_request_is_refused_not_downgraded(self) -> None:
        decision = select_precision(_cuda("RTX 2060", (7, 5), UNSUPPORTED), requested="bf16")
        self.assertFalse(decision.honoured)
        self.assertEqual(decision.dtype, "fp16", "the fallback is reported, but not as honoured")
        self.assertIn("does not support it", decision.reason)

    def test_float32_is_honoured_anywhere(self) -> None:
        for accelerator in (cpu_accelerator(""), _cuda("A100", (8, 0), SUPPORTED)):
            decision = select_precision(accelerator, requested="fp32")
            self.assertEqual(decision.dtype, "fp32")
            self.assertTrue(decision.honoured)

    def test_an_unknown_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_precision(cpu_accelerator(""), requested="int4")


class ProbeAgainstFakedRuntimes(unittest.TestCase):
    """The probe end of the same question: what each torch produces."""

    def test_cuda_runtime(self) -> None:
        report = probe_hardware(torch_module=cuda_torch(capability=(8, 9), bf16=True))
        self.assertEqual(report.accelerator.kind, "cuda")
        self.assertEqual(report.accelerator.bf16, SUPPORTED)
        self.assertEqual(report.accelerator.compute_capability, (8, 9))
        self.assertEqual(select_precision(report.accelerator).dtype, "bf16")

    def test_no_cuda_runtime(self) -> None:
        report = probe_hardware(torch_module=cpu_torch())
        self.assertEqual(report.accelerator.kind, "cpu")
        self.assertIn("CPU build", report.accelerator.detail)
        self.assertEqual(select_precision(report.accelerator).dtype, "fp32")

    def test_cuda_build_with_no_device(self) -> None:
        report = probe_hardware(torch_module=cpu_torch(version="2.9.1", cuda_build="12.8"))
        self.assertEqual(report.accelerator.kind, "cpu")
        self.assertIn("built against CUDA 12.8", report.accelerator.detail)

    def test_old_torch_without_the_bfloat16_query(self) -> None:
        """No ``is_bf16_supported``: fall back to the architecture, never upward."""
        report = probe_hardware(torch_module=cuda_torch(capability=(7, 5), bf16=None))
        self.assertEqual(report.accelerator.bf16, UNSUPPORTED)
        ampere = probe_hardware(torch_module=cuda_torch(capability=(8, 0), bf16=None))
        self.assertEqual(ampere.accelerator.bf16, SUPPORTED)

    def test_metal(self) -> None:
        report = probe_hardware(torch_module=mps_torch())
        self.assertEqual(report.accelerator.kind, "mps")
        self.assertIsNone(report.accelerator.vram_bytes, "unified memory has no VRAM figure")

    def test_absent_torch_is_a_cpu_report_not_a_crash(self) -> None:
        report = probe_hardware(torch_module=None)
        self.assertEqual(report.accelerator.kind, "cpu")
        self.assertIsNotNone(report.disk_free_bytes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

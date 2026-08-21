# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Detection, planning and preflight — including the verdicts nobody wants.

``UNKNOWN`` is tested as carefully as ``BLOCKED``, because the failure this
subsystem is built against is a preflight that returns READY on the grounds
that nothing said no.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from model_studio.backend import DEFAULT_BACKEND, available_backends, get_backend
from model_studio.backend.base import BLOCKED, READY, UNKNOWN, combine_status
from model_studio.config import config_from_mapping
from model_studio.datasets.chat import load_chat_dataset
from model_studio.errors import ConfigurationError
from model_studio.hardware.probe import (
    SUPPORTED,
    Accelerator,
    HardwareReport,
    ObservedGpu,
    cpu_accelerator,
)
from model_studio.models import resolve_base_model
from tests.model_studio.support import simple_conversations, write_dataset, write_model_config

_MODULE = "model_studio.backend.transformers_lora"


def _hardware(*, accelerator=None, ram=32 * 1024 ** 3, disk=100 * 1024 ** 3,
              observed=()) -> HardwareReport:
    return HardwareReport(
        cpu_model="test cpu",
        cpu_logical=8,
        ram_total_bytes=ram,
        ram_available_bytes=ram,
        disk_path="/tmp",
        disk_free_bytes=disk,
        accelerator=accelerator or cpu_accelerator("a test machine"),
        observed_gpus=tuple(observed),
        torch_version="2.9.1",
    )


def _cuda(vram: int, *, name: str = "NVIDIA GeForce RTX 4050 Laptop GPU") -> Accelerator:
    return Accelerator(
        kind="cuda", name=name, vendor="nvidia", vram_bytes=vram, vram_free_bytes=vram,
        compute_capability=(8, 9), bf16=SUPPORTED, fp16=SUPPORTED, detail="torch 2.11 CUDA 12.8",
    )


class Registry(unittest.TestCase):
    def test_the_default_backend_exists(self) -> None:
        self.assertIn(DEFAULT_BACKEND, available_backends())
        self.assertEqual(get_backend().backend_id, DEFAULT_BACKEND)

    def test_an_unknown_backend_is_refused_by_name(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            get_backend("soup")
        self.assertIn("this build has", str(caught.exception))


class Verdict(unittest.TestCase):
    def test_blocked_beats_unknown_beats_ready(self) -> None:
        self.assertEqual(combine_status(blocking=["a"], unknowns=["b"]), BLOCKED)
        self.assertEqual(combine_status(blocking=[], unknowns=["b"]), UNKNOWN)
        self.assertEqual(combine_status(blocking=[], unknowns=[]), READY)


class Detection(unittest.TestCase):
    def test_absence_is_a_result_with_an_instruction(self) -> None:
        status = get_backend().detect()
        self.assertIsInstance(status.available, bool)
        if not status.available:
            self.assertTrue(status.missing)
            self.assertIn("pip install", status.detail)
            self.assertNotIn("lora", status.capabilities)


class Planning(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        self.dataset_path = write_dataset(self.root / "data.jsonl", simple_conversations(20))
        self.config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", "epochs": 2, "batch_size": 2, "seed": 5},
                "dataset": {"path": str(self.dataset_path), "validation_split": 0.25},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        self.dataset = load_chat_dataset(self.dataset_path)
        self.model = resolve_base_model(str(self.root / "base"))

    def _plan(self, accelerator=None):
        return get_backend().prepare(
            self.config,
            hardware=_hardware(accelerator=accelerator),
            model=self.model,
            dataset=self.dataset,
        )

    def test_the_plan_names_every_decision(self) -> None:
        plan = self._plan(_cuda(6 * 1024 ** 3))
        self.assertEqual(plan.method, "lora")
        self.assertEqual(plan.precision.dtype, "bf16")
        self.assertEqual(plan.batch_size, 2)
        self.assertIn("given in the configuration", plan.batch_size_reason)
        self.assertEqual(plan.target_modules, ("q_proj", "k_proj", "v_proj", "o_proj"))
        self.assertIn("llama decoder", plan.target_modules_source)
        self.assertEqual(plan.training_examples, 15)
        self.assertEqual(plan.validation_examples, 5)
        self.assertEqual(plan.optimizer_steps, 16, "8 batches of 2 over 2 epochs")
        self.assertIsNotNone(plan.memory)

    def test_the_cpu_plan_is_float32(self) -> None:
        self.assertEqual(self._plan().precision.dtype, "fp32")

    def test_auto_batch_size_is_resolved_with_a_reason(self) -> None:
        config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", "batch_size": "auto"},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        plan = get_backend().prepare(
            config,
            hardware=_hardware(accelerator=_cuda(24 * 1024 ** 3)),
            model=self.model,
            dataset=self.dataset,
        )
        self.assertGreaterEqual(plan.batch_size, 1)
        self.assertIn("measured free", plan.batch_size_reason)

    def test_max_steps_caps_the_run(self) -> None:
        config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", "epochs": 10, "batch_size": 1, "max_steps": 3},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        plan = get_backend().prepare(config, hardware=_hardware(), model=self.model,
                                     dataset=self.dataset)
        self.assertEqual(plan.optimizer_steps, 3)


class Preflight(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        self.dataset_path = write_dataset(self.root / "data.jsonl", simple_conversations(8))

    def _config(self, **training):
        return config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", **training},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )

    def _report(self, hardware, config=None, available=True):
        backend = get_backend()
        with mock.patch(f"{_MODULE}.probe_hardware", return_value=hardware), \
             mock.patch.object(
                 backend, "detect",
                 return_value=type(backend.detect())(
                     backend_id="transformers-lora", available=available,
                     detail="ready" if available else "torch not installed",
                     capabilities=("lora",) if available else (),
                 ),
             ):
            return backend.preflight(config or self._config())

    def test_a_capable_machine_is_ready(self) -> None:
        report = self._report(_hardware(accelerator=_cuda(8 * 1024 ** 3)))
        self.assertEqual(report.status, READY, report.blocking + report.unknowns)
        self.assertIsNotNone(report.plan)

    def test_too_little_vram_blocks_with_the_arithmetic(self) -> None:
        report = self._report(_hardware(accelerator=_cuda(64 * 1024 ** 2)))
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("derived requirement" in line for line in report.blocking))

    def test_unmeasurable_vram_is_unknown_not_ready(self) -> None:
        """A machine that will not say how much memory it has does not get a pass."""
        blind = Accelerator(kind="cuda", name="cuda device", vendor="nvidia",
                            bf16=SUPPORTED, fp16=SUPPORTED)
        report = self._report(_hardware(accelerator=blind))
        self.assertEqual(report.status, UNKNOWN)
        self.assertTrue(any("could not be measured" in line for line in report.unknowns))

    def test_a_missing_base_model_blocks_and_says_how_to_fix_it(self) -> None:
        config = config_from_mapping(
            {
                "model": {"base": str(self.root / "nowhere")},
                "training": {"method": "lora"},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        report = self._report(_hardware(), config)
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("--allow-model-download" in line for line in report.blocking))

    def test_an_unavailable_backend_blocks(self) -> None:
        report = self._report(_hardware(), available=False)
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("not available" in line for line in report.blocking))

    def test_an_impossible_precision_blocks_rather_than_downgrades(self) -> None:
        turing = Accelerator(kind="cuda", name="RTX 2060", vendor="nvidia",
                             vram_bytes=8 * 1024 ** 3, vram_free_bytes=8 * 1024 ** 3,
                             compute_capability=(7, 5), bf16="unsupported", fp16=SUPPORTED)
        report = self._report(_hardware(accelerator=turing), self._config(precision="bf16"))
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("cannot provide it" in line for line in report.blocking))

    def test_a_present_but_unusable_gpu_is_a_warning(self) -> None:
        report = self._report(_hardware(
            observed=(ObservedGpu(name="NVIDIA RTX 4050", vendor="nvidia",
                                  vram_bytes=6 * 1024 ** 3, source="nvidia-smi"),),
        ))
        self.assertTrue(any("cannot use it" in line for line in report.warnings))

    def test_a_bad_dataset_blocks_preflight(self) -> None:
        bad = self.root / "bad.jsonl"
        bad.write_text("{}\n", encoding="utf-8")
        config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora"},
                "dataset": {"path": str(bad)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        report = self._report(_hardware(), config)
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("dataset:" in line for line in report.blocking))

    def test_qlora_without_the_capability_blocks(self) -> None:
        config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "qlora"},
                "quantization": {"enabled": True, "bits": 4},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        report = self._report(_hardware(accelerator=_cuda(8 * 1024 ** 3)), config)
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("QLoRA is not available" in line for line in report.blocking))

    def test_no_disk_space_blocks(self) -> None:
        report = self._report(_hardware(accelerator=_cuda(8 * 1024 ** 3), disk=1024))
        self.assertEqual(report.status, BLOCKED)
        self.assertTrue(any("free on" in line for line in report.blocking))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

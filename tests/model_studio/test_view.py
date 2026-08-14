# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI contract: a screen can be drawn from a blocked report as well as a ready one."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from model_studio.backend.base import BLOCKED, READY, UNKNOWN, BackendStatus, PreflightReport
from model_studio.config import config_from_mapping
from model_studio.datasets.chat import load_chat_dataset
from model_studio.hardware.precision import select_precision
from model_studio.hardware.probe import SUPPORTED, Accelerator, HardwareReport, cpu_accelerator
from model_studio.models import resolve_base_model
from model_studio.backend import get_backend
from model_studio.view import build_view
from tests.model_studio.support import simple_conversations, write_dataset, write_model_config


class ViewContract(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        self.dataset_path = write_dataset(self.root / "bunny-personal.jsonl",
                                          simple_conversations(842 // 100))
        self.config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", "batch_size": 1},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )
        self.dataset = load_chat_dataset(self.dataset_path)
        self.model = resolve_base_model(str(self.root / "base"))

    def _report(self, accelerator, *, capabilities=("lora",), status=READY,
                blocking=(), unknowns=()) -> PreflightReport:
        hardware = HardwareReport(
            cpu_model="test", cpu_logical=8, ram_total_bytes=32 * 1024 ** 3,
            ram_available_bytes=16 * 1024 ** 3, disk_free_bytes=100 * 1024 ** 3,
            disk_path="/tmp", accelerator=accelerator,
        )
        plan = get_backend().prepare(
            self.config, hardware=hardware, model=self.model, dataset=self.dataset
        )
        return PreflightReport(
            backend=BackendStatus(
                backend_id="transformers-lora", available=True, detail="ready",
                capabilities=capabilities,
            ),
            status=status,
            hardware=hardware,
            model=self.model,
            precision=select_precision(accelerator),
            plan=plan,
            dataset=self.dataset.to_json(),
            blocking=blocking,
            unknowns=unknowns,
        )

    def test_a_ready_screen_has_a_bar_and_an_enabled_button(self) -> None:
        accelerator = Accelerator(
            kind="cuda", name="NVIDIA GeForce RTX 3050 Laptop GPU", vendor="nvidia",
            vram_bytes=4 * 1024 ** 3, vram_free_bytes=4 * 1024 ** 3,
            compute_capability=(8, 6), bf16=SUPPORTED, fp16=SUPPORTED,
        )
        view = build_view(self._report(accelerator), self.config)
        self.assertTrue(view.start.enabled)
        self.assertEqual(view.start.blocked_by, ())
        self.assertEqual(view.device.name, "NVIDIA GeForce RTX 3050 Laptop GPU")
        self.assertIsNotNone(view.device.fraction)
        self.assertLessEqual(view.device.fraction, 1.0)
        self.assertIn("/", view.device.caption)
        self.assertTrue(view.base_model.ok)
        self.assertIn("conversations", view.dataset.detail)

    def test_qlora_is_shown_disabled_with_a_reason_not_hidden(self) -> None:
        view = build_view(
            self._report(cpu_accelerator("no torch"), capabilities=("lora",)), self.config
        )
        identifiers = [option.identifier for option in view.methods]
        self.assertEqual(identifiers, ["lora", "qlora"], "both must be offered")
        qlora = next(option for option in view.methods if option.identifier == "qlora")
        self.assertFalse(qlora.available)
        self.assertTrue(qlora.detail, "a disabled option must say why")

    def test_an_unmeasurable_device_has_no_bar_and_says_unknown(self) -> None:
        blind = Accelerator(kind="cuda", name="cuda device", vendor="nvidia",
                            bf16=SUPPORTED, fp16=SUPPORTED)
        view = build_view(
            self._report(blind, status=UNKNOWN, unknowns=("VRAM could not be measured",)),
            self.config,
        )
        self.assertIsNone(view.device.fraction, "there is nothing to divide by")
        self.assertIn("UNKNOWN", view.device.caption)
        self.assertFalse(view.start.enabled)

    def test_a_blocked_screen_lists_every_reason(self) -> None:
        view = build_view(
            self._report(cpu_accelerator("no torch"), status=BLOCKED,
                         blocking=("not enough VRAM", "no peft")),
            self.config,
        )
        self.assertFalse(view.start.enabled)
        self.assertEqual(view.start.blocked_by, ("not enough VRAM", "no peft"))

    def test_a_cpu_machine_reports_ram_as_its_denominator(self) -> None:
        view = build_view(self._report(cpu_accelerator("torch is a CPU build")), self.config)
        self.assertEqual(view.device.kind, "cpu")
        self.assertEqual(view.device.total_bytes, 32 * 1024 ** 3)

    def test_it_serialises_to_json(self) -> None:
        view = build_view(self._report(cpu_accelerator("")), self.config)
        document = view.to_json()
        for key in ("baseModel", "dataset", "methods", "device", "precision", "start"):
            self.assertIn(key, document)
        self.assertIn("blockedBy", document["start"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

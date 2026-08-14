# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real one. A real model, a real optimizer, real weights on disk.

This is the only test in the suite that proves anything about training, and it
is the only one that is skipped by default. Both facts are deliberate:

* ``make test`` must never download a model or occupy a GPU, so this needs
  ``BUNNY_MODEL_STUDIO_HEAVY=1`` before it will run at all;
* every other test in this directory describes a *rule* — the precision
  decision, the state machine, the estimate. None of them establishes that the
  rules add up to a trained adapter. This does, and it is what the milestone's
  evidence gate rests on.

What it asserts is the gate itself, in order: the adapter loads back from disk,
at least one trainable tensor moved from where it started, and the held-out loss
is not the base model's. A process exiting zero is not on the list.

Set ``BUNNY_MODEL_STUDIO_BASE`` to a local model directory to run offline. With
``BUNNY_MODEL_STUDIO_ALLOW_DOWNLOAD=1`` it will fetch the base model — an
explicit approval, in an environment variable somebody had to type, which is the
same rule the CLI enforces with a flag.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

HEAVY = os.environ.get("BUNNY_MODEL_STUDIO_HEAVY", "") == "1"


@unittest.skipUnless(HEAVY, "set BUNNY_MODEL_STUDIO_HEAVY=1 to run the real training slice")
class TrainingSlice(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        from model_studio.backend import get_backend
        from model_studio.models import resolve_base_model
        from model_studio.network import NetworkPolicy

        status = get_backend().detect()
        if not status.available:
            raise unittest.SkipTest(f"the training backend is not installed: {status.detail}")

        cls.base = os.environ.get("BUNNY_MODEL_STUDIO_BASE", "").strip() \
            or "HuggingFaceTB/SmolLM2-135M-Instruct"
        cls.allow_download = os.environ.get("BUNNY_MODEL_STUDIO_ALLOW_DOWNLOAD", "") == "1"
        cls.policy = NetworkPolicy(
            allow_model_download=cls.allow_download,
            reason="BUNNY_MODEL_STUDIO_ALLOW_DOWNLOAD=1 in the test environment",
        )
        resolved = resolve_base_model(cls.base, policy=cls.policy)
        if not resolved.present and not cls.allow_download:
            raise unittest.SkipTest(
                f"{cls.base} is not on this machine and no download was approved; "
                "set BUNNY_MODEL_STUDIO_BASE to a local directory or "
                "BUNNY_MODEL_STUDIO_ALLOW_DOWNLOAD=1"
            )

    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.output = self.root / "run"

    def _config(self, **training):
        from model_studio.config import config_from_mapping

        corpus = (
            Path(__file__).resolve().parents[2]
            / "model_studio/examples/bunny-companion-demo.jsonl"
        )
        return config_from_mapping(
            {
                "model": {"base": self.base},
                "training": {
                    "method": "lora", "epochs": 1, "batch_size": 2, "max_length": 256,
                    "learning_rate": 0.0005, "seed": 20260813, **training,
                },
                "lora": {"rank": 8, "alpha": 16},
                "dataset": {"path": str(corpus), "validation_split": 0.2},
                "output": {"directory": str(self.output), "overwrite": True},
            },
            base_directory=self.root,
        )

    def _studio(self):
        from model_studio.jobs import JobStore
        from model_studio.studio import ModelStudio

        return ModelStudio(store=JobStore(self.root / "jobs"), network=self.policy)

    def test_the_whole_path_end_to_end(self) -> None:
        from model_studio.jobs import state as machine

        record = self._studio().run(self._config())
        self.assertEqual(record.state, machine.COMPLETED, record.detail)

        evaluation = record.evaluation
        self.assertTrue(evaluation["reloadOk"], "the adapter must load back from disk")
        self.assertGreater(
            evaluation["adapterTensorsChanged"], 0,
            "at least one trainable tensor must have moved from its initial value; "
            "an adapter that did not is indistinguishable from no adapter",
        )
        self.assertGreater(evaluation["maxAbsoluteDelta"], 0.0)
        self.assertIsNotNone(evaluation["baselineLoss"])
        self.assertIsNotNone(evaluation["adapterLoss"])
        self.assertNotEqual(
            evaluation["baselineLoss"], evaluation["adapterLoss"],
            "with the adapter disabled the model must behave differently",
        )

        result = record.result
        self.assertGreater(result["steps"], 0)
        self.assertIsNotNone(result["finalLoss"])
        self.assertGreater(result["trainableParameters"], 0)
        self.assertLess(
            result["trainableParameters"], result["totalParameters"] / 50,
            "LoRA trains a small fraction; a large one means the base was not frozen",
        )

    def test_the_artifacts_are_a_peft_adapter(self) -> None:
        self._studio().run(self._config())
        adapter = self.output / "adapter"
        self.assertTrue((adapter / "adapter_config.json").is_file())
        self.assertTrue((adapter / "adapter_model.safetensors").is_file())
        configuration = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
        self.assertEqual(configuration["peft_type"], "LORA")
        self.assertEqual(configuration["r"], 8)

    def test_the_manifest_and_provenance_describe_what_is_there(self) -> None:
        from model_studio.artifacts import RunArtifacts

        record = self._studio().run(self._config())
        self.assertEqual(RunArtifacts(directory=self.output).verify(), [])
        provenance = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["status"], "completed")
        self.assertEqual(provenance["job_id"], record.job_id)
        self.assertNotEqual(provenance["torch_version"], "absent")
        self.assertNotEqual(provenance["peft_version"], "absent")
        self.assertTrue(provenance["adapter_sha256"])
        self.assertIn(provenance["precision"], ("bf16", "fp16", "fp32"))

    def test_the_estimate_is_not_wildly_wrong(self) -> None:
        """The estimate is a planning tool; this checks it is in the right postcode."""
        record = self._studio().run(self._config())
        measured = record.result.get("peakDeviceMemoryBytes")
        if not measured:
            self.skipTest("no device peak was measured (CPU run)")
        estimated = record.plan["memory"]["totalBytes"]
        ratio = measured / estimated
        self.assertGreater(ratio, 0.2, f"estimate {estimated} vs measured {measured}")
        self.assertLess(ratio, 5.0, f"estimate {estimated} vs measured {measured}")

    def test_a_cancelled_run_saves_no_adapter(self) -> None:
        from model_studio.backend.base import CancellationSignal
        from model_studio.jobs import state as machine

        signal = CancellationSignal()
        signal.cancel("cancelled by the test before the first step")
        record = self._studio().run(self._config(), cancellation=signal)
        self.assertEqual(record.state, machine.CANCELLED)
        self.assertFalse((self.output / "adapter").exists())
        provenance = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["status"], "cancelled")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

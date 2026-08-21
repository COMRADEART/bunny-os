# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestration: every outcome a run can have, on a machine with no GPU.

The four that matter are the unhappy ones. A run that is blocked, one that
fails, one that is cancelled halfway, and — the one this whole subsystem is
built around — one that trains without error and produces an adapter that
learned nothing. The last must end in ``failed``, because a process exiting zero
is not evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from model_studio.backend.base import (
    BLOCKED,
    READY,
    BackendStatus,
    EvaluationResult,
    PreflightReport,
    TrainingResult,
)
from model_studio.config import config_from_mapping
from model_studio.datasets.chat import load_chat_dataset
from model_studio.hardware.precision import select_precision
from model_studio.hardware.probe import HardwareReport, cpu_accelerator
from model_studio.jobs import JobStore, state as machine
from model_studio.models import resolve_base_model
from model_studio.studio import ModelStudio
from tests.model_studio.support import simple_conversations, write_dataset, write_model_config
from model_studio.backend import get_backend


class _FakeBackend:
    """A backend that does everything except arithmetic, and can be told to fail."""

    backend_id = "fake"

    def __init__(self, *, outcome: str = "ok", changed: int = 4) -> None:
        self.outcome = outcome
        self.changed = changed
        self.cancelled_ids: list[str] = []
        self.real = get_backend()

    def detect(self) -> BackendStatus:
        return BackendStatus(backend_id="fake", available=True, detail="ready",
                             capabilities=("lora",))

    def prepare(self, config, **keywords):
        return self.real.prepare(config, hardware=_hardware(), **keywords)

    def preflight(self, config) -> PreflightReport:
        model = resolve_base_model(config.model.base)
        dataset = load_chat_dataset(config.dataset_path)
        plan = self.prepare(config, model=model, dataset=dataset)
        blocking = ("a test made this machine unsuitable",) if self.outcome == "blocked" else ()
        return PreflightReport(
            backend=self.detect(),
            status=BLOCKED if blocking else READY,
            hardware=_hardware(),
            model=model,
            precision=select_precision(cpu_accelerator("test")),
            plan=plan,
            dataset=dataset.to_json(),
            blocking=blocking,
        )

    def train(self, job, *, progress=None, cancellation=None) -> TrainingResult:
        job.artifacts.append_log({"kind": "phase", "detail": "fake training"})
        if self.outcome == "failed":
            return TrainingResult(job_id=job.job_id, ok=False,
                                  output_directory=str(job.artifacts.directory),
                                  failure="the fake backend was told to fail")
        if self.outcome == "cancelled":
            return TrainingResult(job_id=job.job_id, ok=False, cancelled=True,
                                  output_directory=str(job.artifacts.directory),
                                  failure="cancelled before the adapter was saved")
        adapter = job.artifacts.adapter_directory
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / "adapter_config.json").write_text('{"peft_type": "LORA"}', encoding="utf-8")
        (adapter / "adapter_model.safetensors").write_bytes(b"weights")
        return TrainingResult(
            job_id=job.job_id, ok=True,
            output_directory=str(job.artifacts.directory),
            adapter_directory=str(adapter),
            steps=6, epochs_completed=1, initial_loss=2.5, final_loss=1.1,
            loss_history=((1, 2.5), (6, 1.1)), trainable_parameters=1234,
            total_parameters=134_515_008, adapter_bytes=7, precision="fp32", device="cpu",
        )

    def cancel(self, job_id: str) -> None:
        self.cancelled_ids.append(job_id)

    def evaluate(self, result: TrainingResult) -> EvaluationResult:
        return EvaluationResult(
            job_id=result.job_id,
            ok=self.changed > 0,
            reload_ok=True,
            adapter_tensors_changed=self.changed,
            adapter_tensors_total=4,
            max_absolute_delta=0.01 if self.changed else 0.0,
            baseline_loss=2.4,
            adapter_loss=1.2 if self.changed else 2.4,
            detail="changed" if self.changed else "no adapter tensor moved",
        )


def _hardware() -> HardwareReport:
    return HardwareReport(
        cpu_model="test", cpu_logical=4, ram_total_bytes=16 * 1024 ** 3,
        ram_available_bytes=8 * 1024 ** 3, disk_free_bytes=50 * 1024 ** 3,
        disk_path="/tmp", accelerator=cpu_accelerator("a test machine"),
    )


class Runs(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        self.dataset_path = write_dataset(self.root / "data.jsonl", simple_conversations(8))
        self.output = self.root / "out"
        self.config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora", "batch_size": 2, "epochs": 1},
                "dataset": {"path": str(self.dataset_path), "validation_split": 0.25},
                "output": {"directory": str(self.output)},
            },
            base_directory=self.root,
        )

    def _studio(self, **keywords) -> ModelStudio:
        return ModelStudio(
            store=JobStore(self.root / "jobs", boot_id="boot-a"),
            backend=_FakeBackend(**keywords),
        )

    def test_a_good_run_reaches_completed_through_evaluating(self) -> None:
        record = self._studio().run(self.config)
        self.assertEqual(record.state, machine.COMPLETED)
        became = [change.became for change in record.history]
        self.assertEqual(became, [
            machine.CREATED, machine.PREFLIGHTING, machine.READY, machine.PREPARING,
            machine.TRAINING, machine.EVALUATING, machine.COMPLETED,
        ])

    def test_a_good_run_writes_every_artifact(self) -> None:
        record = self._studio().run(self.config)
        for name in ("config.snapshot.json", "preflight.json", "training-metadata.json",
                     "training-log.jsonl", "evaluation.json", "provenance.json",
                     "MANIFEST.json"):
            self.assertTrue((self.output / name).is_file(), f"{name} was not written")
        self.assertTrue((self.output / "adapter/adapter_config.json").is_file())
        self.assertTrue((self.output / "adapter/adapter_model.safetensors").is_file())
        self.assertEqual(record.state, machine.COMPLETED)

    def test_provenance_traces_the_run_to_its_inputs(self) -> None:
        record = self._studio().run(self.config)
        document = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        dataset = load_chat_dataset(self.dataset_path)
        self.assertEqual(document["status"], "completed")
        self.assertEqual(document["dataset_sha256"], dataset.sha256)
        self.assertEqual(document["config_sha256"], self.config.file_sha256)
        self.assertEqual(document["config_canonical_sha256"], self.config.canonical_sha256)
        self.assertEqual(document["base_model"], self.config.model.base)
        self.assertTrue(document["bunny_commit"])
        self.assertTrue(document["adapter_sha256"], "the weights must be digested")
        self.assertEqual(document["steps"], 6)
        self.assertEqual(document["final_loss"], 1.1)
        self.assertIn("torch_version", document)
        self.assertIs(document["network_policy"]["allowUpload"], False)

    def test_the_manifest_matches_what_was_written(self) -> None:
        from model_studio.artifacts import RunArtifacts

        self._studio().run(self.config)
        self.assertEqual(RunArtifacts(directory=self.output).verify(), [])

    def test_a_blocked_preflight_stops_before_any_artifact(self) -> None:
        record = self._studio(outcome="blocked").run(self.config)
        self.assertEqual(record.state, machine.BLOCKED)
        self.assertIn("unsuitable", record.detail)
        self.assertFalse(self.output.exists(), "a blocked run writes nothing")

    def test_a_failed_run_ends_failed_and_still_leaves_provenance(self) -> None:
        record = self._studio(outcome="failed").run(self.config)
        self.assertEqual(record.state, machine.FAILED)
        self.assertIn("told to fail", record.detail)
        document = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "failed")

    def test_a_cancelled_run_ends_cancelled_and_says_so_in_provenance(self) -> None:
        record = self._studio(outcome="cancelled").run(self.config)
        self.assertEqual(record.state, machine.CANCELLED)
        document = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "cancelled")
        self.assertFalse((self.output / "adapter").exists(),
                         "a cancelled run must not leave an adapter that looks finished")

    def test_an_adapter_that_learned_nothing_fails_the_run(self) -> None:
        """Training exited without error. That is not the same as having trained."""
        record = self._studio(changed=0).run(self.config)
        self.assertEqual(record.state, machine.FAILED)
        self.assertIn("evaluation refused it", record.detail)
        self.assertIn("no adapter tensor moved", record.detail)
        self.assertEqual(
            json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))["status"],
            "failed",
        )

    def test_a_second_run_into_the_same_directory_is_refused(self) -> None:
        self._studio().run(self.config)
        record = self._studio().run(self.config)
        self.assertEqual(record.state, machine.FAILED)
        self.assertIn("already holds a run", record.detail)

    def test_overwrite_allows_it(self) -> None:
        self._studio().run(self.config)
        config = config_from_mapping(
            {**json.loads(json.dumps(self.config.to_json())),
             "output": {"directory": str(self.output), "overwrite": True}},
            base_directory=self.root,
        )
        self.assertEqual(self._studio().run(config).state, machine.COMPLETED)

    def test_the_job_is_listed_and_inspectable(self) -> None:
        studio = self._studio()
        record = studio.run(self.config)
        self.assertEqual([item.job_id for item in studio.jobs()], [record.job_id])
        self.assertEqual(studio.inspect(record.job_id).state, machine.COMPLETED)

    def test_cancel_reports_when_there_is_nothing_to_cancel(self) -> None:
        self.assertFalse(self._studio().cancel("no-such-job"))

    def test_a_job_never_ends_in_an_active_state(self) -> None:
        for keywords in ({}, {"outcome": "failed"}, {"outcome": "cancelled"},
                         {"outcome": "blocked"}, {"changed": 0}):
            with self.subTest(keywords=keywords):
                scratch = tempfile.TemporaryDirectory()
                self.addCleanup(scratch.cleanup)
                config = config_from_mapping(
                    {**json.loads(json.dumps(self.config.to_json())),
                     "output": {"directory": str(Path(scratch.name) / "out")}},
                    base_directory=self.root,
                )
                record = ModelStudio(
                    store=JobStore(Path(scratch.name) / "jobs", boot_id="b"),
                    backend=_FakeBackend(**keywords),
                ).run(config)
                self.assertNotIn(record.state, machine.ACTIVE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

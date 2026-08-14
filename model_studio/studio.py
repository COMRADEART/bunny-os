# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The facade: the thing a CLI, and one day a window, actually talks to.

Two responsibilities, and keeping them here rather than in the backend is the
design:

**It owns the state machine.** Every transition in a run's life is written by
this class. A backend cannot mark its own job complete, cannot mark it failed,
and never sees the store. That matters most at the moment a backend crashes —
the component that failed is not the component recording that it failed.

**It decides what "finished" means.** ``train`` returning is not completion.
The run moves to ``evaluating``, the adapter is reloaded from disk and compared
against its own pre-training snapshot, and only an evaluation that found a
changed tensor produces ``completed``. A run whose adapter learned nothing ends
in ``failed`` with the reason, because the alternative is a subsystem whose
success criterion is that a process exited zero.

The order of writes is chosen so that an interruption is never ambiguous. The
artifact directory is written as the run goes; the job record's state moves only
after the thing it describes has happened; and provenance is written for every
outcome, including cancellation, because "what was this half-finished directory"
is a question somebody will ask.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .artifacts import RunArtifacts, directory_digest
from .backend import DEFAULT_BACKEND, CancellationSignal, ProgressEvent, get_backend
from .backend.base import READY as PREFLIGHT_READY
from .config import TrainingConfig, load_config
from .datasets.chat import load_chat_dataset
from .errors import ModelStudioError
from .hardware import HardwareReport, probe_hardware
from .jobs import JobRecord, JobStore, TrainingJob, state as machine
from .models import resolve_base_model
from .network import OFFLINE, NetworkPolicy
from .provenance import ProvenanceRecord, utc_now

__all__ = ["ModelStudio"]


class ModelStudio:
    """One entry point for hardware, validation, preflight, training and jobs."""

    def __init__(
        self,
        *,
        store: JobStore | None = None,
        backend_id: str = DEFAULT_BACKEND,
        network: NetworkPolicy | None = None,
        backend: Any = None,
    ) -> None:
        """``backend`` is injected by the tests, and by nothing else.

        The state machine's hardest cases — a run that failed, a run that was
        cancelled halfway, a run whose adapter learned nothing — have to be
        exercised on every machine, including the ones with no GPU and no torch.
        A backend that can be told to produce each of those outcomes is how, and
        it is a constructor argument rather than a patched module attribute so
        the seam is visible in the type rather than in a test's imports.
        """
        self.store = store if store is not None else JobStore()
        self.backend_id = backend_id
        self.network = network or OFFLINE
        self._backend = backend if backend is not None else get_backend(
            backend_id, network=self.network
        )
        self._cancellations: dict[str, CancellationSignal] = {}

    # -- read-only questions ------------------------------------------------ #

    @property
    def backend(self) -> Any:
        return self._backend

    def hardware(self, *, disk_path: Path | str | None = None) -> HardwareReport:
        return probe_hardware(disk_path=disk_path or Path.cwd())

    def detect(self) -> Any:
        return self._backend.detect()

    def validate(self, path: Path | str) -> TrainingConfig:
        """Load a configuration and everything it points at. Raises on the first problem."""
        config = load_config(path)
        load_chat_dataset(
            config.dataset_path,
            max_examples=config.dataset.max_examples,
            policy_check=config.dataset.policy_check,
        )
        return config

    def preflight(self, config: TrainingConfig) -> Any:
        return self._backend.preflight(config)

    def jobs(self) -> list[JobRecord]:
        return self.store.list()

    def inspect(self, job_id: str) -> JobRecord:
        return self.store.load(job_id)

    def cancel(self, job_id: str) -> bool:
        """Latch this process's signal for a run it is executing.

        Returns whether there was one. A job running in another process is not
        cancellable from here — there is no signalling channel between them, and
        inventing one that wrote a file the other process might read would be a
        cancellation that silently does not work.
        """
        signal = self._cancellations.get(job_id)
        if signal is None:
            return False
        signal.cancel("cancelled by request")
        self._backend.cancel(job_id)
        return True

    # -- the network gate --------------------------------------------------- #

    def ensure_base_model(self, config: TrainingConfig) -> Any:
        """Resolve the base model, downloading only under an explicit approval.

        Called before preflight rather than inside it, so preflight itself never
        has a network path — a preflight is a question about this machine, and a
        question that can change the machine is a different kind of thing.
        """
        resolved = resolve_base_model(
            config.model.base, revision=config.model.revision, policy=self.network
        )
        if resolved.present or not self.network.allow_model_download:
            return resolved
        return resolve_base_model(
            config.model.base,
            revision=config.model.revision,
            policy=self.network,
            download=True,
        )

    # -- the run ------------------------------------------------------------ #

    def run(
        self,
        config: TrainingConfig,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> JobRecord:
        """Take a validated configuration all the way to a terminal state.

        Returns the job record. It is never raised out of: every failure this
        method can produce is a state the record can hold, and a caller that
        wants the reason reads ``record.detail``.
        """
        record = self.store.create(config=config)
        signal = cancellation or CancellationSignal()
        self._cancellations[record.job_id] = signal
        started = utc_now()

        try:
            return self._run(record, config, progress, signal, started)
        except ModelStudioError as exc:
            return self._fail(record, f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a job must never end in an active state
            return self._fail(record, f"unexpected {type(exc).__name__}: {exc}")
        finally:
            self._cancellations.pop(record.job_id, None)

    def _fail(self, record: JobRecord, detail: str) -> JobRecord:
        """Move to ``failed`` from wherever we are, or leave a terminal job alone."""
        current = self.store.load(record.job_id, recover=False)
        if machine.is_terminal(current.state):
            return current
        if machine.FAILED not in machine.TRANSITIONS[current.state]:  # pragma: no cover
            return current
        return self.store.transition(current, machine.FAILED, detail=detail)

    def _run(
        self,
        record: JobRecord,
        config: TrainingConfig,
        progress: Callable[[ProgressEvent], None] | None,
        signal: CancellationSignal,
        started: str,
    ) -> JobRecord:
        resolved = self.ensure_base_model(config)

        record = self.store.transition(record, machine.PREFLIGHTING, detail="checking this machine")
        report = self._backend.preflight(config)
        record = self.store.transition(
            record,
            machine.READY if report.status == PREFLIGHT_READY else machine.BLOCKED,
            detail=(
                "preflight passed"
                if report.status == PREFLIGHT_READY
                else "; ".join(report.blocking or report.unknowns) or report.status
            ),
            preflight=report.to_json(),
        )
        if record.state == machine.BLOCKED:
            return record

        record = self.store.transition(record, machine.PREPARING, detail="deriving the plan")
        dataset = load_chat_dataset(
            config.dataset_path,
            max_examples=config.dataset.max_examples,
            policy_check=config.dataset.policy_check,
        )
        plan = report.plan or self._backend.prepare(config, dataset=dataset)
        artifacts = RunArtifacts.create(
            config.output_directory, overwrite=config.output.overwrite
        )
        artifacts.write_config(config)
        artifacts.write_preflight(report)

        job = TrainingJob(
            job_id=record.job_id,
            config=config,
            plan=plan,
            dataset=dataset,
            artifacts=artifacts,
            network=self.network,
        )
        record = self.store.transition(
            record, machine.TRAINING,
            detail=f"{plan.optimizer_steps} optimizer steps in {plan.precision.dtype}",
            plan=plan.to_json(),
            output_directory=str(artifacts.directory),
        )

        result = self._backend.train(job, progress=progress, cancellation=signal)
        artifacts.write_metadata(plan=plan, result=result, job_id=record.job_id)

        if result.cancelled:
            record = self.store.transition(
                record, machine.CANCELLED,
                detail=result.failure or "cancelled",
                result=result.to_json(),
            )
            self._finish_artifacts(artifacts, config, resolved, plan, result, dataset,
                                   record, started, "cancelled")
            return record

        if not result.ok:
            record = self.store.transition(
                record, machine.FAILED, detail=result.failure, result=result.to_json()
            )
            self._finish_artifacts(artifacts, config, resolved, plan, result, dataset,
                                   record, started, "failed")
            return record

        record = self.store.transition(
            record, machine.EVALUATING,
            detail="reloading the adapter and measuring it",
            result=result.to_json(),
        )
        evaluation = self._backend.evaluate(result)
        artifacts.write_evaluation(evaluation)

        if not evaluation.ok:
            record = self.store.transition(
                record, machine.FAILED,
                detail=(
                    "training finished and the evaluation refused it: "
                    f"{evaluation.detail}"
                ),
                evaluation=evaluation.to_json(),
            )
            self._finish_artifacts(artifacts, config, resolved, plan, result, dataset,
                                   record, started, "failed")
            return record

        provenance = self._finish_artifacts(
            artifacts, config, resolved, plan, result, dataset, record, started, "completed"
        )
        return self.store.transition(
            record, machine.COMPLETED,
            detail=evaluation.detail,
            evaluation=evaluation.to_json(),
            provenance=provenance.to_json(),
        )

    def _finish_artifacts(self, artifacts: RunArtifacts, config: TrainingConfig,
                          resolved: Any, plan: Any, result: Any, dataset: Any,
                          record: JobRecord, started: str, status: str) -> ProvenanceRecord:
        """Write provenance and the manifest, whatever the outcome.

        Every outcome, including a cancelled one: a directory holding a partial
        run and no provenance is a directory nobody can identify later, and the
        record that says ``status: cancelled`` is what stops it being mistaken
        for a finished adapter with a missing file.
        """
        adapter_digest = ""
        if result is not None and getattr(result, "adapter_directory", ""):
            adapter_path = Path(result.adapter_directory)
            if adapter_path.is_dir():
                adapter_digest = directory_digest(adapter_path)
        provenance = ProvenanceRecord.for_run(
            job_id=record.job_id,
            status=status,
            config=config,
            model=resolved,
            plan=plan,
            result=result,
            dataset=dataset,
            network_policy=self.network,
            started_at=started,
            completed_at=utc_now(),
            adapter_sha256=adapter_digest,
            gpu=self._gpu_name(),
        )
        artifacts.write_provenance(provenance)
        artifacts.write_manifest()
        return provenance

    def _gpu_name(self) -> str:
        report = probe_hardware()
        if report.accelerator.kind != "cpu":
            return report.accelerator.name
        if report.observed_gpus:
            return f"{report.observed_gpus[0].name} (present, unusable by this torch)"
        return "none"

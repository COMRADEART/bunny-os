# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a training backend has to be, and what it is never allowed to say.

Everything above this line — the CLI, and a future Model Studio window — talks
to this protocol and to nothing else. Not to torch, not to transformers, not to
PEFT. That is what makes ``SoupBackend``, ``UnslothBackend``, ``MLXBackend`` or
a remote one an addition rather than a rewrite: they are new implementations of
six methods, and the screen that drives them does not change.

The contract borrows its central rule from :mod:`companion.agents.adapter`,
which learned it the hard way in the provider layer:

    **Absence is a result, never an exception.**

``detect`` on a machine with no PEFT returns a :class:`BackendStatus` that says
so and names what is missing. ``preflight`` on a 4 GB card asked for a 7B model
returns ``BLOCKED`` with the arithmetic. Neither raises, because a raised
absence gets caught two frames up and turned into a silent skip, and because
"peft is not installed" rendered as a traceback is a support ticket while the
same fact rendered as a sentence is a ``pip install``.

The exceptions this layer *does* raise are for impossible requests — a
configuration that contradicts itself, a job transition that does not exist —
and they come from :mod:`model_studio.errors`.

Three statuses, and the third is the point:

``READY``
    every requirement was checked and met.
``BLOCKED``
    a requirement was checked and not met. ``blocking`` says which.
``UNKNOWN``
    a requirement could not be checked. This is not a pass. A machine whose
    VRAM cannot be read does not get to start a run on the grounds that nothing
    said no.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from ..config import TrainingConfig
from ..hardware import HardwareReport, PrecisionDecision
from ..memory import MemoryEstimate
from ..models import ResolvedModel

__all__ = [
    "BLOCKED",
    "READY",
    "UNKNOWN",
    "BackendStatus",
    "CancellationSignal",
    "EvaluationResult",
    "PreflightReport",
    "ProgressEvent",
    "TrainingBackend",
    "TrainingPlan",
    "TrainingResult",
]

READY = "READY"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"


class CancellationSignal:
    """A one-way latch the caller owns and the trainer watches.

    The same shape as :class:`companion.agents.adapter.CancellationSignal`,
    restated because this package does not import the runtime. ``cancel``
    returns whether this call was the one that latched it, so exactly one place
    records the cause.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._guard = threading.Lock()
        self._reason = ""

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._guard:
            if self._event.is_set():
                return False
            self._reason = reason or "cancelled"
            self._event.set()
            return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._guard:
            return self._reason


@dataclass(frozen=True)
class BackendStatus:
    """Whether this backend can run here, and what is missing if it cannot."""

    backend_id: str
    available: bool
    detail: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    #: Capabilities this backend has *on this machine*, which is not the same as
    #: capabilities it implements. QLoRA is implemented and unavailable without
    #: bitsandbytes and CUDA, and the difference is the whole reason a user is
    #: told "QLoRA needs a CUDA GPU" rather than being shown an option that
    #: fails at step one.
    capabilities: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "backendId": self.backend_id,
            "available": self.available,
            "detail": self.detail,
            "versions": dict(self.versions),
            "missing": list(self.missing),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class TrainingPlan:
    """Exactly what a run will do, derived before it does any of it.

    Every value a trainer would otherwise decide at runtime is here, including
    the ones it would have defaulted: the resolved target modules, the resolved
    batch size and why, the precision and why. A plan a person can read is a
    plan a person can object to, and a run that departs from its plan is a bug
    with a name.
    """

    backend_id: str
    method: str
    base_model_path: str
    base_model_reference: str
    base_model_revision: str
    precision: PrecisionDecision
    base_weight_dtype: str
    batch_size: int
    batch_size_reason: str
    gradient_accumulation_steps: int
    sequence_length: int
    epochs: int
    optimizer_steps: int
    learning_rate: float
    warmup_steps: int
    seed: int
    lora_rank: int
    lora_alpha: int
    lora_dropout: float
    target_modules: tuple[str, ...]
    target_modules_source: str
    gradient_checkpointing: bool
    quantization_bits: int
    training_examples: int
    validation_examples: int
    estimated_trainable_parameters: int | None
    estimated_total_parameters: int | None
    memory: MemoryEstimate | None
    host_memory_bytes: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "backendId": self.backend_id,
            "method": self.method,
            "baseModel": {
                "path": self.base_model_path,
                "reference": self.base_model_reference,
                "revision": self.base_model_revision,
            },
            "precision": self.precision.to_json(),
            "baseWeightDtype": self.base_weight_dtype,
            "batchSize": self.batch_size,
            "batchSizeReason": self.batch_size_reason,
            "gradientAccumulationSteps": self.gradient_accumulation_steps,
            "sequenceLength": self.sequence_length,
            "epochs": self.epochs,
            "optimizerSteps": self.optimizer_steps,
            "learningRate": self.learning_rate,
            "warmupSteps": self.warmup_steps,
            "seed": self.seed,
            "lora": {
                "rank": self.lora_rank,
                "alpha": self.lora_alpha,
                "dropout": self.lora_dropout,
                "targetModules": list(self.target_modules),
                "targetModulesSource": self.target_modules_source,
            },
            "gradientCheckpointing": self.gradient_checkpointing,
            "quantizationBits": self.quantization_bits,
            "examples": {
                "training": self.training_examples,
                "validation": self.validation_examples,
            },
            "estimatedTrainableParameters": self.estimated_trainable_parameters,
            "estimatedTotalParameters": self.estimated_total_parameters,
            "memory": self.memory.to_json() if self.memory else None,
            "hostMemoryBytes": self.host_memory_bytes,
        }


@dataclass(frozen=True)
class PreflightReport:
    """Everything checked before a run, and the verdict that follows from it."""

    backend: BackendStatus
    status: str
    hardware: HardwareReport
    model: ResolvedModel
    precision: PrecisionDecision
    plan: TrainingPlan | None = None
    dataset: dict[str, Any] = field(default_factory=dict)
    blocking: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == READY

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "backend": self.backend.to_json(),
            "hardware": self.hardware.to_json(),
            "model": self.model.to_json(),
            "precision": self.precision.to_json(),
            "plan": self.plan.to_json() if self.plan else None,
            "dataset": dict(self.dataset),
            "blocking": list(self.blocking),
            "warnings": list(self.warnings),
            "unknowns": list(self.unknowns),
        }


@dataclass(frozen=True)
class ProgressEvent:
    """One thing that happened during a run, for a caller that is drawing it."""

    kind: str  # step | epoch | phase | message
    step: int = 0
    total_steps: int = 0
    epoch: int = 0
    loss: float | None = None
    detail: str = ""
    elapsed_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "step": self.step,
            "totalSteps": self.total_steps,
            "epoch": self.epoch,
            "loss": self.loss,
            "detail": self.detail,
            "elapsedSeconds": round(self.elapsed_seconds, 3),
        }


@dataclass(frozen=True)
class TrainingResult:
    """What a run produced. Measured figures only; nothing here is derived."""

    job_id: str
    ok: bool
    output_directory: str
    adapter_directory: str = ""
    steps: int = 0
    epochs_completed: int = 0
    final_loss: float | None = None
    initial_loss: float | None = None
    loss_history: tuple[tuple[int, float], ...] = ()
    duration_seconds: float = 0.0
    #: Measured, in bytes, or ``None`` where the device will not report it. On
    #: CUDA this is ``max_memory_allocated``; on CPU there is no equivalent that
    #: means the same thing, so it is ``None`` rather than a resident-set figure
    #: that would be compared against a VRAM estimate as if it were one.
    peak_device_memory_bytes: int | None = None
    peak_host_memory_bytes: int | None = None
    trainable_parameters: int = 0
    total_parameters: int = 0
    adapter_bytes: int = 0
    precision: str = ""
    device: str = ""
    cancelled: bool = False
    failure: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "ok": self.ok,
            "cancelled": self.cancelled,
            "failure": self.failure,
            "outputDirectory": self.output_directory,
            "adapterDirectory": self.adapter_directory,
            "steps": self.steps,
            "epochsCompleted": self.epochs_completed,
            "initialLoss": self.initial_loss,
            "finalLoss": self.final_loss,
            "lossHistory": [[step, loss] for step, loss in self.loss_history],
            "durationSeconds": round(self.duration_seconds, 3),
            "peakDeviceMemoryBytes": self.peak_device_memory_bytes,
            "peakHostMemoryBytes": self.peak_host_memory_bytes,
            "trainableParameters": self.trainable_parameters,
            "totalParameters": self.total_parameters,
            "adapterBytes": self.adapter_bytes,
            "precision": self.precision,
            "device": self.device,
        }


@dataclass(frozen=True)
class EvaluationResult:
    """Did the run produce something, and is what it produced loadable?

    ``adapter_tensors_changed`` is the field this whole subsystem's evidence
    gate turns on. A training process that exits zero has proved that it exited
    zero. PEFT initialises every ``lora_B`` to zero, so an adapter whose
    ``lora_B`` tensors are still zero is an adapter that learned nothing, saved
    without error, and would load and generate exactly like the base model. That
    is the failure that looks most like success, and this is where it is caught.
    """

    job_id: str
    ok: bool
    reload_ok: bool = False
    adapter_tensors_changed: int = 0
    adapter_tensors_total: int = 0
    max_absolute_delta: float = 0.0
    baseline_loss: float | None = None
    adapter_loss: float | None = None
    validation_examples: int = 0
    samples: tuple[dict[str, str], ...] = ()
    detail: str = ""

    @property
    def loss_improvement(self) -> float | None:
        if self.baseline_loss is None or self.adapter_loss is None:
            return None
        return self.baseline_loss - self.adapter_loss

    def to_json(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "ok": self.ok,
            "reloadOk": self.reload_ok,
            "adapterTensorsChanged": self.adapter_tensors_changed,
            "adapterTensorsTotal": self.adapter_tensors_total,
            "maxAbsoluteDelta": self.max_absolute_delta,
            "baselineLoss": self.baseline_loss,
            "adapterLoss": self.adapter_loss,
            "lossImprovement": self.loss_improvement,
            "validationExamples": self.validation_examples,
            "samples": [dict(item) for item in self.samples],
            "detail": self.detail,
        }


ProgressCallback = Callable[[ProgressEvent], None]


@runtime_checkable
class TrainingBackend(Protocol):
    """The whole surface. Six methods, and none of them raises for absence."""

    @property
    def backend_id(self) -> str: ...

    def detect(self) -> BackendStatus:
        """Can this backend run on this machine, and with what?"""
        ...

    def preflight(self, config: TrainingConfig) -> PreflightReport:
        """Check everything cheap before anything expensive. Never trains."""
        ...

    def prepare(self, config: TrainingConfig) -> TrainingPlan:
        """Derive the exact run. Loads no weights and writes no files."""
        ...

    def train(
        self,
        job: Any,
        *,
        progress: ProgressCallback | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> TrainingResult:
        """Run the plan on the job's configuration, writing artifacts as it goes."""
        ...

    def cancel(self, job_id: str) -> None:
        """Latch the cancellation signal for an in-flight run, if there is one."""
        ...

    def evaluate(self, result: TrainingResult) -> EvaluationResult:
        """Reload what was saved and measure whether it is different from nothing."""
        ...


def combine_status(*, blocking: Sequence[str], unknowns: Sequence[str]) -> str:
    """The verdict rule, in one place: blocked beats unknown beats ready."""
    if blocking:
        return BLOCKED
    if unknowns:
        return UNKNOWN
    return READY

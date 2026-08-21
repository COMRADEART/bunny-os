# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one backend that works: Hugging Face Transformers plus PEFT, LoRA/QLoRA.

Chosen because torch is already a Bunny dependency — the Pocket TTS runtime
ships a pinned CPU wheel — so this adds two pure-Python libraries rather than a
second numerical stack, and because PEFT's on-disk format (``adapter_config.json``
plus ``adapter_model.safetensors``) is the one every local inference runtime
already knows how to read. The handoff to the Bunny OS side is a directory, not
an integration.

The training loop is written out rather than delegated to ``Trainer``. Three
reasons, in the order they mattered:

1. **Cancellation and progress are ours.** A run has to stop when a person says
   stop, and report where it got to. That is a callback contract, and owning the
   loop makes it twenty lines instead of a callback subclass.
2. **Nothing writes without being asked.** ``Trainer`` has opinions about
   checkpoint directories, logging integrations and telemetry. In a subsystem
   whose first promise is "nothing leaves this machine", the loop that touches
   the corpus should have no behaviour nobody here wrote.
3. **The plan is the run.** Every decision — dtype, batch size, target modules,
   which tokens are supervised — is in :class:`~model_studio.backend.base.
   TrainingPlan` before the first forward pass, so a run that departs from its
   plan is a bug with a name rather than a default somewhere in a framework.

Supervision is assistant-only where the tokenizer allows it: the loss is taken
over the assistant's tokens and the prompt is masked out, computed by tokenizing
each conversation prefix and checking it really is a prefix of the whole. When a
tokenizer merges across that boundary the masking would be wrong, so the plan
records ``full-sequence`` instead and the run says so. A silent fallback here
would change what the model learns without changing anything anyone could read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Callable, Sequence

from ..artifacts import RunArtifacts
from ..config import TrainingConfig
from ..datasets.chat import ChatDataset
from ..errors import ModelStudioError
from ..hardware import HardwareReport, probe_hardware, select_precision
from ..hardware.probe import UNKNOWN
from ..memory import adapter_parameters, estimate_training_memory, resolve_batch_size
from ..models import ResolvedModel, resolve_base_model
from ..network import OFFLINE, NetworkPolicy, applied
from .base import (
    BackendStatus,
    CancellationSignal,
    EvaluationResult,
    PreflightReport,
    ProgressEvent,
    TrainingPlan,
    TrainingResult,
    combine_status,
)

__all__ = ["BACKEND_ID", "TransformersLoraBackend"]

BACKEND_ID = "transformers-lora"

#: The attention projections of a gated decoder. The default target set, and it
#: is the attention block rather than everything because adapting the MLP as
#: well roughly triples the trainable parameters for a change that a corpus of a
#: few dozen conversations cannot support.
_DEFAULT_TARGETS: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")

#: Torch dtype names for each of ours. Resolved through torch at use, never
#: stored, so this module imports nothing at module scope.
_TORCH_DTYPES = {"bf16": "bfloat16", "fp16": "float16", "fp32": "float32"}

_IGNORE = -100


@dataclass
class _RunState:
    """What ``train`` learned that ``evaluate`` needs and cannot re-derive."""

    plan: TrainingPlan
    config: TrainingConfig
    dataset: ChatDataset
    initial_adapter: dict[str, Any] = field(default_factory=dict)
    validation: tuple[Any, ...] = ()
    #: The held-out conversations, unencoded. Sample generations are drawn from
    #: here rather than from the corpus at large: showing what the adapter says
    #: to a prompt it was trained on demonstrates memorisation, which is not the
    #: question anyone is asking.
    validation_dataset: ChatDataset | None = None
    cancellation: CancellationSignal | None = None


def _import(name: str) -> Any:
    import importlib

    return importlib.import_module(name)


def _version(name: str) -> str:
    try:
        return str(getattr(_import(name), "__version__", "unknown"))
    except Exception:  # noqa: BLE001
        return "absent"


class TransformersLoraBackend:
    """LoRA and QLoRA over a Hugging Face causal language model."""

    backend_id = BACKEND_ID

    def __init__(self, *, network: NetworkPolicy | None = None) -> None:
        self._network = network or OFFLINE
        self._runs: dict[str, _RunState] = {}
        self._cancellations: dict[str, CancellationSignal] = {}

    # ------------------------------------------------------------------ #
    # detect
    # ------------------------------------------------------------------ #

    def detect(self) -> BackendStatus:
        """What is installed, and therefore what this machine can actually run."""
        versions: dict[str, str] = {}
        missing: list[str] = []
        for name in ("torch", "transformers", "peft", "safetensors"):
            version = _version(name)
            versions[name] = version
            if version == "absent":
                missing.append(name)

        capabilities: list[str] = []
        if not missing:
            capabilities.append("lora")

        bits = _version("bitsandbytes")
        versions["bitsandbytes"] = bits
        cuda = False
        if "torch" not in missing:
            try:
                cuda = bool(_import("torch").cuda.is_available())
            except Exception:  # noqa: BLE001
                cuda = False
        # QLoRA is implemented here and is *available* only with both halves.
        # Reported as a capability rather than assumed from the code, because a
        # user offered a QLoRA button that fails at model load has been lied to.
        if not missing and bits != "absent" and cuda:
            capabilities.append("qlora")

        detail = "ready"
        if missing:
            detail = (
                f"{', '.join(missing)} not installed. Install with: "
                f"pip install {' '.join(missing)}"
            )
        elif "qlora" not in capabilities:
            reason = "bitsandbytes is not installed" if bits == "absent" else "no CUDA device"
            detail = f"LoRA is available; QLoRA is not, because {reason}"

        return BackendStatus(
            backend_id=self.backend_id,
            available=not missing,
            detail=detail,
            versions=versions,
            missing=tuple(missing),
            capabilities=tuple(capabilities),
        )

    # ------------------------------------------------------------------ #
    # prepare
    # ------------------------------------------------------------------ #

    def _targets(self, model: ResolvedModel, config: TrainingConfig) -> tuple[tuple[str, ...], str]:
        if config.lora.target_modules:
            return config.lora.target_modules, "named in the configuration"
        architecture = model.architecture
        if architecture is None:
            return _DEFAULT_TARGETS, "backend default (the base architecture could not be read)"
        return _DEFAULT_TARGETS, f"backend default for a {architecture.model_type} decoder"

    def prepare(
        self,
        config: TrainingConfig,
        *,
        hardware: HardwareReport | None = None,
        model: ResolvedModel | None = None,
        dataset: ChatDataset | None = None,
    ) -> TrainingPlan:
        """Derive the exact run. Loads no weights, writes no files, reaches nothing.

        The optional arguments exist so preflight can hand over what it has
        already measured. Called with none of them it measures for itself, so
        ``prepare`` is a complete operation and not a private step of preflight.
        """
        if hardware is None:
            hardware = probe_hardware(disk_path=config.output_directory)
        if model is None:
            model = resolve_base_model(
                config.model.base, revision=config.model.revision, policy=self._network
            )
        if dataset is None:
            from ..datasets.chat import load_chat_dataset

            dataset = load_chat_dataset(
                config.dataset_path,
                max_examples=config.dataset.max_examples,
                policy_check=config.dataset.policy_check,
            )

        precision = select_precision(hardware.accelerator, requested=config.training.precision)
        targets, targets_source = self._targets(model, config)

        quantization_bits = config.quantization.bits if config.quantization.enabled else 0
        base_dtype = "nf4" if quantization_bits == 4 else (
            "int8" if quantization_bits == 8 else precision.dtype
        )

        def estimate_for(batch: int) -> Any:
            return estimate_training_memory(
                model.architecture,
                dtype=precision.dtype,
                base_dtype=base_dtype,
                batch_size=batch,
                sequence_length=config.training.max_length,
                rank=config.lora.rank,
                target_modules=targets,
                gradient_checkpointing=config.training.gradient_checkpointing,
                quantization_bits=quantization_bits,
            )

        available = (
            hardware.accelerator.vram_free_bytes
            or hardware.accelerator.vram_bytes
            or (hardware.ram_available_bytes if hardware.accelerator.kind == "cpu" else None)
        )
        batch_size, batch_reason = resolve_batch_size(
            config.training.batch_size, available_bytes=available, estimate_for=estimate_for
        )

        training, validation = dataset.split(
            config.dataset.validation_split, seed=config.training.seed
        )
        per_epoch = max(
            1,
            math.ceil(len(training) / (batch_size * config.training.gradient_accumulation_steps)),
        )
        steps = per_epoch * config.training.epochs
        if config.training.max_steps:
            steps = min(steps, config.training.max_steps)

        trainable = (
            adapter_parameters(model.architecture, rank=config.lora.rank, target_modules=targets)
            if model.architecture is not None
            else None
        )

        return TrainingPlan(
            backend_id=self.backend_id,
            method=config.effective_method,
            base_model_path=model.path,
            base_model_reference=model.reference,
            base_model_revision=model.resolved_revision or model.requested_revision,
            precision=precision,
            base_weight_dtype=base_dtype,
            batch_size=batch_size,
            batch_size_reason=batch_reason,
            gradient_accumulation_steps=config.training.gradient_accumulation_steps,
            sequence_length=config.training.max_length,
            epochs=config.training.epochs,
            optimizer_steps=steps,
            learning_rate=config.training.learning_rate,
            warmup_steps=config.training.warmup_steps,
            seed=config.training.seed,
            lora_rank=config.lora.rank,
            lora_alpha=config.lora.alpha,
            lora_dropout=config.lora.dropout,
            target_modules=targets,
            target_modules_source=targets_source,
            gradient_checkpointing=config.training.gradient_checkpointing,
            quantization_bits=quantization_bits,
            training_examples=len(training),
            validation_examples=len(validation),
            estimated_trainable_parameters=trainable,
            estimated_total_parameters=(
                model.architecture.parameter_count if model.architecture else None
            ),
            memory=estimate_for(batch_size),
            host_memory_bytes=hardware.ram_available_bytes,
        )

    # ------------------------------------------------------------------ #
    # preflight
    # ------------------------------------------------------------------ #

    def preflight(self, config: TrainingConfig) -> PreflightReport:
        """Check everything cheap. Never downloads, never loads weights, never trains."""
        status = self.detect()
        hardware = probe_hardware(disk_path=config.output_directory)
        model = resolve_base_model(
            config.model.base, revision=config.model.revision, policy=self._network
        )
        precision = select_precision(hardware.accelerator, requested=config.training.precision)

        blocking: list[str] = []
        warnings: list[str] = []
        unknowns: list[str] = []
        dataset: ChatDataset | None = None
        dataset_summary: dict[str, Any] = {}

        if not status.available:
            blocking.append(f"the {self.backend_id} backend is not available: {status.detail}")

        try:
            from ..datasets.chat import load_chat_dataset

            dataset = load_chat_dataset(
                config.dataset_path,
                max_examples=config.dataset.max_examples,
                policy_check=config.dataset.policy_check,
            )
            dataset_summary = dataset.to_json()
        except ModelStudioError as exc:
            blocking.append(f"dataset: {exc}")

        if not model.present:
            blocking.append(
                f"the base model is not on this machine: {model.detail}. "
                "Approve a download with --allow-model-download, or point model.base "
                "at a local directory."
            )
        elif model.architecture is None:
            unknowns.append(
                f"the base model's architecture could not be read from {model.path}/config.json, "
                "so no memory requirement can be derived"
            )

        if not precision.honoured:
            blocking.append(
                f"training.precision asks for {precision.requested} and this machine cannot "
                f"provide it: {precision.reason}"
            )

        if config.quantization.enabled and "qlora" not in status.capabilities:
            blocking.append(
                f"quantization is enabled and QLoRA is not available here: {status.detail}"
            )

        plan: TrainingPlan | None = None
        if dataset is not None and model.present:
            try:
                plan = self.prepare(config, hardware=hardware, model=model, dataset=dataset)
            except ModelStudioError as exc:
                blocking.append(str(exc))

        if plan is not None and plan.memory is not None:
            required = plan.memory.total_bytes
            if hardware.accelerator.kind == "cpu":
                if hardware.ram_available_bytes is None:
                    unknowns.append("system memory could not be measured")
                elif required > hardware.ram_available_bytes:
                    blocking.append(
                        f"the derived requirement is {required / 2**30:.2f} GiB and "
                        f"{hardware.ram_available_bytes / 2**30:.2f} GiB of RAM is available"
                    )
            else:
                budget = hardware.accelerator.vram_free_bytes or hardware.accelerator.vram_bytes
                if budget is None:
                    unknowns.append(
                        f"VRAM on {hardware.accelerator.name!r} could not be measured, so the "
                        "requirement cannot be checked against it"
                    )
                elif required > budget:
                    blocking.append(
                        f"the derived requirement is {required / 2**30:.2f} GiB and the device "
                        f"has {budget / 2**30:.2f} GiB free. Reduce training.max_length or "
                        f"training.batch_size, or enable quantization for QLoRA."
                    )
                elif required > budget * 0.85:
                    warnings.append(
                        f"the derived requirement ({required / 2**30:.2f} GiB) is within 15% of "
                        f"the {budget / 2**30:.2f} GiB available; the estimate excludes allocator "
                        "fragmentation and the CUDA context, so this may still run out"
                    )
        elif plan is not None and plan.memory is None:
            unknowns.append("the memory requirement could not be derived for this architecture")

        if hardware.disk_free_bytes is None:
            unknowns.append(f"free space on {hardware.disk_path} could not be measured")
        elif hardware.disk_free_bytes < 512 * 1024 * 1024:
            blocking.append(
                f"{hardware.disk_free_bytes / 2**20:.0f} MiB free on {hardware.disk_path}; "
                "a run needs room for the adapter, the log and the records"
            )

        if hardware.accelerator.kind == "cpu" and hardware.observed_gpus:
            warnings.append(
                f"this machine has {hardware.observed_gpus[0].name}, but the installed torch "
                f"cannot use it ({hardware.accelerator.detail}); training would run on the CPU"
            )
        if hardware.accelerator.kind == "cuda" and hardware.accelerator.bf16 == UNKNOWN:
            warnings.append(
                "bfloat16 support could not be established on this device, so float16 or "
                "float32 was chosen; this is slower and correct"
            )
        if dataset is not None and dataset.policy.ran and dataset.policy.approval_ratio < 0.2:
            warnings.append(
                f"only {dataset.policy.with_approval_step} of {dataset.policy.examined} "
                "conversations show the assistant asking for permission. The corpus passed the "
                "lint, but a model trained on it will rarely have seen the approval step."
            )
        if dataset is not None and not dataset.policy.ran:
            warnings.append(
                "dataset.policy_check is false: this corpus was not checked against Bunny's "
                "permission model, and provenance will record that it was not"
            )

        return PreflightReport(
            backend=status,
            status=combine_status(blocking=blocking, unknowns=unknowns),
            hardware=hardware,
            model=model,
            precision=precision,
            plan=plan,
            dataset=dataset_summary,
            blocking=tuple(blocking),
            warnings=tuple(warnings),
            unknowns=tuple(unknowns),
        )

    # ------------------------------------------------------------------ #
    # train
    # ------------------------------------------------------------------ #

    def cancel(self, job_id: str) -> None:
        signal = self._cancellations.get(job_id)
        if signal is not None:
            signal.cancel("cancelled by request")

    def train(
        self,
        job: Any,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> TrainingResult:
        """Run the plan. Every number in the result is measured, not derived."""
        torch = _import("torch")
        config: TrainingConfig = job.config
        plan: TrainingPlan = job.plan
        dataset: ChatDataset = job.dataset
        artifacts: RunArtifacts = job.artifacts
        signal = cancellation or CancellationSignal()
        self._cancellations[job.job_id] = signal

        emit = progress or (lambda event: None)
        started = time.monotonic()

        def note(kind: str, **fields: Any) -> None:
            event = ProgressEvent(kind=kind, elapsed_seconds=time.monotonic() - started, **fields)
            artifacts.append_log(event.to_json())
            emit(event)

        with applied(self._network):
            try:
                return self._train(
                    torch, job, config, plan, dataset, artifacts, signal, note, started
                )
            except ModelStudioError:
                raise
            except Exception as exc:  # noqa: BLE001 - a framework failure is a run failure
                note("phase", detail=f"failed: {type(exc).__name__}: {exc}")
                return TrainingResult(
                    job_id=job.job_id,
                    ok=False,
                    output_directory=str(artifacts.directory),
                    duration_seconds=time.monotonic() - started,
                    precision=plan.precision.dtype,
                    failure=f"{type(exc).__name__}: {exc}",
                )
            finally:
                self._cancellations.pop(job.job_id, None)

    def _train(self, torch: Any, job: Any, config: TrainingConfig, plan: TrainingPlan,
               dataset: ChatDataset, artifacts: RunArtifacts, signal: CancellationSignal,
               note: Callable[..., None], started: float) -> TrainingResult:
        transformers = _import("transformers")
        peft = _import("peft")

        torch.manual_seed(plan.seed)
        random.seed(plan.seed)

        note("phase", detail=f"loading tokenizer from {plan.base_model_path}")
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            plan.base_model_path, trust_remote_code=False
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token

        training_set, validation_set = dataset.split(
            config.dataset.validation_split, seed=plan.seed
        )
        encoded, masking = _encode(tokenizer, training_set, plan.sequence_length)
        validation_encoded, _ = _encode(tokenizer, validation_set, plan.sequence_length)
        if not encoded:
            raise ModelStudioError(
                "every training conversation encoded to zero supervised tokens; the "
                "tokenizer's chat template and this corpus do not fit together"
            )
        note("phase", detail=f"{len(encoded)} conversations encoded, supervision: {masking}")

        note("phase", detail=f"loading base model in {plan.base_weight_dtype}")
        model = _load_base_model(torch, transformers, peft, plan)
        device = _device_for(torch, plan)
        if plan.quantization_bits == 0:
            model.to(device)

        lora_configuration = peft.LoraConfig(
            r=plan.lora_rank,
            lora_alpha=plan.lora_alpha,
            lora_dropout=plan.lora_dropout,
            target_modules=list(plan.target_modules),
            bias=config.lora.bias,
            task_type="CAUSAL_LM",
        )
        model = peft.get_peft_model(model, lora_configuration)
        if plan.gradient_checkpointing:
            model.enable_input_require_grads()
            model.gradient_checkpointing_enable()
        model.config.use_cache = False

        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        trainable_count = sum(parameter.numel() for parameter in trainable)
        total_count = sum(parameter.numel() for parameter in model.parameters())
        if not trainable:
            raise ModelStudioError(
                f"no parameter is trainable after wrapping with LoRA; target modules "
                f"{plan.target_modules} matched nothing in this architecture"
            )
        note("phase", detail=f"{trainable_count} trainable of {total_count} parameters")

        # The snapshot the evidence gate turns on. Taken here, before the first
        # step, so "changed from initialization" is a comparison rather than an
        # inference from a value that happens to be non-zero.
        initial = {
            name: parameter.detach().clone().cpu()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        }

        optimizer = torch.optim.AdamW(trainable, lr=plan.learning_rate)
        scaler = None
        if plan.precision.dtype == "fp16" and device.type == "cuda":
            scaler = torch.amp.GradScaler("cuda")

        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)

        total_steps = plan.optimizer_steps
        history: list[tuple[int, float]] = []
        initial_loss: float | None = None
        step = 0
        epochs_completed = 0
        cancelled = False

        model.train()
        for epoch in range(plan.epochs):
            # Shuffle the *examples* and re-batch, rather than shuffling a fixed
            # set of batches. Reordering fixed groupings leaves every example
            # with the same companions in every epoch, so the gradient each step
            # sees is the same handful of averages in a different order — most of
            # the benefit of shuffling, missing. Seeded per epoch, so the run is
            # still reproducible from the plan.
            order = list(encoded)
            random.Random(plan.seed + epoch).shuffle(order)
            batches = _batches(order, plan.batch_size)
            accumulated = 0
            consumed = 0
            optimizer.zero_grad(set_to_none=True)
            for batch in batches:
                consumed += 1
                if signal.cancelled:
                    cancelled = True
                    break
                inputs = _to_device(torch, batch, device, tokenizer.pad_token_id)
                loss = _forward(torch, model, inputs, plan, device)
                scaled = loss / plan.gradient_accumulation_steps
                if scaler is not None:
                    scaler.scale(scaled).backward()
                else:
                    scaled.backward()
                accumulated += 1
                if accumulated < plan.gradient_accumulation_steps:
                    continue

                _apply_learning_rate(optimizer, plan, step)
                if scaler is not None:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(trainable, 1.0)
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    torch.nn.utils.clip_grad_norm_(trainable, 1.0)
                    optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                accumulated = 0
                step += 1
                value = float(loss.detach().float().item())
                if initial_loss is None:
                    initial_loss = value
                history.append((step, value))
                note("step", step=step, total_steps=total_steps, epoch=epoch + 1, loss=value)
                if plan.optimizer_steps and step >= plan.optimizer_steps:
                    break
            # An epoch is complete when its last batch was consumed, and not
            # complete when a break left batches behind. Counting a `break` as
            # incomplete on its own is wrong at the boundary: a step ceiling
            # that falls on an epoch's final batch breaks out of a loop that had
            # nothing left to do. "3 epochs completed" is a number people
            # compare between runs, so it gets the arithmetic rather than the
            # control flow.
            if consumed == len(batches) and not cancelled:
                epochs_completed = epoch + 1
            note("epoch", epoch=epochs_completed, step=step, total_steps=total_steps)
            if cancelled or (plan.optimizer_steps and step >= plan.optimizer_steps):
                break

        peak_device = (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else None
        )
        peak_host = _peak_host_memory()

        adapter_bytes = 0
        adapter_directory = ""
        if not cancelled:
            note("phase", detail="saving adapter")
            artifacts.adapter_directory.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(artifacts.adapter_directory))
            tokenizer.save_pretrained(str(artifacts.adapter_directory))
            adapter_directory = str(artifacts.adapter_directory)
            adapter_bytes = sum(
                path.stat().st_size
                for path in artifacts.adapter_directory.rglob("*")
                if path.is_file()
            )

        self._runs[job.job_id] = _RunState(
            plan=plan,
            config=config,
            dataset=dataset,
            initial_adapter=initial,
            validation=tuple(validation_encoded),
            validation_dataset=validation_set,
        )

        return TrainingResult(
            job_id=job.job_id,
            ok=not cancelled,
            cancelled=cancelled,
            failure="cancelled before the adapter was saved" if cancelled else "",
            output_directory=str(artifacts.directory),
            adapter_directory=adapter_directory,
            steps=step,
            epochs_completed=epochs_completed,
            initial_loss=initial_loss,
            final_loss=history[-1][1] if history else None,
            loss_history=tuple(history),
            duration_seconds=time.monotonic() - started,
            peak_device_memory_bytes=peak_device,
            peak_host_memory_bytes=peak_host,
            trainable_parameters=trainable_count,
            total_parameters=total_count,
            adapter_bytes=adapter_bytes,
            precision=plan.precision.dtype,
            device=str(device),
        )

    # ------------------------------------------------------------------ #
    # evaluate
    # ------------------------------------------------------------------ #

    def evaluate(self, result: TrainingResult) -> EvaluationResult:
        """Reload from disk, and ask whether what was saved is different from nothing.

        Three questions, in the order that matters:

        1. does the adapter load from disk, into a fresh base model?
        2. did its tensors move from their initial values?
        3. does the held-out loss with it differ from the held-out loss without?

        A run that answers yes, no, no has produced a well-formed artifact that
        learned nothing — the failure a zero exit status cannot distinguish from
        success, and the reason the second question is asked against a snapshot
        taken before the first step rather than against a zero.
        """
        state = self._runs.get(result.job_id)
        if not result.adapter_directory:
            return EvaluationResult(
                job_id=result.job_id, ok=False,
                detail="no adapter was saved, so there is nothing to evaluate",
            )

        torch = _import("torch")
        peft = _import("peft")
        transformers = _import("transformers")
        adapter = Path(result.adapter_directory)

        with applied(self._network):
            plan = state.plan if state else None
            base_path = plan.base_model_path if plan else ""
            if not base_path:
                return EvaluationResult(
                    job_id=result.job_id, ok=False,
                    detail="the base model this adapter belongs to is not known to this process",
                )
            base = _load_base_model(torch, transformers, peft, plan)
            reloaded = peft.PeftModel.from_pretrained(base, str(adapter))
            device = _device_for(torch, plan)
            if plan.quantization_bits == 0:
                # A 4-bit model is already placed by its device map, and moving
                # one with `.to` raises rather than doing nothing: bitsandbytes
                # refuses because casting quantized weights would silently
                # dequantize them. Same rule as the training path.
                reloaded.to(device)
            reloaded.eval()

            changed, total, largest = _compare_to_initial(
                reloaded, state.initial_adapter if state else {}
            )
            method = (
                "compared against the pre-training snapshot"
                if state and state.initial_adapter
                else "compared against PEFT's zero-initialised lora_B (no snapshot in this process)"
            )

            baseline_loss: float | None = None
            adapter_loss: float | None = None
            examples = 0
            if state and state.validation:
                examples = len(state.validation)
                batches = _batches(list(state.validation), max(1, plan.batch_size))
                tokenizer = transformers.AutoTokenizer.from_pretrained(str(adapter))
                pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
                adapter_loss = _mean_loss(torch, reloaded, batches, device, plan, pad)
                with reloaded.disable_adapter():
                    baseline_loss = _mean_loss(torch, reloaded, batches, device, plan, pad)

            samples = _samples(torch, transformers, reloaded, adapter, device, state)

        return EvaluationResult(
            job_id=result.job_id,
            ok=changed > 0,
            reload_ok=True,
            adapter_tensors_changed=changed,
            adapter_tensors_total=total,
            max_absolute_delta=largest,
            baseline_loss=baseline_loss,
            adapter_loss=adapter_loss,
            validation_examples=examples,
            samples=samples,
            detail=(
                f"{changed} of {total} adapter tensors moved ({method}); "
                f"largest absolute change {largest:.3e}"
                if changed
                else f"no adapter tensor moved ({method}); this adapter would behave "
                     "exactly like the base model"
            ),
        )


# --------------------------------------------------------------------------- #
# The parts that touch torch, kept out of the class so they read as functions
# --------------------------------------------------------------------------- #


def _device_for(torch: Any, plan: TrainingPlan | None) -> Any:
    if torch.cuda.is_available():
        return torch.device("cuda")
    try:
        if torch.backends.mps.is_available():
            return torch.device("mps")
    except AttributeError:  # pragma: no cover - older torch
        pass
    return torch.device("cpu")


def _load_base_model(torch: Any, transformers: Any, peft: Any, plan: TrainingPlan) -> Any:
    """Load the frozen base, in the dtype the plan chose.

    ``dtype`` was called ``torch_dtype`` before transformers 5. Both are passed
    in turn rather than branching on a version string, because the version that
    matters is the one installed and it will answer for itself.
    """
    dtype = getattr(torch, _TORCH_DTYPES[plan.precision.dtype])
    arguments: dict[str, Any] = {"trust_remote_code": False}

    if plan.quantization_bits:
        transformers_module = transformers
        quantization = transformers_module.BitsAndBytesConfig(
            load_in_4bit=plan.quantization_bits == 4,
            load_in_8bit=plan.quantization_bits == 8,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )
        arguments["quantization_config"] = quantization
        arguments["device_map"] = {"": 0}

    for keyword in ("dtype", "torch_dtype"):
        try:
            model = transformers.AutoModelForCausalLM.from_pretrained(
                plan.base_model_path, **{keyword: dtype}, **arguments
            )
            break
        except TypeError:
            continue
    else:  # pragma: no cover - both keywords rejected
        raise ModelStudioError(
            "this transformers version accepts neither 'dtype' nor 'torch_dtype'"
        )

    if plan.quantization_bits:
        model = peft.prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=plan.gradient_checkpointing
        )
    return model


def _encode(tokenizer: Any, dataset: Any, maximum: int) -> tuple[list[dict[str, list[int]]], str]:
    """Tokenize conversations, supervising the assistant's tokens only where possible.

    Returns the encoded examples and which masking was actually used. The
    fallback is reported rather than applied quietly: full-sequence supervision
    trains the model to produce the user's turns as well, which is a different
    thing to have trained and should not be invisible.

    It is also applied to the *whole* corpus or none of it. The first version of
    this function let the mode flip partway through, so a tokenizer that merged
    across a boundary at conversation 20 left the first nineteen supervised one
    way and the rest another — one corpus, two objectives, and a single word in
    the log describing both.
    """
    encoded, masking = _encode_pass(tokenizer, dataset, maximum, force_full=False)
    if masking == "full-sequence":
        encoded, masking = _encode_pass(tokenizer, dataset, maximum, force_full=True)
    return encoded, masking


def _encode_pass(tokenizer: Any, dataset: Any, maximum: int,
                 *, force_full: bool) -> tuple[list[dict[str, list[int]]], str]:
    encoded: list[dict[str, list[int]]] = []
    masking = "full-sequence" if force_full else "assistant-only"
    for example in dataset:
        messages = [dict(message) for message in example.messages]
        try:
            rendered = tokenizer.apply_chat_template(messages, tokenize=False)
        except Exception:  # noqa: BLE001 - a tokenizer with no chat template
            rendered = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
            masking = "full-sequence"
        ids = tokenizer(rendered, add_special_tokens=False)["input_ids"][:maximum]
        if not ids:
            continue

        labels = list(ids)
        if masking == "assistant-only":
            labels = [_IGNORE] * len(ids)
            supervised = 0
            for position, message in enumerate(messages):
                if message["role"] != "assistant":
                    continue
                try:
                    prefix = tokenizer.apply_chat_template(
                        messages[:position], tokenize=False, add_generation_prompt=True
                    )
                    whole = tokenizer.apply_chat_template(messages[: position + 1], tokenize=False)
                except Exception:  # noqa: BLE001
                    masking = "full-sequence"
                    break
                prefix_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
                whole_ids = tokenizer(whole, add_special_tokens=False)["input_ids"]
                if whole_ids[: len(prefix_ids)] != prefix_ids or ids[: len(prefix_ids)] != prefix_ids:
                    # The tokenizer merged across the boundary, so the token
                    # index the mask would use does not exist.
                    masking = "full-sequence"
                    break
                start, end = len(prefix_ids), min(len(whole_ids), len(ids))
                for index in range(start, end):
                    labels[index] = ids[index]
                supervised += max(0, end - start)
            if masking == "full-sequence":
                labels = list(ids)
            elif supervised == 0:
                labels = list(ids)
        encoded.append({"input_ids": ids, "labels": labels})
    return encoded, masking


def _batches(encoded: list[dict[str, list[int]]], size: int) -> list[list[dict[str, list[int]]]]:
    return [encoded[index:index + size] for index in range(0, len(encoded), size)]


def _to_device(torch: Any, batch: Sequence[dict[str, list[int]]], device: Any, pad: int) -> dict[str, Any]:
    width = max(len(item["input_ids"]) for item in batch)
    input_ids, labels, mask = [], [], []
    for item in batch:
        padding = width - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad] * padding)
        labels.append(item["labels"] + [_IGNORE] * padding)
        mask.append([1] * len(item["input_ids"]) + [0] * padding)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long, device=device),
        "labels": torch.tensor(labels, dtype=torch.long, device=device),
        "attention_mask": torch.tensor(mask, dtype=torch.long, device=device),
    }


def _forward(torch: Any, model: Any, inputs: dict[str, Any], plan: TrainingPlan, device: Any) -> Any:
    if plan.precision.dtype in ("bf16", "fp16") and device.type in ("cuda", "cpu"):
        dtype = getattr(torch, _TORCH_DTYPES[plan.precision.dtype])
        with torch.autocast(device_type=device.type, dtype=dtype):
            return model(**inputs).loss
    return model(**inputs).loss


def _apply_learning_rate(optimizer: Any, plan: TrainingPlan, step: int) -> None:
    """Linear warmup then linear decay, written out so the schedule is readable."""
    total = max(1, plan.optimizer_steps)
    if plan.warmup_steps and step < plan.warmup_steps:
        scale = (step + 1) / plan.warmup_steps
    else:
        remaining = max(0, total - step)
        span = max(1, total - plan.warmup_steps)
        scale = max(0.0, remaining / span)
    for group in optimizer.param_groups:
        group["lr"] = plan.learning_rate * scale


def _mean_loss(torch: Any, model: Any, batches: list[list[dict[str, list[int]]]],
               device: Any, plan: TrainingPlan, pad: int) -> float | None:
    if not batches:
        return None
    total = 0.0
    counted = 0
    with torch.no_grad():
        for batch in batches:
            inputs = _to_device(torch, batch, device, pad)
            loss = model(**inputs).loss
            if loss is None:
                continue
            total += float(loss.detach().float().item())
            counted += 1
    return total / counted if counted else None


def _compare_to_initial(model: Any, initial: dict[str, Any]) -> tuple[int, int, float]:
    """How many adapter tensors moved, and by how much.

    With a snapshot, this is a straight comparison. Without one — evaluating a
    run this process did not train — it falls back to PEFT's own initialisation
    contract: ``lora_B`` is created as zeros, so a non-zero ``lora_B`` is proof
    that a gradient reached it and an optimizer stepped it.
    """
    changed = 0
    total = 0
    largest = 0.0
    for name, parameter in model.named_parameters():
        if "lora_" not in name:
            continue
        total += 1
        current = parameter.detach().cpu()
        # Two lookups, not `a or b`. `or` evaluates the truthiness of the first
        # result, and a tensor with more than one element raises rather than
        # answering — so the idiom that reads as "this, else that" is a
        # RuntimeError on every tensor it finds. It cost this subsystem its
        # first three end-to-end runs, all of which trained correctly and
        # crashed in the evaluation that was supposed to prove it.
        reference = initial.get(name)
        if reference is None:
            reference = initial.get(name.replace("base_model.model.", ""))
        if reference is None:
            if "lora_B" in name:
                magnitude = float(current.abs().max().item())
                if magnitude > 0:
                    changed += 1
                    largest = max(largest, magnitude)
            continue
        if reference.shape != current.shape:
            continue
        delta = float((current.float() - reference.float()).abs().max().item())
        if delta > 0:
            changed += 1
        largest = max(largest, delta)
    return changed, total, largest


def _samples(torch: Any, transformers: Any, model: Any, adapter: Path, device: Any,
             state: _RunState | None) -> tuple[dict[str, str], ...]:
    """A handful of side-by-side generations: the same prompt, with and without.

    Greedy decoding and a short limit. This is evidence that the adapter changes
    behaviour, not a benchmark, and a sampled decode would make two runs of the
    same adapter disagree for reasons that have nothing to do with training.
    """
    if state is None:
        return ()
    source = state.validation_dataset if state.validation_dataset and len(
        state.validation_dataset
    ) else state.dataset
    if not source:
        return ()
    tokenizer = transformers.AutoTokenizer.from_pretrained(str(adapter))
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    collected: list[dict[str, str]] = []
    for example in list(source)[:3]:
        messages = [dict(message) for message in example.messages]
        prompt_messages = [item for item in messages if item["role"] != "assistant"][:1]
        if not prompt_messages:
            continue
        try:
            text = tokenizer.apply_chat_template(
                prompt_messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:  # noqa: BLE001
            continue
        inputs = tokenizer(text, return_tensors="pt").to(device)

        def generate() -> str:
            with torch.no_grad():
                output = model.generate(
                    **inputs, max_new_tokens=48, do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                )
            return tokenizer.decode(
                output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
            ).strip()

        with_adapter = generate()
        with model.disable_adapter():
            without_adapter = generate()
        collected.append({
            "prompt": prompt_messages[0]["content"],
            "base": without_adapter,
            "adapter": with_adapter,
            "reference": next(
                (item["content"] for item in messages if item["role"] == "assistant"), ""
            ),
        })
    return tuple(collected)


def _peak_host_memory() -> int | None:
    """Peak resident set, where the platform reports one. ``None`` otherwise."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes; macOS reports bytes.
        return int(peak) * (1 if os.uname().sysname == "Darwin" else 1024)  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        pass
    try:
        import psutil  # type: ignore

        return int(psutil.Process().memory_info().rss)
    except Exception:  # noqa: BLE001
        return None

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The contract a Model Studio window will render, without building the window.

    +-------------------------------------------+
    | Bunny Model Studio                        |
    |                                           |
    | Base Model                                |
    | SmolLM2-360M-Instruct                     |
    |                                           |
    | Dataset                                   |
    | bunny-personal.jsonl                      |
    | 842 conversations                         |
    |                                           |
    | Training                                  |
    | o LoRA                                    |
    | * QLoRA                                   |
    |                                           |
    | GPU                                       |
    | RTX 3050 Laptop                           |
    | #######...  3.1 / 4.0 GB estimated        |
    |                                           |
    |             [ Start Training ]            |
    +-------------------------------------------+

Every field on that screen is a field here, and the reason to define it now —
before there is any GTK — is that the shape of a view model decides what a
backend has to be able to answer. Three of these fields would have been
impossible to fill honestly from the obvious design:

* a radio button needs to be *disabled with a reason*, not hidden, so
  :class:`MethodOption` carries ``available`` and ``detail`` — which is why
  :class:`~model_studio.backend.base.BackendStatus` reports capabilities
  separately from availability;
* the memory bar needs a denominator, and a machine that will not report VRAM
  has none, so :attr:`DeviceView.fraction` is ``None`` and the caption says
  ``UNKNOWN`` rather than the bar quietly rendering empty;
* the button needs to be disabled with the *list* of reasons, so
  :attr:`ActionView.blocked_by` is a sequence and preflight collects all of
  them rather than returning at the first.

A view built from a blocked preflight is a complete screen: it shows what is
wrong, next to the thing that is wrong, with the button off. That is the whole
job of this module, and it is why no widget code needs to make a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backend.base import READY, PreflightReport
from .config import TrainingConfig

__all__ = ["ActionView", "DeviceView", "FieldView", "MethodOption", "StudioView", "build_view"]

_GIB = float(1024 ** 3)


def _gigabytes(value: int | None) -> str:
    return "UNKNOWN" if value is None else f"{value / _GIB:.1f} GB"


@dataclass(frozen=True)
class FieldView:
    """A labelled value, and whether it is a problem."""

    label: str
    value: str
    detail: str = ""
    ok: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "value": self.value, "detail": self.detail, "ok": self.ok}


@dataclass(frozen=True)
class MethodOption:
    """One training method, and why it may not be selectable here."""

    identifier: str
    label: str
    selected: bool
    available: bool
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "label": self.label,
            "selected": self.selected,
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DeviceView:
    """The memory bar. ``fraction`` is ``None`` when there is nothing to divide by."""

    name: str
    kind: str
    total_bytes: int | None
    estimated_bytes: int | None
    caption: str
    fraction: float | None = None
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "totalBytes": self.total_bytes,
            "estimatedBytes": self.estimated_bytes,
            "fraction": self.fraction,
            "caption": self.caption,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ActionView:
    """The button."""

    label: str
    enabled: bool
    blocked_by: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "enabled": self.enabled, "blockedBy": list(self.blocked_by)}


@dataclass(frozen=True)
class StudioView:
    """One screen's worth of state, derived entirely from a preflight report."""

    title: str
    base_model: FieldView
    dataset: FieldView
    methods: tuple[MethodOption, ...]
    device: DeviceView
    precision: FieldView
    plan_summary: tuple[FieldView, ...]
    start: ActionView
    warnings: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    status: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "baseModel": self.base_model.to_json(),
            "dataset": self.dataset.to_json(),
            "methods": [item.to_json() for item in self.methods],
            "device": self.device.to_json(),
            "precision": self.precision.to_json(),
            "planSummary": [item.to_json() for item in self.plan_summary],
            "start": self.start.to_json(),
            "warnings": list(self.warnings),
            "unknowns": list(self.unknowns),
        }


def _method_options(report: PreflightReport, config: TrainingConfig) -> tuple[MethodOption, ...]:
    capabilities = set(report.backend.capabilities)
    chosen = config.effective_method
    options = []
    for identifier, label in (("lora", "LoRA"), ("qlora", "QLoRA")):
        available = identifier in capabilities
        detail = ""
        if not available:
            detail = (
                report.backend.detail
                if not report.backend.available
                else f"{label} is not available on this machine: {report.backend.detail}"
            )
        options.append(
            MethodOption(
                identifier=identifier,
                label=label,
                selected=identifier == chosen,
                available=available,
                detail=detail,
            )
        )
    return tuple(options)


def _device_view(report: PreflightReport) -> DeviceView:
    accelerator = report.hardware.accelerator
    estimated = report.plan.memory.total_bytes if report.plan and report.plan.memory else None

    if accelerator.kind == "cpu":
        total = report.hardware.ram_total_bytes
        name = accelerator.name
        kind = "cpu"
        detail = accelerator.detail
        if report.hardware.observed_gpus:
            detail = (
                f"{report.hardware.observed_gpus[0].name} is present but the installed "
                f"torch cannot use it: {accelerator.detail}"
            )
    else:
        total = accelerator.vram_bytes
        name = accelerator.name
        kind = accelerator.kind
        detail = accelerator.detail

    fraction = None
    if total and estimated is not None:
        fraction = min(1.0, estimated / total)

    if estimated is None:
        caption = f"UNKNOWN / {_gigabytes(total)} estimated"
    else:
        caption = f"{_gigabytes(estimated)} / {_gigabytes(total)} estimated"
    return DeviceView(
        name=name,
        kind=kind,
        total_bytes=total,
        estimated_bytes=estimated,
        caption=caption,
        fraction=fraction,
        detail=detail,
    )


def build_view(report: PreflightReport, config: TrainingConfig) -> StudioView:
    """Turn a preflight report into a screen. The only place display strings are made."""
    dataset_path = Path(config.dataset.path).name or config.dataset.path
    conversations = report.dataset.get("conversations")
    plan = report.plan

    summary: list[FieldView] = []
    if plan is not None:
        summary.extend([
            FieldView("Steps", str(plan.optimizer_steps),
                      f"{plan.epochs} epoch(s), batch {plan.batch_size}"),
            FieldView("Batch size", str(plan.batch_size), plan.batch_size_reason),
            FieldView("Sequence length", str(plan.sequence_length)),
            FieldView("Adapted modules", ", ".join(plan.target_modules), plan.target_modules_source),
            FieldView(
                "Trainable parameters",
                "UNKNOWN" if plan.estimated_trainable_parameters is None
                else f"{plan.estimated_trainable_parameters:,}",
                "derived from the architecture and the LoRA rank",
            ),
        ])

    return StudioView(
        title="Bunny Model Studio",
        status=report.status,
        base_model=FieldView(
            label="Base Model",
            value=config.model.base,
            detail=report.model.detail,
            ok=report.model.present,
        ),
        dataset=FieldView(
            label="Dataset",
            value=dataset_path,
            detail=(
                f"{conversations} conversations" if conversations is not None
                else "could not be read"
            ),
            ok=conversations is not None,
        ),
        methods=_method_options(report, config),
        device=_device_view(report),
        precision=FieldView(
            label="Precision",
            value=report.precision.dtype,
            detail=report.precision.reason,
            ok=report.precision.honoured,
        ),
        plan_summary=tuple(summary),
        start=ActionView(
            label="Start Training",
            enabled=report.status == READY,
            blocked_by=tuple(report.blocking) + tuple(report.unknowns),
        ),
        warnings=tuple(report.warnings),
        unknowns=tuple(report.unknowns),
    )

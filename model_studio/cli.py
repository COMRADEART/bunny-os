# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""``bunny-model``: the developer surface, before there is a window.

Named and shaped after ``bunny-oem``, the repository's other tool that is not
part of the installed system. It is deliberately *not* a ``bunny-os model``
subcommand: ``tools/bunny-os/bunny_os`` is installed to
``/usr/lib/bunny-os/python`` on every Bunny machine, so a subcommand there would
either ship the training subsystem into the image or ship a command that raises
``ImportError`` on every installed system. Neither is a good trade for a shorter
name.

Every command prints a human table by default and a JSON document with
``--json``, because the same commands are how a future window will get its data
and the two must not drift into different answers.

Exit codes, and they are the contract:

``0``
    the thing succeeded, or the report is READY.
``1``
    the input was wrong: a configuration that does not validate, a dataset that
    does not parse, a job that does not exist.
``2``
    the machine cannot do it: preflight BLOCKED or UNKNOWN, training failed.

Two and one are distinct because they lead to different actions — fix the file,
or fix the machine — and a single non-zero code would have made a CI job unable
to tell "this branch broke the config" from "this runner has no GPU".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .artifacts import RunArtifacts
from .backend import DEFAULT_BACKEND, available_backends
from .backend.base import READY
from .config import load_config
from .errors import ModelStudioError
from .hardware import probe_hardware, select_precision
from .jobs import JobStore
from .network import NetworkPolicy
from .studio import ModelStudio
from .view import build_view

__all__ = ["main", "parser"]

EXIT_OK = 0
EXIT_INPUT = 1
EXIT_MACHINE = 2

_GIB = float(1024 ** 3)


def _emit(document: Any) -> None:
    print(json.dumps(document, indent=2, sort_keys=True))


def _size(value: int | None, unit: str = "GiB") -> str:
    if value is None:
        return "UNKNOWN"
    return f"{value / _GIB:.1f} {unit}"


def _rule(title: str) -> str:
    return f"{title}\n{'-' * len(title)}"


# --------------------------------------------------------------------------- #
# hardware
# --------------------------------------------------------------------------- #


def _hardware(arguments: argparse.Namespace) -> int:
    report = probe_hardware(disk_path=arguments.path)
    precision = select_precision(report.accelerator)
    studio = ModelStudio(backend_id=arguments.backend)
    status = studio.detect()

    if arguments.json:
        _emit({
            "hardware": report.to_json(),
            "precision": precision.to_json(),
            "backend": status.to_json(),
            "recommendedMethod": "qlora" if "qlora" in status.capabilities else (
                "lora" if "lora" in status.capabilities else "none"
            ),
        })
        return EXIT_OK

    accelerator = report.accelerator
    print(_rule("Hardware"))
    print(f"{'CPU':<12}{report.cpu_model} ({report.cpu_logical} logical)")
    print(f"{'RAM':<12}{_size(report.ram_total_bytes)} total, "
          f"{_size(report.ram_available_bytes)} available")
    print(f"{'Disk free':<12}{_size(report.disk_free_bytes)} at {report.disk_path}")
    if accelerator.kind == "cpu":
        print(f"{'GPU':<12}none usable — {accelerator.detail}")
        for observed in report.observed_gpus:
            print(f"{'':<12}present: {observed.name} ({_size(observed.vram_bytes)})")
    else:
        print(f"{'GPU':<12}{accelerator.name}")
        print(f"{'VRAM':<12}{_size(accelerator.vram_bytes)} total, "
              f"{_size(accelerator.vram_free_bytes)} free")
        capability = accelerator.compute_capability
        print(f"{'CUDA':<12}{'yes' if accelerator.kind == 'cuda' else accelerator.kind}"
              + (f" (compute {capability[0]}.{capability[1]})" if capability else ""))
    print(f"{'bf16':<12}{accelerator.bf16}")
    print(f"{'fp16':<12}{accelerator.fp16}")
    print()
    print(_rule("Training backend"))
    print(f"{'Backend':<12}{status.backend_id}")
    print(f"{'Available':<12}{'yes' if status.available else 'no'}")
    print(f"{'Detail':<12}{status.detail}")
    print(f"{'Methods':<12}{', '.join(status.capabilities) or 'none'}")
    print()
    print("Recommended mode:")
    print("QLoRA" if "qlora" in status.capabilities else
          ("LoRA" if "lora" in status.capabilities else "none — install the backend first"))
    print(f"Precision: {precision.dtype} ({precision.reason})")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #


def _validate(arguments: argparse.Namespace) -> int:
    studio = ModelStudio(backend_id=arguments.backend)
    try:
        config = studio.validate(arguments.config)
    except ModelStudioError as exc:
        if arguments.json:
            _emit({"valid": False, "error": str(exc), "type": type(exc).__name__})
        else:
            print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INPUT

    from .datasets.chat import load_chat_dataset

    dataset = load_chat_dataset(
        config.dataset_path,
        max_examples=config.dataset.max_examples,
        policy_check=config.dataset.policy_check,
    )
    if arguments.json:
        _emit({"valid": True, "config": config.to_json(), "dataset": dataset.to_json(),
               "canonicalSha256": config.canonical_sha256, "fileSha256": config.file_sha256})
        return EXIT_OK

    print(f"VALID   {config.source_path}")
    print(f"        method {config.effective_method}, base {config.model.base}")
    print(f"        dataset {dataset.path}: {len(dataset)} conversations, "
          f"{dataset.message_count} messages")
    if dataset.policy.ran:
        print(f"        permission lint: passed, {dataset.policy.with_approval_step} of "
              f"{dataset.policy.examined} conversations show an approval step")
    else:
        print("        permission lint: NOT RUN (dataset.policy_check is false)")
    print(f"        config sha256 {config.file_sha256[:16]}, run {config.canonical_sha256[:16]}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #


def _print_preflight(report: Any) -> None:
    hardware = report.hardware
    accelerator = hardware.accelerator
    print(_rule("Hardware"))
    if accelerator.kind == "cpu":
        print(f"GPU: none usable ({accelerator.detail})")
    else:
        print(f"GPU: {accelerator.name}")
        print(f"VRAM: {_size(accelerator.vram_bytes)}")
        print(f"CUDA: {'available' if accelerator.kind == 'cuda' else accelerator.kind}")
    print(f"bf16: {accelerator.bf16}")
    print(f"fp16: {accelerator.fp16}")
    print(f"RAM: {_size(hardware.ram_total_bytes)}")
    print(f"Disk free: {_size(hardware.disk_free_bytes)}")
    print()

    plan = report.plan
    print(_rule("Training plan"))
    if plan is None:
        print("no plan: the inputs above could not be resolved")
    else:
        print(f"Method: {plan.method.upper()}")
        print(f"Base model: {plan.base_model_reference} @ {plan.base_model_revision}")
        print(f"Precision: {plan.precision.dtype} ({plan.precision.reason})")
        print(f"Batch size: {plan.batch_size} ({plan.batch_size_reason})")
        print(f"Steps: {plan.optimizer_steps} over {plan.epochs} epoch(s)")
        print(f"Adapted: {', '.join(plan.target_modules)} ({plan.target_modules_source})")
        estimated = plan.memory.total_bytes if plan.memory else None
        label = "VRAM" if accelerator.kind != "cpu" else "memory"
        print(f"Estimated {label}: {_size(estimated)}")
        if plan.memory:
            for name, value in sorted(plan.memory.components.items()):
                print(f"    {name:<22}{_size(value)}")
        print(f"Estimated host RAM: {_size(plan.host_memory_bytes)} available")
    print()
    for line in report.warnings:
        print(f"WARNING: {line}")
    for line in report.unknowns:
        print(f"UNKNOWN: {line}")
    for line in report.blocking:
        print(f"BLOCKED: {line}")
    if report.warnings or report.unknowns or report.blocking:
        print()
    print(f"STATUS: {report.status}")


def _preflight(arguments: argparse.Namespace) -> int:
    studio = ModelStudio(backend_id=arguments.backend)
    try:
        config = load_config(arguments.config)
    except ModelStudioError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INPUT
    report = studio.preflight(config)
    if arguments.json:
        _emit(report.to_json())
    else:
        _print_preflight(report)
    return EXIT_OK if report.status == READY else EXIT_MACHINE


# --------------------------------------------------------------------------- #
# view (the GUI contract)
# --------------------------------------------------------------------------- #


def _view(arguments: argparse.Namespace) -> int:
    studio = ModelStudio(backend_id=arguments.backend)
    try:
        config = load_config(arguments.config)
    except ModelStudioError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INPUT
    view = build_view(studio.preflight(config), config)
    if arguments.json:
        _emit(view.to_json())
        return EXIT_OK if view.start.enabled else EXIT_MACHINE

    print(view.title)
    print()
    for item in (view.base_model, view.dataset):
        print(f"{item.label}\n  {item.value}\n  {item.detail}")
    print("Training")
    for option in view.methods:
        marker = "*" if option.selected else "o"
        suffix = "" if option.available else f"   (unavailable: {option.detail})"
        print(f"  {marker} {option.label}{suffix}")
    print(f"{view.device.kind.upper()}\n  {view.device.name}")
    filled = int(round((view.device.fraction or 0) * 10))
    bar = "#" * filled + "." * (10 - filled) if view.device.fraction is not None else "?" * 10
    print(f"  {bar}  {view.device.caption}")
    print()
    print(f"  [ {view.start.label} ]  {'enabled' if view.start.enabled else 'disabled'}")
    for reason in view.start.blocked_by:
        print(f"    - {reason}")
    return EXIT_OK if view.start.enabled else EXIT_MACHINE


# --------------------------------------------------------------------------- #
# train
# --------------------------------------------------------------------------- #


def _train(arguments: argparse.Namespace) -> int:
    policy = NetworkPolicy(
        allow_model_download=bool(arguments.allow_model_download),
        reason="--allow-model-download was given on the command line"
        if arguments.allow_model_download else "",
    )
    studio = ModelStudio(
        backend_id=arguments.backend,
        network=policy,
        store=JobStore(arguments.jobs_root) if arguments.jobs_root else None,
    )
    try:
        config = load_config(arguments.config)
    except ModelStudioError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INPUT

    last: dict[str, Any] = {"step": 0}

    def progress(event: Any) -> None:
        if arguments.json or arguments.quiet:
            return
        if event.kind == "step":
            last["step"] = event.step
            print(
                f"\rstep {event.step}/{event.total_steps or '?'}  "
                f"loss {event.loss:.4f}  {event.elapsed_seconds:.0f}s",
                end="", flush=True,
            )
        elif event.kind == "phase":
            if last["step"]:
                print()
            print(f"  {event.detail}", flush=True)
        elif event.kind == "epoch":
            print(f"\n  epoch {event.epoch} done", flush=True)

    record = studio.run(config, progress=progress)
    if arguments.json:
        _emit(record.to_json())
    else:
        print()
        print(f"job {record.job_id}: {record.state.upper()}")
        print(f"  {record.detail}")
        # The directory is named in the configuration from the moment the job is
        # created, so printing it for a run that never got as far as writing
        # anything points a reader at an empty or absent path and calls it the
        # artifacts. Print it when there is something there.
        if record.output_directory and Path(record.output_directory).is_dir():
            print(f"  artifacts: {record.output_directory}")
        evaluation = record.evaluation or {}
        if evaluation:
            print(f"  adapter tensors changed: {evaluation.get('adapterTensorsChanged')}"
                  f"/{evaluation.get('adapterTensorsTotal')}")
            print(f"  held-out loss: base {evaluation.get('baselineLoss')} -> "
                  f"adapter {evaluation.get('adapterLoss')}")
    return EXIT_OK if record.state == "completed" else EXIT_MACHINE


# --------------------------------------------------------------------------- #
# jobs / inspect / verify
# --------------------------------------------------------------------------- #


def _jobs(arguments: argparse.Namespace) -> int:
    store = JobStore(arguments.jobs_root) if arguments.jobs_root else JobStore()
    records = store.list()
    if arguments.json:
        _emit({"root": str(store.root), "jobs": [record.to_json() for record in records]})
        return EXIT_OK
    if not records:
        print(f"no jobs in {store.root}")
        return EXIT_OK
    print(f"{'JOB':<26}{'STATE':<14}{'UPDATED':<22}RUN")
    for record in records:
        print(f"{record.job_id:<26}{record.state:<14}{record.updated_at:<22}{record.run_name}")
    return EXIT_OK


def _inspect(arguments: argparse.Namespace) -> int:
    store = JobStore(arguments.jobs_root) if arguments.jobs_root else JobStore()
    try:
        record = store.load(arguments.job_id)
    except ModelStudioError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT
    if arguments.json:
        _emit(record.to_json())
        return EXIT_OK
    print(_rule(f"job {record.job_id}"))
    print(f"state       {record.state}")
    print(f"detail      {record.detail}")
    print(f"created     {record.created_at}")
    print(f"updated     {record.updated_at}")
    print(f"config      {record.config_path}")
    print(f"output      {record.output_directory}")
    print()
    print(_rule("history"))
    for change in record.history:
        print(f"{change.at}  {change.was or '-':<14} -> {change.became:<14} {change.detail}")
    if record.provenance:
        print()
        print(_rule("provenance"))
        for key in ("base_model", "base_revision", "dataset_sha256", "config_sha256",
                    "bunny_commit", "backend", "precision", "device", "gpu", "steps",
                    "final_loss", "adapter_sha256", "status"):
            print(f"{key:<22}{record.provenance.get(key)}")
    return EXIT_OK


def _verify(arguments: argparse.Namespace) -> int:
    artifacts = RunArtifacts(directory=Path(arguments.directory))
    problems = artifacts.verify()
    if arguments.json:
        _emit({"directory": str(artifacts.directory), "ok": not problems, "problems": problems})
    elif problems:
        print(f"{artifacts.directory}: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  {problem}")
    else:
        print(f"{artifacts.directory}: every file matches MANIFEST.json")
    return EXIT_OK if not problems else EXIT_MACHINE


def _backends(arguments: argparse.Namespace) -> int:
    rows = []
    for identifier in available_backends():
        status = ModelStudio(backend_id=identifier).detect()
        rows.append(status.to_json())
    if arguments.json:
        _emit({"backends": rows})
        return EXIT_OK
    for row in rows:
        print(f"{row['backendId']:<22}{'available' if row['available'] else 'unavailable'}")
        print(f"{'':<22}{row['detail']}")
        print(f"{'':<22}methods: {', '.join(row['capabilities']) or 'none'}")
    return EXIT_OK


# --------------------------------------------------------------------------- #


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="bunny-model",
        description="Bunny Model Studio: train a personal adapter, locally, on purpose.",
    )
    root.add_argument("--json", action="store_true", help="emit JSON")
    root.add_argument("--backend", default=DEFAULT_BACKEND,
                      help=f"training backend (default: {DEFAULT_BACKEND})")
    root.add_argument("--jobs-root", type=Path, default=None,
                      help="where job records live (default: the Bunny state directory)")
    sub = root.add_subparsers(dest="command", required=True)

    hardware = sub.add_parser("hardware", help="what this machine can train")
    hardware.add_argument("--path", type=Path, default=Path.cwd(),
                          help="the filesystem to report free space for")
    hardware.set_defaults(handler=_hardware)

    sub.add_parser("backends", help="which backends this build has").set_defaults(handler=_backends)

    for name, handler, help_text in (
        ("validate", _validate, "check a configuration and its dataset"),
        ("preflight", _preflight, "check the machine against a configuration"),
        ("view", _view, "the Model Studio screen's data, for a UI"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("config", type=Path)
        command.set_defaults(handler=handler)

    train = sub.add_parser("train", help="run a training job to completion")
    train.add_argument("config", type=Path)
    train.add_argument(
        "--allow-model-download", action="store_true",
        help="approve fetching the base model over the network for this run only. "
             "Without it nothing is downloaded and a missing base model blocks preflight.",
    )
    train.add_argument("--quiet", action="store_true", help="no per-step progress")
    train.set_defaults(handler=_train)

    sub.add_parser("jobs", help="every job and its state").set_defaults(handler=_jobs)

    inspect = sub.add_parser("inspect", help="one job in full")
    inspect.add_argument("job_id")
    inspect.set_defaults(handler=_inspect)

    verify = sub.add_parser("verify", help="check a run directory against its manifest")
    verify.add_argument("directory", type=Path)
    verify.set_defaults(handler=_verify)

    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(arguments.handler(arguments))
    except ModelStudioError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_MACHINE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

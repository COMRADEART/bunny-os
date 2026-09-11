#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce the accelerator snapshot selection reads. Never invents VRAM.

Prints JSON. On hosts without GPU/NPU nodes the result is unknown/absent with
evidence, not a fabricated pool. Throughput is not produced here — it comes
from ``scripts/agent_measure.py`` when a local model actually ran.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.agents.resources import (
    default_machine_resources,
    llama_cli_gpu_layers,
    selection_memory_budget,
    tier_product,
)


def main() -> int:
    resources = default_machine_resources()
    budget, axis = selection_memory_budget(resources)
    document = {
        "schema": "bunny-os/accelerator-snapshot/1",
        "gpuUsable": resources.gpu_usable,
        "gpuRuntime": resources.gpu_runtime or None,
        "gpuKind": resources.gpu_kind,
        "vramState": resources.vram_state,
        "vramAvailableBytes": resources.vram_available_bytes if resources.vram_known else None,
        "vramTotalBytes": resources.vram_total_bytes if resources.vram_known else None,
        "npuState": resources.npu_state,
        "evidence": resources.accelerator_evidence,
        "llamaCliGpuLayers": llama_cli_gpu_layers(resources),
        "selectionBudgetBytes": budget or None,
        "selectionBudgetAxis": axis if budget else "none",
        "tierProduct": tier_product(resources),
        "throughputTokensPerSecond": resources.throughput_tokens_per_second,
        "notes": [],
    }
    if not resources.gpu_usable:
        document["notes"].append("GPU offload not requested; llama-cli gets no --n-gpu-layers")
    if not resources.vram_known:
        document["notes"].append("VRAM unknown or absent; a number is not invented")
    if resources.npu_state != "absent":
        document["notes"].append("NPU is not a scheduleable runtime in this build")
    if resources.throughput_tokens_per_second is None:
        document["notes"].append("throughput NOT_RUN; measure with scripts/agent_measure.py on a host with a model")
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

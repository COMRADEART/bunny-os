# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Machines this project does not own, described well enough to test against.

The precision rule has to be right on an Ampere card, a Turing card, a Pascal
card, a machine with no CUDA runtime and a CPU. Nobody has all five, and the
consequence of getting one wrong is a run that fails minutes in on hardware the
author never sees. So the shape torch presents is faked precisely — the same
attribute names, the same call signatures, the same exceptions where a real
torch raises — and the probe is handed one.

Fakes have a well-known failure mode: they drift, and the tests keep passing
against a description of a library that no longer exists. Two things bound it
here. The faked surface is five calls wide, all of them stable public API. And
``test_training_slice.py`` runs the real thing end to end on a real model, so
the mocked tests are a statement about the *rule*, never about the hardware —
which is why no claim in the report rests on this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

__all__ = [
    "SMOLLM2_135M_CONFIG",
    "cpu_torch",
    "cuda_torch",
    "mps_torch",
    "write_dataset",
    "write_model_config",
]


class _Properties:
    def __init__(self, total: int, major: int, minor: int) -> None:
        self.total_memory = total
        self.major = major
        self.minor = minor


def cuda_torch(
    *,
    name: str = "NVIDIA A100-SXM4-40GB",
    capability: tuple[int, int] = (8, 0),
    bf16: bool | None = True,
    total_memory: int = 40 * 1024 ** 3,
    free_memory: int | None = None,
    version: str = "2.9.1",
    cuda_version: str = "12.8",
) -> Any:
    """A torch that reports a CUDA device.

    ``bf16=None`` makes ``is_bf16_supported`` raise, which is how an older torch
    behaves — the case the probe must resolve to ``UNKNOWN`` rather than to
    ``False``, because those two produce different precisions.
    """
    free = total_memory if free_memory is None else free_memory

    def is_bf16_supported() -> bool:
        if bf16 is None:
            raise AttributeError("is_bf16_supported is not available in this build")
        return bf16

    cuda = SimpleNamespace(
        is_available=lambda: True,
        current_device=lambda: 0,
        get_device_name=lambda index=0: name,
        get_device_properties=lambda index=0: _Properties(total_memory, *capability),
        is_bf16_supported=is_bf16_supported,
        mem_get_info=lambda index=0: (free, total_memory),
    )
    return SimpleNamespace(
        __version__=version,
        version=SimpleNamespace(cuda=cuda_version),
        cuda=cuda,
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )


def cpu_torch(*, version: str = "2.9.1+cpu", cuda_build: str | None = None) -> Any:
    """A torch with no usable accelerator. ``cuda_build`` set means a CUDA build with no device."""
    return SimpleNamespace(
        __version__=version,
        version=SimpleNamespace(cuda=cuda_build),
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )


def mps_torch(*, macos_14: bool = True) -> Any:
    return SimpleNamespace(
        __version__="2.9.1",
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(
            mps=SimpleNamespace(
                is_available=lambda: True,
                is_macos_or_newer=lambda major, minor: macos_14,
            )
        ),
    )


#: SmolLM2-135M-Instruct's real configuration, trimmed to the fields the
#: parameter count uses. Its published size is 135M; the arithmetic must land
#: on 134,515,008, which is what makes this a check rather than a fixture.
SMOLLM2_135M_CONFIG: dict[str, Any] = {
    "model_type": "llama",
    "hidden_size": 576,
    "num_hidden_layers": 30,
    "num_attention_heads": 9,
    "num_key_value_heads": 3,
    "intermediate_size": 1536,
    "vocab_size": 49152,
    "tie_word_embeddings": True,
    "max_position_embeddings": 8192,
}


def write_model_config(directory: Path, document: dict[str, Any] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.json"
    path.write_text(
        json.dumps(document if document is not None else SMOLLM2_135M_CONFIG),
        encoding="utf-8",
    )
    return path


def write_dataset(path: Path, conversations: list[list[dict[str, str]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps({"messages": item}) for item in conversations) + "\n",
        encoding="utf-8",
    )
    return path


def simple_conversations(count: int = 4) -> list[list[dict[str, str]]]:
    return [
        [
            {"role": "user", "content": f"Open folder {index}"},
            {"role": "assistant", "content": f"I'll open folder {index}."},
        ]
        for index in range(count)
    ]

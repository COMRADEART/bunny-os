# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Training backends, behind one protocol.

The registry is a mapping from an identifier to a *factory*, not to an
instance. Constructing a backend is allowed to be cheap and is not allowed to
import torch, but nothing here relies on that: a factory means the CLI can list
what exists without loading a numerical stack, which is what makes
``bunny-model backends`` answer in milliseconds on a machine with no GPU.

Adding ``SoupBackend``, ``UnslothBackend`` or ``MLXBackend`` is one entry here
and one module implementing :class:`~model_studio.backend.base.TrainingBackend`.
Nothing above this package changes, because nothing above this package has ever
named a backend except by identifier.
"""

from __future__ import annotations

from typing import Callable, Mapping

from ..errors import ConfigurationError
from .base import (
    BLOCKED,
    READY,
    UNKNOWN,
    BackendStatus,
    CancellationSignal,
    EvaluationResult,
    PreflightReport,
    ProgressEvent,
    TrainingBackend,
    TrainingPlan,
    TrainingResult,
)

__all__ = [
    "BLOCKED",
    "DEFAULT_BACKEND",
    "READY",
    "REGISTRY",
    "UNKNOWN",
    "BackendStatus",
    "CancellationSignal",
    "EvaluationResult",
    "PreflightReport",
    "ProgressEvent",
    "TrainingBackend",
    "TrainingPlan",
    "TrainingResult",
    "available_backends",
    "get_backend",
]


def _transformers_lora(**keywords: object) -> TrainingBackend:
    from .transformers_lora import TransformersLoraBackend

    return TransformersLoraBackend(**keywords)  # type: ignore[arg-type]


#: Every backend this build knows about.
REGISTRY: Mapping[str, Callable[..., TrainingBackend]] = {
    "transformers-lora": _transformers_lora,
}

DEFAULT_BACKEND = "transformers-lora"


def get_backend(identifier: str = DEFAULT_BACKEND, **keywords: object) -> TrainingBackend:
    factory = REGISTRY.get(identifier)
    if factory is None:
        raise ConfigurationError(
            f"no backend {identifier!r}; this build has {', '.join(sorted(REGISTRY))}"
        )
    return factory(**keywords)


def available_backends() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))

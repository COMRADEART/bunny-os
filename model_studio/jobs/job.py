# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bundle a backend is handed: one job, everything about it, nothing else.

A backend receives this and not the store, so it cannot move a job's state.
That separation is on purpose. The state machine is the record of what happened,
and a component that both does the work and writes down what it did will
eventually write down the wrong thing — most often when it fails, which is
exactly when the record matters. :class:`~model_studio.studio.ModelStudio` owns
the transitions; the backend owns the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts import RunArtifacts
from ..config import TrainingConfig
from ..datasets.chat import ChatDataset
from ..network import NetworkPolicy

__all__ = ["TrainingJob"]


@dataclass(frozen=True)
class TrainingJob:
    """Everything one run needs, resolved."""

    job_id: str
    config: TrainingConfig
    plan: object
    dataset: ChatDataset
    artifacts: RunArtifacts
    network: NetworkPolicy

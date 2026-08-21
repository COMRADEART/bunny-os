# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Training jobs: a state machine, a store that survives a crash, and a bundle."""

from __future__ import annotations

from . import state
from .job import TrainingJob
from .state import (
    ACTIVE,
    BLOCKED,
    CANCELLED,
    COMPLETED,
    CREATED,
    EVALUATING,
    FAILED,
    PREFLIGHTING,
    PREPARING,
    READY,
    STATES,
    TERMINAL,
    TRAINING,
    TRANSITIONS,
    check_transition,
)
from .store import JobRecord, JobStore, StateChange, default_jobs_root

__all__ = [
    "ACTIVE",
    "BLOCKED",
    "CANCELLED",
    "COMPLETED",
    "CREATED",
    "EVALUATING",
    "FAILED",
    "PREFLIGHTING",
    "PREPARING",
    "READY",
    "STATES",
    "TERMINAL",
    "TRAINING",
    "TRANSITIONS",
    "JobRecord",
    "JobStore",
    "StateChange",
    "TrainingJob",
    "check_transition",
    "default_jobs_root",
    "state",
]

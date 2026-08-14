# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What this machine is, and what that means for training on it."""

from __future__ import annotations

from .precision import PrecisionDecision, select_precision
from .probe import (
    SUPPORTED,
    UNKNOWN,
    UNSUPPORTED,
    Accelerator,
    HardwareReport,
    probe_hardware,
)

__all__ = [
    "SUPPORTED",
    "UNKNOWN",
    "UNSUPPORTED",
    "Accelerator",
    "HardwareReport",
    "PrecisionDecision",
    "probe_hardware",
    "select_precision",
]

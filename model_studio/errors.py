# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The failures this package raises, and the one class of failure it does not.

An exception here means *the caller asked for something impossible* — a
configuration that contradicts itself, a dataset that would teach the wrong
thing, a job transition that does not exist. Those are programming and input
errors, and raising is right: there is no partial answer to give.

The failures this module deliberately has no class for are the environmental
ones: no GPU, no ``peft`` installed, not enough VRAM, no base model on disk.
Those come back as data — :class:`~model_studio.backend.base.BackendStatus` and
:class:`~model_studio.backend.base.PreflightReport` — for the same reason
:mod:`companion.agents.adapter` returns an unavailable probe instead of raising
one: a raised absence gets caught somewhere unhelpful and becomes a silent skip,
and a UI cannot render a traceback into "your GPU is too small for this, here is
what would fit".
"""

from __future__ import annotations

__all__ = [
    "ConfigurationError",
    "DatasetError",
    "JobStateError",
    "ModelStudioError",
    "NetworkRefused",
    "PolicyViolation",
]


class ModelStudioError(RuntimeError):
    """Base for everything this package raises."""


class ConfigurationError(ModelStudioError):
    """A training configuration is invalid, or valid but unsafe to run."""


class DatasetError(ModelStudioError):
    """A dataset is malformed."""


class PolicyViolation(DatasetError):
    """A dataset example would train the model against Bunny's own permission model.

    A subclass of :class:`DatasetError` because it is found by the same pass and
    a caller that handles bad data handles this too — but a distinct type,
    because "line 12 is not JSON" and "line 12 teaches the assistant to run
    `sudo rm -rf` without asking" are not the same problem and a UI should not
    show them under one heading.
    """


class JobStateError(ModelStudioError):
    """A job was asked to make a transition its state machine does not have."""


class NetworkRefused(ModelStudioError):
    """An operation needed the network and no explicit approval was given.

    Raised rather than returned because reaching this point means a caller
    tried to do the one thing the default policy exists to prevent. There is no
    degraded mode to fall back to and nothing sensible to render: the operation
    does not happen.
    """

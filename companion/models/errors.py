# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What this package raises, and the much larger class of thing it does not.

Almost nothing here raises. An artifact that fails validation is a *result*:
:class:`~companion.models.validation.ValidationReport` with a status, a code and
a field. That is not politeness — it is the difference between a bad adapter
being a listed, explained, inactive model and a bad adapter being a traceback
somewhere in the Companion's start-up.

The exceptions that do exist are for callers who asked for something that
cannot be answered at all: a model id that is not a model id, or a registry
operation on something that was never discovered.
"""

from __future__ import annotations

from ..errors import CompanionError

__all__ = ["ModelArtifactError", "ModelBridgeError", "UnknownModel"]


class ModelBridgeError(CompanionError):
    """Base for the model bridge's own failures."""


class ModelArtifactError(ModelBridgeError):
    """An artifact could not be read at all — not "is invalid", but "is not one".

    Raised only by the parsing layer when the caller handed over something that
    cannot be treated as a manifest: unreadable bytes, not JSON, not an object.
    Everything downstream of a successful parse is reported rather than raised.
    """


class UnknownModel(ModelBridgeError):
    """The registry was asked about a model it never discovered."""

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed failures for the 3D subsystem.

Everything here descends from the character package's own error tree, so a
caller that already handles :class:`companion.character.errors.CharacterError`
handles a hostile GLB too without learning a new exception. The distinctions
that matter downstream are the three the existing code already makes — schema,
security, integrity — plus one this phase adds: a renderer that could not obtain
or keep a GPU context, which is a *degradation* rather than a bad package.
"""

from __future__ import annotations

from companion.character.errors import (
    CharacterError,
    CharacterSchemaError,
    CharacterSecurityError,
    RendererError,
)


class ModelSchemaError(CharacterSchemaError):
    """A glTF/GLB document does not satisfy the supported safe subset."""


class ModelSecurityError(CharacterSecurityError):
    """A model asked for something a character package may never have.

    External references, unknown required extensions, path traversal, embedded
    active content, and every resource bomb below the limits table raise this
    rather than :class:`ModelSchemaError`. The distinction is reported: a
    malformed file is a mistake, and a file reaching outside its package is not.
    """


class ModelLimitError(ModelSecurityError):
    """A declared or observed quantity exceeded its bound.

    A subclass of the security error on purpose. Every limit in
    :mod:`companion.character.three_d.limits` exists because the unbounded
    version of that quantity is an attack, and a caller that distinguishes
    "too big" from "hostile" would eventually treat one as the other.
    """


class RendererContextError(RendererError):
    """A GPU context could not be created, was lost, or refused a resource.

    Never fatal to a task. The presenter catches it, records a typed
    degradation, releases what it can and drops a rung.
    """


class RendererCapabilityError(RendererError):
    """The graphics stack lacks a feature the renderer requires."""


__all__ = [
    "CharacterError",
    "ModelLimitError",
    "ModelSchemaError",
    "ModelSecurityError",
    "RendererCapabilityError",
    "RendererContextError",
]

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed failures produced by the companion character presentation layer."""

from __future__ import annotations

from companion.errors import CompanionError


class CharacterError(CompanionError):
    """Base class for character package and renderer failures."""


class CharacterSchemaError(CharacterError):
    """A manifest does not satisfy the versioned package contract."""


class CharacterSecurityError(CharacterError):
    """Untrusted input crossed a package security boundary."""


class CharacterIntegrityError(CharacterError):
    """Declared and observed package content do not match."""


class CharacterCompatibilityError(CharacterError):
    """A valid package requires a renderer or Bunny OS version not present."""


class RendererError(RuntimeError):
    """A renderer failed after package validation completed."""


class RendererUnavailable(RendererError):
    """The requested presentation cannot run in the current environment."""

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue refusals.

``CatalogSchemaError``
    an entry, or the file holding it, is not something this build understands.
    Refused rather than partially loaded: a catalogue that silently dropped the
    fields it could not parse would present an application with fewer declared
    permissions than the curator wrote, which is the direction that widens.
``CatalogUnknown``
    nothing in the catalogue matches. Distinguished from an empty result so that
    "Bunny has nothing for that" and "Bunny has three and none are installable"
    reach the person as different sentences.
``CatalogRefused``
    an entry exists and will not be installed — unverified provenance, an
    architecture this machine is not, a sandbox incompatibility the person has
    not accepted.
"""

from __future__ import annotations

__all__ = ["CatalogError", "CatalogRefused", "CatalogSchemaError", "CatalogUnknown"]


class CatalogError(Exception):
    code = "catalog-error"


class CatalogSchemaError(CatalogError):
    code = "malformed"


class CatalogUnknown(CatalogError):
    code = "unknown"


class CatalogRefused(CatalogError):
    code = "refused"

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny App Catalogue: curated metadata, and nothing that fetches anything.

An application arrives in Bunny OS because somebody wrote an entry for it and
somebody reviewed that entry. There is no discovery, no scraping, no "install
from this URL", and no code path anywhere in this package that downloads or
executes. §13's rule — *arbitrary repositories must not automatically become
trusted applications* — is enforced by there being nothing here that could make
one.

What the catalogue is *for* is the two decisions immediately downstream of it.

**It establishes the permission ceiling.** An entry's declared permissions become
a :class:`~trust.declaration.PermissionDeclaration`, and an application cannot ask
for anything outside it — not "cannot without a prompt", but cannot at all. That
is the strong form of deny-by-default, and it means the catalogue entry is a
security artefact rather than a listing.

**It makes a choice honest.** §14 asks that a person who says "I need Photoshop"
be shown the commercial option, what it costs, and a free alternative, without
being told the free one is the same thing. The ``differences`` paragraph on each
entry is where the truth about that lives, it is written by a curator, and
:mod:`catalog.selection` can only read it out. There is no field in which a model
may write a comparison.

Module map:

:mod:`~catalog.entry`
    One application and every fact about it, including where the assurance comes
    from and what installing commits a person to.
:mod:`~catalog.registry`
    Loading the curated files, refusing to load half of them.
:mod:`~catalog.selection`
    Capability in, honest choices out.

The entries themselves are JSON under ``catalog/data/``. They ship in the image
and change only by a reviewed commit.
"""

from __future__ import annotations

from .entry import (
    COST_MODELS,
    OPTION_KINDS,
    PACKAGE_SOURCES,
    TRUST_STATUSES,
    UPDATE_MECHANISMS,
    CatalogEntry,
    HardwareRequirements,
)
from .errors import CatalogError, CatalogRefused, CatalogSchemaError, CatalogUnknown
from .registry import CATALOG_SCHEMA_VERSION, CatalogRegistry, default_catalog_directory, load_catalog
from .selection import COMMITMENTS, ApplicationChoice, ChoiceSet, MachineFacts, choices_for

__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "COMMITMENTS",
    "COST_MODELS",
    "OPTION_KINDS",
    "PACKAGE_SOURCES",
    "TRUST_STATUSES",
    "UPDATE_MECHANISMS",
    "ApplicationChoice",
    "CatalogEntry",
    "CatalogError",
    "CatalogRefused",
    "CatalogRegistry",
    "CatalogSchemaError",
    "CatalogUnknown",
    "ChoiceSet",
    "HardwareRequirements",
    "MachineFacts",
    "choices_for",
    "default_catalog_directory",
    "load_catalog",
]

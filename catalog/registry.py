# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading the curated catalogue, and refusing to load half of it.

The catalogue ships as JSON files under ``catalog/data/`` and is part of the
image. It is not fetched, not synchronised and not extensible at runtime by an
application: adding an entry is a change to the repository that somebody reviews,
which is the whole of what "curated" means here.

**A malformed entry fails the load.** Not skipped. A catalogue that dropped the
entries it could not parse would present a shorter list, and the entries most
likely to be malformed are the ones somebody has tampered with. The error names
the file and the entry.

**Duplicate ids fail the load.** Two entries claiming one application id would
make "which declaration applies" depend on iteration order, and the declaration
is a security ceiling.

**The registry answers three questions and no others**: what is this entry, which
entries provide this capability, and what does the trust layer need to know about
this application id. Anything that installs, downloads or launches is somewhere
else, on purpose — a module that both describes software and fetches it is a
module where a description can become a fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from trust.declaration import UNDECLARED, PermissionDeclaration

from .entry import CAPABILITY_PATTERN, CatalogEntry
from .errors import CatalogSchemaError, CatalogUnknown

__all__ = ["CATALOG_SCHEMA_VERSION", "CatalogRegistry", "default_catalog_directory", "load_catalog"]

#: Bumped with ``schemas/app-catalog-entry.schema.json``.
CATALOG_SCHEMA_VERSION = 1


#: Where the entries land on an installed system. A package route copies Python
#: source; the JSON entries are data and are installed separately, so the
#: installed tree has ``catalog/`` without ``catalog/data/`` inside it.
INSTALLED_CATALOG_DIRECTORY = Path("/usr/share/bunny-os/catalog")


def default_catalog_directory() -> Path:
    """Where the curated entries live: the image first, then this checkout.

    The installed path wins when it exists, so a booted system reads the
    reviewed bytes that shipped with it rather than anything a checkout beside
    it happens to contain. The source tree is the fallback for development and
    for the tests.

    The order matters more than it looks. If this returned the source directory
    on an installed system it would find nothing, every application would
    resolve to :func:`~trust.declaration.UNDECLARED`, and the trust layer would
    refuse everything not already granted — fail-closed, correct, and
    indistinguishable from a permission bug to anybody using it.
    """
    if INSTALLED_CATALOG_DIRECTORY.is_dir():
        return INSTALLED_CATALOG_DIRECTORY
    return Path(__file__).resolve().parent / "data"


@dataclass
class CatalogRegistry:
    """Every curated entry, indexed by id, application and capability."""

    entries: Mapping[str, CatalogEntry] = field(default_factory=dict)

    # -- construction ----------------------------------------------------

    @classmethod
    def from_entries(cls, entries: Iterable[CatalogEntry]) -> "CatalogRegistry":
        indexed: dict[str, CatalogEntry] = {}
        seen_applications: dict[str, str] = {}
        for entry in entries:
            if entry.entry_id in indexed:
                raise CatalogSchemaError(f"duplicate catalogue entry id: {entry.entry_id}")
            previous = seen_applications.get(entry.application_id)
            if previous is not None:
                raise CatalogSchemaError(
                    f"{entry.application_id} is claimed by both {previous} and {entry.entry_id}"
                )
            seen_applications[entry.application_id] = entry.entry_id
            indexed[entry.entry_id] = entry
        return cls(entries=indexed)

    @classmethod
    def load(cls, directory: Path | None = None) -> "CatalogRegistry":
        base = Path(directory) if directory is not None else default_catalog_directory()
        found: list[CatalogEntry] = []
        if not base.is_dir():
            return cls.from_entries(())
        for path in sorted(base.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CatalogSchemaError(f"{path} could not be read: {exc}") from exc
            if not isinstance(document, Mapping):
                raise CatalogSchemaError(f"{path} does not contain a catalogue document")
            version = document.get("schemaVersion")
            if version != CATALOG_SCHEMA_VERSION:
                raise CatalogSchemaError(
                    f"{path} is schema version {version!r}; this build understands {CATALOG_SCHEMA_VERSION}"
                )
            records = document.get("entries")
            if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
                raise CatalogSchemaError(f"{path} has no entry list")
            for record in records:
                try:
                    found.append(CatalogEntry.from_record(record))
                except CatalogSchemaError as exc:
                    raise CatalogSchemaError(f"{path}: {exc}") from exc
        return cls.from_entries(found)

    # -- questions -------------------------------------------------------

    def entry(self, entry_id: str) -> CatalogEntry:
        try:
            return self.entries[entry_id]
        except KeyError:
            raise CatalogUnknown(f"no catalogue entry called {entry_id!r}") from None

    def for_application(self, application_id: str) -> CatalogEntry | None:
        for entry in self.entries.values():
            if entry.application_id == application_id:
                return entry
        return None

    def declaration_for(self, application_id: str) -> PermissionDeclaration:
        """What the trust layer should treat as this application's ceiling.

        Returns :func:`~trust.declaration.UNDECLARED` when there is no entry, so
        an application whose catalogue entry was removed is refused everything it
        does not already hold, and the refusal says the catalogue does not know
        it rather than raising somewhere a permission check cannot recover.
        """
        entry = self.for_application(application_id)
        return entry.declaration() if entry is not None else UNDECLARED(application_id)

    def names(self) -> Mapping[str, str]:
        """Application id to display name, for the trust prompts and the audit."""
        return {entry.application_id: entry.name for entry in self.entries.values()}

    def providing(self, capability: str) -> tuple[CatalogEntry, ...]:
        """Every entry that says it can do ``capability``.

        Order is deterministic and deliberate: installable before not, then by
        option kind in the order §14 lists them, then by name. A person reading a
        list of choices should meet them in the same order every time, and a
        ranking that depended on a score would be a recommendation Bunny cannot
        justify.
        """
        if not CAPABILITY_PATTERN.match(capability or ""):
            raise CatalogSchemaError(f"not a capability slug: {capability!r}")
        from .entry import OPTION_KINDS

        matches = [entry for entry in self.entries.values() if capability in entry.capabilities]
        matches.sort(
            key=lambda entry: (
                not entry.installable,
                OPTION_KINDS.index(entry.option_kind),
                entry.name.lower(),
            )
        )
        return tuple(matches)

    def capabilities(self) -> tuple[str, ...]:
        found: set[str] = set()
        for entry in self.entries.values():
            found.update(entry.capabilities)
        return tuple(sorted(found))

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(sorted(self.entries.values(), key=lambda entry: entry.entry_id))


def load_catalog(directory: Path | None = None) -> CatalogRegistry:
    return CatalogRegistry.load(directory)

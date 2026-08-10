# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a capsule is: the document that survives every launch.

The manifest is written once at install and read on every launch. It holds the
facts that do not change with a session — identity, package source, declared
permissions, resource limits, network ceiling, backend — and deliberately holds
no permission *grants*. Grants live in the trust store, and keeping them out of
here is what makes revocation work: a manifest is a description of the
application, and a person revoking a permission must not have to edit a
description of an application to do it.

**The manifest is the ceiling, not the permission.** ``required`` and ``optional``
say what the application may ever be asked about. What it actually holds is the
intersection of that with the trust store, computed at launch by
:func:`capsules.isolation.plan`. A manifest that granted anything would be a
second grant store, and the two would disagree.

**Resource limits are declared here and enforced by the cgroup.** Memory, task
count and CPU weight, expressed as systemd properties. They exist because §24
asks that isolation not make the desktop feel slow, and the honest way to keep
one application from doing that is a limit rather than a hope.

**The backend is a request, not a promise.** ``preferred_backend`` says which
isolation mechanism this application is expected to run under; whether it is
*available* is a property of the machine, answered by
:mod:`capsules.backends`. An application whose preferred backend is missing does
not silently run unconfined — it reports unavailable, which is §22's fail-closed
rule applied to the sandbox itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from trust.categories import CATEGORIES, descriptor
from trust.declaration import PermissionDeclaration
from trust.persistence import atomic_write_json, read_json
from trust.resources import NETWORK_CLASSES

from .errors import CapsuleSchemaError
from .identity import CapsuleIdentity, capsule_identity

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "PACKAGE_SOURCES",
    "ResourceLimits",
    "CapsuleManifest",
]

MANIFEST_SCHEMA_VERSION = 1

#: Where the application's bits came from. Not a trust level — that is the
#: catalogue's business — but it decides which backend can run it and what an
#: update means.
PACKAGE_SOURCES = ("flatpak", "fedora-rpm", "bunny-system", "appimage", "web")

#: Defaults sized for a desktop application rather than for a server. A limit
#: that is never hit costs nothing; a limit that is hit turns "the machine froze"
#: into "one application was stopped", which is the outcome a person can act on.
_DEFAULT_MEMORY_HIGH = 2 * 1024 * 1024 * 1024
_DEFAULT_MEMORY_MAX = 4 * 1024 * 1024 * 1024
_DEFAULT_TASKS_MAX = 512
_DEFAULT_CPU_WEIGHT = 100


@dataclass(frozen=True)
class ResourceLimits:
    """Limits applied to the capsule's cgroup, in systemd's own vocabulary.

    ``memory_high`` throttles and reclaims; ``memory_max`` kills. Both are set
    because only having the second turns a memory-hungry moment into a lost
    document, while only having the first lets a leak consume the machine slowly.
    """

    memory_high: int = _DEFAULT_MEMORY_HIGH
    memory_max: int = _DEFAULT_MEMORY_MAX
    tasks_max: int = _DEFAULT_TASKS_MAX
    cpu_weight: int = _DEFAULT_CPU_WEIGHT

    def __post_init__(self) -> None:
        for name in ("memory_high", "memory_max", "tasks_max", "cpu_weight"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise CapsuleSchemaError(f"{name} must be a positive integer")
        if self.memory_high > self.memory_max:
            raise CapsuleSchemaError("memory_high above memory_max would never throttle before killing")
        if not 1 <= self.cpu_weight <= 10000:
            raise CapsuleSchemaError("cpu_weight is a systemd weight between 1 and 10000")

    def systemd_properties(self) -> tuple[str, ...]:
        """The ``--property`` arguments a transient scope is started with."""
        return (
            f"MemoryHigh={self.memory_high}",
            f"MemoryMax={self.memory_max}",
            f"TasksMax={self.tasks_max}",
            f"CPUWeight={self.cpu_weight}",
        )

    def as_record(self) -> Mapping[str, Any]:
        return {
            "memoryHigh": self.memory_high,
            "memoryMax": self.memory_max,
            "tasksMax": self.tasks_max,
            "cpuWeight": self.cpu_weight,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ResourceLimits":
        try:
            return cls(
                memory_high=int(record.get("memoryHigh", _DEFAULT_MEMORY_HIGH)),
                memory_max=int(record.get("memoryMax", _DEFAULT_MEMORY_MAX)),
                tasks_max=int(record.get("tasksMax", _DEFAULT_TASKS_MAX)),
                cpu_weight=int(record.get("cpuWeight", _DEFAULT_CPU_WEIGHT)),
            )
        except (TypeError, ValueError) as exc:
            raise CapsuleSchemaError(f"not a resource limit record: {exc}") from exc


@dataclass(frozen=True)
class CapsuleManifest:
    """Everything durable about one application's capsule."""

    identity: CapsuleIdentity
    display_name: str
    package_source: str
    package_reference: str
    preferred_backend: str
    required_permissions: frozenset[str] = frozenset()
    optional_permissions: frozenset[str] = frozenset()
    permission_reasons: Mapping[str, str] = field(default_factory=dict)
    network_ceiling: str = "none"
    network_domains: frozenset[str] = frozenset()
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    #: Which of the required permissions the user consented to at install. Stored
    #: as a boolean rather than a set: the consent was to the whole install-time
    #: bundle, and recording it per category would suggest a person answered
    #: seventeen questions when they answered one.
    install_consent: bool = False
    #: Set when the application is expected to keep running with no window. Only
    #: meaningful if ``background`` is granted; the manifest records the
    #: *expectation*, the grant records the permission.
    wants_background: bool = False
    catalog_entry_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise CapsuleSchemaError("a capsule needs a display name")
        if len(self.display_name) > 128:
            raise CapsuleSchemaError("display name longer than 128 characters")
        if self.package_source not in PACKAGE_SOURCES:
            raise CapsuleSchemaError(f"unknown package source: {self.package_source!r}")
        if not isinstance(self.package_reference, str) or not self.package_reference.strip():
            raise CapsuleSchemaError("a capsule needs a package reference")
        overlap = self.required_permissions & self.optional_permissions
        if overlap:
            raise CapsuleSchemaError(f"declared both required and optional: {sorted(overlap)}")
        for category in sorted(self.required_permissions | self.optional_permissions):
            descriptor(category)
        if self.network_ceiling not in NETWORK_CLASSES:
            raise CapsuleSchemaError(f"unknown network class: {self.network_ceiling!r}")
        if self.network_ceiling != "none" and "network" not in (
            self.required_permissions | self.optional_permissions
        ):
            raise CapsuleSchemaError("a network ceiling without a declared network permission")
        if self.wants_background and "background" not in (
            self.required_permissions | self.optional_permissions
        ):
            raise CapsuleSchemaError("wanting to run in the background without declaring the permission")

    # -- projections -----------------------------------------------------

    def declaration(self) -> PermissionDeclaration:
        """The manifest as the trust layer wants to see it.

        A projection rather than shared storage. The trust layer must be able to
        answer about an application whose manifest is missing — the answer is
        denial — and that requires the declaration to be a value it is handed,
        not a file it reads.
        """
        return PermissionDeclaration(
            application_id=self.identity.application_id,
            required=frozenset(self.required_permissions),
            optional=frozenset(self.optional_permissions),
            reasons=dict(self.permission_reasons),
            network_ceiling=self.network_ceiling,
            network_domains=frozenset(self.network_domains),
            known=True,
        )

    def declares(self, category: str) -> bool:
        return category in self.required_permissions or category in self.optional_permissions

    def unenforced_permissions(self) -> tuple[str, ...]:
        """Declared categories this build records but does not actually restrict.

        Surfaced in Settings and in the install prompt. A permission model that
        listed a restriction it did not apply would teach people that denying
        works when it does not, and this is the list that keeps the claim honest.
        """
        return tuple(
            sorted(
                category
                for category in (self.required_permissions | self.optional_permissions)
                if not CATEGORIES[category].enforced_by_default
            )
        )

    def with_install_consent(self, consented: bool) -> "CapsuleManifest":
        return replace(self, install_consent=bool(consented))

    # -- persistence -----------------------------------------------------

    def as_record(self) -> Mapping[str, Any]:
        return {
            "schemaVersion": MANIFEST_SCHEMA_VERSION,
            "applicationId": self.identity.application_id,
            "directoryName": self.identity.directory_name,
            "displayName": self.display_name,
            "packageSource": self.package_source,
            "packageReference": self.package_reference,
            "preferredBackend": self.preferred_backend,
            "requiredPermissions": sorted(self.required_permissions),
            "optionalPermissions": sorted(self.optional_permissions),
            "permissionReasons": dict(sorted(self.permission_reasons.items())),
            "networkCeiling": self.network_ceiling,
            "networkDomains": sorted(self.network_domains),
            "limits": dict(self.limits.as_record()),
            "installConsent": self.install_consent,
            "wantsBackground": self.wants_background,
            "catalogEntryId": self.catalog_entry_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CapsuleManifest":
        if not isinstance(record, Mapping):
            raise CapsuleSchemaError("a manifest must be a record")
        version = record.get("schemaVersion")
        if version != MANIFEST_SCHEMA_VERSION:
            raise CapsuleSchemaError(
                f"manifest schema version {version!r}; this build understands {MANIFEST_SCHEMA_VERSION}"
            )
        try:
            identity = capsule_identity(str(record["applicationId"]))
            return cls(
                identity=identity,
                display_name=str(record["displayName"]),
                package_source=str(record["packageSource"]),
                package_reference=str(record["packageReference"]),
                preferred_backend=str(record["preferredBackend"]),
                required_permissions=frozenset(str(x) for x in record.get("requiredPermissions", ())),
                optional_permissions=frozenset(str(x) for x in record.get("optionalPermissions", ())),
                permission_reasons={str(k): str(v) for k, v in dict(record.get("permissionReasons", {})).items()},
                network_ceiling=str(record.get("networkCeiling", "none")),
                network_domains=frozenset(str(x) for x in record.get("networkDomains", ())),
                limits=ResourceLimits.from_record(dict(record.get("limits", {}))),
                install_consent=bool(record.get("installConsent", False)),
                wants_background=bool(record.get("wantsBackground", False)),
                catalog_entry_id=(str(record["catalogEntryId"]) if record.get("catalogEntryId") else None),
            )
        except KeyError as exc:
            raise CapsuleSchemaError(f"manifest is missing {exc}") from exc

    def write(self, path) -> None:  # type: ignore[no-untyped-def]
        atomic_write_json(path, dict(self.as_record()))

    @classmethod
    def read(cls, path) -> "CapsuleManifest":  # type: ignore[no-untyped-def]
        document = read_json(path, default=None)
        if document is None:
            raise CapsuleSchemaError(f"{path} does not exist")
        return cls.from_record(document)

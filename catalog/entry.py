# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One curated application, and the facts a person needs before installing it.

The catalogue is metadata, not a package manager. It never fetches anything and
never executes anything; it says what is true about an application so that the
install flow and the trust layer have something to work from. §13's constraint is
the shape of this module: *arbitrary repositories must not automatically become
trusted applications*, so there is no field in which a URL turns into an install,
and :data:`TRUST_STATUSES` has no value meaning "found on the internet".

Three fields carry most of the weight.

``trust_status``
    Where the assurance comes from. ``bunny-verified`` means somebody on this
    project reviewed the entry; ``distribution`` means Fedora packages and signs
    it; ``flathub-verified`` means Flathub's verified-publisher process;
    ``vendor`` means the software's own publisher signs it and Bunny checked the
    signing identity, not the software. ``unverified`` exists so an entry can be
    *listed* and not installable without an explicit override — being honest
    about a gap is better than omitting the application and letting somebody find
    it elsewhere.

``cost``
    ``free``, ``paid``, ``subscription``, or ``freemium``, plus
    ``requires_account``. §14 turns on these: when a person asks for a capability
    rather than a program, they are shown the commercial option *and* what it
    actually costs them, in the same list.

``differences``
    Free text, written by whoever curated the entry, saying how this option
    genuinely differs from the alternatives. It exists because §14 forbids
    claiming an open-source tool is identical to a commercial one, and the only
    way to avoid that claim is to have somewhere to put the truth. It is never
    generated: a missing ``differences`` renders as nothing, not as an invention.

**A catalogue entry cannot grant a permission.** It declares what the application
will ask for, which becomes a :class:`~trust.declaration.PermissionDeclaration`
and therefore a ceiling. Whether a permission is held is the trust store's
business, and the split is what stops a catalogue update from silently widening
what an installed application can reach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from trust.categories import CATEGORIES, descriptor
from trust.declaration import PermissionDeclaration
from trust.resources import NETWORK_CLASSES

from .errors import CatalogSchemaError

__all__ = [
    "CAPABILITY_PATTERN",
    "COST_MODELS",
    "OPTION_KINDS",
    "PACKAGE_SOURCES",
    "TRUST_STATUSES",
    "UPDATE_MECHANISMS",
    "CatalogEntry",
    "HardwareRequirements",
]

#: Where the bits come from. Every value is a source with a signing story;
#: ``github-release`` requires a named publisher and a pinned signing identity,
#: which is what keeps §13's "GitHub may be a source for verified open-source
#: projects" from becoming "any repository".
PACKAGE_SOURCES = ("fedora-rpm", "flatpak", "bunny-system", "vendor-rpm", "github-release", "web")

TRUST_STATUSES = ("bunny-verified", "distribution", "flathub-verified", "vendor", "unverified")

COST_MODELS = ("free", "freemium", "paid", "subscription")

UPDATE_MECHANISMS = ("bootc-image", "dnf", "flatpak", "vendor-updater", "none")

#: How an option is presented in a choice. §14's four rows.
OPTION_KINDS = ("commercial", "open-source", "web", "installed")

#: A capability is a stable slug the companion maps an intent onto —
#: ``edit-image``, ``remove-background``, ``write-document``. Deliberately not
#: free text: a capability that could be any string would make the mapping from
#: what a person said to what gets installed unauditable.
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")

_MAX_TEXT = 400


def _text(value: object, field_name: str, *, required: bool = True, limit: int = _MAX_TEXT) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise CatalogSchemaError(f"{field_name} must be a non-empty string")
    if len(value) > limit:
        raise CatalogSchemaError(f"{field_name} exceeds {limit} characters")
    return value


@dataclass(frozen=True)
class HardwareRequirements:
    """What the application needs to be usable, not merely to start.

    Stated so the choice list can say "this needs 8 GB and you have 4" rather
    than installing it and letting the person find out. ``None`` means the
    curator did not state a figure, which is different from zero and is rendered
    as silence.
    """

    memory_bytes: int | None = None
    disk_bytes: int | None = None
    needs_gpu: bool = False
    architectures: tuple[str, ...] = ("x86_64",)

    def as_record(self) -> Mapping[str, Any]:
        return {
            "memoryBytes": self.memory_bytes,
            "diskBytes": self.disk_bytes,
            "needsGpu": self.needs_gpu,
            "architectures": list(self.architectures),
        }


@dataclass(frozen=True)
class CatalogEntry:
    """One application, as the catalogue describes it."""

    entry_id: str
    application_id: str
    name: str
    publisher: str
    purpose: str
    capabilities: tuple[str, ...]
    package_source: str
    package_reference: str
    license_id: str
    cost: str
    trust_status: str
    update_mechanism: str
    option_kind: str
    preferred_backend: str
    required_permissions: frozenset[str] = frozenset()
    optional_permissions: frozenset[str] = frozenset()
    permission_reasons: Mapping[str, str] = field(default_factory=dict)
    network_ceiling: str = "none"
    network_domains: frozenset[str] = frozenset()
    requires_account: bool = False
    sandbox_compatible: bool = True
    #: Why the sandbox does not fit, when it does not. Required whenever
    #: ``sandbox_compatible`` is False, so an incompatibility is always a stated
    #: reason rather than a silent exception.
    sandbox_note: str = ""
    differences: str = ""
    hardware: HardwareRequirements = field(default_factory=HardwareRequirements)
    #: A signing identity the source must present. Required for the two sources
    #: that are not a distribution or Flathub, which is the mechanism that keeps
    #: "a GitHub release" from meaning "whatever is at that URL today".
    signing_identity: str = ""

    def __post_init__(self) -> None:
        _text(self.entry_id, "entry_id", limit=128)
        if not CAPABILITY_PATTERN.match(self.entry_id):
            raise CatalogSchemaError(f"not a catalogue entry id: {self.entry_id!r}")
        _text(self.name, "name", limit=128)
        _text(self.publisher, "publisher", limit=128)
        _text(self.purpose, "purpose")
        _text(self.package_reference, "package_reference", limit=256)
        _text(self.license_id, "license_id", limit=64)
        if not self.capabilities:
            raise CatalogSchemaError(f"{self.entry_id} declares no capability")
        for capability in self.capabilities:
            if not CAPABILITY_PATTERN.match(capability):
                raise CatalogSchemaError(f"not a capability slug: {capability!r}")
        for name, value, allowed in (
            ("package_source", self.package_source, PACKAGE_SOURCES),
            ("cost", self.cost, COST_MODELS),
            ("trust_status", self.trust_status, TRUST_STATUSES),
            ("update_mechanism", self.update_mechanism, UPDATE_MECHANISMS),
            ("option_kind", self.option_kind, OPTION_KINDS),
        ):
            if value not in allowed:
                raise CatalogSchemaError(f"{self.entry_id}: unknown {name} {value!r}")
        overlap = self.required_permissions & self.optional_permissions
        if overlap:
            raise CatalogSchemaError(f"{self.entry_id} declares both required and optional: {sorted(overlap)}")
        for category in sorted(self.required_permissions | self.optional_permissions):
            descriptor(category)
        for category in self.permission_reasons:
            if category not in (self.required_permissions | self.optional_permissions):
                raise CatalogSchemaError(f"{self.entry_id}: reason for undeclared {category}")
        if self.network_ceiling not in NETWORK_CLASSES:
            raise CatalogSchemaError(f"{self.entry_id}: unknown network class {self.network_ceiling!r}")
        if self.network_ceiling != "none" and "network" not in (
            self.required_permissions | self.optional_permissions
        ):
            raise CatalogSchemaError(f"{self.entry_id}: a network ceiling without a network permission")
        if not self.sandbox_compatible and not self.sandbox_note.strip():
            raise CatalogSchemaError(f"{self.entry_id}: a sandbox incompatibility needs a stated reason")
        if self.package_source in ("vendor-rpm", "github-release") and not self.signing_identity.strip():
            raise CatalogSchemaError(
                f"{self.entry_id}: {self.package_source} requires a pinned signing identity"
            )
        if self.option_kind == "web" and self.package_source != "web":
            raise CatalogSchemaError(f"{self.entry_id}: a web option must have a web package source")

    # -- projections -----------------------------------------------------

    def declaration(self) -> PermissionDeclaration:
        """The permission ceiling this entry establishes."""
        return PermissionDeclaration(
            application_id=self.application_id,
            required=frozenset(self.required_permissions),
            optional=frozenset(self.optional_permissions),
            reasons=dict(self.permission_reasons),
            network_ceiling=self.network_ceiling,
            network_domains=frozenset(self.network_domains),
            known=True,
        )

    @property
    def delivery(self) -> str:
        """How, if at all, a person can actually get to this application here.

        Three answers, and keeping them apart is what stops a listing from
        implying an install. ``capsule`` means Bunny installs it and runs it in
        an App Capsule. ``browser`` means it is a web page — usable, but the
        isolation is the browser's and Bunny says so. ``not-available`` is the
        row §14 requires and most catalogues omit: the commercial product exists,
        a person may well want it, and there is no build for this computer. It is
        listed with that fact attached rather than hidden, because a person who
        is not told will go and look for it.
        """
        if self.package_source != "web":
            return "capsule"
        return "browser" if self.option_kind == "web" else "not-available"

    @property
    def installable(self) -> bool:
        """Whether Bunny will install this without an explicit override.

        An ``unverified`` entry is listed and not installed. Listing it is the
        honest move — the application exists and a person may want it — and
        refusing to install it silently is not, so :mod:`catalog.selection`
        carries the reason into the choice.
        """
        return self.trust_status != "unverified" and self.delivery == "capsule"

    @property
    def high_risk_permissions(self) -> tuple[str, ...]:
        """Declared permissions that will always be asked for at the moment of use."""
        return tuple(
            sorted(
                category
                for category in (self.required_permissions | self.optional_permissions)
                if not CATEGORIES[category].catalog_grantable
            )
        )

    def as_record(self) -> Mapping[str, Any]:
        return {
            "entryId": self.entry_id,
            "applicationId": self.application_id,
            "name": self.name,
            "publisher": self.publisher,
            "purpose": self.purpose,
            "capabilities": list(self.capabilities),
            "packageSource": self.package_source,
            "packageReference": self.package_reference,
            "license": self.license_id,
            "cost": self.cost,
            "requiresAccount": self.requires_account,
            "trustStatus": self.trust_status,
            "updateMechanism": self.update_mechanism,
            "optionKind": self.option_kind,
            "preferredBackend": self.preferred_backend,
            "requiredPermissions": sorted(self.required_permissions),
            "optionalPermissions": sorted(self.optional_permissions),
            "permissionReasons": dict(sorted(self.permission_reasons.items())),
            "networkCeiling": self.network_ceiling,
            "networkDomains": sorted(self.network_domains),
            "sandboxCompatible": self.sandbox_compatible,
            "sandboxNote": self.sandbox_note,
            "differences": self.differences,
            "hardware": dict(self.hardware.as_record()),
            "signingIdentity": self.signing_identity,
            "delivery": self.delivery,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CatalogEntry":
        if not isinstance(record, Mapping):
            raise CatalogSchemaError("a catalogue entry must be a record")
        try:
            hardware = dict(record.get("hardware", {}))
            return cls(
                entry_id=str(record["entryId"]),
                application_id=str(record["applicationId"]),
                name=str(record["name"]),
                publisher=str(record["publisher"]),
                purpose=str(record["purpose"]),
                capabilities=tuple(str(x) for x in record["capabilities"]),
                package_source=str(record["packageSource"]),
                package_reference=str(record["packageReference"]),
                license_id=str(record["license"]),
                cost=str(record["cost"]),
                trust_status=str(record["trustStatus"]),
                update_mechanism=str(record["updateMechanism"]),
                option_kind=str(record["optionKind"]),
                preferred_backend=str(record["preferredBackend"]),
                required_permissions=frozenset(str(x) for x in record.get("requiredPermissions", ())),
                optional_permissions=frozenset(str(x) for x in record.get("optionalPermissions", ())),
                permission_reasons={
                    str(k): str(v) for k, v in dict(record.get("permissionReasons", {})).items()
                },
                network_ceiling=str(record.get("networkCeiling", "none")),
                network_domains=frozenset(str(x) for x in record.get("networkDomains", ())),
                requires_account=bool(record.get("requiresAccount", False)),
                sandbox_compatible=bool(record.get("sandboxCompatible", True)),
                sandbox_note=str(record.get("sandboxNote", "")),
                differences=str(record.get("differences", "")),
                hardware=HardwareRequirements(
                    memory_bytes=(int(hardware["memoryBytes"]) if hardware.get("memoryBytes") else None),
                    disk_bytes=(int(hardware["diskBytes"]) if hardware.get("diskBytes") else None),
                    needs_gpu=bool(hardware.get("needsGpu", False)),
                    architectures=tuple(str(x) for x in hardware.get("architectures", ("x86_64",))),
                ),
                signing_identity=str(record.get("signingIdentity", "")),
            )
        except KeyError as exc:
            raise CatalogSchemaError(f"catalogue entry is missing {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise CatalogSchemaError(f"catalogue entry is malformed: {exc}") from exc

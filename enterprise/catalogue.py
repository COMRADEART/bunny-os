# SPDX-License-Identifier: Apache-2.0
"""Organisation application catalogue layered over the Bunny OS catalogue.

Distinct from ``operations/catalogue.py``, which curates the project-wide
catalogue. An organisation catalogue *adds* entries for a single tenant and can
mark project entries required or blocked, but it cannot lower a trust
requirement: an unsigned package is refused at the trusted catalogue interface
regardless of who added it.

Package format determines the maximum permission surface. A Flatpak entry cannot
declare permissions beyond what the sandbox can express, and a native RPM entry
is labelled as having broad system access so an administrator cannot deploy one
believing it is contained.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

PACKAGE_FORMATS = ("flatpak", "rpm", "oci-container")

SOURCES = ("bunny-os-catalogue", "flathub-verified", "organisation-repository", "oem-signed-extension")

DEPLOYMENT_STATES = ("required", "optional-approved", "blocked", "deprecated")

UPDATE_POLICIES = ("automatic", "ring-managed", "manual", "pinned")

REMOVAL_POLICIES = ("user-removable", "administrator-only", "removed-on-unenrolment")

#: Permissions a Flatpak entry may declare. The set is bounded by what the
#: sandbox can actually enforce; a broader claim is a rejection.
FLATPAK_PERMISSIONS = frozenset({
    "network",
    "home-read",
    "home-read-write",
    "documents-portal",
    "camera",
    "microphone",
    "audio-playback",
    "printing",
    "removable-media",
    "gpu-acceleration",
    "notifications",
})

#: Native package formats have no enforceable permission boundary. Entries using
#: them must be labelled, and the label cannot be suppressed.
BROAD_ACCESS_FORMATS = frozenset({"rpm"})

BROAD_ACCESS_LABEL = (
    "This package installs natively and has broad system access. It is not confined by the "
    "application sandbox and can read or modify system state and user data."
)

_PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_FLATPAK_ID = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+){2,}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:+~_-]{0,63}$")
_ORGANISATION_ID = re.compile(r"^org-[a-z0-9][a-z0-9-]{1,62}$")


class CatalogueError(ValueError):
    """Raised when a catalogue entry violates a trust or permission rule."""


@dataclass(frozen=True)
class CatalogueEntry:
    organisationId: str
    packageId: str
    source: str
    packageFormat: str
    publisher: str
    version: str
    signatureVerified: bool
    permissions: tuple[str, ...]
    deploymentState: str
    updatePolicy: str
    removalPolicy: str
    supportOwner: str
    updateRing: str | None
    broadSystemAccess: bool
    label: str | None
    managedConfiguration: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "organisationId": self.organisationId,
            "packageId": self.packageId,
            "source": self.source,
            "packageFormat": self.packageFormat,
            "publisher": self.publisher,
            "version": self.version,
            "signatureVerified": self.signatureVerified,
            "permissions": list(self.permissions),
            "deploymentState": self.deploymentState,
            "updatePolicy": self.updatePolicy,
            "removalPolicy": self.removalPolicy,
            "supportOwner": self.supportOwner,
            "updateRing": self.updateRing,
            "broadSystemAccess": self.broadSystemAccess,
            "label": self.label,
            "managedConfiguration": dict(self.managedConfiguration) if self.managedConfiguration else None,
        }


def _validate_permissions(permissions: Any, package_format: str) -> tuple[str, ...]:
    if not isinstance(permissions, list):
        raise CatalogueError("permissions must be a list")
    values = []
    for item in permissions:
        if not isinstance(item, str) or not item:
            raise CatalogueError("permissions entries must be non-empty strings")
        values.append(item)
    if package_format == "flatpak":
        unsupported = sorted(set(values) - FLATPAK_PERMISSIONS)
        if unsupported:
            raise CatalogueError(
                "flatpak entry declares permissions the sandbox cannot express: " + ", ".join(unsupported)
            )
    if package_format in BROAD_ACCESS_FORMATS and values:
        raise CatalogueError(
            "a native package cannot declare a bounded permission set; its access is broad by construction "
            "and must be represented by the broad-access label instead"
        )
    return tuple(dict.fromkeys(values))


def _validate_managed_configuration(configuration: Any) -> dict[str, Any] | None:
    if configuration is None:
        return None
    if not isinstance(configuration, Mapping):
        raise CatalogueError("managedConfiguration must be an object")
    forbidden = sorted(
        str(key) for key in configuration
        if str(key).replace("_", "").replace("-", "").casefold()
        in {"password", "passphrase", "token", "apikey", "secret", "privatekey", "credential", "credentials"}
    )
    if forbidden:
        raise CatalogueError(
            "managedConfiguration must not contain credentials: " + ", ".join(forbidden)
        )
    return dict(configuration)


def parse_entry(record: Mapping[str, Any]) -> CatalogueEntry:
    """Validate one organisation catalogue entry."""
    if not isinstance(record, Mapping):
        raise CatalogueError("entry must be a mapping")

    allowed = {
        "schemaVersion", "organisationId", "packageId", "source", "packageFormat", "publisher",
        "version", "signatureVerified", "permissions", "deploymentState", "updatePolicy",
        "removalPolicy", "supportOwner", "updateRing", "managedConfiguration",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise CatalogueError("unknown catalogue fields: " + ", ".join(unexpected))
    missing = sorted(allowed - {"updateRing", "managedConfiguration"} - set(record))
    if missing:
        raise CatalogueError("missing catalogue fields: " + ", ".join(missing))

    if record["schemaVersion"] != SCHEMA_VERSION:
        raise CatalogueError("unsupported catalogue schemaVersion")

    organisation_id = record["organisationId"]
    if not isinstance(organisation_id, str) or not _ORGANISATION_ID.match(organisation_id):
        raise CatalogueError("organisationId must match org-<slug>")

    package_format = record["packageFormat"]
    if package_format not in PACKAGE_FORMATS:
        raise CatalogueError(f"packageFormat {package_format!r} is not supported")

    package_id = record["packageId"]
    if not isinstance(package_id, str) or not _PACKAGE_ID.match(package_id):
        raise CatalogueError("packageId is malformed")
    if package_format == "flatpak" and not _FLATPAK_ID.match(package_id):
        raise CatalogueError("a flatpak packageId must be a reverse-DNS application id")

    source = record["source"]
    if source not in SOURCES:
        raise CatalogueError(f"source {source!r} is not a recognised catalogue source")

    publisher = record["publisher"]
    if not isinstance(publisher, str) or not publisher:
        raise CatalogueError("publisher must be a non-empty string")

    version = record["version"]
    if not isinstance(version, str) or not _VERSION.match(version):
        raise CatalogueError("version is malformed")

    if record["signatureVerified"] is not True:
        raise CatalogueError(
            f"{package_id} has no verified signature; unsigned packages are refused at the trusted "
            "catalogue interface regardless of source"
        )

    deployment_state = record["deploymentState"]
    if deployment_state not in DEPLOYMENT_STATES:
        raise CatalogueError(f"deploymentState {deployment_state!r} is not recognised")

    update_policy = record["updatePolicy"]
    if update_policy not in UPDATE_POLICIES:
        raise CatalogueError(f"updatePolicy {update_policy!r} is not recognised")

    removal_policy = record["removalPolicy"]
    if removal_policy not in REMOVAL_POLICIES:
        raise CatalogueError(f"removalPolicy {removal_policy!r} is not recognised")

    support_owner = record["supportOwner"]
    if not isinstance(support_owner, str) or not support_owner:
        raise CatalogueError("supportOwner must name who supports this application")

    update_ring = record.get("updateRing")
    if update_ring is not None:
        from enterprise.fleet import UPDATE_RINGS

        if update_ring not in UPDATE_RINGS:
            raise CatalogueError(f"updateRing {update_ring!r} is not a recognised ring")
    if update_policy == "ring-managed" and update_ring is None:
        raise CatalogueError("a ring-managed application must name its update ring")

    permissions = _validate_permissions(record["permissions"], package_format)
    managed_configuration = _validate_managed_configuration(record.get("managedConfiguration"))

    if deployment_state == "required" and removal_policy == "user-removable":
        raise CatalogueError("a required application cannot also be user-removable")
    if deployment_state == "blocked" and update_policy != "pinned":
        raise CatalogueError("a blocked application must have updatePolicy pinned")

    broad_access = package_format in BROAD_ACCESS_FORMATS
    return CatalogueEntry(
        organisationId=organisation_id,
        packageId=package_id,
        source=source,
        packageFormat=package_format,
        publisher=publisher,
        version=version,
        signatureVerified=True,
        permissions=permissions,
        deploymentState=deployment_state,
        updatePolicy=update_policy,
        removalPolicy=removal_policy,
        supportOwner=support_owner,
        updateRing=update_ring,
        broadSystemAccess=broad_access,
        label=BROAD_ACCESS_LABEL if broad_access else None,
        managedConfiguration=managed_configuration,
    )


def resolve_deployment(entries: Mapping[str, str]) -> dict[str, str]:
    """Resolve required/blocked conflicts deterministically.

    ``blocked`` always wins over ``required``. An organisation that both requires
    and blocks an application has a policy error, and the safe interpretation is
    not to install it.
    """
    resolved: dict[str, str] = {}
    for package_id, state in entries.items():
        if state not in DEPLOYMENT_STATES:
            raise CatalogueError(f"unknown deployment state {state!r} for {package_id}")
        current = resolved.get(package_id)
        if current is None:
            resolved[package_id] = state
            continue
        if "blocked" in {current, state}:
            resolved[package_id] = "blocked"
        elif "deprecated" in {current, state}:
            resolved[package_id] = "deprecated"
        elif "required" in {current, state}:
            resolved[package_id] = "required"
        else:
            resolved[package_id] = "optional-approved"
    return resolved

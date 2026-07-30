# SPDX-License-Identifier: Apache-2.0
"""Multi-tenant isolation for the optional fleet service.

The dangerous failure in a multi-tenant control plane is not a missing check but
a *default* that allows cross-tenant reads when a filter is forgotten. This module
therefore makes the tenant scope a required argument everywhere and refuses
unscoped access rather than treating absence as "all tenants".

``evaluate_isolation`` exists so the required controls can be asserted as
evidence rather than claimed in prose, in the same shape as
``operations/modes.py``'s ``MODE_REQUIREMENTS``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1

#: Resource families that must be tenant-scoped. Every one has been the subject of
#: a cross-tenant bug in some deployed management product.
TENANT_SCOPED_RESOURCES = (
    "device",
    "device-group",
    "policy",
    "update-ring",
    "application-catalogue-entry",
    "compliance-status",
    "audit-entry",
    "enrolment-token",
    "administrator",
    "backup",
    "export",
)

#: Controls a multi-tenant deployment must implement. Evidence is required for
#: each; an absent key is treated as missing evidence, never as a pass.
ISOLATION_REQUIREMENTS = (
    "organisationScopedIdentities",
    "organisationScopedStorage",
    "organisationScopedEncryptionKeys",
    "strictApiAuthorisation",
    "auditIsolation",
    "rateLimits",
    "exportBoundaries",
    "backupIsolation",
)

_ORGANISATION_ID = re.compile(r"^org-[a-z0-9][a-z0-9-]{1,62}$")


class TenancyError(ValueError):
    """Raised when a cross-tenant access or an unscoped query is attempted."""


def assert_organisation_id(value: Any, *, field: str = "organisationId") -> str:
    """Validate an organisation identifier, refusing wildcards and blanks."""
    if not isinstance(value, str) or not value:
        raise TenancyError(f"{field} is required; unscoped access is refused")
    if value in {"*", "all", "any"}:
        raise TenancyError(f"{field} must name one organisation; wildcard tenant scope is refused")
    if not _ORGANISATION_ID.match(value):
        raise TenancyError(f"{field} must match org-<slug>")
    return value


def assert_same_tenant(
    *,
    actorOrganisationId: Any,
    resourceOrganisationId: Any,
    resourceKind: str,
    resourceId: str | None = None,
) -> None:
    """Refuse any access where the actor and resource organisations differ."""
    if resourceKind not in TENANT_SCOPED_RESOURCES:
        raise TenancyError(
            f"unknown tenant-scoped resource kind {resourceKind!r}; "
            "every resource family must declare its scoping"
        )
    actor = assert_organisation_id(actorOrganisationId, field="actorOrganisationId")
    resource = assert_organisation_id(resourceOrganisationId, field="resourceOrganisationId")
    if actor != resource:
        target = f" {resourceId!r}" if resourceId else ""
        raise TenancyError(
            f"cross-organisation access refused: {actor} attempted to reach {resourceKind}{target} "
            f"owned by {resource}"
        )


def scoped_filter(organisation_id: Any, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a query filter that always carries the tenant scope.

    The organisation scope cannot be overridden by a caller-supplied filter; an
    attempt to do so is a refusal rather than a silent override.
    """
    organisation = assert_organisation_id(organisation_id)
    result: dict[str, Any] = {}
    if filters:
        if not isinstance(filters, Mapping):
            raise TenancyError("filters must be a mapping")
        if "organisationId" in filters and filters["organisationId"] != organisation:
            raise TenancyError(
                "a query filter may not override the tenant scope; "
                f"scope is {organisation} but the filter requested {filters['organisationId']!r}"
            )
        result.update({key: value for key, value in filters.items() if key != "organisationId"})
    result["organisationId"] = organisation
    return result


def filter_rows(organisation_id: Any, rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return only rows belonging to the given organisation.

    A row without an ``organisationId`` is a defect, not an unscoped row, so it is
    refused rather than dropped silently.
    """
    organisation = assert_organisation_id(organisation_id)
    result: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TenancyError(f"row {index} is not a mapping")
        owner = row.get("organisationId")
        if owner is None:
            raise TenancyError(f"row {index} has no organisationId; unscoped records are refused")
        assert_organisation_id(owner, field=f"rows[{index}].organisationId")
        if owner == organisation:
            result.append(row)
    return result


@dataclass(frozen=True)
class IsolationVerdict:
    organisationId: str | None
    isolated: bool
    missingEvidence: tuple[str, ...] = ()
    failedControls: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "organisationId": self.organisationId,
            "isolated": self.isolated,
            "missingEvidence": list(self.missingEvidence),
            "failedControls": list(self.failedControls),
        }


def evaluate_isolation(
    evidence: Mapping[str, Any],
    *,
    organisation_id: str | None = None,
    required: Sequence[str] | None = None,
) -> IsolationVerdict:
    """Evaluate multi-tenant isolation evidence.

    Mirrors ``operations/modes.py``: a missing key is missing evidence, a false
    value is a failed control, and only an all-true, all-present result isolates.
    """
    if not isinstance(evidence, Mapping):
        raise TenancyError("evidence must be a mapping")
    requirements = tuple(required) if required is not None else ISOLATION_REQUIREMENTS
    unknown = sorted(set(evidence) - set(ISOLATION_REQUIREMENTS))
    if unknown:
        raise TenancyError("unknown isolation controls: " + ", ".join(unknown))

    missing = [name for name in requirements if name not in evidence]
    failed = [name for name in requirements if evidence.get(name) is False]
    for name in requirements:
        value = evidence.get(name)
        if name in evidence and not isinstance(value, bool):
            raise TenancyError(f"isolation control {name} must be a boolean")

    return IsolationVerdict(
        organisationId=organisation_id,
        isolated=not missing and not failed,
        missingEvidence=tuple(missing),
        failedControls=tuple(failed),
    )

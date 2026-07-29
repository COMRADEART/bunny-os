"""Remote administration boundary and destructive-operation gating.

Two separate concerns live here because they fail differently.

*Boundary*: the set of remote operations is closed. A request naming anything
outside it is refused by name, and shell-shaped requests are refused with a
specific message so the refusal is visible in an audit trail rather than looking
like a typo.

*Authorisation*: destructive operations carry preconditions that scale with
ownership. Removing organisation data from an organisation-owned laptop is
routine; fully wiping a personally owned laptop is not, and requires prior
policy, strong authorisation, an explicit scope, audit evidence, and — where
policy says so — confirmation at the device.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from enterprise.enrolment import ENROLMENT_MODES, ORGANISATION_OWNED_MODES

SCHEMA_VERSION = 1

AUTHORISATION_STRENGTHS = ("single-factor", "multi-factor", "multi-factor-with-second-administrator")
STRONG_AUTHORISATIONS = frozenset({"multi-factor", "multi-factor-with-second-administrator"})

_CORRELATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class RemoteOperationError(ValueError):
    """Raised when a remote request is outside the boundary or under-authorised."""


@dataclass(frozen=True)
class RemoteOperation:
    name: str
    description: str
    destructive: bool = False
    requiresOrganisationOwned: bool = False
    requiresStrongAuthorisation: bool = False
    requiresDeviceConfirmationWhenPersonal: bool = False
    requiresPriorPolicy: bool = False
    protectsRecovery: bool = True


#: The complete remote administration surface. There is no entry that accepts a
#: command, argv, script, or arbitrary path, and there is no shell operation.
REMOTE_OPERATIONS: tuple[RemoteOperation, ...] = (
    RemoteOperation("update.check.request", "Ask the device to check for updates"),
    RemoteOperation("update.schedule", "Schedule an already-approved, signed update"),
    RemoteOperation("device.restart.request", "Ask the device to restart"),
    RemoteOperation("device.lock.request", "Ask the device to lock the screen"),
    RemoteOperation("enrolment.certificate.revoke", "Revoke the device enrolment certificate"),
    RemoteOperation("applications.organisation.disable", "Disable applications the organisation deployed"),
    RemoteOperation("management.certificate.rotate", "Rotate the device-management certificate"),
    RemoteOperation("diagnostics.status.request", "Request a redacted diagnostic status summary"),
    RemoteOperation("recovery.schedule", "Schedule the local recovery environment"),
    RemoteOperation(
        "organisation.data.remove",
        "Remove organisation data and profiles",
        destructive=True,
        requiresPriorPolicy=True,
    ),
    RemoteOperation(
        "organisation.applications.remove",
        "Uninstall organisation-deployed applications",
        destructive=True,
    ),
    RemoteOperation(
        "organisation.credentials.revoke",
        "Invalidate organisation credentials held on the device",
        destructive=True,
    ),
    RemoteOperation(
        "device.factory-reset",
        "Fully reset an organisation-owned device",
        destructive=True,
        requiresOrganisationOwned=True,
        requiresStrongAuthorisation=True,
        requiresPriorPolicy=True,
    ),
    RemoteOperation(
        "device.cryptographic-erase",
        "Destroy the encryption keys so stored data becomes unrecoverable",
        destructive=True,
        requiresOrganisationOwned=True,
        requiresStrongAuthorisation=True,
        requiresPriorPolicy=True,
    ),
)

_OPERATIONS_BY_NAME = {operation.name: operation for operation in REMOTE_OPERATIONS}

#: The five wipe operations, kept separate so an administrator cannot reach for
#: the largest hammer when they meant the smallest.
WIPE_OPERATIONS = (
    "organisation.data.remove",
    "organisation.applications.remove",
    "organisation.credentials.revoke",
    "device.factory-reset",
    "device.cryptographic-erase",
)

#: Operations that destroy user data as well as organisation data.
FULL_DESTRUCTION_OPERATIONS = frozenset({"device.factory-reset", "device.cryptographic-erase"})

_SHELL_SHAPED = re.compile(
    r"(?i)\b(shell|exec|command|run|script|bash|sh|powershell|cmd|ssh|python|eval|system)\b"
)


@dataclass(frozen=True)
class RemoteDecision:
    operation: str
    permitted: bool
    refusals: tuple[str, ...] = ()
    requiresDeviceConfirmation: bool = False
    dataLossConsequences: tuple[str, ...] = ()
    recoveryPreserved: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "permitted": self.permitted,
            "refusals": list(self.refusals),
            "requiresDeviceConfirmation": self.requiresDeviceConfirmation,
            "dataLossConsequences": list(self.dataLossConsequences),
            "recoveryPreserved": self.recoveryPreserved,
        }


def assert_within_boundary(operation: str) -> RemoteOperation:
    """Return the operation spec, or refuse with a boundary-specific message."""
    known = _OPERATIONS_BY_NAME.get(operation)
    if known is not None:
        return known
    if _SHELL_SHAPED.search(operation):
        raise RemoteOperationError(
            f"remote operation {operation!r} is refused: Bunny OS provides no generic remote shell "
            "or command-execution operation. Any advanced remote execution capability must be "
            "separately designed, strongly authenticated, disabled by default, and outside the "
            "stable consumer profile."
        )
    raise RemoteOperationError(
        f"unknown remote operation {operation!r}; the boundary is closed and permits only: "
        + ", ".join(sorted(_OPERATIONS_BY_NAME))
    )


def authorize(request: Mapping[str, Any]) -> RemoteDecision:
    """Decide whether one remote administration request may proceed."""
    if not isinstance(request, Mapping):
        raise RemoteOperationError("request must be a mapping")

    allowed = {
        "schemaVersion", "operation", "enrolmentMode", "authorisationStrength", "priorPolicyDeclared",
        "scope", "auditCorrelationId", "deviceSideConfirmation", "administrator", "policyRequiresDeviceConfirmation",
    }
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        raise RemoteOperationError("unknown request fields: " + ", ".join(unexpected))
    if request.get("schemaVersion") != SCHEMA_VERSION:
        raise RemoteOperationError("unsupported request schemaVersion")

    operation_name = request.get("operation")
    if not isinstance(operation_name, str):
        raise RemoteOperationError("operation must be a string")
    operation = assert_within_boundary(operation_name)

    mode = request.get("enrolmentMode")
    if mode not in ENROLMENT_MODES:
        raise RemoteOperationError(f"enrolmentMode {mode!r} is not a recognised enrolment mode")

    strength = request.get("authorisationStrength")
    if strength not in AUTHORISATION_STRENGTHS:
        raise RemoteOperationError(f"authorisationStrength {strength!r} is not recognised")

    administrator = request.get("administrator")
    if not isinstance(administrator, str) or not administrator:
        raise RemoteOperationError("administrator must identify the accountable operator")

    organisation_owned = mode in ORGANISATION_OWNED_MODES
    refusals: list[str] = []

    if operation.requiresOrganisationOwned and not organisation_owned:
        refusals.append(
            f"{operation.name} is permitted only on organisation-owned devices; this device is enrolled as {mode}"
        )

    if operation.requiresStrongAuthorisation and strength not in STRONG_AUTHORISATIONS:
        refusals.append(
            f"{operation.name} requires multi-factor administrator authorisation; got {strength}"
        )

    if operation.requiresPriorPolicy and request.get("priorPolicyDeclared") is not True:
        refusals.append(
            f"{operation.name} requires a clear prior policy disclosed at enrolment; none was declared"
        )

    scope = request.get("scope")
    if operation.destructive:
        if not isinstance(scope, list) or not scope:
            refusals.append(f"{operation.name} requires an explicit non-empty scope")
        elif any(not isinstance(item, str) or not item for item in scope):
            refusals.append(f"{operation.name} scope entries must be non-empty strings")

        correlation = request.get("auditCorrelationId")
        if not isinstance(correlation, str) or not _CORRELATION_ID.match(correlation):
            refusals.append(
                f"{operation.name} requires audit evidence: a UUID correlation id must be supplied before execution"
            )

    device_confirmation_required = False
    if operation.name in FULL_DESTRUCTION_OPERATIONS and not organisation_owned:
        refusals.append(
            f"{operation.name} on a {mode} device is refused; a personally owned device is never fully wiped remotely"
        )
    if request.get("policyRequiresDeviceConfirmation") is True:
        device_confirmation_required = True
        if request.get("deviceSideConfirmation") is not True:
            refusals.append(
                f"{operation.name} requires confirmation at the device and none was recorded"
            )

    consequences: tuple[str, ...] = ()
    if operation.name == "device.factory-reset":
        consequences = (
            "All local user accounts, files, and settings are removed.",
            "Local Bunny memories, workspaces, and checkpoints are removed and are not recoverable from the organisation.",
            "Locally stored recovery keys are destroyed; encrypted data without an external key copy becomes unrecoverable.",
            "The recovery environment and its verified image are preserved so the device can be reinstalled.",
        )
    elif operation.name == "device.cryptographic-erase":
        consequences = (
            "Encryption keys are destroyed, making all stored user data permanently unrecoverable.",
            "This operation is not reversible and no backup is created by it.",
            "The recovery environment and its verified image are preserved so the device can be reinstalled.",
        )
    elif operation.name == "organisation.data.remove":
        consequences = (
            "Organisation profiles, managed configuration, and organisation credentials are removed.",
            "Personal files, personal accounts, and private Bunny memories are not touched.",
        )

    return RemoteDecision(
        operation=operation.name,
        permitted=not refusals,
        refusals=tuple(refusals),
        requiresDeviceConfirmation=device_confirmation_required,
        dataLossConsequences=consequences,
        recoveryPreserved=operation.protectsRecovery,
    )


def describe_operations() -> list[dict[str, Any]]:
    """Return the remote boundary for disclosure at enrolment and in the console."""
    return [
        {
            "operation": item.name,
            "description": item.description,
            "destructive": item.destructive,
            "organisationOwnedOnly": item.requiresOrganisationOwned,
            "requiresStrongAuthorisation": item.requiresStrongAuthorisation,
            "requiresPriorPolicy": item.requiresPriorPolicy,
        }
        for item in REMOTE_OPERATIONS
    ]

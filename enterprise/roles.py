"""Administrative roles, console views, and enterprise authentication.

Three rules shape this module:

* No role is unrestricted for routine work. ``organisation-owner`` exists, but it
  is break-glass: it must re-authenticate for every destructive action and the
  console is expected to warn when it is used for ordinary administration.
* Destructive actions require step-up authentication. A password-equivalent
  single factor is never sufficient.
* Bunny OS does not implement its own password database. Authentication is
  delegated to a mature protocol or to a hardware-backed credential; a
  ``custom-password`` method is refused by name.

The console itself is a separate deployment with its own trust boundary and lives
outside this repository. What is defined here is the authorisation model it must
implement, so the model can be tested without the console existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from enterprise.remote import REMOTE_OPERATIONS, RemoteOperationError

SCHEMA_VERSION = 1

#: Console views. ``user-content`` is deliberately absent: there is no view that
#: renders a user's files, prompts, memories, or history.
CONSOLE_VIEWS = (
    "organisations",
    "devices",
    "groups",
    "policies",
    "update-rings",
    "applications",
    "security-status",
    "recovery-status",
    "audit",
    "support",
)

#: Views a console must never offer, refused by name so the intent is reviewable.
PROHIBITED_CONSOLE_VIEWS = frozenset({
    "user-files", "user-content", "prompts", "conversations", "memories",
    "browser-history", "terminal-history", "screen-view", "remote-desktop",
    "live-screen", "keystrokes", "file-browser", "remote-shell",
})

ROLES = (
    "organisation-owner",
    "security-administrator",
    "device-administrator",
    "application-administrator",
    "help-desk-operator",
    "auditor",
    "read-only-analyst",
)

#: Authentication methods Bunny OS supports for organisation administrators.
AUTHENTICATION_METHODS = (
    "local-administrator",
    "oidc",
    "saml",
    "passkey",
    "hardware-security-key",
    "recovery-code",
)

#: Methods that satisfy a step-up requirement for destructive actions.
STRONG_AUTHENTICATION_METHODS = frozenset({"passkey", "hardware-security-key"})

#: Refused by name. A bespoke password system is not built when a mature identity
#: protocol is available.
PROHIBITED_AUTHENTICATION_METHODS = frozenset({
    "custom-password", "custom-password-database", "shared-secret", "shared-password",
    "basic-auth", "api-key-only", "plaintext-password",
})

_DESTRUCTIVE = frozenset(item.name for item in REMOTE_OPERATIONS if item.destructive)
_ALL_OPERATIONS = frozenset(item.name for item in REMOTE_OPERATIONS)


@dataclass(frozen=True)
class Role:
    name: str
    description: str
    views: frozenset[str]
    operations: frozenset[str]
    breakGlass: bool = False
    mayReadAudit: bool = False
    mayExportAudit: bool = False


_ROLE_DEFINITIONS: tuple[Role, ...] = (
    Role(
        "organisation-owner",
        "Break-glass owner. Full authority, intended for onboarding and emergencies rather than routine work.",
        views=frozenset(CONSOLE_VIEWS),
        operations=_ALL_OPERATIONS,
        breakGlass=True,
        mayReadAudit=True,
        mayExportAudit=True,
    ),
    Role(
        "security-administrator",
        "Manages security posture, advisories, certificate revocation, and destructive recovery actions.",
        views=frozenset({"devices", "groups", "policies", "security-status", "recovery-status", "audit"}),
        operations=frozenset({
            "enrolment.certificate.revoke",
            "management.certificate.rotate",
            "organisation.credentials.revoke",
            "organisation.data.remove",
            "device.factory-reset",
            "device.cryptographic-erase",
            "recovery.schedule",
            "device.lock.request",
            "diagnostics.status.request",
        }),
        mayReadAudit=True,
        mayExportAudit=True,
    ),
    Role(
        "device-administrator",
        "Manages devices, groups, and update rings. Cannot erase devices or revoke credentials.",
        views=frozenset({"devices", "groups", "policies", "update-rings", "recovery-status"}),
        operations=frozenset({
            "update.check.request",
            "update.schedule",
            "device.restart.request",
            "device.lock.request",
            "recovery.schedule",
            "diagnostics.status.request",
        }),
    ),
    Role(
        "application-administrator",
        "Manages the organisation application catalogue and deployments.",
        views=frozenset({"applications", "groups", "devices"}),
        operations=frozenset({"applications.organisation.disable", "organisation.applications.remove"}),
    ),
    Role(
        "help-desk-operator",
        "Assists users with non-destructive actions only.",
        views=frozenset({"devices", "support", "recovery-status"}),
        operations=frozenset({
            "update.check.request",
            "device.restart.request",
            "device.lock.request",
            "diagnostics.status.request",
        }),
    ),
    Role(
        "auditor",
        "Reads and exports audit records. Performs no device operations.",
        views=frozenset({"audit", "organisations", "devices", "policies"}),
        operations=frozenset(),
        mayReadAudit=True,
        mayExportAudit=True,
    ),
    Role(
        "read-only-analyst",
        "Reads operational status. Performs no device operations and cannot export audit records.",
        views=frozenset({"devices", "groups", "policies", "update-rings", "security-status", "recovery-status"}),
        operations=frozenset(),
        mayReadAudit=True,
    ),
)

_ROLES_BY_NAME = {role.name: role for role in _ROLE_DEFINITIONS}


class RoleError(ValueError):
    """Raised when a role, view, or authentication method is invalid."""


def assert_view_permitted(view: str) -> None:
    """Refuse a console view that would expose user content."""
    folded = view.replace("_", "-").casefold()
    if folded in PROHIBITED_CONSOLE_VIEWS:
        raise RoleError(
            f"console view {view!r} is refused: the enterprise console never renders user content, "
            "screens, keystrokes, or a remote shell"
        )
    if folded not in CONSOLE_VIEWS:
        raise RoleError(f"unknown console view {view!r}")


def assert_authentication_method(method: str) -> None:
    """Refuse a bespoke or weak authentication method."""
    folded = method.replace("_", "-").casefold()
    if folded in PROHIBITED_AUTHENTICATION_METHODS:
        raise RoleError(
            f"authentication method {method!r} is refused: Bunny OS does not implement a custom "
            "password-authentication system when a mature identity protocol can be used"
        )
    if folded not in AUTHENTICATION_METHODS:
        raise RoleError(f"unknown authentication method {method!r}")


@dataclass(frozen=True)
class AccessDecision:
    role: str
    action: str
    permitted: bool
    refusals: tuple[str, ...] = ()
    stepUpRequired: bool = False
    breakGlassWarning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "action": self.action,
            "permitted": self.permitted,
            "refusals": list(self.refusals),
            "stepUpRequired": self.stepUpRequired,
            "breakGlassWarning": self.breakGlassWarning,
        }


def authorize_operation(request: Mapping[str, Any]) -> AccessDecision:
    """Decide whether a role may perform a remote operation with a given credential."""
    if not isinstance(request, Mapping):
        raise RoleError("request must be a mapping")

    allowed = {"role", "operation", "authenticationMethod", "stepUpSatisfied"}
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        raise RoleError("unknown request fields: " + ", ".join(unexpected))

    role_name = request.get("role")
    role = _ROLES_BY_NAME.get(role_name)
    if role is None:
        raise RoleError(f"unknown role {role_name!r}; roles are {', '.join(ROLES)}")

    operation = request.get("operation")
    if not isinstance(operation, str):
        raise RoleError("operation must be a string")
    if operation not in _ALL_OPERATIONS:
        raise RemoteOperationError(
            f"unknown remote operation {operation!r}; role authorisation only covers the closed remote boundary"
        )

    method = request.get("authenticationMethod")
    if not isinstance(method, str):
        raise RoleError("authenticationMethod must be a string")
    assert_authentication_method(method)

    refusals: list[str] = []
    if operation not in role.operations:
        refusals.append(f"role {role.name} is not permitted to perform {operation}")

    destructive = operation in _DESTRUCTIVE
    step_up_required = destructive or role.breakGlass
    if step_up_required:
        if method not in STRONG_AUTHENTICATION_METHODS:
            refusals.append(
                f"{operation} requires step-up authentication with a passkey or hardware security key; "
                f"{method} is not sufficient"
            )
        elif request.get("stepUpSatisfied") is not True:
            refusals.append(f"{operation} requires a fresh step-up authentication that was not completed")

    warning = None
    if role.breakGlass and not destructive:
        warning = (
            "organisation-owner is a break-glass role. Use a scoped role for routine administration "
            "so that ordinary work does not run with unrestricted authority."
        )

    return AccessDecision(
        role=role.name,
        action=operation,
        permitted=not refusals,
        refusals=tuple(refusals),
        stepUpRequired=step_up_required,
        breakGlassWarning=warning,
    )


def authorize_view(role_name: str, view: str) -> AccessDecision:
    """Decide whether a role may open a console view."""
    role = _ROLES_BY_NAME.get(role_name)
    if role is None:
        raise RoleError(f"unknown role {role_name!r}")
    assert_view_permitted(view)
    permitted = view in role.views
    return AccessDecision(
        role=role.name,
        action=f"view:{view}",
        permitted=permitted,
        refusals=() if permitted else (f"role {role.name} cannot open the {view} view",),
    )


def describe_roles() -> list[dict[str, Any]]:
    """Return the role catalogue for documentation and console display."""
    return [
        {
            "role": role.name,
            "description": role.description,
            "views": sorted(role.views),
            "operations": sorted(role.operations),
            "breakGlass": role.breakGlass,
            "mayReadAudit": role.mayReadAudit,
            "mayExportAudit": role.mayExportAudit,
        }
        for role in _ROLE_DEFINITIONS
    ]

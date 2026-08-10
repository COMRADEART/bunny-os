# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What Settings shows about applications, permissions and activity.

§28 asks for Settings sections; §8 asks that a person be able to inspect
permissions, revoke them, clear temporary data, reset an app, delete its data,
see its storage, see recent security-sensitive activity and uninstall it cleanly.
This module is the *projection* those surfaces read. It performs no action and
holds no authority: every button on the page calls back into
:class:`~capsules.runtime.CapsuleRuntime` or :class:`~trust.gate.TrustGate`, and
this file only says what to draw and what each button will actually do.

Two things it is careful about, because both are ways a settings page lies.

**A permission that is not enforced is labelled, everywhere it appears.** The
category table records the mechanism and whether this build applies it; a page
that showed a tidy list of toggles without that distinction would tell somebody
their microphone is blocked when it is only recorded. Every row carries
``enforced`` and the section carries a summary count.

**Revocation says when it takes effect.** ``immediate`` and ``next-launch`` are
different promises and the confirmation sentence differs. Telling somebody a
folder permission is gone while the running application still has the mount is
the kind of small lie that costs all the trust the rest of this work is for.

The activity view is built from the audit records, newest first, and never from a
second structure kept alongside — a projection maintained in parallel with the
log is a second account of what happened, and the two eventually disagree about
whether a camera was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from capsules.layout import CLEARABLE, DELETABLE, RESETTABLE
from capsules.runtime import Capsule, CapsuleRuntime
from catalog.registry import CatalogRegistry
from trust.audit import ActivityEntry, TrustAudit
from trust.categories import CATEGORIES, descriptor
from trust.decision import Grant
from trust.explain import revoke_sentence

__all__ = [
    "MAINTENANCE_ACTIONS",
    "SETTINGS_SECTIONS",
    "ApplicationSettings",
    "PermissionRow",
    "application_settings",
    "capsule_overview",
    "maintenance_actions",
]

#: The sections §28 names, in the order Settings shows them. Listed here so the
#: page and the tests agree on what exists; a section with no projection would be
#: a heading with nothing under it.
SETTINGS_SECTIONS = (
    "companion",
    "privacy",
    "security",
    "app-capsules",
    "applications",
    "ai-providers",
    "voice",
    "accessibility",
    "appearance",
    "notifications",
    "storage",
    "network",
    "updates",
    "developer",
)

#: What a person can do to one capsule, with the exact consequence of each. The
#: consequence strings are here rather than in the page so that the GTK settings
#: window, the shell's quick panel and ``bunny-os capsule`` all say the same
#: thing about the same button.
MAINTENANCE_ACTIONS: Mapping[str, Mapping[str, str]] = {
    "clear_temporary": {
        "label": "Clear temporary data",
        "consequence": "Removes caches and temporary files. Your documents and settings stay.",
        "removes": ", ".join(CLEARABLE),
    },
    "reset": {
        "label": "Reset this app",
        "consequence": "Puts the app back to how it was when it was installed. Your documents in it stay.",
        "removes": ", ".join(RESETTABLE),
    },
    "delete_data": {
        "label": "Delete this app's data",
        "consequence": "Removes everything the app holds, including documents you saved inside it.",
        "removes": ", ".join(DELETABLE),
    },
    "uninstall": {
        "label": "Uninstall",
        "consequence": "Removes the app, its protected space and every permission you ever gave it.",
        "removes": "everything",
    },
}


@dataclass(frozen=True)
class PermissionRow:
    """One line in an application's permission list."""

    category: str
    title: str
    risk: str
    #: ``granted``, ``denied``, ``not-asked`` or ``not-declared``.
    standing: str
    scope: str | None
    resource: str | None
    grant_id: str | None
    required: bool
    enforced: bool
    enforcement: str
    revocation: str
    revoke_note: str
    reason: str | None

    def as_record(self) -> Mapping[str, Any]:
        return {
            "category": self.category,
            "title": self.title,
            "risk": self.risk,
            "standing": self.standing,
            "scope": self.scope,
            "resource": self.resource,
            "grantId": self.grant_id,
            "required": self.required,
            "enforced": self.enforced,
            "enforcement": self.enforcement,
            "revocation": self.revocation,
            "revokeNote": self.revoke_note,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ApplicationSettings:
    """Everything the App Capsule page shows for one application."""

    application_id: str
    display_name: str
    state: str
    backend: str
    permissions: tuple[PermissionRow, ...]
    reachable_paths: tuple[str, ...]
    storage: Mapping[str, int]
    unenforced: tuple[str, ...]
    activity: tuple[ActivityEntry, ...]
    actions: Mapping[str, Mapping[str, str]]
    catalog_note: str | None = None

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.application_id,
            "displayName": self.display_name,
            "state": self.state,
            "backend": self.backend,
            "permissions": [dict(row.as_record()) for row in self.permissions],
            "reachablePaths": list(self.reachable_paths),
            "storage": dict(self.storage),
            "unenforced": list(self.unenforced),
            "activity": [dict(entry.as_record()) for entry in self.activity],
            "actions": {key: dict(value) for key, value in self.actions.items()},
            "catalogNote": self.catalog_note,
        }


def maintenance_actions(capsule: Capsule) -> Mapping[str, Mapping[str, str]]:
    """The buttons available for this capsule, with each one's consequence.

    Every action is offered in every state, with an ``available`` flag rather
    than being hidden when the capsule is running: a button that disappears
    teaches nothing, and "stop the app first" is a sentence a person can act on.
    """
    running = capsule.state.state in ("running", "starting", "stopping", "unknown")
    built: dict[str, Mapping[str, str]] = {}
    for key, entry in MAINTENANCE_ACTIONS.items():
        row = dict(entry)
        row["available"] = "false" if running else "true"
        if running:
            row["blockedReason"] = f"Stop {capsule.manifest.display_name} first."
        built[key] = row
    return built


def application_settings(
    runtime: CapsuleRuntime,
    capsule: Capsule,
    *,
    audit: TrustAudit,
    registry: CatalogRegistry | None = None,
    activity_limit: int = 20,
) -> ApplicationSettings:
    """Build the page for one application.

    The reachable-paths list comes from the isolation plan rather than from the
    grant list, because they can differ: a grant whose file has been deleted, or
    whose path turned out to be a credential directory, is refused at plan time
    and must not be shown as something the application can reach.
    """
    grants = {(grant.category, grant.resource.digest): grant for grant in runtime.grants(capsule)}
    declared = capsule.manifest.required_permissions | capsule.manifest.optional_permissions

    rows: list[PermissionRow] = []
    for category in sorted(declared, key=lambda name: tuple(CATEGORIES).index(name)):
        entry = descriptor(category)
        held = [grant for (cat, _digest), grant in grants.items() if cat == category]
        reason = capsule.manifest.permission_reasons.get(category)
        if not held:
            rows.append(
                _row(category, entry, standing="not-asked", grant=None,
                     required=category in capsule.manifest.required_permissions,
                     display_name=capsule.manifest.display_name, reason=reason)
            )
            continue
        for grant in sorted(held, key=lambda g: (g.verdict, g.resource.display, g.grant_id)):
            rows.append(
                _row(
                    category, entry,
                    standing="granted" if grant.verdict == "allow" else "denied",
                    grant=grant,
                    required=category in capsule.manifest.required_permissions,
                    display_name=capsule.manifest.display_name,
                    reason=reason,
                )
            )

    try:
        plan = runtime.build_plan(capsule, allow_unconfined=True)
        reachable = plan.reachable_paths()
        backend = plan.backend
        unenforced = plan.unenforced
    except Exception:  # noqa: BLE001 - a page must render even when a plan cannot be built
        reachable = ()
        backend = capsule.state.backend or capsule.manifest.preferred_backend
        unenforced = capsule.manifest.unenforced_permissions()

    note = None
    if registry is not None:
        catalog_entry = registry.for_application(capsule.identity.application_id)
        if catalog_entry is not None and not catalog_entry.sandbox_compatible:
            note = catalog_entry.sandbox_note

    return ApplicationSettings(
        application_id=capsule.identity.application_id,
        display_name=capsule.manifest.display_name,
        state=capsule.state.state,
        backend=backend,
        permissions=tuple(rows),
        reachable_paths=tuple(reachable),
        storage=capsule.layout.usage(),
        unenforced=tuple(unenforced),
        activity=audit.activity(limit=activity_limit, application_id=capsule.identity.application_id),
        actions=maintenance_actions(capsule),
        catalog_note=note,
    )


def _row(
    category: str,
    entry,  # type: ignore[no-untyped-def]
    *,
    standing: str,
    grant: Grant | None,
    required: bool,
    display_name: str,
    reason: str | None,
) -> PermissionRow:
    return PermissionRow(
        category=category,
        title=entry.title,
        risk=entry.risk,
        standing=standing,
        scope=grant.scope if grant is not None else None,
        resource=grant.resource.display if grant is not None and grant.resource.display else None,
        grant_id=grant.grant_id if grant is not None else None,
        required=required,
        enforced=entry.enforced_by_default,
        enforcement=entry.enforcement,
        revocation=entry.revocation,
        revoke_note=revoke_sentence(category, application_name=display_name),
        reason=reason,
    )


def capsule_overview(
    runtime: CapsuleRuntime,
    *,
    audit: TrustAudit,
    registry: CatalogRegistry | None = None,
) -> Mapping[str, Any]:
    """The App Capsules section: every application, plus what is broken.

    Broken capsules are listed rather than omitted. §23 requires a recovery path
    for a broken capsule, and a page that silently dropped the unreadable ones
    would give a person no way to reach it.
    """
    applications = [
        dict(application_settings(runtime, capsule, audit=audit, registry=registry, activity_limit=5).as_record())
        for capsule in runtime.list()
    ]
    unenforced_total = sorted({category for app in applications for category in app["unenforced"]})
    return {
        "section": "app-capsules",
        "applications": applications,
        "broken": list(runtime.broken()),
        "unenforcedCategories": unenforced_total,
        "unenforcedNote": (
            "Bunny records these permissions but this build does not enforce them: "
            + ", ".join(unenforced_total)
        )
        if unenforced_total
        else "",
        "recentActivity": [dict(entry.as_record()) for entry in audit.activity(limit=25)],
    }

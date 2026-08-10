# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The seventeen things an application may ask for, and what each one costs.

A descriptor here is the single source for every downstream decision about a
permission: which scopes may be offered, whether an install-time consent can
cover it, which Linux mechanism actually enforces it, what sentence a person is
shown, and whether this build enforces it at all. Writing those facts once is
what stops the prompt and the enforcement disagreeing — the failure where
somebody consents to one sentence and a different capability is handed over.

Four rules shaped the table.

**Not every category gets every scope, and the omissions are the design.**
``credentials`` and ``sensitive_system`` offer ``once`` and nothing else: a
standing grant to read the user's keyring is not a preference, it is a decision
nobody should be able to make by accident on a Tuesday and forget. ``camera``,
``microphone`` and ``screen_capture`` stop at ``session``, because "always" on a
sensor means a device that can watch a room forever after one click. Conversely
``gpu``, ``notifications``, ``startup`` and ``background`` have no ``once``:
asking once per frame is not a permission model, it is a denial of service
against the user's attention.

**Every category names the mechanism that enforces it, and says whether this
build actually does.** :attr:`CategoryDescriptor.enforcement` is the Linux
primitive — a portal, a seccomp filter, a bind mount, a cgroup device
controller. :attr:`CategoryDescriptor.enforced_by_default` is whether the
capsule backends in this repository presently apply it. Those are different
statements and collapsing them is how a security model becomes a diagram. Where
the answer is ``False`` the trust prompt says so, in words, to the person being
asked; see :mod:`trust.explain`.

**Risk decides what an install-time consent may cover.** A curated catalogue
entry may declare permissions as required, and §19 asks that users not be
flooded with low-value prompts. So ``low`` and ``medium`` risk categories are
:attr:`catalog_grantable` — one consent at install can cover them — and ``high``
and ``critical`` never are. There is no configuration that changes this; it is a
property of the table, so a catalogue entry cannot promote itself.

**Revocation has two speeds and the difference is user-visible.** A grant
enforced by a portal call stops mattering the moment it is revoked. A grant
enforced by a bind mount or a device node in a running sandbox stops mattering
when the capsule next starts. Claiming the first when only the second is true
would be the more comfortable lie; :attr:`revocation` records which it is and
:mod:`trust.explain` puts it in the revoke confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .errors import TrustSchemaError

__all__ = [
    "CATEGORIES",
    "CATEGORY_IDS",
    "CATALOG_GRANTABLE_RISK",
    "DENY_SCOPE",
    "RESOURCE_KINDS",
    "RISK_LEVELS",
    "SCOPES",
    "CategoryDescriptor",
    "descriptor",
    "is_category",
    "offered_scopes",
    "requires_resource",
    "risk_at_least",
]

#: Allow-scopes, weakest first. ``once`` is a single use; ``session`` lasts until
#: the login session ends or the capsule stops, whichever is first; ``always``
#: persists across reboots until revoked.
SCOPES = ("once", "session", "always")

#: The scope a denial is stored under. A denial is always durable — a person who
#: said no to the microphone should not be asked again on the next launch — but
#: it is revocable from Settings like any other decision.
DENY_SCOPE = "always"

RISK_LEVELS = ("low", "medium", "high", "critical")

_RISK_RANK = {name: index for index, name in enumerate(RISK_LEVELS)}

#: The highest risk an install-time catalogue consent may cover. Above this the
#: question is asked at the moment of use, with the resource in front of the
#: person, and no catalogue entry can opt out.
CATALOG_GRANTABLE_RISK = "medium"

#: The first risk level *above* the grantable ceiling, derived so that inserting
#: a level into :data:`RISK_LEVELS` cannot silently widen what an install-time
#: consent may cover.
_ABOVE_CATALOG_GRANTABLE = RISK_LEVELS[RISK_LEVELS.index(CATALOG_GRANTABLE_RISK) + 1]

#: What kind of thing a permission is *about*. ``none`` means the permission is
#: about the capability itself: there is no second noun in "Bunny Notes wants to
#: show notifications".
RESOURCE_KINDS = ("path", "network", "device", "peer", "none")


def risk_at_least(value: str, floor: str) -> bool:
    """Whether ``value`` is at least as risky as ``floor``."""
    try:
        return _RISK_RANK[value] >= _RISK_RANK[floor]
    except KeyError:
        raise ValueError(f"unknown risk level: {value!r}") from None


@dataclass(frozen=True)
class CategoryDescriptor:
    """Everything true about one permission category.

    ``sentence`` is a template with two named fields, ``{app}`` and
    ``{resource}``. Categories whose ``resource_kind`` is ``none`` use a template
    without ``{resource}``; :func:`trust.explain.headline` checks that rather
    than trusting the caller, because a template rendered with a missing field
    would put the word ``None`` in front of a person.
    """

    category: str
    title: str
    risk: str
    resource_kind: str
    allow_scopes: tuple[str, ...]
    enforcement: str
    enforced_by_default: bool
    revocation: str
    sentence: str
    #: What the capability *is*, in one clause, for the expandable detail. Never
    #: a claim about why this application wants it — that can only come from the
    #: application or its catalogue entry, and is handled in :mod:`trust.explain`.
    capability_note: str

    def __post_init__(self) -> None:  # pragma: no cover - construction-time guard
        if self.risk not in _RISK_RANK:
            raise ValueError(f"unknown risk level: {self.risk!r}")
        if self.resource_kind not in RESOURCE_KINDS:
            raise ValueError(f"unknown resource kind: {self.resource_kind!r}")
        if self.revocation not in ("immediate", "next-launch"):
            raise ValueError(f"unknown revocation speed: {self.revocation!r}")
        if not self.allow_scopes:
            raise ValueError(f"{self.category}: a category with no allow scope can only ever deny")
        for scope in self.allow_scopes:
            if scope not in SCOPES:
                raise ValueError(f"{self.category}: unknown scope {scope!r}")
        has_resource_field = "{resource}" in self.sentence
        if has_resource_field != (self.resource_kind != "none"):
            raise ValueError(f"{self.category}: sentence and resource kind disagree")

    @property
    def catalog_grantable(self) -> bool:
        """Whether one install-time consent may cover this category.

        Derived rather than declared, so that raising a category's risk
        automatically removes it from the install-time set and no second edit can
        be forgotten.
        """
        return not risk_at_least(self.risk, _ABOVE_CATALOG_GRANTABLE)


def _d(**kwargs: object) -> CategoryDescriptor:
    return CategoryDescriptor(**kwargs)  # type: ignore[arg-type]


#: The table. Ordered by how a person would group them rather than
#: alphabetically, because this order is the order Settings shows.
CATEGORIES: Mapping[str, CategoryDescriptor] = {
    descriptor_.category: descriptor_
    for descriptor_ in (
        _d(
            category="files",
            title="Files",
            risk="medium",
            resource_kind="path",
            allow_scopes=("once", "session", "always"),
            enforcement="xdg-desktop-portal document portal; per-file bind mount into the capsule",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants to open {resource}.",
            capability_note="Read and, if you allow it, change that one file.",
        ),
        _d(
            category="folders",
            title="Folders",
            risk="high",
            resource_kind="path",
            allow_scopes=("session", "always"),
            enforcement="xdg-desktop-portal; read-write bind mount of one directory",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants access to everything in {resource}.",
            capability_note="Read, add, change and delete anything in that folder, now and later.",
        ),
        _d(
            category="camera",
            title="Camera",
            risk="high",
            # The portal grants the camera *subsystem*, and PipeWire mediates
            # which node inside it. Modelling this per-device would put a
            # question in front of a person that the enforcement below cannot
            # actually answer differently.
            resource_kind="none",
            allow_scopes=("once", "session"),
            enforcement="xdg-desktop-portal camera; /dev/video* withheld from the capsule device set",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to use your camera.",
            capability_note="See whatever the camera sees, while it is running.",
        ),
        _d(
            category="microphone",
            title="Microphone",
            risk="high",
            resource_kind="none",
            allow_scopes=("once", "session"),
            enforcement="PipeWire capture node permission; no ALSA device in the capsule",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to use your microphone.",
            capability_note="Hear whatever the microphone hears, while it is running.",
        ),
        _d(
            category="screen_capture",
            title="Screen sharing",
            risk="high",
            resource_kind="none",
            allow_scopes=("once", "session"),
            enforcement="xdg-desktop-portal ScreenCast; no Wayland privileged protocol in the capsule",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to see your screen.",
            capability_note="Watch a window or a whole display, including anything you open in front of it.",
        ),
        _d(
            category="clipboard",
            title="Clipboard",
            risk="medium",
            resource_kind="none",
            allow_scopes=("once", "session"),
            enforcement="Wayland data-device mediation; no X11 clipboard bridge in the capsule",
            enforced_by_default=False,
            revocation="immediate",
            sentence="{app} wants to read what you copied.",
            capability_note="Read the last thing you copied, which is often a password.",
        ),
        _d(
            category="notifications",
            title="Notifications",
            risk="low",
            resource_kind="none",
            allow_scopes=("session", "always"),
            enforcement="xdg-desktop-portal Notification",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to show you notifications.",
            capability_note="Put messages on your screen and in the notification list.",
        ),
        _d(
            category="network",
            title="Network",
            risk="medium",
            resource_kind="network",
            allow_scopes=("session", "always"),
            enforcement="network namespace; slirp/pasta with an address allowlist, or no netns at all",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants to connect to {resource}.",
            capability_note="Send and receive data over that network scope.",
        ),
        _d(
            category="bluetooth",
            title="Bluetooth",
            risk="high",
            resource_kind="device",
            allow_scopes=("once", "session"),
            enforcement="BlueZ D-Bus proxy with a filtered interface set; no raw HCI socket",
            enforced_by_default=False,
            revocation="next-launch",
            sentence="{app} wants to use Bluetooth to reach {resource}.",
            capability_note="Discover and talk to nearby Bluetooth devices.",
        ),
        _d(
            category="usb",
            title="USB devices",
            risk="high",
            resource_kind="device",
            allow_scopes=("once", "session"),
            enforcement="udev device allowlist bound into the capsule; default device set is empty",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants to use {resource}.",
            capability_note="Talk directly to that plugged-in device.",
        ),
        _d(
            category="location",
            title="Location",
            risk="high",
            resource_kind="none",
            allow_scopes=("once", "session"),
            enforcement="xdg-desktop-portal Location; GeoClue is not reachable from the capsule",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to know where you are.",
            capability_note="Learn roughly or precisely where this computer is.",
        ),
        _d(
            category="gpu",
            title="Graphics acceleration",
            risk="low",
            resource_kind="none",
            allow_scopes=("session", "always"),
            enforcement="/dev/dri render node bound into the capsule",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants to use the graphics card.",
            capability_note="Draw faster, and use the graphics card for computation.",
        ),
        _d(
            category="background",
            title="Running in the background",
            risk="medium",
            resource_kind="none",
            allow_scopes=("session", "always"),
            enforcement="systemd user scope kept alive after the last window closes",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to keep running after you close it.",
            capability_note="Stay running, and keep using memory and battery, with no window on screen.",
        ),
        _d(
            category="startup",
            title="Starting with the computer",
            risk="medium",
            resource_kind="none",
            allow_scopes=("always",),
            enforcement="autostart entry written by Bunny, never by the application",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to start when you log in.",
            capability_note="Start automatically every time you log in.",
        ),
        _d(
            category="ipc",
            title="Talking to other applications",
            risk="high",
            resource_kind="peer",
            allow_scopes=("once", "session"),
            enforcement="D-Bus proxy with a per-capsule destination allowlist",
            enforced_by_default=True,
            revocation="next-launch",
            sentence="{app} wants to send something to {resource}.",
            capability_note="Hand data to another application, which then has its own copy.",
        ),
        _d(
            category="credentials",
            title="Saved passwords",
            risk="critical",
            resource_kind="peer",
            allow_scopes=("once",),
            enforcement="Secret Service proxy scoped to the capsule's own collection",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to read a saved password for {resource}.",
            capability_note="Read one stored secret. Bunny never shows it to you or writes it to a log.",
        ),
        _d(
            category="sensitive_system",
            title="System changes",
            risk="critical",
            resource_kind="none",
            allow_scopes=("once",),
            enforcement="bunny-system-broker over its unix socket, with Polkit per operation",
            enforced_by_default=True,
            revocation="immediate",
            sentence="{app} wants to make a change to the system.",
            capability_note="Ask Bunny's privileged helper to do one named, audited thing as root.",
        ),
    )
}

CATEGORY_IDS = tuple(CATEGORIES)


def is_category(value: object) -> bool:
    """Whether ``value`` names a category this build implements."""
    return isinstance(value, str) and value in CATEGORIES


def descriptor(category: str) -> CategoryDescriptor:
    """The descriptor for ``category``.

    Raises :class:`~trust.errors.TrustSchemaError` rather than ``KeyError`` so
    that an unknown category arriving from a request travels the same path as
    every other malformed request and lands, deny-by-default, in the audit.
    """
    try:
        return CATEGORIES[category]
    except (KeyError, TypeError):
        raise TrustSchemaError(f"unknown permission category: {category!r}") from None


def requires_resource(category: str) -> bool:
    """Whether a request in ``category`` is meaningless without a resource."""
    return descriptor(category).resource_kind != "none"


def offered_scopes(category: str) -> tuple[str, ...]:
    """The allow-scopes a prompt for ``category`` may show, weakest first."""
    return descriptor(category).allow_scopes

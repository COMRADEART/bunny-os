# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who a capsule is, and why the name can never be a path.

A capsule's identity is derived from the application id and nothing else. That
single fact carries most of the persistence model: *opening the application
reconnects to its existing capsule* is true because the identity is a function of
the application rather than of the launch, the task, or the moment.

The identity is used in three places with three different constraints, and the
design is what satisfies all three at once:

**A directory name.** ``org.example.Photo-Editor`` is a fine application id and
``../../../etc`` is a plausible attack, so the directory component is not the
application id. It is ``<sanitised>.<digest>``: a conservative slug for humans
reading ``ls``, and eight bytes of SHA-256 over the *exact* id for uniqueness.
Two ids that sanitise to the same slug get different digests, so a hostile id
cannot collide with an honest one, and no id can produce a name containing a
separator, a dot-dot, a NUL, or a leading dash.

**A systemd unit and cgroup name.** Same constraints, plus a length bound.

**A D-Bus and portal identity.** These want the application id itself, unmodified,
which is why the id is kept alongside the slug rather than replaced by it.

The digest is over the id as given, before sanitisation, because sanitising first
and hashing after would make the hash a function of the slug and reintroduce the
collision it exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .errors import CapsuleSchemaError

__all__ = [
    "APPLICATION_ID_PATTERN",
    "MAX_APPLICATION_ID_LENGTH",
    "MAX_SLUG_LENGTH",
    "CapsuleIdentity",
    "capsule_identity",
]

#: Reverse-DNS, as Flatpak, D-Bus and desktop entries all use. Restricted to what
#: all three accept: components of alphanumerics, underscores and hyphens,
#: separated by dots, not starting with a digit or a hyphen.
APPLICATION_ID_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+\Z"
)

#: D-Bus caps a well-known name at 255 bytes; a capsule id has to be able to be
#: one, so this is the same bound.
MAX_APPLICATION_ID_LENGTH = 255

#: Leaves room for a ``.<16 hex>`` suffix and a ``bunny-capsule-`` unit prefix
#: inside the 255-byte limit systemd and most filesystems impose on a component.
MAX_SLUG_LENGTH = 64

_UNSAFE = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class CapsuleIdentity:
    """The three names one application has, derived once."""

    application_id: str
    #: The on-disk and unit-name component. Never contains a path separator, a
    #: dot-dot component, or a leading dash.
    slug: str
    #: Sixteen hex characters of SHA-256 over the exact application id.
    digest: str

    @property
    def directory_name(self) -> str:
        return f"{self.slug}.{self.digest}"

    @property
    def unit_name(self) -> str:
        """The transient systemd unit this capsule's processes live in.

        A *service*, which the user manager spawns, and not a scope forked from
        whatever asked for the launch. That was a scope until the launcher
        qualification section measured what happens when the thing asking is the
        Companion: a scope inherits the caller's seccomp filter and mount
        namespace, both Companion units set ``RestrictNamespaces=yes``, and
        bubblewrap's whole mechanism is ``unshare(2)``. Every capsule launch from
        the Companion failed, on every machine.

        The unit still carries the cgroup, so the resource limits in
        :mod:`capsules.manifest` still apply to the whole application including
        anything it forks. What changed is who the parent is — and with it, that
        the capsule's confinement comes from its own declared plan instead of
        being partly inherited from a launcher nobody was measuring.
        """
        return f"bunny-capsule-{self.directory_name}.service"

    @property
    def portal_id(self) -> str:
        """What the portals and D-Bus see: the application id, unmodified."""
        return self.application_id

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.application_id


def _slug(application_id: str) -> str:
    lowered = application_id.lower()
    cleaned = _UNSAFE.sub("-", lowered).strip("-")
    # Collapse runs, which a reverse-DNS id with adjacent separators produces.
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        # Every character was unsafe. The digest still distinguishes it; the slug
        # only has to be a legal, non-empty, non-special component.
        cleaned = "app"
    return cleaned[:MAX_SLUG_LENGTH].strip("-") or "app"


def capsule_identity(application_id: str) -> CapsuleIdentity:
    """Derive the identity for ``application_id``, or refuse it.

    Refuses before deriving. A name that is going to become a directory has to be
    checked against a pattern, not repaired by a sanitiser: a sanitiser that
    accepted ``../../etc`` and returned ``etc`` would have turned an attack into
    a plausible-looking capsule rather than into a refusal.
    """
    if not isinstance(application_id, str):
        raise CapsuleSchemaError("an application id must be a string")
    if len(application_id) > MAX_APPLICATION_ID_LENGTH:
        raise CapsuleSchemaError(f"application id longer than {MAX_APPLICATION_ID_LENGTH} characters")
    if not APPLICATION_ID_PATTERN.match(application_id):
        raise CapsuleSchemaError(f"not a reverse-DNS application id: {application_id!r}")
    digest = hashlib.sha256(application_id.encode("utf-8")).hexdigest()[:16]
    return CapsuleIdentity(application_id=application_id, slug=_slug(application_id), digest=digest)

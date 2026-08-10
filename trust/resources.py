# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a permission is *about*, canonicalised so two spellings cannot differ.

A grant is worthless if the thing granted can be renamed. ``~/Pictures/cat.png``,
``~/Pictures/./cat.png``, ``~/Pictures/../Pictures/cat.png`` and a symlink
pointing at any of them are one file, and a store that treats them as four keys
has both a bypass (grant the harmless spelling, use the dangerous one) and a leak
(revoke one spelling, keep the other). So every resource is reduced to a
canonical form *before* it is stored, compared or displayed, and the canonical
form is the only thing the rest of the layer ever sees.

**Symlinks are resolved before containment is checked, never after.** The check
is on the real path. ``~/Documents/notes.txt`` being a link to ``/etc/shadow`` is
the entire attack; a check on the path as written passes it. Every component is
resolved, including the directories above the last one, which is the variant that
catches a symlinked parent.

**Containment is by path component, not by string prefix.** ``/home/bunny-evil``
starts with ``/home/bunny`` and is not inside it.

**A resource carries a digest and a display string, and the store keys on the
digest.** The display string is short, relative to a named root where possible,
and safe to put on a screen; the identifier is the canonical absolute path and is
what enforcement uses. An audit record keeps the digest and the display, never
the identifier — ``/home/x/divorce/draft.odt`` discloses something to anyone who
reads the log, whether or not the permission was granted.

This module deliberately does not reuse :mod:`companion.desktop.paths`. That one
answers a different question — *may the companion reveal a path the runtime
already holds a reference to* — and refuses whole classes of location, dot
directories in particular, that a user is entirely allowed to pick in a file
chooser. Sharing the code would mean sharing the refusals, and the two sets are
not the same set. What *is* shared is the shape of the check, and both modules
say so.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Mapping

from .categories import RESOURCE_KINDS, descriptor
from .errors import TrustSchemaError

__all__ = [
    "MAX_DISPLAY_LENGTH",
    "MAX_IDENTIFIER_LENGTH",
    "NETWORK_CLASSES",
    "Resource",
    "contains",
    "device_resource",
    "network_covers",
    "network_resource",
    "no_resource",
    "path_resource",
    "peer_resource",
    "real_path",
    "resource_digest",
    "resource_for",
]

#: Long enough for any real path, short enough that a path cannot be used to
#: smuggle a payload into a record. Linux ``PATH_MAX`` is 4096.
MAX_IDENTIFIER_LENGTH = 1024

#: What a person is shown. Anything longer is elided in the middle, keeping the
#: file name, because the end of a path is the part that identifies it.
MAX_DISPLAY_LENGTH = 96

#: §19's network classes, least capable first. The class *is* the resource for a
#: network permission: "may connect to the internet" and "may reach the printer
#: on your LAN" are different questions and must not share a grant.
NETWORK_CLASSES = ("none", "loopback", "local-network", "allowlisted", "internet")

_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:+/-]{0,127}\Z")
_PEER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DOMAIN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z")


def resource_digest(kind: str, identifier: str) -> str:
    """A stable, comparable stand-in for a resource that discloses nothing.

    The kind is mixed in so that a device called ``/dev/video0`` and a path
    called ``/dev/video0`` cannot collide into one grant.
    """
    return hashlib.sha256(f"{kind}\x00{identifier}".encode("utf-8")).hexdigest()[:32]


def real_path(value: str | os.PathLike[str]) -> Path:
    """Every component resolved, symlinks included, without requiring existence.

    Non-strict on purpose: a path that does not exist must reach the *existence*
    check and be refused for that reason, with that message, rather than raising
    here and being reported as a resolution failure.
    """
    return Path(os.path.realpath(os.fspath(value)))


def contains(root: Path, candidate: Path) -> bool:
    """Whether ``candidate`` is ``root`` or sits beneath it, by component.

    Both are expected to be resolved already. Comparing :attr:`~pathlib.PurePath.parts`
    rather than strings is what makes ``/home/bunny-evil`` not inside
    ``/home/bunny``.
    """
    root_parts = root.parts
    candidate_parts = candidate.parts
    return (
        len(candidate_parts) >= len(root_parts)
        and candidate_parts[: len(root_parts)] == root_parts
    )


def _elide(text: str) -> str:
    if len(text) <= MAX_DISPLAY_LENGTH:
        return text
    tail = text[-(MAX_DISPLAY_LENGTH - 4) :]
    return "..." + tail


@dataclass(frozen=True)
class Resource:
    """The noun in a permission question, canonical and safe to display.

    ``identifier`` is what enforcement uses and is never written to an audit
    record. ``display`` is what a person reads. ``digest`` is what the grant
    store keys on, so that two spellings of one file are one grant and a log can
    prove which resource a decision was about without holding it.
    """

    kind: str
    identifier: str
    display: str
    digest: str

    def __post_init__(self) -> None:  # pragma: no cover - construction-time guard
        if self.kind not in RESOURCE_KINDS:
            raise TrustSchemaError(f"unknown resource kind: {self.kind!r}")
        if len(self.identifier) > MAX_IDENTIFIER_LENGTH:
            raise TrustSchemaError(f"resource identifier longer than {MAX_IDENTIFIER_LENGTH} characters")

    def as_record(self) -> Mapping[str, Any]:
        """The audit projection: kind, display and digest, never the identifier."""
        return {"kind": self.kind, "display": self.display, "digest": self.digest}

    def covers(self, other: "Resource") -> bool:
        """Whether a grant on this resource also covers ``other``.

        Only two kinds widen. A *directory* path covers everything beneath it,
        which is what makes "allow this folder" a folder permission rather than a
        promise to ask again for every file in it. A *network class* covers the
        classes it genuinely subsumes — see :func:`network_covers`, which is a
        deliberate lattice rather than the ordering of :data:`NETWORK_CLASSES`,
        because reaching a named domain does not imply reaching the printer on
        the local network and treating the tuple as a total order would say it
        did.

        Everything else is exact. A grant on one camera is not a grant on
        another; a grant on one D-Bus peer is not a grant on its neighbour.
        """
        if self.kind != other.kind:
            return False
        if self.digest == other.digest:
            return True
        if self.kind == "path":
            root = Path(self.identifier)
            # A file cannot contain anything. Checking is_dir() would be a race
            # and would also fail for a directory that has since been deleted, so
            # the widening rule is carried on the resource itself: only a
            # resource built by path_resource(..., directory=True) widens, and
            # such a resource records a trailing marker in its identifier.
            if not self.identifier.endswith(os.sep) and not self.identifier.endswith("/"):
                return False
            return contains(Path(self.identifier.rstrip("/") or "/"), Path(other.identifier.rstrip("/") or "/"))
        if self.kind == "network":
            return network_covers(self.identifier, other.identifier)
        return False


def _split_network(identifier: str) -> tuple[str, frozenset[str]]:
    head, _, tail = identifier.partition(":")
    return head, frozenset(tail.split(",")) if tail else frozenset()


def network_covers(held: str, wanted: str) -> bool:
    """Whether a grant of network class ``held`` subsumes a request for ``wanted``.

    Written as an explicit lattice because the obvious total order is wrong.
    ``internet`` subsumes everything reachable off this machine. ``allowlisted``
    subsumes a smaller allowlist and nothing else outward-facing — in particular
    it does **not** subsume ``local-network``, because a grant to reach
    ``api.example.com`` is not consent to enumerate the devices in somebody's
    house. ``loopback`` and ``none`` are subsumed by everything, since a capsule
    that may reach the world may certainly reach itself.
    """
    held_class, held_domains = _split_network(held)
    wanted_class, wanted_domains = _split_network(wanted)
    if held_class not in NETWORK_CLASSES or wanted_class not in NETWORK_CLASSES:
        return False
    if wanted_class == "none":
        return True
    if held_class == "internet":
        return True
    if wanted_class == "loopback":
        return held_class != "none"
    if held_class == "allowlisted" and wanted_class == "allowlisted":
        return wanted_domains <= held_domains
    if held_class == "local-network" and wanted_class == "local-network":
        return True
    return False


def no_resource() -> Resource:
    """The resource for a category that has none: a real value, not ``None``.

    A sentinel rather than ``None`` because every downstream record wants a
    digest to key on, and ``None`` in a dictionary key position is the shape of
    bug where two different capabilities share one grant.
    """
    return Resource(kind="none", identifier="", display="", digest=resource_digest("none", ""))


def path_resource(
    value: str | os.PathLike[str],
    *,
    directory: bool = False,
    roots: Mapping[str, Path] | None = None,
    must_exist: bool = True,
) -> Resource:
    """Canonicalise a filesystem path into a resource.

    ``directory`` decides whether the resulting grant widens to cover everything
    beneath it. It is a parameter rather than a probe of the filesystem because
    the widening must be a property of *what was consented to*: a person who
    allowed one file must not find the grant has silently become a folder grant
    because the file was later replaced by a directory of the same name.

    ``roots`` maps a display name to a directory — typically the XDG user
    directories — and is used only to shorten the display string. Containment in
    a root is *not* required here: a user may legitimately choose a file anywhere
    through a file chooser, and refusing that would be the trust layer overruling
    the person it exists to serve. What a capsule may reach without a grant is a
    separate question and lives in :mod:`capsules.isolation`.
    """
    if not isinstance(value, (str, os.PathLike)):
        raise TrustSchemaError("a path resource needs a path")
    raw = os.fspath(value)
    if not raw:
        raise TrustSchemaError("a path resource needs a non-empty path")
    if "\x00" in raw:
        raise TrustSchemaError("a path may not contain a null byte")
    if len(raw) > MAX_IDENTIFIER_LENGTH:
        raise TrustSchemaError(f"path longer than {MAX_IDENTIFIER_LENGTH} characters")
    resolved = real_path(os.path.expanduser(raw))
    if not resolved.is_absolute():  # pragma: no cover - realpath always absolutises
        raise TrustSchemaError("a path resource must resolve to an absolute path")
    if must_exist and not os.path.exists(resolved):
        raise TrustSchemaError("that file is not there")
    if must_exist:
        if directory and not os.path.isdir(resolved):
            raise TrustSchemaError("that is not a folder")
        if not directory and not os.path.isfile(resolved):
            # A FIFO opened by an application blocks; a device node does
            # something nobody predicted. Neither is a file a person picks.
            raise TrustSchemaError("that is not an ordinary file")
    identifier = str(resolved)
    if directory and not identifier.endswith(os.sep):
        identifier = identifier + "/"
    return Resource(
        kind="path",
        identifier=identifier,
        display=_display_path(resolved, roots),
        digest=resource_digest("path", identifier),
    )


def _display_path(resolved: Path, roots: Mapping[str, Path] | None) -> str:
    if roots:
        for name, root in sorted(roots.items(), key=lambda item: -len(str(item[1]))):
            root_resolved = real_path(root)
            if contains(root_resolved, resolved):
                relative = resolved.relative_to(root_resolved)
                return _elide(f"{name}/{relative}" if relative.parts else name)
    home = real_path(Path.home()) if os.path.expanduser("~") != "~" else None
    if home is not None and contains(home, resolved):
        relative = resolved.relative_to(home)
        return _elide(f"~/{relative}" if relative.parts else "~")
    return _elide(str(resolved))


def network_resource(value: str, *, allowlist: tuple[str, ...] = ()) -> Resource:
    """A network class, optionally with the domains an ``allowlisted`` class names.

    The allowlist is part of the identifier because "may reach
    ``api.example.com``" and "may reach anything" are not the same permission and
    must not compare equal in the store.
    """
    if value not in NETWORK_CLASSES:
        raise TrustSchemaError(f"unknown network class: {value!r}")
    if value != "allowlisted" and allowlist:
        raise TrustSchemaError("only the allowlisted network class carries domains")
    if value == "allowlisted" and not allowlist:
        raise TrustSchemaError("the allowlisted network class needs at least one domain")
    domains = tuple(sorted({d.lower() for d in allowlist}))
    for domain in domains:
        if not _DOMAIN.match(domain):
            raise TrustSchemaError(f"not a domain name: {domain!r}")
    # The domains are part of the identifier, not merely of the digest: two
    # allowlists must not compare as one grant, and `covers` has to be able to
    # read the set back out of a stored identifier to answer "is this a subset".
    identifier = value if not domains else value + ":" + ",".join(domains)
    display = {
        "none": "nothing on the network",
        "loopback": "only this computer",
        "local-network": "devices on your local network",
        "allowlisted": ", ".join(domains),
        "internet": "the internet",
    }[value]
    return Resource(
        kind="network",
        identifier=identifier,
        display=_elide(display),
        digest=resource_digest("network", identifier),
    )


def device_resource(identifier: str, display: str | None = None) -> Resource:
    """A named device: a camera, a microphone, a USB peripheral, a radio."""
    if not isinstance(identifier, str) or not _DEVICE_ID.match(identifier):
        raise TrustSchemaError(f"not a device identifier: {identifier!r}")
    shown = display if isinstance(display, str) and display else identifier
    return Resource(
        kind="device",
        identifier=identifier,
        display=_elide(shown),
        digest=resource_digest("device", identifier),
    )


def peer_resource(identifier: str, display: str | None = None) -> Resource:
    """Another application, or a named service the capsule wants to talk to."""
    if not isinstance(identifier, str) or not _PEER_ID.match(identifier):
        raise TrustSchemaError(f"not a peer identifier: {identifier!r}")
    shown = display if isinstance(display, str) and display else identifier
    return Resource(
        kind="peer",
        identifier=identifier,
        display=_elide(shown),
        digest=resource_digest("peer", identifier),
    )


def resource_for(category: str, value: Resource | None) -> Resource:
    """Check that ``value`` is the kind of resource ``category`` needs.

    A category whose ``resource_kind`` is ``none`` must be given no resource, and
    is handed the sentinel. Any other category must be given one of exactly the
    right kind: a folder permission carrying a device resource is a malformed
    request, and malformed requests deny.
    """
    kind = descriptor(category).resource_kind
    if kind == "none":
        if value is not None and value.kind != "none":
            raise TrustSchemaError(f"{category} takes no resource")
        return no_resource()
    if value is None:
        raise TrustSchemaError(f"{category} needs a {kind}")
    if value.kind != kind:
        raise TrustSchemaError(f"{category} needs a {kind}, not a {value.kind}")
    return value

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

**A resource carries a digest and two display strings, and the store keys on the
digest.** ``display`` is what a *prompt* shows: relative to one of the user's own
directories where possible, and the whole path where there is no shorter honest
form. ``log_display`` is what a *record* holds, which elides the directory for a
path outside those directories — a log is read by support tooling, a diagnostic
export and whoever holds the disk, and none of them were in front of the prompt.
The identifier, the canonical absolute path enforcement uses, reaches neither.
``/home/x/divorce/draft.odt`` discloses something to anyone who reads the log,
whether or not the permission was granted.

The distinction between the two was added after a Linux qualification run: the
display defaulted to the whole absolute path whenever a caller passed no roots,
and a Windows developer host had hidden it because its temporary directory
happened to sit under the user profile, so the home-relative fallback shortened
it and the guarding test passed for the wrong reason.

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
    "NETWORK_DECLARED_ONLY",
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
    "user_roots",
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

#: The classes that are *declarations* in this build: recorded, disclosed, and
#: mapped onto plain internet access, because nothing here filters by name,
#: subnet or interface. ``none`` is a kernel boundary and ``internet`` is the
#: absence of one; everything between is a promise the build cannot keep yet.
#: Surfaces must speak of these as declarations, never as boundaries.
NETWORK_DECLARED_ONLY = ("loopback", "local-network", "allowlisted")

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
    #: What a *record* may hold, which is not always what a prompt shows.
    #:
    #: The two differ for one case, and the Linux qualification run is what
    #: found it. A path under one of the user's own directories shortens to
    #: ``Documents/report.odt``: that is what the person saw, it names no
    #: directory above the one they chose, and it is harmless in a log. Any
    #: other path — ``/tmp/x``, ``~/divorce/draft.odt``, an external drive —
    #: has no shorter *honest* form for a prompt, because telling somebody an
    #: app wants to open ``passwd`` when the file is ``/etc/passwd`` would be a
    #: worse failure than a long line. So the prompt shows it whole and the
    #: record keeps only the file name.
    #:
    #: A field rather than something derived from ``display``, because deriving
    #: it would mean inferring *which* shortening rule had applied by looking at
    #: the resulting string, and a rule inferred from its own output is a rule
    #: that silently stops applying when the output changes.
    log_display: str = ""

    def __post_init__(self) -> None:  # pragma: no cover - construction-time guard
        if self.kind not in RESOURCE_KINDS:
            raise TrustSchemaError(f"unknown resource kind: {self.kind!r}")
        if len(self.identifier) > MAX_IDENTIFIER_LENGTH:
            raise TrustSchemaError(f"resource identifier longer than {MAX_IDENTIFIER_LENGTH} characters")
        if not self.log_display:
            # Every non-path kind, and any resource rebuilt from a stored record
            # whose display is already the logged form.
            object.__setattr__(self, "log_display", self.display)

    def as_record(self) -> Mapping[str, Any]:
        """The audit projection: kind, log display and digest, never the identifier."""
        return {"kind": self.kind, "display": self.log_display, "digest": self.digest}

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
    display, under_user_directory = _display_path(resolved, roots)
    return Resource(
        kind="path",
        identifier=identifier,
        display=display,
        digest=resource_digest("path", identifier),
        log_display=display if under_user_directory else ".../" + (resolved.name or display),
    )


#: The XDG user directories, by the name a person calls them. One definition,
#: used for three things that must agree: shortening a path for display, deciding
#: where a capsule may export a result (:func:`capsules.exchange.user_destinations`),
#: and deciding whether a path is somewhere a person keeps their own files.
_XDG_USER_DIRECTORIES: Mapping[str, str] = {
    "Documents": "XDG_DOCUMENTS_DIR",
    "Downloads": "XDG_DOWNLOAD_DIR",
    "Pictures": "XDG_PICTURES_DIR",
    "Music": "XDG_MUSIC_DIR",
    "Videos": "XDG_VIDEOS_DIR",
    "Desktop": "XDG_DESKTOP_DIR",
}


def user_roots(home: Path | None = None) -> Mapping[str, Path]:
    """The user's own directories, resolved, by display name.

    The home directory itself is deliberately not one. "Anywhere in your home"
    is not a bound, and home contains every credential directory
    :mod:`capsules.isolation` refuses.

    This is the default for :func:`path_resource`, and that default is the fix
    for a defect the Linux qualification run found: a caller that passed no
    roots got a resource whose ``display`` was the **whole absolute path**, which
    then went on a person's screen and into the audit record. On a Windows
    developer host the temporary directory happened to sit under the user
    profile, so the home-relative fallback shortened it and the test that guards
    this passed for the wrong reason.
    """
    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    found: dict[str, Path] = {}
    for name, variable in sorted(_XDG_USER_DIRECTORIES.items()):
        configured = os.environ.get(variable)
        found[name] = Path(configured) if configured else base / name
    return found


def _display_path(resolved: Path, roots: Mapping[str, Path] | None) -> tuple[str, bool]:
    """The prompt form, and whether it is relative to one of the user's own
    directories.

    The boolean is what decides :attr:`Resource.log_display`. The home-relative
    fallback below is *not* a named root: ``~/divorce/draft.odt`` hides the
    account name and discloses the directory, and the directory is the part this
    module's own docstring gives as the example of what must not reach a log.
    """
    for name, root in sorted((roots or user_roots()).items(), key=lambda item: -len(str(item[1]))):
        root_resolved = real_path(root)
        if contains(root_resolved, resolved):
            relative = resolved.relative_to(root_resolved)
            return _elide(f"{name}/{relative}" if relative.parts else name), True
    home = real_path(Path.home()) if os.path.expanduser("~") != "~" else None
    if home is not None and contains(home, resolved):
        relative = resolved.relative_to(home)
        return _elide(f"~/{relative}" if relative.parts else "~"), False
    return _elide(str(resolved)), False


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

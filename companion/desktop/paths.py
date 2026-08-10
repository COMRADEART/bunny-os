# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which files may be revealed, and why a provider never names one.

§4.9's first requirement is the one that decides the design: *the path must
already exist in canonical task context*. So a provider does not supply a path
at all. It supplies a **reference** — an opaque identifier for a path the
canonical runtime already holds because the user named it, or because an earlier
approved action produced it. The provider can no more invent a path than it can
invent a task id.

That inverts the usual problem. Instead of validating an attacker-controlled
string against a set of rules and hoping the rules are complete, the set of
reachable paths is enumerated in advance by something the provider cannot reach.
The validation below is therefore a second line rather than the only one, and it
is written as if the first had failed:

**Symlinks are resolved before the containment check, never after.** The check
is on the *real* path. ``~/Documents/report.pdf`` being a symlink to
``/etc/shadow`` is the whole attack, and a check that ran on the path as written
would pass it. :func:`os.path.realpath` resolves every component, including the
directories above the last one, which is the variant that catches a symlinked
parent.

**Roots are resolved too.** Comparing a resolved path against an unresolved root
fails open whenever the root itself is a symlink — on a machine where
``/home`` is a link to ``/var/home``, as it is on this one, every real path
under a user's home would compare as outside it.

**Containment is by path components, not by string prefix.** ``/home/bunny-evil``
starts with ``/home/bunny`` and is not inside it. This is a bug people write
once each.

**Some places are refused even when a root would contain them.** A dot-directory
in a home directory is where credentials live: ``~/.ssh``, ``~/.gnupg``,
``~/.config`` and their neighbours. §13 forbids credential retrieval, and
revealing a directory in a file manager is a form of retrieval when the person
at the desk is not the person who asked.

**Only regular files and directories.** A FIFO opened by a file manager blocks;
a device node opened by one does something nobody predicted. Neither is a thing
a companion needs to reveal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..ids import valid_id
from .errors import DesktopRefused, DesktopSchemaError

__all__ = [
    "FORBIDDEN_DIRECTORY_NAMES",
    "MAX_PATH_LENGTH",
    "PathContext",
    "PathReference",
    "ResolvedPath",
    "default_roots",
    "path_digest",
]

#: Long enough for any real file, short enough that a path cannot be used as a
#: payload. ``PATH_MAX`` on Linux is 4096; this is well inside it and the
#: refusal message says the number rather than truncating.
MAX_PATH_LENGTH = 1024

#: Directory names never revealed, wherever they appear in a path. These hold
#: credentials, keys, tokens and browser profiles. Matched as whole components
#: so that ``~/mysshkeys`` is unaffected and ``~/.ssh/id_ed25519`` is refused.
FORBIDDEN_DIRECTORY_NAMES = frozenset({
    ".ssh", ".gnupg", ".pki", ".password-store", ".aws", ".azure", ".config",
    ".local", ".mozilla", ".thunderbird", ".netrc", ".docker", ".kube",
    ".gnome2_private", ".authinfo", ".git-credentials", ".secrets",
})

#: The kinds of place a root may be. The names are the XDG user directories and
#: exist so that a refusal can say "outside your Documents" rather than printing
#: an absolute path a user did not write.
_ROOT_ENVIRONMENT = {
    "documents": "XDG_DOCUMENTS_DIR",
    "downloads": "XDG_DOWNLOAD_DIR",
    "pictures": "XDG_PICTURES_DIR",
    "music": "XDG_MUSIC_DIR",
    "videos": "XDG_VIDEOS_DIR",
    "desktop": "XDG_DESKTOP_DIR",
    "public": "XDG_PUBLICSHARE_DIR",
}


def path_digest(value: str) -> str:
    """A comparable stand-in for a path, for records that may not hold one.

    §13 permits digests and bounded target metadata in a diagnostic log and not
    the path itself, because a path is user content: ``/home/x/divorce/draft.odt``
    discloses something whether or not anyone opens it.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _real(path: Path) -> Path:
    """Every component resolved, symlinks included, without requiring existence.

    ``strict=False`` on purpose: a path that does not exist must reach the
    *existence* check below and be refused for that reason, with that message,
    rather than raising here and being reported as a resolution failure.
    """
    return Path(os.path.realpath(str(path)))


def _contains(root: Path, candidate: Path) -> bool:
    """Whether ``candidate`` is ``root`` or sits beneath it, by component.

    Both are expected to be already resolved. The comparison is on
    :attr:`~pathlib.PurePath.parts` rather than on strings, which is what makes
    ``/home/bunny-evil`` not inside ``/home/bunny``.
    """
    root_parts = root.parts
    candidate_parts = candidate.parts
    return (
        len(candidate_parts) >= len(root_parts)
        and candidate_parts[: len(root_parts)] == root_parts
    )


def default_roots(home: Path | None = None) -> tuple[Path, ...]:
    """The user directories a reveal may reach, resolved.

    Read from the XDG environment where it is set, because a user who moved
    their Documents directory means the moved one. The home directory itself is
    *not* a root: ``~`` contains every dot-directory in
    :data:`FORBIDDEN_DIRECTORY_NAMES` and a great deal else, and "anywhere in
    your home" is not a bound.
    """
    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    roots: list[Path] = []
    for name, variable in sorted(_ROOT_ENVIRONMENT.items()):
        configured = os.environ.get(variable, "").strip()
        candidate = Path(configured) if configured else base / name.capitalize()
        resolved = _real(candidate)
        if resolved.is_dir():
            roots.append(resolved)
    return tuple(sorted(set(roots), key=str))


@dataclass(frozen=True)
class ResolvedPath:
    """One path, resolved and found acceptable, with what may be shown of it.

    ``display`` is the tilde form because that is what a person recognises, and
    it is computed here rather than by a presentation layer so that every
    surface shows the same string as the one the approval was bound to.
    """

    reference_id: str
    #: The real path, symlinks resolved. This is what the adapter is given.
    real_path: str
    #: The path as the user knows it, with the home directory abbreviated.
    display: str
    #: Which approved root contains it, for the refusal messages and the prompt.
    root: str
    is_directory: bool = False
    #: ``True`` when the path as referenced was a symlink. Recorded because a
    #: user approving "reveal this" is entitled to know they are being shown
    #: somewhere other than where they pointed.
    was_symlink: bool = False

    @property
    def digest(self) -> str:
        return path_digest(self.real_path)

    def to_json(self) -> dict[str, Any]:
        return {
            "referenceId": self.reference_id,
            "display": self.display,
            "root": self.root,
            "isDirectory": self.is_directory,
            "wasSymlink": self.was_symlink,
            "pathDigest": self.digest,
        }


@dataclass(frozen=True)
class PathReference:
    """One path the canonical runtime holds, addressable by identifier.

    Constructed only by the task side. A provider receives the *identifier* and
    the display form; it never receives the path, and there is no field on a
    request through which it could supply one.
    """

    reference_id: str
    path: str
    #: How this path came to be in the task's context. Kept because "the user
    #: named this file" and "an earlier action produced it" are different levels
    #: of consent and a prompt should not read the same for both.
    origin: str = "user"

    def __post_init__(self) -> None:
        if not valid_id(self.reference_id):
            raise DesktopSchemaError(
                f"a path reference needs a usable identifier, not {self.reference_id!r}"
            )
        if not self.path:
            raise DesktopSchemaError("a path reference needs a path")


@dataclass
class PathContext:
    """The paths one task may reveal, and the roots that bound them.

    Nothing here is mutable from the provider side. The runtime builds one of
    these per task from what the user actually named, and the broker resolves
    against it; a reference that is not in :attr:`references` does not resolve,
    whatever it is called.
    """

    references: dict[str, PathReference] = field(default_factory=dict)
    roots: tuple[Path, ...] = ()

    @classmethod
    def build(
        cls,
        entries: Mapping[str, str] | None = None,
        *,
        roots: tuple[Path, ...] | None = None,
        home: Path | None = None,
        origin: str = "user",
    ) -> "PathContext":
        resolved_roots = tuple(_real(item) for item in roots) if roots is not None else default_roots(home)
        return cls(
            references={
                key: PathReference(reference_id=key, path=value, origin=origin)
                for key, value in sorted((entries or {}).items())
            },
            roots=resolved_roots,
        )

    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self.references))

    def resolve(self, reference_id: str) -> ResolvedPath:
        """Turn a reference into a path that may be revealed, or refuse.

        The order of the checks is deliberate. Existence is established *after*
        containment, so that a refusal never reveals whether a path outside the
        approved roots exists — a reveal action that could be used to probe the
        filesystem would be a disclosure channel §13 does not permit.
        """
        if not valid_id(reference_id):
            raise DesktopRefused(f"{reference_id!r} is not a usable path reference")
        reference = self.references.get(reference_id)
        if reference is None:
            raise DesktopRefused(
                f"no path reference {reference_id!r} exists in this task's context; a path a "
                "provider named rather than one the task holds cannot be revealed"
            )

        raw = reference.path
        if len(raw) > MAX_PATH_LENGTH:
            raise DesktopRefused(f"the path is longer than {MAX_PATH_LENGTH} characters")
        if "\x00" in raw:
            raise DesktopRefused("the path contains a null byte")

        as_given = Path(raw)
        if not as_given.is_absolute():
            raise DesktopRefused("the path is not absolute")
        was_symlink = as_given.is_symlink()
        real = _real(as_given)

        if not self.roots:
            raise DesktopRefused(
                "this task has no approved roots, so there is nowhere a reveal could point"
            )
        containing = next((root for root in self.roots if _contains(root, real)), None)
        if containing is None:
            # The message names the roots and not the path: a user is told where
            # a reveal may point, and a caller learns nothing about where this
            # one did.
            raise DesktopRefused(
                "the path resolves outside every approved root "
                f"({', '.join(_tilde(str(item)) for item in self.roots)}); symlinks are "
                "resolved before this check, so a link pointing outside is refused here"
            )

        # ``real.parts``, not ``PurePosixPath(str(real)).parts``. The latter
        # splits on ``/`` only, so on a development machine with backslash
        # separators the whole path is one part and the check silently matches
        # nothing. A check that quietly stops checking on one platform is worse
        # than no check, because the test that covers it goes on passing.
        forbidden = FORBIDDEN_DIRECTORY_NAMES.intersection(real.parts)
        if forbidden:
            raise DesktopRefused(
                f"the path passes through {sorted(forbidden)[0]!r}, which holds credentials "
                "and is never revealed"
            )

        if not real.exists():
            raise DesktopRefused("the path does not exist")
        if real.is_dir():
            is_directory = True
        elif real.is_file():
            is_directory = False
        else:
            raise DesktopRefused(
                "the path is neither a regular file nor a directory; sockets, devices and "
                "pipes are not revealed"
            )

        return ResolvedPath(
            reference_id=reference_id,
            real_path=str(real),
            display=_tilde(str(real)),
            root=_tilde(str(containing)),
            is_directory=is_directory,
            was_symlink=was_symlink,
        )


def _tilde(value: str) -> str:
    """``/home/bunny/Documents/x`` as ``~/Documents/x``.

    Cosmetic and load-bearing: the approval prompt, the event record and the
    refusal message all use it, so a user comparing what they approved with what
    a history says happened is comparing two identical strings.
    """
    home = os.path.expanduser("~")
    if home and home != "~" and (value == home or value.startswith(home + os.sep)):
        return "~" + value[len(home):].replace(os.sep, "/")
    return value

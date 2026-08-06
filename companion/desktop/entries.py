# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which applications may be launched, read from what is actually installed.

§4.2 forbids two things that look similar and fail differently: an arbitrary
executable path, and arbitrary command-line arguments. Both are refused here by
the same structural decision — **an application is named by its desktop entry
identifier and by nothing else.** There is no field on a launch request for a
program, an argument, a working directory or an environment variable. A provider
that wanted one would have to find somewhere to put it.

What remains is the entry itself, and an entry is a file. So this module reads
it, and reads it suspiciously:

**Only from approved directories, after symlinks.** :data:`APPLICATION_ROOTS`
are the XDG application directories. An entry reached through a symlink out of
one of them is refused — that is the substitution attack, and it is the same
check :func:`companion.voice.execution.resolve_executable` makes about binaries
for the same reason.

**Never a path from the caller.** The identifier is matched against a pattern
that admits no separator and no ``..``, and the file is then *searched for* in
the approved directories in order. A caller cannot express "this file"; only
"this name", and the name is resolved by us.

**Hidden and non-application entries are refused.** ``NoDisplay=true`` and
``Hidden=true`` mean the desktop does not show this to a person, and something a
person cannot find in their own menu is not something a companion should start
on their behalf. ``Type`` must be ``Application``: a ``Link`` entry is a URI
opener wearing an application's clothes, and it would bypass
:mod:`companion.desktop.uris` entirely.

**Field codes are validated and never expanded.** The launch path hands the
entry and the approved URIs to the desktop's own launcher, which does the
substitution according to the specification. We never build an argv. That is the
whole answer to field-code injection: a file called ``a b.txt`` or ``%f`` or
``"; rm -rf ~"`` is quoted by the launcher exactly as it quotes every other
filename, and there is no string of ours for it to break out of. What is checked
here is only that the entry's own ``Exec`` line uses codes from the standard set
— an entry using an unknown ``%z`` is malformed, and a malformed entry is
refused rather than guessed at.

**Shell indirection is refused.** ``Exec=sh -c …`` re-introduces a command
string, which is precisely the thing this catalogue does not contain. Legitimate
applications do not need it, and an entry that has it is either broken or
hostile.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import stat
from typing import Any, Iterable, Mapping, Sequence

from .errors import DesktopRefused

__all__ = [
    "APPLICATION_ROOTS",
    "DESKTOP_ENTRY_SUFFIX",
    "DesktopEntry",
    "VALID_FIELD_CODES",
    "application_roots",
    "resolve_application",
    "valid_application_id",
]

DESKTOP_ENTRY_SUFFIX = ".desktop"

#: An application id: the entry's basename. No separator, no ``..``, no leading
#: dot, bounded. Reverse-DNS names with ``+`` and ``-`` are ordinary, so both are
#: admitted; anything that could steer a filesystem lookup is not.
_APPLICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

#: The field codes the desktop entry specification defines. ``%%`` is a literal
#: percent and is handled separately.
VALID_FIELD_CODES = frozenset("fFuUick")

#: Codes the specification deprecated and says must be removed. An entry still
#: carrying one was written against an old spec, and an entry nobody has
#: maintained is not one to run on a user's behalf without being sure.
_DEPRECATED_FIELD_CODES = frozenset("dDnNvm")

#: Codes that mean "give me files" and "give me URIs". Read so a launch that
#: supplies neither, or supplies files to an entry that takes none, is caught
#: before the launcher silently drops them.
_FILE_CODES = frozenset("fF")
_URI_CODES = frozenset("uU")

#: Programs whose whole purpose is to run another command string. An ``Exec``
#: beginning with one of these is a command interpreter, and interpreting a
#: command is the capability this phase does not have.
_INTERPRETERS = frozenset({
    "sh", "bash", "dash", "zsh", "ksh", "csh", "tcsh", "fish", "busybox",
    "python", "python3", "perl", "ruby", "node", "osascript", "pwsh",
})

#: Characters that mean something to a shell. Their presence in an ``Exec``
#: outside a quoted string means the entry expects shell interpretation, which
#: the specification does not promise and which we will not provide.
_SHELL_METACHARACTERS = re.compile(r"[;&|`$<>(){}\[\]!*?~\n\r]")

#: The whole boolean vocabulary of a desktop entry file.
_TRUE = frozenset({"true", "1", "yes"})


def application_roots() -> tuple[Path, ...]:
    """Where installed desktop entries live, in search order, resolved.

    ``XDG_DATA_HOME`` first and ``XDG_DATA_DIRS`` after, per the basedir
    specification, so a user's own entry shadows a system one exactly as it does
    in their menu. Anything that is not a directory is dropped rather than
    guessed at.
    """
    candidates: list[str] = []
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    candidates.append(data_home or os.path.join(os.path.expanduser("~"), ".local", "share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "").strip() or "/usr/local/share:/usr/share"
    candidates.extend(item for item in data_dirs.split(os.pathsep) if item.strip())

    roots: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        directory = Path(os.path.realpath(os.path.join(item, "applications")))
        key = str(directory)
        if key in seen or not directory.is_dir():
            continue
        seen.add(key)
        roots.append(directory)
    return tuple(roots)


#: Computed once at import for the common case, and recomputed by callers that
#: need to see a changed environment — the vertical slice and the tests both do.
APPLICATION_ROOTS: tuple[Path, ...] = application_roots()


def valid_application_id(value: str) -> bool:
    """Whether a string could name an entry. Says nothing about it existing."""
    if not isinstance(value, str):
        return False
    stem = value[: -len(DESKTOP_ENTRY_SUFFIX)] if value.endswith(DESKTOP_ENTRY_SUFFIX) else value
    return bool(stem) and _APPLICATION_ID.match(stem) is not None and ".." not in stem


@dataclass(frozen=True)
class DesktopEntry:
    """One installed application, as much of it as a launch needs.

    ``exec_program`` is recorded and **not used to launch**. It is here so that
    a refusal can name what it refused and so that an audit record shows which
    program an application id actually resolved to on this machine — which is
    the fact that makes "the approved application id was the launched one"
    checkable after the event rather than assumed.
    """

    application_id: str
    #: The entry file, after symlinks, inside an approved root.
    entry_path: str
    #: Which approved root contains it.
    root: str
    display_name: str
    exec_program: str = ""
    accepts_files: bool = False
    accepts_uris: bool = False
    terminal: bool = False
    #: ``True`` when the entry declares ``DBusActivatable``. This is the whole
    #: of §4.3's "where supported": an activatable application can be *raised*
    #: through ``org.freedesktop.Application.Activate``, and one that is not has
    #: no standard mechanism at all — which is reported as ``UNSUPPORTED``
    #: rather than approximated with synthetic input.
    dbus_activatable: bool = False
    #: ``True`` when the entry came from the user's own data directory rather
    #: than a system one. Not a refusal — a user may install applications — but
    #: a fact worth putting in front of them in the approval prompt.
    user_installed: bool = False

    @property
    def entry_file_name(self) -> str:
        return f"{self.application_id}{DESKTOP_ENTRY_SUFFIX}"

    def accepts(self, *, uris: Sequence[str] = ()) -> bool:
        return not uris or self.accepts_files or self.accepts_uris

    def to_json(self) -> dict[str, Any]:
        return {
            "applicationId": self.application_id,
            "displayName": self.display_name,
            "entryPath": self.entry_path,
            "root": self.root,
            "execProgram": self.exec_program,
            "acceptsFiles": self.accepts_files,
            "acceptsUris": self.accepts_uris,
            "terminal": self.terminal,
            "dbusActivatable": self.dbus_activatable,
            "userInstalled": self.user_installed,
        }


def _read_entry_group(text: str) -> dict[str, str]:
    """The ``[Desktop Entry]`` group's keys, unlocalised.

    Only the first group is read, and only its unlocalised keys. A localised
    ``Name[de]`` is skipped rather than merged: which locale a value came from
    would otherwise depend on iteration order, and the *displayed* name is part
    of what a user approves.
    """
    values: dict[str, str] = {}
    in_group = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_group:
                break
            in_group = stripped[1:-1].strip() == "Desktop Entry"
            continue
        if not in_group:
            continue
        key, separator, value = stripped.partition("=")
        if not separator:
            continue
        key = key.strip()
        if "[" in key:  # a localised key
            continue
        values.setdefault(key, value.strip())
    return values


def _check_field_codes(exec_line: str, application_id: str) -> tuple[bool, bool]:
    """Validate the ``Exec`` field codes; report which kind of argument it takes.

    Nothing is expanded here and nothing ever will be. The return value says
    only whether the launcher may be given files or URIs, which is a question
    about the *entry*, not about any particular launch.
    """
    accepts_files = False
    accepts_uris = False
    index = 0
    while index < len(exec_line):
        character = exec_line[index]
        if character != "%":
            index += 1
            continue
        if index + 1 >= len(exec_line):
            raise DesktopRefused(
                f"{application_id!r} has an Exec line ending in a bare '%'; the entry is malformed"
            )
        code = exec_line[index + 1]
        if code == "%":
            index += 2
            continue
        if code in _DEPRECATED_FIELD_CODES:
            raise DesktopRefused(
                f"{application_id!r} uses the deprecated field code '%{code}', which the "
                "specification says must be removed; the entry was not launched"
            )
        if code not in VALID_FIELD_CODES:
            raise DesktopRefused(
                f"{application_id!r} uses the unknown field code '%{code}'; an entry this "
                "build cannot read completely is not one it will start"
            )
        if code in _FILE_CODES:
            accepts_files = True
        if code in _URI_CODES:
            accepts_uris = True
        index += 2
    return accepts_files, accepts_uris


def _check_exec_shape(exec_line: str, application_id: str) -> str:
    """The program an entry would run, having refused the shapes we will not.

    Parsed with :func:`shlex.split` in POSIX mode, which is how the desktop
    entry specification says a value is quoted. A value that will not parse is
    malformed, and a malformed entry is refused rather than repaired.
    """
    # Field codes are removed before parsing: `%f` is not a shell token and
    # leaving it in makes an otherwise valid line look like it has a stray
    # argument. They have already been validated above.
    without_codes = re.sub(r"%[A-Za-z%]", " ", exec_line)
    try:
        tokens = shlex.split(without_codes, posix=True)
    except ValueError as exc:
        raise DesktopRefused(
            f"{application_id!r} has an Exec line that does not parse ({exc}); the entry is malformed"
        ) from None
    if not tokens:
        raise DesktopRefused(f"{application_id!r} has an empty Exec line")

    metacharacter = _SHELL_METACHARACTERS.search(without_codes)
    if metacharacter is not None:
        raise DesktopRefused(
            f"{application_id!r} has an Exec line containing {metacharacter.group(0)!r}, which "
            "asks for shell interpretation; this build starts programs and does not interpret "
            "commands"
        )

    program = os.path.basename(tokens[0])
    if program in _INTERPRETERS or "-c" in tokens[1:2]:
        raise DesktopRefused(
            f"{application_id!r} runs {program!r} as a command interpreter; an entry whose "
            "Exec is a command string is exactly the arbitrary execution this phase excludes"
        )
    return tokens[0]


def _entry_file_safe(path: Path, application_id: str) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise DesktopRefused(
            f"{application_id!r} could not be inspected: {exc.strerror or exc}"
        ) from None
    if not stat.S_ISREG(info.st_mode):
        raise DesktopRefused(f"{application_id!r} is not a regular file")
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise DesktopRefused(
            f"{application_id!r} is writable by group or other, so what it says now is not "
            "what it may say when it is launched; it was refused"
        )
    if os.name == "posix" and info.st_uid not in (0, os.getuid()):
        raise DesktopRefused(
            f"{application_id!r} is owned by neither root nor this user; an entry a third "
            "party controls is not one this build will start"
        )


def resolve_application(
    application_id: str,
    *,
    roots: Iterable[Path] | None = None,
) -> DesktopEntry:
    """Find one installed application by identifier, or refuse and say why.

    The search is by name through the approved roots in order, first match
    wins — the same order the user's own menu uses, so the application this
    starts is the one that name means to them.
    """
    if not valid_application_id(application_id):
        raise DesktopRefused(
            f"{application_id!r} is not a usable application identifier; an identifier names "
            "an installed entry and never a path"
        )
    stem = (
        application_id[: -len(DESKTOP_ENTRY_SUFFIX)]
        if application_id.endswith(DESKTOP_ENTRY_SUFFIX)
        else application_id
    )
    search = tuple(roots) if roots is not None else application_roots()
    if not search:
        raise DesktopRefused(
            "there are no application directories on this system, so no application can be resolved"
        )

    for root in search:
        resolved_root = Path(os.path.realpath(str(root)))
        candidate = resolved_root / f"{stem}{DESKTOP_ENTRY_SUFFIX}"
        if not candidate.exists():
            continue
        real = Path(os.path.realpath(str(candidate)))
        # After symlinks, and against *every* approved root rather than only the
        # one it was found in: an entry in the user's directory may legitimately
        # link to a system one, and that is not a substitution.
        inside = any(
            real == Path(os.path.realpath(str(item)))
            or real.parts[: len(Path(os.path.realpath(str(item))).parts)]
            == Path(os.path.realpath(str(item))).parts
            for item in search
        )
        if not inside:
            raise DesktopRefused(
                f"{stem!r} in {root} resolves to {real}, which is outside every application "
                "directory; this is an entry substitution and was refused"
            )
        _entry_file_safe(real, stem)
        return _entry_from_file(stem, real, resolved_root, search)

    raise DesktopRefused(
        f"{stem!r} is not an installed application; only entries present in "
        f"{', '.join(str(item) for item in search)} may be launched"
    )


def _entry_from_file(
    stem: str, real: Path, root: Path, search: Sequence[Path]
) -> DesktopEntry:
    try:
        text = real.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise DesktopRefused(f"{stem!r} could not be read as a desktop entry: {exc}") from None
    if len(text) > 64 * 1024:
        raise DesktopRefused(f"{stem!r} is larger than any desktop entry should be")

    values = _read_entry_group(text)
    if not values:
        raise DesktopRefused(f"{stem!r} has no [Desktop Entry] group; it is malformed")
    entry_type = values.get("Type", "")
    if entry_type != "Application":
        raise DesktopRefused(
            f"{stem!r} is a {entry_type or 'typeless'} entry rather than an Application; a Link "
            "entry opens a URI and would bypass the URI allowlist"
        )
    if values.get("Hidden", "").lower() in _TRUE:
        raise DesktopRefused(f"{stem!r} is marked Hidden, which means deleted; it was not launched")
    if values.get("NoDisplay", "").lower() in _TRUE:
        raise DesktopRefused(
            f"{stem!r} is marked NoDisplay, so it does not appear in the user's own menu; a "
            "companion does not start what a person cannot find"
        )
    exec_line = values.get("Exec", "").strip()
    if not exec_line:
        raise DesktopRefused(f"{stem!r} has no Exec line; there is nothing to launch")

    accepts_files, accepts_uris = _check_field_codes(exec_line, stem)
    program = _check_exec_shape(exec_line, stem)

    try_exec = values.get("TryExec", "").strip()
    if try_exec and os.path.isabs(try_exec) and not os.path.exists(try_exec):
        raise DesktopRefused(
            f"{stem!r} declares TryExec={try_exec}, which is not installed; the entry says "
            "of itself that it will not run"
        )

    home_root = Path(os.path.realpath(os.path.join(
        os.environ.get("XDG_DATA_HOME", "").strip()
        or os.path.join(os.path.expanduser("~"), ".local", "share"),
        "applications",
    )))
    return DesktopEntry(
        application_id=stem,
        entry_path=str(real),
        root=str(root),
        display_name=values.get("Name", "").strip() or stem,
        exec_program=program,
        accepts_files=accepts_files,
        accepts_uris=accepts_uris,
        terminal=values.get("Terminal", "").lower() in _TRUE,
        dbus_activatable=values.get("DBusActivatable", "").lower() in _TRUE,
        user_installed=root == home_root,
    )


def installed_applications(*, roots: Iterable[Path] | None = None, limit: int = 512) -> tuple[str, ...]:
    """Identifiers of the entries that resolve cleanly, for the explain surface.

    Entries that fail any check above are simply absent — this is a list of what
    *could* be launched, and including something that would be refused would
    make it a list of what could not.
    """
    search = tuple(roots) if roots is not None else application_roots()
    found: list[str] = []
    seen: set[str] = set()
    for root in search:
        try:
            names = sorted(item.name for item in Path(root).iterdir())
        except OSError:
            continue
        for name in names:
            if not name.endswith(DESKTOP_ENTRY_SUFFIX):
                continue
            stem = name[: -len(DESKTOP_ENTRY_SUFFIX)]
            if stem in seen or not valid_application_id(stem):
                continue
            seen.add(stem)
            try:
                resolve_application(stem, roots=search)
            except DesktopRefused:
                continue
            found.append(stem)
            if len(found) >= limit:
                return tuple(sorted(found))
    return tuple(sorted(found))

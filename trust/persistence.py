# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Durable, private, atomic files — one implementation for the new packages.

:mod:`trust`, :mod:`capsules` and :mod:`catalog` all persist small documents that
a security decision depends on, and all three need the same four properties:

**A reader sees the old document or the new one, never a mixture.** The write
goes to a temporary in the *same directory* and is moved into place with
``os.replace``. Across filesystems a move is a copy, and a copy has a window in
which the destination is half written — which for a permission file means a
window in which the grants a person set are partly gone.

**Nothing reports success before the bytes are on the disk.** ``flush`` then
``fsync`` on the file, and ``fsync`` on the directory after the rename, before
the function returns. A caller told a grant was revoked can rely on the
revocation surviving the power going out; the alternative is a machine that comes
back up having re-granted something.

**The file is private from the moment it exists.** The mode is applied to the
temporary before the rename, not to the destination after it, so there is no
instant in which a permission database is world-readable.

**A read that meets a concurrent replacement retries, briefly.** On POSIX a
rename over an open file simply succeeds and this costs nothing. On Windows the
same rename can be refused with ``ERROR_ACCESS_DENIED`` or
``ERROR_SHARING_VIOLATION``, which is not a damaged file and must not be reported
as one; that failure mode was measured in this repository (see
:mod:`companion.store`, whose ``_replace_stable`` carries the full account) and
cost a suite run to diagnose. Bunny OS runs on Linux, where the retry loop
retries nothing.

This is one implementation for three new packages rather than a twenty-first
copy of the pattern. It is deliberately *not* shared with
:mod:`companion.store`: that module's version is part of an append protocol that
holds a session lock and synchronises the directory as a step in it, and pulling
the two together would make a change to the event stream a change to the
permission database.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Mapping

__all__ = [
    "DIRECTORY_MODE",
    "FILE_MODE",
    "PersistenceError",
    "append_jsonl",
    "atomic_write_json",
    "private_directory",
    "read_json",
    "read_jsonl",
]

#: ``rwx------``: a permission database is not a thing other local accounts read.
DIRECTORY_MODE = 0o700

#: ``rw-------``.
FILE_MODE = 0o600

_READ_ATTEMPTS = 5
_READ_BACKOFF_SECONDS = 0.01
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_SECONDS = 0.01

#: Windows codes for "somebody else has this file open". 5 is
#: ``ERROR_ACCESS_DENIED``, 32 is ``ERROR_SHARING_VIOLATION``; which one arrives
#: depends on how the other handle was opened.
_SHARING_WINERRORS = frozenset({5, 32})

#: A module constant rather than an ``os.name`` test inside the predicate, so a
#: test can simulate the platform by patching *this* and nothing else. Patching
#: ``os.name`` reaches ``tempfile`` and ``pathlib`` too.
_WINDOWS = os.name == "nt"


class PersistenceError(OSError):
    """A durable write or read could not be completed."""


def private_directory(directory: Path) -> None:
    """Create ``directory`` and its parents, owner-only."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PersistenceError(f"{directory} could not be created: {exc}") from exc
    try:
        directory.chmod(DIRECTORY_MODE)
    except OSError:
        # A filesystem without POSIX modes — a developer machine, not the
        # installed system. The file modes are the defence that matters.
        pass


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink()
    except OSError:
        pass


def _transient_replacement(error: OSError, path: Path) -> bool:
    if not _WINDOWS or not isinstance(error, PermissionError):
        return False
    if getattr(error, "winerror", None) not in _SHARING_WINERRORS:
        return False
    try:
        status = path.stat()
    except OSError:
        return False
    return bool(status.st_mode & stat.S_IWUSR)


def _replace_stable(temporary: Path, path: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            if attempt == _REPLACE_ATTEMPTS - 1 or not _transient_replacement(exc, path):
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))


def _fsync_directory(directory: Path) -> None:
    """Make a rename durable. A no-op where the platform has no directory fd."""
    try:
        handle = os.open(str(directory), getattr(os, "O_DIRECTORY", os.O_RDONLY))
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Replace ``path`` with ``document``, or leave it entirely unchanged."""
    private_directory(path.parent)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=str(path.parent), prefix=path.name + ".", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, FILE_MODE)
        except OSError:
            pass
        _replace_stable(temporary, path)
    except OSError as exc:
        _discard(temporary)
        raise PersistenceError(f"{path} could not be written: {exc}") from exc
    except BaseException:
        # KeyboardInterrupt and SystemExit arrive most easily during the backoff
        # above; without this the temporary outlives the interruption and the
        # directory accumulates one orphan per attempt.
        _discard(temporary)
        raise
    _fsync_directory(path.parent)


def _read_bytes_stable(path: Path) -> bytes:
    last: OSError | None = None
    for attempt in range(_READ_ATTEMPTS):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            last = exc
            time.sleep(_READ_BACKOFF_SECONDS * (attempt + 1))
    raise last if last is not None else PersistenceError(f"{path} could not be read")


def read_json(path: Path, *, default: Any = None) -> Any:
    """Read a JSON document, returning ``default`` only when the file is absent.

    An *absent* file and an *unreadable* one are different facts and this
    function keeps them different: absence returns the default, damage raises.
    Callers in this package turn the raise into a denial. Returning the default
    for both would make a corrupted permission database indistinguishable from a
    new one, which is the shape of bug where a machine silently forgets that
    somebody said no.
    """
    try:
        raw = _read_bytes_stable(path)
    except FileNotFoundError:
        return default
    except OSError as exc:
        raise PersistenceError(f"{path} could not be read: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersistenceError(f"{path} is not readable JSON: {exc}") from exc


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """Append one JSON record durably to a private, non-symlink file.

    ``O_NOFOLLOW`` matters because these roots are configurable through the
    environment, so one can be pointed at a directory another account can write.
    Following a symlink planted there would append a person's activity history to
    a file of somebody else's choosing.
    """
    private_directory(path.parent)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, FILE_MODE)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PersistenceError(f"{path} is a symbolic link and will not be appended to") from exc
        raise PersistenceError(f"{path} could not be opened: {exc}") from exc
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n", closefd=False) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise PersistenceError(f"{path} could not be appended to: {exc}") from exc
    finally:
        os.close(descriptor)


def read_jsonl(path: Path, *, limit: int | None = None) -> list[Any]:
    """Read a JSON-lines file, newest last.

    A malformed line raises rather than being skipped. These files are audit
    records; a reader that quietly dropped the lines it could not parse would
    report a shorter history than actually happened, and the missing entries
    would be exactly the ones a defect or an attacker had damaged.
    """
    try:
        raw = _read_bytes_stable(path)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise PersistenceError(f"{path} could not be read: {exc}") from exc
    records: list[Any] = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PersistenceError(f"{path}:{number} is not readable JSON: {exc}") from exc
    if limit is not None and limit >= 0:
        return records[-limit:]
    return records

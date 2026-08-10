# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Show one file in the file manager. Show it — nothing else.

``org.freedesktop.FileManager1`` is the freedesktop interface every major file
manager implements, and it has exactly the two methods this action needs:
``ShowItems`` selects a file inside its directory, and ``ShowFolders`` opens a
directory. Neither opens, moves, changes or deletes anything, which is §4.9's
requirement satisfied by the choice of interface rather than by a check
afterwards.

The path is a :class:`~companion.desktop.paths.ResolvedPath`, which is the type
:mod:`companion.desktop.paths` produces only after it has resolved every symlink
and found the real path inside an approved root. As with the URI adapter, the
argument type is doing the security work: there is no method here that takes a
string, so a path that did not go through that resolution cannot be revealed.

A note on the URI conversion. ``ShowItems`` takes URIs, so the resolved path is
percent-encoded into a ``file:`` URI here. It goes back through
:func:`companion.desktop.uris.parse_uri` on the way, which looks redundant and
is not: the encoder and the parser are then checked against each other on every
call, and a path that survives one and not the other is a disagreement worth
finding before the file manager sees it.
"""

from __future__ import annotations

import time
from urllib.parse import quote

from ..errors import DesktopCancelled, DesktopUnavailable
from ..paths import ResolvedPath
from ..uris import parse_uri
from .base import AdapterOutcome, Availability, acknowledged, failure
from .dbus import GioCancellable, SessionBus, gio_available

__all__ = ["FILE_MANAGER_BUS_NAME", "FileRevealAdapter"]

FILE_MANAGER_BUS_NAME = "org.freedesktop.FileManager1"


class FileRevealAdapter:
    """Reveal one already-resolved path."""

    adapter_id = "FileRevealAdapter"

    def __init__(self, bus: SessionBus | None = None) -> None:
        self._bus = bus if bus is not None else SessionBus()

    def probe(self) -> Availability:
        if not gio_available():
            return Availability(
                False, mechanism="dbus", service=FILE_MANAGER_BUS_NAME,
                detail="PyGObject is not installed, so this build has no D-Bus transport",
            )
        # `NameHasOwner` is false for a file manager that is installed and not
        # running, and D-Bus activation would start it. That is the correct
        # behaviour for a *launch* and the wrong answer for a *probe*: §16 asks
        # whether the action is available, and a service that will start on
        # demand is available. So activatability is asked about too.
        if self._bus.name_has_owner(FILE_MANAGER_BUS_NAME):
            return Availability(
                True, mechanism="dbus", service=FILE_MANAGER_BUS_NAME,
                detail="a file manager is running on the session bus",
            )
        if _activatable(self._bus, FILE_MANAGER_BUS_NAME):
            return Availability(
                True, mechanism="dbus", service=FILE_MANAGER_BUS_NAME,
                detail="a file manager is registered for activation and will be started on demand",
            )
        return Availability(
            False, mechanism="dbus", service=FILE_MANAGER_BUS_NAME,
            detail="no file manager implements org.freedesktop.FileManager1 on this session",
        )

    def reveal(
        self,
        path: ResolvedPath,
        *,
        cancellable: GioCancellable | None = None,
    ) -> AdapterOutcome:
        started = time.monotonic()
        self.probe().require("desktop.file.reveal")
        if cancellable is not None:
            cancellable.check("before the file manager was asked")

        uri = "file://" + quote(path.real_path.replace("\\", "/"), safe="/")
        # Re-parsed rather than trusted. See the module docstring: this is the
        # encoder and the parser checking each other on every call.
        parsed = parse_uri(uri, expected_scheme="file")

        call = "filemanager.show_folders" if path.is_directory else "filemanager.show_items"
        try:
            self._bus.call(call, ([parsed.normalised], ""), cancellable=cancellable)
        except DesktopCancelled:
            raise
        except DesktopUnavailable as exc:
            return failure("dbus", str(exc))
        from dataclasses import replace

        return replace(
            acknowledged(
                "dbus",
                detail=(
                    "the file manager accepted the request; whether it drew a window is not "
                    "observable from here"
                ),
                isDirectory=path.is_directory,
            ),
            duration_seconds=max(0.0, time.monotonic() - started),
        )

    def close(self) -> None:
        self._bus.close()


def _activatable(bus: SessionBus, name: str) -> bool:
    """Whether a service would start if it were called.

    Asked through ``ListActivatableNames`` in principle; in practice that is one
    more entry in the D-Bus call table for a question with a cheaper answer —
    a ``.service`` file on disk. Reading the file is a filesystem check and is
    exactly the "inferred from an installed file" reasoning §16 warns about, so
    it is used only as a *second* answer after the bus has said no, and the
    detail line says which of the two applied.
    """
    import os
    from pathlib import Path

    directories = [
        os.path.join(
            os.environ.get("XDG_DATA_HOME", "").strip()
            or os.path.join(os.path.expanduser("~"), ".local", "share"),
            "dbus-1", "services",
        ),
    ]
    data_dirs = os.environ.get("XDG_DATA_DIRS", "").strip() or "/usr/local/share:/usr/share"
    directories.extend(os.path.join(item, "dbus-1", "services") for item in data_dirs.split(os.pathsep))
    for directory in directories:
        try:
            entries = sorted(Path(directory).iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.name.endswith(".service"):
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if f"Name={name}" in text:
                return True
    return False

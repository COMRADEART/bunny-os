# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start an installed application, and — separately — try to raise its window.

Two adapters, because they are two different capabilities with two different
honesty problems, and merging them would let the weaker one borrow the stronger
one's success.

**Launching** goes through :class:`Gio.DesktopAppInfo`, which is §7's "Gio
application launching" and is the same code path the user's own menu uses. It
reads the entry, expands the field codes according to the specification, quotes
every filename correctly, and applies startup notification. We build no argv, so
a file called ``"; rm -rf ~"`` is a filename to GIO exactly as it is to the file
manager. That is the whole answer to field-code injection, and it is an answer
by *not implementing* the thing that would be vulnerable.

**Presenting** has no equivalent. There is no freedesktop interface for "raise
this application's window", and Wayland compositors deliberately refuse
activation requests that do not carry a token proving the user asked. The one
standard mechanism that works is ``org.freedesktop.Application.Activate``, which
only exists for entries declaring ``DBusActivatable``, and even then the
compositor may decline to raise. So:

* an application that is not ``DBusActivatable`` reports ``UNSUPPORTED``;
* an application that is gets activated, and the result is an
  **acknowledgement** — the call returned, the window may or may not have come
  forward, and focus-stealing prevention is respected because we never try to
  work around it;
* nothing here synthesises an Alt-Tab, a pointer event or a keystroke. There is
  no code in this package that can produce an input event, which is a stronger
  statement than a policy against doing so.

§4.3 asks for exactly this and specifically forbids faking success. A user told
"the window was raised" who then finds it behind three others has learned that
this system's reports are decorative.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from ..entries import DesktopEntry
from ..errors import DesktopCancelled, DesktopUnavailable, DesktopUnsupported
from ..uris import ParsedUri
from .base import (
    AdapterOutcome,
    Availability,
    acknowledged,
    failure,
    unsupported_outcome,
)
from .dbus import GioCancellable, SessionBus, gio_available

__all__ = ["ApplicationLaunchAdapter", "ApplicationPresentAdapter"]


def _app_info(entry: DesktopEntry) -> Any:
    """A :class:`Gio.DesktopAppInfo` for one already-resolved entry.

    Constructed from the *file* rather than from the identifier. ``new()`` would
    search GIO's own directory list, which is nearly but not exactly the list
    :func:`companion.desktop.entries.application_roots` checked — and "nearly"
    means there is an entry GIO would find that we did not validate.
    """
    from gi.repository import Gio

    info = Gio.DesktopAppInfo.new_from_filename(entry.entry_path)
    if info is None:
        raise DesktopUnavailable(
            f"{entry.application_id} could not be read as a desktop entry by Gio, although it "
            "parsed here; the entry is inconsistent and was not launched"
        )
    return info


class ApplicationLaunchAdapter:
    """Start one installed application, optionally with approved items."""

    adapter_id = "ApplicationLaunchAdapter"

    def __init__(self, bus: SessionBus | None = None) -> None:
        self._bus = bus if bus is not None else SessionBus()

    def probe(self) -> Availability:
        if not gio_available():
            return Availability(
                False, mechanism="gio", service="Gio.DesktopAppInfo",
                detail="PyGObject is not installed, so applications cannot be launched",
            )
        import os

        if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
            # §16: a graphical session, not an installed binary. An application
            # launched with no display either fails or starts invisibly, and
            # both are worse than saying so.
            return Availability(
                False, mechanism="gio", service="Gio.DesktopAppInfo",
                detail="there is no graphical session, so a launched application would have nowhere to appear",
            )
        return Availability(
            True, mechanism="gio", service="Gio.DesktopAppInfo",
            detail="Gio can launch installed desktop entries in this session",
        )

    def running(self, entry: DesktopEntry) -> bool | None:
        """Whether the application appears to be running already.

        ``None`` means "cannot tell", which is the answer for every entry that
        is not ``DBusActivatable`` — and it is returned rather than guessed
        because §9 lets an uncertain launch be *reconciled* by activation state,
        and a reconciliation built on a guess is worse than none.
        """
        if not entry.dbus_activatable or not gio_available():
            return None
        try:
            return self._bus.name_has_owner(entry.application_id)
        except DesktopUnavailable:
            return None

    def launch(
        self,
        entry: DesktopEntry,
        *,
        file_paths: Sequence[str] = (),
        uris: Sequence[ParsedUri] = (),
        focus_existing: bool = True,
        cancellable: GioCancellable | None = None,
    ) -> AdapterOutcome:
        """Start it, handing over only items that were already approved.

        ``file_paths`` are real paths from
        :class:`~companion.desktop.paths.ResolvedPath`; ``uris`` are parsed
        URIs. Both are converted to URIs here and handed to GIO as a list —
        never joined into a string, and never substituted into a command.
        """
        started = time.monotonic()
        self.probe().require("desktop.application.launch")
        if cancellable is not None:
            cancellable.check("before the application was launched")

        from urllib.parse import quote

        handover = [
            "file://" + quote(item.replace("\\", "/"), safe="/") for item in file_paths
        ]
        handover.extend(item.normalised for item in uris)
        if handover and not entry.accepts(uris=handover):
            raise DesktopUnavailable(
                f"{entry.application_id} declares no field code for files or URIs, so the "
                "items would be silently dropped; the launch was refused instead"
            )

        already = self.running(entry)
        if already and focus_existing and entry.dbus_activatable and not handover:
            # An activatable application that is already running is *activated*
            # rather than started again. This is what `focusExisting` means, and
            # it is also why launching is reconcilable: the same call reaches the
            # same instance.
            return _timed(self._activate(entry, cancellable=cancellable, already_running=True), started)

        info = _app_info(entry)
        from gi.repository import GLib

        try:
            if handover:
                launched = info.launch_uris(list(handover), None)
            else:
                launched = info.launch([], None)
        except GLib.Error as exc:
            return failure("gio", f"{entry.application_id} could not be launched: {exc.message}")
        if not launched:
            return failure("gio", f"{entry.application_id} declined to launch")

        return _timed(
            acknowledged(
                "gio",
                detail=(
                    "Gio launched the entry; whether the application drew a window is not "
                    "observable from here"
                ),
                applicationId=entry.application_id,
                itemsHandedOver=len(handover),
                wasAlreadyRunning=already,
                activatable=entry.dbus_activatable,
            ),
            started,
        )

    def _activate(
        self, entry: DesktopEntry, *, cancellable: GioCancellable | None, already_running: bool
    ) -> AdapterOutcome:
        info = _app_info(entry)
        from gi.repository import GLib

        try:
            launched = info.launch([], None)
        except GLib.Error as exc:
            return failure("gio", f"{entry.application_id} could not be activated: {exc.message}")
        if not launched:
            return failure("gio", f"{entry.application_id} declined activation")
        return acknowledged(
            "gio",
            detail=(
                "the running instance was activated rather than a second one started"
                if already_running
                else "Gio activated the entry"
            ),
            applicationId=entry.application_id,
            wasAlreadyRunning=already_running,
            activatable=True,
        )

    def close(self) -> None:
        self._bus.close()


class ApplicationPresentAdapter:
    """Raise one application's window where the desktop supports it, or say so."""

    adapter_id = "ApplicationPresentAdapter"

    def __init__(self, bus: SessionBus | None = None) -> None:
        self._bus = bus if bus is not None else SessionBus()

    def probe(self) -> Availability:
        if not gio_available():
            return Availability(
                False, mechanism="dbus", service="org.freedesktop.Application",
                detail="PyGObject is not installed, so no activation can be requested",
            )
        import os

        if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
            return Availability(
                False, mechanism="dbus", service="org.freedesktop.Application",
                detail="there is no graphical session, so there is no window to raise",
            )
        return Availability(
            True, mechanism="dbus", service="org.freedesktop.Application",
            detail=(
                "activation can be requested for applications that declare DBusActivatable; "
                "whether the compositor honours it is the compositor's decision"
            ),
        )

    def present(
        self,
        entry: DesktopEntry,
        *,
        window_identity: str = "",
        cancellable: GioCancellable | None = None,
    ) -> AdapterOutcome:
        started = time.monotonic()
        availability = self.probe()
        if not availability.available:
            return unsupported_outcome("dbus", availability.detail)
        if not entry.dbus_activatable:
            # The honest answer, and the one §4.3 asks for by name. The
            # alternatives are all worse: a synthetic Alt-Tab, a pointer click at
            # a guessed coordinate, or a claim of success with nothing behind it.
            return unsupported_outcome(
                "dbus",
                f"{entry.application_id} does not declare DBusActivatable, and there is no "
                "standard way to raise the window of an application that does not. Nothing "
                "was done, and no synthetic input was generated.",
            )
        if window_identity:
            # Accepted by the schema for compositors that can address a window,
            # and unused here because none of the mechanisms this build has can.
            # Recorded rather than silently dropped.
            pass
        if cancellable is not None:
            cancellable.check("before activation was requested")

        running = False
        try:
            running = self._bus.name_has_owner(entry.application_id)
        except DesktopUnavailable:
            running = False
        if not running:
            return unsupported_outcome(
                "dbus",
                f"{entry.application_id} is not running, so there is no window to bring "
                "forward. Presenting does not start an application; launching does, and it is "
                "a separate action with its own approval.",
            )

        info = _app_info(entry)
        from gi.repository import GLib

        try:
            launched = info.launch([], None)
        except GLib.Error as exc:
            return failure("dbus", f"activation of {entry.application_id} failed: {exc.message}")
        if not launched:
            return failure("dbus", f"{entry.application_id} declined activation")
        return _timed(
            acknowledged(
                "dbus",
                detail=(
                    "activation was requested. Whether the window came forward is the "
                    "compositor's decision and is not observable from here; focus-stealing "
                    "prevention was respected and not worked around."
                ),
                applicationId=entry.application_id,
                windowIdentitySupplied=bool(window_identity),
            ),
            started,
        )

    def close(self) -> None:
        self._bus.close()


def _timed(outcome: AdapterOutcome, started: float) -> AdapterOutcome:
    from dataclasses import replace

    return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started))

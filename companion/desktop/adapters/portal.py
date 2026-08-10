# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The xdg-desktop-portal client, and the two things it is honest about.

The portal is the right mechanism for opening things: it is the interface the
desktop itself uses, it applies the user's own default-handler choices, and it
runs outside this process so a hostile URI reaches a program that was going to
open it anyway rather than one we chose.

Two properties of it shape everything here.

**A portal call returns a handle, not an outcome.** ``OpenURI`` replies with the
object path of a ``Request``, and the actual result arrives later as a
``Response`` signal. Waiting for that signal means running a main loop inside a
broker invocation, and a portal dialog a user never answers would hold it for as
long as they leave it open. So the handle *is* the observation: an
acknowledgement, never a confirmation, and
:class:`companion.desktop.result.DesktopActionResult` will not let it be
recorded as anything else.

**A handle is what makes cancellation possible.** §10 asks for portal requests
to be cancelled where supported. Holding the handle is what "where supported"
means in practice — :meth:`PortalAdapter.cancel` calls ``Request.Close``, and
the return value says whether the portal accepted, because a portal that would
not drop a request is a cancellation that did not prevent anything and §10
forbids claiming otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import threading
from typing import Any

from ..errors import DesktopCancelled, DesktopUnavailable
from ..uris import ParsedUri
from .base import Availability
from .dbus import GioCancellable, SessionBus, gio_available

__all__ = ["PORTAL_BUS_NAME", "PortalAdapter", "PortalRequest"]

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"

#: The interface whose presence means "this portal can open things". Read as a
#: property rather than assumed from the bus name being owned: a portal build
#: without the OpenURI backend owns the name and cannot open anything.
_OPEN_URI_INTERFACE = "org.freedesktop.portal.OpenURI"


@dataclass
class PortalRequest:
    """One outstanding portal request, by handle.

    Held so it can be closed. Nothing else about it is kept: §15 forbids a
    portal handle reaching a tool output, and this object never leaves the
    adapter — the broker is given a boolean and a duration.
    """

    handle: str
    action_id: str
    closed: bool = False

    def to_json(self) -> dict[str, Any]:
        # The handle is *not* included. It names an object on the user's session
        # bus, and a record that carries it is a record that can be used to
        # address one.
        return {"actionId": self.action_id, "closed": self.closed, "hasHandle": bool(self.handle)}


class PortalAdapter:
    """Open one URI through xdg-desktop-portal. Nothing else.

    There is no method here that takes an interface, a method name or a bus
    destination. The adapter can open a URI and close a request it made, and
    those are the two things it declares.
    """

    adapter_id = "PortalAdapter"

    def __init__(self, bus: SessionBus | None = None) -> None:
        self._bus = bus if bus is not None else SessionBus()
        self._guard = threading.RLock()
        self._outstanding: dict[str, PortalRequest] = {}

    # -- availability ------------------------------------------------------

    def probe(self) -> Availability:
        """Whether the portal is *answering*, not whether it is installed."""
        if not gio_available():
            return Availability(
                False, mechanism="xdg-desktop-portal", service=PORTAL_BUS_NAME,
                detail="PyGObject is not installed, so this build has no D-Bus transport",
            )
        try:
            if not self._bus.name_has_owner(PORTAL_BUS_NAME):
                return Availability(
                    False, mechanism="xdg-desktop-portal", service=PORTAL_BUS_NAME,
                    detail="no xdg-desktop-portal is running on the session bus",
                )
            self._bus.call(
                "portal.version", (_OPEN_URI_INTERFACE, "version"), timeout_ms=2_000,
            )
        except DesktopUnavailable as exc:
            return Availability(
                False, mechanism="xdg-desktop-portal", service=PORTAL_BUS_NAME, detail=str(exc),
            )
        return Availability(
            True, mechanism="xdg-desktop-portal", service=PORTAL_BUS_NAME,
            detail="the portal answered and offers OpenURI",
        )

    # -- the one operation -------------------------------------------------

    def open_uri(
        self,
        uri: ParsedUri,
        *,
        action_id: str,
        cancellable: GioCancellable | None = None,
        writable: bool = False,
    ) -> PortalRequest:
        """Hand one already-parsed URI to the desktop's handler.

        The parameter is a :class:`~companion.desktop.uris.ParsedUri` rather
        than a string, and that is the type doing security work: a string here
        could be anything, and a ``ParsedUri`` can only have come out of
        :func:`companion.desktop.uris.parse_uri`, which refuses every scheme
        outside the allowlist. There is no way to call this with a
        ``javascript:`` URI because there is no way to *construct the argument*.
        """
        if cancellable is not None:
            cancellable.check("before the portal was asked to open it")
        options: dict[str, Any] = {
            # Ask the portal to ask the user which handler, rather than silently
            # using a default they may not remember choosing. `ask` is the
            # conservative value and costs one click.
            "ask": _variant("b", True),
            # Explicitly not writable. The portal's OpenURI can hand a writable
            # handle to a file; a reveal-and-open action has no business doing
            # that and the option is pinned rather than defaulted.
            "writable": _variant("b", bool(writable)),
        }
        reply = self._bus.call(
            "portal.open_uri",
            ("", uri.normalised, options),
            cancellable=cancellable,
        )
        handle = str(reply[0]) if reply else ""
        request = PortalRequest(handle=handle, action_id=action_id)
        if handle:
            with self._guard:
                self._outstanding[handle] = request
        return request

    def cancel(self, request: PortalRequest) -> bool:
        """Ask the portal to drop a request. Returns whether it accepted.

        A ``False`` is not swallowed anywhere above: it becomes the difference
        between a cancellation that prevented the effect and one that could not,
        which is the distinction §10 is written around.
        """
        if not request.handle or request.closed:
            return False
        accepted = self._bus.close_request(request.handle)
        request.closed = accepted
        with self._guard:
            self._outstanding.pop(request.handle, None)
        return accepted

    def forget(self, request: PortalRequest) -> None:
        """Stop tracking a request that has run its course."""
        with self._guard:
            self._outstanding.pop(request.handle, None)

    @property
    def outstanding(self) -> int:
        """How many handles this adapter still holds.

        §23 counts portal handles across a hundred runs. This is the counter it
        reads, and a run that ends with it non-zero is a leak with a name.
        """
        with self._guard:
            return len(self._outstanding)

    def release_all(self, reason: str = "shutting down") -> tuple[str, ...]:
        """Close every outstanding request. Called on stop and on recovery.

        §20 requires stale portal handles to be cleared after a restart. A
        handle does not survive a restart — the connection it was minted on does
        not — so the *durable* half of that rule is that nothing tries to reuse
        one, and this is the in-process half.
        """
        with self._guard:
            requests = list(self._outstanding.values())
        closed: list[str] = []
        for request in requests:
            if self.cancel(request):
                closed.append(request.action_id)
        return tuple(closed)

    def close(self) -> None:
        self.release_all("closing")
        self._bus.close()


def _variant(signature: str, value: Any) -> Any:
    """A GVariant, or a plain value where Gio is absent.

    The fallback exists so the option dictionaries above can be built and
    inspected by a test on a machine with no PyGObject. A call made with the
    fallback values would fail at :meth:`SessionBus.call`, which is the correct
    place for it to fail.
    """
    if not gio_available():  # pragma: no cover - exercised on development machines
        return value
    from gi.repository import GLib

    return GLib.Variant(signature, value)


def portal_configured() -> bool:
    """Whether a session that could host a portal exists at all.

    Cheap, and used before the bus is touched: a headless run has no
    ``XDG_RUNTIME_DIR`` with a bus in it, and asking the bus about that is
    slower than looking.
    """
    return bool(
        os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        or (os.environ.get("XDG_RUNTIME_DIR") and os.path.exists(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], "bus")
        ))
    )

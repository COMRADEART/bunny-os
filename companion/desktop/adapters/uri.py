# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Open one URI, through the portal, with the handle kept so it can be stopped.

Thin by design. Everything that decides *whether* a URI may be opened happened
in :mod:`companion.desktop.uris` before this adapter was reached, and everything
that decides *where* it goes is the user's own default-handler configuration,
which the portal applies and this build does not read or override.

What is left is the honest reporting, and there are two parts to it:

**A portal handle is an acknowledgement.** The reply says the portal took the
request. Whether a browser opened, whether the user picked a handler from the
chooser, and whether the page loaded are three further questions this build
cannot answer and does not claim to. §4.8's descriptor says so in its
limitations and the result state says so in one word.

**A redirect is out of scope and stays out of scope.** The approval was bound to
:attr:`~companion.desktop.uris.ParsedUri.normalised`, and that string is what was
handed over. A handler that follows a redirect afterwards has gone somewhere
nobody approved, and this adapter has no way to know and no business pretending
it does. Saying that plainly is better than a check that could only ever cover
the redirects we happened to think of.
"""

from __future__ import annotations

import time

from ..errors import DesktopCancelled, DesktopUnavailable
from ..uris import ParsedUri
from .base import AdapterOutcome, Availability, acknowledged, failure
from .dbus import GioCancellable
from .portal import PortalAdapter, PortalRequest

__all__ = ["UriOpenAdapter"]


class UriOpenAdapter:
    """Hand one parsed URI to the desktop. One method, one thing."""

    adapter_id = "UriOpenAdapter"

    def __init__(self, portal: PortalAdapter | None = None) -> None:
        self._portal = portal if portal is not None else PortalAdapter()
        self._last: PortalRequest | None = None

    def probe(self) -> Availability:
        return self._portal.probe()

    def open(
        self,
        uri: ParsedUri,
        *,
        cancellable: GioCancellable | None = None,
    ) -> AdapterOutcome:
        """Open it. The argument's *type* is what makes this safe to call.

        A :class:`~companion.desktop.uris.ParsedUri` can only be produced by
        :func:`companion.desktop.uris.parse_uri`, which refuses every scheme
        outside the four-entry allowlist, every URI carrying credentials, and
        every string with a control character in it. There is no overload here
        that takes a plain string, so the refusals cannot be skipped by calling
        this differently.
        """
        started = time.monotonic()
        availability = self._portal.probe()
        availability.require("desktop.uri.open")
        try:
            request = self._portal.open_uri(
                uri, action_id="desktop.uri.open", cancellable=cancellable, writable=False,
            )
        except DesktopCancelled:
            raise
        except DesktopUnavailable as exc:
            return failure("xdg-desktop-portal", str(exc))
        self._last = request
        outcome = acknowledged(
            "xdg-desktop-portal",
            detail=(
                "the portal accepted the request and returned a handle; whether a handler "
                "opened it is not observable from here"
            ),
            # Recorded as a boolean rather than as the handle: §15 forbids a
            # portal handle reaching a tool output, and a fact about one is not
            # the same as the handle.
            portalRequestOpen=bool(request.handle),
        )
        from dataclasses import replace

        return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started))

    def cancel(self) -> bool:
        """Ask the portal to drop the last request. Returns whether it accepted."""
        if self._last is None:
            return False
        accepted = self._portal.cancel(self._last)
        self._last = None
        return accepted

    def settle(self) -> None:
        """Stop tracking a request that has been reported on."""
        if self._last is not None:
            self._portal.forget(self._last)
            self._last = None

    @property
    def outstanding(self) -> int:
        return self._portal.outstanding

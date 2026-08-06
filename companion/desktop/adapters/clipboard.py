# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Put text on the clipboard without ever finding out what was there.

§13 forbids reading the clipboard, and §4.7 forbids it twice more — never read
the existing clipboard, never return clipboard history. That rules out the
obvious verification (write, read back, compare) and leaves a real question:
what *can* be observed?

The answer is **ownership**, and it comes from how a Wayland or X11 selection
actually works. A selection is not storage; it is a promise by a living process
to produce data when asked. ``wl-copy --foreground`` and ``xclip`` both make
that promise and keep it until they are killed. So:

* the observation is that *our* child is alive after the compositor has had a
  moment to take the offer. That is a genuine ``ownership`` observation and it
  is the only thing in this adapter that may produce ``confirmed``;
* nothing is read. Not the contents, not the previous contents, not the offered
  MIME types. The check is on a process we started, using a handle we hold;
* **release is a real operation**, which is what makes §4.7's "clear temporary
  clipboard ownership on cancellation" and §10's equivalent implementable at
  all. Killing the child drops the selection.

Release is honest about what it does not do. Dropping the selection does not
restore what was on the clipboard before — nobody read it, so nobody could put
it back. That is why §11 classifies a clipboard write as **compensatable** and
not reversible, and why the descriptor's limitations say so in a sentence a user
can read.

The text goes down **stdin**, never into an argument vector. An argv is readable
in ``/proc`` by every process the user runs, and this is the one adapter whose
argument would be the user's own material.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from ..errors import DesktopCancelled
from .base import AdapterOutcome, Availability, failure, unsupported_outcome, verified
from .command import BackgroundChild, have

__all__ = ["ClipboardAdapter", "ClipboardHold"]

#: The MIME type every write declares. Fixed: a caller-chosen type would let a
#: task offer ``text/html`` or an image type, and what a pasting application
#: does with those is a much larger surface than plain text.
_MIME_TYPE = "text/plain;charset=utf-8"


class ClipboardHold:
    """One clipboard ownership this build holds, and the way to give it up."""

    def __init__(self, child: BackgroundChild, *, mechanism: str, taken_at: float) -> None:
        self._child = child
        self.mechanism = mechanism
        self.taken_at = taken_at

    @property
    def held(self) -> bool:
        return not self._child.released

    @property
    def pid(self) -> int:
        return self._child.pid

    def release(self, reason: str = "released") -> bool:
        """Drop the selection. Returns whether this call was the one that did."""
        return self._child.release(reason)

    def to_json(self) -> dict[str, Any]:
        return {"mechanism": self.mechanism, "held": self.held}


class ClipboardAdapter:
    """Take the clipboard with given text; release it. Two operations, no read."""

    adapter_id = "ClipboardAdapter"

    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._holds: list[ClipboardHold] = []

    # -- availability ------------------------------------------------------

    def probe(self) -> Availability:
        if os.environ.get("WAYLAND_DISPLAY"):
            if have("wl-copy"):
                return Availability(
                    True, mechanism="wl-copy", service="wayland-selection",
                    detail="a Wayland session with wl-clipboard installed",
                )
            return Availability(
                False, mechanism="wl-copy", service="wayland-selection",
                detail="this is a Wayland session and wl-clipboard is not installed",
            )
        if os.environ.get("DISPLAY"):
            if have("xclip"):
                return Availability(
                    True, mechanism="xclip", service="x11-selection",
                    detail="an X11 session with xclip installed",
                )
            return Availability(
                False, mechanism="xclip", service="x11-selection",
                detail="this is an X11 session and xclip is not installed",
            )
        return Availability(
            False, mechanism="", service="selection",
            detail="there is no graphical session, so there is no clipboard to take",
        )

    # -- taking ------------------------------------------------------------

    def copy(self, text: str, *, cancellable: Any = None) -> tuple[AdapterOutcome, ClipboardHold | None]:
        """Take the clipboard with ``text``. Returns the outcome and the hold.

        The hold is returned separately rather than put inside the outcome
        because an :class:`~companion.desktop.adapters.base.AdapterOutcome` has
        no field for a live resource, deliberately: §15 forbids a backend object
        reaching a tool output, and the cheapest way to keep that true is for
        there to be nowhere to put one.
        """
        started = time.monotonic()
        availability = self.probe()
        if not availability.available:
            return unsupported_outcome("", availability.detail), None
        if cancellable is not None:
            cancellable.check("before the clipboard was taken")

        if availability.mechanism == "wl-copy":
            # `--foreground` is what makes this ownership rather than a fire-and-
            # forget: without it wl-copy daemonises and this build has no handle
            # to release. `--type` pins the offer to plain text.
            child = BackgroundChild(
                "wl-copy", ["--foreground", "--type", _MIME_TYPE], stdin_text=text
            )
        else:
            # xclip reads until EOF and then holds the selection in the
            # foreground; `-selection clipboard` is the one users mean by
            # "clipboard" as opposed to the X11 primary selection, which is
            # deliberately not touched.
            child = BackgroundChild(
                "xclip", ["-selection", "clipboard", "-t", "text/plain"], stdin_text=text
            )

        try:
            child.start()
        except Exception as exc:  # a missing binary, a permission problem
            return failure(availability.mechanism, str(exc)), None

        holding = child.holding()
        hold = ClipboardHold(child, mechanism=availability.mechanism, taken_at=time.monotonic())
        if not holding:
            detail = child.stderr_text() or "the clipboard helper exited immediately"
            child.release("did not take the selection")
            return failure(availability.mechanism, detail), None

        with self._guard:
            self._holds.append(hold)

        from dataclasses import replace

        outcome = verified(
            availability.mechanism,
            kind="ownership",
            detail=(
                "the clipboard selection is held by a process this build started and can "
                "release; the previous contents were not read and the new contents were not "
                "read back"
            ),
            matched=True,
            observed_value=None,
        )
        return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started)), hold

    # -- releasing ---------------------------------------------------------

    def release(self, hold: ClipboardHold, reason: str = "released") -> bool:
        released = hold.release(reason)
        with self._guard:
            if hold in self._holds:
                self._holds.remove(hold)
        return released

    def release_all(self, reason: str = "shutting down") -> int:
        """Drop every selection this build holds. Returns how many were dropped.

        Called on cancellation, on shutdown and during recovery. §20 requires a
        restarted runtime to release temporary clipboard ownership, and the
        durable half of that is trivially satisfied — a selection belongs to a
        process, and a process that stopped is not holding anything. This is the
        in-process half.
        """
        with self._guard:
            holds = list(self._holds)
            self._holds.clear()
        return sum(1 for item in holds if item.release(reason))

    @property
    def outstanding(self) -> int:
        """How many selections this build currently holds.

        §23 counts clipboard owners across a hundred runs, and this is the
        counter it reads.
        """
        with self._guard:
            return sum(1 for item in self._holds if item.held)

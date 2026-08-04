# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Two clocks, because the runtime needs two different things from time.

**Wall time** answers "when did this happen" for a person reading a history. It
is written into every event. It is also unreliable: it jumps when NTP corrects
it, it goes backwards across a suspend, and a user can set it to anything.

**Monotonic time** answers "has this expired". It never goes backwards and it
has no relationship to any calendar. Deadlines, timeouts and approval expiry are
all measured on it, and none of them may be measured on wall time — an approval
whose expiry was checked against a wall clock could be extended by an hour by
changing the timezone, which is a consent bypass with a settings dialog.

Monotonic time also does not survive a restart: after a reboot the counter
starts again from an arbitrary origin, so a monotonic deadline recorded before
the crash is meaningless afterwards. :mod:`companion.recovery` relies on that
rather than working around it — an approval whose expiry cannot be evaluated is
treated as expired, which is the safe direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Protocol

__all__ = ["Clock", "FrozenClock", "SystemClock", "iso8601"]


def iso8601(epoch_seconds: float) -> str:
    """A UTC timestamp with second resolution and an explicit ``Z``.

    Seconds rather than microseconds: an event history is read by people, and
    sub-second precision in a record whose ordering is already carried by an
    explicit sequence number is noise that also happens to fingerprint the
    machine's scheduling.
    """
    moment = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Clock(Protocol):
    """The runtime's only source of time."""

    def wall(self) -> float:
        """Seconds since the Unix epoch. May jump; never used for expiry."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin. Never jumps; used for every deadline."""


@dataclass(frozen=True)
class SystemClock:
    """The real clocks."""

    def wall(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class FrozenClock:
    """A clock a test drives by hand.

    Both hands move together through :meth:`advance` and can be moved apart
    deliberately, which is how the tests for wall-clock jumps and for monotonic
    expiry are written without either one waiting on the other.
    """

    #: 2026-01-01T00:00:00Z. A fixed, obviously synthetic origin so that a
    #: transcript produced by a test cannot be mistaken for one from a machine.
    wall_seconds: float = 1767225600.0
    monotonic_seconds: float = 1000.0
    _wall_offset: float = field(default=0.0, repr=False)

    def wall(self) -> float:
        return self.wall_seconds + self._wall_offset

    def monotonic(self) -> float:
        return self.monotonic_seconds

    def advance(self, seconds: float) -> None:
        """Move both clocks forward, as ordinary elapsed time does."""
        self.wall_seconds += seconds
        self.monotonic_seconds += seconds

    def jump_wall(self, seconds: float) -> None:
        """Move only the wall clock, as an NTP correction or a user does."""
        self._wall_offset += seconds

    def restart(self, *, monotonic_origin: float = 1.0) -> None:
        """Model a reboot: the monotonic counter restarts, wall time does not."""
        self.monotonic_seconds = monotonic_origin

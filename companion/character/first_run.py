# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The companion's first hello, exactly once, and short.

§5 wants a first-run experience that is polished and brief, and warns against
turning setup into a tutorial maze. So this is deliberately the smallest thing
that satisfies it: the companion greets on the first login and then never again,
the greeting is a handful of seconds, and nothing waits for it.

Three decisions are worth stating, because each has an obvious alternative that
is worse.

**The marker is written when the greeting starts, not when it finishes.** A
crash during the greeting then costs that user their greeting, which is a
disappointment. Writing it at the end instead means a machine that crashes
during start-up greets on *every* boot, which is a broken operating system. The
failure modes are not symmetric and this picks the smaller one.

**The greeting is timed, not acknowledged.** There is no "continue" button and
nothing blocks on it. §5's flow has the desktop arriving after the greeting, and
a greeting that could be *missed* — by a user who looked away, or by an
automated first boot — must not be able to hold the session behind it.

**It yields to anything that matters.** :meth:`FirstRunGreeting.active` is only
ever consulted to set a flag the mapper is free to ignore, and the mapper ranks
``greeting`` below every state that needs an answer. A first boot that opens
with a permission request shows the permission request; the greeting is not
important enough to sit in front of one and it does not get to try.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

__all__ = ["GREETING_FILE_NAME", "GREETING_SECONDS", "FirstRunGreeting"]

#: Beside the character registry, not in ``settings.json``. This is a *fact
#: about what has happened on this machine* rather than a preference, and a user
#: who resets their settings should not be greeted again as a side effect.
GREETING_FILE_NAME = "first-run-greeting.json"

#: How long the greeting shows. Short enough not to delay anybody, long enough
#: to read as deliberate rather than as a flicker.
GREETING_SECONDS = 4.0

_SCHEMA_VERSION = 1


@dataclass
class FirstRunGreeting:
    """Whether to greet, and for how much longer."""

    root: Path
    seconds: float = GREETING_SECONDS
    started_at: float | None = None

    @property
    def path(self) -> Path:
        return Path(self.root) / GREETING_FILE_NAME

    def already_greeted(self) -> bool:
        """Whether this machine has greeted before. Never raises.

        An unreadable marker counts as *greeted*. That is the conservative
        direction: the cost of wrongly skipping a greeting is one missed
        animation, and the cost of wrongly repeating it is a companion that
        introduces itself every single login.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return True
        return isinstance(value, dict) and bool(value.get("greeted"))

    def should_greet(self) -> bool:
        return not self.already_greeted()

    def begin(self, *, now: float) -> bool:
        """Start the greeting if it is owed. Returns whether it started."""
        if self.started_at is not None:
            return False
        if not self.should_greet():
            return False
        self.started_at = now
        self._record()
        return True

    def active(self, *, now: float) -> bool:
        """Whether the greeting is still showing."""
        if self.started_at is None:
            return False
        if now - self.started_at >= self.seconds:
            self.started_at = None
            return False
        return True

    def finish(self) -> None:
        """End the greeting early — a user who started talking, for instance."""
        self.started_at = None

    def _record(self) -> None:
        """Write the marker atomically. A failure is not worth refusing over."""
        payload = json.dumps(
            {"schemaVersion": _SCHEMA_VERSION, "greeted": True}, sort_keys=True
        ) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".first-run-", dir=self.path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        except OSError:
            # The greeting still happens; it may happen again next boot. That is
            # better than refusing to open the companion because a marker file
            # could not be written.
            pass

    def to_json(self) -> dict[str, Any]:
        return {
            "greetingOwed": self.should_greet(),
            "greetingActive": self.started_at is not None,
            "seconds": self.seconds,
        }

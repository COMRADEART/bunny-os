# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Open a settings page, and read or set do-not-disturb.

Two operations in one adapter because they touch the same thing — the desktop's
own settings — and because keeping them together makes one property obvious: this
adapter **opens** a settings page and **never changes a setting on it**. §4.4
says so, and the code says so by having no method that takes a key and a value.

Do-not-disturb is the exception, and it is a declared action of its own with its
own approval, not a setting reachable through the page opener. It is here because
it lives in the same store.

**The page allowlist is a mapping, not a pass-through.** A page identifier from
:data:`companion.desktop.parameters.SETTINGS_PAGES` is translated into whatever
the running desktop calls it. That translation is the reason an unmapped page on
an unrecognised desktop reports ``UNSUPPORTED`` rather than opening something
approximate: "accessibility" is ``universal-access`` on GNOME and
``kcm_access`` on KDE, and a build that passed the word through would open
nothing on both while reporting success.

**Do-not-disturb is verified by read-back.** It is one of the three actions in
this catalogue that can reach ``confirmed``, and the read is the same ``gsettings
get`` a user would run. An environment where the value cannot be read before the
change offers no undo: §11 forbids claiming reversibility whose previous state
was never captured.
"""

from __future__ import annotations

import os
import time
from typing import Any, Mapping

from ..errors import DesktopCancelled, DesktopUnavailable
from .base import (
    AdapterOutcome,
    Availability,
    acknowledged,
    failure,
    unsupported_outcome,
    verified,
)
from .command import capture_command, have, run_command

__all__ = ["DESKTOP_ENVIRONMENTS", "SettingsAdapter", "current_desktop"]

#: The environments this adapter has a mapping for. Anything else is
#: ``UNSUPPORTED``, by name, with the environment quoted in the explanation.
DESKTOP_ENVIRONMENTS = ("GNOME", "KDE")

#: §4.4's identifiers to GNOME's panel names.
_GNOME_PANELS: Mapping[str, str] = {
    "accessibility": "universal-access",
    "display": "display",
    "keyboard": "keyboard",
    "network": "network",
    "notifications": "notifications",
    "power": "power",
    "privacy": "privacy",
    "sound": "sound",
}

#: …and to KDE's modules.
_KDE_MODULES: Mapping[str, str] = {
    "accessibility": "kcm_access",
    "display": "kcm_kscreen",
    "keyboard": "kcm_keyboard",
    "network": "kcm_networkmanagement",
    "notifications": "kcm_notifications",
    "power": "kcm_powerdevilprofilesconfig",
    "privacy": "kcm_privacy",
    "sound": "kcm_pulseaudio",
}

#: GNOME keeps do-not-disturb as the *inverse* of "show banners". The inversion
#: is written once, here, because a second copy of it somewhere would eventually
#: turn do-not-disturb on when a user asked for it off.
_GNOME_DND_SCHEMA = "org.gnome.desktop.notifications"
_GNOME_DND_KEY = "show-banners"


def current_desktop() -> str:
    """The desktop environment, uppercased, or an empty string.

    ``XDG_CURRENT_DESKTOP`` can hold a colon-separated list — ``ubuntu:GNOME``
    is ordinary — so the first entry this build recognises wins rather than the
    first entry present.
    """
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "").strip()
    for part in raw.split(":"):
        upper = part.strip().upper()
        for known in DESKTOP_ENVIRONMENTS:
            if known in upper:
                return known
    return raw.split(":")[0].strip().upper() if raw else ""


class SettingsAdapter:
    """Open one allowlisted settings page; read and set do-not-disturb."""

    adapter_id = "SettingsAdapter"

    def __init__(self, desktop: str = "") -> None:
        self._desktop = desktop or current_desktop()

    @property
    def desktop(self) -> str:
        return self._desktop

    # -- availability ------------------------------------------------------

    def probe(self) -> Availability:
        if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
            return Availability(
                False, mechanism="", service="settings",
                detail="there is no graphical session, so no settings window could appear",
            )
        if self._desktop == "GNOME" and have("gnome-control-center"):
            return Availability(
                True, mechanism="gnome-control-center", service="gnome-control-center",
                detail="GNOME Settings is installed",
            )
        if self._desktop == "KDE" and (have("systemsettings") or have("systemsettings5")):
            return Availability(
                True, mechanism="systemsettings", service="systemsettings",
                detail="KDE System Settings is installed",
            )
        return Availability(
            False, mechanism="", service="settings",
            detail=(
                f"this build has no settings mapping for {self._desktop or 'an unnamed desktop'}; "
                f"it knows {', '.join(DESKTOP_ENVIRONMENTS)}"
            ),
        )

    def probe_do_not_disturb(self) -> Availability:
        if self._desktop != "GNOME":
            return Availability(
                False, mechanism="gsettings", service=_GNOME_DND_SCHEMA,
                detail=(
                    f"{self._desktop or 'this desktop'} does not keep do-not-disturb where this "
                    "build can read it; the action is unsupported here rather than guessed at"
                ),
            )
        if not have("gsettings"):
            return Availability(
                False, mechanism="gsettings", service=_GNOME_DND_SCHEMA,
                detail="gsettings is not installed, so the value can be neither read nor set",
            )
        if self.read_do_not_disturb() is None:
            return Availability(
                False, mechanism="gsettings", service=_GNOME_DND_SCHEMA,
                detail=f"the {_GNOME_DND_SCHEMA} schema is not installed on this system",
            )
        return Availability(
            True, mechanism="gsettings", service=_GNOME_DND_SCHEMA,
            detail="the do-not-disturb value can be read and set",
        )

    # -- settings pages ----------------------------------------------------

    def open_page(self, page: str, *, cancellable: Any = None) -> AdapterOutcome:
        """Open the named page. Never changes anything on it."""
        started = time.monotonic()
        availability = self.probe()
        if not availability.available:
            return unsupported_outcome("", availability.detail)
        if cancellable is not None:
            cancellable.check("before the settings window was opened")

        if self._desktop == "GNOME":
            panel = _GNOME_PANELS.get(page)
            if panel is None:
                return unsupported_outcome(
                    "gnome-control-center", f"GNOME has no page this build maps {page!r} to"
                )
            program, arguments = "gnome-control-center", [panel]
        else:
            module = _KDE_MODULES.get(page)
            if module is None:
                return unsupported_outcome(
                    "systemsettings", f"KDE has no module this build maps {page!r} to"
                )
            program = "systemsettings" if have("systemsettings") else "systemsettings5"
            arguments = [module]

        # The settings program keeps running once opened, so this is started and
        # not waited for: a short timeout that reaps it would close the window
        # the user was just shown. `run_command`'s timeout is the *start*
        # window, and the program is expected to outlive it.
        outcome = run_command(program, arguments, timeout_seconds=2.0)
        if outcome.start_error:
            return failure(program, outcome.start_error)
        if outcome.exit_code not in (None, 0) and not outcome.timed_out:
            return failure(program, outcome.stderr or f"{program} exited {outcome.exit_code}")
        return _timed(
            acknowledged(
                program,
                detail=(
                    f"{program} was started for the {page} page; whether it drew a window is "
                    "not observable from here"
                ),
                page=page,
            ),
            started,
        )

    # -- do-not-disturb ----------------------------------------------------

    def read_do_not_disturb(self) -> bool | None:
        """The current value, or ``None`` when it cannot be read.

        ``None`` is not ``False``. A caller that treated them as the same would
        turn "we could not tell" into "notifications are on", and then offer an
        undo that restores a state nobody observed.
        """
        if self._desktop != "GNOME" or not have("gsettings"):
            return None
        value = _gsettings_value(_GNOME_DND_SCHEMA, _GNOME_DND_KEY)
        if value not in ("true", "false"):
            # Neither value, nor a value this build understands. `None` rather
            # than a default: see the docstring — the two are not the same and
            # treating them alike produces an undo to a state nobody observed.
            return None
        # do-not-disturb is banners *off*. The inversion lives here and nowhere
        # else; see the constant's comment.
        return value == "false"

    def set_do_not_disturb(self, enabled: bool, *, cancellable: Any = None) -> AdapterOutcome:
        """Set it, then read it back. One of three actions that can be confirmed."""
        started = time.monotonic()
        availability = self.probe_do_not_disturb()
        if not availability.available:
            return unsupported_outcome("gsettings", availability.detail)
        if cancellable is not None:
            cancellable.check("before do-not-disturb was changed")

        previous = self.read_do_not_disturb()
        banners = "false" if enabled else "true"
        outcome = run_command(
            "gsettings", ["set", _GNOME_DND_SCHEMA, _GNOME_DND_KEY, banners], timeout_seconds=5.0
        )
        if outcome.cancelled:
            raise DesktopCancelled(
                "do-not-disturb was cancelled while gsettings was running",
                effect_known=False, effect_prevented=False,
            )
        if not outcome.succeeded:
            return failure("gsettings", outcome.stderr or f"gsettings exited {outcome.exit_code}")

        observed = self.read_do_not_disturb()
        return _timed(
            verified(
                "gsettings",
                detail="the do-not-disturb value was read back after the change",
                matched=observed is not None and observed == enabled,
                observed_value=observed,
                previousEnabled=previous,
            ),
            started,
        )


def _gsettings_value(schema: str, key: str) -> str | None:
    """One ``gsettings get``, with its stdout."""
    captured = capture_command("gsettings", ["get", schema, key], timeout_seconds=5.0)
    return None if captured is None else captured.strip()


def _timed(outcome: AdapterOutcome, started: float) -> AdapterOutcome:
    from dataclasses import replace

    return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started))

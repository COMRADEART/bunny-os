# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The display the companion was started too early to be told about.

`bunny-companion.service` was ordered after `graphical-session-pre.target`, so
it started while the session was coming up — two seconds before gnome-session
imported `WAYLAND_DISPLAY`. It spent the whole session with
`XDG_SESSION_TYPE=wayland` and no display variable, and every adapter that asks
for one refused:

    there is no graphical session, so a launched application would have
    nowhere to appear

A spoken "Open Files" was transcribed, routed, approved and answered with that
sentence, on a machine with a desktop plainly on screen.

It hid for a long time because *restarting* the service picks the variables up.
Every development iteration restarts it. So the fault only appears on a machine
that has been booted and left alone, which is every user's machine and no
developer's.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from companion.desktop.environment import (
    adopt_graphical_environment,
    session_type,
)

#: The adapters ask `os.environ` for a display directly; `session_type()` falls
#: back to the session manager's *claim* (`XDG_SESSION_TYPE`) when neither
#: variable is set, and that claim was `wayland` on the machine that could not
#: launch anything. So the property under test is the one the adapters use.
def has_a_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


#: AF_UNIX exists on Linux, which is where this service runs and where the
#: gate is measured. The socket cases cannot be expressed without it.
UNIX_SOCKETS = unittest.skipUnless(
    hasattr(socket, "AF_UNIX"), "AF_UNIX is unavailable on this host")

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "systemd/user/bunny-companion.service"
SERVICE = ROOT / "services/bunny-companion/bunny_companion_service.py"

#: What the service's own environment looked like on the guest that failed.
STARTED_TOO_EARLY = {"XDG_SESSION_TYPE": "wayland", "XDG_RUNTIME_DIR": ""}


class AdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)

    def _socket(self, name: str) -> None:
        """A real AF_UNIX socket, because the check is `S_ISSOCK`."""
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(os.path.join(self.runtime.name, name))

    def _environment(self, **extra: str) -> dict:
        return {**STARTED_TOO_EARLY, "XDG_RUNTIME_DIR": self.runtime.name, **extra}

    @UNIX_SOCKETS
    def test_the_display_is_adopted_from_the_runtime_socket(self) -> None:
        self._socket("wayland-0")
        with mock.patch.dict(os.environ, self._environment(), clear=True):
            self.assertFalse(has_a_display(), "the precondition is a session with no display")
            adopted = adopt_graphical_environment()
            self.assertEqual(adopted, {"WAYLAND_DISPLAY": "wayland-0"})
            self.assertEqual(os.environ["WAYLAND_DISPLAY"], "wayland-0")
            self.assertEqual(session_type(), "wayland")
            self.assertTrue(has_a_display())

    def test_a_lock_file_is_not_a_display(self) -> None:
        Path(self.runtime.name, "wayland-0.lock").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, self._environment(), clear=True):
            self.assertEqual(adopt_graphical_environment(), {})
            self.assertNotIn("WAYLAND_DISPLAY", os.environ)

    def test_an_ordinary_file_named_like_a_socket_is_not_a_display(self) -> None:
        Path(self.runtime.name, "wayland-1").write_text("not a socket", encoding="utf-8")
        with mock.patch.dict(os.environ, self._environment(), clear=True):
            self.assertEqual(adopt_graphical_environment(), {})

    def test_nothing_is_invented_when_there_is_no_socket(self) -> None:
        with mock.patch.dict(os.environ, self._environment(), clear=True):
            self.assertEqual(adopt_graphical_environment(), {})
            self.assertFalse(has_a_display(), "nothing may be invented")

    @UNIX_SOCKETS
    def test_an_existing_display_is_never_overwritten(self) -> None:
        self._socket("wayland-9")
        for existing in ({"WAYLAND_DISPLAY": "wayland-3"}, {"DISPLAY": ":7"}):
            with self.subTest(existing=existing):
                with mock.patch.dict(os.environ, self._environment(**existing), clear=True):
                    self.assertEqual(adopt_graphical_environment(), {})
                    for key, value in existing.items():
                        self.assertEqual(os.environ[key], value)

    @UNIX_SOCKETS
    def test_it_is_idempotent(self) -> None:
        self._socket("wayland-0")
        with mock.patch.dict(os.environ, self._environment(), clear=True):
            self.assertEqual(adopt_graphical_environment(), {"WAYLAND_DISPLAY": "wayland-0"})
            self.assertEqual(adopt_graphical_environment(), {})

    def test_a_missing_runtime_directory_is_not_an_error(self) -> None:
        with mock.patch.dict(
            os.environ, {**STARTED_TOO_EARLY, "XDG_RUNTIME_DIR": "/nonexistent"}, clear=True
        ):
            self.assertEqual(adopt_graphical_environment(), {})


class OrderingTests(unittest.TestCase):
    """The ordering fix, which is the half that stops the race happening."""

    def test_the_unit_is_ordered_after_the_session_target(self) -> None:
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn("After=graphical-session.target", text)
        self.assertNotIn(
            "After=graphical-session-pre.target", text,
            "ordering after -pre starts the service before the display exists")

    def test_the_service_adopts_before_it_probes_anything(self) -> None:
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("adopt_graphical_environment()", text)
        self.assertLess(
            text.index("adopt_graphical_environment()"),
            text.index("CompanionService(_options()).start()"),
            "the display has to be adopted before the service probes the desktop")


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The GTK initialization boundary: what :func:`setup._gtk` promises its callers.

``tests/installer`` learned on Fedora 44 that importing Gtk is not the same as
being able to draw with it. PyGObject auto-initialises at import and swallows
the answer, GTK 4 reports itself initialised even where no display exists, and
the first widget construction then killed the interpreter inside libgtk-4
(segfault; the suite exited 245 with every test up to that point green).

These tests pin the contract that closed that hole:

* ``_gtk()`` hands back Gtk only after the library is initialised *and* a
  display answers — otherwise it refuses with ``SetupDisplayUnavailable``;
* the refusal happens before any widget construction, for every caller,
  including ``--self-check``, which draws real widgets without ever entering
  ``Gtk.Application.run()``;
* when a display does answer, the real rendering path still runs against it,
  and the GUI wires its ``Gtk.Application`` exactly as before.

The refusal cases are simulated by replacing attributes on the GI module
objects, which allow that, so they are deterministic everywhere including a
display-less CI host. Nothing catches signals or pokes at the crash itself:
the boundary simply makes widget construction unreachable on a machine that
cannot draw.
"""

from __future__ import annotations

import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.frontend import setup                            # noqa: E402
from installer.frontend.setup import SetupApplication           # noqa: E402
from installer.frontend.setup import SetupDisplayUnavailable    # noqa: E402


def _gi_or_skip():
    """The live Gtk/Gdk modules, or SkipTest where the bindings are absent."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gtk
        return Gtk, Gdk
    except Exception as error:
        raise unittest.SkipTest(f"GTK4 bindings are not available: {error}")


class _NoDisplay:
    """A Gdk.Display stand-in answering like a machine nobody can draw on."""

    @staticmethod
    def get_default():
        return None

    @staticmethod
    def open(name):
        raise RuntimeError(f"no windowing system answers for {name!r}")


class TheBoundaryRefusesCleanly(unittest.TestCase):
    """No usable windowing system means an exception, never widgets."""

    def test_a_displayless_host_is_refused_with_the_boundary_exception(self):
        Gtk, Gdk = _gi_or_skip()
        # initialised=True isolates the display half of the contract; the
        # init-failed half is refused by the same exception one branch above.
        # Patching Display makes the case deterministic even where DISPLAY is
        # set: the environment cannot reach in past the replacement.
        with mock.patch.object(Gtk, "is_initialized", lambda: True), \
                mock.patch.object(Gdk, "Display", _NoDisplay):
            with self.assertRaises(SetupDisplayUnavailable):
                setup._gtk()

    def test_failed_initialisation_refuses_before_any_display_is_asked(self):
        Gtk, Gdk = _gi_or_skip()
        asked = []

        def record_default():
            asked.append("get_default")
            return None

        display = type("AskedDisplay", (), {
            "get_default": staticmethod(record_default),
            "open": staticmethod(lambda name: None),
        })
        with mock.patch.object(Gtk, "is_initialized", lambda: False), \
                mock.patch.object(Gtk, "init_check", lambda: False), \
                mock.patch.object(Gdk, "Display", display):
            with self.assertRaises(SetupDisplayUnavailable):
                setup._gtk()
        self.assertEqual(asked, [],
                         "a failed initialisation still reached for a display")

    def test_the_test_fixture_converts_a_refusal_into_a_skip(self):
        """_gtk_or_skip is the fixture side of the same contract."""
        from tests.installer.test_setup_flow import _gtk_or_skip

        with mock.patch.object(setup, "_gtk",
                               side_effect=SetupDisplayUnavailable("no display")):
            with self.assertRaises(unittest.SkipTest):
                _gtk_or_skip()


class WhenADisplayAnswers(unittest.TestCase):
    """The other half: a usable environment must reach the real widgets."""

    def setUp(self):
        try:
            self.Gtk = setup._gtk()
        except SetupDisplayUnavailable as error:
            raise unittest.SkipTest(
                f"this host cannot draw; the live path needs a display: {error}")
        except ImportError as error:
            raise unittest.SkipTest(f"GTK4 bindings are not available: {error}")

    def test_the_boundary_hands_back_an_initialised_module_with_a_display(self):
        from gi.repository import Gdk

        self.assertTrue(self.Gtk.is_initialized())
        self.assertIsNotNone(Gdk.Display.get_default())

    def test_the_companion_toggle_still_drives_a_real_render(self):
        """The exact sequence that segfaulted before the boundary existed."""
        application = SetupApplication(self.Gtk)
        application.window = None
        application.on_change("mode", "compact")
        application.on_change("companionTextOnly", True)
        self.assertEqual(application.choices.companion_mode, "text-only")
        application.on_change("companionTextOnly", False)
        self.assertEqual(application.choices.companion_mode, "compact")
        # The toggle re-render built the real widget tree both times.
        self.assertIsNotNone(application.companion)
        self.assertIsNotNone(application.view)


class NormalGuiInitialisationIsUnchanged(unittest.TestCase):
    """run() must wire the same Gtk.Application it always did."""

    def _stub(self, recorded, exit_code=7):
        class StubApplication:
            def __init__(self, application_id):
                recorded["application_id"] = application_id

            def connect(self, signal, handler):
                recorded.setdefault("connections", []).append((signal, handler))

            def run(self, argv):
                recorded["ran_with"] = argv
                return exit_code

        return type("StubGtk", (), {"Application": StubApplication})

    def test_gui_run_wires_the_application_id_and_activate_exactly_as_before(self):
        recorded = {}
        with mock.patch.object(setup, "_gtk",
                               return_value=self._stub(recorded, exit_code=7)):
            self.assertEqual(setup.run(["--offline"]), 7)

        self.assertEqual(recorded["application_id"], "art.comrade.BunnySetup")
        [(signal, handler)] = recorded["connections"]
        self.assertEqual(signal, "activate")
        self.assertEqual(getattr(handler, "__name__"), "build")
        self.assertIsInstance(handler.__self__, SetupApplication)
        self.assertIsNone(recorded["ran_with"])

    def test_gui_run_still_builds_its_context_from_real_choices(self):
        recorded = {}
        probed = {}

        def fake_context(choices):
            probed["choices_type"] = type(choices).__name__
            return {}

        with mock.patch.object(setup, "_gtk",
                               return_value=self._stub(recorded, exit_code=0)), \
                mock.patch.object(setup, "_installer_context", fake_context):
            self.assertEqual(setup.run([]), 0)
        self.assertEqual(probed["choices_type"], "Choices")


class SelfCheckHasTheSameBoundary(unittest.TestCase):
    """``--self-check`` draws real widgets before any Application.run()."""

    def test_a_refused_boundary_stops_self_check_before_any_widget_exists(self):
        constructed = []

        def booby_trap(*args, **kwargs):
            constructed.append((args, kwargs))
            raise AssertionError("widget construction past a refused boundary")

        stderr = StringIO()
        with mock.patch.object(setup, "_gtk",
                               side_effect=SetupDisplayUnavailable("no display")), \
                mock.patch.object(setup, "_ScreenView", booby_trap), \
                mock.patch.object(setup, "_CompanionView", booby_trap), \
                mock.patch.object(sys, "stderr", stderr):
            exit_code = setup.run(["--self-check", "--offline"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(constructed, [],
                         "self-check built widgets after the boundary refused")
        self.assertIn("display", stderr.getvalue())

    def test_self_check_runs_only_after_the_boundary_answers(self):
        order = []
        state = mock.MagicMock()
        # run() serialises whatever self_check() reports as JSON.
        state.self_check.return_value = {}
        captured = []

        def fake_gtk():
            order.append("boundary")
            return object()

        def fake_setup(Gtk, *, choices=None, context=None):
            order.append("application")
            return state

        with mock.patch.object(setup, "_gtk", side_effect=fake_gtk), \
                mock.patch.object(setup, "SetupApplication", fake_setup), \
                mock.patch.object(sys, "stdout", StringIO()) as stdout:
            exit_code = setup.run(["--self-check", "--offline"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(order, ["boundary", "application"],
                         "self-check did not pass the boundary first")
        state.self_check.assert_called_once_with()
        self.assertEqual(stdout.getvalue().strip(), "{}")


if __name__ == "__main__":
    unittest.main()

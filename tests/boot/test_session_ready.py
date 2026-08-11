# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The readiness probe, checked where it can be checked.

Every graphical harness in this repository has at some point waited a fixed
number of seconds and photographed whatever was there — which is how a
screenshot of GDM and a screenshot of a blanked screen both got recorded as
"the desktop". The probe exists so that readiness is a conjunction of measured
conditions instead of a guess that happened to be right on one machine.

These tests cannot make a graphical session exist. What they *can* assert is
everything that would make the probe lie: a check that vanished, a check that
passes when it raised, a marker a partial line could manufacture, and a
conjunction that is really a disjunction.
"""

from __future__ import annotations

import importlib.util
import json
import unittest

from tests.support import ROOT

PROBE = ROOT / "scripts" / "bunny-session-ready.py"


def _load():
    specification = importlib.util.spec_from_file_location("bunny_session_ready", PROBE)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class TheProbeIsAConjunction(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()

    def test_every_condition_the_brief_names_is_checked(self) -> None:
        """§13's list. A condition dropped from here is a condition nobody
        checks, and the probe would still say ready."""
        for name in ("session", "compositor", "shell", "companion",
                     "client", "trust", "capsules", "tasks"):
            with self.subTest(condition=name):
                self.assertIn(name, self.module.CHECKS)

    def test_one_false_check_makes_the_whole_thing_not_ready(self) -> None:
        original = dict(self.module.CHECKS)
        self.addCleanup(lambda: self.module.CHECKS.update(original))
        for name in list(self.module.CHECKS):
            with self.subTest(failing=name):
                self.module.CHECKS.clear()
                self.module.CHECKS.update(
                    {key: (lambda: {"ok": True}) for key in original}
                )
                self.module.CHECKS[name] = lambda: {"ok": False}
                report = self.module.evaluate()
                self.assertFalse(report["ready"])
                self.assertEqual(report["notReady"], [name])

    def test_all_true_is_ready(self) -> None:
        """The positive control. A probe that never says ready is not a probe."""
        original = dict(self.module.CHECKS)
        self.addCleanup(lambda: (self.module.CHECKS.clear(),
                                 self.module.CHECKS.update(original)))
        self.module.CHECKS.clear()
        self.module.CHECKS.update({key: (lambda: {"ok": True}) for key in original})
        self.assertTrue(self.module.evaluate()["ready"])

    def test_a_check_that_raises_is_not_a_pass(self) -> None:
        original = dict(self.module.CHECKS)
        self.addCleanup(lambda: (self.module.CHECKS.clear(),
                                 self.module.CHECKS.update(original)))

        def explode():
            raise RuntimeError("the session bus went away")

        self.module.CHECKS.clear()
        self.module.CHECKS.update({key: (lambda: {"ok": True}) for key in original})
        self.module.CHECKS["shell"] = explode
        report = self.module.evaluate()
        self.assertFalse(report["ready"])
        self.assertIn("shell", report["notReady"])
        self.assertIn("RuntimeError", report["checks"]["shell"]["error"])

    def test_this_machine_is_not_ready_and_says_why(self) -> None:
        """Run for real. A developer host has no Bunny session, so the honest
        answer is a refusal that names conditions — not an exception."""
        report = self.module.evaluate()
        self.assertFalse(report["ready"])
        self.assertTrue(report["notReady"])
        json.dumps(report)  # the harness reads this; it must serialise


class TheMarkerCannotBeManufactured(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()

    def test_the_not_ready_line_does_not_contain_the_bare_marker(self) -> None:
        """A serial console is grepped for the marker. If the failure line were
        a superstring on the same line, a failed boot would read as a good one.

        The failure line is ``BUNNY_SESSION_READY-NOT: ...``, so anything
        matching the marker as a *whole line* is a real ready signal.
        """
        import contextlib
        import io

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = self.module.main(["--quiet"])
        self.assertEqual(code, 1)
        lines = [line.strip() for line in captured.getvalue().splitlines()]
        self.assertNotIn(self.module.MARKER, lines)
        self.assertTrue(any(line.startswith(self.module.MARKER + "-NOT") for line in lines))

    def test_a_capsule_backend_that_confines_nothing_is_not_ready(self) -> None:
        """``systemd-scope`` carries a cgroup and confines nothing. A session
        that would run the first application unconfined is not ready, and this
        is the one condition somebody would be tempted to relax to get a demo
        running."""
        import inspect

        source = inspect.getsource(self.module.check_capsules)
        self.assertIn("systemd-scope", source)


if __name__ == "__main__":
    unittest.main()

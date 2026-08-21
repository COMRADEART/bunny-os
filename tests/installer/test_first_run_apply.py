# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-run applicator, against the defects the first real login found.

Phase 3's login-1 run (machine built from journey E's disk) measured three
failures in ``applied.json``: the companion mode and captions written to a
GSettings schema that exists nowhere (``art.comrade.BunnyShell``), and an
autostart assertion pointing at ``default.target.wants`` when the unit
installs into ``graphical-session.target.wants``. These tests pin the
corrected behaviour: the companion choices go through the companion's own
settings CLI, and the assertion looks where ``[Install]`` actually links.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest
from unittest import mock

from installer.first_run.apply import Applier
from installer.setup_state import Choices

REPO = Path(__file__).resolve().parents[2]
USER_UNITS = REPO / "systemd" / "user"

#: The units a login session starts. Every one of these also started in the
#: GDM greeter's user manager on the first real login (the greeter reaches
#: graphical-session.target too), which is what the ConditionUser guard stops.
SESSION_FAMILY = (
    "bunny-companion.service",
    "bunny-companion-window.service",
    "bunny-config-dir.service",
    "bunny-desktop.service",
    "bunny-first-boot.service",
    "bunny-first-run.service",
)


def _fake_run(calls: list[list[str]], failing: frozenset[str] = frozenset()):
    def run(argv, **_kwargs):
        calls.append(list(argv))
        completed = mock.Mock()
        completed.returncode = 1 if any(part in failing for part in argv) else 0
        completed.stderr = "refused" if completed.returncode else ""
        completed.stdout = ""
        return completed
    return run


class CompanionSettingsApplicationTests(unittest.TestCase):
    """The companion choices land in the settings document, not GSettings."""

    def _apply(self, mode: str, captions: bool = True) -> tuple[list[list[str]], Applier]:
        choices = Choices(companion_mode=mode, companion_captions=captions)
        applier = Applier()
        calls: list[list[str]] = []
        with mock.patch("installer.first_run.apply.shutil.which",
                        return_value="/usr/bin/bunny-os"), \
             mock.patch("installer.first_run.apply.subprocess.run",
                        side_effect=_fake_run(calls)):
            applier.companion(choices)
        return calls, applier

    def test_no_call_mentions_the_schema_that_never_existed(self) -> None:
        calls, _ = self._apply("full")
        flattened = " ".join(" ".join(call) for call in calls)
        self.assertNotIn("art.comrade.BunnyShell", flattened)
        self.assertNotIn("gsettings", flattened)

    def test_full_writes_visible_and_not_text_only(self) -> None:
        calls, applier = self._apply("full")
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "character", "visible", "true"], calls)
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "accessibility", "text_only", "false"], calls)
        record = {r.key: r for r in applier.results}["companionMode"]
        self.assertTrue(record.applied)

    def test_off_hides_the_character(self) -> None:
        calls, applier = self._apply("off")
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "character", "visible", "false"], calls)
        self.assertTrue({r.key: r for r in applier.results}["companionMode"].applied)

    def test_text_only_sets_the_accessibility_preference(self) -> None:
        calls, applier = self._apply("text-only")
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "accessibility", "text_only", "true"], calls)
        self.assertTrue({r.key: r for r in applier.results}["companionMode"].applied)

    def test_compact_persists_the_chrome_level(self) -> None:
        """The Phase 3 honesty record ("no persisted representation") is
        retired by an actual representation: character.companionMode."""
        calls, applier = self._apply("compact")
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "character", "companion_mode", "compact"], calls)
        record = {r.key: r for r in applier.results}["companionMode"]
        self.assertTrue(record.applied)
        self.assertNotIn("no persisted representation", record.detail)

    def test_minimal_persists_the_chrome_level(self) -> None:
        calls, applier = self._apply("minimal")
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "character", "companion_mode", "minimal"], calls)
        self.assertTrue({r.key: r for r in applier.results}["companionMode"].applied)

    def test_off_and_text_only_leave_the_chrome_level_alone(self) -> None:
        """Neither shows a character, so there is no chrome answer to
        record — and writing one would overwrite a level the user may pick
        again later by unhiding the companion."""
        for mode in ("off", "text-only"):
            calls, _ = self._apply(mode)
            written = [call for call in calls if "companion_mode" in call]
            self.assertEqual(written, [], f"mode {mode!r} wrote a chrome level")

    def test_a_refused_chrome_write_is_not_recorded_as_applied(self) -> None:
        choices = Choices(companion_mode="compact")
        applier = Applier()
        calls: list[list[str]] = []
        with mock.patch("installer.first_run.apply.shutil.which",
                        return_value="/usr/bin/bunny-os"), \
             mock.patch("installer.first_run.apply.subprocess.run",
                        side_effect=_fake_run(calls, failing=frozenset({"companion_mode"}))):
            applier.companion(choices)
        record = {r.key: r for r in applier.results}["companionMode"]
        self.assertFalse(record.applied)

    def test_captions_write_captions_always(self) -> None:
        calls, applier = self._apply("full", captions=True)
        self.assertIn(["/usr/bin/bunny-os", "companion", "settings", "set",
                       "accessibility", "captions_always", "true"], calls)
        self.assertTrue({r.key: r for r in applier.results}["companionCaptions"].applied)

    def test_a_refused_write_is_not_recorded_as_applied(self) -> None:
        choices = Choices(companion_mode="full")
        applier = Applier()
        calls: list[list[str]] = []
        with mock.patch("installer.first_run.apply.shutil.which",
                        return_value="/usr/bin/bunny-os"), \
             mock.patch("installer.first_run.apply.subprocess.run",
                        side_effect=_fake_run(calls, failing=frozenset({"visible"}))):
            applier.companion(choices)
        record = {r.key: r for r in applier.results}["companionMode"]
        self.assertFalse(record.applied)


class AutostartAssertionTests(unittest.TestCase):
    def test_assertion_matches_the_units_install_target(self) -> None:
        """The wants directory asserted is the one [Install] links into."""
        unit = (USER_UNITS / "bunny-companion.service").read_text(encoding="utf-8")
        wanted_by = re.search(r"^WantedBy=(\S+)", unit, re.MULTILINE)
        assert wanted_by is not None
        source = (REPO / "installer" / "first_run" / "apply.py").read_text(encoding="utf-8")
        self.assertIn(f"{wanted_by.group(1)}.wants", source)
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn("default.target.wants", code)


class SessionUnitGuardTests(unittest.TestCase):
    def test_the_session_family_does_not_run_in_the_greeter(self) -> None:
        for name in SESSION_FAMILY:
            with self.subTest(unit=name):
                text = (USER_UNITS / name).read_text(encoding="utf-8")
                self.assertIn("ConditionUser=!gdm-greeter", text)
                self.assertIn("ConditionUser=!gdm\n", text)

    def test_the_first_run_window_is_not_denied_executable_memory(self) -> None:
        """Mesa's software renderer JIT-compiles; MDWE on a GUI unit is the
        measured SIGSEGV from the first real login, not a hardening win."""
        text = (USER_UNITS / "bunny-first-run.service").read_text(encoding="utf-8")
        self.assertNotIn("MemoryDenyWriteExecute=yes", text)


if __name__ == "__main__":
    unittest.main()

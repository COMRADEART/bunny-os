# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The launcher section's pure parts, tested where they can be tested.

The section itself needs a Linux host with a user manager and cannot run here.
Its helpers can, and they are the parts that fail quietly: a unit parser that
stops recognising a directive reports a unit with no hardening, and a section
that finds no hardening reports that nothing was restricted — which reads as a
pass. A quoting helper that gets an apostrophe wrong builds a command that runs
something else.

So each helper is asserted against the case that would make the section lie.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.capsules.sections_launcher import (
    LAUNCHER_UNIT_ROLES,
    LAUNCHER_UNITS,
    SANDBOX_DIRECTIVES,
    _as_scope,
    _quote,
    _replace_first,
    find_unit,
    unit_properties,
)

from tests.support import ROOT


class TheUnitParser(unittest.TestCase):
    def _write(self, text: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        path = directory / "sample.service"
        path.write_text(text, encoding="utf-8")
        return path

    def test_only_the_service_section_is_read(self) -> None:
        """A ``[Unit]`` section may name a condition that looks like a directive.
        Reading it would attribute a property to a unit that never set one."""
        path = self._write(
            "[Unit]\nConditionPathExists=/usr\nProtectSystem=strict\n\n"
            "[Service]\nNoNewPrivileges=yes\n"
        )
        self.assertEqual(unit_properties(path), ("NoNewPrivileges=yes",))

    def test_a_commented_directive_is_not_a_directive(self) -> None:
        path = self._write("[Service]\n# RestrictNamespaces=yes\nNoNewPrivileges=yes\n")
        self.assertEqual(unit_properties(path), ("NoNewPrivileges=yes",))

    def test_the_value_survives_spaces_and_lists(self) -> None:
        path = self._write("[Service]\nRestrictAddressFamilies = AF_UNIX AF_NETLINK\n")
        self.assertEqual(unit_properties(path), ("RestrictAddressFamilies=AF_UNIX AF_NETLINK",))

    def test_a_missing_file_is_no_directives_rather_than_an_error(self) -> None:
        self.assertEqual(unit_properties(None), ())
        self.assertEqual(unit_properties(Path("/nonexistent/bunny.service")), ())

    def test_the_shipped_companion_units_still_parse(self) -> None:
        """The section is BLOCKED on a unit with no directives, so an empty result
        here would turn a real measurement into a refusal nobody investigates."""
        for name in LAUNCHER_UNITS:
            with self.subTest(unit=name):
                path = find_unit(name)
                self.assertIsNotNone(path, f"{name} is not in any search path")
                properties = unit_properties(path)
                self.assertGreater(len(properties), 5, f"{name}: {properties}")

    def test_the_directive_that_the_finding_rests_on_is_recognised(self) -> None:
        self.assertIn("RestrictNamespaces", SANDBOX_DIRECTIVES)
        for name in LAUNCHER_UNITS:
            path = ROOT / "systemd/user" / name
            self.assertIn(
                "RestrictNamespaces=yes",
                unit_properties(path),
                f"{name} no longer sets it; the launcher section's control shape "
                f"depends on this being the directive that refuses the namespace",
            )


class TheScopeControl(unittest.TestCase):
    """The pre-fix vector, rebuilt from the current one.

    If this stopped producing a scope the section's control would silently become
    a second copy of the shape it is meant to contrast with, and every shape would
    pass for the wrong reason.
    """

    VECTOR = (
        "systemd-run", "--user", "--quiet", "--collect",
        "--unit=bunny-capsule-x", "--description=d",
        "--property", "MemoryMax=1", "bwrap", "--unshare-user", "--", "/bin/true",
    )

    def test_it_puts_the_scope_back(self) -> None:
        self.assertIn("--scope", _as_scope(self.VECTOR))

    def test_it_drops_collect_which_a_scope_does_not_take(self) -> None:
        self.assertNotIn("--collect", _as_scope(self.VECTOR))

    def test_it_changes_nothing_else(self) -> None:
        rebuilt = _as_scope(self.VECTOR)
        self.assertEqual(
            [item for item in rebuilt if item not in ("--scope",)],
            [item for item in self.VECTOR if item not in ("--collect",)],
        )

    def test_replace_first_replaces_only_the_first(self) -> None:
        self.assertEqual(
            _replace_first(("a", "b", "a"), "a", ("x", "y")), ("x", "y", "b", "a")
        )


class TheQuoting(unittest.TestCase):
    """Asserted through a real shell, because the claim is about a real shell."""

    def _round_trip(self, value: str) -> str:
        completed = subprocess.run(
            ["bash", "-c", "printf %s " + _quote(value)],
            capture_output=True, text=True, check=False,
        )
        return completed.stdout

    def test_an_apostrophe_survives(self) -> None:
        self.assertEqual(self._round_trip("/home/bunny/it's/here"), "/home/bunny/it's/here")

    def test_a_metacharacter_stays_a_character(self) -> None:
        for value in ("a b", "a;rm -rf /", "$(id)", "`id`", "a\\b", 'a"b'):
            with self.subTest(value=value):
                self.assertEqual(self._round_trip(value), value)


class TheRolesAndTheFix(unittest.TestCase):
    """The two halves of the launcher defect, pinned at the source level.

    The section proves them on a Linux host; these fail on any machine the
    moment somebody moves a ReadWritePaths= line to the wrong unit or drops the
    tmpfiles rule the namespace setup depends on.
    """

    def test_exactly_one_unit_is_the_runtime(self) -> None:
        roles = list(LAUNCHER_UNIT_ROLES.values())
        self.assertEqual(roles.count("runtime"), 1, LAUNCHER_UNIT_ROLES)
        self.assertEqual(set(roles), {"runtime", "client"})

    def test_the_runtime_unit_names_the_state_roots(self) -> None:
        properties = unit_properties(ROOT / "systemd/user/bunny-companion.service")
        lines = [item for item in properties if item.startswith("ReadWritePaths=")]
        self.assertEqual(len(lines), 1, properties)
        self.assertIn("%h/.local/share/bunny", lines[0])
        self.assertIn("%h/.local/state/bunny", lines[0])

    def test_the_client_unit_does_not(self) -> None:
        """A window that can write the trust store can mint its own grants."""
        properties = unit_properties(ROOT / "systemd/user/bunny-companion-window.service")
        self.assertEqual(
            [item for item in properties if item.startswith("ReadWritePaths=")], []
        )
        self.assertIn("ProtectHome=read-only", properties)

    def test_the_tmpfiles_rule_creates_what_the_unit_names(self) -> None:
        """A ReadWritePaths= path that does not exist fails namespace setup with
        226/NAMESPACE before ExecStart — measured on 60 of 60 fresh homes by the
        first-boot unit, which is why the rule idiom exists at all."""
        rules = (ROOT / "config/user-tmpfiles/bunny-os.conf").read_text(encoding="utf-8")
        directives = [
            line.split() for line in rules.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        created = {parts[1] for parts in directives if parts[0] == "d"}
        for needed in ("%h/.local/share/bunny", "%h/.local/state/bunny"):
            self.assertIn(needed, created, f"{needed} is named by ReadWritePaths= but never created")

    def test_the_parser_sees_the_relaxation(self) -> None:
        """ReadWritePaths= must be in SANDBOX_DIRECTIVES: a sandbox reproduced
        without its relaxations reports the pre-relaxation behaviour, and the
        writability half of the section would fail forever against the fix."""
        self.assertIn("ReadWritePaths", SANDBOX_DIRECTIVES)

    def test_runtime_directory_is_deliberately_not_reproduced(self) -> None:
        """systemd removes a RuntimeDirectory when its unit stops; a probe unit
        reusing the live Companion's directory name would delete the session's
        socket directory on exit."""
        self.assertNotIn("RuntimeDirectory", SANDBOX_DIRECTIVES)



if __name__ == "__main__":
    unittest.main()

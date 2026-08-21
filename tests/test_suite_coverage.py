# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every test in this tree is run by something, and that something is named.

The failure this exists for is the quietest one a test suite has. A directory
that ``unittest discover`` cannot import as a package is skipped — no error, no
warning, no line in the output — and every subsequent statement that "the suite
is green" silently stops covering it.

It had happened twice, in two spellings, before this file existed.

* ``scripts/task.py`` already carries the note on ``RELEASE_CLOSURE_SUITES``:
  *"a hyphenated directory is not an importable Python package, so unittest
  discover would skip it and the tests would silently never run. A test that
  does not run is worse than one in a differently-spelled directory."* That was
  the first spelling, and it was fixed by renaming directories.

* Phase 5 found the second. ``tests/boot`` (39 tests) and ``tests/operations``
  (114 tests) had no ``__init__.py``. ``tests/boot`` had **no runner at all** —
  not the reference suite, not a dedicated target, nothing — while
  ``LIVE_BOOT_ROOT_CAUSE.md`` and a comment inside
  ``systemd/bunny-update-agent@.service`` both cite it as the check that guards
  a unit's ``RuntimeDirectory``/``ReadWritePaths`` pairing.

  153 tests were outside the reference suite. 39 of them — the boot suite —
  were outside *every* runner; ``tests/operations`` was at least reachable
  through ``make test-phase5``, a target somebody had to remember. The
  distinction is kept because "not in the suite" and "run by nothing" are
  different failures and only one of them is total.

Renaming fixed the first instance and did not prevent the second, because the
repair was applied to the symptom. This is the repair applied to the property:
a directory of tests that nothing runs fails here, whatever the reason it is
not being run.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

#: Directories deliberately run by a runner other than ``discover -s tests``.
#:
#: Each entry names the runner, because "it is covered elsewhere" is only a
#: defence if somebody can check it. ``tests/installer`` is discovered by
#: ``scripts/task.py installer_tests()``, which ``tests()`` calls immediately
#: after the main discovery — so it runs on every ``make test`` — and it is
#: deliberately *not* an importable package: ``installer_tests`` discovers it
#: with the directory itself as the top level.
RUN_BY_ANOTHER_RUNNER = {
    "installer": "scripts/task.py installer_tests(), called by tests() on every `make test`",
}

#: Not test directories. Support code and fixtures live here too.
NOT_TEST_DIRECTORIES = {"__pycache__", "fixtures", "data"}


def test_directories() -> list[Path]:
    """Every directory under ``tests/`` that contains ``test_*.py``."""
    found = []
    for path in sorted(TESTS.iterdir()):
        if not path.is_dir() or path.name in NOT_TEST_DIRECTORIES:
            continue
        if any(path.glob("test_*.py")):
            found.append(path)
    return found


def contributed_test_count(directory: Path) -> int:
    """How many tests this directory contributes to the reference suite.

    Measured by asking the loader to walk the directory the way
    ``discover -s tests -t ROOT`` walks it, and counting what comes back.

    **Not** by reading test ids, which was this file's first attempt and was
    wrong. A test's id names the module that *defined* it, and the
    ``load_tests`` protocol legitimately pulls tests in from elsewhere:
    ``tests/fedora_host`` contributes 71 tests whose ids all begin
    ``test_git_byte_policy`` because they are defined under
    ``infrastructure/fedora-host/tests``, and ``tests/grader`` contributes 31
    whose ids begin ``qualification.grader``. Attributing by id prefix reported
    both as uncovered when both run on every ``make test``.

    A check that fails a legitimate pattern gets deleted rather than fixed, and
    this one would have deserved it.
    """
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(directory), top_level_dir=str(ROOT)
    )
    return suite.countTestCases()


class NoTestDirectoryIsSilentlySkippedTests(unittest.TestCase):
    def test_there_are_test_directories_to_check(self) -> None:
        """A check that found nothing would pass for ever."""
        self.assertGreater(len(test_directories()), 20)

    def test_every_test_directory_is_an_importable_package_or_declared(self) -> None:
        """``__init__.py``, or a named runner. Nothing else counts."""
        unreachable = []
        for directory in test_directories():
            if (directory / "__init__.py").exists():
                continue
            if directory.name in RUN_BY_ANOTHER_RUNNER:
                continue
            unreachable.append(directory.name)
        self.assertEqual(
            unreachable,
            [],
            "these directories are not importable and no runner claims them, so "
            "unittest discover skips them and their tests never run; add an "
            "__init__.py or declare the runner in RUN_BY_ANOTHER_RUNNER",
        )

    def test_every_declared_exception_still_exists(self) -> None:
        """An exception for a directory that is gone is an exception nobody reviews."""
        for name in RUN_BY_ANOTHER_RUNNER:
            with self.subTest(directory=name):
                self.assertTrue((TESTS / name).is_dir(), f"tests/{name} no longer exists")

    def test_every_importable_directory_contributes_at_least_one_test(self) -> None:
        """The property, measured rather than inferred from a file's presence.

        An ``__init__.py`` is the usual cause of a skip, not the only one: a
        module that raises on import, a directory whose name is not a valid
        identifier, or a ``load_tests`` that returns an empty suite would all
        leave a directory present, importable-looking and contributing nothing.
        This asks the loader what it found.
        """
        empty = [
            directory.name
            for directory in test_directories()
            if (directory / "__init__.py").exists() and contributed_test_count(directory) == 0
        ]
        self.assertEqual(
            empty, [], "these are packages and the loader still got nothing from them"
        )

    def test_the_two_directories_phase_5_recovered_are_covered(self) -> None:
        """Named individually, so a future refactor cannot lose them quietly.

        These are the ones that were outside every published count. The counts
        are asserted as floors rather than equalities: a suite that grows is
        fine, a suite that silently empties is the failure.
        """
        for name, floor, why in (
            ("boot", 30, "had no runner at all; cited in a shipped unit's comments"),
            ("operations", 100, "reachable only through `make test-phase5`"),
        ):
            with self.subTest(directory=name):
                self.assertGreaterEqual(
                    contributed_test_count(TESTS / name),
                    floor,
                    f"tests/{name} is uncovered again ({why})",
                )


if __name__ == "__main__":
    unittest.main()

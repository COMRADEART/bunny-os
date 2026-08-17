# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The qualification grader's own tests, pulled into the reference suite.

The grader lives at ``qualification/grader/`` and keeps its tests beside it, so
that somebody handed a recorded run directory can grade it and check the grader
without the rest of this repository. That placement would ordinarily put them
outside ``unittest discover -s tests``, which is how a suite ends up not
covering its own instrument — and an instrument nothing runs is the state
Phase 4's report called the highest-value thing to fix.

``load_tests`` pulls the single copy in rather than duplicating it. There is
one set of tests and both routes execute it.

The count is asserted. A discovery path that silently found nothing would leave
this file green while covering the grader with zero tests, which is precisely
the failure mode the grader exists to refuse.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRADER_TESTS = ROOT / "qualification" / "grader" / "tests"

#: A floor, not an equality. New rules bring new cases, and a test that has to
#: be edited every time one is added is a test people start editing without
#: reading. Zero is the failure this guards.
MINIMUM_TESTS = 25


def load_tests(loader, standard_tests, pattern):  # noqa: ARG001 - unittest protocol
    suite = loader.discover(start_dir=str(GRADER_TESTS), top_level_dir=str(ROOT))
    standard_tests.addTests(suite)
    return standard_tests


class TheGraderIsActuallyCoveredTests(unittest.TestCase):
    def test_the_grader_package_is_where_the_suite_thinks_it_is(self) -> None:
        self.assertTrue(GRADER_TESTS.is_dir(), "the grader's tests have moved or been removed")

    def test_discovery_finds_the_grader_tests(self) -> None:
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(GRADER_TESTS), top_level_dir=str(ROOT)
        )
        self.assertGreaterEqual(
            suite.countTestCases(),
            MINIMUM_TESTS,
            "discovery found fewer grader tests than expected; the instrument may be uncovered",
        )

    def test_no_discovered_test_is_an_import_failure(self) -> None:
        """``discover`` reports a broken module as a passing-looking placeholder.

        A ``_FailedTest`` counts towards ``countTestCases`` and reads as a test
        until it runs. Naming them here means an import error in the grader
        fails as an import error rather than as an arithmetic coincidence.
        """
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(GRADER_TESTS), top_level_dir=str(ROOT)
        )
        broken = []

        def walk(item):
            if isinstance(item, unittest.TestSuite):
                for child in item:
                    walk(child)
            elif type(item).__name__ == "_FailedTest":
                broken.append(str(item))

        walk(suite)
        self.assertEqual(broken, [], "a grader test module failed to import")


if __name__ == "__main__":
    unittest.main()

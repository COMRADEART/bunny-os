# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the Fedora host infrastructure tests as part of the repository suite.

The tests themselves live beside the tooling they cover, in
``infrastructure/fedora-host/tests``. This module exists so that ``task.py test``
and CI discover them, because a readiness gate that only runs when somebody
remembers to run it is a readiness gate that will eventually be wrong.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE_TESTS = ROOT / "infrastructure" / "fedora-host" / "tests"


def load_tests(loader, tests, pattern):  # noqa: ARG001 - unittest protocol
    if not INFRASTRUCTURE_TESTS.is_dir():
        raise AssertionError(f"{INFRASTRUCTURE_TESTS} is missing")
    # A fresh loader is required. unittest.TestLoader.discover writes
    # ``_top_level_dir`` on the instance it is called on. Reusing the parent
    # discovery loader with a nested top (this directory) then makes every
    # later package under ``tests/`` look like it is outside the project —
    # ``python scripts/task.py test`` died with AssertionError at
    # ``tests/first_login`` on Python 3.12.
    nested = unittest.TestLoader()
    discovered = nested.discover(
        start_dir=str(INFRASTRUCTURE_TESTS),
        top_level_dir=str(INFRASTRUCTURE_TESTS),
        pattern="test_*.py",
    )
    if discovered.countTestCases() == 0:
        raise AssertionError("no host infrastructure tests were discovered")
    tests.addTests(discovered)
    return tests


class NestedDiscoveryDoesNotStealTheSuite(unittest.TestCase):
    def test_load_tests_leaves_the_parent_loader_top_level_alone(self) -> None:
        loader = unittest.TestLoader()
        original = str(ROOT)
        loader._top_level_dir = original
        suite = load_tests(loader, unittest.TestSuite(), "test_*.py")
        self.assertEqual(loader._top_level_dir, original)
        self.assertGreater(suite.countTestCases(), 0)

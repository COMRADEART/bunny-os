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
    discovered = loader.discover(
        start_dir=str(INFRASTRUCTURE_TESTS),
        top_level_dir=str(INFRASTRUCTURE_TESTS),
        pattern="test_*.py",
    )
    if discovered.countTestCases() == 0:
        raise AssertionError("no host infrastructure tests were discovered")
    return discovered

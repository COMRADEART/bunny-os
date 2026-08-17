# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the grader.

These live beside the grader rather than under ``tests/`` because the package
is meant to be usable on its own — a person handed a recorded run directory
should be able to grade it and check the grader without the rest of the
repository. They are pulled into the reference suite by
``tests/grader/test_qualification_grader.py`` using unittest's ``load_tests``
protocol, so there is one copy of them and both routes run it.
"""

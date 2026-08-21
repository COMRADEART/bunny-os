# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The VM journey grader, as a library.

Phase 4's largest finding was not about the product. Six defects were found in
the qualification harness, and four of them had been producing *passes* — runs
that had not done what they claimed, recorded as green. The report named the
fix and declined to make it mid-qualification:

    "Extracting the grader so it can be unit-tested against recorded runs is
    the single highest-value piece of work this report can point at."

This package is that extraction. It exists so that the instrument can be
tested the way the product is: fed recorded evidence, and required to produce
a particular answer.

Three properties are load-bearing.

**It is pure.** Grading reads recorded evidence and returns a verdict. It does
not boot a machine, spawn a process, or write a file — see §6 of the Phase 5
directive and ``tests/test_side_effect_safety.py``, which asserts it by
running the grader over a fixture tree and comparing the tree's bytes
afterwards.

**It distinguishes NOT_RUN from PASS.** The harness defect that cost Phase 4 a
whole run was a story that booted, logged in, photographed a desktop and shut
down *without running the journey it was asked for* — and scored a pass,
because nothing in the record said a journey had been requested. A run now
declares its expectation before it runs; a grader given an expectation and no
matching record answers FAIL, and a grader given no expectation at all answers
NOT_RUN rather than PASS.

**It says which subject a finding is about.** ``product``, ``harness`` or
``machine``. Phase 4 spent an hour on a "Trust failure" that was a stale file
in a fixture. A finding that cannot name its subject invites that again.
"""

from .models import (
    Expectation,
    Finding,
    JourneyRecord,
    Outcome,
    RunEvidence,
    Verdict,
)
from .core import grade, load_evidence, load_expectation, grade_run_directory

__all__ = [
    "Expectation",
    "Finding",
    "JourneyRecord",
    "Outcome",
    "RunEvidence",
    "Verdict",
    "grade",
    "grade_run_directory",
    "load_evidence",
    "load_expectation",
]

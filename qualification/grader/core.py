# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading recorded evidence, and grading it.

This is the only module in the package that touches the filesystem, and it
only ever reads. The separation is not tidiness: §6 of the Phase 5 directive
requires that a qualification probe not alter the state it is measuring, and a
single reading entry point is what makes that assertable rather than asserted.

    recorded run directory
          |
      load_evidence  (reads)
          |
        grade        (pure)
          |
      PASS / FAIL / NOT_RUN  +  explanation

Nothing here needs a live VM. Extraction — ``guestfish``, ``qemu-img``,
``journalctl --directory`` — belongs to the collector that produced the
directory, and the grader is deliberately unable to perform it. A grader that
can reach a machine is a grader that can be affected by one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .models import (
    DimensionVerdict,
    Expectation,
    Finding,
    JourneyRecord,
    Outcome,
    RunEvidence,
    Verdict,
    combine,
)
from .rules import grade_instrument, grade_journey, grade_machine

#: File names inside a recorded run directory. Named once so that a collector
#: and the grader cannot drift apart silently.
INTERACTION_FILE = "interaction.json"
JOURNAL_FILE = "journal-lastboot.log"
EXPECTATION_FILE = "expectation.json"
FINDINGS_FILE = "findings.txt"
RESULT_FILE = "result.json"


def _read_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return document if isinstance(document, Mapping) else None


def load_expectation(run: Path) -> Expectation:
    """Read what the run declared it was going to do.

    A run with no declaration gets :meth:`Expectation.undeclared`. That is not
    an error — every run recorded before Phase 5 is in that state — but it
    costs the run the ability to distinguish "the journey was skipped" from
    "no journey was asked for", and the grader says so through ``RI03``.
    """
    document = _read_json(run / EXPECTATION_FILE)
    if document is None:
        return Expectation.undeclared()
    return Expectation.from_json(document)


def load_evidence(run: Path, *, user: str | None = None) -> RunEvidence:
    """Build a :class:`RunEvidence` from a recorded run directory.

    Tolerant of missing files by design. A run whose journal could not be
    extracted still grades — as ``NOT_RUN`` on the machine dimension — and that
    is the point: an absent input has to produce a different answer from a
    present one that passed, and the way to get that is to load it rather than
    to refuse.

    ``user`` overrides the account name the session-opened check looks for. It
    is normally read from ``result.json``, which the collector writes; the
    override exists for fixtures that carry no ``result.json``.
    """
    run = Path(run)
    interaction = _read_json(run / INTERACTION_FILE) or {}
    previous_result = _read_json(run / RESULT_FILE) or {}

    journal_path = run / JOURNAL_FILE
    journal_present = journal_path.is_file()
    journal_text = (
        journal_path.read_text(encoding="utf-8", errors="replace") if journal_present else ""
    )

    findings_path = run / FINDINGS_FILE
    harness_findings: tuple[str, ...] = ()
    if findings_path.is_file():
        harness_findings = tuple(findings_path.read_text(encoding="utf-8").split())

    journey_document = interaction.get("journey")
    journey = (
        JourneyRecord.from_json(journey_document)
        if isinstance(journey_document, Mapping)
        else None
    )

    status = interaction.get("status")
    if not isinstance(status, str):
        status = previous_result.get("interactionStatus")
    if not isinstance(status, str):
        status = "complete" if interaction else None

    resolved_user = user or previous_result.get("user") or ""

    return RunEvidence(
        label=run.name,
        interaction_status=status,
        journal_text=journal_text,
        journal_present=journal_present,
        journey=journey,
        harness_findings=harness_findings,
        user=str(resolved_user),
        artifact_commit=previous_result.get("artifactCommit"),
        raw_interaction=interaction,
    )


def grade(evidence: RunEvidence, expectation: Expectation | None = None) -> Verdict:
    """Grade recorded evidence. Pure, deterministic, replayable.

    Given the same :class:`RunEvidence` and :class:`Expectation` this returns
    the same :class:`Verdict` on any host, at any time, in any order. That is
    the property that makes the fixtures in ``fixtures/`` a regression suite
    rather than a snapshot.
    """
    expectation = expectation or Expectation.undeclared()

    dimensions = (
        grade_machine(evidence, expectation),
        grade_instrument(evidence, expectation),
        grade_journey(evidence, expectation),
    )
    outcome = combine(dimensions)

    findings: list[Finding] = []
    for dimension in dimensions:
        findings.extend(dimension.findings)
    # Stable order, so two runs of the grader over the same evidence produce
    # byte-identical JSON and a diff of two verdicts is a diff of two runs.
    findings.sort(key=lambda finding: (finding.rule, finding.message))

    return Verdict(
        outcome=outcome,
        explanation=_explain(outcome, dimensions),
        dimensions=dimensions,
        findings=tuple(findings),
        label=evidence.label,
        expectation=expectation,
    )


def _explain(outcome: Outcome, dimensions: tuple[DimensionVerdict, ...]) -> str:
    """One sentence a person can act on, naming the dimensions by name.

    A verdict without this is the state Phase 4 was in: ``findings: []`` beside
    a screen that read "the task failed".
    """
    if outcome is Outcome.FAIL:
        failed = [dimension for dimension in dimensions if dimension.outcome is Outcome.FAIL]
        return "FAIL: " + " | ".join(
            f"{dimension.name}: {dimension.explanation}" for dimension in failed
        )
    if outcome is Outcome.NOT_RUN:
        return (
            "NOT_RUN: nothing this run recorded could be graded — "
            + " | ".join(f"{d.name}: {d.explanation}" for d in dimensions)
        )
    graded = [d.name for d in dimensions if d.outcome is Outcome.PASS]
    skipped = [d.name for d in dimensions if d.outcome is Outcome.NOT_RUN]
    # ASCII only. This sentence is printed to a terminal on both the Fedora
    # reference target and the Windows development host, and a code page that
    # cannot render an em dash turns an explanation into mojibake.
    sentence = "PASS: " + ", ".join(
        f"{d.name} - {d.explanation}" for d in dimensions if d.outcome is Outcome.PASS
    )
    if skipped:
        # Said out loud, every time. A pass that quietly measured two of three
        # dimensions is the shape of a false pass.
        sentence += f" (not graded: {', '.join(skipped)})"
    del graded
    return sentence


def grade_run_directory(run: Path, *, user: str | None = None) -> Verdict:
    """Convenience: load a recorded run and grade it in one call.

    The verb a caller wants. It reads, then grades, and the two halves stay
    separable so a test can construct evidence without a directory.
    """
    run = Path(run)
    return grade(load_evidence(run, user=user), load_expectation(run))

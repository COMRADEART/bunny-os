# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the grader reads, and what it says back.

Every type here is frozen and every field is derived from recorded evidence.
Nothing in this module reads a file, spawns a process or asks a machine a
question — construction happens in :mod:`core`, judgement in :mod:`rules`, and
this module is only the vocabulary the two share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class Outcome(str, Enum):
    """The three answers a graded dimension may have.

    ``NOT_RUN`` is not a hedge and not a soft failure. It is the answer for a
    dimension the evidence cannot speak to — no journal was extracted, no
    journey was requested, the driver was never started. Phase 4's harness had
    no such answer, so "nothing was measured" and "everything measured was
    fine" were the same green, and that is precisely how four false passes
    survived.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


#: Which part of the system a finding accuses.
#:
#: Phase 4 spent an hour treating a stale fixture file as a Trust failure. A
#: finding that cannot name its subject invites exactly that, so every rule
#: declares one.
SUBJECTS = ("product", "harness", "machine")

#: ``blocking`` findings decide the verdict. ``advisory`` findings are
#: recorded and do not. The split exists so that a real observation about the
#: instrument — "this run never declared what it was for" — can be published
#: without retroactively failing every run recorded before the rule existed.
SEVERITIES = ("blocking", "advisory")


@dataclass(frozen=True)
class Finding:
    """One thing wrong, with the evidence that says so.

    ``rule`` is stable and greppable (``RJ04``, ``RM02``). It is the identifier
    a report cites, so it does not change when the message is reworded.
    """

    rule: str
    subject: str
    severity: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.subject not in SUBJECTS:
            raise ValueError(f"unknown subject {self.subject!r}; expected one of {SUBJECTS}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}; expected one of {SEVERITIES}")

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"

    def to_json(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "subject": self.subject,
            "severity": self.severity,
            "message": self.message,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class Expectation:
    """What the run declared it was going to do, *before* it did it.

    This is the structural repair for Phase 4's harness defect 3. That run
    booted, logged in, photographed a desktop and shut down without running the
    journey it had been asked for — and passed, because the record it left was
    indistinguishable from the record of a run that had never been asked for a
    journey at all. Nothing downstream could tell the two apart, because the
    difference was never written down.

    A declaration written before the run makes the difference measurable. A
    grader handed ``journey="granted"`` and a record with no journey in it can
    now say so.

    ``declared`` is false when a run left no ``expectation.json``. Every run
    recorded before Phase 5 is in that state, which is why an undeclared
    expectation is an *advisory* finding and not a blocking one — but it also
    forces an unevaluable dimension to ``NOT_RUN`` instead of ``PASS``.
    """

    declared: bool = False
    #: ``"granted"``, ``"denied"``, or ``None`` for "no journey was requested".
    journey: str | None = None
    #: Whether an in-session driver was supposed to run at all.
    interaction: bool = True
    #: Whether the machine was expected to reach a graphical session. A boot
    #: probe that never logs anyone in should not be failed for lacking one.
    graphical_session: bool = True
    label: str = ""

    @classmethod
    def undeclared(cls) -> "Expectation":
        return cls(declared=False, journey=None, interaction=True)

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "Expectation":
        journey = document.get("journey")
        if journey not in (None, "granted", "denied"):
            raise ValueError(
                f"expectation.journey must be 'granted', 'denied' or absent; got {journey!r}"
            )
        return cls(
            declared=True,
            journey=journey,
            interaction=bool(document.get("interaction", True)),
            graphical_session=bool(document.get("graphicalSession", True)),
            label=str(document.get("label", "")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "declared": self.declared,
            "journey": self.journey,
            "interaction": self.interaction,
            "graphicalSession": self.graphical_session,
            "label": self.label,
        }


@dataclass(frozen=True)
class JourneyRecord:
    """The Trust journey's own account of itself.

    Read straight out of ``interaction.json``. Absent fields stay ``None``
    rather than being defaulted, because "the record does not say" and "the
    record says no" are different states and the rules treat them differently.
    """

    decision: str | None = None
    final_state: str | None = None
    final_says: str | None = None
    produced: tuple[str, ...] = ()
    pixels: tuple[int, ...] | None = None
    source_digest_before: str | None = None
    source_digest_after: str | None = None
    neighbour_digest_before: str | None = None
    neighbour_digest_after: str | None = None
    #: ``None`` when the fixture did not report what it cleared. That is not
    #: the same as ``()`` — see rule RJ12.
    cleared_exports: tuple[str, ...] | None = None
    approval_visible: bool | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def input_unchanged(self) -> bool | None:
        if self.source_digest_before is None or self.source_digest_after is None:
            return None
        return self.source_digest_before == self.source_digest_after

    @property
    def neighbour_unchanged(self) -> bool | None:
        if self.neighbour_digest_before is None or self.neighbour_digest_after is None:
            return None
        return self.neighbour_digest_before == self.neighbour_digest_after

    @classmethod
    def from_json(cls, journey: Mapping[str, Any]) -> "JourneyRecord":
        final = journey.get("final") or {}
        result = journey.get("result") or {}
        fixture = journey.get("fixture") or {}
        pixels = result.get("pixels")
        cleared = fixture.get("clearedExports")
        return cls(
            decision=journey.get("decision"),
            final_state=final.get("state"),
            final_says=final.get("says"),
            produced=tuple(result.get("files") or ()),
            pixels=tuple(pixels) if isinstance(pixels, (list, tuple)) else None,
            source_digest_before=fixture.get("sourceDigest"),
            source_digest_after=result.get("sourceDigest"),
            neighbour_digest_before=fixture.get("neighbourDigest"),
            neighbour_digest_after=result.get("neighbourDigest"),
            cleared_exports=tuple(cleared) if isinstance(cleared, (list, tuple)) else None,
            approval_visible=journey.get("approvalVisible"),
            raw=dict(journey),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "finalState": self.final_state,
            "finalSays": self.final_says,
            "produced": list(self.produced),
            "pixels": list(self.pixels) if self.pixels is not None else None,
            "inputUnchanged": self.input_unchanged,
            "neighbourUnchanged": self.neighbour_unchanged,
            "clearedExports": (
                list(self.cleared_exports) if self.cleared_exports is not None else None
            ),
            "approvalVisible": self.approval_visible,
        }


@dataclass(frozen=True)
class RunEvidence:
    """Everything the grader is allowed to look at.

    Deliberately a value, not a directory handle. Once this object exists the
    grader never touches the filesystem again, which is what makes the
    side-effect test in §6 a statement about the grader rather than about the
    caller's discipline.

    ``journal_text`` is the *already extracted* journal for the newest boot.
    Extraction needs ``guestfish``, ``qemu-img`` and ``journalctl``; grading
    needs none of them, and keeping the two apart is what lets the grader run
    on a laptop against a committed evidence tree.
    """

    label: str = ""
    #: ``"complete"``, ``"failed"``, ``"skipped"``, or ``None`` if unrecorded.
    interaction_status: str | None = None
    journal_text: str = ""
    journal_present: bool = False
    journey: JourneyRecord | None = None
    #: Free-form findings the *collector* recorded, e.g. ``unclean-shutdown``.
    harness_findings: tuple[str, ...] = ()
    user: str = ""
    #: Present so a caller can attribute a verdict to an artifact. Never used
    #: in a rule: the grader grades a run, not a build.
    artifact_commit: str | None = None
    raw_interaction: Mapping[str, Any] = field(default_factory=dict)

    def journal_says(self, needle: str) -> bool:
        return needle in self.journal_text

    @property
    def capsule_started(self) -> bool:
        """Whether a capsule unit was ever started, read from the journal.

        "Nothing was produced" is a weak denial — a task that crashed before
        writing also produces nothing. What a refusal has to mean is that the
        confined program never ran, and that is only a *measurement* because
        the granted run shows this same line present.
        """
        return "Started bunny-capsule" in self.journal_text


@dataclass(frozen=True)
class DimensionVerdict:
    """One graded aspect of a run."""

    name: str
    outcome: Outcome
    findings: tuple[Finding, ...] = ()
    explanation: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "explanation": self.explanation,
            "findings": [finding.to_json() for finding in self.findings],
        }


@dataclass(frozen=True)
class Verdict:
    """The grader's answer: an outcome, and why.

    ``explanation`` is required, not decorative. A verdict a person cannot act
    on is the state Phase 4 was in when a granted journey scored
    ``findings: []`` beside a screen reading "the task failed".
    """

    outcome: Outcome
    explanation: str
    dimensions: tuple[DimensionVerdict, ...] = ()
    findings: tuple[Finding, ...] = ()
    label: str = ""
    expectation: Expectation = field(default_factory=Expectation.undeclared)

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.blocking)

    @property
    def advisory_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if not finding.blocking)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "grader": "qualification.grader",
            "label": self.label,
            "outcome": self.outcome.value,
            "explanation": self.explanation,
            "expectation": self.expectation.to_json(),
            "dimensions": {
                dimension.name: dimension.to_json() for dimension in self.dimensions
            },
            "findings": [finding.to_json() for finding in self.findings],
            "blockingFindingCount": len(self.blocking_findings),
            "advisoryFindingCount": len(self.advisory_findings),
        }


def combine(dimensions: Sequence[DimensionVerdict]) -> Outcome:
    """Roll graded dimensions into one answer.

    Three rules, in order:

    1. Any ``FAIL`` makes the run ``FAIL``. A run does not average out.
    2. If nothing could be evaluated, the run is ``NOT_RUN``. This is the
       clause that refuses Phase 4's defect 3: a story that skipped its
       journey and produced only a screenshot has *measured nothing about the
       journey*, and the answer to "did the journey pass" is not "yes".
    3. Otherwise ``PASS`` — at least one dimension was evaluated and none
       failed.
    """
    if not dimensions:
        return Outcome.NOT_RUN
    if any(dimension.outcome is Outcome.FAIL for dimension in dimensions):
        return Outcome.FAIL
    if all(dimension.outcome is Outcome.NOT_RUN for dimension in dimensions):
        return Outcome.NOT_RUN
    return Outcome.PASS

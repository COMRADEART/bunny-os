# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The rules, one function each, all pure.

A rule takes :class:`RunEvidence` and an :class:`Expectation` and returns
findings. It may not read a file, spawn a process, or consult a clock — a
grader whose answer depends on when it runs cannot be replayed, and replay
over a recorded run that *should* fail is the only reason to trust a
strengthened grader at all.

Rule identifiers are stable. ``RJ04`` means "a granted journey produced
nothing" for as long as this file exists, so a report may cite it and a reader
may grep for it. The message may be reworded; the identifier may not be
reused.

Three families:

``RM``  the machine — did it boot, open a session, keep a journal, shut down
``RI``  the instrument — did the driver run, and did it do what was asked
``RJ``  the journey — did the thing the run went there to do happen
"""

from __future__ import annotations

from typing import Callable, Iterable

from .models import DimensionVerdict, Expectation, Finding, Outcome, RunEvidence

Rule = Callable[[RunEvidence, Expectation], Iterable[Finding]]


# --------------------------------------------------------------- the machine

#: What the journal has to show for a run that reached a graphical session.
#: Each entry is (rule id, check name, substring, case-folded?).
_JOURNAL_EVIDENCE = (
    ("RM01", "sessionOpened", "session opened for user {user}", True),
    ("RM02", "graphicalTarget", "Graphical Interface", False),
    ("RM03", "gnomeShell", "gnome-shell", False),
    ("RM04", "companionService", "bunny-companion.service", False),
    ("RM05", "gdmStarted", "GNOME Display Manager", False),
)


def journal_evidence(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The machine reached a desktop and said so in its own journal.

    These are the checks Phase 4 already had, and they are kept exactly as they
    were — with one change in status. They used to be *the* grade. They are now
    one dimension of it, because "the machine is healthy" was the answer that
    let a failed journey score ``findings: []``.
    """
    if not expectation.graphical_session:
        return []
    findings: list[Finding] = []
    for rule, name, template, fold in _JOURNAL_EVIDENCE:
        needle = template.format(user=evidence.user)
        haystack = evidence.journal_text
        present = (
            needle.lower() in haystack.lower() if fold else needle in haystack
        )
        if not present:
            findings.append(
                Finding(
                    rule=rule,
                    subject="machine",
                    severity="blocking",
                    message=f"the journal lacks evidence: {name}",
                    evidence={"looked for": needle},
                )
            )
    return findings


def gdm_alternate_spelling(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """``RM05`` has a second accepted spelling, and it is declared here.

    The Phase 4 check was ``"GNOME Display Manager" in text or "gdm" in text``.
    The bare ``"gdm"`` arm is too loose to be evidence — it matches a path, a
    unit name in an unrelated message, or the word inside another word — so it
    is not used as a *pass*. It is used to soften the finding: if the strict
    string is missing but the loose one is present, the finding is advisory
    rather than blocking, and says which one it found.
    """
    if not expectation.graphical_session:
        return []
    if "GNOME Display Manager" in evidence.journal_text:
        return []
    if "gdm" not in evidence.journal_text.lower():
        return []
    return [
        Finding(
            rule="RM05a",
            subject="machine",
            severity="advisory",
            message=(
                "the journal does not carry the display manager's own start line, "
                "but does mention gdm; RM05 is reported on the strict string"
            ),
            evidence={"strict": "GNOME Display Manager", "loose": "gdm"},
        )
    ]


def clean_shutdown(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The collector reported an orderly powerdown.

    ``unclean-shutdown`` is written by the collector when QEMU is still alive
    two minutes after an ACPI powerdown. It is the collector's observation, not
    the grader's, and it is carried through rather than re-derived.
    """
    if "unclean-shutdown" not in evidence.harness_findings:
        return []
    return [
        Finding(
            rule="RM06",
            subject="machine",
            severity="blocking",
            message="the machine did not shut down within the powerdown timeout and was killed",
            evidence={"collector finding": "unclean-shutdown"},
        )
    ]


def collector_findings(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """Anything else the collector recorded is carried through, never dropped.

    A collector finding the grader does not understand is still a finding. The
    alternative — ignoring what it cannot classify — is how an instrument
    quietly narrows its own scope.
    """
    findings: list[Finding] = []
    for item in evidence.harness_findings:
        if item == "unclean-shutdown":
            continue  # RM06 owns it
        findings.append(
            Finding(
                rule="RM07",
                subject="machine",
                severity="blocking",
                message=f"the collector recorded a finding: {item}",
                evidence={"finding": item},
            )
        )
    return findings


# ------------------------------------------------------------ the instrument


def interaction_completed(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The in-session driver ran to completion when it was supposed to."""
    if evidence.interaction_status == "failed":
        return [
            Finding(
                rule="RI01",
                subject="harness",
                severity="blocking",
                message="the in-session driver reported a failure",
                evidence={"interactionStatus": "failed"},
            )
        ]
    if evidence.interaction_status == "skipped" and expectation.interaction:
        # Only blocking when the run *declared* it wanted a driver. An
        # undeclared run that skipped its driver is ambiguous by construction,
        # and the ambiguity is reported by RI03 instead of being guessed at.
        severity = "blocking" if expectation.declared else "advisory"
        return [
            Finding(
                rule="RI02",
                subject="harness",
                severity=severity,
                message=(
                    "the run was expected to drive a session and the driver was skipped"
                    if expectation.declared
                    else "the driver was skipped and the run never declared whether it should have run"
                ),
                evidence={"interactionStatus": "skipped", "declared": expectation.declared},
            )
        ]
    return []


def expectation_declared(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """A run should say what it is for, before it does it.

    This is the structural repair for Phase 4's harness defect 3. It is
    *advisory*, deliberately: every run recorded before Phase 5 is undeclared,
    and a rule that retroactively fails the evidence it was written to protect
    is a rule nobody will keep. What the undeclared state does change is that
    an unevaluable dimension answers ``NOT_RUN`` instead of ``PASS`` — see
    :func:`grade_journey`.
    """
    if expectation.declared:
        return []
    return [
        Finding(
            rule="RI03",
            subject="harness",
            severity="advisory",
            message=(
                "the run left no expectation.json, so a journey that was skipped "
                "cannot be distinguished from a journey that was never requested"
            ),
            evidence={},
        )
    ]


# ---------------------------------------------------------------- the journey


def journey_present(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """A run that was asked for a journey has to have one in its record.

    This is the rule that would have caught defect 3 on the day. ``g12``'s
    first attempt finished in 3.5 minutes where the real thing took 16, booted,
    logged in, photographed the desktop and shut down — and left a record with
    no journey in it, which the old grader read as "nothing to grade" and
    therefore as a pass.
    """
    if expectation.journey is None:
        return []
    if evidence.journey is not None:
        return []
    return [
        Finding(
            rule="RJ01",
            subject="harness",
            severity="blocking",
            message=(
                f"the run declared a {expectation.journey} journey and its record contains none; "
                "the journey did not run"
            ),
            evidence={"expected": expectation.journey},
        )
    ]


def decision_recorded(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The prompt was answered, and the answer is one of the two it offers."""
    journey = evidence.journey
    if journey is None:
        return []
    if journey.decision in {"granted", "denied"}:
        return []
    return [
        Finding(
            rule="RJ02",
            subject="product",
            severity="blocking",
            message=f"the journey recorded no decision: {journey.decision!r}",
            evidence={"decision": journey.decision},
        )
    ]


def decision_matches_expectation(
    evidence: RunEvidence, expectation: Expectation
) -> list[Finding]:
    """The answer given is the answer the run was driving towards.

    A granted run that records a denial is not a Trust pass with a different
    shape. It is a run that pressed the wrong control — the same class of
    defect as g6, where a second account's password went into the first
    account's field.
    """
    journey = evidence.journey
    if journey is None or expectation.journey is None:
        return []
    if journey.decision == expectation.journey:
        return []
    return [
        Finding(
            rule="RJ03",
            subject="harness",
            severity="blocking",
            message=(
                f"the run declared a {expectation.journey} journey and the record says "
                f"{journey.decision!r}; the run did not do what it was asked"
            ),
            evidence={"expected": expectation.journey, "recorded": journey.decision},
        )
    ]


def granted_produced_output(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """Permission was given, so the task is required to have happened."""
    journey = evidence.journey
    if journey is None or journey.decision != "granted":
        return []
    if journey.produced:
        return []
    return [
        Finding(
            rule="RJ04",
            subject="product",
            severity="blocking",
            message="the journey granted permission and the task produced nothing",
            evidence={"produced": []},
        )
    ]


def granted_started_a_capsule(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """Granting has to start the confined program, and the journal has to say so."""
    journey = evidence.journey
    if journey is None or journey.decision != "granted":
        return []
    if evidence.capsule_started:
        return []
    return [
        Finding(
            rule="RJ05",
            subject="product",
            severity="blocking",
            message="the journey granted permission and no capsule was ever started",
            evidence={"looked for": "Started bunny-capsule"},
        )
    ]


def granted_did_not_error(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """A granted journey that ends in an error state is a failed journey.

    This is the exact rule the false pass needed. ``g7`` recorded
    ``decision: "granted"``, ``final.state: "error"``, ``final.says: "the task
    failed"``, ``result.files: []`` — and ``findings: []``.
    """
    journey = evidence.journey
    if journey is None or journey.decision != "granted":
        return []
    if journey.final_state != "error":
        return []
    reason = journey.final_says or "no reason recorded"
    return [
        Finding(
            rule="RJ06",
            subject="product",
            severity="blocking",
            message=f"the granted journey ended in an error state: {reason}",
            evidence={"finalState": journey.final_state, "finalSays": journey.final_says},
        )
    ]


def denied_produced_nothing(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """A refusal that still produced the file did not refuse anything.

    Weaker than RJ08 on its own — a task that crashed before writing also
    produces nothing — which is why both exist and why RJ08 is the one that
    carries the security claim.
    """
    journey = evidence.journey
    if journey is None or journey.decision != "denied":
        return []
    if not journey.produced:
        return []
    return [
        Finding(
            rule="RJ07",
            subject="product",
            severity="blocking",
            message=(
                f"the journey denied permission and the task still produced "
                f"{list(journey.produced)}"
            ),
            evidence={"produced": list(journey.produced)},
        )
    ]


def denied_started_no_capsule(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The security claim: denial prevents execution, not merely output.

    Read from the journal with the granted run as the control, so the absence
    of the line is a measurement rather than an absence of instrumentation.
    """
    journey = evidence.journey
    if journey is None or journey.decision != "denied":
        return []
    if not evidence.capsule_started:
        return []
    return [
        Finding(
            rule="RJ08",
            subject="product",
            severity="blocking",
            message="the journey denied permission and a capsule was started anyway",
            evidence={"found": "Started bunny-capsule"},
        )
    ]


def denied_declined_rather_than_errored(
    evidence: RunEvidence, expectation: Expectation
) -> list[Finding]:
    """A refusal presents as a calm decline, not as a failure.

    Phase 4 left this ungraded on purpose — no record established which was
    correct, and a check written from a guess would have failed a correct
    refusal. ``g8`` and ``g13`` both settled it by measurement: a denial ends
    ``idle``, saying "the request was declined". It is graded now because there
    is now a measurement to grade against.
    """
    journey = evidence.journey
    if journey is None or journey.decision != "denied":
        return []
    if journey.final_state != "error":
        return []
    return [
        Finding(
            rule="RJ09",
            subject="product",
            severity="blocking",
            message=(
                "the denied journey presented the refusal as an error rather than a "
                f"decline: {journey.final_says!r}"
            ),
            evidence={"finalState": journey.final_state, "finalSays": journey.final_says},
        )
    ]


def input_unchanged(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The tool was given a copy job, and it must not have edited the original.

    Graded in both directions. A granted run that mangles its input has done
    something the prompt did not describe, and the prompt's own words are
    "Your original file will not be changed."
    """
    journey = evidence.journey
    if journey is None:
        return []
    findings: list[Finding] = []
    if journey.input_unchanged is False:
        findings.append(
            Finding(
                rule="RJ10",
                subject="product",
                severity="blocking",
                message="the journey changed its input file, which the prompt promised it would not",
                evidence={
                    "before": journey.source_digest_before,
                    "after": journey.source_digest_after,
                },
            )
        )
    if journey.neighbour_unchanged is False:
        findings.append(
            Finding(
                rule="RJ11",
                subject="product",
                severity="blocking",
                message="the journey changed a file outside the grant",
                evidence={
                    "before": journey.neighbour_digest_before,
                    "after": journey.neighbour_digest_after,
                },
            )
        )
    return findings


def fixture_reported_what_it_cleared(
    evidence: RunEvidence, expectation: Expectation
) -> list[Finding]:
    """A produced-file claim is only about *this* run if the fixture said what it removed.

    This is harness defect 2, turned into a check. The capsule writes into
    ``~/.local/share/bunny/capsules/**/exports``, which survives a reboot, and
    the machine this chain runs on is deliberately persistent. A fixture that
    resets ``~/Pictures`` and nothing else leaves two states indistinguishable:
    "the denied run produced nothing" and "the previous run's file is still
    sitting there".

    An empty ``clearedExports`` is fine — it means the fixture looked and found
    nothing. A *missing* ``clearedExports`` is the finding: the fixture never
    looked, so the result cannot be attributed to this run.
    """
    journey = evidence.journey
    if journey is None:
        return []
    if journey.cleared_exports is not None:
        return []
    return [
        Finding(
            rule="RJ12",
            subject="harness",
            severity="blocking",
            message=(
                "the fixture did not report what it cleared, so a produced-or-absent "
                "result cannot be attributed to this run rather than to a previous one"
            ),
            evidence={"expected field": "fixture.clearedExports"},
        )
    ]


def approval_was_visible(evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    """The person could see the prompt they are recorded as having answered.

    A decision recorded against a prompt nobody could see is a decision the
    product made, not one the person made.
    """
    journey = evidence.journey
    if journey is None or journey.approval_visible is None:
        return []
    if journey.approval_visible:
        return []
    return [
        Finding(
            rule="RJ13",
            subject="product",
            severity="blocking",
            message="a decision was recorded against an approval that was never visible",
            evidence={"approvalVisible": False},
        )
    ]


# ------------------------------------------------------------------ registry

MACHINE_RULES: tuple[Rule, ...] = (
    journal_evidence,
    gdm_alternate_spelling,
    clean_shutdown,
    collector_findings,
)

INSTRUMENT_RULES: tuple[Rule, ...] = (
    interaction_completed,
    expectation_declared,
)

JOURNEY_RULES: tuple[Rule, ...] = (
    journey_present,
    decision_recorded,
    decision_matches_expectation,
    granted_produced_output,
    granted_started_a_capsule,
    granted_did_not_error,
    denied_produced_nothing,
    denied_started_no_capsule,
    denied_declined_rather_than_errored,
    input_unchanged,
    fixture_reported_what_it_cleared,
    approval_was_visible,
)

ALL_RULES: tuple[Rule, ...] = MACHINE_RULES + INSTRUMENT_RULES + JOURNEY_RULES


def _apply(rules: Iterable[Rule], evidence: RunEvidence, expectation: Expectation) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        findings.extend(rule(evidence, expectation))
    return findings


def grade_machine(evidence: RunEvidence, expectation: Expectation) -> DimensionVerdict:
    """Did the machine boot, open a session and shut down.

    ``NOT_RUN`` when no journal was extracted. That is the clause that keeps a
    missing input from reading as a pass: a run whose journal could not be read
    has not shown that its session opened, and saying so is different from
    saying it did not.
    """
    findings = tuple(_apply(MACHINE_RULES, evidence, expectation))
    if not evidence.journal_present:
        return DimensionVerdict(
            name="machine",
            outcome=Outcome.NOT_RUN,
            findings=tuple(f for f in findings if f.rule in {"RM06", "RM07"}),
            explanation="no journal was extracted, so nothing about the machine was measured",
        )
    blocking = [finding for finding in findings if finding.blocking]
    if blocking:
        return DimensionVerdict(
            name="machine",
            outcome=Outcome.FAIL,
            findings=findings,
            explanation=f"{len(blocking)} machine finding(s): " + "; ".join(
                finding.message for finding in blocking
            ),
        )
    return DimensionVerdict(
        name="machine",
        outcome=Outcome.PASS,
        findings=findings,
        explanation="the machine booted, opened a session, kept a journal and shut down cleanly",
    )


def grade_instrument(evidence: RunEvidence, expectation: Expectation) -> DimensionVerdict:
    """Did the harness do what it was asked, and say what it was asked to do."""
    findings = tuple(_apply(INSTRUMENT_RULES, evidence, expectation))
    blocking = [finding for finding in findings if finding.blocking]
    if blocking:
        return DimensionVerdict(
            name="instrument",
            outcome=Outcome.FAIL,
            findings=findings,
            explanation="; ".join(finding.message for finding in blocking),
        )
    if evidence.interaction_status is None:
        return DimensionVerdict(
            name="instrument",
            outcome=Outcome.NOT_RUN,
            findings=findings,
            explanation="the record does not say whether a driver ran",
        )
    return DimensionVerdict(
        name="instrument",
        outcome=Outcome.PASS,
        findings=findings,
        explanation=f"the driver reported {evidence.interaction_status}",
    )


def grade_journey(evidence: RunEvidence, expectation: Expectation) -> DimensionVerdict:
    """Did the thing the run went there to do actually happen.

    The whole point of the extraction. ``NOT_RUN`` here is a real answer and is
    reached in exactly one case: no journey was requested and none was
    recorded. If a journey *was* requested and none was recorded, that is
    ``FAIL`` by RJ01 — the difference between the two is the declaration, and
    the declaration is why :class:`Expectation` exists.
    """
    findings = tuple(_apply(JOURNEY_RULES, evidence, expectation))
    if evidence.journey is None and expectation.journey is None:
        return DimensionVerdict(
            name="journey",
            outcome=Outcome.NOT_RUN,
            findings=findings,
            explanation=(
                "no journey was recorded and none was declared; this run says nothing "
                "about Trust either way"
            ),
        )
    blocking = [finding for finding in findings if finding.blocking]
    if blocking:
        return DimensionVerdict(
            name="journey",
            outcome=Outcome.FAIL,
            findings=findings,
            explanation="; ".join(finding.message for finding in blocking),
        )
    journey = evidence.journey
    assert journey is not None  # RJ01 covers the other case
    if journey.decision == "granted":
        explanation = (
            f"permission was granted, a capsule started, and the task produced "
            f"{list(journey.produced)} without changing the input"
        )
    else:
        explanation = (
            "permission was denied, no capsule was ever started, nothing was produced, "
            "and the refusal presented as a decline"
        )
    return DimensionVerdict(
        name="journey", outcome=Outcome.PASS, findings=findings, explanation=explanation
    )

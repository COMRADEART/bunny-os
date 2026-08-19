# Phase 9 triage, remediation, and the new-artifact path

Applies to evidence that passed intake validation (`INTAKE_GOVERNANCE.md`).
Nothing here runs on absence: zero ACCEPTED intakes means zero findings,
and zero findings is recorded as zero, never as "no issues found".

## Finding identifiers

Stable, assigned at triage, recorded in
`qualification/phase9/triage/findings.json` with the intake ID that
produced them:

    SEC-P9-NNN      security review findings
    HW-P9-NNN       confirmed hardware failures
    ALPHA-P9-NNN    Alpha tester findings

A finding exists only downstream of an ACCEPTED intake entry. The registry
carries the closed vocabularies; the structural tests enforce them.

## Security review results (workstream A)

A completed review's outcome is one of APPROVED / APPROVED_WITH_CONDITIONS /
BLOCKED / MORE_EVIDENCE_REQUIRED. For every Critical or High finding, the
reviewer's result is compared against the Phase 8 inventory
(`qualification/phase8/security-review/review-package.json`: 8 Critical +
36 High; 41 REQUIRES_REVIEW, 3 UNKNOWN). Disagreement is not automatically
an error; it is classified:

    REVIEWER_ADDED          the reviewer found something the inventory lacks
    REVIEWER_REMOVED        the reviewer discounts an inventory finding
    VERSION_DIFFERENCE      the tools saw different component versions
    EXPOSURE_DIFFERENCE     same component, different reachability judgment
    ARTIFACT_MISMATCH       the reviewer examined different bytes
    ANALYSIS_DIFFERENCE     same inputs, different method or conclusion
    UNKNOWN                 not yet explained

## Security remediation (never the frozen artifact)

If review requires a product change, the frozen artifact is not modified.
The path is: remediation commit → new build → new artifact ID → new digest →
targeted qualification → regression qualification. The new artifact becomes
**CANDIDATE-NEXT**; `e906a48793d7` keeps its historical status. History is
not rewritten.

## Hardware failures (workstream B)

Each hardware dimension stays independently graded — a machine PASS never
collapses into "all hardware features PASS", and a matrix like
boot=PASS, Wi-Fi=PASS, microphone=FAIL, native-3D=NOT_SUPPORTED,
fallback-3D=PASS is a valid, useful result. Every confirmed failure gets
`HW-P9-NNN` and one classification:

    RELEASE_BLOCKER   SUPPORTED_HARDWARE_FAILURE   DRIVER   FIRMWARE
    CONFIGURATION     PERFORMANCE   FALLBACK_FAILURE   ENVIRONMENT   UNKNOWN

A failure blocks the Alpha release only per the supported-hardware scope
committed **before** the result
(`qualification/phase8/alpha/RELEASE_SCOPE.md`: VM-only; zero physical
machines declared supported). The scope is never shrunk after a failure to
green the matrix; any scope change is an explicit decision with rationale,
owner, and artifact applicability, recorded in the findings registry.

## Alpha findings (workstream E)

Classification (one per finding): SECURITY, PRIVACY, DATA_LOSS,
RELEASE_BLOCKER, ACCESSIBILITY, FUNCTIONAL, PERFORMANCE, UX, HARDWARE,
HARNESS, ENVIRONMENT. Confidence: CONFIRMED, LIKELY, REPORTED,
UNREPRODUCED. Confirmed findings record reproduction, artifact, expected
behavior, actual behavior, logs/evidence, severity, disposition.
Unconfirmed findings preserve the original report — the tester's words are
never rewritten to sound more certain than they were, and UNREPRODUCED is
user evidence, not invalidity.

## Reproduction boundary

Every reproduction records where it occurred:

    ON_SUBJECT_ARTIFACT     reproduces on e906a48793d7
    ON_NEWER_ARTIFACT       reproduces only on a later build

These are not interchangeable. A defect reproduced only on a later build
does not prove it affected `e906a48793d7`; a defect fixed on a later build
does not repair `e906a48793d7`. Artifact identity stays mandatory in both
directions.

## Remediation decision

Every accepted finding receives exactly one disposition:

    FIX_NOW   FIX_BEFORE_ALPHA   ACCEPT_FOR_ALPHA   DEFER
    NOT_REPRODUCIBLE   NOT_APPLICABLE

`ACCEPT_FOR_ALPHA` requires: the risk, an owner, the affected artifact, the
rationale, and an expiration or review date. There is no silent acceptance;
the structural tests refuse an ACCEPT_FOR_ALPHA finding missing any of the
five.

## The new-artifact path

If any product code, image content, security remediation, or
release-critical configuration changes: new commit → new artifact → new
digest, and an explicit supersession decision — **YES / NO /
PARALLEL_CANDIDATE**. Nothing supersedes `e906a48793d7` automatically. A
new artifact establishes its own qualification boundary: at minimum the
affected journeys, the affected security checks, the relevant regression
tests, artifact binding, and reference certification are rerun. Unrelated
work is not rerun to accumulate green tests.

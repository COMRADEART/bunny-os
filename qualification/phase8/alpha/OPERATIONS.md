# Alpha program operations

Operationalizes `qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md`. The
protocol says what is tested; this file says how a real program runs it
without losing artifact binding or leaking tester identity.

## Tester identity

Testers are `T-001`, `T-002`, … — assigned at enrolment, permanent for the
cohort. **No personally identifying information enters qualification
evidence**: no names, no emails, no hostnames that identify a person. The
mapping from tester ID to person lives outside the repository with the
program operator.

## What every report binds to

    testerId          T-NNN
    artifactDigest    the ISO sha256 the tester computed on their own machine
                      (expected: 823d50ca…; a mismatch is itself a report,
                      and blocks acceptance of the rest)
    journey           A–E, or "exploratory"
    environment       VM (hypervisor + version) or physical (hardware record
                      fields, PII-free)
    date              ISO 8601

A report bound to "latest build" is returned to the tester, not accepted.

## Report shape

`REPORT_TEMPLATE.json` beside this file. Steps carry
`COMPLETED / FAILED / SKIPPED(reason)`; a journey stops at its first FAILED
step. **Measured** evidence (crashes, CPU, memory, boot/voice/Trust/
persistence failures — things something measured) and **user-reported**
evidence (confusing, delightful, distracting, slow, trustworthy, immersive,
difficult) are separate arrays and are never converted into each other.
Exploration outside the journeys is welcome; unstructured findings are valid
reports and get triaged like any other.

## Triage (§14)

Every finding receives: artifact, reproduction confidence, severity,
category, evidence.

    categories:  SECURITY PRIVACY DATA_LOSS RELEASE_BLOCKER ACCESSIBILITY
                 FUNCTIONAL PERFORMANCE UX HARDWARE HARNESS ENVIRONMENT
    confidence:  CONFIRMED LIKELY REPORTED UNREPRODUCED

`UNREPRODUCED` is not `invalid` — it stays open as user evidence with its
confidence stated, and the blocking conditions treat unconfirmed
data-loss/privacy reports as *untriaged*, not as cleared.

## Where evidence lands

`qualification/phase8/alpha/reports/` — one JSON per report, named
`T-NNN-<journey>-<date>.json`. The directory is empty; **zero testers are
enrolled**, and the gate is NOT_RUN until a real person files a real report.

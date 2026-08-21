# Getting started as an Alpha tester

## 1. Enrol

The program operator assigns you a tester identifier:

    T-001, T-002, T-003, …

It is permanent for the cohort and is the only identity that enters
evidence. The mapping from `T-NNN` to a person lives with the operator,
outside this repository — see `PRIVACY_POLICY.md` for the full list of
things the program refuses to collect (your name, email, IP, addresses,
government identity, hardware serials).

Three identifiers, three different things — do not conflate them:

    TESTER_ID              T-NNN — you, for the cohort
    SUBMISSION_ID          INTAKE-NNN — one submitted report, assigned at intake
    DEVICE_OR_MACHINE_ID   a label YOU choose for one of your machines

If you test on more than one machine, pick your own neutral labels
(`machine-1`, `old-laptop`) and use them consistently in
`machine_label`. Never use a hostname that names you, and never a
hardware serial number — the program does not want them.

## 2. Verify the artifact — before you boot it

Follow `ARTIFACT_VERIFICATION.md`. Compute the SHA-256 of the ISO you
actually have, compare it against the published identity, and keep the
value you computed — your report records **what you observed**, not what
the project claims. If it does not match: do not boot it; report the
mismatch.

## 3. Read the edge of the map

`TESTER_SCOPE.md` and `TESTER_LIMITATIONS.md`. Two minutes that prevent
most surprises, and tell you which surprises are reports.

## 4. Run journeys

The five journeys operationalize the pinned protocol
(`qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md`); the letters are
the intake vocabulary:

    A    install and first boot, through login
    B    Companion renderer modes (which character mode you actually get)
    C    voice (push-to-talk, recognition, response)
    D    Trust (the prompt, allow and deny both)
    E    reboot persistence (does what you set survive a restart)

    exploratory    anything outside the five — equally valid

A journey stops at its first failed step; that stop is the report. You
do not need to finish a journey for the report to count, and you do not
need to run all five.

## 5. Report what happened

`REPORTING.md` and `TESTER_REPORT_SCHEMA.json`. Success is a report.
Failure is a report. "It felt slow" and "the wording confused me" are
reports. Check your report with:

    python3 VERIFY_TESTER_REPORT.py my-report.json

then hand it (plus any logs or screenshots) to the program operator, who
registers it into the sealed intake. You get back your `INTAKE-NNN`
submission id. Corrections are new revisions (`INTAKE-NNN-R1`) — your
original is preserved forever, which is a feature: nobody can rewrite
what you said.

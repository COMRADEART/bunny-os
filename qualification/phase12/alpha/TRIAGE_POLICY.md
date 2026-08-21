# Triage policy — how reports become findings

Applies downstream of the Phase 9 intake, alongside
`qualification/phase9/TRIAGE.md` (which stays authoritative for finding
identifiers and the cross-workstream rules). Nothing here runs on
absence: zero accepted reports derive zero findings, recorded as zero.

## Evidence classes

Every evidence item in the derived register carries exactly one class:

    USER_REPORTED   what a tester said, saw, or screenshotted
    MEASURED        what an instrumented measurement recorded, with method
    REPRODUCED      what a recorded reproduction attempt observed
    DERIVED         an interpretation computed from the above, labeled as such

A tester saying "the desktop felt slow" is USER_REPORTED and stays so; it
becomes a performance regression only through MEASURED or REPRODUCED
evidence. A screenshot of an error is USER_REPORTED until the event is
independently validated. Tester-provided numbers are preserved in full
(method, interval, raw values) and remain USER_REPORTED until the project
validates the measurement. **User language is never rewritten into
stronger technical claims** — derivation copies it verbatim and puts its
own classifications in separate, DERIVED-labeled fields.

## From report to finding

Accepted, contract-valid reports produce register rows
(`qualification/phase12/alpha-findings.json`): one row per entry the
tester chose to put in `findings[]`, and one derived row for an
issue-type report (FAILURE, BUG, PERFORMANCE, COMPATIBILITY, USABILITY,
ACCESSIBILITY, SECURITY_OBSERVATION) whose `findings[]` is empty — the
category then comes from a committed report-type map and the row says so
(`classificationSource: DERIVED`). SUCCESS and GENERAL_FEEDBACK produce
success/feedback evidence, not findings. Rows carry provisional
identifiers (`AF-INTAKE-NNN-n`); the triage identifier (`ALPHA-P9-NNN`)
is assigned in the Phase 9 registry and joined by mapping — the derived
register never mints triage identifiers.

## Severity and user impact — two axes, both separate from the tester

Testers assign neither. Triage may derive severity (CRITICAL / HIGH /
MEDIUM / LOW / INFORMATIONAL) and user impact (BLOCKS_USE /
MAJOR_DEGRADATION / MINOR_DEGRADATION / CONFUSING / COSMETIC / UNKNOWN)
— recorded beside, never inside, the tester's words. "I cannot log in"
stays "I cannot log in" in the immutable evidence, whatever severity the
project assigns it in the register.

## Deduplication

Multiple testers describing one issue is signal, not noise. Relationships
between findings are one of DISTINCT / POSSIBLE_DUPLICATE / DUPLICATE_OF
/ RELATED, and every non-DISTINCT relationship is a **recorded decision**
(`qualification/phase12/dedup-decisions.json`: rationale, decider, date)
— derivation applies decisions and does nothing on its own. Similar
titles, matching components, or identical error text justify a human
suspicion, never an automatic merge. Relationships are reversible (a
later decision supersedes an earlier one; both are preserved), reports
are never deleted, and a deduplicated finding still names every source
report individually.

## Lifecycle and closure

Finding lifecycle authority is Phase 10's
(`candidate_ops.py FINDING_TRANSITIONS`): RECEIVED → VALIDATED → TRIAGED
→ REPRODUCTION_PENDING → CONFIRMED | NOT_REPRODUCED, onward through
FIX_REQUIRED → FIXED → REQUALIFIED → CLOSED. Closure requires
requalification evidence bound to the finding's artifact; a code change
closes nothing, a failed reproduction closes nothing, and NOT_REPRODUCED
reopens only to TRIAGED. If a fix is required, the frozen artifact is
not modified — the successor path and its requalification are Phase 10's
rules, unchanged.

## Security observations

A SECURITY_OBSERVATION report enters the same door, is preserved the
same way, and is additionally surfaced to the Phase 11 security workflow
in the derived register. It is tester evidence, not an independent
security review, and can never satisfy that gate. Marking one
`NOT_A_SECURITY_ISSUE` requires a recorded assessment (who, why,
evidence) — never a bare label. A submission whose content is
inappropriate for permanent public evidence (working exploit detail,
credentials) is handled by the quarantine path in `PRIVACY_POLICY.md`:
the intake decision is recorded, nothing unsafe is ingested, and the
event is never silently discarded.

## Intake classifications

The derived view over intake entries:

    ACCEPTED                valid; enters derivation
    INCOMPLETE              required fields absent; usable when revised
    USER_EVIDENCE_UNBOUND   accepted, no artifact binding; moves no gate
    REJECTED                structurally or safety-refused, reason recorded
    QUARANTINED             refused for credential/safety content before
                            ingestion; the decision is the record

A low-detail report is not an invalid report. Rejection happens only for
a defined structural or safety reason, and the rejection itself is
immutable evidence of the intake decision.

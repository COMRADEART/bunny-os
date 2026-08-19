<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 12 — Alpha Tester Operations & Evidence Intake

## STATUS: **PHASE 12 — ALPHA TESTING AWAITING EXTERNAL EVIDENCE**

Not ALPHA EVIDENCE INTAKE ACTIVE — zero tester reports have arrived. Not
ALPHA TRIAGE IN PROGRESS — nothing exists to triage. Not REMEDIATION
REQUIRED — no accepted finding requires one. Not ALPHA EVIDENCE
SUFFICIENT, and not ALPHA APPROVED — the sufficiency thresholds are
owner-undefined (SUFFICIENCY_UNDETERMINED), zero evidence is recorded as
zero, and no machinery here can round silence up to success. The program
is READY_FOR_TESTERS: the door is open, the package is complete, and the
actual testing remains external.

---

## 1. Executive summary

Phase 12 operationalized the Alpha tester program without inventing a
tester. The repository can now enroll pseudonymous testers, hand them one
canonical package that tells them exactly where the edge of the map is,
require them to identify the artifact they actually ran, receive whatever
they report — success, failure, "I could not install it", "it felt slow"
— through the existing sealed intake, preserve it verbatim forever,
classify it without rewriting it, and derive a finding register that can
never inflate it. Concretely:

* a **canonical package** (`qualification/phase12/alpha/`, thirteen
  files): program, scope, limitations, getting-started, reporting,
  artifact verification, reproduction protocol, triage policy, privacy
  policy, the machine-readable report contract, its validator, the
  identity file, and sha256 pins of every reused Phase 7/8 source —
  drift in a pinned source fails closed;
* a **report contract** (schema-driven validator, alias-compatible with
  the unmodified Phase 9 boundary) with a four-state artifact identity
  model in which the tester's observed digest is never silently replaced
  by the expected one;
* a widened **credential scan at the intake itself**: passwords,
  passphrases, tokens, and keys are refused before a byte is ingested,
  naming the class and the filename, never the value;
* an **operations tool** (`tools/alpha_ops.py`): a derived finding
  register whose every row names its source reports, recorded-decision
  deduplication (reversible, never automatic), a reproduction pipeline
  in which NOT_REPRODUCED is never INVALID, hardware/performance/
  accessibility/security observation handling that never converts a
  tester's words into a stronger claim, an eight-state program machine
  that silence cannot advance, and an owner-undefined sufficiency policy
  that stays UNDETERMINED rather than guessed;
* thirteen **TEST_FIXTURE_ONLY fixtures** and **69 guard tests**
  covering every §29 scenario, with the real ledger byte-compared before
  and after every dry run;
* the fifth run of the standing demonstration: **both immutability
  guards refused the Phase 12 tree** (commit `2144e7f1` fails both, all
  thirty-one files named) until `f3974013` declared it deliberately.

No tester was manufactured. No report was rewritten. No gate moved. The
subject artifact, the ledger, and every blocking condition are exactly
as Phase 11 left them.

## 2. Phase 11 baseline

`PHASE 11 — SECURITY REVIEW AWAITING EXTERNAL EVIDENCE` at head
`5acd3739`. Candidate `e906a48793d7` EVIDENCE_PENDING; zero intakes
across all five sources; security gate AWAITING_EXTERNAL_EVIDENCE;
conditions 1, 2, 7, 8 true. All carried forward unmodified. Phase 12
touched two earlier-phase files, both strengthening: the Phase 9 intake
tool's hygiene scan widened from private keys to likely-credential
classes (with `INTAKE_GOVERNANCE.md` updated to say so), and the Phase
10 ladder's Alpha action now names the canonical Phase 12 package —
`candidate-status.json` re-derived byte-identical, since the security
review remains the next action.

## 3. Subject artifact identity

| | |
| --- | --- |
| Identifier | `e906a48793d7` |
| Image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| OCI archive | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Signing status | **UNSIGNED** |

Frozen, unchanged, not rebuilt. The tester package's
`ARTIFACT_IDENTITY.json` is test-pinned equal to the intake ledger's
subject artifact, so a tester can never be handed an identity the
boundary would refuse.

## 4. Alpha program purpose

Real people run the exact frozen artifact on their own machines and
report what actually happened. Their experience is evidence — preserved,
bound or honestly unbound, classified beside (never over) their words —
and it is deliberately hard to inflate: installation is not
qualification, one machine is not all machines, silence is not success,
and a report nobody could reproduce is still a report. The program's
boundaries were all committed before any tester existed, so no
inconvenient report can bend them.

## 5. Tester privacy model

Testers are `T-NNN`, permanent for the cohort; the mapping to a person
lives with the operator, outside the repository. Three identifiers are
kept distinct: TESTER_ID (`T-NNN`), SUBMISSION_ID (`INTAKE-NNN`), and
DEVICE_OR_MACHINE_ID (a tester-chosen, non-PII label like `machine-1`).
No real name, email address, IP address, street address, government
identity, or hardware serial number is required or wanted, and
`PRIVACY_POLICY.md` says so in the tester's own reading order — the
guard suite asserts the policy names each refused category. The report
schema has no field for any of them.

## 6. Artifact verification

Every workflow instructs the tester to independently identify what they
run, and the report distinguishes `artifact_claimed_by_tester`,
`artifact_digest_observed`, `artifact_digest_verified`, and
`artifact_identity_status` ∈ VERIFIED / OBSERVED_UNVERIFIED / MISSING /
MISMATCH. The validator enforces coherence, executed as negative
controls: VERIFIED without an observed digest is refused; an observed
digest outside the subject set must say MISMATCH; a subject digest
cannot claim MISMATCH; MISSING with a smuggled intake digest is refused
with "never substitute the expected digest for an observation"; and the
intake alias must equal the observed digest exactly. The published
digest is displayed; the tester's report records what they saw.

## 7. Tester report contract

`TESTER_REPORT_SCHEMA.json`, enforced by `VERIFY_TESTER_REPORT.py`
reading the schema itself (required lists, enums, patterns, x-aliases),
with the suite refusing any schema keyword the validator does not
enforce. Required: tester_id, report_type, submitted_at,
artifact_identity_status, artifact_digest_observed (nullable, honestly),
environment_summary, user_observation, expected_behavior,
actual_behavior, journey, steps (may be empty) — plus the four Phase 9
alias spellings, constrained equal, so the record passes the unmodified
intake. Nine report types (SUCCESS through GENERAL_FEEDBACK);
reproduction steps, logs, measurements, and assistive-technology detail
are optional. "I could not install it." is a complete, contract-valid
report; the structured `findings[]` classification is the tester's
choice, and their original classification — like all their words — is
immutable in the sealed record.

## 8. User evidence vs measured evidence

Four classes: USER_REPORTED / MEASURED / REPRODUCED / DERIVED. "The
desktop felt slow" is USER_REPORTED and derives no regression; a
tester-provided measurement is preserved in full (method, interval, raw
values) and stays USER_REPORTED until independently validated; a
screenshot is USER_REPORTED evidence of what it shows; register
interpretations are labeled DERIVED. The register keeps subjective
performance and measurements in separate arrays with an empty
`projectMeasured` until the project actually measures — asserted by
test, in both directions.

## 9. Unbound evidence

A report without a digest is preserved as USER_EVIDENCE_UNBOUND
(Phase 9's existing binding), listed in the register's unbound evidence
with its observation verbatim, able to identify an issue and initiate
investigation, and structurally unable to satisfy, fail, pass, or close
any artifact-specific gate — the row invariant refuses an unbound
finding in CONFIRMED/FIXED/REQUALIFIED/CLOSED. A later revision carrying
the digest establishes applicability; the original stays immutable.

## 10. Revisions and supersession

Corrections are `INTAKE-NNN-R1` beside the original, never over it —
Phase 9's existing mechanism, exercised for the tester flow: the dry run
registers an unbound original, registers a bound revision, asserts the
original ledger entry is byte-identical afterwards, that supersession is
derived (never written back), and that only the effective revision
derives register rows.

## 11. Finding derivation

`qualification/phase12/alpha-findings.json` — derived, not primary
evidence, recomputed from the ledger (read-only), the artifact graph,
the recorded dedup decisions, the recorded reproduction attempts, the
sufficiency policy, and the triage registry. Each row: finding_id
(provisional `AF-INTAKE-NNN-…`; the `ALPHA-P9-NNN` triage identifier is
assigned in the Phase 9 registry and joined — the register never mints
triage IDs), source_report_ids (individually, never a bare count),
artifact or an honest null, category with its source (TESTER when the
tester classified, DERIVED via the committed report-type map when they
did not), derived severity and user impact (null/UNKNOWN until triage —
never inferred from the tester's words), reproducibility, lifecycle
(Phase 10 authority), the tester's words verbatim, technical evidence
with its class, remediation artifact, and closure evidence.

## 12. Deduplication policy

DISTINCT / POSSIBLE_DUPLICATE / DUPLICATE_OF / RELATED. Every
non-DISTINCT relationship is a recorded decision
(`dedup-decisions.json`: rationale, decider, date) — a decision missing
any of them is refused as "an automatic merge in disguise", a decision
naming an unknown finding fails closed, and derivation performs no
similarity matching of its own: two near-identical fixture reports stay
DISTINCT until a decision exists. Decisions are reversible (a later
decision about the same pair supersedes; both are preserved), nothing is
deleted, and a related finding still names every source report.

## 13. Reproduction pipeline

States: NOT_ATTEMPTED / REPRODUCTION_QUEUED / REPRODUCED /
NOT_REPRODUCED / INSUFFICIENT_INFORMATION / ENVIRONMENT_DEPENDENT.
Attempts (`reproductions.json`) record source report, artifact tested,
environment, hypothesis, method, result, limitations, date, operator —
validated, with an invented result refused. The critical rule is
executed, not stated: the NOT_REPRODUCED dry run asserts the finding
stays open (lifecycle unchanged) and the tester report stays ACCEPTED.
The ten-step protocol (`REPRODUCTION_PROTOCOL.md`) was committed before
any real report existed.

## 14. Success evidence limits

A success report derives one success-evidence row: tester, artifact,
environment, observation verbatim, verification level, class
USER_REPORTED, and the limit written into the row itself: "one
successful observed run on one machine; never SUPPORTED ON PCS". It
derives no finding, no PASS, and no matrix change — asserted with the
hardware matrix byte-compared before and after the dry run.

## 15. Hardware evidence handling

Three classes: HARDWARE_OBSERVED / HARDWARE_MEASURED /
HARDWARE_QUALIFIED. Every accepted report contributes a
HARDWARE_OBSERVED row (environment, tester's machine label) carrying the
note that PASS still requires the committed protocol
(`qualification/phase8/hardware/PROTOCOL.md`, pinned); tester reports
can never produce HARDWARE_QUALIFIED. The four Companion render modes —
native-3D, fallback-3D, 2D, prerendered — are asserted to be four
separate matrix dimensions with no generic "graphics" dimension to
collapse into.

## 16. Performance evidence handling

Subjective reports and measurements live in separate register arrays.
"The desktop felt slow." stays those five words with class USER_REPORTED
and the note that it initiates investigation and is never a regression
by itself; a tester's measurement is preserved with method, interval,
environment, and raw values, still USER_REPORTED until independently
validated; `projectMeasured` fills only from actual project
measurements. Neither is ever inferred from the other — tested.

## 17. Accessibility evidence handling

Accessibility observations are first-class: the technology used (when
volunteered), the observation verbatim, the environment, and the
artifact binding are preserved; the package tells assistive-technology
testers their reports are especially valuable precisely because most
assistive flows are unverified. "It worked for me" creates one
observation, not a support claim, and the Phase 7 accessibility
qualification remains untouched historical artifact evidence.

## 18. Security observations

A SECURITY_OBSERVATION report enters the same sealed door and is
surfaced in the register's security-observations section with
`assessment: null` and the note that NOT_A_SECURITY_ISSUE requires a
recorded assessment — a bare label is structurally absent. The section
is pointed at the Phase 11 workflow; tester evidence never impersonates
the independent security review, and nothing an Alpha tester submits can
move that gate. Unsafe content (working exploit detail, credentials)
takes the quarantine path: the intake decision is recorded, nothing
unsafe is ingested, nothing is silently discarded.

## 19. Secret and privacy handling

The Phase 9 intake's hygiene scan — previously private keys only — now
refuses likely credential material before ingestion: private keys,
bearer tokens, cloud access key ids, API/session token assignments,
password/passphrase assignments, JSON web tokens, code-forge tokens
(`SECRET_CLASS_PATTERNS`). On a hit nothing is ingested, and the
REJECTED entry names the class and filename, never the value — the dry
runs assert the secret string appears nowhere in the refusal and nowhere
in the intake tree, for a secret nested three levels deep in record
metadata and for one inside an attachment. `VERIFY_TESTER_REPORT.py`
carries the same table as a courtesy pre-check, and the suite asserts
the two copies are identical. Prose about passwords ("the password
prompt appeared") does not fire — the negative control that proves the
scanner can stay quiet. The scan is deliberately fail-closed; the
governance doc records why.

## 20. Attachment integrity

Every ingested attachment is pinned by size and sha256 in the sealed
ledger entry (Phase 9's existing mechanism); a claimed digest that does
not match the ingested bytes yields UNVERIFIABLE, and a byte modified
after ingestion fails `intake.py verify` — both executed in the dry
runs. Attachment provenance is explicit: a screenshot belongs to the
report that pinned it, and its artifact applicability is the report's
binding, never an inference from appearance.

## 21. Alpha state machine

Eight states: NOT_STARTED, READY_FOR_TESTERS, EVIDENCE_RECEIVED,
TRIAGE_IN_PROGRESS, REMEDIATION_REQUIRED, REQUALIFICATION_REQUIRED,
ALPHA_EVIDENCE_SUFFICIENT, BLOCKED. READY_FOR_TESTERS →
ALPHA_EVIDENCE_SUFFICIENT does not exist; the full undeclared-pair sweep
executes every refusal; EVIDENCE_RECEIVED without accepted evidence is
refused with "silence never advances the state"; SUFFICIENT without a
SUFFICIENT determination is refused with "never rounded up"; BLOCKED
requires its reason. The derived ladder reports only what standing
evidence supports — triage rows without accepted evidence derive
READY_FOR_TESTERS, asserted.

## 22. Sufficiency policy

`sufficiency-policy.json`: required evidence dimensions (journeys A–E,
the four render modes, bound-to-subject coverage, negative-feedback
handling) and six owner-defined thresholds — all currently null, so the
determination is **SUFFICIENCY_UNDETERMINED** and nothing is guessed in
its place. The evaluation distinguishes NO_EVIDENCE from
INSUFFICIENT_EVIDENCE from SUFFICIENT_WITH_UNRESOLVED_BLOCKERS from
SUFFICIENT, each tested with constructed policies; no minimum tester
count was invented.

## 23. Candidate status integration

Alpha evidence reaches the Phase 10 candidate status only as accepted,
gate-eligible intake flowing through the existing derivation — Phase 12
added no second path and cannot touch AUTHORIZED, which remains behind
the Phase 9 authorization floor. The ladder's Alpha action now names the
canonical Phase 12 package; `candidate-status.json` re-derived
byte-identical (the security review is still the next action, and
nothing here could move it).

## 24. Successor artifact handling

If tester evidence requires a product change, `e906a48793d7` is not
modified: report → intake → finding → reproduction/analysis →
remediation decision → source change → successor artifact → graph edge →
impact analysis → requalification, with the successor starting
REQUALIFICATION_REQUIRED. Executed refusals: a successor-active
derivation is refused ("tester evidence does not transfer"), root tester
evidence evaluated against the successor is DOES_NOT_APPLY, a
reproduction on the successor moves nothing for the subject without a
recorded applicability relationship (and counts with one — the positive
control), and closure evidence naming the wrong artifact is refused by
the Phase 10 lifecycle it inherits.

## 25. Synthetic validation

All 23 §29 scenarios are executed: bound success and failure, unbound
evidence, artifact mismatch, revision-with-preserved-original, recorded
duplicate and its reversal, reproduction success and failure,
NOT_REPRODUCED validity, performance observation vs measurement,
accessibility observation, hardware observation without PASS, security
observation, missing required fields (Phase 9 accepts, the contract
holds it, nothing derives), secrets in nested metadata and in an
attachment, attachment hash modification, closure without bound
evidence, transfer to successor, invalid state transitions, zero
evidence advancing nothing, and the fixture wrapper rejected by the real
intake code. Every fixture is structurally marked TEST_FIXTURE_ONLY;
secret payloads are constructed inside the tests so no credential-shaped
bytes are committed; and the real ledger, graph, register, and hardware
matrix are byte-compared before and after every dry run.

## 26. Negative controls

| Control | Result |
| --- | --- |
| Wrong digest, honestly reported | ARTIFACT_MISMATCH; evidence for other bytes moves nothing |
| Missing digest | USER_EVIDENCE_UNBOUND — preserved, visible, gate-inert |
| Expected digest substituted for observation | contract refusal, "never substitute" |
| Modified attachment | UNVERIFIABLE at claim time; `fileChanged` after ingestion |
| Secret-bearing record or attachment | REJECTED, nothing ingested, class named, value never repeated |
| NOT_REPRODUCED | finding open, report ACCEPTED — never invalid |
| One success | one observation with its limit; matrix bytes unchanged |
| Zero reports | READY_FOR_TESTERS, SUFFICIENCY_UNDETERMINED, NO_EVIDENCE |
| Successor artifact | no automatic transfer, in three directions |
| Fixture submission | REJECTED by real Phase 9 registration |
| Similar reports, no decision | DISTINCT — auto-dedup does not exist |
| Decision without rationale / dangling decision | refused, fail closed |
| Silence at every guard | refused with its reason |

## 27. Actual external evidence received

**None.** Zero alpha-feedback intakes; zero intakes of any kind; zero
enrolled testers. The ledger's entries are exactly as Phase 9 created
them, byte-identical before and after every dry run — the tests compare
bytes, never assert emptiness, so the suite stays green on the day a
real tester reports.

## 28. Current Alpha status

From `qualification/phase12/alpha-findings.json`, derived and
reproducible: program **READY_FOR_TESTERS** ("zero is recorded as zero,
and silence advances nothing"), sufficiency **SUFFICIENCY_UNDETERMINED**
at evidence level **NO_EVIDENCE**, zero reports, zero findings, zero
success evidence, zero observations of every kind.

## 29. Blocking conditions

Unchanged from Phases 9–11, none weakened: conditions **1, 2, 7, 8
TRUE**, **6 FALSE**, **3, 4, 5, 9, 10 UNDETERMINED**. Condition 10
(Alpha testing finds an unresolved release blocker) remains UNDETERMINED
with zero reports — undetermined is not cleared, and this phase built
the machinery that will evaluate it honestly when evidence arrives.

Validation at `f3974013`: Windows release **346 tests** (277 prior + 69
new) OK (1 skip), portability **205** OK (3 platform skips); reference
target (FedoraLinux-44 WSL2, ext4, as `bunny`) release **346** OK (1
pre-existing skip), portability **205** OK (1 skip), both guards **13**
OK; `intake.py`, `candidate_ops.py`, `security_review_ops.py`, and
`alpha_ops.py` verify clean on both targets; discovery counts verified
explicitly on both.

## 30. Next required action

Unchanged by design: **commission the independent security review**
(`qualification/phase11/security-review/REQUEST.md`) — the deterministic
ladder still names it first, and Phase 12 did not touch that ordering.
For this phase's own thread: **enroll real Alpha testers under
`qualification/phase12/alpha/PROGRAM.md`** and, when the owner is ready,
define the sufficiency thresholds that are currently null. Both actions
belong to people outside this repository; until one of them acts, the
correct description of the Alpha program is the status at the top of
this report.

# PHASE 12 — ALPHA TESTING AWAITING EXTERNAL EVIDENCE

A tester is allowed to be wrong, to be unable to reproduce a problem, to
describe it badly, and to succeed on only one machine. The machinery now
preserves exactly what happened without inflating it: user experience is
evidence, reproduction is additional evidence, qualification is a
separate decision — and no amount of internal processing can turn no
testers into tested, or one machine into all machines.

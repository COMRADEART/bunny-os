<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 9 — External Evidence Intake & Alpha Release Decision

## STATUS: **PHASE 9 — EXTERNAL EVIDENCE INTAKE IN PROGRESS**

Not REMEDIATION REQUIRED — no accepted finding exists to remediate. Not
ALPHA RELEASE BLOCKED — no external actor has returned a blocking result.
Not ALPHA RELEASE AUTHORIZED — the required human decisions have not
happened, and the repository cannot authorize itself. Waiting honestly is
the result.

---

## 1. Executive summary

Phase 9's question is §FINAL's: *did real external evidence support
distributing this exact artifact to Alpha users?* The honest answer today
is **no evidence has arrived** — zero intakes across all five sources — and
this phase's work is that when evidence does arrive, it enters through a
boundary that cannot lose it, forge it, rebind it, or quietly upgrade it:

* a controlled intake structure with one approved append mechanism
  (`qualification/phase9/tools/intake.py register`): intake IDs assigned in
  arrival order, revisions preserved beside their originals, every ingested
  byte pinned by size and sha256, every ledger entry sealed;
* the six validation questions (identity, artifact binding, timestamp,
  completeness, integrity, scope) answered mechanically where mechanical
  answers exist, and recorded for human judgment where they do not — the
  automation validates evidence, it never impersonates its source;
* the six evidence statuses with rejection preserved and explained
  (`usableIf`), artifact mismatch defaulting to **no transfer**, and
  unbound tester reports kept as `USER_EVIDENCE_UNBOUND` rather than
  discarded or silently promoted;
* the §19 immutability properties executed on every test run: accepted
  record modified → FAIL, rejected record modified → FAIL, new intake via
  the mechanism → PASS — plus seal-tamper, deletion, orphan-file and
  tampered-ledger-refusal controls;
* an authorization floor that makes the decision record mechanically unable
  to say AUTHORIZED while the ledger holds no accepted evidence from the
  owners whose absence is the state — with that failure branch executed
  against a constructed AUTHORIZED decision on every run;
* and the same live demonstration Phase 8 earned: **both standing
  immutability guards refused the Phase 9 tree** as an addition until it
  was declared deliberately (commit `5d0071d4` fails both guards;
  `fac4ea45` declares).

No review was performed and labeled independent. No hardware was claimed.
No unsigned byte was called signed. No absence became a PASS.

## 2. Phase 8 baseline

`PHASE 8 — EXTERNAL VALIDATION IN PROGRESS` at head `ef552030`. Six owner
packages ready; every external gate NOT_RUN; ten blocking conditions
committed at `17a34aa6` before any external evidence, none weakened since.
The Phase 7 engineering certification (commit `e65e3df0`, 2 × 6072 tests,
zero failures) remains closed and was not reopened.

## 3. Subject artifact identity

| | |
| --- | --- |
| Identifier | `e906a48793d7` |
| Image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| OCI archive | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Signing status | **UNSIGNED** |

Frozen, unchanged, not rebuilt. No PASS transfers to any other artifact;
a document about other bytes earns `ARTIFACT_MISMATCH` at intake, and any
relationship that would justify a transfer must be explicit, recorded, and
decided by a person. The default is no transfer.

## 4. Intake inventory

`qualification/phase9/intake/LEDGER.json`: **zero intakes.**

| Source | Intakes | Gate-eligible |
| --- | --- | --- |
| security-review | 0 | none |
| hardware | 0 | none |
| signing | 0 | none |
| second-approval | 0 | none |
| alpha-feedback | 0 | none |

The empty ledger is the §2 record of what arrived: nothing. Incoming
evidence lands only under `qualification/phase9/intake/<source>/INTAKE-NNN/`
— never in a frozen Phase 4–8 tree; the Phase 8 landing paths
(`phase8/alpha/reports/`, rows in `phase8/hardware-matrix.json`) are
superseded by this boundary without editing the Phase 8 files.

## 5. Evidence validation results

No submissions exist to validate. The machinery that will validate them is
tested now, against constructed submissions, so its verdicts exist before
its first real input (`tests/release/test_phase9_intake.py`, 24 tests):

* foreign digest → `ARTIFACT_MISMATCH`, gate-ineligible, "no transfer by
  default" in the recorded reason;
* signing drill submitted to the production gate → `REJECTED` (drills
  satisfy nothing there, per the Phase 8 categories that never merge);
* approval naming a branch or commit but no digest → `INCOMPLETE`, with
  the missing recomputed-digest requirement named;
* one person approving twice → `REJECTED`;
* private key material anywhere in a submission → nothing ingested,
  `REJECTED` entry with an empty file list; the refusal is the record;
* unparseable record → `UNVERIFIABLE`, bytes preserved verbatim;
* claimed attachment digest that does not match the ingested bytes →
  `UNVERIFIABLE`;
* tester report without a digest → `ACCEPTED` as user evidence, binding
  `USER_EVIDENCE_UNBOUND`, unable to move an artifact-specific gate;
* hardware PASS without an evidence reference → `INCOMPLETE`; a graded mix
  (boot PASS, microphone FAIL, native-3D NOT_SUPPORTED, fallback PASS) →
  `ACCEPTED`, because dimensions never collapse.

## 6. Security review results

**NOT_RUN — no review has arrived.** The reviewer's package remains ready
at `qualification/phase8/security-review/` (44 Critical/High findings, 41
REQUIRES_REVIEW, 3 UNKNOWN, per-binary analysis uncollapsed). When a review
arrives it is validated for reviewer, scope, artifact digest, date,
findings and one of the four allowed outcomes; new findings receive
`SEC-P9-NNN`; disagreement with the Phase 8 inventory is classified
(REVIEWER_ADDED / REVIEWER_REMOVED / VERSION_DIFFERENCE /
EXPOSURE_DIFFERENCE / ARTIFACT_MISMATCH / ANALYSIS_DIFFERENCE / UNKNOWN),
never auto-treated as error. Nothing was reviewed by this repository and
labeled independent.

## 7. Security remediation

**None required, none performed.** The path is fixed in
`qualification/phase9/TRIAGE.md`: the frozen artifact is never modified;
a required change means remediation commit → new build → new artifact ID →
new digest → targeted + regression qualification, with the new artifact as
CANDIDATE-NEXT and `e906a48793d7` keeping its historical status.

## 8. Hardware qualification results

**NOT_RUN — zero machines, zero submissions.** A hardware intake validates
`HW-NNN`, the tested ISO digest, the machine identity fields including
firmware mode and Secure Boot state, and per-dimension results in the
closed vocabulary, each PASS carrying evidence. Confirmed failures would
receive `HW-P9-NNN` and one of the nine classifications; blocking follows
only the supported-hardware scope committed **before** any result
(`qualification/phase8/alpha/RELEASE_SCOPE.md`: zero physical machines
declared supported), and the scope is never shrunk after a failure to
green a matrix.

## 9. Signing results

**NOT_RUN. The artifact remains UNSIGNED.** Zero signature files (measured
Phase 6, unchanged through today). A future signing intake requires the
PRODUCTION ARTIFACT SIGNED category, the exact digest, signature
identifier, signer identity and authority, timestamp, and a verification
result independent of the signing command — the command's success message
is insufficient, and the entry records its verification basis
(recorded-identity vs recomputed-bytes). Private key material never enters
evidence; `register` refuses the bytes before ingestion.

## 10. Second approval results

**NOT_RUN — one person.** A valid approval intake carries two different
people, each independently recomputing and naming the artifact digest;
a record naming a branch or commit without the digest is INCOMPLETE, and
one person in two hats is REJECTED. Both behaviors are already enforced
and tested.

## 11. Alpha tester results

**None. Zero testers, zero reports.** Tester submissions receive `T-NNN`
identity (no PII in evidence) and validate against the Phase 8 report
shape: journey, environment, steps, measured and user-reported arrays kept
separate and never converted into each other. A report that cannot
establish its digest is preserved as `USER_EVIDENCE_UNBOUND` — kept as
user evidence, unable to satisfy or block an artifact-specific gate until
reproduction binds it.

## 12. Finding triage

`qualification/phase9/triage/findings.json`: **zero findings.** The scheme
is in force before its first entry: identifiers per source (SEC-P9 / HW-P9
/ ALPHA-P9), the eleven categories, four confidence levels with
UNREPRODUCED kept as user evidence, and the structural rule that a finding
exists only downstream of an ACCEPTED intake entry, citing its intake ID.
Confirmed findings must name their reproduction boundary:
`ON_SUBJECT_ARTIFACT` and `ON_NEWER_ARTIFACT` are not interchangeable — a
defect reproduced only on a later build proves nothing about
`e906a48793d7`, and a fix on a later build repairs nothing on it.

## 13. Remediation decisions

**None exist.** Every future accepted finding receives exactly one of
FIX_NOW / FIX_BEFORE_ALPHA / ACCEPT_FOR_ALPHA / DEFER / NOT_REPRODUCIBLE /
NOT_APPLICABLE. ACCEPT_FOR_ALPHA requires risk, owner, affected artifact,
rationale, and an expiration or review date — enforced structurally; there
is no silent acceptance.

## 14. New artifact relationships

**None.** No product code, image content, or release-critical
configuration changed in this phase; no new artifact exists. If one
becomes necessary it gets a new commit, new identity, new digest, an
explicit supersession decision (YES / NO / PARALLEL_CANDIDATE — never
automatic), and its own qualification boundary: affected journeys,
affected security checks, relevant regressions, artifact binding,
reference certification. Unrelated work is not rerun for green
accumulation.

## 15. Blocking conditions

The ten conditions fixed at `17a34aa6`, none weakened, scored in
`qualification/phase9/decision/alpha-release-decision.json`:

* **TRUE — 1, 2, 7, 8**: no completed review exists; every Critical lacks
  an accepted disposition; the artifact is unsigned with no recorded
  exception; no second approval exists. Absence blocks; it does not
  authorize.
* **FALSE — 6**: artifact identity verifies (five digests recomputed from
  bytes 2026-08-18).
* **UNDETERMINED — 3, 4, 5, 9, 10**: no testing evidence exists either
  way; undetermined is not cleared.

The decision test hard-codes the ten titles, so none can be dropped or
reworded silently, and conditions 7 and 8 cannot read anything but TRUE
while the ledger holds no accepted signing or approval intake.

## 16. Release decision matrix

`PHASE9_ALPHA_RELEASE_DECISION_MATRIX.md` — ten rows, each with its
evidence ID column (all `—` today), owner, status, and blocking basis.
PASS rows: exactly two, both internal (artifact identity; the closed
Phase 7 certification). Every external row: NOT_RUN. Statuses are a closed
vocabulary and are never averaged: the release is a conjunction.

## 17. Final authorization state

`alpha-release-decision.json`: **`final_decision: MORE_EVIDENCE_REQUIRED`.**
All twelve required fields present. The decision authority (the project
owner, for the Alpha class) has exercised nothing: MORE_EVIDENCE_REQUIRED
is the measured default state, not a release decision. The authorization
floor (`intake.py authorization_floor`) makes AUTHORIZED /
AUTHORIZED_WITH_LIMITATIONS a violation while security-review, signing and
second-approval hold no gate-eligible ACCEPTED intake — the repository
cannot authorize itself, and the check proving that has an executed
failure branch.

## 18. Evidence inventory

| Path | What |
| --- | --- |
| `qualification/phase9/INTAKE_GOVERNANCE.md` | the intake boundary: IDs, statuses, append mechanism, key hygiene, phase boundaries |
| `qualification/phase9/TRIAGE.md` | finding identifiers, disagreement classes, reproduction boundary, dispositions, new-artifact path |
| `qualification/phase9/intake/LEDGER.json` | the append-only ledger; zero entries |
| `qualification/phase9/intake/<source>/README` | five landing directories, each stating what its emptiness means |
| `qualification/phase9/tools/intake.py` | register / verify / status; sealing, pinning, validation, the authorization floor |
| `qualification/phase9/triage/findings.json` | the findings registry; zero findings; closed vocabularies |
| `qualification/phase9/decision/alpha-release-decision.json` | the §17 decision record: MORE_EVIDENCE_REQUIRED |
| `PHASE9_ALPHA_RELEASE_DECISION_MATRIX.md` | the decision matrix |
| `tests/release/test_phase9_intake.py` | 24 structural and append-only invariants, failure branches executed |
| `tests/release/test_phase9_decision.py` | 17 decision, floor and triage invariants |
| guard maintenance | both immutability guards refused the tree at `5d0071d4`, declared it at `fac4ea45` — refusal and declaration are the audit trail |

Validated on the reference target (ext4, as `bunny`) at `fac4ea45`: the
release suite (152 tests) and the portability suite (205 tests), clean.
The closed Phase 7 certification was not rerun.

## 19. Remaining actions

Everything remaining belongs to an owner outside this repository, whose
input has been ready since Phase 8:

| Owner needed | Their input | Where their evidence lands |
| --- | --- | --- |
| Independent security reviewer | `qualification/phase8/security-review/PACKAGE.md` | `intake/security-review/` |
| A physical machine's operator | `qualification/phase8/hardware/PROTOCOL.md` | `intake/hardware/` |
| Key authority | `qualification/phase8/signing/SIGNING_READINESS.md` | `intake/signing/` |
| A second approver | `qualification/phase8/signing/APPROVALS.md` | `intake/second-approval/` |
| Alpha testers | `qualification/phase8/alpha/` (scope and limitations first) | `intake/alpha-feedback/` |
| Release decision authority | the matrix rows above | `alpha-release-decision.json`, only on evidence |

When evidence arrives: register → validate → bind → triage → remediate if
necessary → re-qualify what changed → decide. Until then:

# PHASE 9 — EXTERNAL EVIDENCE INTAKE IN PROGRESS

Waiting honestly is preferable to manufacturing a release.

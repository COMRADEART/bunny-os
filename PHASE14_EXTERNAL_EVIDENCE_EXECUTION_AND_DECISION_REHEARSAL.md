<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 14 — External Evidence Execution & Decision Rehearsal

## STATUS: **PHASE 14 — EXTERNAL EVIDENCE EXECUTION READY**

**PHASE 14 DOES NOT AUTHORIZE THE ARTIFACT AND CREATED NO EVIDENCE.**

The subject artifact `e906a48793d7` remains ROOT, FROZEN, UNCHANGED,
UNSIGNED. The real Phase 9 intake ledger holds zero entries and is
byte-identical to its Phase 13 state. The derived candidate
authorization state is **EVIDENCE_PENDING** and the derived candidate
decision is **REQUIRES_MORE_EVIDENCE**. What this phase built is the
proof that the day real evidence arrives is already executable: the
complete pipeline — receive, classify, validate, bind, cut, reconcile,
conflict-handle, expire, revoke, assemble, refuse — has been run end to
end, 72 times, on TEST_FIXTURE_ONLY material in scratch universes, with
every real input byte-compared before and after every run. The
machinery being ready is the result. The evidence is still external.

## 1. Executive summary

Phases 8–13 built the governance: blocking conditions, an intake
boundary, an artifact graph, review reconciliation, sufficiency logic,
and release authority. None of it had ever been driven end to end,
because no external evidence exists. Phase 14 closes that gap without
crossing it: `qualification/phase14/tools/evidence_execution_ops.py`
composes the five standing engines — never duplicating them — into an
evidence router, sealed evidence cuts, most-blocking conflict handling,
per-machine hardware truth, signing/approval ordering checks, time
screening, and a decision assembler whose only possible AUTHORIZED is
one a validated, sealed external authority record already made. 72
rehearsal scenarios across 9 tracks execute the whole surface,
including every named refusal; `MATRIX.json` is derived by re-running
them all (under a second) and `verify` refuses drift. 118 new tests
bring the release suite from 436 to 554, green on Windows and on the
Fedora 44 reference target, where the matrix also re-derives
byte-identical. Every favorable row anywhere in this phase is
FIXTURE_DEMONSTRATION_ONLY; every real gate remains
EXTERNAL_EVIDENCE_REQUIRED.

## 2. Exact subject artifact identity

Unchanged from Phase 7. PROVEN by byte comparison on every rehearsal
and by `verify_phase14.py` on every verify run:

| Field | Value |
| --- | --- |
| Identifier | `e906a48793d7` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| ISO sha256 | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| OCI tar sha256 | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| qcow2 sha256 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| raw sha256 | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| Signing status | `UNSIGNED` |
| Graph position | ROOT, frozen, no successor |

Nothing was rebuilt, modified, replaced, superseded, or re-signed.

## 3. No real external evidence was created

Explicit statement: **this phase created zero external evidence and
registered nothing in the real intake ledger.** The real ledger
(`qualification/phase9/intake/LEDGER.json`, sha256
`b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`)
holds zero entries, exactly as Phase 13 left it. This is PROVEN, not
asserted-by-emptiness: every one of the 72 rehearsals snapshots all
eighteen real immutable inputs (ledger, decision record, artifact
graph, security baseline, both derived registers, the Phase 12
sufficiency policy, the Phase 13 status, blocking conditions, and all
nine governance registries) before running and byte-compares after —
one changed byte aborts the whole run with `REAL LEDGER INTEGRITY
FAIL`. Both test suites repeat the comparison in `setUpClass` and
`tearDownClass`. The guarantee survives the day real evidence arrives,
because it compares bytes, not emptiness.

## 4. Phase objective

Prove the external-evidence pipeline executable before real evidence
exists, so that when a reviewer, tester, hardware operator, signer,
approver, or authority acts, nothing about the path their evidence
takes is being run for the first time. Ten capabilities were required
and are now PROVEN over fixtures: receiving without trusting the
submitter, validation, artifact binding, reconciliation against
committed findings and blocking conditions, conservative conflict
handling, time and expiry semantics, owner policy activation without
history rewrite, sufficiency determination, decision assembly from
immutable evidence, and refusal whenever anything is absent, invalid,
expired, conflicting, or bound to the wrong artifact.

## 5. Inherited architecture

Phase 14 is composition, not construction. The engine imports and
drives, at call time, the five standing engines:

| Engine | What Phase 14 drives |
| --- | --- |
| Phase 9 `intake.py` | `register`, `validate_record`, `effective_statuses`, seal verification, credential scanning — the real registration code, in scratch trees |
| Phase 10 `candidate_ops.py` | graph validation, active-candidate identity, applicability (`DOES_NOT_APPLY` default) |
| Phase 11 `security_review_ops.py` | submission validation, reconciliation, register derivation, conflict classification |
| Phase 12 `alpha_ops.py` | register derivation, dedup, reproducibility, sufficiency evaluation |
| Phase 13 `release_authority_ops.py` | authorization validation, the most-restrictive-first status ladder, risk/revocation state, sealed-record append and conflict classification |

No engine was moved or modified. Every rule demonstrated in this phase
is enforced by the phase that owns it; Phase 14 adds only the
orchestration and the walls around fixtures.

## 6. Evidence routing (Track A — 8 scenarios)

Ten evidence classes are declared with owner, route kind (Phase 9
intake vs. Phase 13 governance registry), destination, and validator.
Classification is structural — field-group fingerprints — and refuses
in both directions: a record matching zero classes is refused
("generic evidence" does not exist), and a record matching more than
one is refused (a record shaped like two things is saying nothing).
Routing dispositions are `ACCEPTABLE_FOR_INTAKE`, `INCOMPLETE`,
`REJECTED`, `DOES_NOT_APPLY`, `REQUIRES_HUMAN_DECISION`, and
`TEST_FIXTURE_ONLY` — the fixture check runs first and is terminal.
Governance-class records that are complete and bound route to
`REQUIRES_HUMAN_DECISION` naming the exact `record <kind>` command,
because the repository cannot perform a governance act. All
FIXTURE_DEMONSTRATION_ONLY.

## 7. Evidence cut model (Track B — 8 scenarios)

A cut is a sealed snapshot: subject artifact, artifact digests, ledger
sha256, intake IDs, gate-eligible accepted evidence, graph sha256,
both register shas, and per-cut states with seals for every policy
version, authority record, risk acceptance, and authorization —
sealed with the same sha256-over-canonical-JSON algorithm Phases 9 and
13 use. PROVEN properties: a cut is reproducible from the same inputs;
a broken seal is `IMMUTABILITY FAIL`; evidence arriving after a cut is
detected and named (`postCutIntakeIds`) rather than silently absorbed;
a later assembly supersedes an earlier one by pointing at it, never by
editing it; supersession over the same cut refuses ("not for a
rerun"); and `--as-of` is mandatory once any expiring record exists —
expiry is never evaluated by silence.

## 8. Security review rehearsal (Track D — 8 scenarios)

Run through the real Phase 11 + Phase 9 path in scratch trees: a valid
independent review is ACCEPTED and contract-valid; reconciliation
disposes baseline findings (CONFIRMED / NOT_APPLICABLE) and counts the
unaddressed 42, which keep their prior state — silence dispositions
nothing; the gate becomes UNDER_ANALYSIS, not SATISFIED; a review
bound to the wrong artifact contributes nothing; intake ACCEPTED
without the independent digest layer is not contract-valid and
contributes nothing until revised; a NEW_FINDING mints no ID; two
reviewers concluding oppositely is CONTRADICTORY_CONCLUSIONS — the
gate blocks and both records survive; a revision supersedes without
deleting. Critical dispositions fail closed three separate ways. All
FIXTURE_DEMONSTRATION_ONLY; the real security gate remains
EXTERNAL_EVIDENCE_REQUIRED.

## 9. Alpha evidence rehearsal (Track E — 7 scenarios)

Volume never substitutes for policy: many accepted reports under an
undefined sufficiency policy stay `SUFFICIENCY_UNDETERMINED`, and the
same scenario checks the *real* registry is still
`SUFFICIENCY_POLICY_UNDEFINED` so a fixture policy cannot leak a real
threshold. A fixture policy activated in a scratch registry makes
sufficiency computable without touching history; similar reports merge
only by recorded, reversible dedup decisions; a severe unreproduced
finding stays a finding — `NOT_REPRODUCED` is about attempts, the
report survives; a user-reported success is `USER_REPORTED`, never a
protocol PASS. All FIXTURE_DEMONSTRATION_ONLY.

## 10. Hardware evidence rehearsal (Track F — 6 scenarios)

Hardware truth is per-machine, per-dimension, forever. Machine
identity is required (a missing `hwId` refuses); the render dimensions
`companion-3d-native` and `companion-3d-fallback` are permanently
separate — an unknown dimension refuses; effective state is derived
per machine per dimension with divergence flagged; the aggregate claim
is structurally `null` and `hardware_claims()` always raises — a
finite machine set can never become "SUPPORTED ON PCS". Operator PII
(an email in operator or hwId fields) makes a submission INCOMPLETE
before ingestion. All FIXTURE_DEMONSTRATION_ONLY; the real hardware
gate remains EXTERNAL_EVIDENCE_REQUIRED.

## 11. Signing and approval rehearsal (Track G — 11 scenarios)

No real keys exist anywhere in this phase. A signing *drill* is
REJECTED at the boundary and rechecked at authorization — a rehearsal
of signing can never satisfy the signing gate. Approval hygiene:
the same person approving twice is REJECTED; a signer approving their
own signature is a separation-of-duties CONFLICT absent a recorded
overlap decision; an approval dated before the signature it approves
is `REQUIRES_HUMAN_DECISION` ("cannot have verified evidence that
postdates it"); unparseable dates fail closed. Authority standing is
evaluated per cut: an expired or revoked assignment stops acting at
the cut where it stopped standing. `subject_unsigned_problems()`
checks durable facts (ledger `signingStatus == UNSIGNED`, frozen,
graph ROOT identity) — deliberately not an emptiness assertion. The
candidate remains UNSIGNED. All FIXTURE_DEMONSTRATION_ONLY.

## 12. Conflict policy (Track C — 7 scenarios)

Conflicts resolve to the most blocking effective state via Phase 13's
own classifier, and the Phase 14 wrapper adds a wall: if a resolution
would make the effective assessment *more favorable* than the most
blocking observation, it raises `BoundaryViolation`. That wall has an
executed negative control — a stub engine returning a favorable
resolution is injected into the module cache and the raise is
observed, then the real engine restored. "More PASS than FAIL" does
not exist anywhere in the codebase; contradictory conclusions block
and both records survive; an internal test result attempting to become
a favorable state is refused with the absent floor named.

## 13. Sufficiency behavior

Sufficiency is owner policy applied to accepted evidence — never
inferred. Undefined policy is a terminal answer
(`SUFFICIENCY_POLICY_UNDEFINED`), not a default threshold; an active
fixture policy with insufficient evidence refuses; an active fixture
policy with sufficient evidence is satisfied *inside the scratch
universe only*. The real registry's policy remains undefined —
verified inside the same scenario that activates the fixture policy,
so the two can never be conflated. The real sufficiency gate remains
EXTERNAL_EVIDENCE_REQUIRED (and owner-policy-required).

## 14. Authorization assembly (Track H — 10 scenarios)

`assemble_decision(universe, as_of)` gathers everything — fixture
sweep over ledger entries, graph validation with a candidate-identity
check, a sealed cut, standing assignments at the as-of,
separation-of-duties violations, the five-source authorization floor,
sufficiency, risk and revocation validation, per-record time and
ordering flags — and then hands the state decision to Phase 13's own
most-restrictive-first ladder. There is no favorable shortcut: the
only AUTHORIZED it can report is one a validated external authority
record already made (full Phase 13 validation when the record was cut
against this ledger; the derived revocation/expiry state when cut
earlier). PROVEN: the real universe assembles to exactly the committed
Phase 13 state — EVIDENCE_PENDING, REQUIRES_MORE_EVIDENCE, zero
favorable rows; an empty fixture universe refuses; four of five floor
sources refuse naming the fifth; a floor member bound to the wrong
artifact counts as absent; unresolved security holds the ladder; a
fully-evidenced fixture universe reaches AUTHORIZED only through its
sealed record; a successor artifact inherits nothing. Every favorable
row identifies all eight required fields: intake ID, source, artifact
digest, validation result, binding, policy versions, as-of cut seal,
expiry status. The assembler writes nothing.

## 15. Time and expiry (Track I — 7 scenarios)

There are no clocks in this phase — a source scan in the test suite
refuses `datetime.now`, `date.today`, `time.time()`, and `utcnow`.
Time enters only as operator-stated `--as-of` and as dates inside
records. Screening fails closed: a future-dated record, a revision
dated before its original, an ambiguous time basis, and an unparseable
date each refuse rather than resolve favorably. Once any expiring
record exists, every standing evaluation without an explicit as-of
raises. An authorization evaluated past its `expires_at` derives
EXPIRED at that cut.

## 16. Revocation behavior

Revocation changes later decisions without rewriting earlier ones. A
revocation record accepted at a later cut makes the assembly at that
cut REVOKED; the earlier cut's AUTHORIZED is demonstrated by
re-assembling the earlier cut's inputs — the record set that existed
then — not by pretending the revocation away. Assignment revocations
(a Phase 14 fixture-universe-only shape; the real registry has none)
filter the standing-assignments *view* per cut; no record is ever
edited. Recorded acts at earlier cuts are never rewritten.

## 17. Fixture isolation

A Phase 14 fixture file carries all three markers (`fixtureClass:
"TEST_FIXTURE_ONLY"`, `fixture: true`, `test_fixture_only: true`);
`verify` refuses a committed fixture with fewer. Consumption is the
inverse: any one marker makes a record a fixture everywhere it is
read, so a partially stripped fixture is still refused. Five layered
walls, each executed on every run: the router (fixture first,
terminal), the Phase 9 boundary (`register` rejects the marker
structurally), the Phase 13 registries (`append_record` refuses;
sealed records cannot be edited into or out of fixture-hood), every
derivation independently, and the eighteen-file byte comparison.
Scratch registrations use the *inner* records — exactly what a real
submitter would send — so both directions are proven: the clean inner
record genuinely ACCEPTED in a scratch tree, the marked wrapper
genuinely REJECTED at the same boundary. The real intake tree carries
no marker anywhere (verified).

## 18. Real ledger integrity

PROVEN by byte comparison, before and after all 72 scenarios and both
test suites, on both validation targets:

| Input | State |
| --- | --- |
| `qualification/phase9/intake/LEDGER.json` | sha256 `b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`, 0 entries, byte-identical |
| Artifact graph | sha256 `77067de176684ac101e2211680be9d7708efcd690a80166766de855b540c7f18`, byte-identical |
| Security register | sha256 `a9a80f747bf6659606f6a729b582083eb46a5ec0715b501a468acf9db37e57ad`, byte-identical |
| Alpha register | sha256 `e21cbcd43f4f9a9d40f12ead9ea1d8493e0d0ce11769f74d9d77ca9c43adadb7`, byte-identical |
| All 9 Phase 13 governance registries, decision record, baseline, policy, status, blocking | byte-identical |

`MATRIX.json` pins these shas under `executedAgainst`, so the matrix
legitimately re-derives when real evidence arrives — drift is a signal,
not a defect, and `verify` distinguishes the two by re-executing.

## 19. Artifact applicability

Applicability comes only from the Phase 10 graph and recorded transfer
decisions — never from commit ancestry, version similarity, branch, or
build configuration. PROVEN across tracks: evidence bound to foreign
bytes is `DOES_NOT_APPLY`/`ARTIFACT_MISMATCH` at routing (A5), in
conflict handling (C4), in security review (D2, and a foreign-artifact
closure refuses with "does not transfer"), in alpha evidence (E4), in
hardware (F2), at the signing boundary (G2, G10), at the floor (H4),
and across an artifact edge (H10: a successor inherits nothing —
authorization never crosses an edge; evidence transfers only by
recorded decision).

## 20. Negative controls

Every wall has an executed failure branch — none is asserted by
reading code:

| Control | Executed refusal |
| --- | --- |
| Zero-match / multi-match classification | both refuse (A2, A3) |
| Fixture wrapper at the real registration code | REJECTED in scratch tree (A4, suite) |
| Wrong-artifact evidence | 9 distinct sites (§19) |
| Signing drill | REJECTED at boundary and at authorization (A7, G4) |
| Post-cut evidence | detected and named (B2) |
| Same-cut supersession | refuses (B8) |
| Expiry without `--as-of` | raises (B7, I7) |
| Favorable conflict resolution | raises via injected stub engine, restored after (C7, suite) |
| Internal JSON claiming AUTHORIZED | refused, absent floor named (C6, H2–H7) |
| Aggregate hardware claim | `hardware_claims` always raises; claim structurally null (F6) |
| PII in hardware submission | INCOMPLETE before ingestion (F) |
| Duplicate approver / signer-approves | REJECTED / CONFLICT (G5, G6) |
| Approval predating signature | REQUIRES_HUMAN_DECISION (G7) |
| Expired / revoked authority | stops acting at the cut (G8, G9, I1) |
| Future-dated / ambiguous / unparseable time | fail closed (I4–I6) |
| Tampered scratch ledger entry | seal broken → `SystemExit` (suite) |
| Sealed governance record edited | `IMMUTABILITY FAIL` (suite) |
| Mutated candidate identity | `CANDIDATE IDENTITY FAIL` (suite) |
| Successor inheritance | nothing crosses the edge (H10) |
| Both standing guards vs. the new tree | refused naming all 17 files, then declared (§25) |

## 21. Validation results

All 72 scenarios `AS_EXPECTED` on both targets. `MATRIX.json` derived
by execution in under a second, byte-identical across re-derivations
on Windows and on Fedora — the derived output is portable (a lesson
this repository has paid for before). All seven verification tools
exit 0 on both targets: Phase 9 intake, Phase 10 candidate ops, Phase
11 security review, Phase 12 alpha ops, Phase 13 release authority,
Phase 14 evidence execution, and `verify_phase14.py`.

## 22. Test discovery counts

Measured with `discover().countTestCases()` on both targets, never by
test ID:

| Suite | Before Phase 14 | After Phase 14 |
| --- | --- | --- |
| `tests/release` | 436 | **554** (+71 evidence execution, +47 decision rehearsal) |
| `tests/portability` | 205 | 205 |

Both new modules confirmed *inside* the discovered release suite (the
Phase 5 undiscovered-directory trap re-checked).

## 23. Windows results

Windows 11, Python 3.14.6, at commit `357fccb6`:

| Run | Result |
| --- | --- |
| Release suite | 554 tests, **OK** (skipped=1) in 7.8s |
| Portability suite | 205 tests, **OK** (skipped=3) in 76.7s |
| Both immutability guards | 13 tests, **OK** (after refusal + declaration) |
| All 7 verification tools | exit 0, clean |
| Matrix re-derivation | byte-identical |

The skips are the established environment-conditional skips from
earlier phases; no new skips were introduced.

## 24. Fedora reference-target results

Fedora 44 WSL2, as user `bunny`, from the ext4 clone
`/home/bunny/bunny-os-ref` at the same commit `357fccb6`:

| Run | Result |
| --- | --- |
| Discovery | release 554, portability 205 — identical to Windows |
| Release suite | 554 tests, **OK** (skipped=1) in 6.3s |
| Portability suite | 205 tests, **OK** (skipped=1) in 61.1s |
| Both immutability guards | 13 tests, **OK** |
| All 7 verification tools | exit 0, clean |
| Matrix re-derivation | byte-identical to the committed file |

No new failures on either target; nothing to classify.

## 25. Immutability guard demonstration

The two standing guards (`tests/release/test_frozen_evidence.py`,
`tests/companion/test_three_d_preservation.py`) were run against the
committed Phase 14 tree *before* declaration and both **FAILED their
added-files checks naming all 17 `qualification/phase14/` files** —
the designed refusal, captured at commit `bb16ef97`. The tree was then
deliberately declared in both `PHASES_AFTER_THE_RECORD` tuples (commit
`357fccb6`) with the reason recorded in place: `MATRIX.json` re-derives
from live pinned inputs, so the tree cannot be pinned; its
reproducibility guards are the two Phase 14 test modules. Both guards
pass after the declaration, on both targets.

## 26. Findings

1. **The assembler originally under-reported standing authorizations**
   (caught in design walkthrough, before any run): a REVOKED or
   EXPIRED authorization fell through to READY_FOR_AUTHORIZATION
   instead of surfacing its state. Fixed: standing rows carry whatever
   state Phase 13 derives, and the ladder puts REVOKED and EXPIRED
   first.
2. **The candidate-identity control was initially missing** from
   assembly (Track J requires "modify candidate artifact identity →
   FAIL"). Added: graph validation plus an active-candidate vs. ledger
   subject comparison — `CANDIDATE IDENTITY FAIL`. The matrix was
   re-derived afterward and was byte-identical.
3. **Historical revocation framing**: Phase 13's
   `authorization_state_of` returns REVOKED regardless of the
   revocation's timestamp, so "cut A was AUTHORIZED then" must be
   demonstrated by re-assembling cut A's *inputs*, not by an earlier
   as-of over the current record set. Scenarios B6/H9 are built that
   way; this is a property of the inherited engine, recorded here so
   nobody rediscovers it as a bug.

## 27. Limitations

1. Everything favorable in this phase is FIXTURE_DEMONSTRATION_ONLY.
   Nothing here is evidence about the subject artifact — a passing
   test of the machinery proves the machinery.
2. Governance acts (policy activation, risk acceptance, authorization)
   are rehearsed against scratch registries; the real registries hold
   only what Phase 13 left. The five-source authorization floor has
   zero real members.
3. Time semantics are rehearsed with operator-stated dates; no
   wall-clock reading exists to test against, by design.
4. Assignment revocation is a Phase 14 fixture-universe shape; the
   real Phase 13 registry has no revocation records and none were
   added.
5. The rehearsals prove the pipeline over the ten declared evidence
   classes. A real submission of a genuinely novel shape will refuse
   (zero-match) and require a human to extend the class table — that
   refusal is the designed behavior, not coverage.

## 28. What remains external

Unchanged from Phase 13, now with a rehearsed path for each:

| Gate | Status |
| --- | --- |
| Independent security review | EXTERNAL_EVIDENCE_REQUIRED |
| Alpha tester reports (and owner sufficiency policy) | EXTERNAL_EVIDENCE_REQUIRED |
| Hardware validation on real machines | EXTERNAL_EVIDENCE_REQUIRED |
| Artifact signing (real keys) | EXTERNAL_EVIDENCE_REQUIRED |
| Second-person approval | EXTERNAL_EVIDENCE_REQUIRED |
| Release authority assignment and authorization | EXTERNAL_EVIDENCE_REQUIRED |

## 29. Exact candidate state after Phase 14

Derived by assembling the real universe with the Phase 14 assembler
and confirmed identical to the committed Phase 13 status:

| Property | Value |
| --- | --- |
| Subject artifact | `e906a48793d7` — ROOT / FROZEN / UNCHANGED / UNSIGNED |
| Real external evidence | **0** |
| Real intake ledger | 0 entries, byte-identical to Phase 13 |
| Authorization | **NOT AUTHORIZED** |
| Authorization state | **EVIDENCE_PENDING** |
| Candidate decision | **REQUIRES_MORE_EVIDENCE** |
| Favorable evidence rows (real universe) | **[]** |

## 30. Commit / artifact inventory

| Commit | Content |
| --- | --- |
| `8246a922` | operations(phase14): tree — 9 docs, 5 fixtures, engine (~3,030 lines), gate wrapper, derived `MATRIX.json` (17 files, 4,511 insertions) |
| `bb16ef97` | tests(phase14): 118 tests in two release-suite modules (1,276 insertions) |
| `357fccb6` | guards(phase14): both guards declare the tree, refused first as designed (16 insertions) |
| (this commit) | report(phase14): this document |

No file outside `qualification/phase14/`, the two test modules, the
two guard declarations, and this report was touched. The working tree
is clean. The next deterministic action is unchanged since Phase 11
and is now fully rehearsed: a real independent security reviewer
executes `qualification/phase11/security-review/REQUEST.md` and their
submission enters through `qualification/phase9/tools/intake.py
register` — the first record the real pipeline receives will travel a
path that has already been driven end to end.

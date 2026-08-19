<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 15 — External Security-Review Execution & Evidence Activation

## STATUS: **PHASE 15 — EXTERNAL EVIDENCE PATH OPERATIONAL, AWAITING SUBMISSION**

**PHASE 15 DOES NOT AUTHORIZE THE ARTIFACT AND RECEIVED NO REAL
EVIDENCE.**

The subject artifact `e906a48793d7` remains ROOT, FROZEN, UNCHANGED,
UNSIGNED. The real Phase 9 intake ledger holds zero entries and is
byte-identical to its Phase 13/14 state. The derived security-review
receipt state is **AWAITING_SUBMISSION**, the security gate is
**AWAITING_EXTERNAL_EVIDENCE**, the authorization state is
**EVIDENCE_PENDING**, and the candidate decision is
**REQUIRES_MORE_EVIDENCE** — all derived from live inputs, none
hard-coded. What this phase built is the first-production-use
operational layer: a real reviewer can now receive a complete,
sha256-pinned handoff package and submit evidence without any
repository change, and every possible outcome of that submission —
acceptance, rejection, mismatch, revision, conflict, a new Critical,
or silence — already has an executed, fail-closed path.

## 1. Executive summary

Phase 14 proved the pipeline executable by rehearsing it; Phase 15
turns the highest-priority workflow — the independent security review —
into operator commands over the real universe.
`qualification/phase15/security-review-execution/tools/review_execution_ops.py`
composes the standing engines (Phase 9 intake, Phase 10 candidate ops,
Phase 11 reconciliation, Phase 12 alpha ops, Phase 13 authority,
Phase 14 routing/cuts/assembly) into `prepare-review`, `receive`,
`validate`, `reconcile`, `cut`, `assemble`, and `status`/`sync-status`,
each with explicit boundaries and no "latest automatically" behavior
anywhere. A derived receipt state machine tracks every submission with
**no favorable state in its vocabulary**; a derived identity ceremony
keeps the reviewer's observed digest permanently distinct from the
repository's expectation; the first real evidence cut (`CUT-001`) seals
the zero-evidence state; and `FAILURE_RECOVERY_MATRIX.json` is derived
by executing all 18 failure/recovery scenarios against the real engines
in scratch universes. One genuine defect was found and repaired in an
inherited engine (a new Critical finding crashed the Phase 11 gate
derivation instead of holding it) with an ownership-boundary control;
no historical conclusion changed. 85 new tests bring the release suite
from 554 to 639, green on Windows and on the Fedora 44 reference
target. Zero real submissions exist, and Phase 15 says exactly that.

## 2. Subject artifact identity

Unchanged from Phase 7, verified on every run by the composed
`subject_unsigned_problems` check and the byte comparison walls:

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

Nothing was rebuilt, replaced, re-signed, or re-identified. Every
Phase 15 operation that consumes artifact-specific evidence verifies
binding against these digests through the inherited engines, and a
mismatch fails closed (`ARTIFACT_MISMATCH` / `DOES_NOT_APPLY` /
`MISMATCH`, per layer).

## 3. Phase objective

Ensure that when real evidence arrives the repository can receive it
without altering it, reject unsafe or malformed submissions before
publication, classify without guessing, bind to the correct artifact,
preserve the original, reconcile against the correct baseline, surface
conflicts without averaging, create sealed evidence cuts, derive the
candidate state, and refuse authorization unless the complete Phase 13
floor is actually satisfied — without depending on any reviewer
actually responding. All ten capabilities are demonstrated over the
real engines; the favorable demonstrations are FIXTURE_DEMONSTRATION_ONLY
in scratch universes, and the real universe derives its honest
zero-evidence state.

## 4. Prior-state inputs

| Input | State consumed |
| --- | --- |
| Phase 9 ledger | sha256 `b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`, 0 entries |
| Phase 10 candidate status | `EVIDENCE_PENDING`, five external gates NOT_RUN |
| Phase 11 baseline | 8 Critical + 36 High, 44 identifiers, pinned to the Phase 8 package |
| Phase 11 register | gate `AWAITING_EXTERNAL_EVIDENCE`, all rows BASELINE |
| Phase 12 sufficiency | `SUFFICIENCY_POLICY_UNDEFINED` |
| Phase 13 status | `EVIDENCE_PENDING` / `REQUIRES_MORE_EVIDENCE`, floor missing all five sources |
| Phase 14 machinery | router, cuts, assembler, scratch universes — composed, not duplicated |

## 5. Real evidence boundary

Real evidence has exactly one door:
`qualification/phase9/tools/intake.py register`. Phase 15's `receive`
wrapper resolves explicit paths and calls the Phase 9 `register`
function — it has no append code, no pre-processing, and no opinion.
The guard suite demonstrates refusal equivalence on identical bytes per
class (credential material, private key, fixture marker, tampered
ledger), and a source-scan test proves the engine contains no ledger
append and writes only scratch ledgers. No second intake directory, no
direct-write shortcut, no trusted-reviewer bypass, and no special path
for security findings exists (`SUBMISSION_ROUTING.md`).

## 6. Security-review execution workflow

`EXECUTION_GUIDE.md` documents the exact path — reviewer → identity
recomputation → submission → Phase 9 intake → hygiene screening →
classification → binding → Phase 11 reconciliation → lifecycle
evaluation → sealed cut → Phase 14 assembly → Phase 13 evaluation —
with every step's input, output, responsible authority, mutation
surface, failure behavior, and recovery class (revision vs. new
submission). The operator commands have explicit boundaries
(`DECISION_BOUNDARY.md`): `prepare-review` creates no review, `receive`
decides nothing, `reconcile` invents no dispositions, `assemble`
manufactures no authorization, and every command takes explicit paths
and IDs or refuses ambiguity.

## 7. Reviewer handoff package

`prepare-review --out DIR` assembles the complete external handoff into
an operator-named directory outside the repository: the seven Phase 11
commissioning files, `REVIEW_HANDOFF.md` (request, scope, identity
instructions, acquisition, known limitations, baseline, schema, privacy
expectations, revision protocol, and the every-outcome-is-valid
section: finds-nothing, cannot-reproduce, cannot-obtain-or-boot,
unfavorable), two marked example submissions, and a sha256-pinned
`HANDOFF_MANIFEST.json`. The handoff states verbatim — and `verify` and
the guard suite refuse its absence:

> A reviewer may submit an unfavorable result. The intake system is not
> designed to convert that result into a favorable status.

The examples carry all three fixture markers plus the visible banner
(`TEST_FIXTURE_ONLY` / `NOT EXTERNAL EVIDENCE` / `NOT APPLICABLE TO THE
SUBJECT ARTIFACT`); the packaged copies are registered against the real
intake code in a scratch tree on every suite run and are REJECTED. The
packaged `VERIFY_SUBMISSION.py` is executed from the package copy:
exit 0 on a clean record, exit 2 on the marked example.

## 8. Artifact identity ceremony

`identity_ceremony(record, identity)` derives one of `VERIFIED` /
`OBSERVED_UNVERIFIED` / `MISSING` / `MISMATCH` (Phase 12's identity
vocabulary, asserted equal by test). The reviewer-observed field
(`independently_computed_digest`) is never written by the repository:
the ceremony is read-only (tested by before/after record equality), and
`VERIFIED` additionally requires the reviewer's stated measurement
(`digest_basis` + `digest_computation`). The §10 negative control is
executed: mechanically substituting the repository's expected digest
for an absent observation derives `OBSERVED_UNVERIFIED` with
`artifactSpecificAdvancement: false` — insufficient, never VERIFIED.

## 9. Receipt state machine

Derived, never stored (`RECEIPT_PROTOCOL.md`):
`AWAITING_SUBMISSION`, `RECEIVED`, `REJECTED`, `INCOMPLETE`,
`UNVERIFIABLE` (Phase 9's own word, kept), `DOES_NOT_APPLY`,
`ACCEPTED_FOR_RECONCILIATION`, `RECONCILED`,
`CONFLICT_REQUIRES_DECISION`, `SUPERSEDED`, `EXPIRED`.

There is no favorable state. `RECEIVED → APPROVED` does not exist
because `APPROVED` does not exist;
`ACCEPTED_FOR_RECONCILIATION → SECURITY_GATE_SATISFIED` does not exist
because the gate is a different derivation (Phase 11's, from
reconciliation output and Critical policy, never from receipt
bookkeeping). The guard suite executes the **entire forbidden-transition
cross product** — every (state, target) pair outside the table refuses —
and sweeps the vocabulary and every transition target for favorable
tokens. The six-way inequality
`REVIEWER_IDENTIFIED ≠ REVIEWER_INDEPENDENT ≠ REVIEW_SUBMISSION_VALID ≠
FINDINGS_RECONCILED ≠ SECURITY_GATE_SATISFIED ≠ ARTIFACT_AUTHORIZED`
is a table in `RECEIPT_PROTOCOL.md` mapping each claim to its own
derivation and inputs.

## 10. Intake validation

Demonstrated against the real Phase 9 registration code in scratch
universes (several starting as byte-copies of the real ledger):
credential material → REJECTED before ingestion with zero bytes copied
(secret-shaped content constructed at run time, never committed);
private key attachment → REJECTED before ingestion; unparseable JSON →
UNVERIFIABLE with bytes preserved; fixture marker → REJECTED
structurally; missing required fields → INCOMPLETE; foreign digest →
ARTIFACT_MISMATCH; tampered ledger → refusal to append at all. Intake
ACCEPTED remains distinct from contract-valid: a submission missing the
independent digest is ACCEPTED at the boundary, RECEIVED in the receipt
view, and contributes nothing until revised.

## 11. Baseline reconciliation

Through the real Phase 11 machinery, unchanged
(`RECONCILIATION_PROTOCOL.md` maps every required distinction to
Phase 11 vocabulary): addressed/confirmed/disputed/unresolved baseline
findings, new findings, not-applicable (analysis required at three
layers), accepted risk (five fields, authority, expiry), insufficient
evidence (`REQUIRES_FURTHER_ANALYSIS`), conflicting assessment
(`EVIDENCE_CONFLICT`). A reviewer saying "not exploitable" closes
nothing; closure still requires bound evidence at the CLOSED
transition. An omitted baseline finding stays in its prior state and is
counted: the omission scenario derives exactly 42 unaddressed rows from
a two-finding submission, and the count equals the rows still at
BASELINE — silence is measurable, in both directions.

## 12. New findings

First-class, demonstrated:
`baseline review + NEW_FINDING → expanded reconciled register` with the
original intake record untouched (sealed bytes compared), no
renumbering of `SEC-BL-001..044` (register IDs compared against the
committed baseline order), and no minted identifier (`internal_id`
stays None; triage IDs are assigned at triage, never by the register).
A new Critical enters the register and blocks until appropriately
resolved (§15 below).

## 13. Revision and supersession

All six required cases executed: valid → valid revision
(`INTAKE-001-R1`, original byte-identical, SUPERSEDED derived);
rejected → corrected revision (accepted beside the preserved
rejection); artifact mismatch → correct-artifact revision (gate-eligible);
revision of a nonexistent intake → refusal; alteration of immutable
source bytes → broken pin detected by `verify_intake`; supersession
after a cut → the historical cut re-derives exactly as sealed from its
own inputs and `compare_cut_to_ledger` names the revision as post-cut.
Derived views show the latest applicable revision; the ledger preserves
every original.

## 14. Conflict handling

All five required scenarios executed (`CONFLICT_POLICY.md`):

* **A** — APPROVED_WITH_CONDITIONS + BLOCKED derives
  `CONTRADICTORY_CONCLUSIONS`, effective assessment BLOCKED, receipt
  `CONFLICT_REQUIRES_DECISION`; resolution only through the recorded
  Phase 11 outcome vocabulary, and a favorable-direction resolution is
  refused (`apply_conflict_resolution` enforces the Phase 14 wall).
* **B** — a local re-derivation changes nothing about an accepted
  unfavorable review (executed equality of repeated derivations).
* **C** — an expired favorable authority confers nothing past
  `expires_at`; evaluation without an as-of refuses.
* **D** — a revocation makes the later assembly REVOKED while the
  earlier cut's inputs still re-derive AUTHORIZED — history is
  re-assembled, never rewritten.
* **E** — conflicting dispositions on one Critical derive
  `EVIDENCE_CONFLICT` and hold at UNDER_REVIEW; the executed
  no-majority control registers two favorable reviews against one
  blocking review and the effective assessment is still BLOCKED. No
  averaging exists anywhere.

## 15. Critical-policy execution

All six demonstrations executed over fixtures: (1) a confirmed
unresolved Critical appears in `critical_disposition_gaps` and the gate
is not SATISFIED; (2) NOT_APPLICABLE requires establishing analysis —
the bare transition refuses; (3) ACCEPTED_RISK without standing
authority is ineffective at the Phase 13 layer even with all fields
filled; (4) a valid acceptance stands exactly through its expiry date;
(5) and is EXPIRED after it; (6) a new Critical enters the register and
blocks, named by the reviewer's own identifier. The real register is
untouched: every row remains BASELINE.

## 16. Evidence cuts

The operator workflow is `cut --label CUT-NNN [--as-of DATE]`
(`EVIDENCE_CUT_PROTOCOL.md`), append-only under `cuts/`, over the
Phase 14 cut contract unchanged. PROVEN: same immutable inputs + same
explicit boundary → byte-identical cuts; post-cut evidence is named
(`postCutIntakeIds`), never absorbed; an existing label refuses;
`--as-of` is mandatory once any expiring record exists; a tampered cut
fails its seal. **CUT-001** is committed: the first real evidence cut,
sealing the zero-evidence state (`ledgerSha256 b24ef740…`, 0 entries,
0 gate-eligible, as-of 2026-08-19, seal `3e042c0fa7cf…`). It contains
no evidence — it identifies the absence, reproducibly.

## 17. Authority integration

Nothing about Phase 13 authority changed, and Phase 15 demonstrates the
walls again through composition: a reviewer assignment confers no
authority in any other registry; a signer holding second-approver is a
separation violation; an assignment expires and revokes per cut through
`standing_assignments`; risk acceptances and authorizations are
evaluated per cut and never edited. The real governance registries
remain exactly as Phase 13 left them: no assignment, no policy, no
acceptance, no authorization, no revocation.

## 18. Candidate-state derivation

Phase 15 asserts no candidate status of its own. `assemble` runs the
Phase 14 assembler over the real universe and the result equals the
committed Phase 13 status field-for-field (checked inside `verify` on
every run): authorization state EVIDENCE_PENDING, candidate decision
REQUIRES_MORE_EVIDENCE, favorable-evidence rows `[]`.
`EXTERNAL_STATUS.json` reports four permanently separate questions —
operational readiness (machinery), evidence state (counted), gate state
(Phase 11), candidate decision (Phase 13 ladder) — and the derived-not-
hard-coded property is tested by running the same derivation over a
scratch universe with one accepted review, which reports different
numbers from the same code.

## 19. Fixture isolation

Phase 15 fixtures carry all three markers (`fixtureClass`, `fixture`,
`test_fixture_only`); consumption is any-one-marker; the inner records
carry none (tested — otherwise the valid-path demonstrations would be
vacuous). Fixture-driven scenarios byte-compare all 18 real immutable
inputs plus Phase 15's own derived files and committed cuts before and
after — never asserting emptiness. The fixture-to-real-path scenario
registers the marked wrapper through the real registration code against
a byte-copy of the real ledger: REJECTED, "a fixture is never
evidence", and the real file byte-identical. The real intake tree
carries no marker anywhere (verified on every run).

## 20. Negative controls

Every §19 control of the brief is executed, not asserted:

| Control | Executed refusal |
| --- | --- |
| Malformed / credential / private-key / fixture intake | UNVERIFIABLE / REJECTED-before-ingestion ×2 / REJECTED (M05-M07, M15, suite) |
| Wrong digest | ARTIFACT_MISMATCH + DOES_NOT_APPLY (M03) |
| Expected digest substituted for observation | OBSERVED_UNVERIFIED, advancement false (suite) |
| Unrelated artifact inheriting applicability | nothing crosses an edge (Phase 14 H10 inherited; risk applicability digest-equality re-tested) |
| Omitted Critical | remains unresolved, counted (M09) |
| Conflicting reviewers averaging favorable | most-blocking wins; no-majority control (suite) |
| NOT_APPLICABLE without analysis | transition refuses (suite) |
| ACCEPTED_RISK without authority | ineffective (M13, suite) |
| Original record overwritten | pin breaks, verify names it (suite) |
| Invalid supersession | refusal (suite) |
| Post-cut revision rewriting a cut | cut re-derives as sealed (M16, suite) |
| Expired / revoked authority acting | stops at the boundary (suite) |
| Reviewer → signer by role | no cross-registry authority (suite) |
| Signer → second approver | separation violation (suite) |
| Internal JSON claiming AUTHORIZED | REFUSED, absent floor named (suite) |
| Fixture-only favorable satisfying the real floor | REJECTED at the door; floor still missing 5 (suite) |
| One gate satisfying the five-source floor | four sources still named missing (suite) |
| Tampered sealed record | seal broken, append refused (M17) |
| Candidate identity mutation | CANDIDATE IDENTITY FAIL (M18, suite) |
| Zero evidence → AUTHORIZED | never — assembly refuses, twice-derived equal (suite) |

## 21. Immutability demonstration

The standing ritual, performed in order:

1. **Refusal**: with the tree committed and undeclared, both guards
   FAILED their added-files checks naming all 17
   `qualification/phase15/` files — captured at commit `d886eae3`
   (tests commit; the operations commit `1b3a7957` is where the files
   land).
2. **Declaration**: commit `7689740a` adds `qualification/phase15/` to
   both `PHASES_AFTER_THE_RECORD` tuples with the reason recorded in
   place (the derived status, matrix, and append-only cuts re-derive
   from live inputs, so the tree cannot be pinned; its reproducibility
   guards are the two Phase 15 test modules).
3. Both guards pass after declaration (13 tests), on both targets.

Files covered: the 17 files of commit `1b3a7957` (12 documents/derived
files, 3 fixtures, the engine, the gate). No historical cut-time
exemption grew, neither guard was weakened, and **zero frozen
historical evidence changed** — no real external intake occurred.

## 22. Test discovery

Measured with `discover().countTestCases()` on both targets, never by
test ID, with `defaultTestLoader.errors` asserted empty:

| Suite | Before Phase 15 | After Phase 15 |
| --- | --- | --- |
| `tests/release` | 554 | **639** (+55 review execution, +29 evidence activation, +1 Phase 11 regression control) |
| `tests/portability` | 205 | 205 |

Both new modules are confirmed inside the discovered release suite by
module-name walk (the Phase 5 undiscovered-directory trap, re-checked),
and the discovery-error list is asserted empty so an import failure
cannot silently shrink the count.

## 23. Windows validation

Windows 11, Python 3.14.6, at commit `7689740a`:

| Run | Result |
| --- | --- |
| Release suite | 639 tests, **OK** (skipped=1) in 8.9s |
| Portability suite | 205 tests, **OK** (skipped=3) in 78.3s |
| Both immutability guards | 13 tests, **OK** (after refusal + declaration) |
| All 9 verification tools (phases 9-15 + both gates) | exit 0, clean |
| Matrix, status, CUT-001 re-derivation | byte-identical |

The skips are the established environment-conditional skips from
earlier phases; no new skips were introduced.

## 24. Fedora reference-target validation

Fedora 44 WSL2, as user `bunny`, from the ext4 clone
`/home/bunny/bunny-os-ref` at the same commit `7689740a`:

Fedora release 44, kernel `6.18.33.2-microsoft-standard-WSL2`, user
`bunny`, filesystem `/dev/sdd ext4` (the established reference
context), commit `7689740ab7b3800ae92a75a07446dd4cddec6177`, clean
checkout:

| Run | Result |
| --- | --- |
| Discovery | release 639, portability 205, discovery errors `[]` — identical to Windows |
| Release suite | 639 tests, **OK** (skipped=1) in 6.8s |
| Portability suite | 205 tests, **OK** (skipped=1) in 59.7s |
| Both immutability guards | 13 tests, **OK** |
| All 9 verification tools | exit 0, clean |
| Matrix re-derivation | byte-identical to the committed file |
| EXTERNAL_STATUS re-derivation | byte-identical, zero problems |
| CUT-001 re-derivation | byte-identical to the committed cut |

No failures on either target; nothing to classify (no NEW,
PRE_EXISTING, ENVIRONMENTAL, HARNESS, or NOT_REPRODUCED rows). The
Windows result is not claimed as authoritative over this reference
target; both agree.

## 25. Defects found

1. **Phase 11's gate derivation crashed on a new Critical finding**
   (`fix(phase11)`, commit `afe4ad6c`). `derive_security_gate` sorted
   open Criticals by bare `internal_id`, and a `NEW_FINDING` row
   carries `None` there by design — so a reviewer adding a new Critical
   under an approving assessment raised `TypeError` inside register
   derivation, the exact case where the gate must hold. Found the first
   time the branch was actually executed (Phase 15 scenario M08/M12;
   Phase 11's own new-Critical test used a BLOCKED assessment, which
   returns before the sort — and Phase 14's rehearsal inherited that
   shape). The failing control was executed before the repair.
2. The initial handoff-statement check compared raw markdown and missed
   the statement across a wrapped blockquote; fixed with normalization
   before the operations commit. Recorded here because the failure mode
   (a required-statement check that can be defeated by formatting) is
   worth remembering.

## 26. Corrections to prior claims

The Phase 11 repair changes **no historical conclusion**: the committed
zero-evidence register re-derives byte-identical after the fix
(`phase 11 verify clean` includes register reproducibility), the gate
naming changes only for rows that have never existed in the real
universe, and every prior phase's validation result stands. The repair
is guarded at its ownership boundary by a new test in
`tests/release/test_phase11_security_review.py`
(`test_a_new_critical_under_an_approving_review_holds_the_gate`).

## 27. Real external evidence received

**None.** Zero submissions of any kind were received during Phase 15.
The real ledger holds zero entries and is byte-identical to its
Phase 13/14 state (sha256
`b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`,
compared — not assumed — around every scenario run, both test modules,
and both verification gates). No reviewer evidence, approval evidence,
signing evidence, hardware evidence, or tester evidence was fabricated,
and none exists.

## 28. Real security-gate state

Derived from live inputs (`EXTERNAL_STATUS.json`, reproduced by
`verify` on every run):

```text
SUBJECT ARTIFACT:   e906a48793d7 — ROOT / FROZEN / UNCHANGED / UNSIGNED
SECURITY REVIEW:    receipt AWAITING_SUBMISSION
                    gate AWAITING_EXTERNAL_EVIDENCE
EXTERNAL EVIDENCE:  0 accepted real submissions (0 ledger entries)
AUTHORIZATION:      NOT AUTHORIZED (EVIDENCE_PENDING)
CANDIDATE DECISION: REQUIRES_MORE_EVIDENCE
OPERATIONAL:        pipeline ready — 18/18 scenarios AS_EXPECTED
                    (a statement about machinery, not the artifact)
```

These four lines are four separate derivations and are reported
separately everywhere; no operation collapses them into one status.

## 29. Limitations

1. Everything favorable in this phase is FIXTURE_DEMONSTRATION_ONLY.
   Operational readiness is a property of the machinery; it is not
   evidence about the subject artifact.
2. No real reviewer has been engaged. The handoff package is ready and
   pinned, but delivering it to a person is a human act outside the
   repository.
3. The identity ceremony's VERIFIED state proves a stated, matching,
   reproducible measurement exists — not that the reviewer's statement
   is honest. Credibility remains a human judgment recorded in triage.
4. The receipt state machine covers the security-review workflow;
   the other four evidence sources continue to route through the
   Phase 14 router without a Phase 15 receipt view of their own.
5. Conflict resolution is surfaced (`CONFLICT_REQUIRES_DECISION`) and
   vocabulary-checked, but an actual resolution remains a recorded
   human decision through the Phase 13 mechanism; none exists and none
   was fabricated.

## 30. Exact next required action

Unchanged in substance since Phase 11, now fully operational:

```text
Deliver qualification/phase11/security-review/REQUEST.md
and the Phase 15 handoff package (prepare-review --out DIR)
to an actual independent security reviewer.

Any resulting submission must enter through:

qualification/phase9/tools/intake.py register
(operationally: review_execution_ops.py receive)
```

If the reviewer approves, the gate still waits on Critical
dispositions and the other four floor sources. If the reviewer blocks,
the block stands and is preserved. If the reviewer never responds, the
state above remains exactly as written — **the artifact is not
AUTHORIZED, and nothing in this repository can make it so.**

## 31. Commit / artifact inventory

| Commit | Content |
| --- | --- |
| `afe4ad6c` | fix(phase11): new-Critical gate derivation repair (7 insertions, 1 deletion) |
| `1b3a7957` | operations(phase15): tree — 8 documents, derived status + matrix, CUT-001, 3 fixtures, engine (~1,600 lines), gate (17 files, 3,140 insertions) |
| `d886eae3` | tests(phase15): 85 tests — two release-suite modules + the Phase 11 ownership-boundary control (1,232 insertions) |
| `7689740a` | guards(phase15): both immutability guards declare the tree, refused first as designed (17 insertions) |
| (this commit) | report(phase15): this document |

No file outside `qualification/phase15/`, the Phase 11 engine repair,
the three test modules, the two guard declarations, and this report was
touched. The working tree is clean.

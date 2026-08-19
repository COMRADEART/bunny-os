<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 10 — External Evidence Operations & Candidate Evolution

## STATUS: **PHASE 10 — CANDIDATE OPERATIONS READY**

Not REMEDIATION IN PROGRESS — no accepted finding exists. Not
REQUALIFICATION IN PROGRESS — no successor artifact exists. Not ALPHA
AUTHORIZATION IN PROGRESS — no external evidence has arrived to evaluate.
Not ALPHA RELEASE BLOCKED — no external actor has returned a blocking
result. The operational system is built, tested including its refusals,
and waiting.

---

## 1. Executive summary

Phase 9 built the door evidence enters through; Phase 10 built what
happens on the other side, so that when real evidence arrives the project
can process it without losing provenance, mutating history, transferring
results between artifacts, silently changing gates, rebuilding without
cause, fixing without requalifying, or letting a new artifact inherit a
PASS it never earned. Concretely:

* a formal **artifact graph** with explicit relationships (ROOT /
  REMEDIATES / REBUILDS / EXPERIMENTAL / PARALLEL / SUPERSEDES), holding
  exactly one artifact: `e906a48793d7`, ROOT;
* an **evidence applicability engine** whose default across artifacts is
  DOES_NOT_APPLY — transfer exists only as a recorded decision with
  reasoning and a decider, riding on a recorded relationship;
* a **change impact model** whose component→domain mapping mirrors the
  build COPY roots (cross-checked against `build/Containerfile` by test)
  and fails closed on unmapped components;
* a **requalification planner** that emits REQUIRED / RECOMMENDED /
  NOT_REQUIRED / REQUIRES_HUMAN_REVIEW per qualification domain and
  cannot express PASS;
* a **candidate state machine** in which REMEDIATION_REQUIRED cannot
  reach AUTHORIZED, and AUTHORIZED is reachable only from ALPHA_READY
  past the Phase 9 authorization floor;
* a **finding lifecycle** in which nothing closes because code changed —
  closure requires requalification evidence bound to the finding's
  artifact;
* a **harness reinterpretation policy** whose corrections preserve the
  original verdict verbatim or are refused;
* a **derived candidate status** recomputable from immutable inputs, with
  append-only state history and exactly one next action;
* seven **dry-run fixtures**, each structurally marked TEST_FIXTURE_ONLY
  and refused everywhere evidence is consumed — including by Phase 9
  registration itself, which now REJECTS a marked record;
* and the third run of the standing demonstration: **both immutability
  guards refused the Phase 10 tree** until it was declared deliberately
  (commit `f9fbd60b` fails both guards; `62124f1b` declares).

No artifact was rebuilt. No evidence was fabricated. The subject artifact,
its ledger, and its decision record are exactly as Phase 9 left them.

## 2. Phase 9 baseline

`PHASE 9 — EXTERNAL EVIDENCE INTAKE IN PROGRESS` at head `82d90dcb`.
Sealed append-only intake ledger with zero intakes; decision record
`MORE_EVIDENCE_REQUIRED`; conditions 1, 2, 7, 8 true; the repository
mechanically unable to authorize itself. All of it carried forward
unmodified — Phase 10 reads the Phase 9 trees and writes nothing into
them.

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

Frozen, unchanged, not rebuilt — §14 honored: no rebuild happened merely
to demonstrate the workflow; CANDIDATE-NEXT exists only as a modelled
control inside tests and is nowhere claimed to exist.

## 4. Artifact graph

`qualification/phase10/artifacts/artifact-graph.json`. Each record:
artifact_id, digest, digests, source_commit, build_identity,
parent_artifact, supersedes, relationship, qualification_state.
Relationships are recorded explicitly and validated (`validate_graph`):
exactly one ROOT; every non-ROOT names an existing parent — the validator's
message for a parentless artifact says why: relationships are **never
inferred from commit history**. Today the graph holds one artifact:
`e906a48793d7`, ROOT, parent null, state EVIDENCE_PENDING, with an empty
transfer-decision list and the transfer policy stated in the file.

## 5. Evidence applicability model

`evaluate_applicability(evidence, target, graph)` →
APPLIES / DOES_NOT_APPLY / PARTIALLY_APPLIES / REQUIRES_REVIEW /
ARTIFACT_MISMATCH. Evidence binding to the target's own digests APPLIES;
binding to no graph artifact is ARTIFACT_MISMATCH; binding to a
*different* artifact is **DOES_NOT_APPLY by default**. A transfer happens
only through a recorded decision (fromArtifact, toArtifact, evidenceScope,
result, reasoning, decidedBy, date) riding on an explicit relationship
edge; a decision missing its reasoning, or joining unrelated artifacts,
transfers nothing — both refusals are tested. "The change looks unrelated"
is not a mechanism, and a fixture-marked record raises instead of
evaluating.

## 6. Change impact model

`qualification/phase10/impact/component-domains.json` maps every
repository component to domains (the fifteen §4 areas), with
`productAffecting` mirroring reality: the build COPY roots from
`build/Containerfile` — `docs/` included, because docs/ ships in the
image — plus `.containerignore`, which shapes what those COPYs ship.
Tests cross-check every COPY root against the mapping and every mapping
prefix against the repository. `build_impact` produces
`impact/<artifact>.json` per new artifact; a companion change affects
COMPANION / VOICE / TRUST / ACCESSIBILITY / PERFORMANCE and not INSTALLER
or BOOT — asserted, not assumed. Unmapped components land in
`unmappedComponents` and fail closed downstream. No impact records exist:
no artifact beyond ROOT does.

## 7. Requalification planner

`plan_requalification(impact)` emits one of **REQUIRED / RECOMMENDED /
NOT_REQUIRED / REQUIRES_HUMAN_REVIEW** with a reason, for every
qualification domain (the fourteen product areas plus HARDWARE). Fixed
rules: SECURITY and RELEASE are REQUIRED for any product-affecting new
artifact — their evidence binds to exact bytes; HARDWARE is
REQUIRES_HUMAN_REVIEW for any new artifact — a machine is not a
component; unmapped changed components force REQUIRES_HUMAN_REVIEW over
every domain that would otherwise relax; harness-only change sets plan
nothing. **The planner never outputs PASS**: the vocabulary cannot
express it and `validate_plan` fails a plan that smuggles one. It plans
work; only evidence produces PASS.

## 8. External evidence workflow

`candidate_ops.py sync` derives `qualification/phase10/candidate-status.json`
from the Phase 9 ledger (**read, never written** — asserted byte-for-byte
by test), the artifact graph, both findings registries, and the
pre-committed decision record: gate-eligible ACCEPTED intake → source →
artifact → applicability verdict → gate; open findings; blocking
conditions; required and completed qualification; exactly one next
action. Previous decision states are preserved: state history is
append-only, a sync that would lose an entry refuses, and derivation
without a seeded history refuses rather than inventing one.

## 9. Finding lifecycle

IDs `(SEC|HW|ALPHA)-(P9|EXT)-NNN`; the ID assigned at first triage is the
ID for life (Phase 9's `-P9-` registry and Phase 10's `-EXT-` operations
are one namespace, no renumbering). The lifecycle:
RECEIVED → VALIDATED → TRIAGED → REPRODUCTION_PENDING →
CONFIRMED | NOT_REPRODUCED; CONFIRMED → FIX_REQUIRED | ACCEPTED_RISK |
DEFERRED; FIX_REQUIRED → FIXED → REQUALIFIED → CLOSED. FIXED→REQUALIFIED
requires requalification evidence naming its artifact; REQUALIFIED→CLOSED
requires that artifact to be the finding's; ACCEPTED_RISK→CLOSED requires
the full acceptance record (risk, owner, affected artifact, rationale,
review date). **A finding is never closed because code changed** — the
premature closures are executed refusals, not policy prose. Zero findings
exist (`qualification/phase10/findings/registry.json`).

## 10. Remediation boundary

`validate_remediation` fails a change set touching product-affecting
components without a new artifact identity, and fails a new identity
claimed without a product-affecting cause — both directions tested,
including the repo-specific case that a `docs/` edit is a product change
here. `e906a48793d7` is never modified; Phase 4–9 evidence is never
rewritten; an old artifact becomes a historical record and a new one
starts its own qualification path with its own graph entry.

## 11. Harness reinterpretation policy

A harness-only change creates no product artifact but may invalidate an
interpretation. Corrections classify as PRODUCT_STATUS_UNCHANGED /
EVIDENCE_REINTERPRETED / PRIOR_FALSE_PASS_FOUND / PRIOR_FALSE_FAIL_FOUND
and land in `qualification/phase10/harness-corrections.json`, each
preserving the original verdict and its evidence reference verbatim
beside the correction, the reason, and the corrected verdict.
`validate_harness_correction` refuses a correction without its history,
and a FALSE_PASS claim with an unchanged verdict contradicts itself and
is refused. Zero corrections exist.

## 12. Candidate state machine

Ten states, every allowed transition declared in
`CANDIDATE_TRANSITIONS`, everything undeclared refused — the full
state-pair sweep executes every refusal on every test run.
**REMEDIATION_REQUIRED → AUTHORIZED does not exist**: the fix produces a
new artifact, a new candidate, FROZEN → REQUALIFICATION_REQUIRED →
EVIDENCE_PENDING on its own evidence. AUTHORIZED is reachable only from
ALPHA_READY, only with the decision record and intake ledger in context,
only past the Phase 9 authorization floor, and only with a named decision
authority — the pass branch is tested with constructed floor evidence,
and authority itself stays human.

## 13. Negative controls

Every §12 control exists and its failure branch executes on every run:

| Control | Result |
| --- | --- |
| Evidence for artifact A evaluated against B | DOES_NOT_APPLY, "the default is no transfer" |
| Recorded transfer decision with relationship and scope | PARTIALLY_APPLIES with the decider named |
| Decision without reasoning / without relationship | DOES_NOT_APPLY — an incomplete decision transfers nothing |
| Product change without new artifact identity | FAIL (`validate_remediation`) |
| Harness correction of a false PASS | history preserved verbatim; correction without the original refused |
| Planner asked to output PASS | FAIL (`validate_plan`: "the planner plans work, it never grades it") |
| REMEDIATION_REQUIRED → AUTHORIZED directly | refused (`BoundaryViolation`) |
| Fixture registered as evidence | REJECTED by Phase 9 `register`; refused by applicability and derivation |

## 14. Validation

Windows: release suite **220 tests** (152 prior + 68 new), portability
suite **205 tests**, both immutability guards, all clean; discovery
verified explicitly — `discover().countTestCases()` reports 220 and lists
both `test_phase10_model` and `test_phase10_operations`, so the new tests
are actually reached by the project runner, not merely present. Reference
target (ext4, as `bunny`, at `62124f1b`): release 220 and portability 205,
clean, discovery re-verified there. The guard demonstration: commit
`f9fbd60b` fails both immutability guards (eleven-plus files named);
`62124f1b` declares the tree and passes.

## 15. Current candidate status

`qualification/phase10/candidate-status.json`, derived and reproducible:
candidate `e906a48793d7`, parent null, state **EVIDENCE_PENDING**
(history: FROZEN → EVIDENCE_PENDING, both entries dated and grounded),
zero applicable evidence, zero open findings, five external gates
required, two internal gates completed. The dashboard view is
`PHASE10_CANDIDATE_OPERATIONS.md`.

## 16. External evidence inventory

Zero intakes across all five sources — accepted 0, incomplete 0,
rejected 0, pending 0. The Phase 9 ledger remains the single evidence
store; Phase 10 created no duplicate storage and wrote nothing into the
intake tree.

## 17. Open findings

None. The registries hold zero findings; nothing exists to triage,
remediate, or close, and zero is recorded as zero.

## 18. Blocking conditions

Unchanged from Phase 9, none weakened: conditions **1, 2, 7, 8 TRUE**
(review absent, Criticals undispositioned, unsigned, no second approval —
absence blocks), **6 FALSE** (identity verifies), **3, 4, 5, 9, 10
UNDETERMINED** (no testing evidence either way). Carried verbatim into
the derived status and asserted equal to the pre-committed record by
test.

## 19. Next required action

Exactly one: **commission the independent security review**
(`qualification/phase8/security-review/PACKAGE.md`). It is the
longest-lead external item and the only single action that can move two
blocking conditions (1 and 2). Signing, second approval, hardware, and
tester enrollment remain waiting behind it, each with its package ready —
no tie, by construction: the next action is computed by a deterministic
priority ladder, not chosen per report.

## 20. Limitations

* Every external gate remains NOT_RUN; this phase moved none of them and
  could not have.
* The applicability engine's transfer path has never processed a *real*
  transfer decision — the graph's decision list is empty, and the tested
  behavior is on constructed graphs. The first real transfer decision
  should be reviewed by a person against the recorded reasoning.
* The impact mapping is directory-granular; a surgical change inside a
  broad component (e.g. one file in `build/`) plans conservatively wide.
  Over-requalification is the designed failure direction, but it costs
  real work.
* The candidate state machine's AUTHORIZED guard verifies evidence
  existence and floor, not authority authenticity — verifying that a
  named decision authority is real remains a human act, as it must.
* Harness reinterpretation has vocabulary and validation but no real
  correction has flowed through it; the first one will exercise the
  policy against a genuine historical verdict.

# PHASE 10 — CANDIDATE OPERATIONS READY

The frozen artifact is evidence of what was built. External evidence is
evidence of what happened outside the repository. A remediation is
evidence of what changed. A new artifact is a new object, and
qualification belongs to the artifact that was actually tested. No amount
of green history is silently inherited — the boundaries are now
enforceable, and enforced.

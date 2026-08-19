# Phase 10 candidate operations model

Phase 9 built the door evidence enters through; this tree is what happens on
the other side. Every boundary below is enforced by
`tools/candidate_ops.py` and executed — including its failure branches — by
`tests/release/test_phase10_model.py` and `test_phase10_operations.py`. The
model exists so that processing real evidence cannot lose provenance,
mutate history, transfer a PASS between artifacts, silently change a gate,
rebuild without cause, fix without requalifying, or let a new artifact
inherit results it never earned.

## The artifact graph

`artifacts/artifact-graph.json`. Every artifact records its identity
(artifact_id, digest, digests, source_commit, build_identity), its
parentage (parent_artifact, supersedes), one relationship — **ROOT /
REMEDIATES / REBUILDS / EXPERIMENTAL / PARALLEL / SUPERSEDES** — and its
qualification_state from the candidate state machine. Relationships are
recorded explicitly; nothing is inferred from commit history. Exactly one
ROOT exists: `e906a48793d7`. A dry run may model CANDIDATE-NEXT inside a
test's constructed graph; a modelled candidate is never recorded as
existing.

## Evidence applicability

`evaluate_applicability(evidence, target, graph)` answers *does this
evidence apply to this artifact?* with one of **APPLIES / DOES_NOT_APPLY /
PARTIALLY_APPLIES / REQUIRES_REVIEW / ARTIFACT_MISMATCH**.

* Evidence binding to the target's own digests: APPLIES.
* Evidence binding to no artifact in the graph: ARTIFACT_MISMATCH.
* Evidence binding to a *different* artifact: **DOES_NOT_APPLY** — the
  default. Transfer happens only through a recorded transfer decision
  (scope, result, reasoning, decider, date) riding on an explicit
  relationship edge. A decision missing its reasoning or its relationship
  transfers nothing. "The change looks unrelated" is not a mechanism.
* A record declaring `fixtureClass: TEST_FIXTURE_ONLY` is refused outright.

## Change impact

`impact/component-domains.json` maps every repository component to
qualification domains, with `productAffecting` mirroring the build COPY
roots in `build/Containerfile` (cross-checked by test) plus
`.containerignore`. `build_impact(parent, new, changed, mapping)` produces
`impact/<artifact>.json`: changed components, their domains, whether the
product changed, and — fail-closed — every unmapped component. A companion
renderer change affects COMPANION, VOICE, TRUST, ACCESSIBILITY,
PERFORMANCE; it does not automatically affect INSTALLER or BOOT, and the
mapping saying so is committed and tested, not assumed.

## Requalification planning

`plan_requalification(impact)` emits, per qualification domain (the
fourteen product areas plus HARDWARE): **REQUIRED / RECOMMENDED /
NOT_REQUIRED / REQUIRES_HUMAN_REVIEW**, each with a reason. Fixed rules:
SECURITY and RELEASE are REQUIRED for any product-affecting new artifact
(their evidence binds to exact bytes); HARDWARE is REQUIRES_HUMAN_REVIEW
for any new artifact (a machine is not a component); unmapped changed
components force REQUIRES_HUMAN_REVIEW over every domain that would
otherwise relax. **The planner has no PASS.** It plans work; only evidence
produces PASS, and `validate_plan` fails any plan claiming otherwise.

## The external evidence workflow

`sync` derives `candidate-status.json` from the Phase 9 ledger (read,
never written), the graph, the two findings registries, and the
pre-committed decision record: gate-eligible ACCEPTED intake → source →
artifact → applicability → gate; open findings; blocking conditions;
required and completed qualification; exactly one next action. State
history is append-only — a sync that would lose an entry refuses. The
release decision is reproducible from immutable inputs, and the
reproducibility is a test, not a promise.

## Finding lifecycle

IDs `(SEC|HW|ALPHA)-(P9|EXT)-NNN` — the ID assigned at first triage is the
ID for life. States and transitions:

    RECEIVED → VALIDATED → TRIAGED → REPRODUCTION_PENDING
        REPRODUCTION_PENDING → CONFIRMED | NOT_REPRODUCED
        CONFIRMED → FIX_REQUIRED | ACCEPTED_RISK | DEFERRED
        FIX_REQUIRED → FIXED → REQUALIFIED → CLOSED
        ACCEPTED_RISK → CLOSED (full acceptance record) | FIX_REQUIRED
        DEFERRED → FIX_REQUIRED | TRIAGED
        NOT_REPRODUCED → TRIAGED (new information)

FIXED → REQUALIFIED requires requalification evidence naming its artifact;
REQUALIFIED → CLOSED requires that artifact to be the finding's artifact.
**A finding is never closed because code changed.** Closing an accepted
risk requires risk, owner, affected artifact, rationale, and a review
date — no silent acceptance.

## Remediation boundary

`validate_remediation` fails a change set that touches product-affecting
components without a new artifact identity, and fails a new identity
claimed without a product-affecting cause. `e906a48793d7` is never
modified; Phases 4–9 evidence is never rewritten; the old artifact becomes
a historical record and the new one starts its own qualification path.

## Harness-only changes

A harness-only change creates no product artifact but may invalidate an
interpretation. Corrections are classified **PRODUCT_STATUS_UNCHANGED /
EVIDENCE_REINTERPRETED / PRIOR_FALSE_PASS_FOUND / PRIOR_FALSE_FAIL_FOUND**
and land in `harness-corrections.json`, each preserving the original
verdict and its evidence reference verbatim beside the corrected verdict,
the harness change, and the reason. `validate_harness_correction` refuses
a correction that fails to carry its history.

## Candidate state machine

    FROZEN → EVIDENCE_PENDING | REQUALIFICATION_REQUIRED
    EVIDENCE_PENDING → UNDER_REVIEW | BLOCKED | SUPERSEDED | RETIRED
    UNDER_REVIEW → ALPHA_READY | REMEDIATION_REQUIRED | BLOCKED
                 | EVIDENCE_PENDING | SUPERSEDED
    REMEDIATION_REQUIRED → BLOCKED | SUPERSEDED | RETIRED
    REQUALIFICATION_REQUIRED → EVIDENCE_PENDING | BLOCKED | RETIRED
    ALPHA_READY → AUTHORIZED | EVIDENCE_PENDING | BLOCKED | SUPERSEDED
    AUTHORIZED → BLOCKED | SUPERSEDED | RETIRED
    BLOCKED → EVIDENCE_PENDING | REMEDIATION_REQUIRED | SUPERSEDED | RETIRED
    SUPERSEDED → RETIRED
    RETIRED → (terminal)

Everything absent is refused. **REMEDIATION_REQUIRED cannot reach
AUTHORIZED**: the fix produces a new artifact, which is a new candidate
starting at FROZEN and passing REQUALIFICATION_REQUIRED on its own
evidence. AUTHORIZED is reachable only from ALPHA_READY, only with the
decision record and the intake ledger in hand, and only past the Phase 9
authorization floor — the repository cannot authorize itself from any
state.

## Fixtures

`fixtures/` holds synthetic dry-run material, each file declaring
`fixtureClass: TEST_FIXTURE_ONLY` at top level — the distinction is
structural, not a filename convention. Phase 9 `register` REJECTS a marked
record; the applicability engine and status derivation refuse marked
input; `verify` sweeps the real intake tree for markers. Tests exercise
acceptance flows using the fixtures' inner payloads inside constructed
scratch trees only — the real ledger never sees them.

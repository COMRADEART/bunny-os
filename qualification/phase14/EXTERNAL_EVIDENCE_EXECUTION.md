<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# External Evidence Execution

## The pipeline, end to end

When a real external record arrives, it travels exactly this path — the
path Phase 14 rehearses:

1. **Route** (`route_evidence`). The record resolves exactly one of ten
   evidence classes, its owning workstream, its destination (a Phase 9
   intake source or a Phase 13 registry), and its validator. Unknown
   and ambiguous classes refuse. A fixture marker is terminal.
2. **Validate without trusting the submitter.** Intake evidence answers
   the six Phase 9 questions (identity, artifact binding, timestamp,
   completeness, integrity, scope) and is scanned for likely
   credentials before a byte is ingested. Contract layers
   (Phase 11 submission schema, Phase 12 tester-report schema) are
   validated on top: intake ACCEPTED is not contract-valid.
3. **Bind to the artifact.** Every digest the record claims is
   recomputed against the subject's five digests. Foreign bytes derive
   `ARTIFACT_MISMATCH` / `DOES_NOT_APPLY`; applicability across
   artifacts follows the Phase 10 graph and recorded transfer decisions
   only — never ancestry, similarity, branch, or configuration.
4. **Reconcile.** Security submissions reconcile against the pinned
   44-finding baseline (Phase 11); tester reports derive findings,
   dedup relationships, and reproduction states (Phase 12); hardware
   records stay per-machine, per-dimension.
5. **Handle conflicts conservatively.** One policy, everywhere: nothing
   is averaged, the effective state is the most blocking one, and a
   conflict that needs interpretation derives
   `REQUIRES_HUMAN_DECISION` (`CONFLICT_POLICY.md`).
6. **Apply time.** Expiry and revocation are derived per evaluation
   date; an operator-stated `--as-of` is mandatory once any expiring
   record exists; undeterminable time fails closed
   (`EXPIRY_AND_TIME.md`).
7. **Activate policy without rewriting history.** An owner's threshold
   policy activates through `record policy`; earlier evaluations under
   earlier cuts re-derive unchanged.
8. **Determine sufficiency.** Against the active, artifact-applicable
   policy only; undefined thresholds keep every quantity of evidence
   `SUFFICIENCY_UNDETERMINED`.
9. **Assemble the decision** from immutable evidence over a sealed cut
   (`EVIDENCE_CUT_CONTRACT.md`, `DECISION_ASSEMBLY.md`).
10. **Refuse authorization** when any required input is absent,
    invalid, expired, revoked, conflicting, or bound to another
    artifact — the Phase 13 ladder, unchanged.

## What "rehearsal" means

Every step above runs against the **real code** — the Phase 9
registration function, the Phase 11 reconciler, the Phase 12 register
derivation, the Phase 13 validators and ladder — but inside a
**scratch universe**: a temporary intake tree seeded with the real
subject-artifact identity (read-only) and zero entries. The records are
`TEST_FIXTURE_ONLY` material. The scratch universe is deleted after
every scenario, and the real immutable inputs are byte-compared before
and after the run.

What a rehearsal proves: the machinery routes, validates, binds,
reconciles, refuses, and assembles correctly. What it can never prove:
anything about the subject artifact. The two are kept apart
structurally — see `FIXTURE_BOUNDARY.md`.

## The favorable-conclusion rule

Every favorable conclusion the assembler derives identifies its source
evidence, artifact digest, intake ID, validation result, applicable
policy versions, as-of cut seal, and expiry status (the
`favorableEvidence` rows of an assembly). A conclusion that cannot name
all of these is not derived. Missing evidence remains missing evidence.

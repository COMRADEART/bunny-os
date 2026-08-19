<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Execution guide — the independent security review, end to end

This is the exact path a real independent security review travels, from
reviewer to candidate decision. Every step names its input, its output,
the responsible authority, whether it can mutate persistent state, its
failure behavior, and whether a failure recovers through a revision or
requires a new submission. The engines are the standing Phases 9-14;
Phase 15 adds only the operator commands
(`tools/review_execution_ops.py`) and the derived views.

```text
Reviewer
   ↓
artifact identity independently recomputed
   ↓
review submission produced
   ↓
Phase 9 intake
   ↓
credential / hygiene screening
   ↓
classification
   ↓
artifact binding
   ↓
Phase 11 security reconciliation
   ↓
finding lifecycle evaluation
   ↓
sealed evidence cut
   ↓
Phase 14 assembly
   ↓
Phase 13 authorization evaluation
```

## Step 0 — Handoff (`prepare-review`)

| | |
| --- | --- |
| Input | operator-named destination directory (must not exist, must be outside the repository) |
| Output | the sha256-pinned handoff package: the Phase 11 commissioning files, `REVIEW_HANDOFF.md`, marked examples, `HANDOFF_MANIFEST.json` |
| Authority | the project operator |
| Mutates | nothing inside the repository |
| Failure | refuses on an existing destination, a destination inside the repository, a missing package file, an unmarked example, or a handoff that lost its unfavorable-result statement |
| Recovery | rerun with a valid destination; the command is idempotent in effect because it never overwrites |

## Step 1 — Reviewer recomputes the artifact identity

| | |
| --- | --- |
| Input | the artifact bytes in the reviewer's hands; `ARTIFACT_IDENTITY.json` |
| Output | the reviewer's own digest, recorded in `independently_computed_digest` (+ `digest_basis`, `digest_computation`) |
| Authority | the reviewer, alone — the repository's claim is explicitly not to be trusted |
| Mutates | nothing |
| Failure | a mismatch means the reviewer holds different bytes: stop, report exactly that (blocking condition 6) |
| Recovery | obtain the right bytes and restart; a review of other bytes satisfies nothing |

## Step 2 — Review produced, pre-checked (`validate`)

| | |
| --- | --- |
| Input | `record.json` per `SUBMISSION_SCHEMA.json`, plus attachments pinned in `attachmentDigests` |
| Output | contract verdict + derived identity-ceremony state (`VERIFIED` / `OBSERVED_UNVERIFIED` / `MISSING` / `MISMATCH`) |
| Authority | the reviewer (content); the contract (shape) |
| Mutates | nothing — validation is not acceptance, and the ceremony never writes the expected digest into the observed field |
| Failure | problems are listed; a fixture-marked record is refused outright |
| Recovery | fix and re-run; nothing has been submitted yet |

## Step 3 — Phase 9 intake (`receive`)

| | |
| --- | --- |
| Input | explicit record path, attachment paths, `--received-on`, `--submitted-by`, optional `--revises` |
| Output | one sealed, append-only ledger entry with an intake ID; the submission bytes preserved verbatim |
| Authority | the Phase 9 boundary — the wrapper only carries paths |
| Mutates | the real ledger and intake tree (append-only; the single door) |
| Failure | credential material → REJECTED before ingestion; fixture marker → REJECTED; unparseable → UNVERIFIABLE; missing fields → INCOMPLETE; foreign digest → ARTIFACT_MISMATCH; tampered ledger → refuses to append at all |
| Recovery | REJECTED needs a new submission; INCOMPLETE / UNVERIFIABLE / ARTIFACT_MISMATCH recover through a revision (`--revises INTAKE-NNN`), preserving the original |

Steps 3a-3c (hygiene screening, classification, binding) happen inside
the boundary, in that order: the credential scan runs before a byte is
ingested; the six validation questions classify the record; every
claimed digest is normalized and compared against the subject
artifact's five digests.

## Step 4 — Phase 11 reconciliation (`reconcile`)

| | |
| --- | --- |
| Input | the ledger (read-only), the pinned 44-finding baseline, the artifact graph |
| Output | the derived register `qualification/phase11/security-findings.json`: per-finding classifications, unaddressed baseline count, conflict record, gate state |
| Authority | the Phase 11 engine; dispositions stay human decisions |
| Mutates | only the derived register (recomputable; `verify` refuses drift) |
| Failure | a contract-invalid submission contributes nothing until revised; an unestablished conclusion is held at `REQUIRES_FURTHER_ANALYSIS`; conflicting reviews derive `EVIDENCE_CONFLICT` and hold |
| Recovery | revision for contract problems; recorded human decisions for dispositions and conflicts |

## Step 5 — Finding lifecycle evaluation

| | |
| --- | --- |
| Input | register rows + proposed transitions with their evidence context |
| Output | allowed transitions only (`SECURITY_FINDING_TRANSITIONS`); refusals for everything else |
| Authority | `AUTH-SECURITY-OWNER` for dispositions; the engine enforces the evidence each state requires |
| Mutates | the derived register on re-derivation |
| Failure | `NOT_APPLICABLE` without analysis, `ACCEPTED_RISK` without the full acceptance record, closure without bound evidence — each refuses |
| Recovery | supply the evidence the state requires; there is no silent path |

## Step 6 — Sealed evidence cut (`cut`)

| | |
| --- | --- |
| Input | `--label CUT-NNN`, operator-stated `--as-of` (mandatory once any expiring record exists) |
| Output | one sealed cut under `cuts/`, append-only |
| Authority | the project operator states the boundary; the cut derives |
| Mutates | adds one file under `cuts/`; never edits an existing one |
| Failure | an existing label refuses; a missing as-of with expiring records refuses; a broken seal later is `IMMUTABILITY FAIL` |
| Recovery | later evidence goes into a later cut; historical cuts are never rewritten |

## Step 7 — Phase 14 assembly (`assemble`)

| | |
| --- | --- |
| Input | the real universe (every committed input, read-only), an as-of |
| Output | the assembled decision: floor state, gate state, sufficiency, standing authority, favorable-evidence rows |
| Authority | none — the assembler gathers and never invents |
| Mutates | nothing |
| Failure | fixture-marked ledger entries, a mutated candidate identity, and expiring records without an as-of each abort |
| Recovery | not applicable; the assembler reports the state that exists |

## Step 8 — Phase 13 authorization evaluation

| | |
| --- | --- |
| Input | the assembly; the five-source floor; sealed authority records |
| Output | the authorization state from Phase 13's most-restrictive-first ladder; the candidate decision |
| Authority | `AUTH-RELEASE`, via a sealed record through `record authorization` — the repository can check the decision, never make it |
| Mutates | nothing (evaluation); a real authorization is a Phase 13 governance act with its own append mechanism |
| Failure | any missing floor source, unresolved Critical, standing conflict, expired or revoked authority keeps the state non-authorizing |
| Recovery | more external evidence; there is no other path |

## Derived views (`status`, `sync-status`, `build-matrix`)

`EXTERNAL_STATUS.json` reports the four separate questions
(`DECISION_BOUNDARY.md`); `FAILURE_RECOVERY_MATRIX.json` is derived by
executing every failure/recovery scenario against the real engines in
scratch universes. Both refuse drift under `verify` and neither is ever
hand-edited.

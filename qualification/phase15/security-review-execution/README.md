<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 15 — External Security-Review Execution

Phases 9-14 built and rehearsed the external-validation machinery.
This track is its first-production-use operational layer for the
deterministic highest-priority next action: the independent security
review. It makes the workflow executable by a real operator and a real
reviewer — handoff, receipt, validation, reconciliation, cuts,
assembly, status — while remaining correct if the first reviewer
rejects the artifact, finds a new Critical, submits malformed evidence,
revises, or never responds at all.

The invariant, enforced mechanically everywhere in this tree:

> The repository may prepare the decision, validate the evidence,
> preserve the evidence, and derive the consequence. It may not author
> the external evidence it requires.

## What is here

| File | Contents |
| --- | --- |
| `EXECUTION_GUIDE.md` | the end-to-end path with per-step inputs, outputs, authority, mutation, failure, recovery |
| `REVIEW_HANDOFF.md` | the human-facing reviewer handoff (packaged by `prepare-review`) |
| `RECEIPT_PROTOCOL.md` | the derived receipt state machine — no favorable state exists |
| `SUBMISSION_ROUTING.md` | one door: the Phase 9 intake; the wrapper contract that cannot weaken it |
| `RECONCILIATION_PROTOCOL.md` | how the Phase 11 machinery answers every reconciliation distinction |
| `CONFLICT_POLICY.md` | conflicts stay visible; most-blocking wins; no averaging, no majority |
| `EVIDENCE_CUT_PROTOCOL.md` | the operator cut workflow over the Phase 14 contract |
| `DECISION_BOUNDARY.md` | four questions kept separate; command boundaries |
| `EXTERNAL_STATUS.json` | derived: readiness / evidence / gate / decision (run `sync-status`, never hand-edit) |
| `FAILURE_RECOVERY_MATRIX.json` | derived: every failure/recovery scenario, executed (run `build-matrix`) |
| `cuts/` | append-only sealed evidence cuts over the real universe |
| `fixtures/` | marked examples (all three markers, always; the intake rejects them) |
| `tools/review_execution_ops.py` | the engine: composition over Phases 9-14, nothing re-implemented |
| `VERIFY_PHASE15.py` | the verification gate (exit 0 clean, exit 2 on any issue) |

## Commands

```
python qualification/phase15/security-review-execution/tools/review_execution_ops.py verify
python .../review_execution_ops.py prepare-review --out DIR
python .../review_execution_ops.py receive --record R.json [--attach F]... \
       --received-on DATE --submitted-by WHO [--revises INTAKE-NNN]
python .../review_execution_ops.py validate RECORD.json
python .../review_execution_ops.py reconcile [--record RECORD.json]
python .../review_execution_ops.py cut --label CUT-NNN [--as-of DATE]
python .../review_execution_ops.py assemble [--as-of DATE]
python .../review_execution_ops.py status | sync-status | build-matrix
python qualification/phase15/security-review-execution/VERIFY_PHASE15.py
```

## What is deliberately not here

- No record in the real Phase 9 ledger: zero real submissions exist,
  and the ledger is byte-compared before and after every scenario run.
- No second intake path, no trusted-reviewer bypass, no
  "latest automatically" selection anywhere.
- No favorable receipt state, no receipt→approval transition, and no
  vocabulary in which absence of evidence reads as anything but
  blocking.
- No change to the subject artifact `e906a48793d7`: ROOT, FROZEN,
  UNCHANGED, UNSIGNED.

## Placement note

The guard suites live at
`tests/release/test_phase15_review_execution.py` and
`tests/release/test_phase15_evidence_activation.py` — inside the
discovered release suite, exactly as Phases 9-14 placed theirs.

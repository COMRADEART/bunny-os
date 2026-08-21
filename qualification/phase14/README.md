<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 14 — External Evidence Execution and Decision Rehearsal

**This phase creates no evidence.** It proves that the pipeline built by
Phases 9–13 works end to end when real evidence eventually arrives:
routing, validation, artifact binding, reconciliation, conflict
handling, time and expiry, policy activation, sufficiency, and decision
assembly — every step exercised against `TEST_FIXTURE_ONLY` records in
scratch universes that die with the run.

The principle, enforced mechanically everywhere in this tree:

> A passing test of this machinery is not evidence about the subject
> artifact. The machinery being ready is the result; the evidence is
> still external.

## What is here

| File | Contents |
| --- | --- |
| `EXTERNAL_EVIDENCE_EXECUTION.md` | The end-to-end execution model and what "rehearsal" means |
| `EVIDENCE_ROUTING.md` | Track A: the ten evidence classes and the fail-closed router |
| `EVIDENCE_CUT_CONTRACT.md` | Track B: the sealed as-of decision cut |
| `CONFLICT_POLICY.md` | Track C: one conflict policy across every workstream |
| `EXPIRY_AND_TIME.md` | Track I: time semantics, expiry, revocation, the mandatory as-of |
| `DECISION_ASSEMBLY.md` | Track H: the assembler that gathers and never invents |
| `FAILURE_MODES.md` | The enumerated failure modes and their structural handling |
| `FIXTURE_BOUNDARY.md` | Track J: why fixtures cannot reach the real ledger |
| `MATRIX.json` | Derived: all 72 rehearsal scenarios, executed, every row `FIXTURE_DEMONSTRATION_ONLY` |
| `fixtures/` | Phase 14's own fixtures (all three markers, always) |
| `tools/evidence_execution_ops.py` | The engine: router, cuts, rehearsals, assembler, matrix, verify |
| `tools/verify_phase14.py` | The verification gate (exit 0 clean, exit 2 on any issue) |

## What is deliberately not here

- No record in the real Phase 9 ledger. The ledger's bytes are compared
  before and after every rehearsal — never asserted empty.
- No change to the subject artifact `e906a48793d7`: still ROOT, FROZEN,
  UNCHANGED, UNSIGNED.
- No threshold value, no authority assignment, no risk acceptance, no
  authorization, no revocation in any real registry.
- No new favorable vocabulary. The assembler derives states through
  Phase 13's own ladder; the router and validators compose Phases 9–13
  rather than re-implementing them.

## Commands

```
python qualification/phase14/tools/evidence_execution_ops.py verify
python qualification/phase14/tools/evidence_execution_ops.py build-matrix
python qualification/phase14/tools/evidence_execution_ops.py route <record.json>
python qualification/phase14/tools/evidence_execution_ops.py assemble [--as-of DATE]
python qualification/phase14/tools/verify_phase14.py
```

`MATRIX.json` is a derived output, exactly like the Phase 11/12
registers: `build-matrix` re-executes every scenario, and `verify`
refuses drift. When real evidence arrives, its `executedAgainst` pins
change and the matrix is re-derived — the demonstration record stays
honest about which world it ran in.

## Placement note

The brief sketches `tests/` inside this tree; the guard suites live at
`tests/release/test_phase14_evidence_execution.py` and
`tests/release/test_phase14_decision_rehearsal.py` instead — where the
release suite discovers them, exactly as Phases 9–13 placed theirs. A
test directory here would sit outside every suite count, which is the
Phase 5 undiscovered-tests failure this project already paid for.

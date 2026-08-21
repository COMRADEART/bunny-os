# Phase 16 — external security-review intake and gate execution

This directory is the operational intake layer for the first real independent
security-review submission. It does not contain a second ledger, a second
artifact-applicability policy, a second security gate, or a release authority.
The operator composes the Phase 9, 10, 11, 13, 14, and 15 engines in that
order and keeps their answers separate.

The subject is frozen artifact `e906a48793d7`, relationship `ROOT`, image
digest
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
and signing state `UNSIGNED`. Phase 16 never rebuilds, changes, or signs it.

At creation, no real external review exists. That fact is derived from the
Phase 9 ledger, not assumed by the tests. The scenario runner byte-compares the
real evidence universe before and after every fixture exercise, so these checks
remain valid after a genuine submission arrives.

## Operator

Run from the repository root:

```text
python qualification/phase16/tools/security_review_intake_ops.py prepare --out <outside-repository-directory>
python qualification/phase16/tools/security_review_intake_ops.py inspect --record <record.json> [--attach <file> ...]
python qualification/phase16/tools/security_review_intake_ops.py receive --record <record.json> [--attach <file> ...] --received-on YYYY-MM-DD --submitted-by <operator>
python qualification/phase16/tools/security_review_intake_ops.py validate <record.json> [--attach <file> ...] [--received-on YYYY-MM-DD]
python qualification/phase16/tools/security_review_intake_ops.py bind --record <record.json>
python qualification/phase16/tools/security_review_intake_ops.py reconcile [--record <record.json>]
python qualification/phase16/tools/security_review_intake_ops.py cut --label CUT-NNN [--as-of YYYY-MM-DD]
python qualification/phase16/tools/security_review_intake_ops.py assemble [--as-of YYYY-MM-DD]
python qualification/phase16/tools/security_review_intake_ops.py status
python qualification/phase16/tools/security_review_intake_ops.py sync-status
python qualification/phase16/tools/verify_phase16.py
```

`receive` is the only Phase 16 command that can hand a submission to intake,
and it delegates through the Phase 15 carrier to Phase 9 `register`. Inspection,
validation, binding, reconciliation of a supplied record, status, and assembly
are read-only. `reconcile` without `--record` refreshes the Phase 11 derived
register. `cut` appends to the single Phase 15 cut archive and refuses an
existing label.

## Six different answers

`INTAKE_STATUS.json` never compresses these into one word:

1. operational readiness — whether the path and controls execute;
2. receipt state — whether a submission crossed the boundary;
3. review assessment — what the reviewer concluded;
4. security gate — what Phase 11 derives;
5. authorization state — what Phase 13 derives;
6. candidate decision — the standing derived release decision.

An `ACCEPTED` receipt proves only boundary crossing. It is not review approval,
gate satisfaction, authorization, or a release decision.

The executable route matrix is `MATRIX.json`; the same execution renders the
operator-facing `FAILURE_RECOVERY_MATRIX.json`. Every hypothetical package is
wrapped with `TEST_FIXTURE_ONLY` and runs only through production code in an
isolated temporary universe.

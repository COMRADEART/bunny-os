<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Security review receipt states

Phase 15 derives a **receipt state** for the security review as a whole
and for every security-review intake individually. Derived means
derived: no receipt state is ever stored, hand-set, or written back into
the ledger — `receipt_state_of` and `derive_receipt_register` in
`tools/review_execution_ops.py` recompute it from the immutable inputs
(the Phase 9 ledger, the Phase 11 derived register, and any explicit
as-of boundary) on every call.

## The vocabulary

| State | Meaning | Recoverable? |
| --- | --- | --- |
| `AWAITING_SUBMISSION` | zero security-review intakes exist | by a submission arriving |
| `RECEIVED` | registered at the boundary, but not eligible for reconciliation (intake ACCEPTED while the Phase 11 contract is unsatisfied) | revision |
| `REJECTED` | never valid for this gate (credential hygiene, fixture marker, wrong category) | new submission |
| `INCOMPLETE` | required fields absent | revision |
| `UNVERIFIABLE` | the record or a claimed digest cannot be checked (Phase 9's established word for it — kept, not renamed) | revision |
| `DOES_NOT_APPLY` | binds to bytes that are not the subject artifact (`ARTIFACT_MISMATCH` at the boundary) | resubmission against the subject artifact, or an explicit recorded artifact relationship |
| `ACCEPTED_FOR_RECONCILIATION` | intake ACCEPTED, gate-eligible, contract-valid; reconciliation output not yet derived | — (advances by derivation) |
| `RECONCILED` | reconciliation output exists for this submission in the derived register | — |
| `CONFLICT_REQUIRES_DECISION` | accepted submissions disagree; an explicit recorded resolution is required | recorded conflict resolution |
| `SUPERSEDED` | a later revision of this chain exists (derived, exactly as Phase 9 derives it) | terminal for this entry |
| `EXPIRED` | the record carries `expires_at` and the explicit as-of boundary is past it | new submission |

`UNVERIFIABLE` extends the brief's minimum vocabulary because it is the
Phase 9 boundary's own word for a submission whose claims cannot be
checked; renaming it here would make the two layers disagree about the
same entry.

## What does not exist

There is **no favorable receipt state**. `APPROVED`, `SATISFIED`,
`PASS`, and `AUTHORIZED` are not in the vocabulary and the transition
table contains no edge into any such word — swept mechanically by the
guard tests, which walk every state's allowed successors and refuse a
favorable token anywhere in the machine. In particular:

* `RECEIVED → APPROVED` does not exist (there is no `APPROVED`).
* `ACCEPTED_FOR_RECONCILIATION → SECURITY_GATE_SATISFIED` does not
  exist. The security gate is a different derivation (Phase 11's
  `securityGate`), computed from reconciliation output and
  Critical-policy state — never from receipt bookkeeping. A submission
  in any receipt state moves the gate only through what its accepted,
  reconciled content actually establishes.

## The transition table

Receipt states resolve at derivation time, so the table below is the
set of *observable successions* — what the next derivation may report
for the same chain after new immutable facts (a registration, a
revision, a derived reconciliation, a recorded resolution, a later
as-of) exist. Anything absent is forbidden; the guard test executes the
sweep.

```text
AWAITING_SUBMISSION        -> RECEIVED | REJECTED | INCOMPLETE | UNVERIFIABLE
                              | DOES_NOT_APPLY | ACCEPTED_FOR_RECONCILIATION
RECEIVED                   -> ACCEPTED_FOR_RECONCILIATION | SUPERSEDED | EXPIRED
REJECTED                   -> SUPERSEDED
INCOMPLETE                 -> SUPERSEDED
UNVERIFIABLE               -> SUPERSEDED
DOES_NOT_APPLY             -> SUPERSEDED
ACCEPTED_FOR_RECONCILIATION-> RECONCILED | CONFLICT_REQUIRES_DECISION
                              | SUPERSEDED | EXPIRED
RECONCILED                 -> CONFLICT_REQUIRES_DECISION | SUPERSEDED | EXPIRED
CONFLICT_REQUIRES_DECISION -> RECONCILED | SUPERSEDED
SUPERSEDED                 -> (terminal)
EXPIRED                    -> (terminal at that as-of; a different as-of
                               re-derives, because nothing was stored)
```

Notes:

* A revision entry starts its own receipt state; the entry it revises
  derives `SUPERSEDED`. The original's stored bytes never change.
* `CONFLICT_REQUIRES_DECISION → RECONCILED` requires a recorded
  resolution in the allowed Phase 11 outcome vocabulary
  (`RESOLUTION_REQUIRED` pending, then `ADDITIONAL_REVIEW_REQUIRED`,
  `REMEDIATION_REQUIRED`, or `BLOCKED`); a resolution that would make
  the effective assessment more favorable than the most blocking
  observation is refused (`CONFLICT_POLICY.md`).
* `EXPIRED` never occurs without an explicit as-of: no clock is read
  anywhere in this phase, so expiry is only evaluable at an
  operator-stated boundary.

## Relation to the security gate

```text
REVIEWER_IDENTIFIED ≠ REVIEWER_INDEPENDENT ≠ REVIEW_SUBMISSION_VALID
≠ FINDINGS_RECONCILED ≠ SECURITY_GATE_SATISFIED ≠ ARTIFACT_AUTHORIZED
```

Each inequality is a separate derivation with its own inputs:

| Claim | Derived by | From |
| --- | --- | --- |
| reviewer identified | Phase 9 validation question 1 | the record's identity field |
| reviewer independent | a human, in triage | the declaration + operator judgment; never automation |
| submission valid | Phase 11 `validate_submission` | schema + cross-field rules |
| findings reconciled | Phase 11 `reconcile_submission` / register derivation | accepted, contract-valid records |
| gate satisfied | Phase 11 `derive_security_gate` | reconciliation output + Critical policy |
| artifact authorized | Phase 13 ladder via Phase 14 assembly | the five-source floor + sealed authority records |

A structurally valid review submission may still fail artifact binding,
be incomplete, introduce unresolved Critical findings, conflict with
another review, require risk acceptance, or leave the gate awaiting
further evidence. No layer in this table implies the next.

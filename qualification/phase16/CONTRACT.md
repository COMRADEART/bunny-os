# Phase 16 contract

## Scope

Phase 16 receives, classifies, validates, binds, reconciles, cuts, and reflects
an independent security review. It never authors a review, reviewer identity,
artifact observation, disposition, risk acceptance, or authorization. It does
not mutate the frozen subject artifact.

## Ownership and composition

| Concern | Owning engine | Phase 16 action |
| --- | --- | --- |
| immutable evidence intake and credential scan | Phase 9 | delegate explicit paths through Phase 15 |
| artifact graph and transfer policy | Phase 10 | call `evaluate_applicability` |
| submission contract, reconciliation, conflict, gate | Phase 11 | validate and derive |
| authority, risk acceptance, authorization floor | Phase 13 | display/evaluate only |
| evidence routing, sealed cuts, decision assembly | Phase 14 | call the standing functions |
| reviewer package, receipt workflow, cut archive | Phase 15 | extend and reuse |

The sha256 and byte-size pins in `CONTRACT_PINS.json` identify the exact Phase
11 and Phase 15 inputs under this layer. Pin drift is a refusal until a human
reviews and records the new pins.

## Boundary invariants

- The real evidence door is `qualification/phase9/tools/intake.py register`.
- No Phase 16 code opens the ledger in append mode, constructs a ledger entry,
  computes a substitute ledger seal, or writes below the real intake tree.
- A fixture marker is terminal at every real boundary.
- Expected identity is never copied into the reviewer-observation field.
- Foreign evidence defaults to `DOES_NOT_APPLY`; Git ancestry and reviewer
  intent are not artifact relationships.
- Receipt acceptance is not an assessment. Assessment is not gate
  satisfaction. Gate satisfaction is not authorization.
- The Phase 11 gate and Phase 13 decision ladder are displayed, never
  reimplemented.
- Every decision-time input is explicit. No wall clock is consulted.
- Real immutable inputs are compared by bytes, never by an assertion that a
  ledger is empty.

## Receipt vocabulary

The Phase 16 boundary states are `AWAITING_SUBMISSION`, `RECEIVED`, `REJECTED`,
`INCOMPLETE`, `UNVERIFIABLE`, `DOES_NOT_APPLY`, `ACCEPTED`, and the derived
`SUPERSEDED`. `APPROVED` is not a receipt state. Leaving a refused state needs a
new or revised submission; an original is never overwritten.

## Validation vocabulary

`COMPLETE` means all required fields are present. `VALID` means the full
contract, identity ceremony, credential hygiene, attachment integrity, and any
explicit time relation hold. `ACCEPTED` is a later Phase 9 intake outcome.
These are independent facts.

## Fixture contract

Every committed hypothetical submission has a wrapper carrying all three
markers: `fixtureClass: TEST_FIXTURE_ONLY`, `fixture: true`, and
`test_fixture_only: true`. The wrapper is rejected by real intake. Its unmarked
inner record may run only inside a temporary scratch universe through the same
production mechanisms. No fixture can transfer evidence or satisfy the Phase
13 floor.

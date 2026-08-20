# Reconciliation and security gate

Every gate-eligible accepted security-review intake follows one composition:

```text
Phase 9 immutable intake
  -> Phase 10 exact-artifact applicability
  -> Phase 11 contract validation and reconciliation
  -> Phase 11 security-gate derivation
  -> Phase 14 decision assembly over the Phase 13 floor
```

Phase 16 does not copy any of those rules.

## Evidence shapes

- A review with no new findings preserves every unaddressed baseline row.
- A baseline reassessment maps by public advisory, never by an invented
  internal ID.
- A new finding carries the reviewer's identifier with `NEW_FINDING`; the
  register mints no triage ID.
- An unestablished or undetermined finding remains under analysis.
- A `BLOCKED` overall assessment remains blocking even with no finding rows.
- Contradictory legitimate reviews are both preserved. Phase 11 derives the
  most blocking assessment and a required human resolution; it never averages
  or counts votes.

An approving assessment plus a new Critical executes the inherited regression
branch: a new finding has no internal ID, so Phase 11 names it by the reviewer's
identifier and holds the gate without attempting to sort `None` against
strings. A new non-Critical under-review row also remains unresolved; an
approving word cannot make an untriaged finding disappear.

## Critical findings and accepted risk

Reviewer prose recommending risk acceptance is not a risk-acceptance record.
The Phase 13 mechanism requires a sealed, artifact-bound, scoped, expiring
record by the assigned security owner. Wrong-artifact, expired, revoked, or
unauthorized acceptances sustain no favorable gate or decision and never
transfer to a successor.

## Gate meanings

The Phase 11 engine alone derives `AWAITING_EXTERNAL_EVIDENCE`,
`UNDER_ANALYSIS`, `BLOCKED`, `REMEDIATION_REQUIRED`, or `SATISFIED` from the
accepted applicable evidence set. Phase 16 displays that result.

- no external review stays awaiting;
- an accepted but contract-invalid review stays under analysis;
- an unresolved Critical cannot satisfy the gate;
- conflict stays human-decision/blocking;
- a foreign review does not apply;
- fixture evidence never enters the real set;
- only an inherited-policy-complete review set may derive `SATISFIED`.

Even `SATISFIED` is one gate, not release authorization. The scratch favorable
security-only scenario proves Phase 14/13 still names hardware, signing, second
approval, and Alpha feedback as missing.

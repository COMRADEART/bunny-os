# Decision governance: evidence cuts, authorization, expiry, revocation

## Evidence cut rules

Every authorization decision is explicit about what it decided over:

- **artifact identity** — `artifact_digest` + `artifact_identity`, which
  must be the intake subject's; anything else is `DOES_NOT_APPLY`;
- **evidence applicability** — only gate-eligible ACCEPTED intakes count,
  under Phase 10's applicability rules (default `DOES_NOT_APPLY` across
  artifacts);
- **policy version** — the active `SUFFICIENCY-POLICY-NNN` must be named
  in `policy_versions`;
- **evaluation time** — the operator-stated `--as-of` date recorded in
  the derived status (never a clock read);
- **decision time** — `decision_timestamp`, `issued_at`;
- **authority** — `authority` + `authority_role`, which must be an
  assigned `AUTH-RELEASE` identity;
- **the ledger itself** — `evidence_cut.ledgerSha256` pins the exact
  bytes of `LEDGER.json` the decision was cut against, with the intake
  IDs relied on. A cut naming different bytes than the ledger presented
  is refused: the derived decision must be reproducible from immutable
  inputs.

## The authorization floor

`AUTHORIZED` requires a gate-eligible ACCEPTED intake in **all five**
external-gate sources — `security-review`, `hardware`, `signing`,
`second-approval`, `alpha-feedback` — extending Phase 9's three-source
floor to the full release decision. On top of the floor: the security
gate `SATISFIED`, Alpha sufficiency `SUFFICIENT` under an active policy,
every blocking condition `FALSE` on evidence, no standing separation
violation, no expired risk acceptance, and signing evidence in the
`PRODUCTION ARTIFACT SIGNED` category — a drill satisfies nothing.

The repository derives at most `NOT_AUTHORIZED`, `BLOCKED`, or
`REQUIRES_MORE_EVIDENCE`. It checks `AUTHORIZED`; it never produces it.

## Expiry

Every authorization carries `issued_at` and `expires_at`. A record
without an expiry is **invalid** — there is no infinite authorization by
omission. At evaluation, `as_of > expires_at` derives `EXPIRED`
automatically; nobody flips the state by hand, and an evaluation that
needs an expiry answer without an operator-stated date refuses rather
than assuming.

## Revocation

`REVOCATION-NNN` records target one authorization, name the artifact,
the reason, the authority (an assigned `AUTH-RELEASE` or
`AUTH-SECURITY-OWNER` identity), the timestamp, and the evidence.

```
AUTHORIZED → REVOKED        allowed, with the record
REVOKED   → AUTHORIZED      refused, always
```

A new authorization is a new record evaluated from
`READY_FOR_AUTHORIZATION`. Revocation status is derived from the
revocations registry and never stored on the authorization record — a
stored flag would be an editable flag. Both records are sealed; editing
either is an `IMMUTABILITY FAIL`. Revocation outranks expiry.

## Successor artifacts

Authorization for artifact A is not authorization for artifact B. A
successor in the Phase 10 graph starts `NOT_AUTHORIZED` regardless of
its parent's state. Evidence applicability across the edge may be
evaluated under Phase 10's recorded transfer decisions; **authorization
and accepted risk may not** — there is deliberately no transfer branch
in either check.

## Conflict resolution

Contradictory external evidence — tester PASS vs FAIL, machine PASS vs
FAIL, reviewer NOT_AFFECTED vs owner CONFIRMED — is never averaged. The
default is `CONFLICT → REQUIRES_HUMAN_DECISION` with the unfavorable
assessment(s) effective and the deciding authority named per domain
(security → `AUTH-SECURITY-OWNER`, hardware → `AUTH-HARDWARE`, alpha →
`AUTH-ALPHA-PROGRAM`, release → `AUTH-RELEASE`). All evidence stays
visible beside the effective assessment and its reason. Only a sealed
resolution by the assigned domain authority changes the outcome.

## Decision priority

Most restrictive state wins, in this documented, tested order:

```
REVOKED > EXPIRED > REMEDIATION_REQUIRED > BLOCKED
        > EVIDENCE_PENDING > SECURITY_REVIEW_PENDING
        > ALPHA_EVIDENCE_PENDING > SUFFICIENCY_UNDEFINED
        > SUFFICIENCY_UNDETERMINED > REQUIRES_MORE_EVIDENCE
        > READY_FOR_AUTHORIZATION > AUTHORIZED
```

A condition TRUE **on absence of evidence** keeps the candidate in a
pending state (this project's established semantics: absence blocks, it
does not block-with-prejudice); a condition TRUE **on adverse evidence**
derives `BLOCKED`. Neither authorizes anything, and `UNDETERMINED` is
not cleared. Only a human authority record can change an underlying
condition — never the ordering.

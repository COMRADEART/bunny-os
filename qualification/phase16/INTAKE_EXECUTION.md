# Intake execution

## Prepare

`prepare --out <directory>` calls Phase 15's handoff builder, adds the Phase 16
handoff and ceremony documents, and writes a deterministic manifest. The
destination must not exist and must be outside the repository. The operation
creates no reviewer, review, receipt, or ledger entry.

## Inspect

`inspect` is read-only and returns exactly one pre-boundary class:
`STRUCTURALLY_VALID`, `INCOMPLETE`, `MALFORMED`, `WRONG_ARTIFACT`,
`AMBIGUOUS_IDENTITY`, `CREDENTIAL_BEARING`, `FIXTURE_MARKED`, or
`UNSUPPORTED_EVIDENCE_SHAPE`. Credential scanning happens over raw record and
attachment bytes before parsing. A successful inspection is not acceptance.

## Validate

`validate` executes the Phase 11 schema and cross-field validator, the identity
ceremony, Phase 9 credential classes, attachment sha256 checks, completeness,
and—when `--received-on` is supplied—Phase 14 explicit ordering checks. It
never fills a missing field or rewrites bytes. `COMPLETE`, `VALID`, and
`ACCEPTED` are reported separately.

## Receive: the one door

`receive` resolves explicit paths and delegates to the Phase 15 carrier, which
calls Phase 9 `register`. Phase 9 scans credentials before ingestion, preserves
accepted/incomplete/malformed original bytes, computes file pins, seals the
entry, and appends once. Phase 16 contains no direct append implementation.

On a credential hit, Phase 9 records only a sealed refusal entry: no submitted
file is copied beneath intake. The reason names the credential class and
filename, never the matching value. The real ledger byte identity is checked
around every scratch exercise.

Inspection should normally precede receipt, but inspection cannot pre-authorize
the boundary: Phase 9 repeats its own authoritative checks. A malformed real
submission is not cleaned up; its original bytes and `UNVERIFIABLE` outcome
remain evidence about the receipt process.

## Bind

`bind` calls Phase 10 `evaluate_applicability`. Exact subject bytes derive
`APPLIES`. Missing/unknown digests do not become artifact-specific evidence.
Another artifact derives `DOES_NOT_APPLY` unless a complete transfer decision
names an explicit graph relationship, scope, reasoning, decider, and date.
Commit/branch ancestry is never consulted.

# Evidence cut policy

Phase 16 reuses the Phase 15 append-only cut archive and Phase 14 cut schema.
It does not create a parallel `cuts/` directory.

A cut pins the subject artifact digests, exact ledger bytes and included intake
IDs, artifact graph, security and Alpha registers, policy versions, authority
records, risk-acceptance states, authorization/revocation/resolution records,
and the explicit `asOf` boundary. Phase 14 computes a deterministic seal over
that record.

Rules:

- labels match `CUT-NNN` and an existing filename is never overwritten;
- the moment an expiring input exists, `--as-of` is mandatory;
- `as-of` is an exact valid calendar date supplied by the operator, not a clock
  read and not `latest`;
- evidence appended after a cut is excluded and named by intake ID;
- an edit breaks the seal; a resealed ledger differs from the cut's ledger
  sha256;
- a later assembly supersedes an earlier one only with a different sealed cut;
- current revocation affects a current cut but cannot rewrite a valid earlier
  cut whose explicit date predates the revocation;
- historical reconstruction uses the earlier universe's immutable inputs,
  never mutable current status as a shortcut.

`CUT-001` remains the Phase 15 historical cut. While real inputs remain the
same it re-derives byte-identically; after a legitimate append it remains
valid as history and the comparison names every post-cut intake instead of
expecting current inputs to reproduce old bytes.

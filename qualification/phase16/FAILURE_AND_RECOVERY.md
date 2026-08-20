# Failure and recovery

`FAILURE_RECOVERY_MATRIX.json` is generated from the same scenario execution
as `MATRIX.json`; it is not a hand-maintained checklist. Each row records the
scenario ID, expected and observed result, recovery path, fixture designation,
and sha256 identities of the ledger, graph, security register, and baseline.

The executed controls include absence, malformed JSON, missing/substituted/
wrong/ambiguous identity, foreign artifacts, private and nested credentials,
attachment credentials, incomplete findings, new Criticals, contradictory
reviews, post-cut evidence, revisions, ledger and cut tampering, expired risk,
revoked authority, internal authorization claims, real fixture rejection,
unsupported evidence shapes, historical reconstruction, and a favorable
security-only gate with an incomplete authorization floor.

Recovery never edits a sealed original:

- malformed, incomplete, or sanitized material returns as a named revision;
- wrong-artifact material remains non-applicable unless the Phase 10 recorded
  transfer contract is fully satisfied;
- credential-bearing files are not ingested and must be sanitized; any real
  exposed credential is treated as compromised outside this repository;
- conflicts require the standing human decision record;
- a fix produces a new artifact and qualification boundary;
- expired or revoked authority requires a new valid authority act;
- tampering is restored from committed immutable bytes and recorded as an
  incident, never hidden by resealing history;
- missing authorization-floor evidence can be supplied only by its external
  owner through the appropriate boundary.

The current-real-universe row is read-only and does not assume an empty ledger.
At Phase 16 genesis it records the genuine zero-submission state distinctly
from every fixture-only row. After real evidence arrives it re-derives to that
current state, while isolated zero-evidence controls continue to exercise the
absence branch.

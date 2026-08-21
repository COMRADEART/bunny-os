# State model

Phase 16 exposes six orthogonal dimensions rather than a synthetic green/red
flag.

| Dimension | Source | Examples |
| --- | --- | --- |
| operational readiness | Phase 16 executable scenarios | ready / control failure |
| receipt | Phase 9 ledger plus Phase 16/15 derived views | awaiting, received, incomplete, accepted |
| reviewer assessment | accepted submission bytes | approved, blocked, more evidence required |
| security gate | Phase 11 | awaiting external evidence, under analysis, blocked, remediation required, satisfied |
| authorization | Phase 13 | evidence pending, blocked, ready for authorization, authorized, revoked |
| candidate decision | Phase 13 ladder via Phase 14 | requires more evidence, blocked, authorized, revoked |

There is no implication arrow between adjacent rows. An accepted receipt may
carry a blocking review. A satisfied security gate leaves four other external
floor sources absent in the zero-evidence scratch demonstration. An
authorization input is honored only if a valid external authority record was
already made over the complete floor.

The subject artifact identity is a separate invariant: `e906a48793d7`, `ROOT`,
`FROZEN`, `UNSIGNED`. Candidate workflow state may be `EVIDENCE_PENDING` while
the artifact remains frozen; those are not contradictory states.

# Artifact identity ceremony

The ceremony binds a review to bytes, never to a commit ancestry claim. Its
executable source is the Phase 15 `identity_ceremony` function, called through
the Phase 16 fail-closed input screen.

| State | Condition | Artifact-specific advancement |
| --- | --- | --- |
| `VERIFIED` | one well-formed independent digest matches one of the five subject digests and the reviewer states basis and computation | yes |
| `OBSERVED_UNVERIFIED` | a digest is present but its independent measurement basis/method is absent | no |
| `MISSING` | no independent digest was supplied | no |
| `MISMATCH` | the measured digest is well formed but identifies other bytes | no |

Malformed or ambiguous observations fail before this four-state derivation.
Two different artifact claims bind to nothing.

Mandatory controls:

- exact independent match with basis and method derives `VERIFIED`;
- copying the repository expectation without basis/method derives
  `OBSERVED_UNVERIFIED`, never `VERIFIED`;
- absence derives `MISSING`;
- a wrong value derives `MISMATCH`;
- a list, prose value, truncated digest, or multiple distinct claims refuses;
- a correct source commit without an artifact digest remains unbound;
- a correct digest for an artifact with the wrong graph relationship does not
  transfer applicability.

The expected values are supplied only so the reviewer can compare after their
measurement. The repository cannot attest that the reviewer actually observed
the bytes; credibility remains a human assessment over the recorded ceremony.

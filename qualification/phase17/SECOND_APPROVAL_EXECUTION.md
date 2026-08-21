# Second approval execution

A second approval is an external authority action, not an intake status. It
names the approver, role, independently recomputed artifact digest, decision,
timestamp, relevant cut, and conditions. Only `APPROVED` can contribute.
`REJECTED`, `CONDITIONAL`, pre-signing approval, stale-cut approval, expired or
revoked authority, wrong-artifact binding, and signer/approver or
release-authority overlap without a Phase 13 exception fail closed.

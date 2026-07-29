# Phase 7 security review

Date: 2026-07-29. Scope: Phase 7 source in `oem/`, `enterprise/`, `sync/`, their schemas, and their tests. Twelve separate assessments.

**No unresolved Blocker or Critical issue exists in Phase 7 source.** Inherited stable-release blockers remain unresolved and independently prevent any pilot.

## 1. OEM supply chain

Profiles must be signed with an `oem-` key. Package repositories come from a closed reviewed set. Out-of-tree kernel modules must be in the reviewed set. Overlays cannot deliver executables, units, policy files, or archives, and cannot write outside eight destination roots. Findings: one, fixed — the namespace collision check was unreachable and is now correct.

Residual: an OEM can still ship poor hardware or a weak default outside the protected set. Trademark misuse is a legal remedy, not a technical one.

## 2. Factory provisioning

22 finalisation checks with `UNKNOWN` and `NOT_RUN` treated as failure and a missing check treated as failure. Unknown check ids are errors, so a typo cannot pass. See `FACTORY_PROVISIONING_SECURITY_REVIEW.md`.

Residual, and significant: the checks evaluate a supplied record. No executor inspects the device, so a dishonest record passes. This is a Major limitation, not a Critical defect, because no factory exists.

## 3. Device identity

Locally generated, rotatable, never derived from hardware identifiers. Server-issued identity refused. Findings: none.

Residual: reinstall produces a new identity, so fleet inventory cannot track hardware across reinstalls. Intended.

## 4. Enterprise enrolment

Single-use tokens with a 24-hour maximum, consumed-id rejection, 60-second message freshness, per-message nonce replay rejection, recursive secret refusal in params, and refusal of secrets in process arguments. Nine mandatory disclosures. Findings: none.

Residual: a stolen token used inside its window before the legitimate device enrols is still effective.

## 5. Policy agent

15 typed operations, no execution channel at any depth, 12 safety invariants rejected at parse time. Findings: one, fixed — a validator was registered with the wrong arity and raised `TypeError` for every allowlist policy.

Residual, and blocking for deployment: the agent has no privileged transport, and the settings layer has no organisation scope. Both are Major and recorded in `KNOWN_LIMITATIONS.md`.

## 6. Fleet service

Rings cannot disable signature verification; supplying `false` is a rejection. Promotion cannot skip early validation. Forced restart requires an explicit policy reference. Failed updates must report preserved rollback. Findings: one, fixed — the behavioural-field refusal was preempted by a generic unknown-field check.

Residual: a compromised control plane can pin a channel, set deadlines, and disable organisation applications within the typed surface.

## 7. Enterprise console

Seven roles, no single role unrestricted for routine work, step-up authentication with a passkey or hardware key for destructive actions, and no console view that renders user content, screens, keystrokes, or a shell. Custom password authentication refused by name. Findings: none.

Residual: no console exists, so none of this has been assessed in a running application.

## 8. Encrypted sync

Envelope refuses plaintext description and key material at any depth. Version bound as associated data; rollback and same-version ciphertext substitution refused. Keyring refuses a collection key still wrapped for a revoked device. Findings: none. See `ENCRYPTED_SYNC_SECURITY_REVIEW.md`.

Residual: no reviewed cryptographic backend is installed, and no independent cryptographic review has been commissioned. This is why `make gate-sync-pilot` fails.

## 9. Device pairing

The authenticator is recomputed locally from received key material and bound to the session id, so server-side key substitution is detected rather than trusted. Replay, expiry, downgrade, and self-pairing refused. Findings: none.

Residual: a user who confirms without comparing defeats the control. The instruction text says so explicitly.

## 10. Account recovery

Server-assisted recovery of private content refused. Organisation recovery limited to three organisation-owned collections and refused on personally owned devices. No personal key escrow. Findings: none.

Residual: careless storage of a recovery phrase remains the user's risk, and the mandatory warning states it.

## 11. Remote wipe

Five separate operations. Full reset and cryptographic erase refused on non-organisation-owned devices. Prior policy, multi-factor authorisation, explicit scope, audit correlation id, and device confirmation enforced. Recovery preserved. Findings: none.

Residual: a compromised security-administrator account can wipe organisation-owned devices. Step-up authentication and audit chaining reduce but do not remove this.

## 12. Air-gapped management

No unsigned import path for any bundle kind. Monotonic per-organisation sequence refuses stale replay. Expiry enforced with a 90-day maximum. Only the `fleet-` key namespace accepted; revoked keys refused. Workflow ordering enforced. Findings: none.

Residual: a bundle inside its window and above the last applied sequence is accepted, which is the intended behaviour and the residual risk of any offline distribution.

## Severity summary

| Severity | Count | Status |
|---|---|---|
| Blocker | 0 in Phase 7 source | 5 inherited stable-release blocker codes remain |
| Critical | 0 in Phase 7 source | 8 inherited Critical vulnerability findings in the beta image dependency set |
| Major | 3 | Policy agent transport, settings organisation scope, factory record trust — all documented, none fixed |
| Minor | 3 | All fixed during implementation, each caught by a test |

## What this review does not cover

No running service, console, or device. No penetration test, load test, or fuzzing campaign. No independent review of any kind. Every control above is verified by host tests over synthetic data, which establishes that the code refuses what it claims to refuse — not that a deployed system is secure.

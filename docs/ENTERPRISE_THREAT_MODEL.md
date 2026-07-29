# Enterprise threat model

Extends `docs/THREAT_MODEL.md`, which retains the Phase 1 and Phase 5 tables. This document holds the Phase 7 additions in the same shape.

## New assets

Device identity keys, enrolment tokens and certificates, organisation policy bundles, fleet audit chains, fleet-control signing keys, sync device and collection keys, the user recovery secret, OEM profile signing keys, and factory provisioning credentials.

## New boundaries

Device ↔ organisation control plane; device ↔ sync service; control plane ↔ sync service (separate trust domains); tenant ↔ tenant; OEM build host ↔ official image; factory environment ↔ shipped device; administrator role ↔ administrator role.

## Threats and controls

| Actor or event | Representative attack | Controls | Residual risk |
|---|---|---|---|
| Malicious organisation administrator | Read personal files or Bunny memory on a personally owned enrolled device | Fleet health limited to 10 categorical fields; console has no user-content view; memory exposure is a safety invariant and unrepresentable as policy; enrolment discloses the personal-data boundary | An administrator still sees OS version, update, and encryption state, which is a small but real signal about a person's device |
| Malicious organisation administrator | Wipe a personally owned device out of spite | Full reset and cryptographic erase refused unless organisation-owned; prior policy, MFA, explicit scope, audit id, and device confirmation required | Organisation data removal is still available and may disrupt a user |
| Compromised fleet server | Push a policy that disables update verification | Safety invariants rejected at parse time; `signatureVerificationRequired` cannot be set false; policy agent exposes no execution operation | A compromised server can still pin an old channel or set aggressive deadlines within the typed surface |
| Compromised fleet server | Push a stale policy bundle to roll a device back | Monotonic per-organisation sequence; bundle expiry with 90-day maximum | A bundle within the window and above the last sequence is accepted |
| Compromised identity provider | Impersonate an administrator | Step-up authentication for destructive actions requires passkey or hardware key; role separation limits blast radius; audit chain records the authorisation method | An IdP compromise still permits non-destructive operations by a scoped role |
| Cross-tenant access | Tenant A reads tenant B devices, policies, audit, catalogue, or backups | `assert_same_tenant` required for 11 resource families; wildcard and absent scopes refused; unscoped rows refused rather than dropped; per-organisation audit chains | Controls are source-level only; no running control plane has been assessed |
| Stolen enrolment token | Enrol an attacker device into an organisation | Single-use, 24-hour maximum lifetime, consumed-id rejection, no secret in the descriptor or in argv, 60-second message freshness, nonce replay rejection | A token used within its window before the legitimate device is still effective |
| Malicious OEM | Ship an image that weakens privacy or security defaults | Closed profile schema; overlay destination and content allowlists; protected settings refused as key or value; no executable overlay payloads | An OEM can still ship a poor hardware choice or a weak default that is outside the protected set |
| Malicious OEM | Present a modified image as official | Official-device claim requires the matching programme level, a signed qualification report, and validated recovery; independent variants cannot claim official status | Trademark enforcement is a legal process, not a technical control |
| Compromised factory environment | Leave credentials or identifiers on a shipped device | 22-check finalisation with UNKNOWN and NOT_RUN treated as failure and missing checks treated as failure | The checks evaluate a supplied record; no executor verifies the device itself |
| Compromised sync server | Read user content | Content encrypted on device under keys the service never receives; envelope refuses plaintext description and key material | Operational metadata remains visible; see `docs/ENCRYPTED_SYNC.md` |
| Compromised sync server | Substitute a device key during pairing | Authenticator recomputed locally from received key material and bound to the session; user compares out of band; mismatch reported as substitution | A user who confirms without comparing defeats the control |
| Compromised sync server | Roll back or substitute ciphertext | Version bound as associated data; `assert_no_version_rollback` refuses lower versions and differing ciphertext at the same version | A server can still withhold updates, which is a denial of service rather than a confidentiality break |
| Malicious paired device | Read collections it was not granted | Collection keys wrapped per device; new devices granted nothing by default | A device granted a collection reads that collection's existing objects |
| Key-recovery abuse | Operator or organisation recovers private content | Server-assisted recovery of private content refused; organisation recovery limited to three organisation-owned collections; no personal key escrow | A user who stores the recovery phrase carelessly remains vulnerable |
| Unauthorised remote wipe | Erase a device without authority | Ownership constraint, prior policy, MFA, explicit scope, audit id, device confirmation | An organisation-owned device can be wiped by a legitimately compromised security administrator account |
| Policy downgrade | Replace a strict policy with a permissive one | Monotonic bundle sequence; policy version and expiry; audit chain records the policy version applied | A legitimately newer permissive policy is accepted, as intended |
| Update-ring manipulation | Force a disruptive restart across a fleet | Forced restart requires an explicit policy reference; deferred ring cannot force restart; withdrawal forces rollout to zero | An organisation that genuinely sets the policy can force restarts |
| Audit tampering | Delete or edit an incriminating entry | Per-entry hash over canonical content plus previous hash; monotonic sequence exposes gaps; signed truncation marker distinguishes expiry from tampering | An attacker with write access from entry N can rewrite the chain from N forward; off-device anchoring is not implemented |

## Not assessed

No running control plane, sync service, or console exists, so none has been penetration-tested. Every control above is verified by host tests over synthetic data. Independent cryptographic and infrastructure review has not been commissioned.

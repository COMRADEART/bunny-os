<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent cryptography review — request

Bunny OS contains a designed, implemented, and **never operated** encrypted
synchronisation subsystem. `gate-sync-pilot` lists
`independentCryptographicReview` as a requirement and it is unmet, so the sync
pilot cannot proceed on any other basis regardless of how the stable release
goes.

This request is for a review of the cryptographic design and its implementation.
It is not a request to bless a service, because there is no service.

## Exact scope

**In scope:**

1. **The envelope format** — `sync/`, `docs/SYNC_CRYPTOGRAPHY.md`. Construction,
   AEAD choice, nonce derivation, associated data, versioning, downgrade
   resistance.
2. **The key hierarchy** — root key derivation, per-device keys, per-collection
   keys, and what compromise of each yields.
3. **Device pairing** — `docs/DEVICE_PAIRING.md`. Authentication of a new device,
   the out-of-band channel, and resistance to an active attacker during pairing.
4. **Account recovery** — `docs/SYNC_RECOVERY.md`, `docs/KEY_RECOVERY.md`. What
   the recovery secret protects, what the server learns, and what an attacker who
   obtains the recovery secret can do.
5. **Deletion semantics** — `docs/DATA_DELETION.md`. Whether deletion is
   cryptographic, what the disclosed retention bounds actually bound, and whether
   a deleted item is recoverable by the server.
6. **Device revocation** — whether a revoked device is cryptographically excluded
   or merely denied at an API.
7. **The release signing design** — `docs/SIGNING_ROLE_SEPARATION.md`,
   `docs/PRODUCTION_SIGNING_CEREMONY.md`. Seven roles with disjoint namespaces,
   Ed25519, and the rotation-overlap requirement.

**Out of scope:**

- Systems security of the broker, installer and update path. Separate request
  (`reviews/security/REQUEST.md`).
- The 24 vulnerability findings. Separate request.
- Disk encryption: Bunny OS uses LUKS2 through the standard Fedora stack and
  implements no cryptography of its own there. Comment on the *policy* — PBKDF
  parameters, TPM binding, recovery-key entropy and display — but the primitives
  are cryptsetup's.
- Any operated service. Nothing is deployed. There is no server to test.

## Commit

- **Evidence baseline commit:** `80df25b09f6578276d18c8a82f15c47dd8959740`.
- **Your scope commit:** the commit you are given at engagement start. Record it
  as `scopeCommit`; intake rejects a review scoped to a different commit.

## Artifacts

| Artifact | What it is |
|---|---|
| `sync/` | The implementation, including the envelope encoder and key hierarchy |
| `schemas/sync-envelope.schema.json` | The wire format |
| `docs/SYNC_CRYPTOGRAPHY.md` | The design, including the primitives and their parameters |
| `docs/SYNC_RECOVERY.md`, `docs/KEY_RECOVERY.md` | Recovery design |
| `docs/DEVICE_PAIRING.md`, `docs/DEVICE_IDENTITY.md` | Pairing and identity |
| `docs/DATA_DELETION.md` | Deletion and retention |
| `docs/REMOTE_WIPE.md` | Remote wipe semantics |
| `docs/SIGNING_ROLE_SEPARATION.md` | Signing roles and namespaces |
| `docs/PRODUCTION_SIGNING_CEREMONY.md` | The ceremony that has not been run |
| `tests/sync/`, `tests/cryptography/` | The project's own tests |
| `ENCRYPTED_SYNC_SECURITY_REVIEW.md`, `ENCRYPTED_SYNC_PRIVACY_REVIEW.md` | The project's internal reviews. Statements of belief, not evidence. |
| `DEVELOPMENT_SIGNING_DRILL_REPORT.md` | 9/9 with development keys, including four rejection checks |
| `TWO_PERSON_DEVELOPMENT_SIGNING_DRILL_REPORT.md` | The two-signer drill, also with development keys |

## Threat model

1. **The sync server itself, honest-but-curious.** The design claims the server
   learns nothing about content. Test that claim, including metadata: item
   counts, sizes, timing, collection structure.
2. **The sync server, actively malicious.** Can it serve a stale version, roll
   back a collection, suppress a deletion, or substitute a device key?
3. **A network attacker** with the ability to intercept and modify.
4. **A stolen paired device**, before and after revocation.
5. **An attacker who obtains the account recovery secret** but not a device.
6. **A compromised release signing key**, one role at a time. What does each of
   the seven roles unlock, and does role separation actually contain it?

Not in the model: a server that has been compromised *and* holds a device key; an
adversary with a quantum computer.

## Questions

1. **Is the envelope format sound**, and does it bind everything it needs to bind
   — version, collection, device, ordering — into the associated data?
2. **Is the key hierarchy sound**, and is the blast radius of each key
   compromise what the design claims?
3. **Can the server roll back or suppress?** Is there a construction that would
   let a client detect it?
4. **What does the server learn** that the design does not acknowledge?
5. **Is device pairing safe against an active attacker** during the pairing
   window?
6. **Is account recovery a backdoor?** Specifically: does the recovery path give
   the server, or anyone holding the recovery secret alone, access to content?
7. **Is deletion cryptographic or nominal?** If a key is destroyed, is the
   ciphertext genuinely unrecoverable, and do the disclosed retention bounds
   describe what actually happens?
8. **Does revocation cryptographically exclude a device**, or only deny it at an
   API?
9. **Is the signing role separation meaningful**, and is the rotation-overlap
   requirement the right control? The project enforces that a replacement key
   must be published before its predecessor expires, on the grounds that a device
   updating late would otherwise trust neither key.
10. **Are the LUKS2 policy choices defensible** — PBKDF parameters, TPM binding
    conditions, recovery-key entropy and how it is displayed to a user?

## Expected report format

Markdown or PDF, plus a machine-readable record conforming to
`security/reachability/schemas/independent-review-record.schema.json` with
`reviewType: "cryptography"`.

Required: `independenceDeclaration`, `scopeCommit`, `scopeArtifacts`,
`findings[]`, `conclusion`, `reportDigest`, and a detached `signature` over
`reportDigest`. Intake recomputes the digest from the file and rejects an
unsigned record.

## Severity model

- **critical** — a break that exposes plaintext to the server or to a network
  attacker, or that makes a signature forgeable.
- **high** — a break requiring a condition a normal deployment reaches, or a
  metadata leak that reveals content.
- **medium** — a weakness requiring an already-privileged position or an
  unsupported configuration.
- **low** — a parameter choice below current practice with no demonstrated break.
- **informational** — observation.

State your assumptions. If a finding depends on a primitive's security bound,
name the bound.

## Expected independence statement

In your own words:

- no employment, contract, consultancy, equity or advisory relationship with
  ComradeArt or Bunny OS beyond this engagement;
- no authorship of the design or implementation under review;
- your conclusions are your own, not directed or edited by the project.

## Confidentiality requirements

- The code is source-available. Quote it freely.
- **Findings embargoed until remediated or 90 days from delivery, whichever is
  sooner.**
- Do not publish an unremediated critical or high finding during the embargo.
- No user data exists: the sync service has never been operated and has no users.

## Prohibited claims

- **"Certified"**, "approved", "compliant", "endorsed", "military-grade",
  "unbreakable". None of these is a finding.
- **Any claim about an operated service.** There is none. A review of a design is
  not a review of a deployment, and the project will not represent it as one.
- **"Zero-knowledge"** or "end-to-end encrypted" as a bare conclusion. If the
  design achieves a property, name the property and the adversary it holds
  against.
- Any statement that the sync pilot may begin. That is a gate decision with six
  other unmet requirements.
- A conclusion about a document you did not read. Say what you covered.

A `fail` or `conditional` conclusion is a useful result. The subsystem is not
deployed and nothing is at stake in this review being negative, which is the
best possible time to have it.

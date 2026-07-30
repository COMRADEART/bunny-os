# ADR-020: End-to-end encrypted sync

- Status: accepted as design; no implementation is enabled
- Date: 2026-07-29

## Decision

Optional sync encrypts every object on the device before upload, under a key hierarchy rooted in a user recovery secret that the service never receives. The service stores versioned opaque envelopes and coordinates conflicts. It cannot decrypt content, and it is a separate trust domain from the organisation control plane: an organisation that controls device policy gains no access to private synced content.

Reviewed AEAD constructions only — XChaCha20-Poly1305 or AES-256-GCM — with envelope version, collection, object, and object version bound as associated data. Key derivation is HKDF-SHA256 with distinct per-purpose labels. Nothing is invented; `docs/SYNC_CRYPTOGRAPHY.md` specifies parameters rather than algorithms.

Bunny OS implements no cryptographic primitive in Python. Following the existing practice in `build/scripts/sign-stable-rc.py`, which shells out to `openssl pkeyutl`, the sync backend is a reviewed out-of-process component. In a source-only checkout it is absent and `sync/crypto.py` refuses every operation rather than degrading.

## Why not simpler alternatives

*Server-side encryption with operator-held keys* was rejected: it protects against disk theft and nothing else, and it would let a compromised operator or a legal demand reach user prompts and memories, which the privacy model prohibits.

*Encrypting everything by default* was rejected because it conflates enabling an account with enabling a data flow. Sensitive collections default to local-only and require explicit acknowledgement, so a user who wants preference sync does not silently upload memories.

*A single account-wide key* was rejected because it makes device revocation meaningless — revoking one device would require re-encrypting everything. Per-collection and per-device keys let revocation rotate only what the revoked device could read.

*Claiming zero knowledge* was rejected as false. Object size, upload time, version count, device count, and account identity remain visible, so `sync/metadata.py` documents them and `assert_no_zero_knowledge_claim` refuses text that overstates the guarantee.

## Consequences

Losing every key and the recovery secret makes data permanently unrecoverable, and the warning is mandatory and acknowledged. Objects a revoked device already downloaded cannot be retracted. Deleted encrypted objects may persist in backups for up to 35 days. All three are disclosed rather than glossed.

An independent cryptographic review has not been commissioned. `make gate-sync-pilot` fails until it is.

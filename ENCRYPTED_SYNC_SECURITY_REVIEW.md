# Encrypted sync security review

Date: 2026-07-29. Scope: `sync/`. Tests: `tests/sync` (72), `tests/cryptography` (27), `tests/recovery` (19).

## Primary claim and how it is enforced

**The sync operator cannot decrypt synced content.**

Enforced in three places rather than asserted once:

- `_assert_no_key_material` refuses any envelope field that looks like a key, wrapped key, passphrase, seed, or recovery secret, at any nesting depth. A client bug cannot upload the material the design keeps away from the server.
- `_assert_no_plaintext_fields` refuses title, filename, path, tags, preview, mime type, author, and content fields, so the plaintext is not leaked through metadata.
- Collection identifiers are opaque, so the service is not told which collection holds memories.

## No invented cryptography

Bunny OS defines no cipher, mode, KDF, or key-agreement protocol. Reviewed AEAD only: XChaCha20-Poly1305 with a 24-byte nonce or AES-256-GCM with a 12-byte nonce, and nonce length is checked against the algorithm. Key derivation is HKDF-SHA256 with distinct per-purpose labels, so a key valid in one context is invalid in another.

`tests/cryptography` asserts the repository contains no hand-rolled block cipher, S-box, or Feistel construction under `sync/`, and no committed private key material.

The cryptographic executor is absent in a source-only checkout. `sync/crypto.py` reports `available: false` and refuses every operation, following `installer/bin/bunny-installer-backend`. A stub returning plausible ciphertext would be worse than a refusal, because downstream tests would pass while nothing was encrypted.

## Compromised server

| Attack | Control |
|---|---|
| Read content | Content encrypted on device under keys the service never holds |
| Move a ciphertext to another object | Collection, object, and version bound as associated data |
| Replay an older version as current | `assert_no_version_rollback` refuses a lower version |
| Substitute a different ciphertext at the same version | Refused, digest mismatch at equal version |
| Substitute a device key during pairing | Authenticator recomputed locally from received key material and bound to the session |
| Withhold updates | Not prevented; this is denial of service, not a confidentiality break |

## Device revocation

Revoking a device rotates every collection it could read and rewraps the new generation for remaining active devices only. `parse_keyring` refuses a keyring that still wraps any collection key for a revoked device, which makes "revocation rotates relevant access" an enforced invariant rather than a procedure someone might skip.

On suspected compromise the root key rotates too. Revoking the last active device is refused — that is account deletion.

Two honest limits are returned with the plan rather than buried: objects the revoked device already downloaded cannot be retracted, and a newly added device can read the granted collections' existing objects.

## Recovery

Server-assisted recovery of private content is refused. A recovery path must present the recovery secret or an already-trusted device. Organisation recovery reaches three organisation-owned collections, is refused on personally owned devices, requires a disclosed policy reference, and is audited. No personal key escrow exists, consistent with `docs/RECOVERY_KEYS.md`.

The 24-word, 2048-word-list, 128-bit-minimum recovery phrase specification is stated in code and documentation so an implementation cannot quietly weaken it.

## Findings

No Blocker or Critical finding in Phase 7 sync source.

**One Blocker for pilot purposes, external to the source:** no independent cryptographic review has been commissioned, and no reviewed backend is installed. A design that looks correct in review is not a design that has been reviewed. `syncCryptographyIndependentReview` is `false` and `make gate-sync-pilot` fails on it.

Residual risks, accepted and documented: a user who confirms a pairing code without comparing it defeats the substitution defence; operational metadata remains visible; deleted objects may persist in backups for up to 35 days; and loss of all keys and the recovery secret makes data permanently unrecoverable.

## Not assessed

No sync service exists. Nothing has been encrypted, uploaded, downloaded, paired, revoked, or recovered. No cryptographic implementation has been tested, because none is installed. Every control is verified structurally.

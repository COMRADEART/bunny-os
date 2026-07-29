# Sync cryptography

Implementation: `sync/keys.py`, `sync/envelope.py`, `sync/crypto.py`. Tests: `tests/cryptography`. Decision: `docs/adr/ADR-020-end-to-end-encrypted-sync.md`.

## No invented primitives

Bunny OS defines no cipher, no mode, no KDF, and no key-agreement protocol. This document specifies which reviewed constructions to use and with which parameters. `tests/cryptography` asserts the repository contains no hand-rolled block cipher, S-box, or Feistel construction under `sync/`.

The repository's established practice is to call a reviewed implementation out of process — `build/scripts/sign-stable-rc.py` shells out to `openssl pkeyutl` rather than importing a crypto library — and sync follows it.

## Key hierarchy

```text
User recovery secret
    |
User root key
    |
    +-- Device wrapping keys        one per paired device
    +-- Memory collection key
    +-- Workspace collection key
    +-- Backup collection key
    +-- File collection keys        one per file collection
```

The root key is derived from the recovery secret and never leaves the device in plaintext. Collection keys are wrapped to each device's wrapping key. Adding a device is a rewrap; removing one is a rotate-then-rewrap.

Per-file-collection keys exist so that revoking access to one collection does not force rotation of the others.

## Derivation

HKDF-SHA256 with these exact info labels. Distinct labels per purpose prevent a key from being valid in two contexts.

```text
bunny-os/sync/v1/user-root-key
bunny-os/sync/v1/device-wrapping-key
bunny-os/sync/v1/collection-key
bunny-os/sync/v1/object-key
bunny-os/sync/v1/backup-key
```

## Object encryption

XChaCha20-Poly1305 with a 24-byte nonce, or AES-256-GCM with a 12-byte nonce. Associated data binds envelope version, collection id, object id, and object version.

## Operations a backend must provide

`derive-root-key`, `derive-subkey`, `wrap-key`, `unwrap-key`, `seal-object`, `open-object`, `generate-recovery-phrase`. Acceptable backends are libsodium via the system package, or OpenSSL 3. Neither is vendored.

## Recovery secret

24 words from a 2048-word list, at least 128 bits of entropy before checksum. Specified here so an implementation cannot quietly weaken it.

## Rotation and revocation

Revoking a device rotates every collection it could read and rewraps the new generation for the remaining active devices only. `parse_keyring` refuses a keyring that still wraps any collection key for a revoked device, which is the enforced meaning of "revocation rotates relevant access".

On suspected compromise the root key rotates too, because a compromised device may hold a copy.

Revoking the last active device is refused; that is account deletion, not revocation.

## Honest limits

Objects a revoked device already downloaded cannot be retracted. Only future objects are protected. A device added to a collection can read that collection's existing objects, because they are encrypted under the current collection key. Both facts are returned in the operation plan rather than left for a user to discover.

## Not reviewed

No independent cryptographic review has been commissioned or completed, and no reviewed backend is installed. `syncCryptographyIndependentReview` is `false` in `operations/data/phase7-readiness.json` and `make gate-sync-pilot` fails on it.

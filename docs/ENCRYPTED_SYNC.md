# Optional encrypted sync

Schema: `schemas/sync-envelope.schema.json`. Implementation: `sync/`. Tests: `tests/sync`, `tests/cryptography`, `tests/recovery`.

Optional and independent. Bunny OS is fully usable with no account. Nothing about the core OS degrades when sync is disabled or the service is unreachable, and no core function is withheld to encourage account creation.

## Nothing syncs by default

Enabling sync enables an account, not a data flow. Each domain is chosen individually:

`preferences`, `bookmarks`, `workspaces`, `plans`, `tasks`, `configuration`, `approved-memories`, `conversation-metadata`, `approved-files`, `encrypted-backups`.

The last four are sensitive and stay local-only until explicitly acknowledged; enabling them cannot happen as a side effect of enabling something else. At least one device must be selected before any domain syncs.

## What the service cannot do

Read content. Objects are encrypted on the device before upload under keys the service never receives. The envelope validator refuses any field that would describe the plaintext — title, filename, tags, preview, mime type, author — and any field that would carry key material.

Collection identifiers are opaque, so the service is not told which collection holds memories.

## What the service can see

See `docs/ENCRYPTED_SYNC.md` metadata table below and `sync/metadata.py`, which is the source of truth.

| Visible | Not visible |
|---|---|
| Account identifier | Object content |
| Device key id | Object title or filename |
| Collection identifier (opaque) | Bunny prompts and memories |
| Object identifier | Which collection is memory |
| Object version and version count | |
| Encrypted object size | |
| Upload timestamp | |

From the visible set an observer can infer that an account exists, how many devices it has, roughly how much data it stores and how often that changes, when a device was active, and that two devices belong to the same account.

This is **not** zero knowledge, and `assert_no_zero_knowledge_claim` refuses documentation or UI text that says it is. Overstating the guarantee would be a privacy claim we cannot support.

## Envelope

Versioned. Reviewed AEAD only: XChaCha20-Poly1305 or AES-256-GCM, with nonce length checked against the algorithm. Collection, object, object version, and envelope version are bound as associated data, so the service cannot relocate a ciphertext to a different object or replay an older version as current. `assert_no_version_rollback` refuses a server response offering a lower version, and refuses a different ciphertext at the same version.

## Cryptography is delegated

Bunny OS implements no AEAD, no KDF, and no key agreement in Python. `sync/crypto.py` reports the backend unavailable and refuses every operation in a source-only checkout, matching `installer/bin/bunny-installer-backend`. A stub returning plausible ciphertext would be worse than a refusal because downstream tests would pass while nothing was encrypted. See `docs/SYNC_CRYPTOGRAPHY.md`.

# Encrypted-sync cryptography review package

Review id: `review-sync-cryptography`  
State: **package-prepared**  
Reviewer: **not yet identified**  
Organisation: **not yet identified**  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`

This package is prepared and has not been sent. It is not a review, and nothing in this
repository may cite it as one. `release/reviews.py` refuses to record a reviewer
affiliated with the project, so this cannot become a self-review by being filled in.

## Scope

The encrypted-sync envelope format, the key hierarchy, device pairing, account recovery, and the deletion semantics.

## Threat model

docs/SYNC_CRYPTOGRAPHY.md, ENCRYPTED_SYNC_SECURITY_REVIEW.md

## Design documents

- `docs/ENCRYPTED_SYNC.md`
- `docs/SYNC_CRYPTOGRAPHY.md`
- `docs/SYNC_RECOVERY.md`
- `docs/DEVICE_PAIRING.md`
- `docs/DATA_DELETION.md`
- `docs/adr/ADR-020-end-to-end-encrypted-sync.md`
- `schemas/sync-envelope.schema.json`

## Test results

- `tests/sync/`
- `tests/cryptography/`
- ENCRYPTED_SYNC_SECURITY_REVIEW.md

## Known limitations

The AEAD backend is AES-256-GCM with HKDF-SHA256 and RFC 3394 key wrap. No third party has examined it. The design is explicitly not described as zero knowledge.

## Explicit questions

1. Does the associated data binding of object identifier and version prevent envelope substitution and rollback across collections?
2. Is the recovery-secret-to-root-key derivation resistant to an offline attack by an operator holding all uploaded ciphertext?
3. Does the locally recomputed pairing authenticator actually defeat server key substitution, and under what assumptions?
4. Are the disclosed retention bounds for the six deletion scopes achievable by an honest operator, and detectable if violated?
5. Is per-collection key separation sufficient to prevent a compromised device from decrypting collections it was never paired for?

## Expected deliverables

- A written cryptographic review identifying the reviewer and their credentials
- An explicit statement on each of the five questions above
- A judgement on whether the construction is sound as specified and as implemented
- Any recommended changes before a sync service is operated

## How this package becomes a completed review

1. Identify an external reviewer and record their name and organisation.
2. Set `state` to `commissioned` in `operations/data/independent-reviews.json`.
3. On delivery, place the report in this directory and set `reportReference` to its path.
4. Set `state` to `delivered`. The gate verifies the file exists before accepting it.

Generated from `operations/data/independent-reviews.json`. Edit that file, not this one.

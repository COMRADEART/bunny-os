# Encrypted sync privacy review

Date: 2026-07-29. Scope: `sync/metadata.py`, `sync/selective.py`, `sync/deletion.py`, `sync/recovery.py`.

## This is not zero knowledge

End-to-end encryption protects content. It does not hide that content exists. A service that routes and versions objects necessarily observes operational metadata, and pretending otherwise would be a false privacy claim.

`assert_no_zero_knowledge_claim` refuses documentation or interface text containing "zero knowledge", "we know nothing", "no metadata", "metadata-free", "completely anonymous", or "untraceable". The refusal is a test, not a style guide.

## Visible to the operator

| Field | Why it is unavoidable |
|---|---|
| Account identifier | Required to authenticate and route |
| Device key id | Required to register devices, wrap per-device keys, honour revocation |
| Collection identifier | Required to group objects and coordinate versions; opaque, so the kind is not revealed |
| Object identifier | Required to address an object |
| Object version | Required for conflict detection and rollback prevention |
| Version count | Inherent to versioned storage |
| Encrypted object size | Inherent to storing a blob; padding reduces but does not remove correlation |
| Upload timestamp | Inherent to accepting a write; used for quota and abuse limits |

## Not visible

Object content, object title or filename, Bunny prompts and memories, and which collection is the memory collection.

## What an observer can infer

Stated plainly rather than omitted:

- That an account exists and how many devices it has.
- Roughly how much data the account stores and how often it changes.
- When a device was active, at upload-timestamp granularity.
- That two devices belong to the same account.

For a user deciding whether to enable sync, that set is the honest answer to "what does the service learn about me". It is a real disclosure, and the mitigation is telling the user rather than claiming it does not exist.

## Nothing syncs by default

Enabling sync enables an account, not a data flow. Ten domains are individually selectable and all default to off. The four sensitive domains — approved memories, conversation metadata, approved files, encrypted backups — stay local-only until explicitly acknowledged, and enabling them cannot happen as a side effect of enabling something else. At least one device must be selected before any domain syncs.

## Deletion is honest

Six scopes with distinct effects. Server object deletion removes the live copy; backup and disaster-recovery copies may persist up to 35 days and remain encrypted. Instantaneous physical deletion from all backups is not claimed, and `assert_no_overclaim` refuses text that claims it.

Tombstones persist up to 180 days so an offline device does not resurrect a deleted item. For memory and conversation metadata a concurrent edit never silently restores a deleted item; the deletion is kept and the edit is queued for explicit review.

Account deletion removes the account, device registry, and encrypted objects, does **not** delete local data on the user's devices, does not delete keys from those devices, and cannot be undone. All four facts are stated together.

## Service-side data minimisation

`minimisation_report` compares what a service actually stores against the declared visible set and flags excess. An excess field means either the service or the documentation must change.

The service should store only what is necessary for encrypted object routing, version coordination, device registration, account authentication, billing if a paid service ever exists, abuse prevention, and service security. Product engagement analytics are not collected by default, and abuse controls must work without decrypting user content — rate limits, quotas, and payload size bounds operate on ciphertext.

## Data residency

Not implemented, and no residency guarantee is offered. Stating a storage, backup, or processing region for a service that does not exist would promise a control no infrastructure enforces. If a service is ever built, region selection, backup region, processing region, support access, cross-region replication, and key location must all be documented and enforced before any residency claim is made.

## Findings

No Blocker or Critical privacy finding in Phase 7 sync source.

**One Major limitation.** The visible metadata set genuinely reveals device count and activity timing, and size padding reduces without eliminating correlation. This is inherent to the architecture, is disclosed, and should be shown to users at the point they decide whether to enable sync.

## Not assessed

No service has been operated, so no real metadata has been observed accumulating over time. No independent privacy assessment has been conducted.

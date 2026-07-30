# Data deletion

Implementation: `sync/deletion.py`. Tests: `tests/sync`.

Six scopes, because "delete" means six different things and conflating them is how a product ends up claiming data is gone when it is not.

| Scope | Local plaintext | Other devices | Server ciphertext | Max backup persistence |
|---|---|---|---|---|
| `local-deletion` | removed | kept | kept | — |
| `all-synced-devices` | removed | removed, tombstone propagated | kept | — |
| `server-encrypted-object-deletion` | kept | kept | removed from live storage | 35 days |
| `account-deletion` | kept | kept | removed | 35 days |
| `organisation-data-removal` | organisation data removed | — | — | — |
| `device-decommission` | removed | — | — | — |

## Retention delays are disclosed

Deleting an encrypted object removes it from live server storage. Copies may persist in backups and disaster-recovery systems for up to 35 days before expiry. Those copies remain encrypted and the service cannot read them.

Instantaneous physical deletion from all backups is **not** claimed. `assert_no_overclaim` refuses user-facing text saying "completely gone", "immediately deleted from all backups", or "unrecoverable everywhere", and refuses claiming server deletion for a scope that does not perform it.

## Tombstones

Deleting across devices retains a tombstone for up to 180 days so a device that was offline does not resurrect the item when it reconnects. For memory and conversation metadata, a concurrent edit never silently restores a deleted item; the deletion is kept and the edit is queued for explicit review. See `docs/ENCRYPTED_SYNC.md` and `sync/conflict.py`.

## Account deletion

Removes the account, device registry, and all encrypted objects. Local data on the user's devices is **not** deleted; that is a separate action. Keys on the user's devices are not deleted either. It cannot be undone.

## Organisation data removal

Removes organisation profiles, managed configuration, and organisation credentials. Personal accounts, personal files, and private Bunny memories are untouched. Audit records of the removal are retained by the organisation.

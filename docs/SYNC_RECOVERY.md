# Sync account recovery

Implementation: `sync/recovery.py`. Tests: `tests/recovery`.

## The trade-off, stated plainly

Any mechanism that lets a user recover without holding a secret also lets the operator recover — and lets an attacker who compromises the operator recover. Bunny OS therefore refuses server-side recovery of private content. A recovery path must present the recovery secret or be authorised by an already-trusted device.

## Methods

| Method | Proves | Scope | Server can do it alone |
|---|---|---|---|
| Recovery phrase | Possession of a 24-word phrase | All collections the account holds | No |
| Recovery file | Possession of an exported key file | All collections the account holds | No |
| Trusted existing device | An already-paired device authorises the new one | Collections that device can read | No |
| Organisation recovery policy | A disclosed policy on an organisation-owned device | Organisation-owned collections only | No |

## Organisation recovery is bounded

It reaches `organisation-configuration`, `organisation-documents`, and `organisation-backup`, and nothing else. Requesting a personal collection is refused. Requesting it on a personally owned device is refused. It requires a reference to the policy disclosed at enrolment, and it is recorded in the audit log.

There is no organisation escrow of a user's personal keys. `docs/RECOVERY_KEYS.md` already establishes that Bunny OS holds no escrow copy of a LUKS recovery key, and sync does not introduce one.

## Mandatory warning

Shown when sync encryption is first enabled, with acknowledgement required:

> If you lose every key and your recovery secret, your synced data cannot be recovered. Your data is encrypted on your devices with keys the sync service never receives. That means nobody at the service, and nobody at Bunny OS, can decrypt it for you. Keep your recovery phrase or recovery file somewhere separate from your devices.

## Local recovery is unaffected

Recovery never depends solely on a cloud service. `docs/RECOVERY.md` describes a local recovery target present in every deployment plus a separately composed recovery image, and neither requires an account, a network, or a sync service.

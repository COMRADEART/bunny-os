# Remote wipe

Implementation: `enterprise/remote.py`. Tests: `tests/fleet`.

Five separate operations, kept separate so an administrator cannot reach for the largest hammer when they meant the smallest.

| Operation | Removes | Leaves |
|---|---|---|
| `organisation.data.remove` | Organisation profiles, managed configuration, organisation credentials | Personal files, personal accounts, private Bunny memories |
| `organisation.applications.remove` | Organisation-deployed applications | User-installed applications |
| `organisation.credentials.revoke` | Organisation credentials held on the device | Everything else |
| `device.factory-reset` | All local accounts, files, settings, memories, workspaces, checkpoints, and locally stored recovery keys | The recovery environment and its verified image |
| `device.cryptographic-erase` | The encryption keys, making stored data permanently unrecoverable | The recovery environment and its verified image |

## Personally owned devices

Never fully wiped remotely. `device.factory-reset` and `device.cryptographic-erase` are refused on any device not enrolled in an organisation-owned mode.

For the operations that *are* permitted on a personally owned device, all five preconditions apply: a clear prior policy disclosed at enrolment, multi-factor administrator authorisation where the operation demands it, an explicit non-empty scope, a UUID audit correlation id recorded before execution, and device-side confirmation where policy requires it.

## Recovery is protected

Full reset and cryptographic erase both preserve the recovery partition and its verified image, so a wiped device remains reinstallable. `enterprise/decommission.py` refuses to record a completed reset that did not preserve recovery.

## Consequences are disclosed, not implied

Both destructive operations return their data-loss consequences with the authorisation decision. In particular: locally stored recovery keys are destroyed, and `docs/RECOVERY_KEYS.md` already establishes that Bunny OS holds no escrow copy, so encrypted data with no external key copy becomes unrecoverable. There is no organisation-side key escrow that would change this.

## What is not tested

No remote wipe has been executed against a device. The tests verify the authorisation boundary, the ownership constraint, the precondition set, and the consequence disclosure. They do not verify that a wipe erases anything, because no executor exists.

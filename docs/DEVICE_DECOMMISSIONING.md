# Device decommissioning

Implementation: `enterprise/decommission.py`. Tests: `tests/decommission`.

## Why the action set is enumerated

Partial decommissioning is the common real-world failure: a device is wiped but its enrolment certificate is never revoked, or it is removed from the console while its sync device key still decrypts newly uploaded objects. `evaluate_decommission` refuses to report a device as decommissioned until every required action for that scenario is recorded.

## Scenarios and required actions

| Scenario | Required |
|---|---|
| `personally-owned-unenrolment` | revoke enrolment certificate, remove organisation data, remove organisation applications, revoke organisation credentials, remove from update rings, remove from groups, archive audit history, notify user |
| `organisation-owned-reassignment` | the above minus notify, plus revoke sync device, rotate sync keys, full reset |
| `device-retirement` | revoke certificate and credentials, revoke sync device, rotate sync keys, remove from rings and groups, archive audit history, cryptographic erase |
| `storage-replacement` | revoke sync device, rotate sync keys, cryptographic erase, archive audit history |
| `lost-device` | revoke certificate and credentials, revoke sync device, rotate sync keys, remove from rings, archive audit history, record incident report, notify user |
| `stolen-device` | as lost-device |

Personally owned unenrolment deliberately requires no wipe. The organisation withdraws its own footprint and nothing more.

## Ownership constraints

`full-reset` and `cryptographic-erase` require an organisation-owned device. Recording either on a personally owned device is refused. Both must preserve the recovery environment, or the record is refused.

Every decommission requires an audit correlation id, so the action is auditable.

## Lost and stolen devices

Revoke enrolment, revoke the sync device, rotate sync keys, invalidate organisation credentials, remove from update rings, archive audit history, record an incident report, and notify the user.

Honest guidance rather than reassurance:

- Encrypted data on the lost device stays protected by the user's LUKS credentials.
- Rotating sync keys prevents the device decrypting objects uploaded *after* revocation.
- Objects the device already downloaded cannot be retracted.
- Remote wipe remains constrained by ownership and prior policy; a personally owned device is not fully wiped. See `docs/REMOTE_WIPE.md`.

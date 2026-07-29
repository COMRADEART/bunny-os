# Device identity

Schema: `schemas/device-identity.schema.json`. Implementation: `enterprise/identity.py`. Tests: `tests/identity`.

## Constraint

`docs/PRIVACY.md` prohibits persistent tracking IDs, and `operations/redaction.py` already redacts `deviceid`, `serial`, and `macaddress` from every export. A device identity therefore has to be locally generated, rotatable, and unlinkable from hardware.

## Composition

A locally generated 128-bit installation identifier, an asymmetric device key, a TPM-backed private key where TPM 2.0 is present and a software-protected key otherwise, an optional device certificate, an optional enrolment identity, and a rotation history.

`locallyGenerated` is `const: true`. A server never issues a device identity and the factory never assigns one; `oem/validation/finalize.py` requires device identity to be absent or freshly created at handoff.

## Never the remote identity

MAC address, motherboard or chassis serial, product or system serial, storage or NVMe serial, CPU serial, IMEI, and advertising identifiers. `FORBIDDEN_IDENTITY_SOURCES` rejects a record that names any of them in `derivedFrom`, and the schema has no field for them.

Hardware identifiers stay available for local diagnostics, where `docs/DIAGNOSTICS.md` already scopes output to a local mode-0600 export and the existing redactor removes them from anything leaving the device.

## Four distinct concepts

`device identity`, `boot attestation`, `compliance status`, and `user identity` are separate. `assert_distinct_identity_kinds` refuses a payload that puts a user identifier inside a device-identity block, because that is how an operational record silently becomes a person-tracking record.

## Rotation

Reasons are a closed set: scheduled, operator-requested, suspected-compromise, storage-migration, reinstall, unenrolment, decommission. History must be chronological. Rotation on suspected compromise also rotates sync keys; see `docs/ENCRYPTED_SYNC.md`.

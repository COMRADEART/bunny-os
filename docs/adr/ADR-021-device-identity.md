# ADR-021: Device identity

- Status: accepted
- Date: 2026-07-29

## Decision

A device identity is a locally generated 128-bit installation identifier plus an asymmetric key, TPM-backed where TPM 2.0 is present and software-protected otherwise. It is rotatable, and `locallyGenerated` is a schema constant: no server issues it and no factory assigns it.

Hardware identifiers are never the remote identity. MAC address, board, chassis, product, storage, and CPU serials, IMEI, and advertising identifiers are refused as derivation sources and have no schema field. They remain usable for local diagnostics, where `operations/redaction.py` already strips them from anything leaving the device.

Device identity, boot attestation, compliance status, and user identity stay four separate concepts, and a payload that places a user identifier inside a device-identity block is refused.

## Why not hardware identifiers

They are the obvious choice and the wrong one. `docs/PRIVACY.md` prohibits persistent tracking IDs, and a hardware serial is the most persistent identifier a device has: it survives reinstall, cannot be rotated, links a device to a unit sold, and correlates across unrelated services. Using one as a remote identity would make every fleet report and every attestation a tracking beacon.

*A server-issued identifier* was rejected because it lets the issuer link devices before the device has consented to anything, and because it makes the enrolment service a mandatory dependency for an identity the device needs locally.

*TPM-only identity* was rejected because TPM 2.0 presence is not guaranteed across the hardware matrix, and requiring it would make device identity unavailable on supported hardware. The storage location is recorded honestly instead of assumed.

## Consequences

A device that reinstalls gets a new installation identifier and is a new device to a fleet, which is correct behaviour but means fleet inventory cannot silently track hardware across reinstalls. An organisation that wants asset tracking must maintain its own asset register keyed to something it owns; Bunny OS does not provide a hardware-derived handle for it.

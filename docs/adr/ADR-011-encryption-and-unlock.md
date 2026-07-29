# ADR-011: Encryption and unlock

- Status: accepted design; runtime qualification pending
- Date: 2026-07-28

## Decision

Use Anaconda/Blivet with cryptsetup LUKS2 for the encrypted automatic layout. Password unlock is required; a generated user-held recovery key is offered and must be confirmed. Optional TPM2 enrolment may be added only after encrypted password/recovery boot works and it always retains an independent password and recovery path.

Passwords and keys are secret-channel inputs, never protocol fields, argv, environment variables, logs, support bundles, first-run state, or image layers. Prefer Argon2id where the installed cryptsetup stack selects/supports it. The UI reports the active keyboard layout and never silently escrows or uploads a key.

## Recovery and TPM

A recovery key may be displayed, printed, or saved to an explicitly selected removable/user location; it is never automatically stored on the installed system. TPM policy initially binds only to a documented measured-boot PCR set after update, firmware-change, motherboard-reset, and fallback tests. TPM-only unlock is prohibited.

## Consequences

Phase 3 source validates an encryption plan and protected secret reference, but cannot claim working FDE until a disposable VM proves install, password unlock, wrong-password rejection, recovery-key unlock, update, rollback, and log/argv exclusion.

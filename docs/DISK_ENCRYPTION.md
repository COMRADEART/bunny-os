# Disk encryption

Bunny OS selects LUKS2 through Anaconda/Blivet and cryptsetup. The intended beta flow requires a password and offers a generated recovery key. Optional TPM2 assistance is experimental and must retain both fallback password and recovery key.

## Secret handling

- Passwords are entered twice with keyboard layout visible.
- Strength feedback is advisory and does not reject legitimate long passphrases.
- The frontend passes an opaque protected handle through the established installer secret channel; never JSON, argv, environment, logs, or image content.
- Recovery keys are displayed once and may be printed or saved only to an explicitly chosen target.
- There is no escrow, cloud upload, Bunny Core dependency, or automatic copy to the installed filesystem.
- Argon2id is preferred where the installed cryptsetup/Anaconda combination supports it; exact parameters must be recorded from the VM evidence rather than asserted here.

## TPM2

TPM enrolment remains disabled by default until measured-boot PCR policy is fixed and tested across kernel/image update, rollback, Secure Boot state change, firmware update, motherboard reset, and TPM clear. TPM-only unlock is prohibited. A valid password or recovery key must keep the volume recoverable.

## Required evidence

An encrypted install is not accepted until a disposable VM passes installation, password unlock, wrong-password rejection, recovery-key unlock, interrupted setup, keyslot inventory, update, rollback, recovery boot, and secret scans of argv/environment/journal/files. This host produced none of that evidence.


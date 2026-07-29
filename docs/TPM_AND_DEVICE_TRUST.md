# TPM and device trust

TPM 2.0 is optional. Basic boot, password-unlocked LUKS2, recovery, Bunny, updates, and conventional administration must work without a TPM.

Planned uses are measured-boot evidence, a non-exportable device identity, TPM-assisted LUKS2 unlock, and sealing references to update/recovery trust state. Private update signing keys never belong on clients. Provider credentials remain user Secret Service objects; Bunny sees handles or decrypted values only through the owning user session.

TPM enrollment must include a password recovery path and user-held recovery key, document PCR changes, permit clearing/re-enrollment, and avoid server-side device lock-in or silent escrow. Phase 1 only detects `/sys/class/tpm/tpm0` and reports `available`; it does not claim provisioning, measured-boot verification, or sealed-key protection.


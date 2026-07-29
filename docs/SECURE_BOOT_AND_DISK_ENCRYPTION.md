# Secure Boot and disk encryption

The production path is UEFI → distribution-signed shim/bootloader → signed kernel/initramfs/modules → image deployment, with LUKS2 for persistent data. Phase 1 consumes Fedora components but has not qualified the derived disk, so `secureBoot` inventory is detection evidence only and reports say untested.

Developer automation may use unencrypted ext4. Production should offer LUKS2 password unlock and a user-held recovery key, with optional TPM2 enrollment; basic unlock/recovery never depends on Bunny. There is no key escrow. Enrollment must display data-loss warnings and verify the recovery key before completion.

NVIDIA proprietary/custom modules are not bundled. Any later module requires license review, reproducible package path, signature/MOK enrollment, Secure Boot negative tests, update compatibility, and recovery removal. Development signing keys are never production trust roots.


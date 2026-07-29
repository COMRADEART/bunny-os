# Secure Boot

The intended chain is UEFI firmware to Fedora-signed shim/GRUB to the Fedora-signed kernel/initramfs/modules and the verified bootc deployment. The installer reports one of: enabled and supported; enabled with limitations; disabled; or unknown.

For the current source-only build, enabled systems must report `enabled_with_limitations` or `unknown`: no derived disk has booted, no unsigned-negative test ran, no recovery/update/rollback chain was validated, and no production image/media key exists.

Development keys are not production roots and private keys never enter the repository or pull-request CI. Release key rotation requires overlapping public trust, a signed transition, revocation metadata, and recovery media. Proprietary NVIDIA modules are not bundled; any later MOK/module-signing path requires a separate exact driver and Secure Boot matrix.

Users are not told to disable Secure Boot as a normal remedy. Safe graphics changes graphics parameters, not firmware trust. If a platform cannot follow the validated chain, the installer must explain the limitation or stop instead of claiming protection.


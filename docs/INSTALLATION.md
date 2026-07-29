# Install Bunny OS beta candidate

> No installable beta artifact has been produced from this checkout yet. Use this guide only with a release entry whose checksum, signature, provenance, SBOM, known issues, and VM test report are published together.

1. Download the ISO and adjacent manifest/signature from the named Bunny OS release channel.
2. Verify the detached signature with the separately obtained Bunny OS media public key, then verify checksums. On Bunny OS, use `bunny-os media verify`.
3. Write the ISO to a USB device using a tool that shows the exact model and size. This erases that USB; never guess the target.
4. Back up every internal disk. For Windows, save BitLocker recovery information, finish updates, disable Fast Startup/hibernation for preparation, and create unallocated space with Windows tools if dual booting.
5. Boot the USB in UEFI mode. Keep Secure Boot enabled when the published hardware status says the signed chain is supported. If it is not, read the release limitation before changing firmware security.
6. Choose Try or Install, Safe Graphics, Recovery Tools, Memory Test where available, or Verify Installation Media. Verification failure is a stop condition.
7. In the live session, connect networking only if wanted, review hardware compatibility, memory, storage, firmware, Secure Boot, and battery/power status.
8. Launch Install Bunny OS. Confirm the target by model, size, path, removable label, installation-source warning, and existing OS list.
9. Choose erase, encrypted erase, or verified free-space alongside. Review every create/reuse/format operation. Erase requires a disk-specific phrase and a second confirmation.
10. For encryption, enter and confirm a passphrase with the keyboard layout visible. Record and confirm the recovery key before continuing; keep it away from the computer.
11. Wait for final verification. Do not remove power or media during writes. If an error occurs, export the redacted diagnostics and follow the reported stage; do not blindly retry destructive steps.
12. Reboot, remove media, and unlock the disk. Complete first run; provider, local model, search, Bluetooth/audio, and backup are optional.
13. Open update status and recovery information. Confirm the previous deployment and recovery entry are visible before relying on rollback.
14. Review driver status. Intel/AMD open drivers are the default; proprietary NVIDIA is not included in this beta definition.

Troubleshooting: use Safe Graphics for display failure, Recovery Tools for deployment/boot inspection, and installation logs for the exact failed stage. Do not paste recovery keys or passwords into support reports. Dual boot, encryption, Secure Boot, rollback, and hardware claims apply only to the exact tested release tuple.


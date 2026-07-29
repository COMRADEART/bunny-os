# ADR-015: Dual-boot policy

- Status: accepted with deliberately limited support
- Date: 2026-07-28

## Decision

Support installation into already-unallocated free space while preserving existing partitions and EFI entries. Detect Windows/Linux, BitLocker-like/encrypted volumes, NTFS hibernation/Fast Startup risk, ESPs, mounted targets, RAID/LVM, and multiple disks. Reuse an eligible ESP without formatting it.

Phase 3 does not resize BitLocker, FileVault, encrypted Linux, hibernated NTFS, RAID, LVM, or unknown filesystems. General NTFS shrink is disabled until the mature resize-tool preflight and disposable Windows fixture pass. Users receive Windows backup, BitLocker recovery, hibernation, and Fast Startup guidance.

## Safety

The installation medium is excluded by default. Erase mode requires target identity plus a second destructive confirmation. Alongside/manual modes show exact operations and warn that writes cannot be rolled back. Both Bunny and existing boot entries must be verified after install where possible. Dual boot is never described as risk-free.

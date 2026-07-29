# Partitioning policy

## Qualified design

Bunny OS is UEFI/GPT and bootc image-managed. The conservative automatic layout is a 1 GiB VFAT EFI System Partition, 2 GiB ext4 `/boot`, and the remaining aligned system deployment. The system partition is ext4 or a LUKS2 container with ext4 inside. `/usr` and `/opt/bunny` come from the image; `/etc`, `/var`, and `/home` persist according to bootc semantics.

The host-tested planner supports erase, encrypted erase, OEM erase, and alongside planning into already-unallocated space. It can reuse an eligible existing ESP without formatting. Replacement/manual plans are schema-defined, but destructive execution is unqualified.

## Safety rules

- Installation media and read-only, mounted, undersized, unknown-sector, RAID, and multipath targets are blocked by the Bunny policy layer.
- Model, size, path, removable state, existing operating systems, and installation source are shown.
- Erase requires a disk-bound phrase and a second confirmation.
- Manual mode validates root, `/boot`, and `/boot/efi`; duplicate/unsafe mount points, overlaps, invalid sizes, preserve+format conflicts, and unsupported filesystems fail.
- Existing shared ESPs are preserved and never implicitly formatted.
- BitLocker, encrypted Linux, hibernated NTFS, RAID/LVM, and unknown filesystems are never resized.
- No plan claims partition-table writes are reversible.

Supported filesystem declarations are VFAT for ESP and ext4 for the beta system. Btrfs/XFS are understood by validation tooling but are not exposed as automatic beta combinations until bootc, update, rollback, and recovery tests qualify them. F2FS is not offered.

Synthetic metadata fixtures cover empty GPT/MBR, Windows UEFI, Linux, dual boot, encrypted Linux, BitLocker-like, multiple, small, read-only, removable media, and corrupted/unknown sectors. They are not destructive virtual-disk evidence.


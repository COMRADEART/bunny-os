# Dual boot

Phase 3's supported design is installation into verified, already-unallocated free space while preserving all existing partitions and firmware entries. The installer may reuse a sufficiently sized FAT ESP but does not format it. Bunny and existing entries are verified after installation where possible.

Before booting media, Windows users should make a current backup, save their BitLocker recovery information, finish updates, disable Windows Fast Startup/hibernation for the resize/preparation session, and create unallocated space with Windows' own supported tools. Disabling BitLocker or Secure Boot has security consequences and is not a default recommendation.

The probe identifies NTFS, BitLocker-like/encrypted volumes, Linux filesystems, ESPs, mounted devices, and multiple disks. It warns that firmware updates or boot-order changes may show a BitLocker recovery prompt and that dual boot cannot be risk-free.

The beta planner does not shrink BitLocker, encrypted Linux, hibernated NTFS, FileVault, RAID, LVM, or unknown filesystems. General in-installer NTFS resize remains disabled until filesystem checks, minimum-size calculation, AC-power detection, mature resize tooling, and disposable Windows fixtures pass. If safe free space cannot be verified, alongside mode is unavailable.


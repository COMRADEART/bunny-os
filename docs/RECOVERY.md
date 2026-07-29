# Recovery

Phase 1 supplies two related prototypes: `bunny-recovery.target` inside every OS deployment and a separately composed headless recovery QCOW2 profile. Neither runs Bunny Desktop/Core/app-server or needs network/cloud.

An authenticated `recovery.schedule` request writes a mode/UID/time marker atomically in a root-only directory. A validator rejects wrong fields, permissions, or symlinks; an early systemd generator selects the recovery target once. The recovery console removes the marker immediately, inventories version/deployments/filesystems, can select `bootc rollback`, disable Bunny autostart, disable user plugin directories, export redacted diagnostics, create a one-shot BLS entry with `nomodeset`, reboot, or power off. Mutations require typing `YES`.

Filesystem checking of a mounted filesystem is unsafe, so Phase 1 shows `lsblk --fs` and a dry-run repartition view; offline fsck per unmounted volume is a documented operator action. Configuration restore and full re-image are architectural requirements but are not automated until signed backup format, encryption, path traversal, ownership, and confirmation tests exist. Safe graphics clones only a concrete, regular, bounded default BLS entry, appends `nomodeset`, and asks `bootctl` to select it once; this path still requires VM/physical/Secure Boot qualification and may not work with every UKI/bootloader configuration.

Recovery cannot unlock encrypted data without the user's LUKS password/recovery key, cannot bypass Secure Boot, never silently resets, and is intentionally administrable with standard Linux tools.

# Phase 3 known issues

## Blockers

- No Phase 1/2 image existed at preflight, so no Phase 3 live/beta image could be derived or booted on this host.
- The Windows host lacks Podman, unified image-builder, Linux systemd, UEFI/KVM, loop/mount, Syft, Grype, and hardware fixtures.
- The Anaconda/Blivet production adapter is intentionally absent; the Bunny backend is simulation-only and fails before disk writes.
- No ISO/raw/QCOW2/recovery artifact, checksum/signature, SBOM, scan, VM install, encrypted boot, upgrade, rollback, or physical test exists.
- Fedora 44 Anaconda Web UI, bootc generic ISO, package list, live target, and boot menu must be qualified on the builder.
- `memtest86+` is declared for the live profile, but no boot-menu path is advertised until the composed ISO proves the EFI payload location.
- Secure Boot, TPM2, LUKS2, ESP reuse, firmware variables, dual boot, and failure cleanup are untested.
- The signed upstream Bunny Linux artifact and release trust material remain absent.

## Deliberate limitations

- x86-64 UEFI only; legacy BIOS and ARM64 are unsupported.
- Alongside planning uses already-unallocated free space; general filesystem resize and BitLocker resize are disabled.
- RAID, multipath, LVM reuse, FileVault, unknown sector sizes, and unsupported filesystems are blocked.
- Proprietary NVIDIA is not bundled; open/safe graphics remains experimental.
- OEM and unattended modes are scaffolds, not enabled production paths.
- Flathub is opt-in; no cloud provider, model, telemetry, or backup is required.

## Source-level caveats

The GTK live and first-run surfaces are source-compiled only and have not run with GNOME, screen reader, high contrast, scale, keyboard-only, multiple displays, or translations. Synthetic lsblk JSON validates parsing and policy but is not a virtual block-device destructive test. Any release report must retain those distinctions.

## Phase 5 stable-qualification blockers

- All required Phase 4/public-beta reports, images, feedback/failure records, signed update metadata, and observation history are absent.
- Public issue counts, failure rates, crash trends, beta duration/installations, and support capacity are unknown.
- No stable RC/artifact/signature/SBOM/provenance/reproducibility/license/malware evidence exists.
- Migration, preservation, rollback, independent recovery, multi-user, local-only, Bunny-disabled, privacy traffic/manual bundle, essential accessibility, physical hardware, kernel/driver, power/pressure, and soak tests did not run.
- Stable candidate/release gates intentionally fail and the decision is `NO-GO`.

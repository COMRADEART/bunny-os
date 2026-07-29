# Bunny OS Phase 3 report

Date: 2026-07-28  
Baseline commit: `8fc27253e448cfe0cbe267231f816012f831ebf0`  
Feature branch: `feature/installer-and-beta-image`  
Outcome: source/static implementation pass; destructive/image/VM/hardware completion blocked

## Preflight result

The mandatory documents and all ADRs were reviewed. Phase 1/2 host gates passed: 92 tests with one Linux-only skip, the 24-check original architecture verifier, checkout CLI/info, and static `gate-phase-2`. The required boot preflight could not run because `IMAGE_BUILD_REPORT.md` and `VM_TEST_REPORT.md` confirm that no Phase 1/2 OCI, QCOW2, recovery, or shell image exists. This prevents Phase 3 from meeting its definition of done.

## Architecture

- Installer framework: Fedora 44 Anaconda 44.x, separately packaged Anaconda Web UI, Anaconda D-Bus/Blivet, cryptsetup, Fedora shim/GRUB, bootc, and unified OSBuild image-builder `bootc-generic-iso`.
- Protocol version: 1, JSON Schema 2020-12, ten allowlisted operations, strict fields, no generic command or secret value.
- Component model: unprivileged live/installer presentation; read-only storage probe; pure plan/safety/encryption policy; established Anaconda privileged services; bootc deployment; post-install/recovery validation.
- Storage: GPT/UEFI, 1 GiB VFAT ESP, 2 GiB ext4 `/boot`, remaining ext4 system or LUKS2 container; bootc image-managed `/usr`/`/opt/bunny`, persistent `/etc`/`var`/`home` semantics.
- Supported source-planning modes: erase, encrypted erase, OEM erase, and install into verified unallocated free space. Manual/replace schemas validate but are not destructively executed.
- Filesystems exposed automatically: VFAT ESP and ext4. Btrfs/XFS are parsed/validated but unqualified as beta automatic layouts.

## Safety and encryption

The parser redacts serials/UUIDs, separates disks/partitions, recognizes existing Windows/Linux/encrypted structures, and marks installation/removable/mounted/read-only/small/complex/unknown-sector targets. Target disk ID, path, and byte size are bound and revalidated. Erase requires a disk-derived phrase plus a second confirmation. Plans display exact operations and say writes cannot be rolled back.

Encryption design is LUKS2 password plus user-held recovery key, with Argon2id preferred when the runtime supports it. JSON, argv, environment, logs, images, and first-run state cannot carry plaintext secrets. Optional TPM2 requires an explicit PCR policy, fallback password, and recovery key; TPM2 execution is not enabled. No LUKS volume/keyslot/unlock was produced.

## Boot and dual boot

UEFI is the only supported firmware mode; legacy BIOS is rejected. Fedora's signed boot chain is the design, but Secure Boot status is `unknown`/`enabled_with_limitations` because no derived image or unsigned-negative test exists. Existing ESPs/boot entries are preserved by policy. Dual boot is limited to already-unallocated free space; BitLocker, encrypted Linux, hibernated NTFS, RAID, LVM, FileVault, and unknown filesystem resize are disabled. No real Windows or dual-boot disk was executed.

## Live, first run, hardware, and applications

Live/beta profiles, package lists, boot menu, fixed ephemeral live user, disabled automount, GNOME welcome, Anaconda configuration, offline payload composition, media manifest/signing hooks, and QEMU disposable-disk launch definitions exist. They have not been composed or booted.

The per-user GTK first-run flow is resumable and optional. Its defaults keep telemetry/cloud/remote diagnostics/capture/indexing/plugin network off; providers, local models, search locations, Bluetooth/audio, and backup are optional. Credential values are excluded. User creation remains Anaconda/conventional elevation; no unrestricted sudo or root-equivalent groups are added.

Applications use image-owned native system packages, per-user Flatpak/portals, GNOME Software, and rootless developer containers. Flathub is explicit opt-in. Native permissions are labelled not enforceable. Bunny plugins remain separate. Proprietary NVIDIA is not bundled or auto-selected.

## Image formats and artifacts

Definitions: beta QCOW2/raw, live bootc-generic ISO with embedded offline payload, recovery QCOW2, OCI source images, external checksum/media manifest/signature hooks, provenance, SPDX/CycloneDX, vulnerability and licence paths. Produced artifacts: **none**. No checksum, signature, SBOM, package manifest, scan, ISO, raw, QCOW2, recovery image, or provenance output was generated on this host.

All requested artifact/VM targets were attempted. Windows Make could not resolve `bash`; direct MSYS2 Bash execution then reached the intended fail-closed checks: image builds reported missing Podman, inspection and Phase 1/2 VM scripts reported no QCOW2, media verification reported no live output, installation VM reported missing QEMU, upgrade reported no Phase 2 QCOW2, and SBOM reported missing Syft.

## Validation

Host/static results:

- repository validation: 27 JSON documents, 13 schema graphs, 130 Python files, 9 desktop entries, 8 XML/SVG assets, GNOME extension syntax;
- existing suite: 92 pass, one inherited Linux-only skip;
- Phase 3 suite: 60 pass;
- combined: 152 pass, one skip;
- `gate-phase-3`: pass in static mode;
- seven Phase 3 Bash scripts: syntax pass under MSYS2 Bash;
- installation baseline/ADR audit: pass.

Host-only medians/p95/max were 0.0128/0.0149/0.0946 ms for one synthetic Windows-disk parse, 0.0106/0.0118/0.0706 ms for an encrypted free-space plan, and 0.0050/0.0054/0.0278 ms for plan validation. `INSTALLER_PERFORMANCE_REPORT.md` limits these to deterministic source logic; every boot/UI/deployment/application/update timing remains unmeasured.

Coverage includes malformed/stale/secret/generic requests; wrong token/cross-user/replay; disk parsing/redaction; installation-media and wrong-disk blockers; identity-bound confirmations; erase/encrypted/alongside/manual plans; LUKS/TPM plan policy; recovery-key confirmation; media signature/hash/path checks with mocked signature process; live/beta definitions; first-run privacy/resume/secret/search restrictions; application/driver policy; and source-level command constraints.

Not executed: JSON Schema validator library, ShellCheck, installed-form systemd/desktop/Anaconda validation, SELinux, real lsblk/Blivet/Anaconda/cryptsetup/bootc, destructive virtual disk, image build/inspect, signature/SBOM/scans, UEFI/Secure Boot/TPM, VM install/encrypted install/upgrade/rollback/recovery, GTK/Orca/accessibility runtime, or physical hardware.

## Exact commands run

```text
python scripts/task.py validate
python scripts/task.py test
python scripts/task.py test-installer
python scripts/task.py installer-audit
python scripts/installer-performance.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\phase-1\verify.ps1
C:\msys64\usr\bin\make.exe PYTHON=python gate-phase-2
C:\msys64\usr\bin\make.exe PYTHON=python gate-phase-3
C:\msys64\usr\bin\bash.exe -n build/scripts/build-image.sh build/scripts/build-live-image.sh build/scripts/build-beta-image.sh build/scripts/verify-install-media.sh build/scripts/vm-install-smoke.sh build/scripts/vm-encrypted-install.sh build/scripts/vm-upgrade-test.sh
C:\msys64\usr\bin\bash.exe build/scripts/build-live-image.sh
C:\msys64\usr\bin\bash.exe build/scripts/build-beta-image.sh
C:\msys64\usr\bin\bash.exe build/scripts/verify-install-media.sh
C:\msys64\usr\bin\bash.exe build/scripts/vm-install-smoke.sh
C:\msys64\usr\bin\bash.exe build/scripts/vm-encrypted-install.sh
C:\msys64\usr\bin\bash.exe build/scripts/vm-upgrade-test.sh
```

Builder commands still required are the full command list in `docs/BETA_IMAGES.md`, with `FULL_GATE=1`, signed/reproducible inputs, fresh disposable disks, and manual accessibility/hardware matrices.

## Security and accessibility disposition

Host-tested planning boundaries are suitable for a Fedora/KVM validation attempt. Beta/release approval is denied. Blockers are the absent production Anaconda adapter qualification, images/VMs, LUKS/Secure Boot/TPM, destructive fixtures, supply-chain evidence, cross-user peer-credential service, UI runtime, and inherited signed Bunny/update/SELinux gaps. No Blocker is falsely marked closed.

## Unsupported configurations

Legacy BIOS, ARM64, in-installer general resize, BitLocker resize, RAID/multipath/LVM reuse, FileVault, proprietary NVIDIA, TPM-only unlock, unqualified memory-test boot entry, stable channel, production OEM/unattended install, cloud account services, and physical hardware certification.

## Recommendation for Phase 4

Do not begin Phase 4. First provision the trusted Fedora 44/KVM builder; close Phase 1/2 image/runtime blockers; build and boot the live/beta/recovery artifacts; implement and externally review the narrow Anaconda adapter; pass disposable-disk erase/encrypted/free-space/failure tests; pass upgrade/rollback/recovery and full accessibility/security/supply-chain gates; then run named physical hardware. Re-review Phase 3 only after that evidence exists.

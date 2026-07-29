# Bunny OS Phase 1 implementation report

Date: 2026-07-28  
Branch: `feature/os-foundation`  
Baseline: `8fc27253e448cfe0cbe267231f816012f831ebf0`

## Delivered

- Fedora 44 bootc/GNOME/Wayland/SELinux/firewalld architecture and four accepted OS ADRs.
- Independent contract 1.0.0 JSON Schema, update-manifest schema, and Bunny artifact schema.
- AF_UNIX/SO_PEERCRED broker with exact methods/params, Polkit, logind binding, nonce replay/rate controls, timeouts/cancellation, fixed subprocesses, bounded output, safe errors, and metadata audit.
- Conventional `bunny-os` CLI and local-only `bunny-os-info` with evidence states rather than support inference.
- Hardened system/user units, tmpfiles, sysctl, firewall zone, privacy-first first boot, offline health, and recovery target/profile.
- Signed Ed25519 manifest verification, revocation, expiry/channel/arch/contract/Bunny/repository/digest/space/sequence gates, atomic state, and bootc staging/rollback scaffolding.
- OCI Containerfile, explicit package/profile manifests, unified `image-builder` wrappers, image inspection/QEMU smoke scripts, provenance/checksums, SPDX/CycloneDX generation, vulnerability/license scans.
- Explicit upstream Bunny 0.2.0 placeholder and fail-closed release-directory hash/mode/path verifier. No Bunny source was copied or changed.
- Host tests, self-hosted privileged image CI gate, SELinux compile job, ten source diagrams, and demonstration package.

## Important implementation constraint

The original documents named the standalone `bootc-image-builder`; upstream OSBuild has merged/archived it. Phase 1 therefore uses unified `image-builder` and retains `bootc` in the installed system. This is a verified constraint update, not an architecture change.

## Not delivered as a result

No bootable artifact was produced on this host and no VM or hardware boot was observed. The repository contains the build system and bootable-image definition; `IMAGE_BUILD_REPORT.md` and `VM_TEST_REPORT.md` correctly record blocked execution. Phase 1 cannot be called release-complete against the user's definition of done until those gates run.

## Phase 2 implementation update

Branch `feature/bunny-shell` adds the GNOME 50 Bunny/Safe session definitions, image-owned extension, GTK launcher/settings/workspace/project/task/plan/approval/command surfaces, private metadata search, pinned/recent launcher state, workspace/settings/Core-summary/intent/terminal schemas, command parser/classifier, local/offline policy evaluation, private opt-in clipboard handling, bounded Git status, Nautilus actions, original themes/icons/wallpapers, bounded systemd user units, shell/shell-test image profiles, Phase 2 make targets, 59 new host tests, ADR-005 through ADR-009, user/developer documentation, and the demonstration package.

The implementation preserves GNOME/Mutter, Files, Terminal, Settings, notifications, portals, AT-SPI, base GNOME, and the Phase 1 broker. It adds no root or generic execution path. Source/host gates pass; image, GNOME, VM, Bunny Core, accessibility runtime, and hardware validation are not delivered on this host. See `PHASE_2_REPORT.md`.

## Phase 3 implementation update

Branch `feature/installer-and-beta-image` adds the installation baseline audit, ADR-010 through ADR-015, typed protocol/schema, serial-redacted fixed disk probe, target safety/confirmation, erase/encrypted/free-space/manual plan validation, primary-user policy, LUKS2/TPM/recovery-key policy, authenticated simulation-only backend, staged progress/cancellation model, redacted audit, media signature/checksum verification, hardware/driver detection and classification, resumable GTK first run, Flatpak/native permission policy, Fedora Anaconda Web UI/bootc live and beta profiles, offline package sets, boot menu, ephemeral live identity, no-automount configuration, media manifest/signing hooks, QEMU disposable-disk launch definitions, 19 installer guides, demonstration package, and 60 Phase 3 host tests.

The implementation deliberately contains no Bunny raw-disk executor. `install.start` fails before writes unless a reviewed Anaconda adapter is supplied. No Phase 1/2 image existed, so no live/beta artifact, install, LUKS, Secure Boot, VM, upgrade, rollback, recovery, UI runtime, or hardware result is delivered. See `PHASE_3_REPORT.md`.

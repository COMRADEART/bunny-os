# Next work after the Phase 1 implementation pass

Do not start a custom shell, compositor, visual redesign, installer experience, app store, or consumer release.

The immediate next milestone is **Phase 1 validation closure**:

1. provision trusted Fedora 44/KVM builder with digest-pinned base and unified image-builder;
2. run compose/inspection/SBOM/vulnerability/license/two-build gates and fix real package/tool differences;
3. boot QEMU/KVM and qualify services, first boot, network/listeners/privacy, health/update/rollback/recovery;
4. enforce and test OCI signature policy plus update key ceremony;
5. qualify SELinux domains and systemd security scores;
6. obtain signed upstream Bunny 0.2.0 Linux artifacts and run lifecycle/protocol/rollback tests;
7. run VMware/VirtualBox then named physical/Secure Boot/LUKS/GPU matrices.

Upstream Bunny requirement: publish a signed x86-64 Linux Tauri release directory containing Bunny Desktop, `bunny-core`, `ccgrep`, protocol v3 schema/provenance, SHA-256/modes/source commit, updater signature, SBOM, and clean install/update/rollback evidence. No Bunny repository edit was made in this phase.

## Phase 2 validation closure

Phase 2 source has now been implemented on `feature/bunny-shell`, but the inherited Phase 1 blockers prevented the required boot preflight and the Phase 2 image/VM/accessibility definition of done. The next milestone remains validation closure:

1. run `FULL_GATE=1 make gate-phase-2` on the pinned Fedora 44/KVM builder;
2. fix real package, GLib schema, systemd, GNOME 50 extension, GDM session, portal, and SELinux findings;
3. boot developer/shell/shell-test/recovery images and execute both VM matrices;
4. install the signed Bunny artifact and qualify authenticated task/plan/approval/provider/degraded flows;
5. execute Orca, keyboard, contrast/scale/motion, multi-monitor, suspend/resume, performance, privacy-egress, VMware/VirtualBox, and physical hardware tests;
6. archive image provenance, checksums, SBOM, vulnerability/licence reports, VM logs, and exact configurations.

Do not start Phase 3, an installer, app store, device provisioning/manufacturing, consumer distribution, or stable release work until these rows pass.

## Phase 3 validation closure

Phase 3 source work now exists on `feature/installer-and-beta-image`, but the inherited image blockers and absent Anaconda adapter prevent completion. Do not begin Phase 4. The next milestone is evidence closure:

1. close Phase 1/2 builder, signed Bunny, registry, SELinux, GNOME, accessibility and VM blockers;
2. pin/qualify Fedora 44 Anaconda Web UI, Blivet, cryptsetup, bootc and unified image-builder packages;
3. implement and externally review the narrow authenticated Anaconda adapter and protected secret channel;
4. build, sign, inspect and archive beta QCOW2/raw, live ISO, recovery, manifests, SBOMs, provenance and scans;
5. pass disposable-disk empty/encrypted/free-space/manual/failure/power-loss suites and prove no secret leakage;
6. pass UEFI/Secure Boot positive/negative, LUKS password/recovery and optional TPM fallback;
7. install Phase 2 then upgrade/rollback/recovery with user, Bunny, workspace, plugin, application and model preservation;
8. run Orca/keyboard/contrast/scale/motion/localisation and multi-user isolation;
9. run VMware/VirtualBox then named physical Intel/AMD/NVIDIA/NVMe/Wi-Fi/HiDPI matrices;
10. re-review Blocker/High findings and publish a beta candidate only when no Blocker remains.

Stable release, OEM partnerships/manufacturing, public store operation, cloud services and fleet management remain prohibited.

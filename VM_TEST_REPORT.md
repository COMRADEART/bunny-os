# Bunny OS Phase 1 VM test report

## Result: not performed

No QCOW2 existed and QEMU/KVM, `qemu-img`, OVMF, libguestfs, VirtualBox, and VMware were unavailable. No boot, GNOME graphics, networking, audio, suspend/resume, first login, Bunny launch, broker runtime, update stage, rollback, recovery, shutdown, or reboot was observed.

Planned first tuple: QEMU/KVM, q35 UEFI/OVMF, x86-64, 4 vCPU, 6–8 GiB RAM, 64 GiB virtio QCOW2, virtio network/GPU, NAT, serial capture. `make vm-smoke` checks a boot marker; it is not a substitute for the manual matrix in `docs/TESTING.md`.

VMware/VirtualBox remain separate untested rows. No physical hardware support may be inferred. Phase 2 is blocked until at least QEMU/KVM normal/recovery/previous-deployment tests and the full broker/update/rollback/diagnostics demonstration pass.

## Phase 2 shell matrix

No Phase 2 VM run occurred. `build/scripts/vm-shell-smoke.sh` targets the `shell-test` QCOW2 and checks only graphical-login serial markers; `tests/vm/PHASE_2.md` requires interactive Bunny/base/Safe session, launcher, panel, terminal, settings, notifications, approvals, workspaces, degraded modes, updates, recovery, logout/reboot, monitor/scaling, and accessibility checks. All rows are untested.

## Phase 3 installation matrix

No ISO or Phase 2 disk exists and QEMU/KVM/OVMF are unavailable, so live boot, media verification, storage probe, Anaconda, automatic/manual/encrypted install, reboot/unlock, first run, applications, update, upgrade, rollback, recovery, and shutdown were not observed. Scripts define fresh 80 GiB disposable QCOW2 launch paths and refuse reuse; the upgrade wrapper fails closed without a Phase 2 disk. They are not test results.

QEMU/KVM, VMware, VirtualBox, Secure Boot, TPM2 and physical hardware remain untested. See `INSTALLATION_TEST_REPORT.md`.

## Phase 5 stable-qualification matrix

The installation VM launcher was attempted on 2026-07-29 and stopped because `qemu-system-x86_64` is unavailable. No latest public beta exists to install. Clean/encrypted/offline install, prior-beta upgrade, rollback, recovery, migration, application install, diagnostics, multi-user, Bunny-disabled, local-only, driver regression, pressure, long-session, or soak VM scenario ran.

Phase 5 supplies evidence requirements and source tests only. QEMU/KVM, VirtualBox, VMware, Secure Boot, power-interruption, and independent recovery rows remain `NOT RUN`.

## 2026-07-29 QEMU/KVM remediation run

Developer and beta QCOW2 images were booted locally with QEMU/KVM, q35, OVMF
UEFI, four vCPUs, 6 GiB RAM, virtio disk/network/GPU, no graphical display, and
serial capture. The first developer run exposed a failing
`bunny-health-check.service`: its strict filesystem sandbox omitted
`/var/lib/bunny`, which the probe intentionally tests. After adding that exact
writable path and making the smoke gate require a finished health service, both
the rebuilt developer image and final beta image passed.

The final beta serial log reached `multi-user.target` and `graphical.target` and
contained `Finished bunny-health-check.service - Bunny OS boot health check.`
The bounded QEMU process ended after the expected 240-second observation
timeout; the smoke gate exited zero. The serial-log SHA-256 is
`675de0650b357a1ebfb3add832b7b262440ac0c36cbb597e19bc5fa1a7919616`.

This closes only the basic q35/OVMF/virtio boot and offline health-smoke defect.
Interactive GDM/Bunny behavior, install, LUKS, Secure Boot, TPM, update,
rollback, recovery, accessibility, VMware/VirtualBox, and physical hardware
remain untested.

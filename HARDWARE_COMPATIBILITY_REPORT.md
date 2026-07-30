# Bunny OS Phase 3 hardware compatibility report

Date: 2026-07-28

No physical hardware installation or live boot was performed. No Intel/AMD/NVIDIA, NVMe/SATA/USB/MMC, Secure Boot, TPM, Wi-Fi, Bluetooth, audio, camera, battery, suspend, HiDPI, multi-monitor, or firmware update may be called supported from this work.

| Tuple | Status | Evidence |
|---|---|---|
| x86-64 UEFI architecture | design target | schema, package, planner, and docs only |
| QEMU/KVM q35/OVMF/virtio | blocked | launcher definition; no artifact/runtime |
| Intel graphics | untested | Fedora kernel/Mesa policy only |
| AMD graphics | untested | Fedora amdgpu/Mesa policy only |
| NVIDIA | experimental policy | proprietary driver absent; no system test |
| Secure Boot/TPM/LUKS2 | untested | status and fallback policy only |
| legacy BIOS | unsupported | deliberate architecture decision |
| ARM64 | unsupported Phase 3 | x86-64-first decision |

The source classifier never upgrades presence to physical certification and includes `physicalHardwareCertified=false`. Minimum profiles are conservative capacity gates, not performance results. Hardware support remains a release blocker.

## Phase 5 update

The stable evidence database contains zero physical submissions. Recommended: 0; Supported: 0; all models remain Untested. The Phase 5 classifier requires physical clean/encrypted install, update, rollback, recovery, graphics, network, audio, suspend/resume, and no High issue for Stable recommended. No kernel, Mesa, firmware, NVIDIA, Wi-Fi, Bluetooth, audio, camera, dock, battery, or power result was added. See `STABLE_HARDWARE_SUPPORT_REPORT.md`.

## Phase 7 preflight update

No hardware has entered an OEM participation level or qualification programme.
No OEM profile, hardware-specific image, factory installation, burn-in, thermal,
sustained-load, Secure Boot, TPM, recovery, driver-update, or decommission test
was created or run. OEM readiness and every pilot remain `NO-GO`.

## 2026-07-29 virtual hardware update

The QEMU/KVM q35, OVMF UEFI, virtio disk/network/GPU tuple now has a successful
local beta boot-health smoke and a clean QCOW2 structural check. This changes
only that virtual smoke row from blocked to observed. It does not constitute an
interactive graphics result, an install result, a stable-candidate result, or
physical hardware certification. Every named physical, Secure Boot, TPM, LUKS,
GPU, network, audio, suspend, dock, battery, and firmware row remains untested.

## 2026-07-29 Phase 7 OEM qualification update

Phase 7 adds an OEM hardware qualification kit: `schemas/oem-qualification.schema.json` and `oem/qualification.py`, with thirteen required tests, six optional tests, and seven sustained-load scenarios each requiring six recorded observations including negative ones.

This changes no row in the matrix above. **Zero hardware models have been submitted, qualified, or tested.** Execution status is `NOT_RUN` for every test on every model, because no model exists.

The kit is distinct from the community hardware reporting in `operations/hardware.py`, which classifies submitted reports into support tiers. The OEM kit evaluates a signed per-model qualification run by the qualifying party.

Three refusals are enforced rather than documented: an image cannot be approved without validated recovery, nothing is described as certified without a completed formal process and at least two independent repeat runs, and no performance figure is accepted without a declared methodology of substance.

Consequently no hardware is described as certified, no OEM image has been built, and no recovery media has been booted on any device. `oemRecoveryValidation` is `false` and `make gate-oem-pilot` fails on it.

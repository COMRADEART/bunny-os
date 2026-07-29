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

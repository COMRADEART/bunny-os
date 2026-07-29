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


# Hardware and firmware support

Status words mean: **tested** physical execution; **partial** some required cases; **failed** reproduced failure; **blocked** unavailable dependency; **untested** no execution. Hardware presence or a VM result is never hardware support evidence.

| Category | Phase 1 status | Required evidence |
|---|---|---|
| Intel/AMD/NVIDIA laptop | untested | install/boot, Wi-Fi/Bluetooth/audio, suspend, battery, touchpad, camera portal, update/rollback |
| Intel/AMD/NVIDIA desktop | untested | install/boot, GPU/multi-display/audio, update/rollback/recovery |
| UEFI Secure Boot device | untested | enabled/disabled boot and unsigned-negative test |
| legacy BIOS | unsupported | architecture intentionally requires UEFI |
| HiDPI/multiple displays | untested | GNOME scaling, resume, hotplug |
| Intel/Realtek/Broadcom/MediaTek Wi-Fi | untested | firmware, WPA2/3, suspend/resume |
| Bluetooth chipsets | untested | keyboard/audio/power cycling |
| NVMe/SATA/USB storage | untested | install, trim/SMART, encryption, recovery |
| QEMU/KVM | blocked on this host | automated plus manual matrix |
| VMware/VirtualBox | untested | graphics, network, audio, suspend where supported |

Firmware comes only from redistributable Fedora `linux-firmware`/`fwupd` content and the base's licensing metadata. No proprietary NVIDIA driver is bundled. Intel/AMD open drivers and Mesa are the default path. Vendor firmware updates use fwupd only after explicit user action/policy.

| GPU | Install path | Secure Boot/Wayland | Local AI | Test status |
|---|---|---|---|---|
| Intel integrated | Fedora kernel/Mesa | expected distribution path; not qualified | runtime benchmark required | untested |
| AMD integrated/discrete | Fedora amdgpu/Mesa | expected distribution path; not qualified | ROCm not bundled | untested |
| NVIDIA open modules | future reviewed image extension | signing/enrollment required; Wayland matrix | CUDA runtime/license review | untested |
| NVIDIA proprietary | not bundled | license + module signing/MOK risk | future optional channel only | unsupported in Phase 1 |
| virtio/VMware virtual GPU | guest drivers/Mesa | VM-specific | no support claim | untested |
| software rendering | Mesa llvmpipe | troubleshooting fallback | CPU only | untested |

`bunny-os-info` reports detected vs driver-available/active vs runtime-verified evidence. Local model suitability is always `verified:false` until Bunny runs its upstream runtime benchmark. Models remain per-user, optional, quota-governed later, license-acknowledged, and never downloaded at first boot.


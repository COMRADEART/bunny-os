# Hardware provisioning

The preflight records architecture, CPU, RAM, target storage, graphics, display, Wi-Fi/Ethernet, Bluetooth, audio, battery, Secure Boot, TPM, virtualization, and firmware mode. Each item is `supported`, `supported_with_limitations`, `experimental`, `unsupported`, or `unknown`; detection alone never yields a physical-support claim.

## Requirements profiles

| Profile | Minimum | Recommended | Qualification note |
|---|---|---|---|
| Base desktop | x86-64 UEFI, 4 GiB RAM, 40 GiB storage | 8 GiB, 64 GiB | physical graphics/network/audio still device-specific |
| Cloud models | 8 GiB, 64 GiB | 16 GiB, 96 GiB | network only while a configured provider is used |
| Small local models | 16 GiB, 96 GiB | 24 GiB, 128 GiB | verified manifest plus runtime benchmark required |
| Medium local models | 32 GiB, 160 GiB | 64 GiB, 256 GiB | exact RAM/VRAM and throughput measured per model/device |
| Developer | 16 GiB, 128 GiB | 32 GiB, 256 GiB | containers/build tools increase storage demand |

These capacities are conservative installation gates, not local-model performance benchmarks. The beta source supports x86-64 UEFI only. Legacy BIOS and ARM64 are unavailable.

Firmware comes from Fedora-signed RPMs (`linux-firmware`, microcode dependencies) and explicit fwupd/LVFS updates. Missing firmware is reported; arbitrary third-party downloads are forbidden. Live Wi-Fi and NetworkManager profiles may migrate without logging credentials; offline skip remains available. Bluetooth, audio, display, and laptop setup are optional first-run checks with conservative defaults.


# Phase 5 reproduction and qualification fixtures

Every fixture uses immutable signed inputs, fresh disposable disks or QEMU snapshots, q35 UEFI, serial/journal capture, and a content-free preservation manifest. Never attach host storage.

| Hypervisor | Firmware/storage | Required Phase 5 cases | Status |
|---|---|---|---|
| QEMU/KVM | q35 OVMF, virtio/NVMe/SATA matrices | clean/encrypted/offline install; Beta N/N-1 updates; failure rollback; independent recovery; migration; multi-user; Bunny-disabled; local-only | NOT RUN |
| VirtualBox | UEFI, fresh VDI | install, graphics/network/audio, update/rollback/recovery, degraded modes | NOT RUN |
| VMware | UEFI, fresh VMDK | install, graphics/network/audio, update/rollback/recovery, degraded modes | NOT RUN |
| Secure Boot KVM | reviewed OVMF test keys | signed positive, unsigned/revoked/downgrade negative, recovery | NOT RUN |

Record source/artifact hashes, hypervisor version, CPU/RAM/devices, firmware variables, disk layout, encryption, exact steps, expected/actual result, failure signature, and cleanup. High-or-greater fixes require independent verification on a new RC.

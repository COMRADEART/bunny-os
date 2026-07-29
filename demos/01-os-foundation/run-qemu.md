# Run in QEMU

Use `make vm-smoke` for the serial marker. For the interactive demo use q35/UEFI OVMF, 4 vCPU, 8 GiB RAM, 64 GiB virtio QCOW2, virtio NAT and GPU. Start a snapshot/overlay so the source artifact remains unchanged. Record QEMU version, settings, serial log, and artifact SHA-256.


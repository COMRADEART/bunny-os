# Run in QEMU/KVM

Use q35 UEFI/OVMF, x86-64, 4 vCPU, 8 GiB RAM, 64 GiB virtio QCOW2, virtio GPU/network, NAT, and serial logging. First run `make vm-shell-smoke`; then boot the same artifact with a visible display. Record Fedora, GNOME Shell, QEMU, firmware, kernel, image digest, display backend, and host GPU.

At GDM verify Bunny, GNOME, and Bunny (Safe Shell) before selecting Bunny. Do not infer interactive success from the serial marker.

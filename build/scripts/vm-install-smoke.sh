#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

iso="${BUNNY_INSTALL_ISO:-build/out/live/bunny-os.iso}"
firmware="${BUNNY_OVMF_CODE:-/usr/share/edk2/ovmf/OVMF_CODE.fd}"
disk="${BUNNY_VM_DISK:-build/out/vm/phase3-install.qcow2}"
for command in qemu-system-x86_64 qemu-img timeout; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing VM command: ${command}" >&2; exit 3; }
done
[[ -f "${iso}" && -f "${firmware}" ]] || { echo "missing ISO or OVMF firmware" >&2; exit 3; }
[[ ! -e "${disk}" ]] || { echo "refusing to reuse disposable install disk: ${disk}" >&2; exit 4; }
mkdir -p "$(dirname "${disk}")"
qemu-img create -f qcow2 "${disk}" 80G
echo "Launching an interactive disposable-disk install smoke. Completion must be recorded manually." >&2
timeout "${BUNNY_VM_TIMEOUT:-1800}" qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host -smp 4 -m 8192 \
  -drive "if=pflash,format=raw,readonly=on,file=${firmware}" \
  -drive "if=virtio,format=qcow2,file=${disk}" \
  -cdrom "${iso}" \
  -device virtio-vga \
  -nic user,model=virtio-net-pci \
  -serial mon:stdio

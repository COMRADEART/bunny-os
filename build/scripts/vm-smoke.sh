#!/usr/bin/bash
set -euo pipefail

profile="${1:-developer}"
output="build/out/${profile}"
disk="$(find "${output}" -type f -name '*.qcow2' -print -quit)"
firmware="${OVMF_CODE:-/usr/share/OVMF/OVMF_CODE.fd}"
[[ -n "${disk}" ]] || { echo "QCOW2 image not found" >&2; exit 2; }
[[ -r "${firmware}" ]] || { echo "OVMF firmware not found at ${firmware}" >&2; exit 3; }
command -v qemu-system-x86_64 >/dev/null 2>&1 || { echo "qemu-system-x86_64 is required" >&2; exit 3; }

log="${output}/vm-smoke-serial.log"
set +e
timeout 240 qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max \
  -smp 4 \
  -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio,snapshot=on" \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net0 \
  -device virtio-vga \
  -display none \
  -serial "file:${log}" \
  -no-reboot
status=$?
set -e
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
  echo "QEMU failed with status ${status}" >&2
  exit "${status}"
fi
grep -aEiq 'Graphical Interface|Multi-User System|GNOME Display Manager' "${log}" || {
  echo "boot success marker not observed; see ${log}" >&2
  exit 4
}
grep -aEiq 'Finished .*Bunny OS boot health check' "${log}" || {
  echo "required Bunny OS health check did not finish successfully; see ${log}" >&2
  exit 4
}
echo "VM boot marker observed. Interactive graphics, Bunny, rollback, and recovery still require the documented manual matrix."

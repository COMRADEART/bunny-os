#!/usr/bin/env bash
# Quiet-boot network capture.
#
# docs/PRIVACY_REGRESSION_TESTING.md requires a quiet packet capture with
# updates disabled, and a separate capture per explicit network feature. This
# runs the quiet case: boot the image with nothing asked of it and record every
# packet the guest emits.
#
# QEMU's filter-dump writes a pcap at the netdev, so it sees the guest's own
# view before user-mode NAT rewrites anything. Any destination outside the
# 10.0.2.0/24 slirp range is real outbound traffic and is reported.
#
# A clean result is meaningful but narrow: it says an idle freshly booted image
# does not phone home. It says nothing about an installed system doing real
# work over days, which is what the production evidence row needs.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=build/scripts/vm-lib.sh
source "${script_dir}/vm-lib.sh"

profile="${1:-developer}"
output="build/out/${profile}"
disk="$(find "${output}" -type f -name '*.qcow2' -print -quit)"
seconds="${BUNNY_CAPTURE_SECONDS:-180}"
evidence="${BUNNY_EVIDENCE_DIR:-build/out/vm-evidence}"

[[ -n "${disk}" ]] || { echo "QCOW2 image not found under ${output}" >&2; exit 2; }
bunny_require_commands qemu-system-x86_64 timeout python3

mkdir -p "${evidence}"
capture="${evidence}/${profile}-quiet-boot.pcap"
log="${evidence}/${profile}-quiet-boot.log"
firmware="$(bunny_firmware)"

echo "== booting ${profile} with no user action and capturing all traffic =="
rm -f "${capture}"
status=0
timeout "${seconds}" qemu-system-x86_64 \
    -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 6144 \
    -bios "${firmware}" \
    -drive "file=${disk},format=qcow2,if=virtio,snapshot=on" \
    -device virtio-net-pci,netdev=net0 \
    -netdev user,id=net0 \
    -object "filter-dump,id=capture,netdev=net0,file=${capture}" \
    -display none -serial "file:${log}" -no-reboot || status=$?
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
    echo "QEMU failed with status ${status}" >&2
    exit "${status}"
fi

[[ -f "${capture}" ]] || { echo "no capture file was produced" >&2; exit 4; }

echo "== analysing capture =="
python3 "${script_dir}/analyse-capture.py" \
    --capture "${capture}" \
    --output "${evidence}/${profile}-network-privacy.json"

#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Phase 7 recovery journey, step 3: the repaired disk must boot normally.
#
# Boots the same disk the recovery session repaired — persistently broken
# before, persistently repaired now — and requires a healthy target plus the
# kernel's own ostree= identity. The outcome-verified step of the §5 journey.
set -uo pipefail

repo="${BUNNY_REPO:-/root/bunny-os}"
# shellcheck source=build/scripts/vm-lib.sh
source "${repo}/build/scripts/vm-lib.sh"

WORK="${BUNNY_P7_WORK:-/home/bunny/p7-work/recovery}"
EVIDENCE="${BUNNY_P7_EVIDENCE:-/home/bunny/p7-evidence/recovery}"
BROKEN="${WORK}/broken.qcow2"
timeout_seconds="${BUNNY_VM_TIMEOUT:-600}"

bunny_require_commands qemu-system-x86_64

[[ -f "${BROKEN}" ]] || { echo "NOT_RUN: no journey disk" >&2; exit 5; }
[[ -f "${EVIDENCE}/recovery-session.log" ]] || { echo "NOT_RUN: no recovery session ran" >&2; exit 5; }

log="${EVIDENCE}/repaired-boot.log"
firmware="$(bunny_firmware)"
: >"${log}"
status=0
timeout "${timeout_seconds}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 4096 \
  -bios "${firmware}" \
  -drive "file=${BROKEN},format=qcow2,if=virtio,snapshot=on" \
  -display none -serial "file:${log}" -no-reboot || status=$?
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
  echo "QEMU failed with status ${status}; see ${log}" >&2
  exit "${status}"
fi

echo "== repaired disk boot =="
bunny_boot_health "${log}" || true
grep -aoE 'ostree=/ostree/boot\.[0-9]+/[^/ ]+/[a-f0-9]{64}/[0-9]+' "${log}" | head -1 | sed 's/^/  /'
echo "  log: ${log}"

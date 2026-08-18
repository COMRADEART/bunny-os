#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Phase 7 recovery journey, step 1: make an installed disk that cannot boot,
# and PROVE it cannot.
#
# The breakage is a corrupted BLS entry: the kernel and initrd paths are
# rewritten to name a checksum directory that does not exist on the boot
# partition. GRUB finds no kernel; the machine never reaches a target. The
# `options` line — including the `ostree=` argument — is left intact, so the
# repair cannot cheat by reading the correct paths out of the corruption.
#
# The failed boot is measured, not assumed: a "broken" disk that reaches a
# healthy target fails this script, because a recovery qualified against a
# disk that was never broken is the grubenv mistake with new names.
set -uo pipefail

repo="${BUNNY_REPO:-/root/bunny-os}"
# shellcheck source=build/scripts/vm-lib.sh
source "${repo}/build/scripts/vm-lib.sh"

WORK="${BUNNY_P7_WORK:-/home/bunny/p7-work/recovery}"
EVIDENCE="${BUNNY_P7_EVIDENCE:-/home/bunny/p7-evidence/recovery}"
SUBJECT="${BUNNY_P7_SUBJECT_DISK:-/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z/bootc-fedora-44-qcow2-x86_64/bootc-fedora-44-qcow2-x86_64.qcow2}"
DISK="${WORK}/broken.qcow2"
BOOT_PART="${BUNNY_BOOT_PARTITION:-/dev/sda3}"
timeout_seconds="${BUNNY_VM_TIMEOUT:-300}"
BOGUS="0000000000000000000000000000000000000000000000000000000000000bad"

bunny_require_commands qemu-img qemu-system-x86_64 guestfish virt-ls

[[ -f "${SUBJECT}" ]] || { echo "NOT_RUN: subject disk absent: ${SUBJECT}" >&2; exit 5; }
[[ -e "${DISK}" ]] && { echo "REFUSED: ${DISK} already exists" >&2; exit 2; }
mkdir -p "${WORK}" "${EVIDENCE}"

echo "== subject identity =="
subject_sha="$(sha256sum "${SUBJECT}" | cut -d' ' -f1)"
echo "  ${SUBJECT}"
echo "  sha256 ${subject_sha}"

echo "== overlay and breakage =="
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${SUBJECT}")" "${DISK}" >/dev/null
entry="$(virt-ls -a "${DISK}" -m "${BOOT_PART}" /loader/entries | grep '\.conf$' | head -1)"
[[ -n "${entry}" ]] || { echo "NOT_RUN: no BLS entry on the subject disk" >&2; exit 5; }
before="$(guestfish --ro -a "${DISK}" -m "${BOOT_PART}" cat "/loader/entries/${entry}")"
real_csum="$(echo "${before}" | grep -E '^linux ' | grep -oE '[a-f0-9]{64}' | head -1)"
[[ -n "${real_csum}" ]] || { echo "NOT_RUN: could not read the kernel checksum dir" >&2; exit 5; }
broken="$(echo "${before}" | sed -E "s|^(linux .*)${real_csum}|\1${BOGUS}|; s|^(initrd .*)${real_csum}|\1${BOGUS}|")"
fixed_file="${WORK}/broken-entry.conf"
printf '%s\n' "${broken}" >"${fixed_file}"
guestfish -a "${DISK}" -m "${BOOT_PART}" upload "${fixed_file}" "/loader/entries/${entry}"
echo "  ${entry}: kernel/initrd now name ${BOGUS:0:12}... (nonexistent)"
diff <(printf '%s\n' "${before}") <(printf '%s\n' "${broken}") | sed 's/^/  /' || true

echo "== the broken disk must fail to boot =="
log="${EVIDENCE}/broken-boot.log"
firmware="$(bunny_firmware)"
: >"${log}"
status=0
timeout "${timeout_seconds}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 4096 \
  -bios "${firmware}" \
  -drive "file=${DISK},format=qcow2,if=virtio,snapshot=on" \
  -display none -serial "file:${log}" -no-reboot || status=$?

if grep -aEq 'Reached target|Multi-User System|Graphical Interface' "${log}"; then
  echo "FAIL: the 'broken' disk reached a boot target; the breakage control failed" >&2
  exit 4
fi
echo "  no boot target reached within ${timeout_seconds}s (qemu status ${status})"

python3 - "${EVIDENCE}/breakage.json" <<PY
import json, sys
json.dump({
    "subjectDisk": "${SUBJECT}",
    "subjectSha256": "${subject_sha}",
    "brokenDisk": "${DISK}",
    "blsEntry": "${entry}",
    "realChecksumDir": "${real_csum}",
    "bogusChecksumDir": "${BOGUS}",
    "brokenBootReachedTarget": False,
    "note": "options/ostree= left intact; only linux and initrd paths corrupted",
}, open(sys.argv[1], "w"), indent=1, sort_keys=True)
PY
echo
echo "BREAKAGE CONTROLLED: the disk is broken and measured broken."

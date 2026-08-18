#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Phase 7 recovery journey, step 2: boot the recovery medium with the broken
# disk attached, inspect the installation, repair the boot entry, and prove
# every step on the serial log.
#
# The recovery console is interactive by design (tty1, typed YES). This
# harness does not pretend to type: it instruments a DERIVED overlay of the
# recovery medium with a oneshot driver unit that performs the documented
# operator steps (docs/RECOVERY.md: inspect deployments, repair boot) and
# records both digests — the pristine medium's and the instrumented
# overlay's. The medium qualified is the pristine one; the overlay is the
# instrument, and saying otherwise would be the §6 mistake.
#
# The repair derives the correct kernel and initrd paths from the broken
# disk's own /ostree directory on its boot partition. Nothing was stashed at
# breakage time, so there is nothing to copy back: the repair is computed
# from on-disk truth or it does not happen.
set -uo pipefail

repo="${BUNNY_REPO:-/root/bunny-os}"
# shellcheck source=build/scripts/vm-lib.sh
source "${repo}/build/scripts/vm-lib.sh"

WORK="${BUNNY_P7_WORK:-/home/bunny/p7-work/recovery}"
EVIDENCE="${BUNNY_P7_EVIDENCE:-/home/bunny/p7-evidence/recovery}"
MEDIUM="${BUNNY_P7_RECOVERY_MEDIUM:?the pristine recovery medium qcow2 must be named}"
BROKEN="${WORK}/broken.qcow2"
OVERLAY="${WORK}/recovery-instrumented.qcow2"
timeout_seconds="${BUNNY_VM_TIMEOUT:-600}"

bunny_require_commands qemu-img qemu-system-x86_64 guestfish sha256sum

[[ -f "${MEDIUM}" ]] || { echo "NOT_RUN: recovery medium absent: ${MEDIUM}" >&2; exit 5; }
[[ -f "${BROKEN}" ]] || { echo "NOT_RUN: no broken disk; run break-disk.sh first" >&2; exit 5; }
[[ -f "${EVIDENCE}/breakage.json" ]] || { echo "NOT_RUN: no breakage record" >&2; exit 5; }
mkdir -p "${WORK}" "${EVIDENCE}"

echo "== media identities =="
medium_sha="$(sha256sum "${MEDIUM}" | cut -d' ' -f1)"
echo "  pristine medium: ${MEDIUM}"
echo "  sha256 ${medium_sha}"

rm -f "${OVERLAY}"
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${MEDIUM}")" "${OVERLAY}" >/dev/null

driver="${WORK}/recovery-driver.sh"
cat >"${driver}" <<'DRIVER'
#!/usr/bin/bash
set -uo pipefail
mark() { echo "BUNNY-P7R: $*"; }
mark "BEGIN recovery driver"
mark "recovery-os=$(grep PRETTY_NAME /usr/lib/os-release | head -1)"
mark "recovery-target=$(systemctl get-default 2>/dev/null || echo UNKNOWN)"

# The broken disk is the second virtio disk.
disk=/dev/vdb
for _ in $(seq 30); do [ -b "${disk}" ] && break; sleep 1; done
[ -b "${disk}" ] || { mark "FAIL: no attached disk"; exit 1; }

mkdir -p /run/p7r/boot /run/p7r/root
mount "${disk}3" /run/p7r/boot || { mark "FAIL: cannot mount boot partition"; exit 1; }
mount -o ro "${disk}4" /run/p7r/root || { mark "FAIL: cannot mount root partition"; exit 1; }

mark "INSPECT: deployments on the attached installation"
for d in /run/p7r/root/ostree/deploy/*/deploy/*.0; do
  [ -d "$d" ] || continue
  mark "deployment=$(basename "$d")"
  origin="${d%/}.origin"
  [ -f "$origin" ] && grep -h "image" "$origin" | while read -r line; do mark "origin=${line}"; done
  pretty="$(grep -h PRETTY_NAME "$d/usr/lib/os-release" 2>/dev/null | head -1)"
  mark "os-release=${pretty}"
done

mark "REPAIR: deriving kernel paths from the boot partition"
entry="$(ls /run/p7r/boot/loader/entries/*.conf 2>/dev/null | head -1)"
[ -n "${entry}" ] || { mark "FAIL: no BLS entry to repair"; exit 1; }
mark "entry=$(basename "${entry}")"
mark "entry-before-linux=$(grep -E '^linux ' "${entry}")"
kdir="$(ls -d /run/p7r/boot/ostree/*/ 2>/dev/null | head -1)"
[ -n "${kdir}" ] || { mark "FAIL: no kernel directory on the boot partition"; exit 1; }
kname="$(basename "${kdir%/}")"
kernel="$(ls "${kdir}"vmlinuz-* 2>/dev/null | head -1)"
initrd="$(ls "${kdir}"initramfs-* 2>/dev/null | head -1)"
[ -n "${kernel}" ] && [ -n "${initrd}" ] || { mark "FAIL: kernel or initrd missing in ${kname}"; exit 1; }
mark "derived-dir=${kname}"
sed -i -E "s|^linux .*|linux /boot/ostree/${kname}/$(basename "${kernel}")|; s|^initrd .*|initrd /boot/ostree/${kname}/$(basename "${initrd}")|" "${entry}"
mark "entry-after-linux=$(grep -E '^linux ' "${entry}")"
mark "entry-after-initrd=$(grep -E '^initrd ' "${entry}")"
sync
umount /run/p7r/root /run/p7r/boot
mark "REPAIRED"
mark "END recovery driver"
DRIVER

unit="${WORK}/bunny-p7r-driver.service"
cat >"${unit}" <<'UNIT'
[Unit]
Description=Phase 7 recovery journey driver
After=multi-user.target bunny-recovery.target
ConditionPathExists=/etc/bunny-p7r/recovery-driver.sh

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c '/usr/bin/bash /etc/bunny-p7r/recovery-driver.sh; echo "BUNNY-P7R: wrapper exit=$?"; sync; sleep 2; systemctl poweroff'
TimeoutStartSec=10min
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target bunny-recovery.target
UNIT

echo "== instrumenting the overlay (the medium itself is untouched) =="
guestfish -i -a "${OVERLAY}" <<GF
mkdir-p /etc/bunny-p7r
upload ${driver} /etc/bunny-p7r/recovery-driver.sh
chmod 0644 /etc/bunny-p7r/recovery-driver.sh
upload ${unit} /etc/systemd/system/bunny-p7r-driver.service
chmod 0644 /etc/systemd/system/bunny-p7r-driver.service
mkdir-p /etc/systemd/system/multi-user.target.wants
ln-sf /etc/systemd/system/bunny-p7r-driver.service /etc/systemd/system/multi-user.target.wants/bunny-p7r-driver.service
mkdir-p /etc/systemd/system/bunny-recovery.target.wants
ln-sf /etc/systemd/system/bunny-p7r-driver.service /etc/systemd/system/bunny-recovery.target.wants/bunny-p7r-driver.service
lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 /etc/bunny-p7r
lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 /etc/bunny-p7r/recovery-driver.sh
lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0 /etc/systemd/system/bunny-p7r-driver.service
GF
overlay_sha="$(sha256sum "${OVERLAY}" | cut -d' ' -f1)"
echo "  instrumented overlay sha256 ${overlay_sha}"

echo "== booting recovery with the broken disk attached =="
log="${EVIDENCE}/recovery-session.log"
firmware="$(bunny_firmware)"
: >"${log}"
status=0
timeout "${timeout_seconds}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 4096 \
  -bios "${firmware}" \
  -drive "file=${OVERLAY},format=qcow2,if=virtio" \
  -drive "file=${BROKEN},format=qcow2,if=virtio" \
  -display none -serial "file:${log}" -no-reboot || status=$?
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
  echo "QEMU failed with status ${status}; see ${log}" >&2
  exit "${status}"
fi
grep -a "BUNNY-P7R" "${log}" | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | sed 's/^/  /'

python3 - "${EVIDENCE}/recovery-media.json" <<PY
import json, sys
json.dump({
    "pristineMedium": "${MEDIUM}",
    "pristineSha256": "${medium_sha}",
    "instrumentedOverlaySha256": "${overlay_sha}",
    "instrumentation": "qualification/phase7/recovery/recover.sh driver unit; documented operator steps, no console interaction",
    "signature": "NONE - production signing is an external gate; this run is engineering evidence for the journey, not release evidence for the medium",
}, open(sys.argv[1], "w"), indent=1, sort_keys=True)
PY
echo
echo "recovery session complete; verdict comes from verdict.py after verify-disk.sh"

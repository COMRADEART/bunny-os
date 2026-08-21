#!/usr/bin/bash
# Roll back the way a device would, and read which deployment actually booted.
#
# `vm-rollback-test.sh deployment-rollback` reports
#
#   Rollback PASSED: the previous deployment was selected and reached a healthy
#   target.
#
# and it is wrong. It selects the previous entry by writing
#
#   guestfish ... write /grub2/grubenv "# GRUB Environment Block\nsaved_entry=1\n"
#
# A GRUB environment block is a fixed 1024-byte record padded with '#'. A short
# file is not one, so the write is ignored, the machine boots its default, and
# the harness's only check -- "did it reach a healthy target" -- passes. Three
# boots of that harness all report
#
#   os-release commit=e501218f2fe0...   (N+1, on every one)
#   bootc booted=/run/p5update/candidate:e501218f2fe0
#   bootc rollback=localhost/bunny-os-beta:e906a48793d7
#
# identical cmdline `ostree=` argument included. The rollback target was there
# the whole time and was never booted. This is the §5 failure exactly: the
# machine survived, so the journey was recorded as a success.
#
# So: use `bootc rollback`, which is the command the product documents and a
# device would run, then boot again and ask the deployment what it is.
set -uo pipefail
WORK=/home/bunny/p5-work/stage
EVIDENCE=/home/bunny/p5-evidence/rollback-real
STAGED="${WORK}/staged.qcow2"
DISK="${WORK}/rollback-real.qcow2"
UPDATE_IMG="${WORK}/update.img"
ROOT_PARTITION=/dev/sda4
mkdir -p "${EVIDENCE}"

[[ -f "${STAGED}" ]] || { echo "no staged disk" >&2; exit 3; }

echo "== a disposable copy of the staged disk =="
rm -f "${DISK}"
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${STAGED}")" "${DISK}" >/dev/null

mapfile -t deployments < <(guestfish --ro -a "${DISK}" run : mount "${ROOT_PARTITION}" / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null)
echo "  deployments: ${#deployments[@]}"

cat >"${WORK}/rollback.sh" <<'ROLLBACK'
#!/usr/bin/bash
set -uo pipefail
mark() { echo "BUNNY-P5-ROLLBACK: $*"; }
run() { "$@" 2>&1 | sed 's/^/    /'; return "${PIPESTATUS[0]}"; }

mark "before:"
run bootc status
mark "running bootc rollback"
run bootc rollback
mark "rollback exit=$?"
mark "after:"
run bootc status
run ostree admin status

# Run once. Leaving this enabled would roll back again on the next boot and the
# second reading would be of a machine that had rolled forward and back.
rm -f /etc/systemd/system/multi-user.target.wants/bunny-p5-rollback.service
sync
mark "done"
ROLLBACK

cat >"${WORK}/bunny-p5-rollback.service" <<'UNIT'
[Unit]
Description=Phase 5 rollback
After=multi-user.target
ConditionPathExists=/etc/bunny-p5-stage/rollback.sh

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c '/usr/bin/bash /etc/bunny-p5-stage/rollback.sh; echo "BUNNY-P5-ROLLBACK: wrapper exit=$?"; sync; sleep 2; systemctl poweroff'
TimeoutStartSec=15min
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
UNIT

echo "== injecting the rollback unit into every deployment =="
commands=(run : mount "${ROOT_PARTITION}" /)
labels=(run : mount "${ROOT_PARTITION}" /)
for entry in "${deployments[@]}"; do
  entry="${entry%/}"
  commands+=(: mkdir-p "${entry}/etc/bunny-p5-stage")
  commands+=(: upload "${WORK}/rollback.sh" "${entry}/etc/bunny-p5-stage/rollback.sh")
  commands+=(: chmod 0644 "${entry}/etc/bunny-p5-stage/rollback.sh")
  commands+=(: upload "${WORK}/bunny-p5-rollback.service" "${entry}/etc/systemd/system/bunny-p5-rollback.service")
  commands+=(: chmod 0644 "${entry}/etc/systemd/system/bunny-p5-rollback.service")
  commands+=(: mkdir-p "${entry}/etc/systemd/system/multi-user.target.wants")
  commands+=(: ln-sf /etc/systemd/system/bunny-p5-rollback.service
             "${entry}/etc/systemd/system/multi-user.target.wants/bunny-p5-rollback.service")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
           "${entry}/etc/bunny-p5-stage/rollback.sh")
  labels+=(: lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0
           "${entry}/etc/systemd/system/bunny-p5-rollback.service")
done
guestfish -a "${DISK}" "${commands[@]}"
guestfish -a "${DISK}" "${labels[@]}"

firmware=/usr/share/edk2/ovmf/OVMF_CODE.fd
[[ -f "${firmware}" ]] || firmware=$(find /usr/share -name 'OVMF_CODE*.fd' 2>/dev/null | head -1)

boot() {
  local log="$1" seconds="$2"
  : >"${log}"
  timeout "${seconds}" qemu-system-x86_64 \
    -machine q35,accel=kvm:tcg \
    -cpu max -smp 4 -m 6144 \
    -bios "${firmware}" \
    -drive "file=${DISK},format=qcow2,if=virtio" \
    -drive "file=${UPDATE_IMG},format=raw,if=virtio" \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -display none -serial "file:${log}" -no-reboot
  echo "  qemu exit=$?"
}

echo
echo "== boot 1: the machine rolls itself back =="
boot "${EVIDENCE}/boot1-rollback.log" 900
grep -a "BUNNY-P5-ROLLBACK\|BUNNY-P5-STATE" "${EVIDENCE}/boot1-rollback.log" \
  | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | sed 's/^/  /'

echo
echo "== boot 2: which deployment came up? =="
boot "${EVIDENCE}/boot2-after.log" 900
grep -a "BUNNY-P5-STATE" "${EVIDENCE}/boot2-after.log" \
  | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | sed 's/^/  /'

echo
echo "ROLLBACK-REAL-DONE"

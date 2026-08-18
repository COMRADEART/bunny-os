#!/usr/bin/bash
# Stage N+1 onto a copy of N, so a disk with two deployments exists.
#
# Both update and rollback qualification stop at the same place: a freshly
# built image carries exactly one bootc deployment, and neither
# `vm-upgrade-test.sh staged` nor `vm-rollback-test.sh deployment-rollback`
# will pass vacuously on one. They exit 5 and say so. What has been missing is
# not the harness -- it is a disk on which an update has actually been staged.
#
# Phase 5 has two images now, so this makes that disk: boot N, hand it N+1 on a
# second drive, let the shipped `bootc` stage it, power off. Nothing is
# simulated; the staging is done by the same binary a device would use, on the
# same disk layout.
#
# Rules inherited from capsule-qualify-inject.sh, each learned the hard way:
#   * guestfish, not virt-customize -- a bootc disk has no inspectable root;
#   * writes confined to <deployment>/etc and the stateroot's /var, because
#     <deployment>/usr is a sealed composefs image;
#   * every created file gets an SELinux label explicitly, because a
#     guestfish-created file has none at all and the policy silently refuses it.
#
# Two learned here:
#
#   * the unit does NOT exec the injected script. The first attempt set
#     ExecStart to the script with a bin_t label and the unit failed before
#     printing a line of its own -- the failure of an exec, not of the work. It
#     execs /usr/bin/bash and passes the script as an argument, so the script is
#     read rather than executed.
#   * `bootc switch --transport oci-archive` is listed in `--help` and is not
#     implemented: the guest answered `unsupported transport "oci-archive" for
#     looking up local images`. The drive therefore carries an OCI *directory*,
#     and the guest tries `oci` first and falls back to copying into
#     containers-storage with the shipped skopeo. Both attempts are logged, so
#     whichever works, the record says which.
set -uo pipefail

WORK=/home/bunny/p5-work/stage
EVIDENCE=/home/bunny/p5-evidence/update
ARCHIVE_DIR=$(find /root/bunny-build-archive -maxdepth 1 -type d -name 'beta-phase4-rc-e906a48793d7-*' | sort | tail -1)
BASE=$(find "${ARCHIVE_DIR}/bootc-fedora-44-qcow2-x86_64" -name '*.qcow2' 2>/dev/null | head -1)
CANDIDATE_TAR=/root/bunny-os/build/out/beta/bunny-os.oci.tar
TAG="${BUNNY_CANDIDATE_TAG:-e501218f2fe0}"
ROOT_PARTITION="${BUNNY_ROOT_PARTITION:-/dev/sda4}"
STAGED="${WORK}/staged.qcow2"
UPDATE_IMG="${WORK}/update.img"

mkdir -p "${WORK}" "${EVIDENCE}"

echo "== inputs =="
echo "  N       : ${BASE:-NOT FOUND}"
echo "  N+1 tar : ${CANDIDATE_TAR}"
[[ -f "${BASE}" ]] || { echo "the previous disk is required" >&2; exit 3; }
[[ -f "${CANDIDATE_TAR}" ]] || { echo "the candidate archive is required" >&2; exit 3; }
sha256sum "${BASE}" "${CANDIDATE_TAR}" | tee "${EVIDENCE}/stage-inputs.sha256"

echo
echo "== a writable copy of N (N itself stays pristine) =="
rm -f "${STAGED}"
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${BASE}")" "${STAGED}" >/dev/null
qemu-img info "${STAGED}" | head -5 | sed 's/^/  /'

echo
echo "== a second drive carrying the candidate as an OCI directory =="
if [[ ! -f "${UPDATE_IMG}" || "${BUNNY_REBUILD_UPDATE_IMG:-0}" == "1" ]]; then
  rm -f "${UPDATE_IMG}"
  truncate -s 12G "${UPDATE_IMG}"
  mkfs.ext4 -q -F "${UPDATE_IMG}"
  mkdir -p /mnt/p5-update
  mount -o loop "${UPDATE_IMG}" /mnt/p5-update || { echo "loop mount failed" >&2; exit 4; }
  echo "  converting oci-archive -> oci directory"
  skopeo copy "oci-archive:${CANDIDATE_TAR}" "oci:/mnt/p5-update/candidate:${TAG}" \
    || { umount /mnt/p5-update; echo "skopeo copy failed" >&2; exit 4; }
  du -sh /mnt/p5-update/candidate | sed 's/^/  /'
  df -h /mnt/p5-update | tail -1 | sed 's/^/  /'
  sync
  umount /mnt/p5-update
fi
ls -la "${UPDATE_IMG}" | sed 's/^/  /'

echo
echo "== the deployment to write into =="
deployment="$(guestfish --ro -a "${STAGED}" run : mount "${ROOT_PARTITION}" / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null | head -1)"
[[ -n "${deployment}" ]] || { echo "no ostree deployment on ${ROOT_PARTITION}" >&2; exit 2; }
deployment="${deployment%/}"
stateroot="$(dirname "$(dirname "${deployment}")")"
echo "  deployment: ${deployment}"
echo "  stateroot:  ${stateroot}"

cat >"${WORK}/stage.sh" <<RUNNER
#!/usr/bin/bash
# Injected. Everything it prints goes to the serial console, because the host
# reads the serial log and a message only in the journal is a message the host
# cannot see.
set -uo pipefail
TAG="${TAG}"
RUNNER
cat >>"${WORK}/stage.sh" <<'RUNNER'
LOG=/var/log/bunny-p5-stage.log
say() { echo "BUNNY-P5-STAGE: $*" | tee -a "${LOG}"; }
run() { "$@" 2>&1 | sed 's/^/    /' | tee -a "${LOG}"; return "${PIPESTATUS[0]}"; }

say "begin $(date -Is)"
say "current deployment:"
run bootc status

# §20: state a rollback must not lose, written before the switch.
source /etc/bunny-p5-stage/state-fragment.sh
write_state

say "free space before:"
run df -h /sysroot /var

mkdir -p /run/p5update
if mount -o ro /dev/vdb /run/p5update; then
  say "mounted /dev/vdb"
else
  say "MOUNT FAILED for /dev/vdb"
  run lsblk -o NAME,SIZE,FSTYPE
fi
run ls -la /run/p5update

source_dir="/run/p5update/candidate"
if [[ ! -d "${source_dir}" ]]; then
  say "OCI DIRECTORY MISSING at ${source_dir}"
else
  say "attempt 1: bootc switch --transport oci ${source_dir}:${TAG}"
  if run bootc switch --transport oci "${source_dir}:${TAG}"; then
    say "attempt 1 SUCCEEDED"
  else
    say "attempt 1 failed"
    say "attempt 2: skopeo into containers-storage, then switch"
    if run skopeo copy "oci:${source_dir}:${TAG}" \
         "containers-storage:localhost/bunny-os-beta:${TAG}"; then
      say "copied into containers-storage"
      if run bootc switch --transport containers-storage "localhost/bunny-os-beta:${TAG}"; then
        say "attempt 2 SUCCEEDED"
      else
        say "attempt 2 failed"
      fi
    else
      say "skopeo copy failed"
    fi
  fi
fi

say "deployments after:"
run bootc status
run ostree admin status
say "free space after:"
run df -h /sysroot /var
say "done"
RUNNER

cat >"${WORK}/state-report.sh" <<'REPORT'
#!/usr/bin/bash
# Runs on every boot of the staged disk and prints what survived, to the serial
# console, so the rollback harness's own logs carry the answer.
set -uo pipefail
mark() { echo "BUNNY-P5-STATE: $*"; }
mark "boot $(date -Is)"
mark "deployment: $(bootc status 2>/dev/null | grep -iE 'booted|image' | head -3 | tr '\n' ' ')"
for file in \
  /var/home/p5-user-data.txt \
  /var/lib/bunny-os/companion/p5-mode.json \
  /var/lib/bunny-os/trust/p5-grants.json \
  /var/lib/bunny-os/voice/p5-settings.json \
  /var/lib/bunny-os/p5-settings.txt
do
  if [[ -f "${file}" ]]; then
    mark "PRESENT ${file} :: $(head -c 120 "${file}" | tr -d '\n')"
  else
    mark "MISSING ${file}"
  fi
done
if [[ -f /etc/bunny-p5-etc-marker.txt ]]; then
  mark "PRESENT /etc/bunny-p5-etc-marker.txt (per-deployment control)"
else
  mark "MISSING /etc/bunny-p5-etc-marker.txt (per-deployment control)"
fi
mark "end"
REPORT

cat >"${WORK}/bunny-p5-state.service" <<'STATEUNIT'
[Unit]
Description=Phase 5 state report
After=local-fs.target
ConditionPathExists=/etc/bunny-p5-stage/state-report.sh

[Service]
Type=oneshot
ExecStart=/usr/bin/bash /etc/bunny-p5-stage/state-report.sh
StandardOutput=journal+console
StandardError=journal+console
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
STATEUNIT

cat >"${WORK}/bunny-p5-stage.service" <<'UNIT'
[Unit]
Description=Phase 5 update staging
After=multi-user.target
ConditionPathExists=/etc/bunny-p5-stage/stage.sh

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c '/usr/bin/bash /etc/bunny-p5-stage/stage.sh; echo "BUNNY-P5-STAGE: wrapper exit=$?"; sync; sleep 2; systemctl poweroff'
TimeoutStartSec=40min
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
UNIT

echo
echo "== injecting =="
guestfish -a "${STAGED}" \
  run \
  : mount "${ROOT_PARTITION}" / \
  : mkdir-p "${deployment}/etc/bunny-p5-stage" \
  : upload "${WORK}/stage.sh" "${deployment}/etc/bunny-p5-stage/stage.sh" \
  : chmod 0644 "${deployment}/etc/bunny-p5-stage/stage.sh" \
  : upload "${WORK}/state-report.sh" "${deployment}/etc/bunny-p5-stage/state-report.sh" \
  : chmod 0644 "${deployment}/etc/bunny-p5-stage/state-report.sh" \
  : upload /home/bunny/p5-ops/state-fragment.sh "${deployment}/etc/bunny-p5-stage/state-fragment.sh" \
  : chmod 0644 "${deployment}/etc/bunny-p5-stage/state-fragment.sh" \
  : upload "${WORK}/bunny-p5-state.service" "${deployment}/etc/systemd/system/bunny-p5-state.service" \
  : chmod 0644 "${deployment}/etc/systemd/system/bunny-p5-state.service" \
  : upload "${WORK}/bunny-p5-stage.service" "${deployment}/etc/systemd/system/bunny-p5-stage.service" \
  : chmod 0644 "${deployment}/etc/systemd/system/bunny-p5-stage.service" \
  : mkdir-p "${deployment}/etc/systemd/system/multi-user.target.wants" \
  : ln-sf /etc/systemd/system/bunny-p5-stage.service \
      "${deployment}/etc/systemd/system/multi-user.target.wants/bunny-p5-stage.service" \
  : ln-sf /etc/systemd/system/bunny-p5-state.service \
      "${deployment}/etc/systemd/system/multi-user.target.wants/bunny-p5-state.service"

echo "== labelling =="
guestfish -a "${STAGED}" \
  run \
  : mount "${ROOT_PARTITION}" / \
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 \
      "${deployment}/etc/bunny-p5-stage" \
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 \
      "${deployment}/etc/bunny-p5-stage/stage.sh" \
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 \
      "${deployment}/etc/bunny-p5-stage/state-report.sh" \
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 \
      "${deployment}/etc/bunny-p5-stage/state-fragment.sh" \
  : lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0 \
      "${deployment}/etc/systemd/system/bunny-p5-state.service" \
  : lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0 \
      "${deployment}/etc/systemd/system/bunny-p5-stage.service"

echo
echo "== booting N with the candidate attached =="
log="${EVIDENCE}/stage-boot.log"
: >"${log}"
firmware=/usr/share/edk2/ovmf/OVMF_CODE.fd
[[ -f "${firmware}" ]] || firmware=$(find /usr/share -name 'OVMF_CODE*.fd' 2>/dev/null | head -1)
echo "  firmware: ${firmware}"

timeout "${BUNNY_STAGE_TIMEOUT:-2700}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max -smp 4 -m 6144 \
  -bios "${firmware}" \
  -drive "file=${STAGED},format=qcow2,if=virtio" \
  -drive "file=${UPDATE_IMG},format=raw,if=virtio" \
  -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
  -display none -serial "file:${log}" -no-reboot
status=$?
echo "  qemu exit=${status}"

echo
echo "== what the guest said =="
grep -a "BUNNY-P5-STAGE" "${log}" | sed 's/^/  /' || echo "  no marker in the serial log"

echo
echo "== deployment entries on the staged disk =="
guestfish --ro -a "${STAGED}" run : mount "${ROOT_PARTITION}" / \
  : glob-expand "/ostree/deploy/*/deploy/*/" 2>/dev/null | sed 's/^/  /'
entries=$(guestfish --ro -a "${STAGED}" run : mount "${ROOT_PARTITION}" / \
  : glob-expand "/ostree/deploy/*/deploy/*/" 2>/dev/null | grep -c . || true)
echo "  entries: ${entries}"

echo "STAGE-UPDATE-DONE entries=${entries} qemu=${status}"

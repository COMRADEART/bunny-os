#!/usr/bin/bash
# The two harness modes that have never had an input, run against the disk
# `stage-update.sh` produced.
#
#   vm-upgrade-test.sh   BUNNY_UPGRADE_MODE=staged
#   vm-rollback-test.sh  BUNNY_ROLLBACK_MODE=deployment-rollback
#
# Both refuse a disk with fewer than two deployment entries -- exit 5, with the
# reason named, rather than a vacuous pass. The staged disk has two.
set -uo pipefail
TREE=/root/bunny-os
STAGED=/home/bunny/p5-work/stage/staged.qcow2
EVIDENCE=/home/bunny/p5-evidence/update
mkdir -p "${EVIDENCE}"

[[ -f "${STAGED}" ]] || { echo "no staged disk at ${STAGED}" >&2; exit 3; }

echo "== the staged disk =="
sha256sum "${STAGED}" | tee "${EVIDENCE}/staged-disk.sha256"
guestfish --ro -a "${STAGED}" run : mount /dev/sda4 / \
  : glob-expand "/ostree/deploy/*/deploy/*/" 2>/dev/null | sed 's/^/  /'

cd "${TREE}" || exit 1

echo
echo "=============================================================="
echo "== vm-upgrade-test.sh, staged mode                          =="
echo "=============================================================="
BUNNY_UPGRADE_MODE=staged \
BUNNY_STAGED_UPDATE_DISK="${STAGED}" \
BUNNY_EVIDENCE_DIR="${EVIDENCE}" \
BUNNY_VM_TIMEOUT="${BUNNY_VM_TIMEOUT:-420}" \
  bash build/scripts/vm-upgrade-test.sh
upgrade=$?
echo "vm-upgrade-test exit=${upgrade}"

echo
echo "=============================================================="
echo "== vm-rollback-test.sh, deployment-rollback mode            =="
echo "=============================================================="
rm -f /home/bunny/p5-work/stage/rollback-test.qcow2
BUNNY_ROLLBACK_MODE=deployment-rollback \
BUNNY_STABLE_CANDIDATE_DISK="${STAGED}" \
BUNNY_ROLLBACK_TEST_DISK=/home/bunny/p5-work/stage/rollback-test.qcow2 \
BUNNY_EVIDENCE_DIR="${EVIDENCE}" \
BUNNY_VM_TIMEOUT="${BUNNY_VM_TIMEOUT:-420}" \
  bash build/scripts/vm-rollback-test.sh
rollback=$?
echo "vm-rollback-test exit=${rollback}"

echo
echo "STAGED-TESTS-DONE upgrade=${upgrade} rollback=${rollback}"

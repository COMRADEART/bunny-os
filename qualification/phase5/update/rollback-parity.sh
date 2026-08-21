#!/usr/bin/bash
# §20 boot parity: N and N+1 both reach a healthy boot target.
#
# This is the mode the harness has always had and never been able to run,
# because the project had exactly one build. It now has two:
#
#   N    the frozen Phase 4 Alpha release candidate, e906a48793d7, moved intact
#        to /root/bunny-build-archive/ when its output directory was cleared
#   N+1  the Phase 5 build, e501218f2fe0.1787016937
#
# The harness is explicit that this is *prerequisite* evidence and not a live
# deployment switch, and it writes that into its own JSON. Nothing here upgrades
# that claim: rolling back to an image that does not boot is not a rollback, so
# this is the thing that has to be true first, and it is now measured rather
# than assumed.
set -uo pipefail
TREE=/root/bunny-os
ARCHIVE=$(find /root/bunny-build-archive -maxdepth 1 -type d -name 'beta-phase4-rc-e906a48793d7-*' | sort | tail -1)
EVIDENCE=/home/bunny/p5-evidence/rollback
mkdir -p "${EVIDENCE}"

previous=$(find "${ARCHIVE}/bootc-fedora-44-qcow2-x86_64" -name '*.qcow2' 2>/dev/null | head -1)
candidate=$(find "${TREE}/build/out/beta/bootc-fedora-44-qcow2-x86_64" -name '*.qcow2' 2>/dev/null | head -1)

echo "previous  (N):   ${previous:-NOT FOUND}"
echo "candidate (N+1): ${candidate:-NOT FOUND}"
[[ -f "${previous}" && -f "${candidate}" ]] || { echo "both disks are required" >&2; exit 3; }

sha256sum "${previous}" "${candidate}" | tee "${EVIDENCE}/disks.sha256"

cd "${TREE}" || exit 1
export BUNNY_ROLLBACK_MODE=boot-parity
export BUNNY_PREVIOUS_BETA_DISK="${previous}"
export BUNNY_STABLE_CANDIDATE_DISK="${candidate}"
export BUNNY_EVIDENCE_DIR="${EVIDENCE}"
export BUNNY_VM_TIMEOUT="${BUNNY_VM_TIMEOUT:-420}"

bash build/scripts/vm-rollback-test.sh
status=$?
echo "vm-rollback-test exit=${status}"
echo "ROLLBACK-PARITY-DONE status=${status}"
exit "${status}"

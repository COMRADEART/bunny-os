#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rollback qualification harness.
#
# Two modes, because they prove different things and conflating them would
# overstate the evidence.
#
#   boot-parity          Both the previous release and the candidate boot to a
#                        healthy target. This is the prerequisite for rollback:
#                        rolling back to an image that does not boot is not a
#                        rollback. It does NOT prove a live deployment switch.
#
#   deployment-rollback  A disk that already carries two or more bootc
#                        deployments is booted on its non-default entry, and
#                        that entry must reach a healthy target. This is the
#                        real rollback evidence.
#
# A freshly built image carries exactly one deployment entry, so
# deployment-rollback needs a disk on which an update has already been staged.
# The harness says so and exits 5 rather than passing vacuously.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=build/scripts/vm-lib.sh
source "${script_dir}/vm-lib.sh"

mode="${BUNNY_ROLLBACK_MODE:-boot-parity}"
previous="${BUNNY_PREVIOUS_BETA_DISK:-}"
candidate="${BUNNY_STABLE_CANDIDATE_DISK:-}"
test_disk="${BUNNY_ROLLBACK_TEST_DISK:-}"
timeout_seconds="${BUNNY_VM_TIMEOUT:-300}"
evidence="${BUNNY_EVIDENCE_DIR:-build/out/vm-evidence}"

bunny_require_commands qemu-system-x86_64 qemu-img timeout

case "${mode}" in
    boot-parity|deployment-rollback) ;;
    *) echo "unsupported BUNNY_ROLLBACK_MODE: ${mode}" >&2; exit 2 ;;
esac

mkdir -p "${evidence}"

if [[ "${mode}" == "boot-parity" ]]; then
    [[ -f "${previous}" ]] || { echo "BUNNY_PREVIOUS_BETA_DISK must name an existing QCOW2" >&2; exit 3; }
    [[ -f "${candidate}" ]] || { echo "BUNNY_STABLE_CANDIDATE_DISK must name an existing QCOW2" >&2; exit 3; }

    echo "== previous release boots =="
    bunny_boot "${previous}" "${evidence}/rollback-previous.log" "${timeout_seconds}"
    bunny_boot_health "${evidence}/rollback-previous.log"

    echo "== candidate boots =="
    bunny_boot "${candidate}" "${evidence}/rollback-candidate.log" "${timeout_seconds}"
    bunny_boot_health "${evidence}/rollback-candidate.log"

    candidate_entries="$(bunny_count_deployments "${candidate}")"
    echo "== candidate deployment entries: ${candidate_entries} =="
    bunny_list_deployments "${candidate}" | sed 's/^/  /'

    cat >"${evidence}/rollback-boot-parity.json" <<EOF
{
  "mode": "boot-parity",
  "previousBoots": true,
  "candidateBoots": true,
  "candidateDeploymentEntries": ${candidate_entries:-0},
  "liveDeploymentSwitchTested": false,
  "note": "Both images reach a healthy boot target, which is the prerequisite for rollback. A live bootc deployment switch was not exercised; use BUNNY_ROLLBACK_MODE=deployment-rollback against a disk with a staged update for that."
}
EOF
    echo
    echo "Rollback boot parity PASSED. Both images boot healthy."
    echo "This is prerequisite evidence, not a live deployment switch."
    exit 0
fi

# deployment-rollback
[[ -f "${candidate}" ]] || { echo "BUNNY_STABLE_CANDIDATE_DISK must name an existing QCOW2 with a staged update" >&2; exit 3; }
[[ -n "${test_disk}" && "${test_disk}" == *.qcow2 && ! -e "${test_disk}" ]] || {
    echo "BUNNY_ROLLBACK_TEST_DISK must name a new disposable QCOW2 path" >&2
    exit 3
}
bunny_require_commands virt-ls guestfish

entries="$(bunny_count_deployments "${candidate}")"
if [[ "${entries:-0}" -lt 2 ]]; then
    echo "the candidate disk carries ${entries:-0} deployment entry; a rollback target requires at least two." >&2
    echo "Stage an update on the disk first: a freshly built image has one deployment and cannot demonstrate rollback." >&2
    exit 5
fi

mkdir -p "$(dirname "${test_disk}")"
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${candidate}")" "${test_disk}" >/dev/null

echo "== default deployment boots =="
bunny_boot "${test_disk}" "${evidence}/rollback-default.log" "${timeout_seconds}"
bunny_boot_health "${evidence}/rollback-default.log"

echo "== selecting the previous deployment =="
# BLS entries sort newest-first, so index 1 is the rollback target.
guestfish --rw -a "${test_disk}" -m "${BUNNY_BOOT_PARTITION:-/dev/sda3}" \
    write /grub2/grubenv "# GRUB Environment Block
saved_entry=1
" >/dev/null

echo "== previous deployment boots =="
bunny_boot "${test_disk}" "${evidence}/rollback-previous-deployment.log" "${timeout_seconds}"
bunny_boot_health "${evidence}/rollback-previous-deployment.log"

cat >"${evidence}/rollback-deployment.json" <<EOF
{
  "mode": "deployment-rollback",
  "deploymentEntries": ${entries},
  "defaultDeploymentBoots": true,
  "previousDeploymentBoots": true,
  "liveDeploymentSwitchTested": true
}
EOF

echo
echo "Rollback PASSED: the previous deployment was selected and reached a healthy target."

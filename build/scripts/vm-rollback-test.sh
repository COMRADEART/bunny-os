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
#
# deployment-rollback used to pass vacuously in a different way. It wrote
# saved_entry into the GRUB environment, booted, and checked only that a healthy
# target was reached -- so three consecutive runs reported
# "the previous deployment was selected" while the machine booted its default
# every time. Both halves are repaired: the environment block is written in the
# format GRUB requires, and the deployment that booted is identified from the
# kernel command line rather than inferred from the machine surviving. On the
# Alpha images the selection still does not take, so the mode now exits 5 and
# names the route that does work.

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

mapfile -t checksums < <(bunny_deployment_checksums "${test_disk}")
if [[ ${#checksums[@]} -lt 2 ]]; then
    echo "could not read two deployment identifiers from the BLS entries" >&2
    exit 5
fi
echo "== deployment identifiers =="
printf '  %s\n' "${checksums[@]}"

echo "== default deployment boots =="
bunny_boot "${test_disk}" "${evidence}/rollback-default.log" "${timeout_seconds}"
bunny_boot_health "${evidence}/rollback-default.log"

default_deployment="$(bunny_booted_checksum "${evidence}/rollback-default.log")"
if [[ -z "${default_deployment}" ]]; then
    echo "the default boot printed no ostree= argument; this harness cannot identify deployments on this image" >&2
    exit 5
fi
echo "  default deployment: ${default_deployment}"

previous_deployment=""
for candidate in "${checksums[@]}"; do
    [[ "${candidate}" == "${default_deployment}" ]] && continue
    previous_deployment="${candidate}"
    break
done
if [[ -z "${previous_deployment}" ]]; then
    echo "every BLS entry names the deployment that just booted; there is no rollback target to select" >&2
    exit 5
fi
echo "  rollback target:    ${previous_deployment}"

echo "== selecting the previous deployment =="
# A GRUB environment block is a fixed 1024-byte record: a header line, the
# variables, then '#' padding to exactly 1024 bytes. The first version of this
# wrote a 40-byte file, GRUB ignored it, the machine booted its default every
# time, and the harness passed anyway because reaching a healthy target was its
# only check. Both halves are fixed: the block is written correctly, and the
# boot afterwards must prove which deployment it used.
grubenv="$(mktemp)"
{
    printf '# GRUB Environment Block\n'
    printf 'saved_entry=1\n'
} >"${grubenv}"
python3 - "${grubenv}" <<'PYTHON'
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = path.read_bytes()
if len(data) > 1024:
    raise SystemExit("grub environment block would exceed 1024 bytes")
path.write_bytes(data + b"#" * (1024 - len(data)))
PYTHON
guestfish --rw -a "${test_disk}" -m "${BUNNY_BOOT_PARTITION:-/dev/sda3}" \
    upload "${grubenv}" /grub2/grubenv >/dev/null
rm -f "${grubenv}"

echo "== previous deployment boots =="
bunny_boot "${test_disk}" "${evidence}/rollback-previous-deployment.log" "${timeout_seconds}"
bunny_boot_health "${evidence}/rollback-previous-deployment.log"

if ! bunny_require_booted_deployment "${evidence}/rollback-previous-deployment.log" \
        "${previous_deployment}"; then
    cat >"${evidence}/rollback-deployment.json" <<EOF
{
  "mode": "deployment-rollback",
  "deploymentEntries": ${entries},
  "defaultDeployment": "${default_deployment}",
  "rollbackTarget": "${previous_deployment}",
  "defaultDeploymentBoots": true,
  "previousDeploymentBoots": false,
  "liveDeploymentSwitchTested": false,
  "outcome": "NOT_RUN",
  "note": "The machine reached a healthy boot target and it was not the rollback target: this harness could not select the previous deployment. Reported as an absent capability rather than a product failure, because the product's own rollback path is separately demonstrated - see qualification/phase5/update/rollback-real.sh, where 'bootc rollback' followed by a reboot does bring up the previous deployment."
}
EOF
    echo >&2
    echo "This harness cannot select a deployment on this image." >&2
    echo "Writing saved_entry into /grub2/grubenv does not change what boots here, with a" >&2
    echo "correctly padded 1024-byte environment block or without one, and the machine came" >&2
    echo "up on its default deployment. That is a gap in this harness, not a failure of the" >&2
    echo "product: 'bootc rollback' followed by a reboot does roll back, which" >&2
    echo "qualification/phase5/update/rollback-real.sh measures on this same disk." >&2
    echo >&2
    echo "NOT_RUN: no deployment switch was exercised." >&2
    exit 5
fi

cat >"${evidence}/rollback-deployment.json" <<EOF
{
  "mode": "deployment-rollback",
  "deploymentEntries": ${entries},
  "defaultDeployment": "${default_deployment}",
  "rollbackTarget": "${previous_deployment}",
  "defaultDeploymentBoots": true,
  "previousDeploymentBoots": true,
  "liveDeploymentSwitchTested": true,
  "note": "The deployment that booted was identified from the kernel command line, not inferred from the machine surviving."
}
EOF

echo
echo "Rollback PASSED: the previous deployment was selected and reached a healthy target."

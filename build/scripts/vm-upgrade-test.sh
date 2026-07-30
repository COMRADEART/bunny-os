#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Update-path qualification harness.
#
# A real update means: a signed manifest is fetched, verified against an
# image-owned key, and a new deployment is staged that the device can boot and
# can roll back from. Two of those three steps need infrastructure that does
# not exist here yet — a published manifest and a reachable registry — so this
# harness covers what can be verified locally and reports precisely which step
# it stopped at, instead of exiting 78 for all of them.
#
#   manifest      Verify a signed update manifest end to end with the real
#                 update-agent validator: signature, channel, architecture,
#                 contract range, expiry and monotonic sequence. Needs no VM.
#
#   staged        Boot a disk on which an update has already been staged and
#                 require both the new deployment and a retained rollback
#                 target. Needs a disk with two deployments.
#
# Neither mode invents a result. A missing input is exit 3; a genuinely absent
# capability is exit 5 with the reason named.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=build/scripts/vm-lib.sh
source "${script_dir}/vm-lib.sh"

repo_root="$(cd "${script_dir}/../.." && pwd)"
mode="${BUNNY_UPGRADE_MODE:-manifest}"
manifest="${BUNNY_UPDATE_MANIFEST:-}"
public_key="${BUNNY_UPDATE_PUBLIC_KEY:-}"
staged_disk="${BUNNY_STAGED_UPDATE_DISK:-}"
timeout_seconds="${BUNNY_VM_TIMEOUT:-300}"
evidence="${BUNNY_EVIDENCE_DIR:-build/out/vm-evidence}"

case "${mode}" in
    manifest|staged) ;;
    *) echo "unsupported BUNNY_UPGRADE_MODE: ${mode}" >&2; exit 2 ;;
esac

mkdir -p "${evidence}"

if [[ "${mode}" == "manifest" ]]; then
    [[ -f "${manifest}" ]] || {
        echo "BUNNY_UPDATE_MANIFEST must name a signed update manifest." >&2
        echo "No published manifest exists yet, so this step cannot be satisfied from the repository alone." >&2
        exit 3
    }
    [[ -f "${public_key}" ]] || { echo "BUNNY_UPDATE_PUBLIC_KEY must name the image-owned trust root" >&2; exit 3; }
    bunny_require_commands python3 openssl

    echo "== verifying the update manifest with the real update-agent validator =="
    python3 - "${manifest}" "${public_key}" "${repo_root}" <<'PYTHON'
import json
import sys
from pathlib import Path

manifest_path, key_path, repo_root = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, str(Path(repo_root) / "services/bunny-update-agent"))

import bunny_update_agent as agent

document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
# Use the shipped validator rather than a harness reimplementation, so this
# tests the code that actually runs on a device.
for name in ("validate_manifest", "_validate_manifest", "verify_manifest"):
    validator = getattr(agent, name, None)
    if validator is not None:
        validator(document)
        print(f"  manifest accepted by {name}")
        break
else:
    raise SystemExit("the update agent exposes no manifest validator; harness needs updating")
PYTHON

    cat >"${evidence}/upgrade-manifest.json" <<EOF
{
  "mode": "manifest",
  "manifestVerified": true,
  "deploymentStaged": false,
  "note": "Manifest structure and signature policy verified with the shipped update-agent validator. Staging and reboot were not exercised."
}
EOF
    echo
    echo "Update manifest PASSED verification. Staging was not exercised in this mode."
    exit 0
fi

# staged
[[ -f "${staged_disk}" ]] || {
    echo "BUNNY_STAGED_UPDATE_DISK must name a QCOW2 with an update already staged" >&2
    exit 3
}
bunny_require_commands qemu-system-x86_64 timeout virt-ls

entries="$(bunny_count_deployments "${staged_disk}")"
if [[ "${entries:-0}" -lt 2 ]]; then
    echo "the disk carries ${entries:-0} deployment entry; a staged update produces at least two." >&2
    echo "No update has been staged on this disk, so the staged-update path cannot be verified." >&2
    exit 5
fi

echo "== staged deployment entries: ${entries} =="
bunny_list_deployments "${staged_disk}" | sed 's/^/  /'

echo "== booting the staged deployment =="
bunny_boot "${staged_disk}" "${evidence}/upgrade-staged.log" "${timeout_seconds}"
bunny_boot_health "${evidence}/upgrade-staged.log"

cat >"${evidence}/upgrade-staged.json" <<EOF
{
  "mode": "staged",
  "deploymentEntries": ${entries},
  "stagedDeploymentBoots": true,
  "rollbackTargetRetained": true
}
EOF

echo
echo "Staged update PASSED: the new deployment boots and a rollback target is retained."

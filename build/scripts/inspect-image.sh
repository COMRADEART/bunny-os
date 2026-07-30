#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

profile="${1:-developer}"
output="build/out/${profile}"
disk="$(find "${output}" -type f -name '*.qcow2' -print -quit)"
if [[ -z "${disk}" ]]; then
  echo "no QCOW2 artifact found under ${output}" >&2
  exit 2
fi
for command in qemu-img virt-filesystems virt-ls virt-cat; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing ${command}" >&2; exit 3; }
done

qemu-img info --output=json "${disk}" > "${output}/qemu-img-info.json"
mapfile -t root_filesystems < <(
  virt-filesystems -a "${disk}" --filesystems --long |
    awk 'NR > 1 && $2 == "filesystem" && $4 == "root" { print $1 }'
)
if [[ ${#root_filesystems[@]} -ne 1 ]]; then
  echo "expected exactly one filesystem labelled root; found ${#root_filesystems[@]}" >&2
  exit 4
fi
root_mount="${root_filesystems[0]}:/"

mapfile -t state_roots < <(
  virt-ls -a "${disk}" -m "${root_mount}" /ostree/deploy |
    grep -E '^[A-Za-z0-9._-]+$'
)
if [[ ${#state_roots[@]} -ne 1 ]]; then
  echo "expected exactly one bootc state root; found ${#state_roots[@]}" >&2
  exit 4
fi

mapfile -t deployments < <(
  virt-ls -a "${disk}" -m "${root_mount}" "/ostree/deploy/${state_roots[0]}/deploy" |
    grep -E '^[a-f0-9]{64}\.[0-9]+$'
)
if [[ ${#deployments[@]} -ne 1 ]]; then
  echo "expected exactly one immutable bootc deployment; found ${#deployments[@]}" >&2
  exit 4
fi
deployment_root="/ostree/deploy/${state_roots[0]}/deploy/${deployments[0]}"

virt-ls -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/lib/bunny-os" > "${output}/image-files.txt"
virt-cat -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/lib/bunny-os/release.json" > "${output}/release.json"
virt-cat -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/share/bunny-os/bunny-artifact.json" > "${output}/bunny-artifact.json"
grep -q 'release.json' "${output}/image-files.txt"
grep -q '"contractVersion": "1.0.0"' "${output}/release.json"
grep -q '"status": "placeholder"\|"status": "verified"' "${output}/bunny-artifact.json"
if [[ "${profile}" == "shell" || "${profile}" == "shell-test" || "${profile}" == "developer" ]]; then
  virt-ls -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/share/wayland-sessions" > "${output}/wayland-sessions.txt"
  virt-ls -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org" > "${output}/bunny-shell-extension.txt"
  virt-ls -a "${disk}" -m "${root_mount}" "${deployment_root}/usr/bin" > "${output}/usr-bin.txt"
  grep -q '^bunny\.desktop$' "${output}/wayland-sessions.txt"
  grep -q '^bunny-safe\.desktop$' "${output}/wayland-sessions.txt"
  grep -q '^extension\.js$' "${output}/bunny-shell-extension.txt"
  grep -q '^bunny-launcher$' "${output}/usr-bin.txt"
  grep -q '^bunny-terminal$' "${output}/usr-bin.txt"
fi
echo "Image inspection passed: ${disk}"

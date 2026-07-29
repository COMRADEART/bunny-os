#!/usr/bin/bash
set -euo pipefail

profile="${1:-developer}"
output="build/out/${profile}"
disk="$(find "${output}" -type f -name '*.qcow2' -print -quit)"
if [[ -z "${disk}" ]]; then
  echo "no QCOW2 artifact found under ${output}" >&2
  exit 2
fi
for command in qemu-img virt-ls virt-cat; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing ${command}" >&2; exit 3; }
done

qemu-img info --output=json "${disk}" > "${output}/qemu-img-info.json"
virt-ls -a "${disk}" -i /usr/lib/bunny-os > "${output}/image-files.txt"
virt-cat -a "${disk}" -i /usr/lib/bunny-os/release.json > "${output}/release.json"
virt-cat -a "${disk}" -i /usr/share/bunny-os/bunny-artifact.json > "${output}/bunny-artifact.json"
grep -q 'release.json' "${output}/image-files.txt"
grep -q '"contractVersion": "1.0.0"' "${output}/release.json"
grep -q '"status": "placeholder"\|"status": "verified"' "${output}/bunny-artifact.json"
if [[ "${profile}" == "shell" || "${profile}" == "shell-test" || "${profile}" == "developer" ]]; then
  virt-ls -a "${disk}" -i /usr/share/wayland-sessions > "${output}/wayland-sessions.txt"
  virt-ls -a "${disk}" -i /usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org > "${output}/bunny-shell-extension.txt"
  virt-ls -a "${disk}" -i /usr/bin > "${output}/usr-bin.txt"
  grep -q '^bunny\.desktop$' "${output}/wayland-sessions.txt"
  grep -q '^bunny-safe\.desktop$' "${output}/wayland-sessions.txt"
  grep -q '^extension\.js$' "${output}/bunny-shell-extension.txt"
  grep -q '^bunny-launcher$' "${output}/usr-bin.txt"
  grep -q '^bunny-terminal$' "${output}/usr-bin.txt"
fi
echo "Image inspection passed: ${disk}"

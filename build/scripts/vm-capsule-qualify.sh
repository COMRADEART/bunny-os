#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run the capsule runtime qualification inside a booted Bunny OS guest.
#
# The Fedora host qualification measured namespaces and cgroups with SELinux
# Disabled. The guest has it Enforcing, which is the whole reason this exists:
# the same harness, the same probe, the same mandatory negative control, on a
# system where every layer of the design is actually running.
#
# The guest powers itself off when the run finishes, so the disk is consistent
# when the evidence is read back out of it with guestfish. A timeout kills the
# machine if it does not, and the difference between "finished" and "was killed"
# is visible afterwards in whether the evidence directory has a summary in it.
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

profile="${BUNNY_CAPSULE_PROFILE:-shell}"
label="${1:-guest-qualification}"
seconds="${BUNNY_CAPSULE_TIMEOUT:-1500}"
user="${BUNNY_CAPSULE_USER:-bunny}"
commit="$(git rev-parse HEAD)"

bunny_require_commands qemu-system-x86_64 guestfish openssl git python3 || exit 3

source_image="${BUNNY_CAPSULE_IMAGE:-}"
if [[ -z "${source_image}" ]]; then
  source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' \
    -not -path '*/desktop-story/*' -not -path '*/capsule-qualify/*' -print -quit 2>/dev/null)"
fi
if [[ -z "${source_image}" ]]; then
  echo "no qcow2 under build/out/${profile}; build the image first" >&2
  exit 2
fi

work="build/out/${profile}/capsule-qualify/${label}"
rm -rf "${work}"
mkdir -p "${work}"
disk="${work}/disk.qcow2"
log="${work}/serial.log"

echo "source image: ${source_image}"
echo "commit:       ${commit}"
echo "work:         ${work}"

cp --reflink=auto "${source_image}" "${disk}"

echo "--- injecting ---"
if ! bash build/scripts/capsule-qualify-inject.sh "${disk}" "${user}" "${commit}" \
      >"${work}/inject.log" 2>&1; then
  echo "injection failed; see ${work}/inject.log" >&2
  tail -30 "${work}/inject.log" >&2
  exit 4
fi
cat "${work}/inject.log"

firmware="$(bunny_firmware)" || exit 3
: >"${log}"

echo "--- booting (${seconds}s budget) ---"
# No snapshot=on: the guest's writes must survive, because the evidence is read
# back out of this disk afterwards.
timeout "${seconds}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max \
  -smp 4 \
  -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio" \
  -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
  -device virtio-vga \
  -display none \
  -serial "file:${log}" \
  -no-reboot
boot_status=$?
echo "qemu exit: ${boot_status}"

echo
echo "--- console summary ---"
python3 - "${log}" <<'PYEOF'
import re, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes().decode("utf-8", "replace")
plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
begin, end = "BUNNY-CAPSULE-QUALIFY-BEGIN", "BUNNY-CAPSULE-QUALIFY-END"
if begin in plain and end in plain:
    print(plain.split(begin, 1)[1].split(end, 1)[0].strip()[:4000])
else:
    print("no summary marker on the console; the run did not reach the end")
    for line in plain.splitlines():
        if re.search(r"bunny-capsule-qualify|Traceback|error|Failed", line, re.I):
            print("  " + line.strip()[:160])
PYEOF

echo
echo "--- extracting evidence ---"
deployment="$(guestfish --ro -a "${disk}" run : mount /dev/sda4 / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null | head -1)"
deployment="${deployment%/}"
stateroot="$(dirname "$(dirname "${deployment}")")"
mkdir -p "${work}/evidence"
if guestfish --ro -a "${disk}" run : mount /dev/sda4 / \
     : is-dir "${stateroot}/var/log/bunny-capsule-qualify" 2>/dev/null | grep -q true; then
  guestfish --ro -a "${disk}" run : mount /dev/sda4 / \
    : copy-out "${stateroot}/var/log/bunny-capsule-qualify" "${work}/evidence" 2>/dev/null
  find "${work}/evidence" -type f | head -30
else
  echo "no ${stateroot}/var/log/bunny-capsule-qualify in the guest" >&2
fi
echo
echo "work: ${work}"

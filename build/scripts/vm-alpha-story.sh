#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot the Public Alpha image and ask it about itself.
#
# The existing VM harnesses read the serial console for a marker and conclude
# that the system booted. That is the right check for what they check, and it
# cannot answer any of the Alpha questions: whether the companion started in a
# *user session*, which files the running code was imported from, what the
# provider survey found, whether anything went out to the network. Those need a
# program running inside the guest.
#
# So this injects one. `build/scripts/alpha-probe.py` is copied into a *copy* of
# the disk together with a oneshot unit that runs it after the graphical target,
# and its JSON comes back out on the serial console between two markers. The
# probe is injected rather than installed, because a measuring instrument that
# shipped in the artifact would be part of what it measures.
#
# Two things this harness configures that the image does not, and both are
# recorded in the output so the evidence never overstates what was booted:
#
#   * a desktop user, because a directly-booted payload image has none — on a
#     real installation the installer creates it, and the installation path is
#     exercised separately by vm-install-smoke.sh;
#   * GDM autologin for that user, because §11 is a claim about what happens
#     *after login* and a VM with no keyboard cannot log in.
#
# Neither changes the companion. The units under test are enabled by the image's
# own preset, and the harness never touches them.
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

profile="${BUNNY_ALPHA_PROFILE:-beta}"
label="${1:-alpha-story}"
seconds="${BUNNY_ALPHA_TIMEOUT:-600}"
offline="${BUNNY_ALPHA_OFFLINE:-0}"
user="${BUNNY_ALPHA_USER:-bunny}"

bunny_require_commands qemu-system-x86_64 guestfish openssl git python3 || exit 3

# BUNNY_ALPHA_IMAGE names the disk explicitly. It exists so the harness can run
# from a worktree while the image lives in the tree that built it — a build takes
# tens of minutes and resetting the checkout underneath one to pick up a harness
# change is how a build gets corrupted.
#
# -not -path '*/alpha-story/*' matters for the search: this harness copies the
# disk it is about to boot into a work directory under the same tree, so a later
# run would otherwise find a previous run's mutated copy and boot that. The
# evidence would be of a system somebody had already customised.
source_image="${BUNNY_ALPHA_IMAGE:-}"
if [[ -z "${source_image}" ]]; then
  source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' \
    -not -path '*/alpha-story/*' -print -quit 2>/dev/null)"
fi
if [[ -z "${source_image}" ]]; then
  echo "no qcow2 under build/out/${profile}; run make build-alpha-image first" >&2
  exit 2
fi

work="${BUNNY_ALPHA_WORK:-build/out/${profile}/alpha-story/${label}}"
mkdir -p "${work}"
disk="${work}/disk.qcow2"
log="${work}/serial.log"
record="${work}/alpha-record.json"

echo "source image: ${source_image}"
echo "work:         ${work}"
echo "network:      $([[ "${offline}" == "1" ]] && echo 'disconnected (§13)' || echo 'user-mode NAT (§14)')"

# A copy, not a snapshot overlay: the injection writes into the disk, and the
# image the build produced is evidence.
cp --reflink=auto "${source_image}" "${disk}"

echo "--- injecting ---"
if ! bash build/scripts/alpha-inject.sh \
      "${disk}" build/scripts/alpha-probe.py "${user}" "${offline}" \
      >"${work}/inject.log" 2>&1; then
  echo "injection failed; see ${work}/inject.log" >&2
  tail -20 "${work}/inject.log" >&2
  exit 4
fi
cat "${work}/inject.log"

echo "--- booting (${seconds}s budget) ---"
network_args=(-device virtio-net-pci,netdev=net0 -netdev user,id=net0)
if [[ "${offline}" == "1" ]]; then
  network_args=(-nic none)
fi

firmware="$(bunny_firmware)" || exit 3
status=0
timeout "${seconds}" qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max \
  -smp 4 \
  -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio" \
  "${network_args[@]}" \
  -device virtio-vga \
  -display none \
  -serial "file:${log}" \
  -no-reboot || status=$?
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
  echo "QEMU failed with status ${status}; see ${log}" >&2
  exit "${status}"
fi

echo "--- extracting ---"
python3 build/scripts/alpha-record.py \
  --serial "${log}" --output "${record}" \
  --label "${label}" \
  --profile "${profile}" \
  --source-image "${source_image}" \
  --offline "${offline}" \
  --commit "$(git rev-parse HEAD)"
extract=$?
echo "record: ${record}"
exit "${extract}"

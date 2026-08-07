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

bunny_require_commands qemu-system-x86_64 virt-customize git python3 || exit 3

source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' -print -quit 2>/dev/null)"
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

# A copy, not a snapshot overlay: virt-customize writes into the disk, and the
# source image is evidence.
cp --reflink=auto "${source_image}" "${disk}"

cat >"${work}/bunny-alpha-probe.service" <<'UNIT'
[Unit]
Description=Bunny OS Public Alpha probe (injected by the harness, not shipped)
# After the graphical target and after a delay, because the questions are about
# a settled session: a probe that ran the moment graphical.target was reached
# would ask whether the companion had started before it had had a chance to.
After=graphical.target
Wants=graphical.target

[Service]
Type=oneshot
ExecStartPre=/usr/bin/sleep 45
ExecStart=/usr/local/bin/bunny-alpha-probe
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=900

[Install]
WantedBy=graphical.target
UNIT

# A serial console the probe's output can reach, and a kernel that logs to it.
customize_args=(
  --root-password "password:bunny-alpha-vm"
  --run-command "useradd -m -s /bin/bash -G wheel ${user} 2>/dev/null || true"
  --password "${user}:password:bunny-alpha-vm"
  --run-command "loginctl enable-linger ${user} 2>/dev/null || true"
  --mkdir /etc/gdm
  --write "/etc/gdm/custom.conf:[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=${user}\nWaylandEnable=True\n"
  --copy-in "build/scripts/alpha-probe.py:/usr/local/bin"
  --run-command "mv /usr/local/bin/alpha-probe.py /usr/local/bin/bunny-alpha-probe && chmod 0755 /usr/local/bin/bunny-alpha-probe"
  --copy-in "${work}/bunny-alpha-probe.service:/etc/systemd/system"
  --run-command "systemctl enable bunny-alpha-probe.service"
  --run-command "printf 'BUNNY_PROBE_USER=%s\n' '${user}' >>/etc/environment"
)
if [[ "${offline}" == "1" ]]; then
  # §13: disconnect the network *inside* the guest as well as outside it, so the
  # record shows a system that was configured offline rather than one that
  # merely had nowhere to go.
  customize_args+=(--run-command "systemctl disable NetworkManager.service || true")
fi

echo "--- customising ---"
if ! virt-customize -a "${disk}" "${customize_args[@]}" >"${work}/customize.log" 2>&1; then
  echo "virt-customize failed; see ${work}/customize.log" >&2
  tail -20 "${work}/customize.log" >&2
  exit 4
fi

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

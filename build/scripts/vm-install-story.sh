#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install Bunny OS in a VM, unattended, and photograph it happening.
#
# §44 is explicit that a static setup UI does not complete this phase, and this
# is the harness that answers it. `vm-install-smoke.sh` — the only installer VM
# script that existed — boots the ISO with `-serial mon:stdio` and prints
# "Completion must be recorded manually."
#
# ## What is different from vm-desktop-story.sh
#
# That harness boots an installed qcow2 and injects a probe with guestfish. An
# ISO is read-only, so there is nothing to inject into; the driver ships *in* the
# live image instead (`build/scripts/setup-drive.py`, installed to
# /usr/libexec/bunny-setup-drive on the live profile). That is the better
# arrangement: the thing driving the installer is the thing the installer ships.
#
# The guest talks back over the serial console, which the host reads from outside
# without cooperation from the session — the same reason the desktop harness
# reads serial rather than asking the desktop how it is doing.
#
# ## §43, on the host side
#
# The disk this creates is created *here*, by this script, at a path under
# build/out, and it refuses to reuse one that already exists. The guest then
# independently verifies size and model before confirming. Two checks that must
# agree, on either side of the boundary, and neither is "the harness said so".
#
#   BUNNY_INSTALL_ISO      the medium to boot (default: build/out/live/*.iso)
#   BUNNY_JOURNEY          a|b|c|d  (§53). Default a.
#   BUNNY_INSTALL_TIMEOUT  seconds for the whole install (default 3000)
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

journey="${BUNNY_JOURNEY:-a}"
label="${1:-install-${journey}}"
seconds="${BUNNY_INSTALL_TIMEOUT:-3000}"
disk_gib="${BUNNY_INSTALL_DISK_GIB:-80}"
# The screen the guest gets. Declared and *applied* — shellcheck found these
# set and never used, which would have meant a run at whatever resolution
# virtio-vga defaults to while the evidence claimed otherwise. Journey B runs at
# the declared minimum from installer/hardware/preflight.py, because 200 % text
# on the smallest supported screen is the case §39 exists for.
width="${BUNNY_INSTALL_WIDTH:-1280}"
height="${BUNNY_INSTALL_HEIGHT:-1024}"
shots="${BUNNY_INSTALL_SHOTS:-60 150 300 600 900 1200}"

bunny_require_commands qemu-system-x86_64 qemu-img python3 git || exit 3

iso="${BUNNY_INSTALL_ISO:-}"
if [[ -z "${iso}" ]]; then
  iso="$(find build/out/live -maxdepth 2 -type f -name '*.iso' -print -quit 2>/dev/null)"
fi
if [[ ! -f "${iso}" ]]; then
  echo "no installation ISO; set BUNNY_INSTALL_ISO or run make build-live-image" >&2
  exit 2
fi

work="${BUNNY_INSTALL_WORK:-build/out/install/${label}}"
mkdir -p "${work}/screens"
disk="${work}/target.qcow2"
log="${work}/serial.log"
qmp="${work}/qmp.sock"

# §43: a disposable disk, created here, never reused. Refusing to reuse is the
# difference between "a fresh disk" and "whatever was left from last time",
# and the second is how a harness ends up reporting a pass from a previous run.
if [[ -e "${disk}" ]]; then
  echo "refusing to reuse an install target that already exists: ${disk}" >&2
  echo "archive or remove the work directory before another evidence run." >&2
  exit 4
fi
qemu-img create -f qcow2 "${disk}" "${disk_gib}G" >/dev/null || exit 3

echo "iso:     ${iso}"
echo "target:  ${disk} (${disk_gib} GiB, fresh)"
echo "journey: ${journey}"
echo "work:    ${work}"

firmware="$(bunny_firmware)" || exit 3
rm -f "${qmp}"
: >"${log}"

# The journey's parameters reach the in-guest driver through the kernel command
# line, so that one ISO serves all four of §53 without a rebuild.
case "${journey}" in
  a) drive_args="--passphrase=bunny-disk-passphrase" ;;
  b) drive_args="--text-scale=2.0 --high-contrast --reduced-motion --passphrase=bunny-disk-passphrase"
     width="${BUNNY_INSTALL_WIDTH:-1024}"; height="${BUNNY_INSTALL_HEIGHT:-768}" ;;
  c) drive_args="" ;;
  d) drive_args="--expect-refusal" ;;
  *) echo "unknown journey: ${journey} (expected a, b, c or d)" >&2; exit 2 ;;
esac
echo "driver:  ${drive_args:-<no extra arguments>}"

qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max -smp 4 -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio" \
  -cdrom "${iso}" \
  -boot d \
  -device "virtio-vga,xres=${width},yres=${height}" \
  -device virtio-tablet-pci \
  -display none \
  -serial "file:${log}" \
  -qmp "unix:${qmp},server,nowait" \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
  -smbios "type=11,value=bunny.drive=${drive_args}" \
  -no-reboot &
qemu_pid=$!

cleanup() {
  kill "${qemu_pid}" 2>/dev/null
  wait "${qemu_pid}" 2>/dev/null
}
trap cleanup EXIT

# §54: screenshots bound to a run, taken on a schedule rather than guessed at.
# Taken from outside the guest through QMP, so what is captured is what a
# monitor plugged into that machine would show.
(
  elapsed=0
  for at in ${shots}; do
    sleep $(( at - elapsed ))
    elapsed="${at}"
    # Both helpers take the arguments they take, not the ones that seemed
    # natural. `qmp-screendump.py` is --socket/--output, and `ppm-to-png.py`
    # takes files or directories and writes each alongside its source with a
    # .png suffix — it has no output argument at all. The first version of this
    # passed positionals to one and an output path to the other, which would
    # have produced an install run with no screenshots and no error.
    python3 build/scripts/qmp-screendump.py --socket "${qmp}" \
      --output "${work}/screens/t${at}.ppm" >/dev/null 2>&1 || true
    if [[ -s "${work}/screens/t${at}.ppm" ]]; then
      python3 build/scripts/ppm-to-png.py "${work}/screens/t${at}.ppm" \
        >/dev/null 2>&1 || true
      rm -f "${work}/screens/t${at}.ppm"
    fi
  done
) &
shots_pid=$!

# Wait for the driver to report a terminal outcome on the serial console, or
# for the timeout. Both failure and success are matched: a watcher that only
# looked for success would sit silently through a crash until the timeout.
outcome="timeout"
deadline=$(( SECONDS + seconds ))
while (( SECONDS < deadline )); do
  if grep -aq '"event": "done"' "${log}" 2>/dev/null; then
    outcome="done"
    break
  fi
  if grep -aq '"event": "error"' "${log}" 2>/dev/null; then
    outcome="error"
    break
  fi
  if ! kill -0 "${qemu_pid}" 2>/dev/null; then
    outcome="qemu-exited"
    break
  fi
  sleep 10
done
kill "${shots_pid}" 2>/dev/null

echo "--- driver events ---"
grep -a 'BUNNY-INSTALL' "${log}" | tail -40

python3 - "${log}" "${work}/result.json" "${journey}" "${outcome}" <<'PYTHON'
import json, sys, re
log, out, journey, outcome = sys.argv[1:5]
events = []
for line in open(log, encoding="utf-8", errors="replace"):
    if "BUNNY-INSTALL " in line:
        try:
            events.append(json.loads(line.split("BUNNY-INSTALL ", 1)[1]))
        except Exception:
            continue
done = [e for e in events if e.get("event") == "done"]
json.dump({
    "schemaVersion": 1,
    "journey": journey,
    "harnessOutcome": outcome,
    "driverOutcome": done[0].get("outcome") if done else None,
    "stages": [e.get("name") for e in events if e.get("event") == "stage"],
    "targetVerified": any(e.get("event") == "target-verified" for e in events),
    "confirmationPhrase": next((e.get("phrase") for e in events
                                if e.get("event") == "confirmation-phrase"), None),
    "errors": [e for e in events if e.get("event") == "error"],
    "events": events,
}, open(out, "w", encoding="utf-8"), indent=1)
print(f"wrote {out}")
PYTHON

case "${outcome}" in
  done)
    if grep -aq '"outcome": "complete"' "${log}"; then
      echo "PASS: the guest reported a completed installation"
      exit 0
    fi
    if [[ "${journey}" == "d" ]] && grep -aq '"outcome": "refused-as-expected"' "${log}"; then
      echo "PASS: journey D refused as expected and installed nothing"
      exit 0
    fi
    echo "FAIL: the guest finished without reporting completion" >&2
    exit 5
    ;;
  *)
    echo "FAIL: ${outcome}; see ${log}" >&2
    exit 5
    ;;
esac

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
#   BUNNY_INSTALL_NET      none = no NIC at all (an offline-installation
#                          evidence run); anything else keeps the user-mode NIC
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
  a) drive_args="--passphrase=bunny-disk-passphrase"; verify_passphrase="bunny-disk-passphrase" ;;
  b) drive_args="--text-scale=2.0 --high-contrast --reduced-motion --passphrase=bunny-disk-passphrase"
     verify_passphrase="bunny-disk-passphrase"
     width="${BUNNY_INSTALL_WIDTH:-1024}"; height="${BUNNY_INSTALL_HEIGHT:-768}" ;;
  # Not empty, deliberately: an empty bunny.drive= is indistinguishable from
  # no marker at all, and the driver treats that as an ordinary person's boot
  # and exits — journey C spent fifteen minutes at the welcome screen with
  # nobody driving. Passing the default text scale explicitly is the
  # sentence "drive this journey, change nothing".
  c) drive_args="--text-scale=1.0"; verify_passphrase="" ;;
  d) drive_args="--expect-refusal"; verify_passphrase="" ;;
  # Phase 3's primary journey: encrypted, with a device name, and judged
  # against the full setup-choices document rather than the reduced form —
  # which is what makes the §45 handoff (choices.json on the target), the
  # locale and the hostname all part of the verdict.
  e) drive_args="--passphrase=bunny-disk-passphrase --device-name=warren"
     verify_passphrase="bunny-disk-passphrase" ;;
  *) echo "unknown journey: ${journey} (expected a, b, c, d or e)" >&2; exit 2 ;;
esac
echo "driver:  ${drive_args:-<no extra arguments>}"

# Offline is a claim that has to be earned, not asserted: the offline evidence
# run removes the NIC entirely, so nothing in the guest can quietly reach out
# and the installation either completes from the medium alone or fails where
# everyone can see it. The default keeps the user-mode NIC the interactive
# journeys ran with.
net_args=("-netdev" "user,id=net0" "-device" "virtio-net-pci,netdev=net0")
if [[ "${BUNNY_INSTALL_NET:-user}" == "none" ]]; then
  net_args=("-nic" "none")
  echo "network: none (offline evidence run)"
fi

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
  "${net_args[@]}" \
  -smbios "type=11,value=bunny.drive=${drive_args}" \
  -no-reboot &
qemu_pid=$!

cleanup() {
  kill "${qemu_pid}" 2>/dev/null
  wait "${qemu_pid}" 2>/dev/null
}
trap cleanup EXIT

# GRUB waits. `installer/config/iso.yaml` declares menu entries and no timeout,
# so the medium draws its menu and sits there — the first run of this harness
# spent fifty minutes at a menu, wrote 197 KB to an 80 GiB disk, and reported a
# timeout with no driver events at all. The serial log was nineteen kilobytes of
# GRUB drawing a box.
#
# Pressing Return selects the default entry, "Try or Install Bunny OS". Done
# here rather than by adding a timeout to the ISO because a person booting this
# medium *should* get a menu that waits for them; it is the unattended harness
# that needs a keypress, and that is a property of the harness.
#
# Sent more than once, at increasing delays: the firmware takes a variable time
# to reach GRUB, and a key pressed before the menu exists goes nowhere. Extra
# Returns land on the selected entry and are harmless.
(
  for delay in 12 20 30 45; do
    sleep "${delay}"
    python3 build/scripts/qmp-input.py --socket "${qmp}"       --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
  done
) &
grub_pid=$!

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
kill "${shots_pid}" "${grub_pid}" 2>/dev/null

# The guest has reported its outcome; power the machine off before anything
# reads the disk. Run 25 completed and the verifier still failed the gate,
# because the still-running qemu held the image's write lock and qemu-img
# refused to open it — the machine must be off before its disk is evidence.
cleanup
trap - EXIT

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
      # The screen's word is not the verdict — run 15's screen said
      # "Bunny OS is ready" over a 196 KB disk. Completion is claimed by the
      # guest and PROVEN by the disk, read from outside: a bootloader entry
      # exists and the verifier found nothing wrong.
      # What the journey chose is what the disk must carry. Without
      # --expected the verifier only checks what it happens to see: run 18's
      # disk came out unencrypted on an encrypted journey, and this gate
      # would have called it a PASS had the install finished.
      # The username is the driver's default: every journey creates alex, so
      # a completion claim whose /etc/passwd lacks alex is a FAIL — run 18
      # completed users-first tasks and no account existed, and without this
      # expectation the verifier reports that only as a fact, not a finding.
      expected="${work}/expected.json"
      # The driver speaks the full choices document as the product's own
      # record; when it did, that is the expectation — locale, hostname and
      # the §45 handoff all become part of the verdict. The reduced form
      # remains the fallback so a medium without the emitting driver still
      # gets the checks the earlier journeys had.
      if ! python3 - "${work}/result.json" "${expected}" <<'PYTHON'
import json, sys
result, out = sys.argv[1:3]
records = [e.get("record") for e in json.load(open(result)).get("events", [])
           if e.get("event") == "expected-choices" and isinstance(e.get("record"), dict)]
if not records:
    sys.exit(1)
json.dump(records[-1], open(out, "w", encoding="utf-8"), indent=1)
PYTHON
      then
        if [[ -n "${verify_passphrase}" ]]; then
          printf '{"encryption": {"enabled": true}, "account": {"username": "alex"}}\n' >"${expected}"
        else
          printf '{"encryption": {"enabled": false}, "account": {"username": "alex"}}\n' >"${expected}"
        fi
      fi
      verify_args=(--disk "${disk}" --output "${work}/installed.json"
                   --expected "${expected}")
      if [[ -n "${verify_passphrase}" ]]; then
        verify_args+=(--passphrase "${verify_passphrase}")
      fi
      python3 build/scripts/verify-installed-choices.py "${verify_args[@]}" \
        >"${work}/installed.log" 2>&1 || true
      if python3 -c "
import json, sys
record = json.load(open(sys.argv[1]))
observed = record.get('observed', {})
sys.exit(0 if (observed.get('bootEntries') and not record.get('findings')) else 1)
" "${work}/installed.json"; then
        echo "PASS: the guest reported completion and the disk carries the installation"
        exit 0
      fi
      echo "FAIL: the guest reported completion and the disk disagrees; see ${work}/installed.json" >&2
      exit 6
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

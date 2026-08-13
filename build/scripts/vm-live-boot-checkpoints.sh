#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot the installation medium and classify how far it gets — nothing else.
#
# ## Why this is not vm-install-story.sh
#
# That harness boots the ISO, drives an installation and writes a disk. It has
# one outcome, and when the medium failed before userspace it reported
# "timeout", after fifty minutes, with a nineteen-kilobyte serial log of GRUB
# drawing a box. Everything that mattered — that the kernel had loaded, that the
# initramfs had started, that switch-root had failed — was either in that log
# unread or on a screen nobody photographed.
#
# So this exists to answer one question in nine parts, cheaply, before any disk
# is created and before the installer is asked to do anything:
#
#   BOOT-1  the firmware starts the medium
#   BOOT-2  GRUB renders its menu
#   BOOT-3  the kernel starts
#   BOOT-4  the initramfs starts, and does not fail to find a live root
#   BOOT-5  the live root is located
#   BOOT-6  initrd-switch-root.service succeeds
#   BOOT-7  real userspace is PID 1
#   BOOT-8  the graphical target starts
#   BOOT-9  the Bunny setup surface appears
#
# ## §28: the screenshot comes first
#
# A screenshot is taken before the first keypress and on a schedule after it,
# and the run keeps them whether it passes or fails. The single decisive piece
# of evidence about this medium so far — "Failed to start
# initrd-switch-root.service" — was plain text on a screen. Screenshots do not
# replace logs and are not asked to; they are independent, they cost nothing,
# and twice now they have been the only thing that said what was happening.
#
# ## Why the serial-console menu entry
#
# GRUB renders to the video console, so BOOT-2 is a screenshot question. The
# kernel and systemd render wherever console= says, and the default entry says
# `console=tty0` only — which is why earlier runs had no kernel output on serial
# at all. The medium ships an entry that adds `console=ttyS0,115200n8`, and this
# harness selects it rather than editing the command line, so what is qualified
# is a menu entry the medium actually offers.
#
#   BUNNY_INSTALL_ISO      the medium to boot (default: newest under build/out/live)
#   BUNNY_BOOT_TIMEOUT     seconds to wait for BOOT-9 (default 900)
#   BUNNY_BOOT_WORK        evidence directory (default build/out/boot/<label>)
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

label="${1:-$(date -u +%Y%m%d-%H%M%S)}"
seconds="${BUNNY_BOOT_TIMEOUT:-900}"
width="${BUNNY_BOOT_WIDTH:-1280}"
height="${BUNNY_BOOT_HEIGHT:-1024}"

bunny_require_commands qemu-system-x86_64 python3 git || exit 3

iso="${BUNNY_INSTALL_ISO:-}"
if [[ -z "${iso}" ]]; then
  iso="$(find build/out/live -maxdepth 2 -type f -name '*.iso' -print -quit 2>/dev/null)"
fi
if [[ ! -f "${iso}" ]]; then
  echo "no installation ISO; set BUNNY_INSTALL_ISO or run make build-live-image" >&2
  exit 2
fi

work="${BUNNY_BOOT_WORK:-build/out/boot/${label}}"
if [[ -e "${work}" ]]; then
  echo "refusing to overwrite an existing evidence directory: ${work}" >&2
  echo "§18: a failed run's evidence is not overwritten by the next run." >&2
  exit 4
fi
mkdir -p "${work}/screens"
log="${work}/serial.log"
qmp="${work}/qmp.sock"
: >"${log}"

# §32/§18: the run is bound to an exact artifact and an exact commit, recorded
# before it starts so a failed run is still attributable.
{
  echo "sourceCommit    $(git rev-parse HEAD)"
  echo "iso             ${iso}"
  echo "isoSha256       $(sha256sum "${iso}" | cut -d' ' -f1)"
  echo "isoBytes        $(stat -c %s "${iso}")"
  echo "startedUtc      $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "qemuVersion     $(qemu-system-x86_64 --version | head -1)"
} | tee "${work}/run.txt"

firmware="$(bunny_firmware)" || exit 3
rm -f "${qmp}"

# No disk is attached. This run must not be able to write to anything: it is
# asking whether the medium boots, and a harness that could install by accident
# is a harness that will.
qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max -smp 4 -m 6144 \
  -bios "${firmware}" \
  -cdrom "${iso}" \
  -boot d \
  -device "virtio-vga,xres=${width},yres=${height}" \
  -device virtio-tablet-pci \
  -display none \
  -serial "file:${log}" \
  -qmp "unix:${qmp},server,nowait" \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
  -no-reboot &
qemu_pid=$!
cleanup() { kill "${qemu_pid}" 2>/dev/null; wait "${qemu_pid}" 2>/dev/null; }
trap cleanup EXIT

shot() {
  local name="$1"
  python3 build/scripts/qmp-screendump.py --socket "${qmp}" \
    --output "${work}/screens/${name}.ppm" >/dev/null 2>&1 || return 0
  if [[ -s "${work}/screens/${name}.ppm" ]]; then
    # Measured before the conversion, because ppm-to-png.py deletes nothing but
    # this harness does: the png is for a person and the stats are for the
    # classifier, and a blank frame has to be distinguishable from a missing one.
    python3 build/scripts/screen-stats.py --ppm "${work}/screens/${name}.ppm" \
      --json "${work}/screens/${name}.stats.json" >/dev/null 2>&1 || true
    python3 build/scripts/ppm-to-png.py "${work}/screens/${name}.ppm" >/dev/null 2>&1 || true
    rm -f "${work}/screens/${name}.ppm"
  fi
}

# The menu, before anything is pressed. This is BOOT-2's whole evidence — GRUB
# renders to video and writes nothing to serial — so it is taken first, because
# after the keypress the menu is gone. Two captures because the firmware takes a
# variable time to reach GRUB and one of them may be too early.
( sleep 10; shot "00-early"; sleep 8; shot "01-grub-menu" ) &
menu_shot_pid=$!

# Select "Try or Install Bunny OS (serial console)": the fifth entry, so four
# Downs and a Return.
#
# Every attempt lands inside GRUB's own timeout, and that bound is the reason
# for these numbers rather than any others. image-builder writes `set timeout=60`
# into both grub.cfg files, so at 60 seconds GRUB boots the *default* entry —
# which carries `console=tty0` and no serial console at all. A harness that
# pressed late would get a booting machine, an empty serial log, and a BOOT-3
# failure that belonged to the harness rather than the medium.
#
# 22, 35 and 50 seconds: three chances, the last ten seconds clear of the
# deadline. Extra Downs and Returns after a successful selection land in a
# booting Linux console and do nothing.
(
  previous_at=0
  for at in 22 35 50; do
    sleep $(( at - previous_at )); previous_at="${at}"
    for _ in 1 2 3 4; do
      python3 build/scripts/qmp-input.py --socket "${qmp}" \
        --width "${width}" --height "${height}" --key down >/dev/null 2>&1 || true
    done
    python3 build/scripts/qmp-input.py --socket "${qmp}" \
      --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
    shot "02-after-selection-t${at}"
  done
) &
select_pid=$!

( elapsed=0
  for at in 60 90 120 180 240 300 420 540 660 780 900; do
    sleep $(( at - elapsed )); elapsed="${at}"
    shot "t${at}"
  done
) &
shots_pid=$!

# Wait for BOOT-9's marker or for a terminal failure. Both are matched: a
# watcher that looked only for success would sit silently through an emergency
# shell until the timeout, which is exactly what happened last time.
outcome="timeout"
deadline=$(( SECONDS + seconds ))
while (( SECONDS < deadline )); do
  if grep -aqE 'Reached target .*(Graphical Interface|graphical\.target)' "${log}" 2>/dev/null; then
    outcome="graphical"
    # Let the session settle so BOOT-9's screenshot shows the surface rather
    # than the moment the target was reached.
    sleep 45
    shot "03-session"
    break
  fi
  # Every way this medium is known to stop, plus the shapes a stop takes.
  # `Failed to allocate manager object` / `Freezing execution` was added after a
  # run sat for the full fifteen minutes watching a PID 1 that had frozen at
  # 7.3 seconds: the boot had ended, and only the harness did not know it.
  if grep -aqE 'Entering emergency mode|Failed to start initrd-switch-root|dracut-initqueue.*[Tt]imeout|Kernel panic|Failed to allocate manager object|Freezing execution|Failed to switch root' "${log}" 2>/dev/null; then
    outcome="boot-failure"
    sleep 5
    shot "99-failure"
    break
  fi
  if ! kill -0 "${qemu_pid}" 2>/dev/null; then
    outcome="qemu-exited"
    break
  fi
  sleep 5
done
[[ "${outcome}" == "timeout" ]] && shot "99-timeout"
kill "${shots_pid}" "${select_pid}" "${menu_shot_pid}" 2>/dev/null

# §17: record what actually happened, from inside the guest's own output.
grep -aoE '/proc/cmdline.*|Command line: .*' "${log}" | head -3 > "${work}/cmdline.txt" || true

python3 build/scripts/classify-boot-checkpoints.py \
  --serial "${log}" \
  --screens "${work}/screens" \
  --harness-outcome "${outcome}" \
  --json "${work}/checkpoints.json"
status=$?

echo ""
echo "evidence: ${work}"
echo "  serial.log       $(wc -l <"${log}") lines"
echo "  screens          $(find "${work}/screens" -name '*.png' | wc -l) png"
echo "  checkpoints.json the verdict per stage"
exit "${status}"

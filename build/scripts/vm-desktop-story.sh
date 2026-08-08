#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot Bunny OS into the Bunny session and photograph the screen.
#
# Every other VM harness in this repository reads the serial console for a
# marker. That is the right check for "did it boot" and it cannot answer the
# only question this phase has, which is whether a person logging in sees the
# Bunny desktop. A desktop that fails to draw still reaches
# graphical.target, still logs a clean boot, and still passes vm-shell-smoke.
#
# So the screen itself is captured, through QEMU's QMP `screendump`. That reads
# the emulated framebuffer from outside the guest, which matters: it needs no
# screenshot API, no portal, no cooperation from the session, and it cannot be
# fooled by a compositor that thinks it drew something. What comes out is what a
# monitor plugged into that machine would show.
#
# Screenshots are taken more than once, at increasing delays. A single shot has
# to guess when the session has settled, and the two wrong answers look
# identical afterwards: too early photographs GDM, too late photographs a
# blanked screen. A series shows the desktop appearing and makes the timing
# visible instead of a parameter someone tuned.
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

profile="${BUNNY_DESKTOP_PROFILE:-shell-test}"
label="${1:-desktop-story}"
seconds="${BUNNY_DESKTOP_TIMEOUT:-540}"
user="${BUNNY_DESKTOP_USER:-bunny}"
session="${BUNNY_DESKTOP_SESSION:-bunny}"
width="${BUNNY_DESKTOP_WIDTH:-1920}"
height="${BUNNY_DESKTOP_HEIGHT:-1080}"
#: Seconds after boot at which to photograph. The last one is also when the
#: run ends, so it must be inside the timeout.
shots="${BUNNY_DESKTOP_SHOTS:-120 180 240 300}"

bunny_require_commands qemu-system-x86_64 guestfish openssl git python3 || exit 3

source_image="${BUNNY_DESKTOP_IMAGE:-}"
if [[ -z "${source_image}" ]]; then
  source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' \
    -not -path '*/desktop-story/*' -print -quit 2>/dev/null)"
fi
if [[ -z "${source_image}" ]]; then
  echo "no qcow2 under build/out/${profile}; build the image first" >&2
  exit 2
fi

work="${BUNNY_DESKTOP_WORK:-build/out/${profile}/desktop-story/${label}}"
mkdir -p "${work}/screens"
disk="${work}/disk.qcow2"
log="${work}/serial.log"
qmp="${work}/qmp.sock"

echo "source image: ${source_image}"
echo "work:         ${work}"
echo "display:      ${width}x${height}"
echo "session:      ${session}"

cp --reflink=auto "${source_image}" "${disk}"

echo "--- injecting ---"
if ! bash build/scripts/desktop-inject.sh "${disk}" build/scripts/desktop-probe.py \
      "${user}" "${session}" >"${work}/inject.log" 2>&1; then
  echo "injection failed; see ${work}/inject.log" >&2
  tail -30 "${work}/inject.log" >&2
  exit 4
fi
cat "${work}/inject.log"

firmware="$(bunny_firmware)" || exit 3
rm -f "${qmp}"
: >"${log}"

echo "--- booting (${seconds}s budget) ---"
# virtio-vga with an explicit resolution: the layout the brief specifies is for
# 1920x1080, and a default 1024x768 framebuffer would exercise the narrow
# breakpoint and photograph a layout nobody asked about.
#
# -display none keeps QEMU headless on a machine with no X; the framebuffer is
# still emulated, which is all screendump needs.
qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max \
  -smp 4 \
  -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio" \
  -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
  -device "virtio-vga,xres=${width},yres=${height}" \
  -display none \
  -serial "file:${log}" \
  -qmp "unix:${qmp},server,nowait" \
  -no-reboot &
qemu_pid=$!

cleanup() {
  if kill -0 "${qemu_pid}" 2>/dev/null; then
    kill "${qemu_pid}" 2>/dev/null
    # A guest given no chance to finish writing its record leaves a truncated
    # one, and a truncated record reads as a probe that did not run.
    for _ in $(seq 1 20); do
      kill -0 "${qemu_pid}" 2>/dev/null || break
      sleep 1
    done
    kill -9 "${qemu_pid}" 2>/dev/null
  fi
}
trap cleanup EXIT

# Wait for the QMP socket rather than sleeping a fixed amount: QEMU creates it
# before it starts the guest, so this is over in milliseconds on a fast host and
# still correct on a slow one.
for _ in $(seq 1 60); do
  [[ -S "${qmp}" ]] && break
  sleep 1
done
if [[ ! -S "${qmp}" ]]; then
  echo "QEMU never created ${qmp}" >&2
  exit 5
fi

elapsed=0
for at in ${shots}; do
  delay=$(( at - elapsed ))
  [[ ${delay} -gt 0 ]] && sleep "${delay}"
  elapsed=${at}
  if ! kill -0 "${qemu_pid}" 2>/dev/null; then
    echo "the guest exited before t=${at}s; see ${log}" >&2
    break
  fi
  target="${work}/screens/t${at}.ppm"
  if python3 build/scripts/qmp-screendump.py --socket "${qmp}" --output "${target}"; then
    echo "screenshot at t=${at}s: ${target}"
  else
    echo "screendump failed at t=${at}s" >&2
  fi
done

echo "--- shutting down ---"
python3 build/scripts/qmp-screendump.py --socket "${qmp}" --powerdown || true
for _ in $(seq 1 60); do
  kill -0 "${qemu_pid}" 2>/dev/null || break
  sleep 1
done
cleanup
trap - EXIT

echo "--- extracting the probe record ---"
probe_json="${work}/desktop-probe.json"
rm -f "${probe_json}"
root_partition="${BUNNY_DESKTOP_ROOT_PARTITION:-/dev/sda4}"
deployment="$(guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null | head -1)"
if [[ -n "${deployment}" ]]; then
  stateroot="$(dirname "$(dirname "${deployment%/}")")"
  if guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
       : download "${stateroot}/var/log/bunny-desktop-record.json" "${probe_json}" 2>/dev/null; then
    echo "record read from the guest filesystem"
  fi
fi
if [[ ! -s "${probe_json}" ]]; then
  # The serial console is the fallback, and it is a fallback: it is shared with
  # the kernel and a long record can be interleaved.
  python3 - "${log}" "${probe_json}" <<'PYTHON'
import sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
begin, end = "BUNNY-DESKTOP-RECORD-BEGIN", "BUNNY-DESKTOP-RECORD-END"
if begin in text and end in text:
    body = text.split(begin, 1)[1].split(end, 1)[0].strip()
    pathlib.Path(sys.argv[2]).write_text(body, encoding="utf-8")
    print("record recovered from the serial console")
else:
    print("no record on the serial console either")
PYTHON
fi

# PNGs, because a PPM is not viewable anywhere useful. Optional: the PPMs are
# the evidence and a missing converter must not fail the run.
if command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; then
  converter="$(command -v magick || command -v convert)"
  for ppm in "${work}/screens/"*.ppm; do
    [[ -f "${ppm}" ]] || continue
    "${converter}" "${ppm}" "${ppm%.ppm}.png" 2>/dev/null && echo "converted $(basename "${ppm%.ppm}.png")"
  done
else
  python3 build/scripts/ppm-to-png.py "${work}/screens" || true
fi

echo
echo "serial log:   ${log}"
echo "screenshots:  ${work}/screens"
echo "probe record: ${probe_json}"
[[ -s "${probe_json}" ]] || exit 6
python3 - "${probe_json}" <<'PYTHON'
import json, sys, pathlib
record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
extension = record.get("extension", {})
print(f"  shell responded:   {record.get('shellResponded', {}).get('responded')}"
      f" after {record.get('shellResponded', {}).get('afterSeconds')}s")
print(f"  extension state:   {extension.get('stateName')}")
if extension.get("error"):
    print(f"  extension error:   {extension['error']}")
print(f"  modules installed: {record.get('installedModules', {}).get('moduleCount')}")
print(f"  wallpaper present: {record.get('background', {}).get('fileExists')}")
lines = record.get("journal", {}).get("desktopLines", [])
print(f"  desktop log lines: {len(lines)}")
for line in lines[:12]:
    print(f"    {line}")
PYTHON

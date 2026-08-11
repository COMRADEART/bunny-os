#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot Bunny OS into its own session, ask Bunny to resize an image, answer the
# permission question, and photograph the screen while it happens.
#
# This is vm-desktop-story.sh's machinery with a different probe: the same disk
# copy, the same GDM autologin into the *Bunny* session rather than stock GNOME,
# the same QMP screendump. What changes is what runs inside — the journey probe,
# which talks to the Companion service over its own socket as the logged-in user.
#
# Two decisions, one script. `granted` is the success slice; `denied` is the
# refusal slice. They differ in one argument, so a difference in the outcome is
# a difference in the answer rather than in the harness.
#
# The record comes back on the serial console between two markers. A guest with
# no network and a read-only /usr has no better channel, and the console is the
# one thing a hung boot still writes to.
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

profile="${BUNNY_JOURNEY_PROFILE:-shell}"
decision="${1:-granted}"
label="${2:-journey-${decision}}"
seconds="${BUNNY_JOURNEY_TIMEOUT:-660}"
user="${BUNNY_JOURNEY_USER:-bunny}"
session="${BUNNY_JOURNEY_SESSION:-bunny}"
width="${BUNNY_JOURNEY_WIDTH:-1920}"
height="${BUNNY_JOURNEY_HEIGHT:-1080}"
#: When to photograph. The probe sleeps 45s then waits for readiness, so the
#: first shot is after the session should exist and the later ones bracket the
#: task itself.
shots="${BUNNY_JOURNEY_SHOTS:-120 180 210 240 300}"

# `failing` is `granted` with an input the program cannot read: the approval is
# given and the confined process then exits non-zero, which is the execution
# failure §13 asks for and the one a permission denial cannot stand in for.
fixture="real"
case "${decision}" in
  granted|denied) ;;
  failing) decision="granted"; fixture="corrupt"; label="${2:-journey-failing}" ;;
  *) echo "usage: vm-capsule-journey.sh [granted|denied|failing] [label]" >&2; exit 2 ;;
esac

bunny_require_commands qemu-system-x86_64 guestfish openssl git python3 || exit 3

source_image="${BUNNY_JOURNEY_IMAGE:-}"
if [[ -z "${source_image}" ]]; then
  source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' \
    -not -path '*/desktop-story/*' -not -path '*/journey/*' \
    -not -path '*/capsule-qualify/*' -print -quit 2>/dev/null)"
fi
if [[ -z "${source_image}" ]]; then
  echo "no qcow2 under build/out/${profile}; build the image first" >&2
  exit 2
fi

# Beside the build output, not inside it. The image build refuses to start
# unless its own output directory is empty, so a harness that wrote under
# build/out/<profile>/ made the next build exit 5 in under a second — and the
# alternative, letting the build delete it, took a set of screenshots with it.
# A sibling directory is neither the build's to clear nor in its way.
work="${BUNNY_JOURNEY_WORK:-build/out/journey/${profile}-${label}}"
mkdir -p "${work}/screens"
disk="${work}/disk.qcow2"
log="${work}/serial.log"
qmp="${work}/qmp.sock"

echo "source image: ${source_image}"
echo "work:         ${work}"
echo "decision:     ${decision} (fixture: ${fixture})"

cp --reflink=auto "${source_image}" "${disk}"

# The probe is injected with its decision baked into the unit, because the
# harness has no channel into the guest before the session exists and a probe
# that read its own configuration from somewhere would need one.
probe="${work}/capsule-journey-probe.py"
sed "s|^DECISION_DEFAULT = .*$|DECISION_DEFAULT = \"${decision}\"|" \
  build/scripts/capsule-journey-probe.py >"${probe}"
# The rewrite is checked, not assumed. A sed that matched nothing would leave
# the denial run answering "allow" and produce a green record for the wrong
# journey - which is the failure this whole script exists to be able to see.
if ! grep -qx "DECISION_DEFAULT = \"${decision}\"" "${probe}"    || ! grep -qx "FIXTURE_DEFAULT = \"${fixture}\"" "${probe}"; then
  echo "the decision or fixture could not be written into the probe" >&2
  exit 5
fi
cp build/scripts/desktop_interaction.py "${work}/" 2>/dev/null || true

echo "--- injecting ($(grep -m1 '^DECISION_DEFAULT' "${probe}")) ---"
if ! bash build/scripts/desktop-inject.sh "${disk}" "${probe}" \
       "${user}" "${session}" >"${work}/inject.log" 2>&1; then
  echo "injection failed; see ${work}/inject.log" >&2
  tail -30 "${work}/inject.log" >&2
  exit 4
fi
tail -5 "${work}/inject.log"

firmware="$(bunny_firmware)" || exit 3
rm -f "${qmp}"
: >"${log}"

echo "--- booting (${seconds}s budget) ---"
qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max \
  -smp 4 \
  -m 6144 \
  -bios "${firmware}" \
  -drive "file=${disk},format=qcow2,if=virtio" \
  -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
  -device "virtio-vga,xres=${width},yres=${height}" \
  -device virtio-tablet-pci \
  -display none \
  -serial "file:${log}" \
  -qmp "unix:${qmp},server,nowait" \
  -no-reboot &
qemu_pid=$!

cleanup() {
  if kill -0 "${qemu_pid}" 2>/dev/null; then
    kill "${qemu_pid}" 2>/dev/null
    for _ in $(seq 1 20); do
      kill -0 "${qemu_pid}" 2>/dev/null || break
      sleep 1
    done
    kill -9 "${qemu_pid}" 2>/dev/null
  fi
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  [[ -S "${qmp}" ]] && break
  sleep 1
done

elapsed=0
for at in ${shots}; do
  delay=$(( at - elapsed ))
  [[ ${delay} -gt 0 ]] && sleep "${delay}"
  elapsed=${at}
  kill -0 "${qemu_pid}" 2>/dev/null || break
  target="${work}/screens/t${at}.ppm"
  if python3 build/scripts/qmp-screendump.py --socket "${qmp}" --output "${target}"; then
    echo "screenshot at t=${at}s"
  fi
done

# Wait for the record, then stop. Polling the log rather than sleeping a fixed
# remainder: the journey is ~1s once the session is up, and the rest of the
# budget is boot.
deadline=$(( SECONDS + seconds ))
while (( SECONDS < deadline )); do
  grep -q "BUNNY-JOURNEY-END" "${log}" 2>/dev/null && break
  kill -0 "${qemu_pid}" 2>/dev/null || break
  sleep 5
done

python3 build/scripts/qmp-screendump.py --socket "${qmp}" --output "${work}/screens/final.ppm" || true
python3 build/scripts/qmp-screendump.py --socket "${qmp}" --powerdown || true
for _ in $(seq 1 60); do
  kill -0 "${qemu_pid}" 2>/dev/null || break
  sleep 1
done
cleanup
trap - EXIT

# The record, from the disk. The console copy is the fallback: it is shared with
# the kernel, and an audit line landed inside a JSON line on one run — not
# between lines, where the prefix strip would have caught it — so a completed
# journey read as no record at all.
echo "--- the record ---"
root_partition="${BUNNY_JOURNEY_ROOT_PARTITION:-/dev/sda4}"
# Clear any record from a previous run *before* looking for this one. A stale
# file left in place was parsed and announced as "from the guest filesystem",
# which is the most misleading thing this script has done: a run that produced
# no record reported the previous run's.
rm -f "${work}/journey.json"
deployment="$(guestfish --ro -a "${disk}" run : mount "${root_partition}" /   : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null | head -1)"
if [[ -n "${deployment}" ]]; then
  stateroot="$(dirname "$(dirname "${deployment%/}")")"
  # The user's home first: the probe runs as the user, and /var/log is not
  # writable by one - the first version wrote nowhere and said so only on stderr.
  for candidate in "${stateroot}/var/home/${user}/bunny-journey.json"                    "${stateroot}/var/tmp/bunny-journey.json"; do
    if guestfish --ro -a "${disk}" run : mount "${root_partition}" /          : download "${candidate}" "${work}/journey.json" 2>/dev/null        && [[ -s "${work}/journey.json" ]]; then
      echo "record read from the guest filesystem (${candidate})"
      break
    fi
  done
fi

python3 - "${log}" "${work}/journey.json" <<'PYTHON'
import json, pathlib, re, sys

target = pathlib.Path(sys.argv[2])
record = None
if target.exists() and target.stat().st_size:
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
        print("  (from the guest filesystem)")
    except json.JSONDecodeError:
        record = None

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
begin, end = "BUNNY-JOURNEY-BEGIN", "BUNNY-JOURNEY-END"
if record is None and (begin not in text or end not in text):
    print("no journey record on the console and none on the disk")
    raise SystemExit(0)
body = text.split(begin, 1)[1].split(end, 1)[0] if begin in text and end in text else ""
# The console interleaves kernel lines with the probe's, and systemd prefixes
# each with a timestamp and the unit. Strip both rather than hoping neither
# appeared: a record that failed to parse would be reported as "no record".
lines = []
for line in body.splitlines():
    line = re.sub(r"^\[\s*\d+\.\d+\]\s*", "", line)
    line = re.sub(r"^\S+\[\d+\]:\s*", "", line)
    if line.strip():
        lines.append(line)
raw = "\n".join(lines)
if record is None:
    try:
        record = json.loads(raw)
        print("  (from the serial console)")
    except json.JSONDecodeError as error:
        print(f"the console copy did not parse and there was no file: {error}")
        target.write_text(raw, encoding="utf-8")
        raise SystemExit(0)
# A record already read from the disk is *not* re-parsed from the console over
# the top of it. Doing exactly that destroyed one: the console copy had a kernel
# line in it, the parse failed, and the failure path wrote the raw text back
# over the good file it had just read.
target.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
print(f"  decision      {record.get('decision')}")
print(f"  ready         {(record.get('readiness') or {}).get('ok')}"
      f"  not ready: {(record.get('readiness') or {}).get('notReady')}")
print(f"  states        {' -> '.join(record.get('states') or [])}")
print(f"  approval      {str((record.get('approval') or {}).get('reason') or '')[:150]}")
print(f"  answered      {record.get('answeredAt')}  {record.get('answerError') or ''}")
print(f"  final         {record.get('finalState')}")
print(f"  summary       {str(record.get('summary') or '')[:150]}")
print(f"  result        {(record.get('result') or {}).get('files')}"
      f" {(record.get('result') or {}).get('pixels')}")
print(f"  original      {record.get('original')}")
print(f"  grants after  {record.get('grantsAfter')}")
PYTHON

if command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; then
  converter="$(command -v magick || command -v convert)"
  for ppm in "${work}/screens/"*.ppm; do
    [[ -f "${ppm}" ]] && "${converter}" "${ppm}" "${ppm%.ppm}.png" 2>/dev/null
  done
else
  python3 build/scripts/ppm-to-png.py "${work}/screens" || true
fi

echo
echo "serial log:  ${log}"
echo "screenshots: ${work}/screens"
echo "record:      ${work}/journey.json"

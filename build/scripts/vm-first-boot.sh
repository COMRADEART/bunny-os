#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot an installed disk without its installation medium, twice, and prove it.
#
# `vm-install-story.sh` ends with a disk that a verifier has read from outside;
# what it cannot say is that the disk *boots*. This harness answers that, and
# the second boot answers persistence: a system that reaches the session once
# and never again is a first-boot script that destroyed something it needed.
#
# ## What is measured, and how
#
# The installed system does not carry a serial console (the kernel command line
# is the payload's, not the harness's), so the guest cannot narrate. Evidence
# is read where it actually lands: the persistent journal, extracted from the
# disk afterwards with guestfish and read with journalctl on the host. The
# criterion per boot is systemd's own "Reached target ... Graphical Interface"
# — the same target the qualification matrices name. Screenshots are taken on
# a schedule from outside through QMP, because a journal cannot show a login
# screen with a crashed greeter painted on it (§54: look at the screen).
#
# ## The overlay
#
# The boot happens on a qcow2 overlay backed by the installed disk, so the
# evidence disk `vm-install-story.sh` produced is never mutated and remains
# re-runnable evidence. Both boots share ONE overlay: boot 2 must see what
# boot 1 wrote, or persistence was not tested at all.
#
# ## The passphrase
#
# An encrypted install (journeys A and B) stops at the LUKS prompt. The
# passphrase is typed blind through QMP at fixed delays; a keystroke sent
# before the prompt exists is buffered by plymouth or lost by the firmware
# console, and one typed after unlock lands on a login screen, which is
# cosmetic. Each attempt is preceded by a screenshot so a wrong guess about
# timing is visible in the evidence rather than a mystery.
#
#   BUNNY_FIRSTBOOT_DISK         installed qcow2 (default: journey-a's target)
#   BUNNY_FIRSTBOOT_PASSPHRASE   LUKS passphrase, empty = unencrypted install
#   BUNNY_FIRSTBOOT_BOOTS        boots to perform (default 2)
#   BUNNY_FIRSTBOOT_RUN_SECONDS  seconds each boot runs before shutdown (300)
#   BUNNY_FIRSTBOOT_TYPE_AT      delays for passphrase attempts ("35 90")
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

label="${1:-first-boot}"
disk="${BUNNY_FIRSTBOOT_DISK:-build/out/install/journey-a/target.qcow2}"
passphrase="${BUNNY_FIRSTBOOT_PASSPHRASE:-}"
boots="${BUNNY_FIRSTBOOT_BOOTS:-2}"
run_seconds="${BUNNY_FIRSTBOOT_RUN_SECONDS:-300}"
type_at="${BUNNY_FIRSTBOOT_TYPE_AT:-35 90}"
width=1280
height=1024

bunny_require_commands qemu-system-x86_64 qemu-img python3 git guestfish journalctl || exit 3

if [[ ! -f "${disk}" ]]; then
  echo "no installed disk at ${disk}; run vm-install-story.sh first" >&2
  exit 2
fi

work="build/out/install/${label}"
if [[ -d "${work}" ]]; then
  mv "${work}" "${work}.archived-$(date -u +%Y%m%d-%H%M%S)"
fi
mkdir -p "${work}/screens"

overlay="${work}/boot.qcow2"
qemu-img create -f qcow2 -b "$(realpath "${disk}")" -F qcow2 "${overlay}" >/dev/null || exit 3

echo "disk:    ${disk} (boots run on an overlay; the evidence disk stays pristine)"
echo "boots:   ${boots} x ${run_seconds}s"
echo "work:    ${work}"

firmware="$(bunny_firmware)" || exit 3

boot_once() {
  local index="$1"
  local log="${work}/serial-${index}.log"
  local qmp="${work}/qmp-${index}.sock"
  rm -f "${qmp}"
  : >"${log}"

  qemu-system-x86_64 \
    -machine q35,accel=kvm:tcg \
    -cpu max -smp 4 -m 6144 \
    -bios "${firmware}" \
    -drive "file=${overlay},format=qcow2,if=virtio" \
    -boot c \
    -device "virtio-vga,xres=${width},yres=${height}" \
    -device virtio-tablet-pci \
    -display none \
    -serial "file:${log}" \
    -qmp "unix:${qmp},server,nowait" \
    -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
    -no-reboot &
  local pid=$!

  local elapsed=0 at shot
  if [[ -n "${passphrase}" ]]; then
    for at in ${type_at}; do
      sleep $(( at - elapsed ))
      elapsed="${at}"
      python3 build/scripts/qmp-screendump.py --socket "${qmp}" \
        --output "${work}/screens/b${index}-t${at}-before-type.ppm" >/dev/null 2>&1 || true
      python3 build/scripts/qmp-input.py --socket "${qmp}" \
        --width "${width}" --height "${height}" --type "${passphrase}" >/dev/null 2>&1 || true
      python3 build/scripts/qmp-input.py --socket "${qmp}" \
        --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
    done
  fi
  while (( elapsed < run_seconds )); do
    shot=$(( elapsed + 60 ))
    (( shot > run_seconds )) && shot="${run_seconds}"
    sleep $(( shot - elapsed ))
    elapsed="${shot}"
    python3 build/scripts/qmp-screendump.py --socket "${qmp}" \
      --output "${work}/screens/b${index}-t${elapsed}.ppm" >/dev/null 2>&1 || true
  done

  # An orderly ACPI shutdown, so journald flushes and boot 2 starts from a
  # cleanly unmounted filesystem. logind's HandlePowerKey default answers the
  # power button even at a greeter. If the guest ignores it, the kill is
  # recorded as a finding rather than hidden — an unclean stop does not erase
  # the "Reached target" entries journald wrote minutes earlier.
  python3 - "${qmp}" <<'PYTHON' || true
import json, socket, sys
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
f = s.makefile("rw")
f.readline()
f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
f.write(json.dumps({"execute": "system_powerdown"}) + "\n"); f.flush(); f.readline()
PYTHON
  local waited=0
  while kill -0 "${pid}" 2>/dev/null && (( waited < 120 )); do
    sleep 5
    waited=$(( waited + 5 ))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "boot ${index}: no orderly shutdown after 120s; killing" >&2
    echo "boot-${index}-unclean-shutdown" >>"${work}/findings.txt"
    kill "${pid}" 2>/dev/null
  fi
  wait "${pid}" 2>/dev/null
  python3 build/scripts/ppm-to-png.py "${work}/screens" >/dev/null 2>&1 || true
  rm -f "${work}/screens"/*.ppm
}

for (( index = 1; index <= boots; index++ )); do
  echo "boot ${index} of ${boots}"
  boot_once "${index}"
done

# The verdict comes from the journal on the disk, not from the harness's
# impression of how the boots went.
python3 - "${work}" "${overlay}" "${passphrase}" "${boots}" <<'PYTHON'
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

work, overlay, passphrase, boots = (
    Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] or None, int(sys.argv[4]))

specification = importlib.util.spec_from_file_location(
    "verify_installed_choices", "build/scripts/verify-installed-choices.py")
verifier = importlib.util.module_from_spec(specification)
specification.loader.exec_module(verifier)

findings = []
findings_file = work / "findings.txt"
if findings_file.exists():
    findings.extend(findings_file.read_text().split())

partitions = verifier.find_partitions(overlay, passphrase)
root = partitions.get("root")
observed_boots = []
if not root:
    findings.append(f"no root filesystem found on the booted overlay: {partitions}")
else:
    tar_path = work / "journal.tar"
    output = verifier.guestfish(
        overlay,
        verifier._script(f"mount-ro {root} /",
                         f"glob tar-out /ostree/deploy/*/var/log/journal {tar_path}"),
        passphrase=passphrase)
    if output.startswith("__ERROR__") or not tar_path.exists():
        findings.append(f"the persistent journal could not be extracted: {output[:200]}")
    else:
        journal_dir = work / "journal"
        journal_dir.mkdir(exist_ok=True)
        with tarfile.open(tar_path) as archive:
            archive.extractall(journal_dir, filter="data")
        listed = subprocess.run(
            ["journalctl", "--directory", str(journal_dir), "--list-boots",
             "--output", "json", "--no-pager"],
            capture_output=True, text=True)
        try:
            boot_rows = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError:
            boot_rows = []
            findings.append(f"journalctl could not list boots: {listed.stderr[:200]}")
        for row in boot_rows:
            identifier = row.get("boot_id")
            shown = subprocess.run(
                ["journalctl", "--directory", str(journal_dir), "-b", identifier,
                 "--no-pager", "--output", "cat"],
                capture_output=True, text=True)
            reached = "Graphical Interface" in shown.stdout
            observed_boots.append({"bootId": identifier, "reachedGraphical": reached})
        if len(observed_boots) < boots:
            findings.append(
                f"the journal records {len(observed_boots)} boot(s); {boots} were performed — "
                "a boot that leaves no journal did not persist")
        for row in observed_boots:
            if not row["reachedGraphical"]:
                findings.append(f"boot {row['bootId']} never reached the graphical target")

record = {
    "schemaVersion": 1,
    "bootsRequested": boots,
    "bootsObserved": len(observed_boots),
    "boots": observed_boots,
    "findings": findings,
}
(work / "result.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
print(json.dumps(record, indent=1))
sys.exit(1 if findings else 0)
PYTHON
verdict=$?

if (( verdict == 0 )); then
  echo "PASS: the installed disk boots to the graphical target and persists across a reboot"
  exit 0
fi
echo "FAIL: see ${work}/result.json and ${work}/screens/" >&2
exit 5

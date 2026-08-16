#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot an installed Bunny OS machine, log in as the person the installer
# created, and record what they get.
#
# Every earlier session-level harness bypassed the front door: autologin was
# injected, the session was chosen through a planted AccountsService record,
# and the user was created by the harness. This one drives the path a person
# actually walks — LUKS passphrase, GDM, a typed password, the session the
# product defaults them into — and the machine disk PERSISTS across
# invocations, because "configure, reboot, come back to the same machine" is
# the Phase 3 claim and a fresh disk per run cannot carry it.
#
#   vm-login-story.sh <label>
#
#   BUNNY_LOGIN_SOURCE      installed disk to create the machine from
#                           (default build/out/install/journey-e/target.qcow2)
#   BUNNY_LOGIN_MACHINE     the persistent machine disk
#                           (default build/out/phase3/machine.qcow2)
#   BUNNY_LOGIN_FRESH       1 = archive the machine and recreate from source
#   BUNNY_LOGIN_PASSPHRASE  LUKS passphrase (default bunny-disk-passphrase;
#                           empty for an unencrypted machine)
#   BUNNY_LOGIN_USER        default alex
#   BUNNY_LOGIN_PASSWORD    default bunny-test-password
#   BUNNY_LOGIN_TYPE_AT     LUKS typing delays (default "35 90")
#   BUNNY_LOGIN_AT          seconds after boot to type the login (default 150)
#   BUNNY_LOGIN_JOURNEY     desktop-drive journey (default skip)
#   BUNNY_LOGIN_RUN_SECONDS overall in-session budget (default 600)
#   BUNNY_LOGIN_INTERACT    0 = photograph only, no driver (default 1)
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1
# shellcheck source=build/scripts/vm-lib.sh
source build/scripts/vm-lib.sh

label="${1:?usage: vm-login-story.sh <label>}"
source_disk="${BUNNY_LOGIN_SOURCE:-build/out/install/journey-e/target.qcow2}"
machine="${BUNNY_LOGIN_MACHINE:-build/out/phase3/machine.qcow2}"
passphrase="${BUNNY_LOGIN_PASSPHRASE-bunny-disk-passphrase}"
user="${BUNNY_LOGIN_USER:-alex}"
password="${BUNNY_LOGIN_PASSWORD:-bunny-test-password}"
type_at="${BUNNY_LOGIN_TYPE_AT:-35 90}"
login_at="${BUNNY_LOGIN_AT:-150}"
journey="${BUNNY_LOGIN_JOURNEY:-skip}"
run_seconds="${BUNNY_LOGIN_RUN_SECONDS:-600}"
interact="${BUNNY_LOGIN_INTERACT:-1}"
width=1920
height=1080

bunny_require_commands qemu-system-x86_64 qemu-img guestfish python3 git journalctl || exit 3

work="build/out/phase3/login/${label}"
if [[ -d "${work}" ]]; then
  mv "${work}" "${work}.archived-$(date -u +%Y%m%d-%H%M%S)"
fi
mkdir -p "${work}/screens"

# ---------------------------------------------------------------- the machine
if [[ "${BUNNY_LOGIN_FRESH:-0}" == "1" && -f "${machine}" ]]; then
  mv "${machine}" "${machine%.qcow2}.archived-$(date -u +%Y%m%d-%H%M%S).qcow2"
fi
if [[ ! -f "${machine}" ]]; then
  if [[ ! -f "${source_disk}" ]]; then
    echo "no installed disk at ${source_disk}; run vm-install-story.sh first" >&2
    exit 2
  fi
  mkdir -p "$(dirname "${machine}")"
  # A full copy, not an overlay: the machine has its own life now, and the
  # journey evidence disk stays exactly what the installer wrote.
  cp --reflink=auto "${source_disk}" "${machine}"
  echo "machine created from ${source_disk}"
  echo "--- injecting the probe (probe only; login stays the product's) ---"
  if ! BUNNY_PHASE3_PASSPHRASE="${passphrase}" \
       bash build/scripts/phase3-inject.sh "${machine}" \
       build/scripts/desktop-probe.py "${user}" >"${work}/inject.log" 2>&1; then
    echo "injection failed; see ${work}/inject.log" >&2
    tail -20 "${work}/inject.log" >&2
    exit 4
  fi
  cat "${work}/inject.log"
else
  echo "machine reused: ${machine} (its history is the persistence evidence)"
fi

firmware="$(bunny_firmware)" || exit 3
log="${work}/serial.log"
qmp="${work}/qmp.sock"
control="${work}/control.sock"
rm -f "${qmp}" "${control}"
: >"${log}"

echo "--- booting the machine ---"
qemu-system-x86_64 \
  -machine q35,accel=kvm:tcg \
  -cpu max -smp 4 -m 6144 \
  -bios "${firmware}" \
  -drive "file=${machine},format=qcow2,if=virtio" \
  -boot c \
  -device "virtio-vga,xres=${width},yres=${height}" \
  -device virtio-tablet-pci \
  -device virtio-serial-pci \
  -chardev "socket,id=bunnyctl,path=${control},server=on,wait=off" \
  -device virtserialport,chardev=bunnyctl,name=org.bunny-os.control \
  -display none \
  -serial "file:${log}" \
  -qmp "unix:${qmp},server,nowait" \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
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
[[ -S "${qmp}" ]] || { echo "QEMU never created ${qmp}" >&2; exit 5; }

shot() {
  python3 build/scripts/qmp-screendump.py --socket "${qmp}" \
    --output "${work}/screens/$1.ppm" >/dev/null 2>&1 || true
}

elapsed=0
if [[ -n "${passphrase}" ]]; then
  for at in ${type_at}; do
    sleep $(( at - elapsed )); elapsed="${at}"
    shot "t${at}-before-passphrase"
    python3 build/scripts/qmp-input.py --socket "${qmp}" \
      --width "${width}" --height "${height}" --type "${passphrase}" >/dev/null 2>&1 || true
    python3 build/scripts/qmp-input.py --socket "${qmp}" \
      --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
  done
fi

# ------------------------------------------------------------------ the login
# One attempt, deliberately. A second blind attempt after a successful first
# would type the password into whatever the session focused, and a login that
# missed its moment fails loudly here with the greeter in the screenshots —
# re-runnable, unlike a password typed into a desktop search box.
sleep $(( login_at - elapsed )); elapsed="${login_at}"
shot "t${elapsed}-greeter"
echo "typing the login for ${user} at t=${elapsed}s"
python3 build/scripts/qmp-input.py --socket "${qmp}" \
  --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
sleep 4
python3 build/scripts/qmp-input.py --socket "${qmp}" \
  --width "${width}" --height "${height}" --type "${password}" >/dev/null 2>&1 || true
python3 build/scripts/qmp-input.py --socket "${qmp}" \
  --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
sleep 15
shot "t$(( elapsed + 19 ))-after-login"

interaction_status=skipped
if [[ "${interact}" == "1" ]]; then
  echo "--- the session, through the probe ---"
  if python3 build/scripts/desktop-drive.py \
      --journey "${journey}" \
      --system-report \
      --marker "/var/home/${user}/bunny-terminal-typed.txt" \
      --qmp "${qmp}" --control "${control}" \
      --width "${width}" --height "${height}" \
      --screens "${work}/screens" \
      --output "${work}/interaction.json"; then
    interaction_status=complete
  else
    interaction_status=failed
    echo "the interaction driver reported a failure; see ${work}/interaction.json" >&2
  fi
fi
shot "t-final"

echo "--- shutting down ---"
python3 build/scripts/qmp-screendump.py --socket "${qmp}" --powerdown || true
waited=0
while kill -0 "${qemu_pid}" 2>/dev/null && (( waited < 120 )); do
  sleep 5; waited=$(( waited + 5 ))
done
if kill -0 "${qemu_pid}" 2>/dev/null; then
  echo "no orderly shutdown after 120s; killing" >&2
  echo "unclean-shutdown" >>"${work}/findings.txt"
fi
cleanup
trap - EXIT
python3 build/scripts/ppm-to-png.py "${work}/screens" >/dev/null 2>&1 || true
rm -f "${work}/screens"/*.ppm

echo "--- reading the machine back ---"
python3 - "${work}" "${machine}" "${passphrase}" "${user}" "${interaction_status}" <<'PYTHON'
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

work, machine, passphrase, user, interaction = (
    Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] or None, sys.argv[4], sys.argv[5])

specification = importlib.util.spec_from_file_location(
    "verify_installed_choices", "build/scripts/verify-installed-choices.py")
verifier = importlib.util.module_from_spec(specification)
specification.loader.exec_module(verifier)

findings = []
findings_file = work / "findings.txt"
if findings_file.exists():
    findings.extend(findings_file.read_text().split())

# Read through a throwaway overlay so the journal replays without the machine
# disk being written by the reader.
overlay = work / "read-overlay.qcow2"
subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2",
                "-b", str(machine.resolve()), "-F", "qcow2", str(overlay)], check=True)

luks_devices = verifier.find_luks_devices(overlay) if passphrase else ()
partitions = verifier.find_partitions(overlay, passphrase, luks_devices)
root = partitions.get("root")
checks = {}
if not root:
    findings.append(f"no root filesystem found on the machine: {partitions}")
else:
    tar_path = work / "journal.tar"
    output = verifier.guestfish(
        overlay,
        verifier._script(f"mount {root} /",
                         f"glob tar-out /ostree/deploy/*/var/log/journal {tar_path}"),
        passphrase=passphrase, luks_devices=luks_devices)
    if output.startswith("__ERROR__") or not tar_path.exists():
        findings.append(f"the persistent journal could not be extracted: {output[:200]}")
    else:
        import tarfile
        journal_dir = work / "journal"
        journal_dir.mkdir(exist_ok=True)
        with tarfile.open(tar_path) as archive:
            archive.extractall(journal_dir, filter="data")
        completed = subprocess.run(
            ["journalctl", "--directory", str(journal_dir), "--no-pager",
             "--output", "short-iso", "-b", "-1"],
            capture_output=True, text=True)
        text = completed.stdout
        if not text.strip():
            completed = subprocess.run(
                ["journalctl", "--directory", str(journal_dir), "--no-pager",
                 "--output", "short-iso"],
                capture_output=True, text=True)
            text = completed.stdout
        (work / "journal-lastboot.log").write_text(text, encoding="utf-8")
        checks = {
            "sessionOpened": f"session opened for user {user}" in text.lower(),
            "graphicalTarget": "Graphical Interface" in text,
            "gnomeShell": "gnome-shell" in text,
            "companionService": "bunny-companion.service" in text,
            "gdmStarted": "GNOME Display Manager" in text or "gdm" in text,
        }
        for name, value in sorted(checks.items()):
            if not value:
                findings.append(f"journal lacks evidence: {name}")

interaction_report = {}
interaction_path = work / "interaction.json"
if interaction_path.exists():
    interaction_report = json.loads(interaction_path.read_text(encoding="utf-8"))

result = {
    "schemaVersion": 1,
    "harness": "vm-login-story",
    "machine": str(machine),
    "user": user,
    "interactionStatus": interaction,
    "journalChecks": checks,
    "systemReport": interaction_report.get("system"),
    "findings": findings,
}
(work / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True),
                                  encoding="utf-8")
overlay.unlink(missing_ok=True)
print(json.dumps({k: v for k, v in result.items() if k != "systemReport"}, indent=1))
sys.exit(0 if not findings and interaction != "failed" else 6)
PYTHON
status=$?
if (( status == 0 )); then
  echo "PASS: the person logged in and the machine says so"
else
  echo "FAIL: see ${work}/result.json" >&2
fi
exit "${status}"

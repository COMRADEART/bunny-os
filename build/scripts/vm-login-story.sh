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
#   BUNNY_LOGIN_SESSION_SCRIPT  a phase3-session.py step file; when set it
#                           replaces desktop-drive as the in-session driver
#   BUNNY_LOGIN_INTERACT    0 = photograph only, no driver (default 1)
#   BUNNY_LOGIN_EXPECT_JOURNEY  granted | denied | none — what this run is FOR,
#                           declared before it runs and written to
#                           expectation.json. See the note below; the default
#                           is `none`, which is a declaration, not a silence.
#
# What this script grades, and what it does not
# ---------------------------------------------
# Until Phase 5 the grading lived here, in a heredoc, and could only run at the
# end of a sixteen-minute VM run. It is now `qualification/grader`, which is a
# library with fixtures and a test suite, and this script is a *collector*: it
# drives the machine, extracts the journal, and hands a directory to the
# grader. The one that runs here is the one the tests exercise.
#
# The declaration matters as much as the extraction. A run that booted, logged
# in, photographed a desktop and shut down *without running the journey it was
# asked for* was recorded as a pass in Phase 4, because nothing in its record
# said a journey had been requested. Writing the expectation down before the
# run is what makes that case a failure rather than a silence.
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
interact="${BUNNY_LOGIN_INTERACT:-1}"
expect_journey="${BUNNY_LOGIN_EXPECT_JOURNEY:-none}"
width=1920
height=1080

case "${expect_journey}" in
  granted|denied|none) ;;
  *) echo "BUNNY_LOGIN_EXPECT_JOURNEY must be granted, denied or none" >&2; exit 2 ;;
esac

bunny_require_commands qemu-system-x86_64 qemu-img guestfish python3 git journalctl || exit 3

work="build/out/phase3/login/${label}"
if [[ -d "${work}" ]]; then
  mv "${work}" "${work}.archived-$(date -u +%Y%m%d-%H%M%S)"
fi
mkdir -p "${work}/screens"

# ------------------------------------------------- what this run is going to do
#
# Written now, before the machine boots, and never rewritten afterwards. That
# ordering is the whole point: a declaration made after the fact could be made
# to agree with whatever happened.
python3 - "${work}/expectation.json" "${expect_journey}" "${interact}" "${label}" <<'PYTHON'
import json
import sys

path, expect_journey, interact, label = sys.argv[1:5]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "journey": None if expect_journey == "none" else expect_journey,
            "interaction": interact == "1",
            "graphicalSession": True,
            "label": label,
        },
        handle,
        indent=1,
        sort_keys=True,
    )
    handle.write("\n")
PYTHON
echo "declared: journey=${expect_journey} interaction=${interact}"

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
# Choosing somebody other than the account the greeter offers.
#
# GDM opens on the last user's password prompt, so a story for a second
# account typed that account's password into the first account's field and
# recorded a machine that never logged anyone in (g6, first attempt). The
# chords here walk back to the user list and pick a row — `esc,down,ret` for
# the account below the offered one — and the photograph taken afterwards is
# what makes the choice checkable rather than assumed.
if [[ -n "${BUNNY_LOGIN_SELECT:-}" ]]; then
  echo "  selecting another account at the greeter: ${BUNNY_LOGIN_SELECT}"
  IFS=',' read -ra chords <<< "${BUNNY_LOGIN_SELECT}"
  for chord in "${chords[@]}"; do
    python3 build/scripts/qmp-input.py --socket "${qmp}" \
      --width "${width}" --height "${height}" --key "${chord}" >/dev/null 2>&1 || true
    sleep 3
  done
  shot "t${elapsed}-user-chosen"
else
  python3 build/scripts/qmp-input.py --socket "${qmp}" \
    --width "${width}" --height "${height}" --key ret >/dev/null 2>&1 || true
fi
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
  if [[ -n "${BUNNY_LOGIN_SESSION_SCRIPT:-}" ]]; then
    if python3 build/scripts/phase3-session.py \
        --control "${control}" \
        --script "${BUNNY_LOGIN_SESSION_SCRIPT}" \
        --qmp "${qmp}" --width "${width}" --height "${height}" \
        --output "${work}/interaction.json"; then
      interaction_status=complete
    else
      interaction_status=failed
      echo "the session driver reported a failure; see ${work}/interaction.json" >&2
    fi
  elif python3 build/scripts/desktop-drive.py \
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
#
# Collection only. Everything below extracts what the run left behind and
# writes it down; nothing below decides whether the run passed. That decision
# is `qualification/grader`, called afterwards, and it is called rather than
# reimplemented so that the checks running here are the checks the fixtures in
# `qualification/grader/fixtures/` exercise.
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

# Read through a throwaway overlay so the journal replays without the machine
# disk being written by the reader. The same rule the grader is held to by
# `test_side_effect_safety`, applied one layer earlier: a probe must not alter
# the state it is measuring, and a qcow2 opened read-write would.
overlay = work / "read-overlay.qcow2"
subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2",
                "-b", str(machine.resolve()), "-F", "qcow2", str(overlay)], check=True)

luks_devices = verifier.find_luks_devices(overlay) if passphrase else ()
partitions = verifier.find_partitions(overlay, passphrase, luks_devices)
root = partitions.get("root")
if not root:
    findings.append(f"no-root-filesystem-found:{partitions}")
else:
    tar_path = work / "journal.tar"
    output = verifier.guestfish(
        overlay,
        verifier._script(f"mount {root} /",
                         f"glob tar-out /ostree/deploy/*/var/log/journal {tar_path}"),
        passphrase=passphrase, luks_devices=luks_devices)
    if output.startswith("__ERROR__") or not tar_path.exists():
        findings.append("persistent-journal-could-not-be-extracted")
    else:
        import tarfile
        journal_dir = work / "journal"
        journal_dir.mkdir(exist_ok=True)
        with tarfile.open(tar_path) as archive:
            archive.extractall(journal_dir, filter="data")
        # The boot that owns the newest journal entry IS the boot this run
        # produced. `-b -1` -- used here at first -- is an *offset*, and on a
        # directory holding N boots it selects the second-newest: login-2's
        # checks silently graded login-1's journal, with identical PIDs in the
        # extract as the tell. An explicit boot ID cannot repeat that.
        newest = subprocess.run(
            ["journalctl", "--directory", str(journal_dir), "--no-pager",
             "--output", "json", "-n", "1"],
            capture_output=True, text=True)
        boot_id = ""
        try:
            boot_id = json.loads(newest.stdout.splitlines()[-1]).get("_BOOT_ID", "")
        except (ValueError, IndexError):
            pass
        selector = ["-b", boot_id] if boot_id else []
        completed = subprocess.run(
            ["journalctl", "--directory", str(journal_dir), "--no-pager",
             "--output", "short-iso", *selector],
            capture_output=True, text=True)
        text = completed.stdout
        if not text.strip():
            findings.append("journal-extraction-produced-no-text")
        # Written even when empty, so that "extracted and empty" and "never
        # extracted" are different states on disk. The grader answers NOT_RUN
        # for the second and FAIL for the first, and it can only tell them
        # apart if this file's existence means something.
        (work / "journal-lastboot.log").write_text(text, encoding="utf-8")

# Appended, never overwritten: the shutdown watchdog may already have written
# `unclean-shutdown` here, and a collector that clobbered an earlier finding
# would be deciding what counts, which is the grader's job.
if findings:
    with (work / "findings.txt").open("a", encoding="utf-8") as handle:
        handle.write("
".join(findings) + "
")

interaction_report = {}
interaction_path = work / "interaction.json"
if interaction_path.exists():
    interaction_report = json.loads(interaction_path.read_text(encoding="utf-8"))

# The collector's own record: what it observed, with no verdict in it.
(work / "result.json").write_text(json.dumps({
    "schemaVersion": 2,
    "harness": "vm-login-story",
    "collector": "vm-login-story.sh",
    "machine": str(machine),
    "user": user,
    "interactionStatus": interaction,
    "systemReport": interaction_report.get("system"),
}, indent=1, sort_keys=True), encoding="utf-8")
overlay.unlink(missing_ok=True)
PYTHON
collect_status=$?
if (( collect_status != 0 )); then
  echo "collection failed with ${collect_status}; nothing was graded" >&2
  exit 8
fi

# The interaction status the driver reported is not in `interaction.json`, so
# it is handed to the grader on the command line rather than being re-derived.
python3 - "${work}/interaction.json" "${interaction_status}" <<'PYTHON'
import json
import sys
from pathlib import Path

path, status = Path(sys.argv[1]), sys.argv[2]
document = {}
if path.exists():
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        document = {}
if not isinstance(document, dict):
    document = {}
document["status"] = status
path.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
PYTHON

echo "--- grading ---"
PYTHONPATH="${repository_root}${PYTHONPATH:+:${PYTHONPATH}}" python3 -m qualification.grader.cli "${work}"   --user "${user}"   --merge-into "${work}/result.json"   --output "${work}/result.json"
status=$?

case "${status}" in
  0) echo "PASS: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["explanation"])' "${work}/result.json")" ;;
  6) echo "FAIL: see ${work}/result.json" >&2 ;;
  7) echo "NOT_RUN: this run measured nothing it could be graded on; see ${work}/result.json" >&2 ;;
  *) echo "the grader itself failed with ${status}" >&2 ;;
esac
exit "${status}"

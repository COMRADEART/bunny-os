#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Phase 7 rollback qualification — step 1 of 2: prepare, and write the
# expectation BEFORE anything boots.
#
# The Phase 5/6 finding this harness answers: three runs of the old harness
# reported "the previous deployment was selected" while the machine booted its
# default every time, because reaching a healthy target was the only check.
# The repaired product path (`bootc rollback` inside the guest) is
# demonstrated; what has never existed is a harness that (a) writes its
# expected state before the journey, (b) identifies the booted deployment
# from independent sources, and (c) calls a healthy machine on the wrong
# deployment FAIL.
#
# This script:
#   1. makes a disposable overlay of the Phase 5 staged disk (two deployments:
#      the Alpha RC e906a48793d7 and the dev counterpart e501218f2fe0);
#   2. reads both deployments' identities offline — BLS boot checksum, ostree
#      deploy commit, and the container image each .origin names — and binds
#      them to each other;
#   3. seeds the Phase 7 user-state markers into the shared stateroot /var and
#      writes a per-deployment /etc identity marker into each deployment, so a
#      booted system can prove whose /etc it is running from;
#   4. injects the journey unit into both deployments;
#   5. writes expectation.json: identities, preservation rules, and the
#      SHA-256 of every marker as it exists before any boot.
#
# It does NOT boot anything. run-journey.sh refuses to run until the
# expectation this script wrote has been committed, so "expected" can never be
# authored by somebody who has already seen the result.
set -uo pipefail

repo="${BUNNY_REPO:-/root/bunny-os}"
# shellcheck source=build/scripts/vm-lib.sh
source "${repo}/build/scripts/vm-lib.sh"

WORK="${BUNNY_P7_WORK:-/home/bunny/p7-work/rollback}"
EVIDENCE="${BUNNY_P7_EVIDENCE:-/home/bunny/p7-evidence/rollback}"
STAGED="${BUNNY_P7_STAGED_DISK:-/home/bunny/p5-work/stage/staged.qcow2}"
DISK="${WORK}/journey.qcow2"
BOOT_PART="${BUNNY_BOOT_PARTITION:-/dev/sda3}"
ROOT_PART="${BUNNY_ROOT_PARTITION:-/dev/sda4}"
EXPECTATION="${EVIDENCE}/expectation.json"

bunny_require_commands qemu-img guestfish virt-ls python3 sha256sum

[[ -f "${STAGED}" ]] || { echo "NOT_RUN: no staged two-deployment disk at ${STAGED}" >&2; exit 5; }
[[ -e "${DISK}" ]] && { echo "REFUSED: ${DISK} already exists; this journey is prepared once" >&2; exit 2; }
[[ -e "${EXPECTATION}" ]] && { echo "REFUSED: ${EXPECTATION} already exists; the expectation is written once" >&2; exit 2; }

mkdir -p "${WORK}" "${EVIDENCE}"

echo "== overlay =="
qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "${STAGED}")" "${DISK}" >/dev/null
echo "  ${DISK} (backing $(readlink -f "${STAGED}"))"

echo "== deployment identities, read offline =="
mapfile -t bls < <(virt-ls -a "${DISK}" -m "${BOOT_PART}" /loader/entries | grep '\.conf$' | sort)
[[ ${#bls[@]} -eq 2 ]] || { echo "NOT_RUN: expected 2 BLS entries, found ${#bls[@]}" >&2; exit 5; }

ident_py="${WORK}/identities.py"
cat >"${ident_py}" <<'PY'
import json, subprocess, sys
disk, boot_part, root_part = sys.argv[1], sys.argv[2], sys.argv[3]
entries = sys.argv[4:]

def fish(part, *cmds):
    out = subprocess.run(
        ["guestfish", "--ro", "-a", disk, "-m", part, *cmds],
        capture_output=True, text=True, check=True)
    return out.stdout

deployments = []
for conf in entries:
    text = fish(boot_part, "cat", f"/loader/entries/{conf}")
    title = version = bootcsum = None
    for line in text.splitlines():
        if line.startswith("title "):
            title = line[6:].strip()
        elif line.startswith("version "):
            version = int(line[8:].strip())
        elif "ostree=" in line:
            arg = [w for w in line.split() if w.startswith("ostree=")][0]
            bootcsum = arg.split("/")[-2]
    # Bind the BLS boot checksum to the deploy commit through the symlink the
    # kernel argument names, then to the image through the .origin file.
    target = fish(root_part, "realpath",
                  f"/ostree/boot.0/default/{bootcsum}/0").strip()
    commit = target.rstrip("/").split("/")[-1].split(".")[0]
    origin = fish(root_part,
                  "cat", f"/ostree/deploy/default/deploy/{commit}.0.origin")
    image = None
    for line in origin.splitlines():
        if "=" in line and "image" in line.split("=")[0]:
            image = line.split("=", 1)[1].strip()
    deployments.append({
        "blsEntry": conf, "blsVersion": version, "title": title,
        "bootChecksum": bootcsum, "deployCommit": commit, "originImage": image,
    })
json.dump(deployments, sys.stdout, indent=1, sort_keys=True)
PY
deployments_json="$(python3 "${ident_py}" "${DISK}" "${BOOT_PART}" "${ROOT_PART}" "${bls[@]}")"
echo "${deployments_json}" | sed 's/^/  /'

echo "== seeding user-state markers and identity markers =="
mapfile -t deploy_dirs < <(guestfish --ro -a "${DISK}" -m "${ROOT_PART}" \
    glob-expand '/ostree/deploy/default/deploy/*.0/')
[[ ${#deploy_dirs[@]} -eq 2 ]] || { echo "NOT_RUN: expected 2 deploy dirs" >&2; exit 5; }

guest_script="${WORK}/journey-guest.sh"
cp "${repo}/qualification/phase7/rollback/journey-guest.sh" "${guest_script}"

unit="${WORK}/bunny-p7-journey.service"
cat >"${unit}" <<'UNIT'
[Unit]
Description=Phase 7 rollback journey step
After=multi-user.target
ConditionPathExists=/etc/bunny-p7/journey-guest.sh

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c '/usr/bin/bash /etc/bunny-p7/journey-guest.sh; echo "BUNNY-P7: wrapper exit=$?"; sync; sleep 2; systemctl poweroff'
TimeoutStartSec=15min
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
UNIT

var_root="/ostree/deploy/default/var"
scale_json='{"scale":1.25,"setBy":"phase7 rollback qualification"}'
position_json='{"x":1600,"y":900,"anchor":"bottom-right","setBy":"phase7 rollback qualification"}'
userdata="phase7 user data written before the journey at $(date -Is)"

# The measured fact this journey design answers: the staged disk boots the
# Alpha (before-update) deployment by default today, so the journey opens
# with a restage boot that puts the machine on the update target before the
# qualified rollback runs. The guest reads which commits mean what from
# expected.env; it never guesses.
before_commit="$(echo "${deployments_json}" | python3 -c '
import json, sys
for d in json.load(sys.stdin):
    if "e906a48793d7" in (d.get("originImage") or ""):
        print(d["deployCommit"])
')"
target_commit="$(echo "${deployments_json}" | python3 -c '
import json, sys
for d in json.load(sys.stdin):
    if "e501218f2fe0" in (d.get("originImage") or ""):
        print(d["deployCommit"])
')"
[[ -n "${before_commit}" && -n "${target_commit}" ]] \
  || { echo "NOT_RUN: could not bind both deployments to their images" >&2; exit 5; }
expected_env="${WORK}/expected.env"
printf 'BEFORE_UPDATE=%s\nUPDATE_TARGET=%s\n' "${before_commit}" "${target_commit}" >"${expected_env}"

commands=(run : mount "${ROOT_PART}" /)
commands+=(: mkdir-p "${var_root}/lib/bunny-p7")
commands+=(: write "${var_root}/lib/bunny-p7/step" "restage
")
commands+=(: write "${var_root}/lib/bunny-os/companion/p7-scale.json" "${scale_json}
")
commands+=(: write "${var_root}/lib/bunny-os/companion/p7-position.json" "${position_json}
")
commands+=(: write "${var_root}/home/p7-user-data.txt" "${userdata}
")
labels=(run : mount "${ROOT_PART}" /)
labels+=(: lsetxattr security.selinux "system_u:object_r:var_lib_t:s0" 0 "${var_root}/lib/bunny-p7")
labels+=(: lsetxattr security.selinux "system_u:object_r:var_lib_t:s0" 0 "${var_root}/lib/bunny-p7/step")
labels+=(: lsetxattr security.selinux "system_u:object_r:var_lib_t:s0" 0 "${var_root}/lib/bunny-os/companion/p7-scale.json")
labels+=(: lsetxattr security.selinux "system_u:object_r:var_lib_t:s0" 0 "${var_root}/lib/bunny-os/companion/p7-position.json")
labels+=(: lsetxattr security.selinux "system_u:object_r:user_home_t:s0" 0 "${var_root}/home/p7-user-data.txt")

while read -r commit; do
  entry="/ostree/deploy/default/deploy/${commit}.0"
  # The journey owns the boot. The staged disk still carries Phase 5's
  # oneshot units in its deployments' /etc, and bunny-p5-stage.service ends
  # in `systemctl poweroff` — run 3 of this journey lost `bootc rollback`
  # mid-command to that poweroff racing it. A harness that shares the machine
  # with another harness's leftovers measures the race, not the product.
  for leftover in bunny-p5-stage.service bunny-p5-rollback.service bunny-p5-state.service; do
    commands+=(: rm-f "${entry}/etc/systemd/system/multi-user.target.wants/${leftover}")
  done
  commands+=(: mkdir-p "${entry}/etc/bunny-p7")
  commands+=(: upload "${guest_script}" "${entry}/etc/bunny-p7/journey-guest.sh")
  commands+=(: chmod 0644 "${entry}/etc/bunny-p7/journey-guest.sh")
  commands+=(: upload "${expected_env}" "${entry}/etc/bunny-p7/expected.env")
  commands+=(: chmod 0644 "${entry}/etc/bunny-p7/expected.env")
  commands+=(: write "${entry}/etc/bunny-p7-etc-identity" "${commit}
")
  commands+=(: upload "${unit}" "${entry}/etc/systemd/system/bunny-p7-journey.service")
  commands+=(: chmod 0644 "${entry}/etc/systemd/system/bunny-p7-journey.service")
  commands+=(: mkdir-p "${entry}/etc/systemd/system/multi-user.target.wants")
  commands+=(: ln-sf /etc/systemd/system/bunny-p7-journey.service
             "${entry}/etc/systemd/system/multi-user.target.wants/bunny-p7-journey.service")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 "${entry}/etc/bunny-p7")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 "${entry}/etc/bunny-p7/journey-guest.sh")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 "${entry}/etc/bunny-p7/expected.env")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 "${entry}/etc/bunny-p7-etc-identity")
  labels+=(: lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0 "${entry}/etc/systemd/system/bunny-p7-journey.service")
done < <(echo "${deployments_json}" | python3 -c 'import json,sys; [print(d["deployCommit"]) for d in json.load(sys.stdin)]')

guestfish -a "${DISK}" "${commands[@]}"
guestfish -a "${DISK}" "${labels[@]}"
echo "  markers seeded, identity markers written, journey unit injected into both deployments"

echo "== recording marker digests, offline, before any boot =="
markers=(
  "${var_root}/home/p5-user-data.txt"
  "${var_root}/home/p7-user-data.txt"
  "${var_root}/lib/bunny-os/companion/p5-mode.json"
  "${var_root}/lib/bunny-os/companion/p7-scale.json"
  "${var_root}/lib/bunny-os/companion/p7-position.json"
  "${var_root}/lib/bunny-os/trust/p5-grants.json"
  "${var_root}/lib/bunny-os/voice/p5-settings.json"
  "${var_root}/lib/bunny-os/p5-settings.txt"
)
digest_lines=""
for m in "${markers[@]}"; do
  sum="$(guestfish --ro -a "${DISK}" -m "${ROOT_PART}" checksum sha256 "${m}")" \
    || { echo "NOT_RUN: expected marker ${m} is absent" >&2; exit 5; }
  runtime_path="/var${m#${var_root}}"
  digest_lines+="${sum}  ${runtime_path}"$'\n'
done
printf '%s' "${digest_lines}" | sed 's/^/  /'

python3 - "${EXPECTATION}" <<PY
import json, sys
deployments = ${deployments_json}
digests = {}
for line in """${digest_lines}""".strip().splitlines():
    sha, path = line.split(None, 1)
    digests[path] = sha
expectation = {
    "schemaVersion": 1,
    "writtenBeforeBoot": True,
    "journey": "phase7-rollback",
    "subjectDisk": {
        "stagedFrom": "${STAGED}",
        "backing": "Phase 4 Alpha RC e906a48793d7 qcow2 with the Phase 5 e501218f2fe0 update staged",
    },
    "deployments": deployments,
    "rules": {
        "bootRestage": [
            "the staged disk boots the before-update deployment by default (measured before this harness was designed); the restage boot must put the machine on the update target, or observe it is already there, before the qualified rollback runs",
            "the restage boot's own identity must be readable from all three sources like every other boot",
        ],
        "bootRollback": [
            "the journey unit reports the booted deployment from the kernel cmdline, bootc status --json, and the /etc identity marker; all three must name the same deployment",
            "bootc rollback must exit 0",
            "ostree admin status after the rollback must list the OTHER deployment first (the selected rollback target)",
        ],
        "bootVerify": [
            "the booted deployment must be the selected rollback target, agreed independently by the kernel cmdline ostree= argument, by bootc status --json, and by the /etc identity marker",
            "a healthy boot target on any other deployment is FAIL, not PASS and not NOT_RUN",
        ],
        "preservedByteIdentical": digests,
        "perDeploymentEtc": "the /etc identity marker read after rollback must name the rollback target's deploy commit -- proving the per-deployment /etc actually switched",
        "hostname": {"file": "ABSENT in both deployments before the journey", "expectAfterRollback": "ABSENT (transient hostname localhost)"},
        "locale": {"expectAfterRollback": "LANG=\"C.UTF-8\" (the fallback locale.conf, identical in both deployments)"},
        "verdicts": {"PASS": "every rule above holds", "FAIL": "any rule fails, including healthy-but-wrong-deployment", "NOT_RUN": "a precondition was absent and no deployment switch was exercised"},
    },
}
with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as fh:
    json.dump(expectation, fh, indent=1, sort_keys=True)
    fh.write("\n")
PY

echo
echo "expectation written: ${EXPECTATION}"
echo "Commit it. run-journey.sh refuses to boot until the committed copy matches."

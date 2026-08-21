#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Put the capsule runtime qualification harness, and a unit that runs it as the
# ordinary user, into a copy of a bootc disk.
#
# The harness is *injected*, not shipped. A measuring instrument inside the
# artifact would be part of what it measures, and the existing desktop probe is
# arranged the same way for the same reason. What the image already carries is
# the thing under test — trust, capsules, catalog and companion at
# /usr/lib/bunny-os/python — and the harness only needs to be able to import it.
#
# Everything here follows desktop-inject.sh's hard-won rules:
#
#   * guestfish rather than virt-customize, because a bootc disk has no
#     inspectable root;
#   * writes confined to <deployment>/etc and the stateroot's /var, because
#     <deployment>/usr is a read-only composefs image and an instrument that
#     modified it would have changed what it measures;
#   * every file guestfish *creates* gets an SELinux label applied explicitly.
#     A new file has no security.selinux xattr at all, the policy sees
#     unlabeled_t, and the failure is silent and looks like something else
#     entirely. Files that are overwritten keep their label; files that are
#     created do not.
set -euo pipefail

disk="${1:?usage: capsule-qualify-inject.sh <disk.qcow2> [user] [commit]}"
user="${2:-bunny}"
commit="${3:-unknown}"
repository_root="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

root_partition="${BUNNY_CAPSULE_ROOT_PARTITION:-/dev/sda4}"

deployment="$(guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null | head -1)"
if [[ -z "${deployment}" ]]; then
  echo "no ostree deployment found on ${root_partition} of ${disk}" >&2
  exit 2
fi
deployment="${deployment%/}"
stateroot="$(dirname "$(dirname "${deployment}")")"
echo "deployment: ${deployment}"
echo "stateroot:  ${stateroot}"

# Refuse early if the image does not carry the thing under test. Without this a
# run produces a guest that boots, a unit that fails on ImportError, and an
# empty evidence directory that reads as "the harness did not run" rather than
# "the image does not contain the packages".
for required in trust capsules catalog companion; do
  if ! guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
       : is-dir "${deployment}/usr/lib/bunny-os/python/${required}" 2>/dev/null | grep -q true; then
    echo "the image has no /usr/lib/bunny-os/python/${required}" >&2
    echo "there is nothing in it to qualify; rebuild from a commit that installs it" >&2
    exit 2
  fi
done
echo "image carries: trust capsules catalog companion"

# The harness, mirroring the repository layout because harness.py derives its
# root from its own location and reads the probe from qualification/capsules/.
mkdir -p "${work}/tree/scripts/capsules" "${work}/tree/qualification/capsules"
cp "${repository_root}"/scripts/capsules/*.py "${work}/tree/scripts/capsules/"
cp "${repository_root}"/qualification/capsules/probe.py \
   "${repository_root}"/qualification/capsules/stress.py "${work}/tree/qualification/capsules/"

cat >"${work}/run-qualification.sh" <<'RUNNER'
#!/usr/bin/bash
# Injected by capsule-qualify-inject.sh. Runs the qualification as the ordinary
# user and powers the machine off, so the harness on the host can read the disk.
set -uo pipefail
user="${BUNNY_QUALIFY_USER:-bunny}"
commit="${BUNNY_QUALIFY_COMMIT:-unknown}"
out=/var/log/bunny-capsule-qualify
mkdir -p "${out}"
chown "${user}" "${out}"

# The user manager has to be up before `systemd-run --user` can create a scope.
# Linger is set by the injector, and it is asked for explicitly as well: a
# lingering user whose marker file the policy refused to read looks exactly like
# a user with no linger, and starting the unit by name says which it was.
systemctl start "user@1000.service" >/dev/null 2>&1 || true
for _ in $(seq 1 60); do
  [[ -d /run/user/1000 ]] && [[ -S /run/user/1000/bus ]] && break
  sleep 1
done
loginctl show-user "${user}" >"${out}/loginctl.txt" 2>&1 || true
# Kernel messages as root, kept beside the evidence. The section collects its
# own as the ordinary user and records whether it could; this is the copy a
# person can read afterwards when the answer was "it could not".
dmesg --ctime >"${out}/dmesg-root.txt" 2>&1 || echo "dmesg unavailable" >"${out}/dmesg-root.txt"
sysctl kernel.dmesg_restrict >"${out}/dmesg-restrict.txt" 2>&1 || true
systemctl is-active "user@1000.service" >"${out}/user-manager.txt" 2>&1 || true

runuser -u "${user}" -- env \
  XDG_RUNTIME_DIR=/run/user/1000 \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  PYTHONPATH=/usr/lib/bunny-os/python \
  BUNNY_QUALIFY_COMMIT="${commit}" \
  HOME="/var/home/${user}" \
  /usr/bin/python3 /etc/bunny-capsule-qualify/scripts/capsules/runtime_qualify.py \
    --all --evidence-root "${out}/evidence" \
  >"${out}/runtime_qualify.log" 2>&1
echo "qualification exit: $?" >>"${out}/runtime_qualify.log"

# A compact summary on the console, so a run whose disk cannot be read
# afterwards still says something.
# The kernel buffer after the run, captured as root. The section collects its
# own as the ordinary user and records that it could not: kernel.dmesg_restrict
# is 1 in this image, the journal carries no kernel lines and auditd is not
# installed. This is the copy that can actually answer "were there denials",
# and it is taken after the capsule work rather than before it.
dmesg --ctime >"${out}/dmesg-after.txt" 2>"${out}/dmesg-after.err" || true
grep -ci "avc" "${out}/dmesg-after.txt" >"${out}/dmesg-avc-count.txt" 2>/dev/null || echo 0 >"${out}/dmesg-avc-count.txt"
grep -i "avc" "${out}/dmesg-after.txt" >"${out}/dmesg-avc-lines.txt" 2>/dev/null || true

echo "BUNNY-CAPSULE-QUALIFY-BEGIN"
echo "kernel-avc-lines: $(cat "${out}/dmesg-avc-count.txt" 2>/dev/null || echo unknown)"
/usr/bin/python3 - "${out}/evidence" <<'SUMMARY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
summary = {}
for path in sorted(root.rglob("*.json")):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    summary[document.get("section", path.stem)] = {
        "verdict": document.get("verdict"),
        "explanation": (document.get("explanation") or "")[:200],
        "findings": [f[:160] for f in document.get("findings", [])][:4],
    }
print(json.dumps(summary, indent=1, sort_keys=True))
SUMMARY
echo "BUNNY-CAPSULE-QUALIFY-END"

sync
systemctl poweroff --no-block
RUNNER
chmod 0755 "${work}/run-qualification.sh"

cat >"${work}/bunny-capsule-qualify.service" <<UNIT
[Unit]
Description=Bunny OS capsule runtime qualification (injected by the harness, not shipped)
After=multi-user.target systemd-user-sessions.service
Wants=multi-user.target

[Service]
Type=oneshot
Environment=BUNNY_QUALIFY_USER=${user}
Environment=BUNNY_QUALIFY_COMMIT=${commit}
# The user manager is started by linger and needs a moment; the runner waits for
# /run/user/1000 itself, and this is only the delay before it starts asking.
ExecStartPre=/usr/bin/sleep 20
ExecStart=/usr/bin/bash /etc/bunny-capsule-qualify/run-qualification.sh
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
UNIT

password_hash="$(openssl passwd -6 bunny-qualify-vm)"

commands=(
  run
  : mount "${root_partition}" /
  : mkdir-p "${deployment}/etc/bunny-capsule-qualify/scripts/capsules"
  : mkdir-p "${deployment}/etc/bunny-capsule-qualify/qualification/capsules"
  : upload "${work}/run-qualification.sh" "${deployment}/etc/bunny-capsule-qualify/run-qualification.sh"
  : chmod 0755 "${deployment}/etc/bunny-capsule-qualify/run-qualification.sh"
  : upload "${work}/bunny-capsule-qualify.service" "${deployment}/etc/systemd/system/bunny-capsule-qualify.service"
  : mkdir-p "${deployment}/etc/systemd/system/multi-user.target.wants"
  : ln-sf /etc/systemd/system/bunny-capsule-qualify.service
          "${deployment}/etc/systemd/system/multi-user.target.wants/bunny-capsule-qualify.service"
  : mkdir-p "${stateroot}/var/lib/systemd/linger"
  : touch "${stateroot}/var/lib/systemd/linger/${user}"
  : mkdir-p "${stateroot}/var/home/${user}"
  : chown 1000 1000 "${stateroot}/var/home/${user}"
  : chmod 0700 "${stateroot}/var/home/${user}"
  : mkdir-p "${stateroot}/var/log/bunny-capsule-qualify"
)
for file in "${work}"/tree/scripts/capsules/*.py; do
  commands+=(: upload "${file}" "${deployment}/etc/bunny-capsule-qualify/scripts/capsules/$(basename "${file}")")
done
for file in "${work}"/tree/qualification/capsules/*.py; do
  commands+=(: upload "${file}" "${deployment}/etc/bunny-capsule-qualify/qualification/capsules/$(basename "${file}")")
done

{
  guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
    : download "${deployment}/etc/passwd" "${work}/passwd" \
    : download "${deployment}/etc/group" "${work}/group" \
    : download "${deployment}/etc/shadow" "${work}/shadow"
} 2>/dev/null

if ! grep -q "^${user}:" "${work}/passwd"; then
  printf '%s:x:1000:1000:Bunny qualification user:/var/home/%s:/bin/bash\n' "${user}" "${user}" \
    >>"${work}/passwd"
  printf '%s:x:1000:\n' "${user}" >>"${work}/group"
  printf '%s:%s:20000:0:99999:7:::\n' "${user}" "${password_hash}" >>"${work}/shadow"
  commands+=(
    : upload "${work}/passwd" "${deployment}/etc/passwd"
    : upload "${work}/group" "${deployment}/etc/group"
    : upload "${work}/shadow" "${deployment}/etc/shadow"
    : chmod 0000 "${deployment}/etc/shadow"
  )
  echo "created ${user} (uid 1000)"
else
  echo "${user} already present in the image"
fi

guestfish -a "${disk}" "${commands[@]}"
echo "injected: harness, unit, linger, ${user}"

# SELinux labels for everything created. See the header: a guestfish-created
# file has no label at all and the policy refuses it, silently.
#
# A `labels=$(guestfish ... file-architecture ...)` probe stood here and its
# output was never read — a whole extra guestfish boot, several seconds, for a
# value nothing used. ShellCheck's SC2034 is what noticed.
relabel=(
  run
  : mount "${root_partition}" /
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify"
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify/scripts"
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify/scripts/capsules"
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify/qualification"
  : lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify/qualification/capsules"
  : lsetxattr security.selinux "system_u:object_r:bin_t:s0" 0
      "${deployment}/etc/bunny-capsule-qualify/run-qualification.sh"
  : lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0
      "${deployment}/etc/systemd/system/bunny-capsule-qualify.service"
  : lsetxattr security.selinux "system_u:object_r:var_log_t:s0" 0
      "${stateroot}/var/log/bunny-capsule-qualify"
  # The linger marker. Unlabelled, logind cannot read it, the user manager never
  # starts, and `systemd-run --user` has no bus to talk to — which is exactly
  # what the first guest run produced: user@1000.service inactive and an empty
  # loginctl. The failure is silent in the same way the AccountsService one was.
  : lsetxattr security.selinux "system_u:object_r:var_lib_t:s0" 0
      "${stateroot}/var/lib/systemd/linger/${user}"
  : lsetxattr security.selinux "system_u:object_r:user_home_dir_t:s0" 0
      "${stateroot}/var/home/${user}"
)
for file in "${work}"/tree/scripts/capsules/*.py "${work}"/tree/qualification/capsules/*.py; do
  case "${file}" in
    */scripts/capsules/*) target="${deployment}/etc/bunny-capsule-qualify/scripts/capsules/$(basename "${file}")" ;;
    *) target="${deployment}/etc/bunny-capsule-qualify/qualification/capsules/$(basename "${file}")" ;;
  esac
  relabel+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0 "${target}")
done
guestfish -a "${disk}" "${relabel[@]}"
echo "relabelled: harness tree, unit, log directory, home"

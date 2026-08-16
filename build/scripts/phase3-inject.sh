#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Put ONLY the desktop probe into an installed Bunny OS disk — encrypted or
# not — leaving the greeter, the password prompt and the session choice
# exactly as the installer produced them.
#
# desktop-inject.sh exists for images with no user: it creates one, hashes a
# password, writes autologin and chooses the session through AccountsService.
# Phase 3's real-login journey is *about* the path all of that bypasses: a
# person at GDM, typing a password, getting the session the product defaults
# them into. So this injects the probe and nothing else, and it can open a
# LUKS root because the disks it works on were installed with encryption on —
# the mechanics (--keys-from-stdin, a writable luks-open so the journal can
# replay, the grown appliance for argon2id) are the verifier's, measured on
# runs 19b through 27.
#
#   BUNNY_PHASE3_PASSPHRASE       LUKS passphrase; empty = unencrypted disk
#   BUNNY_PHASE3_ROOT_PARTITION   default /dev/sda3 (installed layout: EFI,
#                                 boot, root — found, not counted, by the
#                                 verifier; fixed here because the injector
#                                 refuses rather than guesses)
set -euo pipefail

disk="${1:?usage: phase3-inject.sh <disk.qcow2> <probe.py> [user]}"
probe="${2:?usage: phase3-inject.sh <disk.qcow2> <probe.py> [user]}"
user="${3:-alex}"
# The probe imports this from beside itself; see desktop-probe.py.
interaction="$(dirname "${probe}")/desktop_interaction.py"
passphrase="${BUNNY_PHASE3_PASSPHRASE:-}"
root_partition="${BUNNY_PHASE3_ROOT_PARTITION:-/dev/sda3}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

# argon2id on these disks costs 1 GiB per unlock; the default appliance fails
# the KDF as "No key available" when memory luck runs out.
export LIBGUESTFS_MEMSIZE="${LIBGUESTFS_MEMSIZE:-3072}"

gf() {
  # guestfish against the disk with the root mounted, LUKS-opened when the
  # passphrase is set. First argument ro|rw, the rest are guestfish commands.
  local access="$1"; shift
  local flags=()
  [[ "${access}" == ro ]] && flags+=(--ro)
  if [[ -n "${passphrase}" ]]; then
    printf '%s\n' "${passphrase}" | guestfish "${flags[@]}" --keys-from-stdin \
      -a "${disk}" run : luks-open "${root_partition}" phase3root \
      : mount /dev/mapper/phase3root / "$@"
  else
    guestfish "${flags[@]}" -a "${disk}" run \
      : mount "${root_partition}" / "$@"
  fi
}

deployment="$(gf ro : glob-expand '/ostree/deploy/*/deploy/*.0/' 2>/dev/null | head -1)"
if [[ -z "${deployment}" ]]; then
  echo "no ostree deployment found on ${root_partition} of ${disk}" >&2
  exit 2
fi
deployment="${deployment%/}"
echo "deployment: ${deployment}"

cat >"${work}/bunny-desktop-probe.service" <<UNIT
[Unit]
Description=Bunny OS desktop probe (injected by the harness, not shipped)
After=graphical.target
Wants=graphical.target

[Service]
# exec, not oneshot: this probe serves a command queue for the life of the
# guest; a oneshot is "activating" for its whole runtime and systemd's start
# timeout killed the channel 15m45s into every boot on the Stage 2 run.
Type=exec
Environment=BUNNY_PROBE_USER=${user}
# The probe waits for GNOME Shell on its own; this only delays when it starts
# asking. On this journey the shell appears when a person logs in, and the
# probe's own wait rides through the greeter.
ExecStartPre=/usr/bin/sleep 45
ExecStart=/usr/bin/python3 /etc/bunny-desktop-probe.py
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=300

[Install]
WantedBy=graphical.target
UNIT

gf rw \
  : upload "${probe}" "${deployment}/etc/bunny-desktop-probe.py" \
  : chmod 0755 "${deployment}/etc/bunny-desktop-probe.py" \
  : upload "${interaction}" "${deployment}/etc/desktop_interaction.py" \
  : chmod 0644 "${deployment}/etc/desktop_interaction.py" \
  : upload "${work}/bunny-desktop-probe.service" "${deployment}/etc/systemd/system/bunny-desktop-probe.service" \
  : mkdir-p "${deployment}/etc/systemd/system/graphical.target.wants" \
  : ln-sf /etc/systemd/system/bunny-desktop-probe.service \
          "${deployment}/etc/systemd/system/graphical.target.wants/bunny-desktop-probe.service"

# SELinux labels, read out of the guest's own policy — a file guestfish
# creates has no label at all, and unlabeled_t is refused by the policy in
# ways that surface as somebody else's bug (desktop-inject.sh's header carries
# the eleven-restart GDM measurement).
contexts="${work}/policy-specifications"
: >"${contexts}"
for specification in file_contexts file_contexts.homedirs; do
  gf ro : download "${deployment}/etc/selinux/targeted/contexts/files/${specification}" \
    "${work}/spec-${specification}" 2>/dev/null || continue
  cat "${work}/spec-${specification}" >>"${contexts}"
done
if [[ ! -s "${contexts}" ]]; then
  echo "the guest has no file_contexts; cannot label the injected files" >&2
  exit 5
fi

label_commands=()
verify=()
apply_label() {
  local target="$1" type="$2" justification="$3"
  if ! grep -qE "${justification}" "${contexts}"; then
    echo "no specification matching ${justification} in the guest policy" >&2
    exit 5
  fi
  local value="system_u:object_r:${type}:s0"
  label_commands+=(: setxattr "security.selinux" "${value}" "${#value}" "${target}")
  verify+=("${target}")
}
apply_label "${deployment}/etc/bunny-desktop-probe.py" etc_t '^/etc/\.\*'
apply_label "${deployment}/etc/desktop_interaction.py" etc_t '^/etc/\.\*'
apply_label "${deployment}/etc/systemd/system/bunny-desktop-probe.service" \
  systemd_unit_file_t 'systemd_unit_file_t'

gf rw "${label_commands[@]}"

read_commands=()
for entry in "${verify[@]}"; do
  read_commands+=(: getxattr "${entry}" "security.selinux")
done
echo "--- labels, read back ---"
gf ro "${read_commands[@]}" | tr -d '\000' | while read -r line; do
  [[ -n "${line}" ]] && echo "  ${line}"
done
echo "injected: probe only, as ${user}; login stays the product's own"

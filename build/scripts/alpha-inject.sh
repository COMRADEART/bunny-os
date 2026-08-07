#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Put the probe, a desktop user and GDM autologin into a bootc disk image.
#
# `virt-customize` cannot do this and says so: *no operating systems were found
# in the guest image*. Its inspection looks for a root filesystem with /etc and
# /usr at the top, and a bootc disk has neither — the root partition holds
# `ostree/` and `boot/`, and the system lives at
#
#     /ostree/deploy/default/deploy/<checksum>.0/
#
# with `/var` beside it at /ostree/deploy/default/var. So this drives guestfish
# directly and writes to the two places that are actually writable in an ostree
# deployment:
#
#   <deployment>/etc   per-deployment configuration, a real directory
#   .../default/var    the stateroot's /var, shared across deployments
#
# `<deployment>/usr` is deliberately not written to. It is a composefs image
# (`.ostree.cfs`), it is read-only by design, and an instrument that had to
# modify the immutable half of the image in order to measure it would have
# changed the thing under test. The probe therefore lives in /etc and is run by
# the system python from /usr, which is the copy the image shipped.
set -euo pipefail

disk="${1:?usage: alpha-inject.sh <disk.qcow2> <probe.py> <user> [offline]}"
probe="${2:?usage: alpha-inject.sh <disk.qcow2> <probe.py> <user> [offline]}"
user="${3:-bunny}"
offline="${4:-0}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

root_partition="${BUNNY_ALPHA_ROOT_PARTITION:-/dev/sda4}"

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

# A SHA-512 crypt of a fixed password. This is a throwaway virtual machine that
# exists for one boot and is deleted afterwards; the password is in the harness
# in plain sight rather than hidden, because a credential nobody can see is a
# credential somebody will assume is a secret.
password_hash="$(openssl passwd -6 bunny-alpha-vm)"

cat >"${work}/bunny-alpha-probe.service" <<UNIT
[Unit]
Description=Bunny OS Public Alpha probe (injected by the harness, not shipped)
# After the graphical target, and then a wait: the questions are about a settled
# session, and a probe that ran the moment graphical.target was reached would
# ask whether the companion had started before it had had the chance to.
After=graphical.target
Wants=graphical.target

[Service]
Type=oneshot
Environment=BUNNY_PROBE_USER=${user}
ExecStartPre=/usr/bin/sleep 60
ExecStart=/usr/bin/python3 /etc/bunny-alpha-probe.py
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=900

[Install]
WantedBy=graphical.target
UNIT

cat >"${work}/gdm-custom.conf" <<GDM
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=${user}
WaylandEnable=True
GDM

# A serial console for the probe's output, and a kernel that will use it.
cat >"${work}/serial.conf" <<'SERIAL'
[Service]
StandardOutput=journal+console
SERIAL

commands=(
  run
  : mount "${root_partition}" /
  # -- the probe -----------------------------------------------------------
  : upload "${probe}" "${deployment}/etc/bunny-alpha-probe.py"
  : chmod 0755 "${deployment}/etc/bunny-alpha-probe.py"
  : upload "${work}/bunny-alpha-probe.service" "${deployment}/etc/systemd/system/bunny-alpha-probe.service"
  : mkdir-p "${deployment}/etc/systemd/system/graphical.target.wants"
  : ln-sf /etc/systemd/system/bunny-alpha-probe.service
          "${deployment}/etc/systemd/system/graphical.target.wants/bunny-alpha-probe.service"
  # -- autologin -----------------------------------------------------------
  : mkdir-p "${deployment}/etc/gdm"
  : upload "${work}/gdm-custom.conf" "${deployment}/etc/gdm/custom.conf"
  # -- linger, so the user manager starts and stays -------------------------
  : mkdir-p "${stateroot}/var/lib/systemd/linger"
  : touch "${stateroot}/var/lib/systemd/linger/${user}"
  # -- the home directory --------------------------------------------------
  : mkdir-p "${stateroot}/var/home/${user}"
  : chown 1000 1000 "${stateroot}/var/home/${user}"
  : chmod 0700 "${stateroot}/var/home/${user}"
)

# The account records, appended rather than templated: the base image's own
# passwd already has every system account and rewriting it would be a change to
# something the image shipped.
{
  guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
    : download "${deployment}/etc/passwd" "${work}/passwd" \
    : download "${deployment}/etc/group" "${work}/group" \
    : download "${deployment}/etc/shadow" "${work}/shadow"
} 2>/dev/null

if ! grep -q "^${user}:" "${work}/passwd"; then
  printf '%s:x:1000:1000:Bunny Alpha harness user:/var/home/%s:/bin/bash\n' "${user}" "${user}" \
    >>"${work}/passwd"
  printf '%s:x:1000:\n' "${user}" >>"${work}/group"
  printf 'wheel:x:10:%s\n' "${user}" >>"${work}/group"
  printf '%s:%s:20000:0:99999:7:::\n' "${user}" "${password_hash}" >>"${work}/shadow"
fi

commands+=(
  : upload "${work}/passwd" "${deployment}/etc/passwd"
  : upload "${work}/group" "${deployment}/etc/group"
  : upload "${work}/shadow" "${deployment}/etc/shadow"
  : chmod 0000 "${deployment}/etc/shadow"
)

if [[ "${offline}" == "1" ]]; then
  # §13: configure the guest offline as well as unplugging it, so the record
  # shows a system that was configured that way rather than one that merely had
  # nowhere to go.
  commands+=(
    : mkdir-p "${deployment}/etc/systemd/system/NetworkManager.service.d"
    : write "${deployment}/etc/systemd/system/NetworkManager.service.d/offline.conf"
            "[Unit]\nConditionPathExists=/nonexistent-offline-marker\n"
  )
fi

guestfish -a "${disk}" "${commands[@]}"
echo "injected: probe, ${user}, autologin, linger$( [[ "${offline}" == "1" ]] && echo ', offline' )"

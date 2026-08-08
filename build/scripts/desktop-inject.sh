#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Put a desktop user, GDM autologin *into the Bunny session*, and the desktop
# probe into a copy of a bootc disk.
#
# This is alpha-inject.sh with one addition that is the entire point of it. That
# script logs a user in; GDM then starts whichever session it defaults to, which
# on this image is plain GNOME. The Bunny extension would be installed, enabled
# and completely inert, because extension.js returns early unless
# BUNNY_SHELL_MODE is "normal" and only /usr/libexec/bunny-shell-session sets
# that. A harness that did not choose the session would photograph a stock GNOME
# desktop and prove nothing at all.
#
# The session is chosen through AccountsService, which is where GDM reads a
# user's last choice from. Both keys are written: modern GNOME reads `Session`,
# older versions read `XSession`, and a harness that guessed wrong would fail in
# the way described above — silently, with a plausible screenshot.
#
# Everything else is inherited from alpha-inject.sh's reasoning: guestfish
# rather than virt-customize because a bootc disk has no inspectable root;
# writes confined to <deployment>/etc and the stateroot's /var because
# <deployment>/usr is a read-only composefs image and an instrument that
# modified it would have changed what it measures.
set -euo pipefail

disk="${1:?usage: desktop-inject.sh <disk.qcow2> <probe.py> [user] [session]}"
probe="${2:?usage: desktop-inject.sh <disk.qcow2> <probe.py> [user] [session]}"
user="${3:-bunny}"
session="${4:-bunny}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

root_partition="${BUNNY_DESKTOP_ROOT_PARTITION:-/dev/sda4}"

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

# Confirm the session file the harness is about to select actually exists in
# the image. Selecting a session GDM cannot find makes it fall back to GNOME,
# which is the failure this whole file exists to avoid, and it would be
# invisible afterwards.
if ! guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
     : is-file "${deployment}/usr/share/wayland-sessions/${session}.desktop" \
     2>/dev/null | grep -q true; then
  echo "the image has no /usr/share/wayland-sessions/${session}.desktop" >&2
  echo "GDM would silently fall back to GNOME and the run would prove nothing" >&2
  exit 2
fi
echo "session:    ${session}.desktop is present in the image"

password_hash="$(openssl passwd -6 bunny-desktop-vm)"

cat >"${work}/bunny-desktop-probe.service" <<UNIT
[Unit]
Description=Bunny OS desktop probe (injected by the harness, not shipped)
After=graphical.target
Wants=graphical.target

[Service]
Type=oneshot
Environment=BUNNY_PROBE_USER=${user}
# The probe waits for GNOME Shell to answer on its own; this is only the
# delay before it starts asking, so a cold llvmpipe boot is not polled from
# the first second of the graphical target.
ExecStartPre=/usr/bin/sleep 45
ExecStart=/usr/bin/python3 /etc/bunny-desktop-probe.py
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

# AccountsService: the session choice. Both keys, for the reason in the header.
cat >"${work}/accounts-user" <<ACCOUNTS
[User]
Session=${session}
XSession=${session}
SystemAccount=false
Icon=/var/home/${user}/.face
ACCOUNTS

commands=(
  run
  : mount "${root_partition}" /
  # -- the probe -----------------------------------------------------------
  : upload "${probe}" "${deployment}/etc/bunny-desktop-probe.py"
  : chmod 0755 "${deployment}/etc/bunny-desktop-probe.py"
  : upload "${work}/bunny-desktop-probe.service" "${deployment}/etc/systemd/system/bunny-desktop-probe.service"
  : mkdir-p "${deployment}/etc/systemd/system/graphical.target.wants"
  : ln-sf /etc/systemd/system/bunny-desktop-probe.service
          "${deployment}/etc/systemd/system/graphical.target.wants/bunny-desktop-probe.service"
  # -- autologin, into the Bunny session -----------------------------------
  : mkdir-p "${deployment}/etc/gdm"
  : upload "${work}/gdm-custom.conf" "${deployment}/etc/gdm/custom.conf"
  : mkdir-p "${stateroot}/var/lib/AccountsService/users"
  : upload "${work}/accounts-user" "${stateroot}/var/lib/AccountsService/users/${user}"
  : chmod 0600 "${stateroot}/var/lib/AccountsService/users/${user}"
  # -- linger, so the user manager starts and stays -------------------------
  : mkdir-p "${stateroot}/var/lib/systemd/linger"
  : touch "${stateroot}/var/lib/systemd/linger/${user}"
  # -- the home directory --------------------------------------------------
  : mkdir-p "${stateroot}/var/home/${user}"
  : chown 1000 1000 "${stateroot}/var/home/${user}"
  : chmod 0700 "${stateroot}/var/home/${user}"
)

{
  guestfish --ro -a "${disk}" run : mount "${root_partition}" / \
    : download "${deployment}/etc/passwd" "${work}/passwd" \
    : download "${deployment}/etc/group" "${work}/group" \
    : download "${deployment}/etc/shadow" "${work}/shadow"
} 2>/dev/null

if ! grep -q "^${user}:" "${work}/passwd"; then
  printf '%s:x:1000:1000:Bunny desktop harness user:/var/home/%s:/bin/bash\n' "${user}" "${user}" \
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

guestfish -a "${disk}" "${commands[@]}"
echo "injected: probe, ${user}, autologin into ${session}, linger"

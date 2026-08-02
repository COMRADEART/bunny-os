#!/usr/bin/env bash
# Stage 9 hypothesis material: pull the avahi-daemon journal lines out of
# the prior installed-system evidence disks (read-only; single small
# libguestfs appliance at a time).
set -u
export LIBGUESTFS_BACKEND=direct
cd /root/bunny-os
for d in qualification/installed-system/evidence/ISQ-20260801-brlapi-first-boot-00{1,2,3,5}; do
  disk="$d/work/target-disk.qcow2"
  [ -f "$disk" ] || continue
  out="/tmp/avahi-$(basename "$d")"
  rm -rf "$out"; mkdir -p "$out"
  root=$(guestfish --ro -a "$disk" run : list-filesystems 2>/dev/null | awk -F: "/ext4/ {print \$1; exit}")
  guestfish --ro -a "$disk" run : mount-ro "$root" / : \
    glob-expand "/ostree/deploy/*/var/log/journal" 2>/dev/null | while read -r j; do
      guestfish --ro -a "$disk" run : mount-ro "$root" / : copy-out "$j" "$out" 2>/dev/null
  done
  if [ -d "$out/journal" ]; then
    echo "=== $(basename "$d") ==="
    journalctl -D "$out/journal" --no-pager -o short-monotonic 2>/dev/null \
      | grep -iE "avahi" | grep -viE "Registering|Joining|New relevant|address record|Server startup|Network interface|host name|NSS support|service file|chroot|privileges|Found user|Starting Avahi|dbus-broker-launch" | head -20
  else
    echo "=== $(basename "$d") === journal extraction failed"
  fi
done

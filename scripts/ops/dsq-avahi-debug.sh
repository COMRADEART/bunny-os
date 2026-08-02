#!/usr/bin/env bash
set -u
disk=/root/bunny-os/qualification/installed-system/evidence/ISQ-20260801-brlapi-first-boot-001/work/target-disk.qcow2
guestfish --ro -a "$disk" run : list-filesystems
for dev in /dev/sda3 /dev/sda4; do
  echo "--- $dev"
  guestfish --ro -a "$disk" run : mount-ro "$dev" / : glob-expand "/ostree/deploy/*/var/log/journal" 2>&1 | head -3
done

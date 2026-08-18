#!/usr/bin/bash
# Can this builder write, or not?
#
# The Phase 5 build has been treated as blocked because Windows C: has under
# 8 GB free and WSL's ext4.vhdx cannot grow past it. But the vhdx is already
# 731.5 GB on disk while the guest reports 350 GB used -- roughly 380 GB of
# blocks that are allocated to the file and free inside the filesystem. Writing
# into those does not grow the file, and if that is what happens, the build is
# not blocked at all.
#
# The probe writes 1 GiB and stops. The caller measures C: before and after.
set -uo pipefail
PROBE=/home/bunny/p5-space-probe.bin

echo "== guest view before =="
df -h / | tail -1
echo "== writing 1 GiB =="
if dd if=/dev/zero of="${PROBE}" bs=1M count=1024 conv=fsync 2>&1 | tail -2; then
  echo "write ok"
else
  echo "WRITE FAILED"
fi
sync
ls -la "${PROBE}"
echo "== guest view after =="
df -h / | tail -1
echo "SPACE-PROBE-DONE"

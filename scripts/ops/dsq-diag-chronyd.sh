#!/usr/bin/env bash
# 20-boot diagnostic arm: chronyd ordered after authselect-apply-changes
# via a per-run overlay drop-in. Fills no matrix cell.
set -u
cd /root/bunny-os || exit 1
for i in $(seq 1 20); do
  python3 qualification/display-stack/scripts/run_boot.py \
    --cell A --diagnostic chronyd-after-authselect --sequence "$i"
done
echo diag-chronyd-complete

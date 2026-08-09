#!/usr/bin/bash
# The canonical Source gate, on the Linux reference host, as `bunny`, from ext4.
#
# Measured here and nowhere else: /mnt/c produces nine false failures and root
# produces one, both recorded in the qualification notes.
set -uo pipefail
sudo -u bunny -H bash <<'INNER'
set -uo pipefail
cd /home/bunny/bunny-os || exit 9
echo "=== candidate ==="
echo "branch: $(git rev-parse --abbrev-ref HEAD)"
echo "head:   $(git rev-parse HEAD)"
echo "clean:  [$(git status --porcelain | head -5)]"
echo "fs:     $(df -T . | tail -1)"
echo "user:   $(id -un)"
echo "=== command: python3 scripts/release.py gate --kind source ==="
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python3 scripts/release.py gate --kind source >/tmp/gate-source.out 2>&1
code=$?
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "started:  ${started}"
echo "finished: ${finished}"
echo "GATE_EXIT_CODE=${code}"
echo "=== output ==="
cat /tmp/gate-source.out
INNER

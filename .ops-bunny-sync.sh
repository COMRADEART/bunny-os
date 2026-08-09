#!/usr/bin/bash
# Sync the `bunny` ext4 checkout — the one the source gate is measured on —
# to the candidate commit, and report what it is.
set -uo pipefail
target="${1:-}"
sudo -u bunny -H bash -s "$target" <<'INNER'
set -uo pipefail
target="$1"
cd /home/bunny/bunny-os || exit 9
git remote -v
git fetch ref "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)" 2>/dev/null || true
git fetch /root/bunny-os feature/bunny-desktop-shell 2>&1 | tail -2
git reset --hard FETCH_HEAD 2>&1 | tail -1
git clean -fdx shell build/scripts tests release 2>&1 | tail -5
echo "--- head ---"
git rev-parse HEAD
git status --porcelain | head -5
echo "--- filesystem ---"
df -T . | tail -1
echo "--- user ---"
id -un
INNER

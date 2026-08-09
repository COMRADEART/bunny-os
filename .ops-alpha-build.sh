#!/usr/bin/bash
# The canonical Alpha payload build, unchanged, from the candidate commit.
exec >/root/alpha-build.log 2>&1
cd /root/bunny-os || exit 9

echo "=== Bunny OS Alpha build ==="
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "commit:  $(git rev-parse HEAD)"
echo "dirty:   [$(git status --porcelain | head -3)]"
echo "command: make build-alpha-image"
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================="

make build-alpha-image
code=$?

echo "=========================================="
echo "ALPHA_BUILD_EXIT=${code}"
echo "finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "${code}" >/root/alpha-build.exit

echo "=== artifacts ==="
find /root/bunny-os/build/out/beta -maxdepth 2 -type f \
  \( -name '*.qcow2' -o -name '*.raw' -o -name '*.iso' \) -printf '%s %p\n' | sort

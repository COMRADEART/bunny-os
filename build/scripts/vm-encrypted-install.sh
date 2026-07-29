#!/usr/bin/bash
set -euo pipefail
echo "Encrypted VM automation requires a reviewed Anaconda test configuration and protected secret channel; interactive use only." >&2
BUNNY_VM_DISK="${BUNNY_VM_DISK:-build/out/vm/phase3-encrypted.qcow2}" "${BASH:-/usr/bin/bash}" build/scripts/vm-install-smoke.sh

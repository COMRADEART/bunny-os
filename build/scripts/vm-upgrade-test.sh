#!/usr/bin/bash
set -euo pipefail
phase2="${BUNNY_PHASE2_DISK:-build/out/shell/bunny-os.qcow2}"
[[ -f "${phase2}" ]] || { echo "missing Phase 2 QCOW2: ${phase2}" >&2; exit 3; }
echo "Upgrade test requires a signed Phase 3 registry deployment and Phase 2 boot evidence; no automated mutation was attempted." >&2
exit 78

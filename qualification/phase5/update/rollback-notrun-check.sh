#!/usr/bin/bash
# Negative control for the repaired rollback harness.
#
# The same staged disk that made the old harness print
# "Rollback PASSED: the previous deployment was selected" three times. The
# repaired harness must not say that, and must classify the outcome as an
# absent capability rather than a product failure.
set -uo pipefail
export BUNNY_EVIDENCE_DIR=/home/bunny/p5-evidence/rollback-notrun
export BUNNY_ROLLBACK_MODE=deployment-rollback
export BUNNY_STABLE_CANDIDATE_DISK=/home/bunny/p5-work/stage/staged.qcow2
export BUNNY_ROLLBACK_TEST_DISK=/home/bunny/p5-work/stage/rollback-notrun.qcow2
export BUNNY_VM_TIMEOUT=420
mkdir -p "${BUNNY_EVIDENCE_DIR}"
rm -f "${BUNNY_ROLLBACK_TEST_DISK}"
cd /root/bunny-os || exit 1
bash build/scripts/vm-rollback-test.sh
status=$?
echo "EXIT=${status}"
echo "--- the json it wrote ---"
cat "${BUNNY_EVIDENCE_DIR}/rollback-deployment.json" 2>/dev/null
echo "NOTRUN-CHECK-DONE status=${status}"

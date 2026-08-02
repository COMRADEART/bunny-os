#!/usr/bin/env bash
# Stage 16 gate recalculation: run every required command, record exact
# exit codes, force nothing.
cd /root/bunny-os || exit 1
run() {
  "$@" >/tmp/gate-out.log 2>&1
  local rc=$?
  echo "exit=$rc  $*"
  tail -2 /tmp/gate-out.log | sed "s/^/    /"
}
run python3 scripts/task.py validate
run python3 scripts/task.py test
run python3 scripts/task.py test-installer
run python3 scripts/task.py test-phase5
run python3 scripts/phase7.py source-gate
run make reproducibility-gate
run make tpm-qualification-gate
run make display-stack-matrix
run make display-stack-evidence-gate
run make display-stack-reliability-gate
run make test-display-stack
run make gate-qualification-candidate
run make gate-stable-release
run make gate-oem-pilot
run make gate-enterprise-pilot
run make gate-sync-pilot

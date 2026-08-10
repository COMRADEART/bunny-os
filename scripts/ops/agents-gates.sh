#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Launch the three §24 gates as one detached systemd user unit.
#
# One unit, not three commands: a dropped client, a WSL idle-stop or a host
# sleep each kill a foreground run, and a gate that dies at iteration 87 has
# to start again from one. The unit outlives the client that started it.
#
# BUNNY_STRESS_COMMIT is passed explicitly because this worktree is a copy
# with no .git of its own — without it the harness would read whatever
# repository happens to be above it and stamp 100 iterations with the wrong
# commit, which is the one thing the evidence cannot survive.
set -euo pipefail

WORKTREE="${WORKTREE:-/home/bunny/agents-work}"
EVIDENCE="${EVIDENCE:-/home/bunny/agents-evidence}"
UNIT="${UNIT:-agent-gates}"
COMMIT="${1:?usage: agents-gates.sh <commit-sha> [start|status|log]}"
ACTION="${2:-start}"

case "$ACTION" in
  start)
    mkdir -p "$EVIDENCE"
    systemctl --user reset-failed "$UNIT.service" 2>/dev/null || true
    systemd-run --user --unit="$UNIT" \
      --setenv=BUNNY_STRESS_COMMIT="$COMMIT" \
      --setenv=EVIDENCE="$EVIDENCE" \
      --setenv=WORKTREE="$WORKTREE" \
      --working-directory="$WORKTREE" \
      /bin/bash "$WORKTREE/scripts/ops/agents-run.sh" gates
    echo "launched $UNIT for commit $COMMIT"
    ;;
  status)
    systemctl --user is-active "$UNIT.service" || true
    systemctl --user show "$UNIT.service" -p Result -p ExecMainStatus || true
    ;;
  log)
    tail -n "${3:-40}" "$EVIDENCE/gates.log" 2>/dev/null || echo "no transcript yet"
    ;;
  *)
    echo "usage: agents-gates.sh <commit-sha> [start|status|log]" >&2
    exit 64
    ;;
esac

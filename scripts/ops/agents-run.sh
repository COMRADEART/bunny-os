#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run one agent-provider step on the Linux reference target and write its
# JSON where the collector expects it. A file, not an inline command: the
# harness that invokes this mangles $VAR and $(...) on the way through.
set -euo pipefail

WORKTREE="${WORKTREE:-/home/bunny/agents-work}"
EVIDENCE="${EVIDENCE:-/home/bunny/agents-evidence}"
PYTHON="${PYTHON:-python3}"

mkdir -p "$EVIDENCE"
cd "$WORKTREE"

case "${1:-}" in
  health)
    $PYTHON tools/bunny-os/bin/bunny-os --json companion agents-health \
      > "$EVIDENCE/health.json"
    $PYTHON scripts/ops/agents-report.py health "$EVIDENCE/health.json"
    ;;

  suite)
    $PYTHON -m unittest discover -s tests/companion -t . 2>&1 \
      | tail -40 | tee "$EVIDENCE/linux-suite.log"
    ;;

  slice)
    $PYTHON tools/bunny-os/bin/bunny-os --json companion run-agent-slice \
      > "$EVIDENCE/slice.json"
    $PYTHON scripts/ops/agents-report.py slice "$EVIDENCE/slice.json"
    ;;

  measure)
    $PYTHON scripts/agent_measure.py \
      --generations "${GENERATIONS:-10}" \
      --cancellations "${CANCELLATIONS:-5}" \
      --output "$EVIDENCE/agent-measurements.json"
    $PYTHON scripts/ops/agents-report.py measurements "$EVIDENCE/agent-measurements.json"
    ;;

  gate)
    # $2 target, $3 runs, $4 output name
    target="$2"; runs="$3"; name="$4"
    $PYTHON scripts/companion_stress.py \
      --target "$target" --runs "$runs" \
      --output "$EVIDENCE/$name" --json > /dev/null
    $PYTHON scripts/ops/agents-report.py gate "$EVIDENCE/$name"
    ;;

  gates)
    # All three, sequentially, on one commit, with a transcript. Run under
    # systemd-run --user so a dropped client or a WSL idle-stop cannot
    # truncate it.
    {
      echo "gates starting on commit $(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || echo "$BUNNY_STRESS_COMMIT") at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "=== gate 1: 100 provider-worker lifecycles ==="
      $PYTHON scripts/companion_stress.py --target agents --runs 100 \
        --output "$EVIDENCE/gate-agents-100.json" --verbose
      echo "gate 1 exit: $?"
      echo "=== gate 2: 50 complete companion suites ==="
      $PYTHON scripts/companion_stress.py --target suite --runs 50 \
        --output "$EVIDENCE/gate-suite-50.json" --verbose
      echo "gate 2 exit: $?"
      echo "=== gate 3: 20 installed local-provider slices ==="
      $PYTHON scripts/companion_stress.py --target agent-slice --runs 20 \
        --output "$EVIDENCE/gate-agent-slice-20.json" --verbose
      echo "gate 3 exit: $?"
      echo "gates finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } 2>&1 | tee "$EVIDENCE/gates.log"
    ;;

  *)
    echo "usage: agents-run.sh {health|suite|slice|measure|gate <target> <runs> <name>|gates}" >&2
    exit 64
    ;;
esac

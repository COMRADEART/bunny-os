#!/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# §42's gates, on one commit, in one place. A development tool, not shipped.
#
# The refusals before the first iteration each exist because a previous phase's
# gate run measured the wrong thing:
#
#  1. the checkout is at the declared commit and clean, and the commit is written
#     into every iteration through BUNNY_STRESS_COMMIT — a gate result belongs
#     to what was executed, not to what HEAD happened to be at the end;
#  2. the tree is on ext4 rather than /mnt/c, because DrvFs presents every file
#     as 0777 and the character package validator refuses an executable file in
#     a package. Correctly, and nine self-checks away from anything to do with
#     the thing under test;
#  3. the character packages are present, because a gate that ran the
#     default-character policy against an empty registry would report a hundred
#     consecutive text-only decisions and the summary would say 100/100.
#
# Usage:
#   scripts/ops/alpha-gates.sh <commit> <evidence-directory> [vm-runs] [install-runs]
#
# The VM gates are separate arguments because they cost minutes each and the
# in-process gates cost seconds. Passing 0 skips them and the collector records
# them NOT_RUN with the count that was asked for — an unrun gate must never read
# as a passed one.

set -euo pipefail

COMMIT="${1:?usage: alpha-gates.sh <commit> <evidence-directory> [vm-runs] [install-runs]}"
EVIDENCE="${2:?usage: alpha-gates.sh <commit> <evidence-directory> [vm-runs] [install-runs]}"
VM_RUNS="${3:-0}"
INSTALL_RUNS="${4:-0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

case "$ROOT" in
  /mnt/*)
    echo "refusing to run gates from $ROOT: use an ext4 copy" >&2
    exit 2
    ;;
esac

actual="$(git rev-parse HEAD)"
if [[ "$actual" != "$COMMIT"* && "$COMMIT" != "$actual"* ]]; then
  echo "refusing: HEAD is $actual, the gate was asked for $COMMIT" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing: the tree is dirty, so the gate would not belong to $COMMIT" >&2
  git status --porcelain >&2
  exit 2
fi

if ! python3 - <<'PROBE'
import sys
sys.path.insert(0, ".")
from companion.character.defaults import default_character_paths
missing = [str(p) for p in default_character_paths() if not p.is_dir()]
present = [str(p) for p in default_character_paths() if p.is_dir()]
if not present:
    print("no built-in character package is present", file=sys.stderr)
    raise SystemExit(2)
print(f"character packages: {len(present)} present")
for path in present:
    print(f"  {path}")
PROBE
then
  echo "refusing to run the Alpha gates without a character package" >&2
  exit 2
fi

mkdir -p "$EVIDENCE"
export BUNNY_STRESS_COMMIT="$COMMIT"
export PYTHONPATH="$ROOT"

echo "== gate 1: 100 consecutive companion service lifecycles =="
python3 scripts/companion_stress.py --target service --runs 100 \
  --output "$EVIDENCE/gate-service-100.json" 2>&1 | tee "$EVIDENCE/gate-service-100.log"

echo "== gate 2: 100 consecutive Alpha session-surface lifecycles =="
python3 scripts/companion_stress.py --target alpha --runs 100 \
  --output "$EVIDENCE/gate-alpha-100.json" 2>&1 | tee "$EVIDENCE/gate-alpha-100.log"

# The suite gate runs as an unprivileged user, and that is a correctness
# requirement rather than a hardening preference.
#
# tests/companion/test_store_durability.py asserts that a store in a read-only
# directory fails *before* it replaces anything. Root ignores the permission
# bits, the write succeeds, and the assertion that it should have raised fails —
# on every iteration, for a reason that has nothing to do with the code under
# test. Measured on this host at the base commit: the module fails as root and
# the whole suite passes as `bunny`.
#
# The other two gates stay as root: they exercise the service lifecycle and the
# session surfaces, neither of which asserts anything about being refused.
suite_runner=()
if [[ "$(id -u)" == "0" ]] && id -u bunny >/dev/null 2>&1; then
  echo "   (as bunny: a suite run as root cannot observe a read-only refusal)"
  chmod -R a+rX "$ROOT" 2>/dev/null || true
  chmod 0777 "$EVIDENCE" 2>/dev/null || true
  suite_runner=(runuser -u bunny -- env "BUNNY_STRESS_COMMIT=$COMMIT" "PYTHONPATH=$ROOT" "HOME=/tmp")
fi

echo "== gate 3: 50 consecutive complete companion suites =="
"${suite_runner[@]}" python3 scripts/companion_stress.py --target suite --runs 50 \
  --output "$EVIDENCE/gate-suite-50.json" 2>&1 | tee "$EVIDENCE/gate-suite-50.log"

if [[ "$VM_RUNS" -gt 0 ]]; then
  echo "== gate 4: $VM_RUNS consecutive booted VM Alpha stories =="
  for index in $(seq 1 "$VM_RUNS"); do
    label="$(printf 'vm-%03d' "$index")"
    echo "--- $label ---"
    bash build/scripts/vm-alpha-story.sh "$label" \
      2>&1 | tee "$EVIDENCE/gate-vm-${label}.log" || true
    story="build/out/beta/alpha-story/${label}/alpha-record.json"
    if [[ -f "$story" ]]; then
      cp "$story" "$EVIDENCE/gate-vm-${label}.json"
    fi
  done
else
  echo "== gate 4: booted VM Alpha stories NOT RUN (asked for 0) =="
fi

if [[ "$INSTALL_RUNS" -gt 0 ]]; then
  echo "== gate 5: $INSTALL_RUNS consecutive install -> boot -> first-run stories =="
  for index in $(seq 1 "$INSTALL_RUNS"); do
    echo "--- install-$index ---"
    bash build/scripts/vm-install-smoke.sh 2>&1 \
      | tee "$EVIDENCE/gate-install-$(printf '%03d' "$index").log" || true
  done
else
  echo "== gate 5: install stories NOT RUN (asked for 0) =="
fi

python3 scripts/ops/alpha-collect.py \
  --evidence "$EVIDENCE" \
  --commit "$COMMIT" \
  --vm-runs "$VM_RUNS" \
  --install-runs "$INSTALL_RUNS"

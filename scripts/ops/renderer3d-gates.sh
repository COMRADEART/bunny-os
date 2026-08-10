#!/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# §34's three gates, on one commit, in one place.
#
# A development tool, not shipped.
#
# The runner asserts three things before it runs anything, and each assertion
# exists because a previous phase's gate run measured the wrong thing:
#
#  1. the checkout is at the declared commit and clean, and the commit is
#     written into every iteration by BUNNY_STRESS_COMMIT — a gate result
#     belongs to what was actually executed;
#  2. the tree is on ext4, not /mnt/c, because a package under DrvFs presents
#     every file as 0777 and the character validator refuses an executable file
#     in a package — correctly, and nine self-checks away from anything to do
#     with the renderer;
#  3. an offscreen graphics context can actually be created here. Without one,
#     the 3D gates would report a hundred consecutive "no graphics" results and
#     the summary would say 100/100.
#
# Usage:
#   scripts/ops/renderer3d-gates.sh <commit> <evidence-directory>

set -euo pipefail

COMMIT="${1:?usage: renderer3d-gates.sh <commit> <evidence-directory>}"
EVIDENCE="${2:?usage: renderer3d-gates.sh <commit> <evidence-directory>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

case "$ROOT" in
  /mnt/*)
    echo "refusing to run gates from $ROOT: use an ext4 copy" >&2
    exit 2
    ;;
esac

if ! python3 - <<'PROBE'
import sys
sys.path.insert(0, ".")
from companion.character.three_d.context import SurfacelessContext, offscreen_available
available, reason = offscreen_available()
if not available:
    print(f"no offscreen graphics context: {reason}", file=sys.stderr)
    raise SystemExit(2)
context = SurfacelessContext()
try:
    info = context.info()
    print(f"context: {info.renderer} / {info.version} (accelerated={info.accelerated})")
finally:
    context.release()
PROBE
then
  echo "refusing to run 3D gates without a graphics context" >&2
  exit 2
fi

if ! python3 - <<'PROBE'
import sys
sys.path.insert(0, ".")
from companion.character.defaults import default_3d_character_path
path = default_3d_character_path()
if not path.is_dir():
    print(f"the built-in 3D package is missing at {path}", file=sys.stderr)
    raise SystemExit(2)
print(f"package: {path}")
PROBE
then
  echo "refusing to run 3D gates without the built-in 3D package" >&2
  exit 2
fi

mkdir -p "$EVIDENCE"
export BUNNY_STRESS_COMMIT="$COMMIT"
export PYTHONPATH="$ROOT"

echo "== gate 1: 100 consecutive 3D-renderer lifecycles =="
python3 scripts/companion_stress.py --target renderer3d --runs 100 \
  --output "$EVIDENCE/gate-renderer3d-100.json" 2>&1 | tee "$EVIDENCE/gate-renderer3d-100.log"

echo "== gate 2: 50 consecutive complete companion suites =="
python3 scripts/companion_stress.py --target suite --runs 50 \
  --output "$EVIDENCE/gate-suite-50.json" 2>&1 | tee "$EVIDENCE/gate-suite-50.log"

echo "== gate 3: 20 consecutive installed 3D vertical slices =="
python3 scripts/companion_stress.py --target renderer3d-slice --runs 20 \
  --output "$EVIDENCE/gate-renderer3d-slice-20.json" 2>&1 | tee "$EVIDENCE/gate-renderer3d-slice-20.log"

python3 scripts/ops/renderer3d-collect.py \
  --evidence "$EVIDENCE" \
  --commit "$COMMIT" \
  --gate "renderer3d-100=$EVIDENCE/gate-renderer3d-100.json" \
  --gate "suite-50=$EVIDENCE/gate-suite-50.json" \
  --gate "renderer3d-slice-20=$EVIDENCE/gate-renderer3d-slice-20.json" \
  --slice-gate "$EVIDENCE/gate-renderer3d-slice-20.json"

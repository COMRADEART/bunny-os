#!/usr/bin/bash
# Phase 6 -- prove the qualification-candidate gate did not move.
#
# The claim in PHASE6_EXTERNAL_RELEASE_GATE_CLOSURE.md is that Phase 6 changed
# what the release must demonstrate without changing what the gate tool counts.
# A claim like that should not rest on two outputs having looked the same.
#
# This checks out the pre-Phase-6 commit and the Phase 6 commit into separate
# clones, runs the gate in each, and diffs. Run inside WSL: the Windows path
# limit cannot hold a second checkout of this repository.
set -uo pipefail

BEFORE_COMMIT="${1:?the pre-phase-6 commit must be named}"
AFTER_COMMIT="${2:?the phase 6 commit must be named}"
SOURCE=/mnt/c/Users/allam/Documents/new/bunny-os
WORK=/home/bunny/p6-gatecheck
OUT=/home/bunny/p6-evidence/gates

mkdir -p "$OUT" "$WORK"
git config --global --add safe.directory "$SOURCE" 2>/dev/null

for pair in "before:$BEFORE_COMMIT" "after:$AFTER_COMMIT"; do
  name="${pair%%:*}"
  commit="${pair##*:}"
  target="$WORK/$name"
  rm -rf "$target"
  git clone --quiet --no-checkout "$SOURCE" "$target" || exit 3
  git -C "$target" checkout --quiet --detach "$commit" || exit 3
  actual=$(git -C "$target" rev-parse HEAD)
  echo "$name: asked for $commit, checked out $actual"
  case "$actual" in
    "$commit"*) ;;
    *) echo "  COMMIT ASSERTION FAILED"; exit 4 ;;
  esac
  ( cd "$target" && python3 scripts/release.py gate --kind qualification-candidate ) \
      > "$OUT/gate-$name.txt" 2>&1
  echo "  gate exit: $?"
done

echo
echo "=== sha256 of each gate output ==="
sha256sum "$OUT/gate-before.txt" "$OUT/gate-after.txt"

echo
echo "=== diff ==="
if diff -u "$OUT/gate-before.txt" "$OUT/gate-after.txt"; then
  echo "IDENTICAL -- the gate did not move"
  result=0
else
  echo "THE GATE MOVED -- the report's claim is false and must be corrected"
  result=1
fi

echo
echo "=== negative control: does this check notice a difference at all? ==="
# Compare the before output against a deliberately altered copy. If diff reports
# nothing here, the comparison above proved nothing.
sed 's/BLOCKED NOT_RUN                  Update matrix passed/ok      PASS                     Update matrix passed/' \
    "$OUT/gate-before.txt" > "$OUT/gate-tampered.txt"
if diff -q "$OUT/gate-before.txt" "$OUT/gate-tampered.txt" >/dev/null; then
  echo "CONTROL FAILED -- the comparison cannot detect a changed row"
  result=1
else
  echo "control OK -- a single flipped row is detected"
fi

exit "$result"

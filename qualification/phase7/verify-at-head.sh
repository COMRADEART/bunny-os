#!/usr/bin/bash
# Phase 7 -- certify the reference suite at the Phase 7 HEAD.
#
# Run as `bunny`, from the ext4 clone. /mnt/c produces nine false failures and
# root produces one more; see the reference-target runbook.
#
# Two assertions this script makes about itself, both of which an earlier
# version of the Phase 5 equivalent failed:
#
#   * it asserts the commit it actually checked out, because a script that
#     defaults to FETCH_HEAD can run a different branch and report clean runs
#     of code nobody changed;
#   * it asserts a test-count floor, because a collapsed discovery passes. That
#     script once reported three clean runs of 1555 tests where the suite has
#     5988.
set -uo pipefail

SUITE=/home/bunny/p7-suite
SOURCE=/mnt/c/Users/allam/Documents/new/bunny-os
OUT=/home/bunny/p7-evidence/verify
EXPECT_COMMIT="${1:?the commit to certify must be named}"
FLOOR=6030

mkdir -p "$OUT"

# One run at a time, or the record is worthless.
#
# Two invocations were started against different commits, both truncated and
# appended to the same verify.log, and the result was a log carrying one
# commit's header and the other's test output. It was caught because the
# per-run lines did not add up -- but a contaminated log that happens to look
# consistent is exactly the artefact this project keeps finding.
#
# The lock is not politeness. A second run must FAIL, loudly, rather than
# quietly interleave.
LOCK="$OUT/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "REFUSED: another certification run holds $LOCK" >&2
  echo "  Two runs sharing one log produce a record of neither." >&2
  exit 6
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# A distinct log per commit, so a later run can never overwrite an earlier
# one's record even if the lock is removed by hand.
LOG="$OUT/verify-${1:-unknown}.log"
: > "$LOG"

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

say "=== Phase 7 reference-suite certification ==="
say "started  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "expected commit: $EXPECT_COMMIT"
say "user: $(id -un)   suite: $SUITE   fs: $(findmnt -no FSTYPE "$(dirname "$SUITE")")"

git config --global --add safe.directory "$SUITE" 2>/dev/null
git config --global --add safe.directory "$SOURCE" 2>/dev/null

if [ ! -d "$SUITE/.git" ]; then
  say "cloning from the working tree"
  git clone --quiet "$SOURCE" "$SUITE" || { say "CLONE FAILED"; exit 3; }
fi

git -C "$SUITE" fetch --quiet "$SOURCE" 2>&1 | tee -a "$LOG"
git -C "$SUITE" checkout --quiet --detach "$EXPECT_COMMIT" 2>&1 | tee -a "$LOG" || {
  say "CHECKOUT FAILED -- the named commit is not reachable"; exit 3; }

ACTUAL=$(git -C "$SUITE" rev-parse HEAD)
say "checked out: $ACTUAL"
case "$ACTUAL" in
  "$EXPECT_COMMIT"*) say "commit assertion: OK" ;;
  *) say "commit assertion: FAILED -- expected $EXPECT_COMMIT, got $ACTUAL"; exit 4 ;;
esac

DISCOVERED=$(cd "$SUITE" && python3 -c "
import unittest
print(unittest.defaultTestLoader.discover(start_dir='tests', top_level_dir='.').countTestCases())
" 2>>"$LOG")
say "discovered tests: $DISCOVERED"
if [ -z "$DISCOVERED" ] || [ "$DISCOVERED" -lt "$FLOOR" ]; then
  say "test-count floor FAILED -- discovered $DISCOVERED, floor $FLOOR"
  say "a collapsed discovery passes; that is what this floor exists to catch"
  exit 5
fi
say "test-count floor: OK ($DISCOVERED >= $FLOOR)"

say ""
say "--- run 1 of 2: full reference suite ---"
( cd "$SUITE" && python3 -m unittest discover -s tests -t . 2>&1 ) | tail -40 | tee -a "$LOG"
RUN1=${PIPESTATUS[0]}
say "run 1 exit: $RUN1"

say ""
say "--- run 2 of 2: full reference suite ---"
( cd "$SUITE" && python3 -m unittest discover -s tests -t . 2>&1 ) | tail -40 | tee -a "$LOG"
RUN2=${PIPESTATUS[0]}
say "run 2 exit: $RUN2"

say ""
say "--- installer sub-suite ---"
( cd "$SUITE" && python3 -m unittest discover -s tests/installer -t . 2>&1 ) | tail -10 | tee -a "$LOG"

say ""
say "=== finished $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
say "commit=$ACTUAL discovered=$DISCOVERED run1=$RUN1 run2=$RUN2"
touch "$OUT/.done-$ACTUAL"

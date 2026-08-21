#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Negative control for the Phase 7 frozen-evidence guard.
#
# Phase 6's lesson, applied to the check that encodes it: the guard's failure
# branch must be observed firing on the real record, not assumed from the
# constructed-tree unit controls. This script mutates one real historical
# evidence file, watches the guard fail, restores the file, stages one new
# file under a frozen tree, watches the guard fail again, cleans up, and
# requires the guard to pass at the end. Any expectation not met exits 1.
#
# The mutation is transient and restored with `git restore` / `git rm
# --cached`; the script refuses to start unless the two paths it touches are
# clean, so it can never destroy a real change.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${root}" || exit 1

victim="qualification/phase5/update/rollback-boot-parity.json"
planted="qualification/phase6/negative-control-planted.tmp"

fail() { echo "CONTROL FAILED: $*" >&2; exit 1; }

[[ -z "$(git status --porcelain -- "${victim}" "${planted}")" ]] \
  || fail "the paths this control touches are not clean; refusing to start"

run_guard() {
  python -m unittest tests.release.test_frozen_evidence >/dev/null 2>&1
}

echo "== 1. untouched tree: the guard must pass =="
run_guard || fail "the guard failed on an untouched tree"
echo "   PASS"

echo "== 2. one byte appended to ${victim}: the guard must fail =="
printf '\n' >> "${victim}"
if run_guard; then
  git restore -- "${victim}"
  fail "the guard passed while a frozen file was modified"
fi
echo "   the guard failed, as required"
git restore -- "${victim}"

echo "== 3. a file staged under a frozen tree: the guard must fail =="
printf 'planted by the negative control\n' > "${planted}"
git add -- "${planted}"
if run_guard; then
  git rm --cached --quiet -- "${planted}"; rm -f "${planted}"
  fail "the guard passed while a file was staged into a frozen tree"
fi
echo "   the guard failed, as required"
git rm --cached --quiet -- "${planted}"
rm -f "${planted}"

echo "== 4. restored tree: the guard must pass again =="
run_guard || fail "the guard did not recover after restoration"
echo "   PASS"

echo
echo "NEGATIVE CONTROL PASSED: modify -> FAIL, add -> FAIL, restore -> PASS"

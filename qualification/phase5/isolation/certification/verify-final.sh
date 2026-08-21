#!/usr/bin/bash
# Re-certify the reference suite at a named commit.
#
# §8: do not declare the suite reliable after one passing run.
#
# The first version of this script took `git checkout "${BUNNY_VERIFY_REF:-FETCH_HEAD}"`
# and its `git fetch origin` pointed at a clone that had not moved, so FETCH_HEAD
# resolved to a commit from a different branch entirely. It then ran happily and
# reported
#
#   suite run 1: rc=0 failures=0 | Ran 1555 tests Ran 60 tests
#
# three times. Three clean runs of the wrong tree. Nothing in the output said
# so, because "0 failures" looks the same whatever it ran.
#
# Two guards, and they are the general lesson rather than a patch:
#
#   * the commit is required, not defaulted, and the checkout is *asserted*
#     afterwards -- a script that quietly runs something other than what it was
#     asked to run is worse than one that fails;
#   * the number of tests has a floor. A discovery that collapses -- an import
#     error in a package `__init__`, a renamed directory -- silently shrinks the
#     suite, and a shrunken suite passes. 1555 against 5988 is not a detail.
set -uo pipefail
SUITE=/home/bunny/p5-suite
OUT=/home/bunny/p5-evidence/verify-final
runs="${1:-3}"
ref="${BUNNY_VERIFY_REF:-}"
floor="${BUNNY_TEST_FLOOR:-5900}"
installer_floor="${BUNNY_INSTALLER_TEST_FLOOR:-170}"
mkdir -p "${OUT}"

[[ -n "${ref}" ]] || { echo "BUNNY_VERIFY_REF must name the commit to certify" >&2; exit 3; }

cd "${SUITE}" || exit 1
git fetch winsrc --quiet || { echo "fetch failed" >&2; exit 3; }
git checkout -q "${ref}" || { echo "checkout of ${ref} failed" >&2; exit 3; }

head="$(git rev-parse HEAD)"
wanted="$(git rev-parse "${ref}")"
if [[ "${head}" != "${wanted}" ]]; then
  echo "the worktree is at ${head}, not ${wanted}" >&2
  exit 3
fi
dirty="$(git status --porcelain | wc -l)"
echo "suite at: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
echo "worktree modifications: ${dirty}"
if (( dirty != 0 )); then
  echo "the worktree is not clean; a certification of a modified tree certifies nothing" >&2
  exit 3
fi

echo
echo "=== shellcheck and the rest of tests/portability ==="
python3 -m unittest discover -s tests/portability -t . >"${OUT}/portability.log" 2>&1
portability=$?
echo "portability rc=${portability} $(grep -hoE '^Ran [0-9]+ tests' "${OUT}/portability.log" | tail -1)"
grep -E "^(FAIL|ERROR): " "${OUT}/portability.log" | sed 's/ (.*//' | sort | uniq -c

echo
echo "=== the whole reference suite, x${runs} ==="
clean=0
for i in $(seq 1 "${runs}"); do
  python3 scripts/task.py test >"${OUT}/suite-${i}.log" 2>&1
  rc=$?
  mapfile -t counts < <(grep -hoE "^Ran [0-9]+ tests" "${OUT}/suite-${i}.log" | grep -oE '[0-9]+')
  main="${counts[0]:-0}"
  installer="${counts[1]:-0}"
  fails=$(grep -cE "^(FAIL|ERROR): " "${OUT}/suite-${i}.log")
  verdict="clean"
  if (( fails > 0 || rc != 0 )); then
    verdict="FAILURES"
  elif (( main < floor || installer < installer_floor )); then
    verdict="SUSPECT: discovered ${main}/${installer}, floor ${floor}/${installer_floor}"
  else
    clean=$(( clean + 1 ))
  fi
  echo "suite run ${i}: rc=${rc} failures=${fails} tests=${main}+${installer} -> ${verdict}"
  if (( fails > 0 )); then
    grep -E "^(FAIL|ERROR): " "${OUT}/suite-${i}.log" | sed 's/ (.*//' | sort | uniq -c
  fi
done

echo
echo "clean runs: ${clean}/${runs} at ${head}"
echo "VERIFY-FINAL-DONE clean=${clean} of ${runs}"
[[ "${clean}" -eq "${runs}" && "${portability}" -eq 0 ]]

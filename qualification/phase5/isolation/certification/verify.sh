#!/usr/bin/bash
# Verify the isolation fix, and certify the suite under §8.
#
# Two things, in order.
#
# 1. The mechanism, on the reference target. Read /proc/pressure/memory before
#    and after a package run, so the claim "the suite crosses the PSI threshold"
#    is a measurement on this host rather than an inference from Windows.
#
# 2. §8: run the whole reference suite repeatedly. Do not declare it reliable
#    after one passing run.
set -uo pipefail
SUITE=/home/bunny/p5-suite
OUT=/home/bunny/p5-evidence/verify
runs="${1:-5}"

mkdir -p "${OUT}"
cd "${SUITE}" || exit 1

echo "=== memory pressure on this host, before anything ==="
cat /proc/pressure/memory | tee "${OUT}/psi-before.txt"

echo
echo "=== tests/companion x8, with PSI sampled after each ==="
for i in $(seq 1 8); do
  python3 -m unittest discover -s tests/companion -t . >"${OUT}/companion-${i}.log" 2>&1
  rc=$?
  psi=$(awk '/^some/{print $2}' /proc/pressure/memory)
  slice=$(grep -cE "VerticalSliceAndPerformance|IncidentalRendererFault" "${OUT}/companion-${i}.log")
  echo "companion run ${i}: rc=${rc} sliceFailures=${slice} psi_${psi}"
done

echo
echo "=== §8: the whole reference suite, x${runs} ==="
for i in $(seq 1 "${runs}"); do
  python3 scripts/task.py test >"${OUT}/suite-${i}.log" 2>&1
  rc=$?
  ran=$(grep -hoE "^Ran [0-9]+ tests" "${OUT}/suite-${i}.log" | tail -2 | tr '\n' ' ')
  fails=$(grep -cE "^(FAIL|ERROR): " "${OUT}/suite-${i}.log")
  echo "suite run ${i}: rc=${rc} failures=${fails} | ${ran}"
  if (( fails > 0 )); then
    grep -E "^(FAIL|ERROR): " "${OUT}/suite-${i}.log" | sed 's/ (.*//' | sort | uniq -c
  fi
done

echo "VERIFY-DONE"

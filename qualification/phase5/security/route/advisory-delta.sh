#!/usr/bin/bash
# Ask the vulnerability database what it now says about the seven advisories
# that made Phase 4's Critical count.
#
# The Phase 5 re-scan reports none of them. The SBOM proves the package they
# were reported against -- golang.org/x/crypto v0.46.0 -- is still in the
# candidate, in /usr/bin/skopeo. So the change is in the data, not the image,
# and the database is the place to read the change.
#
# `grype db search` is a read of the cached database. No image, no export, no
# disk.
#
# Run as root: the database the candidate scan used is /root/.cache/grype, and
# the first attempt at this ran as `bunny`, found no database, and printed
# "NO ROWS" for every advisory -- an instrument answering "I could not look"
# in the same words it uses for "there is nothing there". The exit status is
# checked here for that reason.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-delta
mkdir -p "${OUT}"
chmod 777 "${OUT}" 2>/dev/null

command -v grype >/dev/null || { echo "grype is required" >&2; exit 3; }

echo "== database in use =="
grype db status 2>&1 | tee "${OUT}/db-status.txt"

echo
echo "== the eight Phase 4 Criticals, as the current database describes them =="
for advisory in \
  GHSA-5cgq-3rg8-m6cv GHSA-89gr-r52h-f8rx GHSA-f5wc-c3c7-36mc \
  GHSA-jppx-rxg9-jmrx GHSA-rm3j-f69w-wqmq GHSA-vgwf-h737-ff37 \
  GHSA-x527-x647-q7gg GHSA-p77j-4mvh-x3m3
do
  echo "--- ${advisory} ---"
  if grype db search --vuln "${advisory}" -o json \
      >"${OUT}/${advisory}.json" 2>"${OUT}/${advisory}.err"; then
    python3 /home/bunny/p5-ops/advisory-summary.py "${OUT}/${advisory}.json"
  else
    echo "    SEARCH FAILED: $(head -2 "${OUT}/${advisory}.err" | tr '\n' ' ')"
  fi
done

echo
echo "== every advisory the database holds against golang.org/x/crypto =="
if grype db search --pkg golang.org/x/crypto -o json \
    >"${OUT}/pkg-x-crypto.json" 2>"${OUT}/pkg-x-crypto.err"; then
  python3 /home/bunny/p5-ops/advisory-summary.py "${OUT}/pkg-x-crypto.json" --package
else
  echo "    SEARCH FAILED: $(head -2 "${OUT}/pkg-x-crypto.err" | tr '\n' ' ')"
fi

echo "ADVISORY-DELTA-DONE"

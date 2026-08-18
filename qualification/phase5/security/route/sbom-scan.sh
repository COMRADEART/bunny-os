#!/usr/bin/bash
# Scan the candidate through its own SBOM.
#
# The `dir:` scan of the mounted image missed all seven Critical
# `golang.org/x/crypto` findings. The control proved the matcher is fine: the
# same package records, lifted out of the candidate's own SBOM, produce all
# seven. So the defect is in the `dir:` route, and the SBOM route is the one to
# trust -- it is also the route an independent reviewer would use, because the
# SBOM is what §18 says to hand them.
#
# Reads a file that already exists. No disk.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-sbom
SBOM=/home/bunny/p5-evidence/sbom/candidate.spdx.json
mkdir -p "${OUT}"

command -v grype >/dev/null || { echo "grype is required" >&2; exit 3; }
[[ -f "${SBOM}" ]] || { echo "SBOM missing: ${SBOM}" >&2; exit 2; }

echo "== the SBOM this scans =="
sha256sum "${SBOM}" | tee "${OUT}/sbom.sha256"

echo
echo "== free space before =="
df -h / | tail -1

echo
echo "== --only-fixed, the same scope build/scripts/security-scan.sh uses =="
grype "sbom:${SBOM}" --only-fixed --output json \
  >"${OUT}/sbom-fixed.json" 2>"${OUT}/sbom-fixed.err"
echo "exit=$?"
tail -3 "${OUT}/sbom-fixed.err"

echo
echo "== unfiltered =="
grype "sbom:${SBOM}" --output json \
  >"${OUT}/sbom-all.json" 2>"${OUT}/sbom-all.err"
echo "exit=$?"
tail -3 "${OUT}/sbom-all.err"

echo
echo "== free space after =="
df -h / | tail -1

python3 /home/bunny/p5-ops/scan-summary.py \
  "${OUT}/sbom-fixed.json" "${OUT}/sbom-all.json"

echo "SBOM-SCAN-DONE"

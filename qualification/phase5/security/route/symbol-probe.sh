#!/usr/bin/bash
# Isolate the mechanism to one binary.
#
# The filesystem scan emitted no "none carry function symbols" warning; the
# SBOM scan did. That points at grype matching Go findings at *function*
# granularity when it can read the binary, and falling back to *module*
# granularity when it is handed an SBOM.
#
# /usr/bin/skopeo is the whole disagreement: it carries golang.org/x/crypto
# v0.46.0, the database says seven Critical advisories apply to <0.52.0, the
# SBOM scan reports all seven and the filesystem scan reports none.
#
# Scanning one file is seconds and no disk.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-symbol
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
mkdir -p "${OUT}"

command -v grype >/dev/null || { echo "grype is required" >&2; exit 3; }

echo "== does grype have a knob for this? =="
grype config 2>/dev/null | grep -inE "symbol|golang|go-" | head -20
echo "--- help ---"
grype --help 2>&1 | grep -inE "symbol" | head -10

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5
echo "mounted at ${mountpoint}"

echo
echo "== syft on the single binary: does it capture symbols? =="
syft "file:${mountpoint}/usr/bin/skopeo" -o json \
  >"${OUT}/skopeo.syft.json" 2>"${OUT}/skopeo.syft.err"
echo "syft exit=$?"
tail -2 "${OUT}/skopeo.syft.err"

echo
echo "== grype on the single binary =="
grype "file:${mountpoint}/usr/bin/skopeo" --output json \
  >"${OUT}/skopeo.binary.json" 2>"${OUT}/skopeo.binary.err"
echo "grype exit=$?"
tail -2 "${OUT}/skopeo.binary.err"

echo
echo "== grype on the SBOM of that same binary =="
grype "sbom:${OUT}/skopeo.syft.json" --output json \
  >"${OUT}/skopeo.sbom.json" 2>"${OUT}/skopeo.sbom.err"
echo "grype exit=$?"
tail -2 "${OUT}/skopeo.sbom.err"

python3 /home/bunny/p5-ops/scan-summary.py \
  "${OUT}/skopeo.binary.json" "${OUT}/skopeo.sbom.json"

echo "SYMBOL-PROBE-DONE"

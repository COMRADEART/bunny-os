#!/usr/bin/bash
set -euo pipefail

profile="${1:-developer}"
output="build/out/${profile}/security"
archive="build/out/${profile}/bunny-os.oci.tar"
command -v grype >/dev/null 2>&1 || { echo "grype is required" >&2; exit 3; }
[[ -f "${archive}" ]] || { echo "OCI archive is required: ${archive}" >&2; exit 2; }
mkdir -p "${output}"
grype "oci-archive:${archive}" --fail-on high --only-fixed --output json > "${output}/grype.json"

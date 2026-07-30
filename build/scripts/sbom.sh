#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

profile="${1:-developer}"
output="build/out/${profile}/sbom"
archive="build/out/${profile}/bunny-os.oci.tar"
command -v syft >/dev/null 2>&1 || { echo "syft is required" >&2; exit 3; }
[[ -f "${archive}" ]] || { echo "OCI archive is required: ${archive}" >&2; exit 2; }
mkdir -p "${output}"
syft "oci-archive:${archive}" -o "cyclonedx-json=${output}/bunny-os.cdx.json" -o "spdx-json=${output}/bunny-os.spdx.json"
python3 -m json.tool "${output}/bunny-os.cdx.json" >/dev/null
python3 -m json.tool "${output}/bunny-os.spdx.json" >/dev/null
sha256sum "${output}/bunny-os.cdx.json" "${output}/bunny-os.spdx.json" > "${output}/SHA256SUMS"
